import streamlit as st
import datetime
import io
import xlsxwriter
import requests
from icalendar import Calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import traceback
import time

# --- CONFIGURAZIONE GLOBALE ---
st.set_page_config(page_title="Gestionale Galbino", page_icon="🏰", layout="wide")

# ==============================================================================
# SEZIONE 0: SISTEMA DI AUTENTICAZIONE
# ==============================================================================

def check_login():
    if 'authentication_status' not in st.session_state:
        st.session_state['authentication_status'] = False
        st.session_state['user_role'] = None
        st.session_state['user_name'] = None

    if st.session_state['authentication_status']:
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🔐 Accesso Gestionale")
        username = st.text_input("Utente")
        password = st.text_input("Password", type="password")
        
        if st.button("ACCEDI", type="primary", use_container_width=True):
            creds = st.secrets.get("credentials")
            if creds and username in creds and creds[username]["password"] == password:
                st.session_state['authentication_status'] = True
                st.session_state['user_role'] = creds[username]["role"]
                st.session_state['user_name'] = creds[username]["name"]
                st.rerun()
            else:
                st.error("Utente o password non corretti.")
    return False

def logout():
    st.session_state['authentication_status'] = False
    st.session_state['user_role'] = None
    st.session_state['user_name'] = None
    st.rerun()

# ==============================================================================
# SEZIONE 1: FUNZIONI COMUNI
# ==============================================================================

def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    return gspread.authorize(creds)

# ==============================================================================
# SEZIONE 2: APP PREVENTIVI AFFITTO
# ==============================================================================

def app_preventivi_affitto():
    st.title(f"🏰 Preventivi Affitto (Utente: {st.session_state['user_name']})")
    
    LODGIFY_ICAL_URL = "https://www.lodgify.com/5bab045e-30ec-4edf-aabf-970d352e7549.ics"
    
    LISTA_SERVIZI = [
        ("Wedding Fee", 30), ("Breakfast", 20), ("Lunch", 45), ("Dinner", 75),
        ("BBQ", 60), ("Cooking Class", 120), ("Wine Tasting", 50),
        ("Truffle Hunting", 150), ("Ebike Tour", 80), ("Transfer", 150),
        ("Prima Spesa", 0), ("Extra Cleaning", 200)
    ]

    RATES = {
        "Alta": {"Base": 1700, "We": 2635, "CapienzaBase": 16, "Max": 24},
        "Media": {"Base": 1275, "We": 1870, "CapienzaBase": 16, "Max": 24},
        "Bassa": {"Base": 1020, "We": 1020, "CapienzaBase": 10, "Max": 22}
    }
    COSTO_EXTRA_PAX = 100
    SCONTO_LUNGA_DURATA = 0.15
    MIN_STAY = 3

    def calcola_pasqua(anno):
        a, b, c = anno % 19, anno // 100, anno % 100
        d, e = b // 4, b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = c // 4, c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        mese = (h + l - 7 * m + 114) // 31
        giorno = ((h + l - 7 * m + 114) % 31) + 1
        return datetime.date(anno, mese, giorno)

    def get_stagione(data):
        anno = data.year
        dt_pasqua = calcola_pasqua(anno)
        if (dt_pasqua - datetime.timedelta(days=5)) <= data <= (dt_pasqua + datetime.timedelta(days=2)): return "Media"
        if datetime.date(anno, 12, 20) <= data <= datetime.date(anno, 12, 31) or datetime.date(anno, 1, 1) <= data <= datetime.date(anno, 1, 6): return "Media"
        maggio_31 = datetime.date(anno, 5, 31)
        inizio_alta = maggio_31 - datetime.timedelta(days=(maggio_31.weekday() - 3) % 7)
        luglio_31 = datetime.date(anno, 7, 31)
        ultimo_lun_luglio = luglio_31 - datetime.timedelta(days=luglio_31.weekday())
        fine_alta = ultimo_lun_luglio - datetime.timedelta(days=1)
        if inizio_alta <= data <= fine_alta: return "Alta"
        inizio_media_1 = datetime.date(anno, 4, 1)
        fine_media_2 = datetime.date(anno, 8, 31)
        inizio_media_3 = datetime.date(anno, 9, 1)
        primo_ott = datetime.date(anno, 10, 1)
        terza_dom_ott = primo_ott + datetime.timedelta(days=(6 - primo_ott.weekday()) % 7) + datetime.timedelta(days=14)
        if (inizio_media_1 <= data < inizio_alta) or (ultimo_lun_luglio <= data <= fine_media_2) or (inizio_media_3 <= data <= terza_dom_ott): return "Media"
        return "Bassa"

    def calcola_soggiorno_netto(data_arrivo, notti, ospiti):
        tot, log = 0, []
        for i in range(notti):
            giorno = data_arrivo + datetime.timedelta(days=i)
            stg = get_stagione(giorno)
            tipo = "We" if giorno.weekday() in [3,4,5,6] else "Base"
            tariffa = RATES[stg]
            if ospiti > tariffa["Max"]: return None, f"Troppi ospiti per {stg} (Max {tariffa['Max']})"
            prezzo = tariffa[tipo] + (max(0, ospiti - tariffa["CapienzaBase"]) * COSTO_EXTRA_PAX)
            tot += prezzo
            log.append(f"{giorno.strftime('%d/%m')}: €{prezzo}")
        return tot, log

    def check_availability(checkin, checkout, url):
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            cal = Calendar.from_ical(r.content)
            checkin_dt = checkin
            checkout_dt = checkout
            is_occupied = False
            msg_occupato = ""
            for component in cal.walk():
                if component.name == "VEVENT":
                    dtstart = component.get('dtstart').dt
                    dtend = component.get('dtend').dt
                    if isinstance(dtstart, datetime.datetime): dtstart = dtstart.date()
                    if isinstance(dtend, datetime.datetime): dtend = dtend.date()
                    if (checkin_dt < dtend) and (checkout_dt > dtstart):
                        is_occupied = True
                        msg_occupato = f"Occupato: {dtstart.strftime('%d/%m')} - {dtend.strftime('%d/%m')}"
            if is_occupied: return False, msg_occupato
            else: return True, "Libero"
        except Exception as e: return None, f"Errore: {e}"

    def salva_su_google_sheets(riga_dati):
        try:
            client = get_gspread_client()
            sheet = client.open_by_url(st.secrets["spreadsheet_url"]).sheet1
            sheet.append_row(riga_dati)
            return True
        except Exception as e:
            st.error(f"Errore DB Affitti: {e}")
            return False
            
    def generate_excel(autore, canale, cliente, checkin, checkout, notti, ospiti, affitto_finale, pulizie, dettagli_servizi, sconto, totale_gen, costo_medio, note):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Preventivo")
        bold = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#D3D3D3'})
        merge_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#FFD700'}) 
        currency = workbook.add_format({'num_format': '#,##0.00 €', 'border': 1, 'align': 'center'})
        normal = workbook.add_format({'border': 1, 'align': 'center'})
        
        worksheet.set_column('A:B', 15); worksheet.set_column('C:C', 12); worksheet.set_column('D:D', 30)
        worksheet.set_column('E:F', 13); worksheet.set_column('G:H', 8); worksheet.set_column('I:K', 16)
        
        general_headers = ["Autore", "Canale", "Data Prev", "Cliente", "CheckIn", "CheckOut", "Notti", "Ospiti", "Affitto", "Media/Notte", "Pulizie"]
        worksheet.write_row('A1', general_headers, bold)
        worksheet.write_row('A2', [autore, canale, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti], normal)
        worksheet.write('I2', affitto_finale, currency); worksheet.write('J2', costo_medio, currency); worksheet.write('K2', pulizie, currency)

        col_idx = 11 
        for nome, _ in LISTA_SERVIZI:
            worksheet.merge_range(0, col_idx, 0, col_idx+3, nome.upper(), merge_format)
            worksheet.write_row(1, col_idx, ["€ Unit", "Pax", "Qta", "Totale"], bold)
            if nome in dettagli_servizi:
                d = dettagli_servizi[nome]
                worksheet.write(2, col_idx, d['p_unit'], currency); worksheet.write(2, col_idx+1, d['pax'], normal)
                worksheet.write(2, col_idx+2, d['qta'], normal); worksheet.write(2, col_idx+3, d['subtotale'], currency)
            else:
                worksheet.write_row(2, col_idx, [0, 0, 0, 0], currency)
            col_idx += 4 

        col_idx += 1
        worksheet.write(0, col_idx, "SCONTO", bold); worksheet.write(2, col_idx, sconto, currency)
        worksheet.write(0, col_idx+1, "TOTALE", bold); worksheet.write(2, col_idx+1, totale_gen, currency)
        worksheet.write(0, col_idx+2, "NOTE", bold); worksheet.write(2, col_idx+2, note, normal)
        workbook.close()
        return output.getvalue()
    
    def download_full_db_excel():
        try:
            client = get_gspread_client()
            sheet = client.open_by_url(st.secrets["spreadsheet_url"]).sheet1
            data = sheet.get_all_values()
            if len(data) < 2: return None
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            worksheet = workbook.add_worksheet("DB Completo")
            for r, row in enumerate(data):
                for c, val in enumerate(row):
                    worksheet.write(r, c, val)
            workbook.close()
            return output.getvalue()
        except: return None

    with st.container():
        c_aut, c_can, c_cli = st.columns([1, 1, 2])
        with c_aut: 
            current_user = st.session_state.get('user_name', 'Seleziona...')
            options_auth = ["Seleziona...", "Luca", "Stefano"]
            idx = options_auth.index(current_user) if current_user in options_auth else 0
            autore = st.selectbox("Autore", options_auth, index=idx)
            
        with c_can: 
            canale = st.radio("Listino", ["Netto Galbino", "Airbnb (+15%)", "Oliver's (+20%)"], horizontal=True)
            
        with c_cli: cliente = st.text_input("Nome Cliente")
        
        c1, c2, c3 = st.columns(3)
        with c1: checkin = st.date_input("Check-In", datetime.date.today(), format="DD/MM/YYYY")
        with c2: checkout = st.date_input("Check-Out", datetime.date.today() + datetime.timedelta(days=MIN_STAY), format="DD/MM/YYYY")
        with c3: ospiti = st.number_input("Ospiti", min_value=1, value=10)

    is_free, msg = check_availability(checkin, checkout, LODGIFY_ICAL_URL)
    if is_free: st.success("✅ DATE DISPONIBILI")
    else: st.error(f"⛔ {msg}")

    notti = (checkout - checkin).days
    costo_netto_base, log_affitto = calcola_soggiorno_netto(checkin, notti, ospiti)
    affitto_calcolato = 0
    netto_reale = 0
    sconto_long = 0
    
    if notti >= MIN_STAY and costo_netto_base is not None:
        netto_reale = costo_netto_base
        if notti >= 7:
            sconto_long = costo_netto_base * SCONTO_LUNGA_DURATA
            netto_reale = costo_netto_base - sconto_long
        
        if canale == "Airbnb (+15%)": affitto_calcolato = netto_reale / 0.85
        elif canale == "Oliver's (+20%)": affitto_calcolato = netto_reale / 0.80
        else: affitto_calcolato = netto_reale
    
    st.markdown("### 🍷 Servizi")
    dettagli_servizi_excel = {}
    totale_servizi = 0
    
    for nome, prezzo_def in LISTA_SERVIZI:
        with st.expander(f"{nome}"):
            if "Wedding" in nome:
                c1, c2 = st.columns(2)
                p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
                pax = c2.number_input("Invitati", min_value=0, key=f"x_{nome}")
                qta = 1 
            elif "Truffle" in nome:
                c1, c2 = st.columns(2)
                p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
                pax = c2.number_input("Partecipanti", min_value=0, key=f"x_{nome}")
                qta = 1
            elif "Prima Spesa" in nome:
                p_unit = st.number_input(f"Costo Scontrino", value=0.0, key=f"p_{nome}"); pax=1; qta=1
            elif "Transfer" in nome or "Extra Cleaning" in nome:
                c1, c2 = st.columns(2)
                p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
                pax = 1 
                qta = c2.number_input(f"Quantità/Volte", min_value=0, key=f"q_{nome}")
            else:
                c1, c2, c3 = st.columns(3)
                p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
                pax = c2.number_input("Pax", min_value=0, key=f"x_{nome}")
                qta = c3.number_input("Qta", min_value=0, key=f"q_{nome}")
            
            if (("Prima Spesa" in nome and p_unit > 0) or (p_unit > 0 and pax > 0 and qta > 0)):
                sub = p_unit * pax * qta
                totale_servizi += sub
                dettagli_servizi_excel[nome] = {'p_unit': p_unit, 'pax': pax, 'qta': qta, 'subtotale': sub}

    st.divider()
    c_f1, c_f2 = st.columns(2)
    with c_f1: sconto = st.number_input("Sconto Manuale (€)", min_value=0.0, step=50.0)
    with c_f2: note = st.text_area("Note interne")
    
    pulizie = 600
    totale_gen = affitto_calcolato + pulizie + totale_servizi - sconto
    costo_medio = affitto_calcolato / notti if notti > 0 else 0

    st.markdown("### 💰 Preventivo Live")
    k1, k2, k3 = st.columns(3)
    k1.metric(f"Affitto ({canale})", f"€ {affitto_calcolato:,.2f}", delta=f"Tuo Netto: € {netto_reale:,.2f}")
    k2.metric("Servizi", f"€ {totale_servizi:,.2f}")
    k3.metric("TOTALE", f"€ {totale_gen:,.2f}")
    
    is_valid = True
    if autore == "Seleziona...": is_valid=False
    if notti < MIN_STAY: is_valid=False
    
    b1, b2 = st.columns(2)
    with b1:
        if st.button("☁️ SALVA SOLO CLOUD", use_container_width=True):
            if is_valid:
                riga = [autore, canale, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, affitto_calcolato, costo_medio, pulizie]
                for n, _ in LISTA_SERVIZI:
                    if n in dettagli_servizi_excel: riga.extend([dettagli_servizi_excel[n]['p_unit'], dettagli_servizi_excel[n]['pax'], dettagli_servizi_excel[n]['qta'], dettagli_servizi_excel[n]['subtotale']])
                    else: riga.extend([0,0,0,0])
                riga.extend([sconto, totale_gen, note])
                if salva_su_google_sheets(riga): st.toast("✅ Salvato!");
            else: st.error("Dati incompleti")
            
    with b2:
        if is_valid:
            excel_data = generate_excel(autore, canale, cliente, checkin, checkout, notti, ospiti, affitto_calcolato, pulizie, dettagli_servizi_excel, sconto, totale_gen, costo_medio, note)
            def callback_save():
                riga = [autore, canale, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, affitto_calcolato, costo_medio, pulizie]
                for n, _ in LISTA_SERVIZI:
                    if n in dettagli_servizi_excel: riga.extend([dettagli_servizi_excel[n]['p_unit'], dettagli_servizi_excel[n]['pax'], dettagli_servizi_excel[n]['qta'], dettagli_servizi_excel[n]['subtotale']])
                    else: riga.extend([0,0,0,0])
                riga.extend([sconto, totale_gen, note])
                salva_su_google_sheets(riga)
                st.toast("✅ Salvato e Scaricato!")
                
            st.download_button("💾 SALVA E SCARICA", excel_data, f"Prev_{cliente}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click=callback_save, type="primary", use_container_width=True)
        else:
             st.button("💾 SALVA E SCARICA", disabled=True, use_container_width=True)

    if st.session_state['user_role'] == 'admin':
        with st.expander("Admin: Gestione DB"):
            if st.button("SCARICA DATABASE AFFITTI COMPLETO"):
                db = download_full_db_excel()
                if db: st.download_button("Download DB", db, f"DB_Affitti_{datetime.date.today()}.xlsx")

# ==============================================================================
# SEZIONE 3: APP CATERING MANAGER
# ==============================================================================

def app_catering_manager():
    st.title(f"👨‍🍳 Catering Manager (Utente: {st.session_state['user_name']})")
    
    def salva_db_catering(riga):
        try:
            client = get_gspread_client()
            url = st.secrets.get("spreadsheet_url_catering", st.secrets["spreadsheet_url"])
            sheet = client.open_by_url(url).sheet1
            sheet.append_row(riga)
            return True
        except Exception as e:
            st.error(f"Errore DB Catering: {e}")
            return False

    def genera_excel_catering(cliente, data_evento, status, pax, prezzo, incasso_loc, tot_inc, fc, cost_utenze, kwh_val, p_kwh, staff_tot, tot_costi, marg_eur, marg_perc, staff_list, menu, note):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet("Catering")
        fmt_head = workbook.add_format({'bold': True, 'bg_color': '#FFD700', 'border': 1})
        fmt_curr = workbook.add_format({'num_format': '#,##0.00 €', 'border': 1})
        
        ws.write('A1', f"CATERING: {cliente}", fmt_head)
        ws.write('B1', status, fmt_head)
        
        ws.write('A3', "Incasso Totale"); ws.write('B3', tot_inc, fmt_curr)
        ws.write('A4', "Food Cost"); ws.write('B4', fc, fmt_curr)
        ws.write('A5', f"Utenze ({kwh_val} kWh * €{p_kwh})"); ws.write('B5', cost_utenze, fmt_curr)
        ws.write('A6', "Staff Totale"); ws.write('B6', staff_tot, fmt_curr)
        ws.write('A7', "COSTI TOTALI"); ws.write('B7', tot_costi, fmt_curr)
        
        ws.write('A9', "Margine €"); ws.write('B9', marg_eur, fmt_curr)
        ws.write('A10', "Margine %"); ws.write('B10', marg_perc, workbook.add_format({'num_format': '0.00%'}))
        
        ws.write('A12', "DETTAGLIO STAFF", fmt_head)
        for i, s in enumerate(staff_list): ws.write(12+i+1, 0, s)
        
        r_menu = 12+len(staff_list)+3
        ws.write(r_menu, 0, "MENU", fmt_head)
        ws.write(r_menu+1, 0, menu)
        
        workbook.close()
        return output.getvalue()

    c_status, c_cli = st.columns([1, 3])
    with c_status: status_prev = st.radio("Status", ["PREVENTIVO", "CONSUNTIVO"], horizontal=True)
    with c_cli: cliente = st.text_input("Evento / Cliente")
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: data_evento = st.date_input("Data", datetime.date.today(), format="DD/MM/YYYY")
    with c2: pax = st.number_input("Pax", 1, value=50)
    with c3: tipo = st.selectbox("Tipo", ["Buffet", "Servito", "Cocktail"])
    with c4: prezzo_pax = st.number_input("€/Pax", 0.0, value=80.0)
    
    incasso_loc = st.number_input("Incasso Extra/Location €", 0.0)
    totale_incasso = (pax * prezzo_pax) + incasso_loc
    st.metric("INCASSO PREVISTO", f"€ {totale_incasso:,.2f}")
    
    st.divider()
    st.subheader("Costi")
    
    cc1, cc2 = st.columns(2)
    with cc1: 
        food_cost = st.number_input("Food Cost Totale €", 0.0, value=500.0)
        if pax > 0: st.caption(f"Food Cost pax: € {food_cost/pax:.2f}")

    with cc2:
        st.markdown("**Utenze (Risc/Raff)**")
        c_kwh, c_pr = st.columns(2)
        kwh = c_kwh.number_input("kWh", 0.0, value=0.0)
        price_kwh = c_pr.number_input("€/kWh", 0.0, value=0.60, step=0.05)
        costo_utenze = kwh * price_kwh
        if costo_utenze > 0:
            st.caption(f"Totale Utenze: € {costo_utenze:.2f}")
    
    st.markdown("#### Personale")
    num_staff = st.number_input("N. Staff", 0, value=3)
    costo_staff_tot = 0.0
    staff_list = []
    
    if num_staff > 0:
        cols = st.columns([2,2,1,1,1])
        cols[0].write("Nome"); cols[1].write("Ruolo"); cols[2].write("Ore"); cols[3].write("€/h"); cols[4].write("Tot")
        ruoli_disponibili = ["Cameriere", "Cuoco", "Aiuto Cuoco", "Lavapiatti", "Extra"]
        for i in range(int(num_staff)):
            cc = st.columns([2,2,1,1,1])
            idx_default = 1 if i == 0 else 0
            nome = cc[0].text_input(f"n{i}", label_visibility="collapsed")
            ruolo = cc[1].selectbox(f"r{i}", ruoli_disponibili, index=idx_default, label_visibility="collapsed")
            ore = cc[2].number_input(f"o{i}", 0.0, value=6.0, step=0.5, label_visibility="collapsed")
            paga = cc[3].number_input(f"p{i}", 0.0, value=10.0, label_visibility="collapsed")
            tot = ore * paga
            costo_staff_tot += tot
            cc[4].write(f"€{tot:.0f}")
            if nome: staff_list.append(f"{nome} ({ruolo}): {ore}h x {paga}€ = {tot}€")
            
    st.write(f"**Totale Staff: € {costo_staff_tot:,.2f}**")
    
    totale_costi = food_cost + costo_staff_tot + costo_utenze
    margine = totale_incasso - totale_costi
    margine_perc = (margine / totale_incasso * 100) if totale_incasso > 0 else 0
    
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Totale Costi", f"€ {totale_costi:,.2f}")
    m2.metric("Margine €", f"€ {margine:,.2f}")
    m3.metric("Margine %", f"{margine_perc:.1f}%", delta_color="normal" if margine_perc > 20 else "inverse")
    
    menu = st.text_area("Menu")
    note = st.text_area("Note")
    
    b1, b2 = st.columns(2)
    with b1:
        if st.button("☁️ SALVA CATERING"):
            riga = [status_prev, data_evento.strftime("%d/%m/%Y"), cliente, tipo, pax, prezzo_pax, incasso_loc, totale_incasso, food_cost, costo_utenze, costo_staff_tot, totale_costi, margine, f"{margine_perc:.2f}%", " | ".join(staff_list), menu, note]
            if salva_db_catering(riga): st.toast("Salvato!")
            
    with b2:
        exc = genera_excel_catering(cliente, data_evento, status_prev, pax, prezzo_pax, incasso_loc, totale_incasso, food_cost, costo_utenze, kwh, price_kwh, costo_staff_tot, totale_costi, margine, margine_perc/100, staff_list, menu, note)
        st.download_button("💾 SCARICA REPORT", exc, f"Cat_{cliente}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

# ==============================================================================
# MAIN LOOP
# ==============================================================================

if check_login():
    st.sidebar.title("Navigazione")
    st.sidebar.write(f"Utente: **{st.session_state['user_name']}**")
    
    role = st.session_state['user_role']
    app_mode = None
    
    if role == 'admin':
        app_mode = st.sidebar.radio("Vai a:", ["🏰 Preventivi Affitto", "👨‍🍳 Catering Manager"])
    elif role == 'affitti':
        app_mode = "🏰 Preventivi Affitto"
    elif role == 'catering':
        app_mode = "👨‍🍳 Catering Manager"
        
    if st.sidebar.button("Esci"):
        logout()

    if app_mode == "🏰 Preventivi Affitto":
        app_preventivi_affitto()
    elif app_mode == "👨‍🍳 Catering Manager":
        app_catering_manager()

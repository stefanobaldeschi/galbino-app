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
st.set_page_config(page_title="Preventivi Galbino", page_icon="🏰", layout="wide")

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
# SEZIONE 2: APP PREVENTIVI
# ==============================================================================

def app_preventivi_affitto():
    st.title(f"🏰 Preventivi Castello (Utente: {st.session_state['user_name']})")
    
    LODGIFY_ICAL_URL = "https://www.lodgify.com/5bab045e-30ec-4edf-aabf-970d352e7549.ics"
    
    LISTA_SERVIZI = [
        ("Wedding Fee", 30), ("Breakfast", 20), ("Lunch", 45), ("Dinner", 75),
        ("BBQ", 60), ("Cooking Class", 120), ("Wine Tasting", 50),
        ("Truffle Hunting", 150), ("Ebike Tour", 80), ("Transfer", 150),
        ("Prima Spesa", 0), ("Extra Cleaning", 200)
    ]

    # --- COSTI E PARAMETRI ---
    COSTO_EXTRA_PAX = 100
    SCONTO_LUNGA_DURATA_STD = 0.15 # Si applica solo all'Opzione A (Standard)
    MIN_STAY = 3
    
    # --------------------------------------------------------------------------
    # LOGICA DATE E STAGIONI
    # --------------------------------------------------------------------------
    
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

    def get_stagione_pura(data):
        """Restituisce la stagione base. Per il 2027+ applica la logica Wedding estesa."""
        anno = data.year
        
        # --- LOGICA 2027 (e successivi) ---
        if anno >= 2027:
            # 1. Tutto Settembre è Alta
            if data.month == 9: return "Alta"
            # 2. Tutto Giugno, Luglio, Agosto è Alta
            # (Agosto verrà scontato dopo, ma tecnicamente è stagione Wedding)
            if data.month in [6, 7, 8]: return "Alta"
            
            # 3. Fine Maggio (Ultimo weekend)
            if data.month == 5:
                # Calcoliamo l'ultimo giovedì di maggio come start
                maggio_31 = datetime.date(anno, 5, 31)
                # Giorni da sottrarre per arrivare a giovedì (weekday 3)
                offset = (maggio_31.weekday() - 3) % 7
                inizio_alta = maggio_31 - datetime.timedelta(days=offset)
                if data >= inizio_alta: return "Alta"
            
            # Tutto il resto è Media/Bassa (Semplificazione: Media da Aprile a Ottobre, Bassa resto)
            # Per ora manteniamo la logica 'Media' per i periodi spalla non-Alta
            if 4 <= data.month <= 10: return "Media"
            return "Bassa"

        # --- LOGICA VECCHIA (2026 e precedenti) ---
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
        # Nel 2026 Settembre è Media
        if (inizio_media_1 <= data < inizio_alta) or (ultimo_lun_luglio <= data <= fine_media_2) or (datetime.date(anno, 9, 1) <= data <= datetime.date(anno, 10, 15)):
             return "Media"
             
        return "Bassa"

    # --------------------------------------------------------------------------
    # OPZIONE A: CALCOLO STANDARD (Rental Puro)
    # --------------------------------------------------------------------------
    def calcola_opzione_A_standard(data_arrivo, notti, ospiti):
        tot_base = 0
        tot_extra = 0
        log = []
        is_2027_high = False
        
        # Prezzi Vecchi (2026 / Media / Bassa)
        RATES_OLD = {
            "Alta":  {"Base": 2000, "We": 3100},
            "Media": {"Base": 1500, "We": 2200},
            "Bassa": {"Base": 1200, "We": 1200}
        }
        capienza_base_old = 16
        
        for i in range(notti):
            giorno = data_arrivo + datetime.timedelta(days=i)
            anno = giorno.year
            mese = giorno.month
            wd = giorno.weekday()
            stg = get_stagione_pura(giorno)
            
            prezzo_notte = 0
            tag = ""
            
            # --- LOGICA 2027+ ---
            if anno >= 2027 and stg == "Alta":
                is_2027_high = True
                
                # Definizione prezzi base 2027
                p_infra = 3200
                p_weekend = 4250 # Gio-Dom
                
                # Se è Agosto, sconto 20%
                if mese == 8:
                    p_infra = p_infra * 0.8  # 2560
                    p_weekend = p_weekend * 0.8 # 3400
                    tag = "Ago'27"
                else:
                    tag = "Alta'27"
                
                if wd in [0, 1, 2]: # Lun-Mer
                    prezzo_notte = p_infra
                    tag += "(Infra)"
                else: # Gio-Dom
                    prezzo_notte = p_weekend
                    tag += "(We)"
                
                costo_ex = 0 
                
            else:
                # --- LOGICA VECCHIA (2026 / Bassa / Media) ---
                if stg == "Alta": # Caso Alta 2026
                     tipo = "We" if wd in [3,4,5,6] else "Base"
                     prezzo_notte = RATES_OLD["Alta"][tipo]
                else:
                     tipo = "We" if wd in [3,4,5,6] else "Base"
                     prezzo_notte = RATES_OLD[stg][tipo]
                
                pax_eccedenti = max(0, ospiti - capienza_base_old)
                costo_ex = pax_eccedenti * COSTO_EXTRA_PAX
                tag = f"{stg}-{tipo}"
            
            tot_base += prezzo_notte
            tot_extra += costo_ex
            log.append(f"{giorno.strftime('%d/%m')} {tag}: €{prezzo_notte:.0f}")

        totale = tot_base + tot_extra
        # Sconto settimanale solo su Opzione A
        sconto_long = 0
        if notti >= 7:
            sconto_long = totale * SCONTO_LUNGA_DURATA_STD
            totale -= sconto_long
            
        return totale, log, is_2027_high

    # --------------------------------------------------------------------------
    # OPZIONE B: PACCHETTI WEDDING (Solo Alta/Agosto 2027+)
    # --------------------------------------------------------------------------
    def calcola_opzione_B_pacchetto(data_arrivo, notti):
        # Verifica preliminare: deve essere 2027+ e Alta Stagione (incluso Agosto)
        stg_start = get_stagione_pura(data_arrivo)
        
        if data_arrivo.year < 2027: return None
        if stg_start != "Alta": return None
        
        # VINCOLO DURATA: Solo 3, 4 o 7 notti.
        if notti in [5, 6]:
            return {"error": "⛔ Durata non valida per Pacchetto Wedding (ammessi solo 3, 4 o 7 notti)"}
        if notti < 3: return None

        wd_start = data_arrivo.weekday() # 0=Lun, 6=Dom
        
        # Fattore Sconto Agosto
        fattore_agosto = 0.8 if data_arrivo.month == 8 else 1.0
        label_agosto = " (Agosto -20%)" if fattore_agosto < 1.0 else ""
        
        # 1. SETTIMANA (7 notti, Ven-Ven)
        if notti == 7:
            if wd_start == 4: # Venerdì
                prezzo = 25500 * fattore_agosto
                desc = f"📦 WEEKLY{label_agosto}"
                dettaglio = "7 notti (Ven-Ven) - Esclusiva"
                return {"prezzo": prezzo, "desc": desc, "dettagli": dettaglio}
            else:
                 return {"error": "⛔ Il pacchetto settimanale deve iniziare di Venerdì"}

        # 2. PACCHETTI 3 o 4 NOTTI
        # Definiamo i Base Packages
        PKG_WEEKEND = {"stay": 14500, "fee": 4000, "tot": 18500, "name": "WEEKEND"}
        PKG_MIDWEEK = {"stay": 11500, "fee": 3500, "tot": 15000, "name": "MIDWEEK"}
        
        selected_pkg = None
        
        # WEEKEND Pkg: check-in Giovedì(3) o Venerdì(4)
        if wd_start in [3, 4]: 
             selected_pkg = PKG_WEEKEND
        # MIDWEEK Pkg: check-in Lunedì(0) o Martedì(1)
        elif wd_start in [0, 1]: 
             selected_pkg = PKG_MIDWEEK
        else:
             return None # Mer, Sab, Dom non startano pacchetti
             
        # Calcolo costo
        base_tot = selected_pkg["tot"]
        extra_cost = 0
        notti_extra = notti - 3
        
        msg_extra = ""
        if notti_extra == 1:
            # Calcolo valore notte extra: (Stay / 3) * 0.8
            valore_notte_base = selected_pkg["stay"] / 3
            valore_notte_scontato = valore_notte_base * 0.8
            extra_cost = valore_notte_scontato
            msg_extra = f" + 4° notte scontata (€ {extra_cost:,.0f})"

        totale_lordo = base_tot + extra_cost
        totale_finale = totale_lordo * fattore_agosto
        
        desc = f"📦 {selected_pkg['name']}{label_agosto}"
        dettagli = f"Base 3 notti (€ {base_tot:,.0f}){msg_extra}"
        
        return {"prezzo": totale_finale, "desc": desc, "dettagli": dettagli}

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
            st.error(f"Errore DB: {e}")
            return False
            
    def generate_excel(autore, cliente, checkin, checkout, notti, ospiti, prezzo_finale, dettagli_servizi, sconto, note, tipo_prev, dettagli_pkg):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Preventivo")
        bold = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#D3D3D3'})
        merge_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#FFD700'}) 
        currency = workbook.add_format({'num_format': '#,##0.00 €', 'border': 1, 'align': 'center'})
        normal = workbook.add_format({'border': 1, 'align': 'center'})
        
        worksheet.set_column('A:B', 25); worksheet.set_column('C:D', 20)
        
        headers = ["Autore", "Data", "Cliente", "CheckIn", "CheckOut", "Notti", "Ospiti", "TIPO"]
        worksheet.write_row('A1', headers, bold)
        worksheet.write_row('A2', [autore, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, tipo_prev], normal)
        
        # Totali
        worksheet.write('A5', "PREZZO BASE", bold)
        worksheet.write('B5', prezzo_finale, currency)
        
        if dettagli_pkg:
             worksheet.write('A6', "DETTAGLI PACCHETTO", bold)
             worksheet.write('B6', dettagli_pkg, normal)
        
        # Servizi
        r = 8
        worksheet.write(r, 0, "SERVIZI EXTRA", bold)
        r += 1
        tot_servizi = 0
        for nome, dati in dettagli_servizi.items():
            worksheet.write(r, 0, nome, normal)
            worksheet.write(r, 1, dati['subtotale'], currency)
            tot_servizi += dati['subtotale']
            r += 1
            
        r += 1
        worksheet.write(r, 0, "SCONTO EXTRA", bold); worksheet.write(r, 1, sconto, currency)
        r += 1
        worksheet.write(r, 0, "TOTALE GENERALE", merge_format); worksheet.write(r, 1, prezzo_finale + tot_servizi - sconto, currency)
        
        worksheet.write(r+2, 0, "NOTE INTERNE", bold); worksheet.write(r+2, 1, note, normal)

        workbook.close()
        return output.getvalue()

    # --- UI AFFITTO ---
    with st.container():
        c_aut, c_cli = st.columns([1, 2])
        with c_aut: 
            current_user = st.session_state.get('user_name', 'Seleziona...')
            options_auth = ["Seleziona...", "Luca", "Stefano"]
            idx = options_auth.index(current_user) if current_user in options_auth else 0
            autore = st.selectbox("Autore", options_auth, index=idx)
            
        with c_cli: cliente = st.text_input("Nome Cliente")
        
        c1, c2, c3 = st.columns(3)
        with c1: checkin = st.date_input("Check-In", datetime.date.today(), format="DD/MM/YYYY")
        default_checkout = checkin + datetime.timedelta(days=MIN_STAY)
        with c2: checkout = st.date_input("Check-Out", value=default_checkout, min_value=checkin + datetime.timedelta(days=1), format="DD/MM/YYYY")
        with c3: ospiti = st.number_input("Ospiti", min_value=1, value=10)

    is_free, msg = check_availability(checkin, checkout, LODGIFY_ICAL_URL)
    if is_free: st.success("✅ DATE DISPONIBILI")
    else: st.error(f"⛔ {msg}")
    
    notti = (checkout - checkin).days
    
    # 1. Calcolo Opzione A (Standard / Rental)
    price_A, log_A, is_high_27 = calcola_opzione_A_standard(checkin, notti, ospiti)
    
    # 2. Calcolo Opzione B (Pacchetto) - Solo se idoneo
    res_B = calcola_opzione_B_pacchetto(checkin, notti)
    
    st.markdown("---")
    st.markdown("### 🏷️ Opzioni di Prezzo")
    
    col_A, col_B = st.columns(2)
    
    # BOX OPZIONE A
    with col_A:
        st.markdown("#### 🅰️ Opzione Rental (Standard)")
        st.metric("Totale Affitto", f"€ {price_A:,.0f}")
        with st.expander("Dettaglio Giornaliero"):
            for l in log_A: st.write(l)
            if notti >= 7 and not is_high_27: st.write("✅ Incluso Sconto Settimanale 15% (Old Logic)")
    
    # BOX OPZIONE B (Logica Aggressiva)
    prezzo_da_salvare = price_A
    desc_da_salvare = "Rental Standard"
    
    with col_B:
        st.markdown("#### 🅱️ Opzione Wedding (Aggressive)")
        if res_B:
            if "error" in res_B:
                st.error(res_B["error"])
                usa_B = False
            else:
                st.metric("Totale Pacchetto", f"€ {res_B['prezzo']:,.0f}", help=res_B['desc'])
                st.info(res_B['dettagli'])
                usa_B = st.checkbox("✅ Seleziona Opzione Pacchetto", value=False)
                if usa_B:
                    prezzo_da_salvare = res_B['prezzo']
                    desc_da_salvare = res_B['desc'] + " | " + res_B['dettagli']
        else:
            st.caption("Non disponibile per queste date/durata (Solo Alta '27: Lun-Ven o Gio-Lun o Settimana)")

    st.markdown("---")
    
    # --- SERVIZI EXTRA ---
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
                totale_servizi += sub

    # --- SCONTI E SALVATAGGIO ---
    st.markdown("### 💾 Totale e Export")
    
    col_sconto, col_note = st.columns([1, 2])
    with col_sconto:
        sconto_manuale = st.number_input("Sconto Manuale Extra (€)", min_value=0.0, step=50.0)
    with col_note:
        note = st.text_area("Note Interne")

    totale_generale = prezzo_da_salvare + totale_servizi - sconto_manuale
    
    st.divider()
    st.markdown(f"## TOTALE PREVENTIVO: € {totale_generale:,.2f}")
    if desc_da_salvare != "Rental Standard":
        st.caption(f"Basato su: {desc_da_salvare}")
        
    b1, b2 = st.columns(2)
    
    is_valid = True
    if autore == "Seleziona...": is_valid=False
    if notti < MIN_STAY: is_valid=False
    
    with b1:
        if st.button("☁️ SALVA SOLO CLOUD", use_container_width=True):
            if is_valid:
                riga = [autore, desc_da_salvare, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, prezzo_da_salvare, totale_generale, note]
                if salva_su_google_sheets(riga): st.toast("✅ Salvato!");
            else: st.error("Dati incompleti")
            
    with b2:
        if is_valid:
            excel_data = generate_excel(autore, cliente, checkin, checkout, notti, ospiti, prezzo_da_salvare, dettagli_servizi_excel, sconto_manuale, note, desc_da_salvare, res_B['dettagli'] if res_B and 'dettagli' in res_B else "")
            
            def callback_save():
                 riga = [autore, desc_da_salvare, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, prezzo_da_salvare, totale_generale, note]
                 salva_su_google_sheets(riga)
                 st.toast("✅ Salvato e Scaricato!")

            st.download_button("💾 SALVA E SCARICA", excel_data, f"Prev_{cliente}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click=callback_save, type="primary", use_container_width=True)
        else:
             st.button("💾 SALVA E SCARICA", disabled=True, use_container_width=True)

# ==============================================================================
# MAIN LOOP
# ==============================================================================

if check_login():
    app_preventivi_affitto()

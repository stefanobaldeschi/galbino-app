import streamlit as st
import datetime
import io
import xlsxwriter
import requests
from icalendar import Calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import traceback

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
    
    # LISTA SERVIZI AGGIORNATA
    LISTA_SERVIZI = [
        ("Wedding Fee", 50), 
        ("Extra Event Fee", 15),
        ("Breakfast (Inclusa)", 0), ("Lunch", 45), ("Dinner", 75),
        ("BBQ", 60), ("Cooking Class", 120), ("Wine Tasting", 50),
        ("Truffle Hunting", 150), ("Ebike Tour", 80), ("Transfer", 150),
        ("Prima Spesa", 0)
    ]

    # --- COSTI E PARAMETRI ---
    SPESE_PULIZIA = 600
    MOLTIPLICATORE_AIRBNB = 1.05
    MIN_STAY = 3
    
    # --------------------------------------------------------------------------
    # LOGICA DATE E STAGIONI UNIFICATA (Valida per tutti gli anni)
    # --------------------------------------------------------------------------
    def get_stagione_pura(data):
        anno = data.year
        mese = data.month
        giorno = data.day
        
        # Festività invernali: 21 Dicembre - 6 Gennaio -> MEDIA
        if (mese == 12 and giorno >= 21) or (mese == 1 and giorno <= 6):
            return "Media"
            
        # Pieno inverno: 7 Gennaio - 31 Marzo -> BASSA
        if (mese == 1 and giorno >= 7) or mese in [2, 3]:
            return "Bassa"
            
        # Primavera: 1 Aprile fino al mercoledì dell'ultimo weekend di Maggio -> MEDIA
        if mese == 4:
            return "Media"
        if mese == 5:
            maggio_31 = datetime.date(anno, 5, 31)
            # Troviamo il giovedì dell'ultimo weekend (weekday 3)
            offset = (maggio_31.weekday() - 3) % 7
            ultimo_giovedi = maggio_31 - datetime.timedelta(days=offset)
            if data < ultimo_giovedi:
                return "Media"
            else:
                return "Alta"
                
        # Estate/Settembre: Giugno, Luglio e Settembre -> ALTA
        if mese in [6, 7, 9]:
            return "Alta"
            
        # Agosto e Ottobre -> MEDIA
        if mese in [8, 10]:
            return "Media"
            
        # Autunno inoltrato/Inverno: Novembre e fino al 20 Dicembre -> BASSA
        if mese == 11 or (mese == 12 and giorno <= 20):
            return "Bassa"
            
        return "Bassa" # Fallback di sicurezza

    # --------------------------------------------------------------------------
    # CALCOLO PREZZO SOGGIORNO UNIFICATO
    # --------------------------------------------------------------------------
    def calcola_soggiorno(data_arrivo, notti):
        tot_base = 0
        log = []
        
        # GRIGLIA PREZZI FLAT UNICA (Fino a 26 pax)
        PRICES = {
            "Alta":  {"Infra": 4000, "We": 5200},
            "Media": {"Infra": 3200, "We": 4160},
            "Bassa": {"Infra": 2000, "We": 2600}
        }
        
        for i in range(notti):
            giorno = data_arrivo + datetime.timedelta(days=i)
            wd = giorno.weekday()
            stg = get_stagione_pura(giorno)
            
            # 0=Lun, 1=Mar, 2=Mer (Infra) | 3=Gio, 4=Ven, 5=Sab, 6=Dom (Weekend)
            tipo_giorno = "Infra" if wd in [0, 1, 2] else "We"
            prezzo_notte = PRICES[stg][tipo_giorno]
            
            tot_base += prezzo_notte
            log.append(f"{giorno.strftime('%d/%m')} ({stg} - {tipo_giorno}): € {prezzo_notte:,.0f}")

        return tot_base, log

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
            
    def generate_excel(autore, cliente, checkin, checkout, notti, ospiti, prezzo_soggiorno, spese_pulizia, totale_diretto, dettagli_servizi, sconto, note):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Preventivo")
        bold = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#D3D3D3'})
        merge_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#FFD700'}) 
        currency = workbook.add_format({'num_format': '#,##0.00 €', 'border': 1, 'align': 'center'})
        normal = workbook.add_format({'border': 1, 'align': 'center'})
        
        worksheet.set_column('A:B', 25); worksheet.set_column('C:D', 20)
        
        headers = ["Autore", "Data", "Cliente", "CheckIn", "CheckOut", "Notti", "Ospiti"]
        worksheet.write_row('A1', headers, bold)
        worksheet.write_row('A2', [autore, datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti], normal)
        
        # Totali Base
        worksheet.write('A5', "PREZZO SOGGIORNO", bold)
        worksheet.write('B5', prezzo_soggiorno, currency)
        worksheet.write('A6', "SPESE DI PULIZIA", bold)
        worksheet.write('B6', spese_pulizia, currency)
        
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
        worksheet.write(r, 0, "TOTALE DIRETTO", merge_format); worksheet.write(r, 1, totale_diretto + tot_servizi - sconto, currency)
        
        worksheet.write(r+2, 0, "NOTE INTERNE", bold); worksheet.write(r+2, 1, note, normal)

        workbook.close()
        return output.getvalue()

    # --- UI PRINCIPALE ---
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
        with c2: checkout = st.date_input("Check-Out", value=default_checkout, min_value=checkin + datetime.timedelta(days=MIN_STAY), format="DD/MM/YYYY")
        with c3: ospiti = st.number_input("Ospiti (Max 26)", min_value=1, max_value=26, value=16)

    is_free, msg = check_availability(checkin, checkout, LODGIFY_ICAL_URL)
    if is_free: st.success("✅ DATE DISPONIBILI")
    else: st.error(f"⛔ {msg}")
    
    notti = (checkout - checkin).days
    
    # Calcolo Prezzi
    prezzo_soggiorno, log_notti = calcola_soggiorno(checkin, notti)
    totale_diretto = prezzo_soggiorno + SPESE_PULIZIA
    totale_airbnb = totale_diretto * MOLTIPLICATORE_AIRBNB
    
    st.markdown("---")
    st.markdown("### 🏷️ Opzioni di Vendita (Fino a 26 Ospiti)")
    
    col_A, col_B = st.columns(2)
    
    # BOX PREZZO DIRETTO
    with col_A:
        st.markdown("#### 🟢 PREZZO DIRETTO")
        st.caption("✅ Incl: Affitto, Pulizie (€ 600) e Colazione")
        st.metric("Totale Diretto", f"€ {totale_diretto:,.0f}")
        with st.expander("Dettaglio Giornaliero Soggiorno"):
            for l in log_notti: st.write(l)
            st.write(f"Pulizie Finali: € {SPESE_PULIZIA}")
    
    # BOX PREZZO AIRBNB
    with col_B:
        st.markdown("#### 🔴 PREZZO AIRBNB / PORTALI")
        st.caption("Maggiorazione del 5% applicata")
        st.metric("Totale Portali", f"€ {totale_airbnb:,.0f}", help="Da inserire sulle OTA")

    st.markdown("---")
    
    # --- SERVIZI EXTRA ---
    st.markdown("### 🍷 Servizi e Fee")
    dettagli_servizi_excel = {}
    totale_servizi = 0
    
    for nome, prezzo_def in LISTA_SERVIZI:
        with st.expander(f"{nome}"):
            if "Wedding Fee" in nome or "Extra Event Fee" in nome:
                c1, c2 = st.columns(2)
                p_unit = c1.number_input(f"€ {nome} (a pax)", value=prezzo_def, key=f"p_{nome}")
                pax = c2.number_input("Numero Ospiti", min_value=0, key=f"x_{nome}")
                qta = 1 
            elif "Truffle" in nome:
                c1, c2 = st.columns(2)
                p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
                pax = c2.number_input("Partecipanti", min_value=0, key=f"x_{nome}")
                qta = 1
            elif "Prima Spesa" in nome:
                p_unit = st.number_input(f"Costo Scontrino", value=0.0, key=f"p_{nome}"); pax=1; qta=1
            elif "Transfer" in nome:
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
                dettagli_servizi_excel[nome] = {'p_unit': p_unit, 'pax': pax, 'qta': qta, 'subtotale': sub}
                totale_servizi += sub

    # --- SCONTI E SALVATAGGIO ---
    st.markdown("### 💾 Totale e Export")
    
    col_sconto, col_note = st.columns([1, 2])
    with col_sconto:
        sconto_manuale = st.number_input("Sconto Manuale Extra (€)", min_value=0.0, step=50.0)
    with col_note:
        note = st.text_area("Note Interne")

    totale_generale_diretto = totale_diretto + totale_servizi - sconto_manuale
    
    st.divider()
    st.markdown(f"## TOTALE PREVENTIVO DIRETTO: € {totale_generale_diretto:,.2f}")
        
    b1, b2 = st.columns(2)
    
    is_valid = True
    if autore == "Seleziona...": is_valid=False
    if notti < MIN_STAY: is_valid=False
    
    with b1:
        if st.button("☁️ SALVA SOLO CLOUD", use_container_width=True):
            if is_valid:
                riga = [autore, "Diretto", datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, totale_diretto, totale_generale_diretto, note]
                if salva_su_google_sheets(riga): st.toast("✅ Salvato!");
            else: st.error(f"Dati incompleti o Soggiorno minimo non rispettato ({MIN_STAY} notti)")
            
    with b2:
        if is_valid:
            excel_data = generate_excel(autore, cliente, checkin, checkout, notti, ospiti, prezzo_soggiorno, SPESE_PULIZIA, totale_diretto, dettagli_servizi_excel, sconto_manuale, note)
            
            def callback_save():
                 riga = [autore, "Diretto", datetime.date.today().strftime("%d/%m/%Y"), cliente, checkin.strftime("%d/%m/%Y"), checkout.strftime("%d/%m/%Y"), notti, ospiti, totale_diretto, totale_generale_diretto, note]
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

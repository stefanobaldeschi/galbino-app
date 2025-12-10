import streamlit as st
import datetime
import io
import xlsxwriter
import requests
from icalendar import Calendar
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import traceback

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Preventivi Galbino", page_icon="🏰", layout="wide")

# --- 0. CALENDARIO LODGIFY ---
LODGIFY_ICAL_URL = "https://www.lodgify.com/5bab045e-30ec-4edf-aabf-970d352e7549.ics"

# --- 1. DATI ---
LISTA_SERVIZI = [
    ("Wedding Fee", 30), 
    ("Breakfast", 20),
    ("Lunch", 45),
    ("Dinner", 75),
    ("BBQ", 60),
    ("Cooking Class", 120),
    ("Wine Tasting", 50),
    ("Truffle Hunting", 150),
    ("Ebike Tour", 80),
    ("Transfer", 150),
    ("Prima Spesa", 0),
    ("Extra Cleaning", 200)
]

RATES = {
    "Alta": {"Base": 2000, "We": 3100, "CapienzaBase": 16, "Max": 24},
    "Media": {"Base": 1500, "We": 2200, "CapienzaBase": 16, "Max": 24},
    "Bassa": {"Base": 1200, "We": 1200, "CapienzaBase": 10, "Max": 22}
}

COSTO_EXTRA_PAX = 100
SCONTO_LUNGA_DURATA = 0.15
MIN_STAY = 3

# --- FUNZIONI UTILI ---
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

def calcola_soggiorno(data_arrivo, notti, ospiti):
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
    if not url: return None, "Link mancante"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"}
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

# --- SALVATAGGIO DATABASE GOOGLE ---
def salva_su_google_sheets(riga_dati):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["spreadsheet_url"]).sheet1
        sheet.append_row(riga_dati)
        return True
    except Exception as e:
        st.error("⚠️ ERRORE SALVATAGGIO CLOUD")
        st.write("COPIA QUESTO CODICE DI ERRORE:")
        st.code(traceback.format_exc())
        return False

# --- EXCEL GENERATOR ---
def generate_excel(autore, cliente, checkin, checkout, notti, ospiti, affitto_netto, pulizie, dettagli_servizi, sconto, totale_gen, costo_medio, note):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet("Preventivo")
    bold = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#D3D3D3'})
    merge_format = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#FFD700'}) 
    currency = workbook.add_format({'num_format': '€ #,##0.00', 'border': 1})
    normal = workbook.add_format({'border': 1, 'align': 'center'})
    
    # Formato Date Italiano
    general_headers = ["Autore", "Data Prev", "Cliente", "CheckIn", "CheckOut", "Notti", "Ospiti", "Affitto Totale", "Pulizie"]
    worksheet.write_row('A1', general_headers, bold)
    
    # Scrittura date formattate
    worksheet.write('A2', autore, normal)
    worksheet.write('B2', datetime.date.today().strftime("%d/%m/%Y"), normal)
    worksheet.write('C2', cliente, normal)
    worksheet.write('D2', checkin.strftime("%d/%m/%Y"), normal)
    worksheet.write('E2', checkout.strftime("%d/%m/%Y"), normal)
    worksheet.write('F2', notti, normal)
    worksheet.write('G2', ospiti, normal)
    worksheet.write('H2', affitto_netto, currency)
    worksheet.write('I2', pulizie, currency)

    col_idx = 9 
    for nome, _ in LISTA_SERVIZI:
        worksheet.merge_range(0, col_idx, 0, col_idx+3, nome.upper(), merge_format)
        worksheet.write(1, col_idx, "€ Unit", bold)
        worksheet.write(1, col_idx+1, "Pax", bold)
        worksheet.write(1, col_idx+2, "Qta", bold)
        worksheet.write(1, col_idx+3, "Totale", bold)
        
        if nome in dettagli_servizi:
            dati = dettagli_servizi[nome]
            worksheet.write(2, col_idx, dati['p_unit'], currency)
            worksheet.write(2, col_idx+1, dati['pax'], normal)
            worksheet.write(2, col_idx+2, dati['qta'], normal)
            worksheet.write(2, col_idx+3, dati['subtotale'], currency)
        else:
            worksheet.write(2, col_idx, 0, currency)
            worksheet.write(2, col_idx+1, 0, normal)
            worksheet.write(2, col_idx+2, 0, normal)
            worksheet.write(2, col_idx+3, 0, currency)
        col_idx += 4 

    col_idx += 1
    worksheet.write(0, col_idx, "SCONTO", bold)
    worksheet.write(2, col_idx, sconto, currency)
    worksheet.write(0, col_idx+1, "TOTALE PREVENTIVO", bold)
    worksheet.write(2, col_idx+1, totale_gen, currency)
    worksheet.write(0, col_idx+2, "MEDIA AFFITTO/NOTTE", bold)
    worksheet.write(2, col_idx+2, costo_medio, currency)
    worksheet.write(0, col_idx+3, "NOTE", bold)
    worksheet.write(2, col_idx+3, note, normal)
    workbook.close()
    return output.getvalue()

def aggiorna_date():
    if 'data_in' in st.session_state: st.session_state.data_out = st.session_state.data_in + datetime.timedelta(days=MIN_STAY)

# --- INTERFACCIA ---
st.title("🏰 Castello di Galbino")

with st.container():
    st.markdown("### 📅 Dati Soggiorno")
    
    c_aut, c_cli = st.columns([1, 3])
    with c_aut:
        autore = st.selectbox("Autore Preventivo", ["Seleziona...", "Luca", "Stefano"])
    with c_cli:
        cliente = st.text_input("Nome Cliente")
    
    c1, c2, c3 = st.columns(3)
    # FORMATO ITALIANO NELL'INPUT (DD/MM/YYYY)
    with c1: 
        checkin = st.date_input("Check-In", value=datetime.date.today(), key='data_in', on_change=aggiorna_date, format="DD/MM/YYYY")
    with c2: 
        default_out = datetime.date.today() + datetime.timedelta(days=MIN_STAY)
        if 'data_out' not in st.session_state: st.session_state.data_out = default_out
        checkout = st.date_input("Check-Out", key='data_out', format="DD/MM/YYYY")
    with c3: 
        ospiti = st.number_input("Ospiti a Dormire", min_value=1, value=10)

is_free, msg = check_availability(checkin, checkout, LODGIFY_ICAL_URL)
if is_free is True: st.success(f"✅ DATE DISPONIBILI")
elif is_free is False: st.error(f"⛔ {msg}")
else: st.warning(f"⚠️ Errore controllo: {msg}")

st.markdown("### 🍷 Servizi")
dettagli_servizi_excel = {}
totale_servizi = 0
descrizione_servizi_txt = [] 

for nome, prezzo_def in LISTA_SERVIZI:
    with st.expander(f"{nome}"):
        
        if "Wedding" in nome:
            c1, c2 = st.columns(2)
            p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = c2.number_input("Invitati", min_value=0, value=0, key=f"x_{nome}")
            qta = 1 
        elif "Truffle" in nome:
            c1, c2 = st.columns(2)
            p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = c2.number_input("Partecipanti", min_value=0, value=0, key=f"x_{nome}")
            qta = 1
        elif "Prima Spesa" in nome:
            p_unit = st.number_input(f"Costo Scontrino", value=0.0, key=f"p_{nome}")
            pax = 1
            qta = 1
        elif "Transfer" in nome or "Extra Cleaning" in nome:
            c1, c2 = st.columns(2)
            p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = 1 
            qta = c2.number_input(f"Quantità/Volte", min_value=0, value=0, key=f"q_{nome}")
        else:
            c1, c2, c3 = st.columns(3)
            p_unit = c1.number_input(f"€ {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = c2.number_input(f"Pax", min_value=0, value=0, key=f"x_{nome}")
            qta = c3.number_input(f"Qta", min_value=0, value=0, key=f"q_{nome}")
        
        condizione_attiva = False
        if "Prima Spesa" in nome and p_unit > 0: condizione_attiva = True
        elif p_unit > 0 and pax > 0 and qta > 0: condizione_attiva = True
            
        if condizione_attiva:
            sub = p_unit * pax * qta
            totale_servizi += sub
            dettagli_servizi_excel[nome] = {'p_unit': p_unit, 'pax': pax, 'qta': qta, 'subtotale': sub}
            
            if "Wedding" in nome: descrizione_servizi_txt.append(f"{nome}: €{p_unit} x {pax} = €{sub:.2f}")
            elif "Prima Spesa" in nome: descrizione_servizi_txt.append(f"{nome}: €{sub:.2f}")
            elif "Transfer" in nome or "Extra Cleaning" in nome: descrizione_servizi_txt.append(f"{nome}: €{p_unit} x {qta} = €{sub:.2f}")
            else: descrizione_servizi_txt.append(f"{nome}: €{p_unit} x {pax} x {qta} = €{sub:.2f}")

st.divider()
c_f1, c_f2 = st.columns(2)
with c_f1: sconto = st.number_input("Sconto Manuale (€)", min_value=0.0, step=50.0)
with c_f2: note = st.text_area("Note interne")

if st.button("CALCOLA, SALVA SU CLOUD E SCARICA", type="primary", use_container_width=True):
    if autore == "Seleziona...":
        st.error("⚠️ ATTENZIONE: Devi selezionare chi sta facendo il preventivo (Luca o Stefano)!")
    elif notti < MIN_STAY: 
        st.error(f"⚠️ Minimo {MIN_STAY} notti.")
    elif notti <= 0: 
        st.error("⚠️ Date non valide.")
    else:
        costo_affitto, log_affitto = calcola_soggiorno(checkin, notti, ospiti)
        if costo_affitto is None: st.error(f"❌ {log_affitto}")
        else:
            affitto_netto = costo_affitto
            desc_affitto = f"Affitto {notti} notti"
            if notti >= 7:
                sconto_long = costo_affitto * SCONTO_LUNGA_DURATA
                affitto_netto = costo_affitto - sconto_long
                desc_affitto += " (-15%)"
            
            pulizie = 600
            totale_gen = affitto_netto + pulizie + totale_servizi - sconto
            costo_medio_notte = affitto_netto / notti
            
            st.success(f"✅ TOTALE: € {totale_gen:,.2f}")
            
            # --- SALVATAGGIO SU GOOGLE SHEETS (Con formato Date IT) ---
            riga_db = [
                autore,
                datetime.date.today().strftime("%d/%m/%Y"), # Oggi
                cliente,
                checkin.strftime("%d/%m/%Y"), # CheckIn
                checkout.strftime("%d/%m/%Y"), # CheckOut
                notti, ospiti, affitto_netto, pulizie
            ]
            
            for s_nome, _ in LISTA_SERVIZI:
                if s_nome in dettagli_servizi_excel:
                    dati = dettagli_servizi_excel[s_nome]
                    riga_db.extend([dati['p_unit'], dati['pax'], dati['qta'], dati['subtotale']])
                else:
                    riga_db.extend([0, 0, 0, 0])
            
            riga_db.extend([sconto, totale_gen, costo_medio_notte, note])
            
            if salva_su_google_sheets(riga_db):
                st.toast("☁️ Salvato nel Database!", icon="✅")
            
            with st.expander("Dettagli Rapidi", expanded=True):
                st.write(f"- {desc_affitto}: €{affitto_netto:.2f}")
                st.write(f"- Pulizie: €{pulizie:.2f}")
                for riga in descrizione_servizi_txt: st.write(f"- {riga}")
                if sconto > 0: st.write(f"- Sconto: -€{sconto:.2f}")
                st.write("---")
                st.write(f"🌙 **Media Affitto a notte:** €{costo_medio_notte:,.2f}")

            excel_data = generate_excel(autore, cliente, checkin, checkout, notti, ospiti, affitto_netto, pulizie, dettagli_servizi_excel, sconto, totale_gen, costo_medio_notte, note)
            st.download_button(label="📥 Scarica Excel (.xlsx)", data=excel_data, file_name=f"Prev_{cliente}_{datetime.date.today()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

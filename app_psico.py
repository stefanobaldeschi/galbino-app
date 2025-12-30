import streamlit as st
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Diario Clinico", page_icon="🧠", layout="centered")

# ==============================================================================
# 1. COLLEGAMENTO DATABASE
# ==============================================================================
def get_db():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["psico_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_url(st.secrets["psico"]["spreadsheet_url"])
    except Exception as e:
        st.error(f"Errore nei Secrets: {e}")
        st.stop()

# ==============================================================================
# 2. LOGICA INTELLIGENTE (Storico + Anagrafica)
# ==============================================================================
def get_dati_intelligenti(sheet_diario, sheet_pazienti):
    # 1. LEGGE LO STORICO DAL DIARIO
    data_diario = sheet_diario.get_all_values()
    pazienti_last_date = {}
    pazienti_last_price = {}
    
    # Salta intestazione (riga 1)
    for row in data_diario[1:]:
        if len(row) > 3:
            data_str = row[0]
            nome = row[1].strip()
            prezzo_str = row[3].replace("€", "").replace(",", ".").strip()
            
            if nome and data_str:
                try:
                    dt = datetime.datetime.strptime(data_str, "%d/%m/%Y").date()
                    # Aggiorna data
                    if nome not in pazienti_last_date or dt > pazienti_last_date[nome]:
                        pazienti_last_date[nome] = dt
                    # Aggiorna prezzo
                    if prezzo_str:
                        valore = float(prezzo_str)
                        if valore > 0:
                            pazienti_last_price[nome] = valore
                except:
                    pass

    # 2. LEGGE L'ANAGRAFICA MANUALE (Foglio Pazienti)
    try:
        nomi_anagrafica = sheet_pazienti.col_values(1)[1:] # Legge colonna A saltando l'intestazione
        nomi_anagrafica = [n.strip() for n in nomi_anagrafica if n.strip()] # Pulisce righe vuote
    except:
        nomi_anagrafica = []

    # 3. UNISCE I DATI (Chi è attivo?)
    oggi = datetime.date.today()
    attivi_set = set(nomi_anagrafica) # Parte con quelli scritti a mano
    
    # Aggiunge quelli recenti dallo storico (ultimi 90gg)
    for p, data_ult in pazienti_last_date.items():
        delta = (oggi - data_ult).days
        if delta <= 90:
            attivi_set.add(p)
            
    # Crea liste ordinate
    attivi = list(attivi_set)
    attivi.sort()
    
    storico_completo = list(pazienti_last_date.keys())
    storico_completo.sort()
            
    return attivi, storico_completo, pazienti_last_price

# ==============================================================================
# 3. INTERFACCIA UTENTE
# ==============================================================================
st.title("🧠 Diario Clinico")

try:
    sh = get_db()
    ws_diario = sh.worksheet("Diario")
    # Prova a prendere il foglio Pazienti, se non esiste lo ignora
    try:
        ws_pazienti = sh.worksheet("Pazienti")
    except:
        ws_pazienti = None
        
    attivi, storico, memoria_prezzi = get_dati_intelligenti(ws_diario, ws_pazienti)
    
    # --- FORM ---
    
    # DATA
    data_seduta = st.date_input("Data Seduta", datetime.date.today(), format="DD/MM/YYYY")
    st.write("")
    
    # PAZIENTE
    scelta = st.radio("Paziente", ["Lista Attiva", "Archivio", "➕ Nuovo"], horizontal=True, label_visibility="collapsed")
    
    paziente = ""
    if scelta == "Lista Attiva":
        if attivi:
            paziente = st.selectbox("Seleziona", attivi)
        else:
            st.info("Nessun paziente in lista. Aggiungili nel foglio 'Pazienti' o fai la prima seduta.")
    elif scelta == "Archivio":
        if storico:
            paziente = st.selectbox("Cerca nell'archivio", storico)
        else:
            st.warning("Archivio vuoto.")
    else:
        paziente = st.text_input("Nome Nuovo Paziente").strip()
        
    st.write("")
    
    # DETTAGLI
    c1, c2 = st.columns([1, 1])
    with c1:
        tipo = st.radio("Modalità", ["Presenza", "Online"])
    with c2:
        prezzo_suggerito = 0.0
        msg = "Inserisci importo"
        if paziente in memoria_prezzi and scelta != "➕ Nuovo":
            prezzo_suggerito = memoria_prezzi[paziente]
            msg = f"Ultimo: € {prezzo_suggerito:.2f}"
            
        prezzo = st.number_input("Prezzo (€)", min_value=0.0, value=prezzo_suggerito, step=5.0, help=msg)

    note = st.text_area("Note (Opzionale)", height=80)
    
    st.divider()
    
    # SAVE
    is_ready = paziente != "" and prezzo > 0
    
    if st.button("💾 REGISTRA SEDUTA", type="primary", use_container_width=True, disabled=not is_ready):
        riga = [
            data_seduta.strftime("%d/%m/%Y"),
            paziente,
            tipo,
            f"{prezzo:.2f}".replace(".", ","),
            note,
            "DA FARE"
        ]
        ws_diario.append_row(riga)
        st.success(f"✅ Salvato: {paziente}")
        time.sleep(1.5)
        st.rerun()
        
except Exception as e:
    st.error(f"Errore: {e}")

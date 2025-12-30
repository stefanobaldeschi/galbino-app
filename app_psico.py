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
        # Legge le credenziali direttamente dal formato TOML dei secrets
        creds_dict = dict(st.secrets["psico_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_url(st.secrets["psico"]["spreadsheet_url"])
    except Exception as e:
        st.error(f"Errore nei Secrets o nel collegamento: {e}")
        st.stop()

# ==============================================================================
# 2. LOGICA INTELLIGENTE (Impara dai dati passati)
# ==============================================================================
def get_dati_intelligenti(sheet_diario):
    data = sheet_diario.get_all_values()
    pazienti_last_date = {}
    pazienti_last_price = {}
    
    # Salta l'intestazione (riga 1)
    # Colonne attese: A:Data | B:Paziente | C:Tipo | D:Prezzo | E:Note
    for row in data[1:]:
        if len(row) > 3: # Se la riga ha abbastanza dati
            data_str = row[0]
            nome = row[1].strip()
            # Pulisce il prezzo da € e converte virgola in punto
            prezzo_str = row[3].replace("€", "").replace(",", ".").strip()
            
            if nome and data_str:
                try:
                    dt = datetime.datetime.strptime(data_str, "%d/%m/%Y").date()
                    
                    # Memorizza l'ultima data per sapere se è attivo
                    if nome not in pazienti_last_date or dt > pazienti_last_date[nome]:
                        pazienti_last_date[nome] = dt
                    
                    # Memorizza l'ultimo prezzo valido
                    if prezzo_str:
                        valore = float(prezzo_str)
                        if valore > 0:
                            pazienti_last_price[nome] = valore
                except:
                    pass # Ignora righe rovinate

    # Filtra i pazienti degli ultimi 3 mesi (90 gg)
    oggi = datetime.date.today()
    attivi = []
    storico = list(pazienti_last_date.keys())
    storico.sort()
    
    for p in storico:
        delta = (oggi - pazienti_last_date[p]).days
        if delta <= 90:
            attivi.append(p)
            
    return attivi, storico, pazienti_last_price

# ==============================================================================
# 3. INTERFACCIA UTENTE
# ==============================================================================
st.title("🧠 Diario Clinico")

try:
    # Connessione
    sh = get_db()
    ws_diario = sh.worksheet("Diario")
    
    # Lettura dati
    attivi, storico, memoria_prezzi = get_dati_intelligenti(ws_diario)
    
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
            st.info("Nessun paziente recente.")
    elif scelta == "Archivio":
        if storico:
            paziente = st.selectbox("Cerca nell'archivio", storico)
        else:
            st.warning("Archivio vuoto.")
    else:
        paziente = st.text_input("Nome Nuovo Paziente").strip()
        
    st.write("")
    
    # DETTAGLI (Tipo e Prezzo)
    c1, c2 = st.columns([1, 1])
    with c1:
        tipo = st.radio("Modalità", ["Presenza", "Online"])
    with c2:
        prezzo_suggerito = 0.0
        msg = "Inserisci importo"
        # Se esiste uno storico prezzi per questo paziente, lo suggerisce
        if paziente in memoria_prezzi and scelta != "➕ Nuovo":
            prezzo_suggerito = memoria_prezzi[paziente]
            msg = f"Ultimo: € {prezzo_suggerito:.2f}"
            
        prezzo = st.number_input("Prezzo (€)", min_value=0.0, value=prezzo_suggerito, step=5.0, help=msg)

    note = st.text_area("Note (Opzionale)", height=80)
    
    st.divider()
    
    # TASTO SALVA (Attivo solo se c'è nome e prezzo)
    is_ready = paziente != "" and prezzo > 0
    
    if st.button("💾 REGISTRA SEDUTA", type="primary", use_container_width=True, disabled=not is_ready):
        # A=Data | B=Paziente | C=Tipo | D=Prezzo | E=Note | F=Stato
        riga = [
            data_seduta.strftime("%d/%m/%Y"),
            paziente,
            tipo,
            f"{prezzo:.2f}".replace(".", ","),
            note,
            "DA FARE"
        ]
        ws_diario.append_row(riga)
        st.success(f"✅ Salvato: {paziente} - € {prezzo}")
        time.sleep(1.5)
        st.rerun()
        
except Exception as e:
    st.error(f"Errore generale: {e}")

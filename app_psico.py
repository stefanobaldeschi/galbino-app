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
# 2. LOGICA INTELLIGENTE (DEBUG MODE)
# ==============================================================================
def get_dati_intelligenti(sheet_diario, sh_generale):
    # 1. LEGGE LO STORICO
    data_diario = sheet_diario.get_all_values()
    pazienti_last_date = {}
    pazienti_last_price = {}
    
    for row in data_diario[1:]:
        if len(row) > 3:
            data_str = row[0]
            nome = row[1].strip()
            prezzo_str = row[3].replace("€", "").replace(",", ".").strip()
            
            if nome and data_str:
                try:
                    dt = datetime.datetime.strptime(data_str, "%d/%m/%Y").date()
                    if nome not in pazienti_last_date or dt > pazienti_last_date[nome]:
                        pazienti_last_date[nome] = dt
                    if prezzo_str:
                        valore = float(prezzo_str)
                        if valore > 0:
                            pazienti_last_price[nome] = valore
                except:
                    pass

    # 2. LEGGE L'ANAGRAFICA (SENZA PROTEZIONI)
    nomi_anagrafica = []
    try:
        # Cerca esplicitamente il foglio "Pazienti"
        ws_pazienti = sh_generale.worksheet("Pazienti")
        colonna_A = ws_pazienti.col_values(1)
        
        # Se la colonna ha dati, li prende (saltando la riga 1)
        if len(colonna_A) > 1:
            nomi_anagrafica = [n.strip() for n in colonna_A[1:] if n.strip()]
        else:
            # Se trova il foglio ma è vuoto, lo segnala in piccolo
            st.toast("⚠️ Trovato foglio 'Pazienti' ma sembra vuoto nella colonna A!")
            
    except gspread.exceptions.WorksheetNotFound:
        st.error("ERRORE: Non trovo il foglio chiamato 'Pazienti'. Controlla maiuscole/minuscole nel Google Sheet!")
        st.stop()
    except Exception as e:
        st.error(f"Errore imprevisto leggendo i Pazienti: {e}")
        st.stop()

    # 3. UNISCE I DATI
    oggi = datetime.date.today()
    attivi_set = set(nomi_anagrafica)
    
    for p, data_ult in pazienti_last_date.items():
        delta = (oggi - data_ult).days
        if delta <= 90:
            attivi_set.add(p)
            
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
    
    # Passiamo l'intero spreadsheet (sh) per cercare "Pazienti" dentro la funzione
    attivi, storico, memoria_prezzi = get_dati_intelligenti(ws_diario, sh)
    
    # --- FORM ---
    data_seduta = st.date_input("Data Seduta", datetime.date.today(), format="DD/MM/YYYY")
    st.write("")
    
    scelta = st.radio("Paziente", ["Lista Attiva", "Archivio", "➕ Nuovo"], horizontal=True, label_visibility="collapsed")
    
    paziente = ""
    if scelta == "Lista Attiva":
        if attivi:
            paziente = st.selectbox("Seleziona", attivi)
        else:
            st.warning("Lista vuota. Controlla di aver scritto i nomi nella Colonna A del foglio 'Pazienti'.")
    elif scelta == "Archivio":
        if storico:
            paziente = st.selectbox("Cerca archivio", storico)
        else:
            st.warning("Archivio vuoto.")
    else:
        paziente = st.text_input("Nome Nuovo Paziente").strip()
        
    st.write("")
    
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

    note = st.text_area("Note", height=80)
    st.divider()
    
    is_ready = paziente != "" and prezzo > 0
    
    if st.button("💾 REGISTRA SEDUTA", type="primary", use_container_width=True, disabled=not is_ready):
        riga = [data_seduta.strftime("%d/%m/%Y"), paziente, tipo, f"{prezzo:.2f}".replace(".", ","), note, "DA FARE"]
        ws_diario.append_row(riga)
        st.success(f"✅ Salvato: {paziente}")
        time.sleep(1.5)
        st.rerun()
        
except Exception as e:
    st.error(f"Errore Generale: {e}")

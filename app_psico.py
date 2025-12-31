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
        st.error(f"Errore di connessione: {e}")
        st.stop()

# ==============================================================================
# 2. LOGICA INTELLIGENTE (Anagrafica + Storico)
# ==============================================================================
def get_dati_intelligenti(sheet_diario, sh_generale):
    
    pazienti_last_date = {}
    pazienti_last_price = {}
    nomi_anagrafica = []

    # --- FASE A: LEGGI ANAGRAFICA (Foglio Pazienti) ---
    try:
        ws_pazienti = sh_generale.worksheet("Pazienti")
        dati_pazienti = ws_pazienti.get_all_values()
        
        # Salta intestazione (riga 1)
        for row in dati_pazienti[1:]:
            if len(row) >= 1:
                nome = row[0].strip()
                if nome:
                    nomi_anagrafica.append(nome)
                    
                    # Se c'è un prezzo nella colonna B, lo memorizza
                    if len(row) >= 2:
                        try:
                            # Pulisce il prezzo
                            p_clean = row[1].replace("€", "").replace(",", ".").strip()
                            if p_clean:
                                pazienti_last_price[nome] = float(p_clean)
                        except:
                            pass 
    except:
        pass # Se manca il foglio, prosegue senza errori

    # --- FASE B: LEGGI LO STORICO (Diario) ---
    # Lo storico vince sull'anagrafica (aggiorna il prezzo all'ultimo usato)
    data_diario = sheet_diario.get_all_values()
    
    for row in data_diario[1:]:
        if len(row) > 3:
            data_str = row[0]
            nome = row[1].strip()
            prezzo_str = row[3].replace("€", "").replace(",", ".").strip()
            
            if nome and data_str:
                try:
                    dt = datetime.datetime.strptime(data_str, "%d/%m/%Y").date()
                    
                    # Aggiorna data ultima visita
                    if nome not in pazienti_last_date or dt > pazienti_last_date[nome]:
                        pazienti_last_date[nome] = dt
                    
                    # Aggiorna ultimo prezzo pagato
                    if prezzo_str:
                        valore = float(prezzo_str)
                        if valore > 0:
                            pazienti_last_price[nome] = valore
                except:
                    pass

    # --- FASE C: LISTE FINALI ---
    oggi = datetime.date.today()
    
    # Lista Attiva: Anagrafica + Recenti (90gg)
    attivi_set = set(nomi_anagrafica)
    for p, data_ult in pazienti_last_date.items():
        delta = (oggi - data_ult).days
        if delta <= 90:
            attivi_set.add(p)
            
    attivi = list(attivi_set)
    attivi.sort()
    
    # Archivio: Tutto
    storico_completo = list(set(list(pazienti_last_date.keys()) + nomi_anagrafica))
    storico_completo.sort()
            
    return attivi, storico_completo, pazienti_last_price

# ==============================================================================
# 3. INTERFACCIA UTENTE
# ==============================================================================
st.title("🧠 Diario Clinico")

try:
    sh = get_db()
    ws_diario = sh.worksheet("Diario")
    
    # Legge i dati
    attivi, storico, memoria_prezzi = get_dati_intelligenti(ws_diario, sh)
    
    # --- FORM ---
    
    # 1. DATA
    data_seduta = st.date_input("Data Seduta", datetime.date.today(), format="DD/MM/YYYY")
    st.write("")
    
    # 2. PAZIENTE
    scelta = st.radio("Paziente", ["Lista Attiva", "Archivio", "➕ Nuovo"], horizontal=True, label_visibility="collapsed")
    
    paziente = ""
    if scelta == "Lista Attiva":
        if attivi:
            paziente = st.selectbox("Seleziona Paziente", attivi)
        else:
            st.info("Nessun paziente. Aggiungili nel foglio 'Pazienti' colonna A.")
    elif scelta == "Archivio":
        if storico:
            paziente = st.selectbox("Cerca nell'archivio", storico)
        else:
            st.warning("Archivio vuoto.")
    else:
        paziente = st.text_input("Nome Nuovo Paziente").strip()
        
    st.write("")
    
    # 3. DETTAGLI
    c1, c2 = st.columns([1, 1])
    
    with c1:
        tipo = st.radio("Modalità", ["Presenza", "Online"])
        
    with c2:
        prezzo_suggerito = 0.0
        msg_help = "Inserisci l'importo"
        
        # Recupera il prezzo dalla memoria (Anagrafica o Storico)
        if paziente in memoria_prezzi and scelta != "➕ Nuovo":
            prezzo_suggerito = memoria_prezzi[paziente]
            msg_help = f"Prezzo standard/ultimo: € {prezzo_suggerito:.2f}"
            
        prezzo = st.number_input("Prezzo (€)", min_value=0.0, value=prezzo_suggerito, step=5.0, help=msg_help)

    # 4. NOTE
    note = st.text_area("Note (Opzionale)", height=80)
    
    st.divider()
    
    # 5. SALVATAGGIO
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
        st.success(f"✅ Salvato: {paziente} - € {prezzo}")
        time.sleep(1.5)
        st.rerun()
        
except Exception as e:
    st.error(f"Si è verificato un errore: {e}")

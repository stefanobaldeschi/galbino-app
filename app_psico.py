import streamlit as st
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Diario Clinico", page_icon="🧠", layout="centered")

# ==============================================================================
# 1. COLLEGAMENTO DATABASE (SALVATO IN CACHE)
# ==============================================================================
@st.cache_resource
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
# 2. LOGICA INTELLIGENTE CON CACHE (Evita l'errore 429)
# ==============================================================================
@st.cache_data(ttl=600) # Salva i dati in memoria per 10 minuti per non stressare Google
def get_dati_intelligenti():
    sh_generale = get_db()
    sheet_diario = sh_generale.worksheet("Diario")
    
    pazienti_last_date = {}
    pazienti_last_price = {}
    nomi_anagrafica = []
    
    debug_log = []

    # --- FASE A: LEGGI ANAGRAFICA (Foglio Pazienti) ---
    try:
        ws_pazienti = sh_generale.worksheet("Pazienti")
        dati_pazienti = ws_pazienti.get_all_values()
        
        for i, row in enumerate(dati_pazienti[1:]):
            if len(row) >= 1:
                nome = row[0].strip()
                if nome:
                    nomi_anagrafica.append(nome)
                    prezzo_raw = "Nessuno"
                    if len(row) >= 2:
                        prezzo_raw = row[1] 
                        try:
                            p_clean = row[1].replace("€", "").replace(",", ".").strip()
                            if p_clean:
                                p_base = float(p_clean)
                                pazienti_last_price[nome] = p_base
                                debug_log.append(f"✅ Riga {i+2}: {nome} -> Letto: {p_base}")
                            else:
                                debug_log.append(f"❌ Riga {i+2}: {nome} -> Prezzo vuoto")
                        except:
                            debug_log.append(f"⚠️ Riga {i+2}: {nome} -> Errore lettura prezzo '{row[1]}'")
                    else:
                        debug_log.append(f"❌ Riga {i+2}: {nome} -> Manca Colonna B")
    except Exception as e:
        debug_log.append(f"🔥 Errore leggendo Pazienti: {e}")

    # --- FASE B: LEGGI LO STORICO (Diario) ---
    try:
        data_diario = sheet_diario.get_all_values()
        for row in data_diario[1:]:
            if len(row) > 3:
                data_str, nome = row[0], row[1].strip()
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
    except Exception as e:
         debug_log.append(f"🔥 Errore leggendo Diario: {e}")

    # --- FASE C: UNIONE ---
    oggi = datetime.date.today()
    attivi_set = set(nomi_anagrafica)
    for p, data_ult in pazienti_last_date.items():
        if (oggi - data_ult).days <= 90:
            attivi_set.add(p)
            
    attivi = list(attivi_set)
    attivi.sort()
    storico = list(set(list(pazienti_last_date.keys()) + nomi_anagrafica))
    storico.sort()
            
    return attivi, storico, pazienti_last_price, debug_log

# ==============================================================================
# 3. INTERFACCIA UTENTE
# ==============================================================================
st.title("🧠 Diario Clinico")

try:
    sh = get_db()
    ws_diario = sh.worksheet("Diario")
    
    # Richiama i dati (se li ha già in memoria, ci mette zero secondi e zero richieste!)
    attivi, storico, memoria_prezzi, debug_info = get_dati_intelligenti()
    
    # --- FORM ---
    data_seduta = st.date_input("Data Seduta", datetime.date.today(), format="DD/MM/YYYY")
    st.write("")
    
    scelta = st.radio("Paziente", ["Lista Attiva", "Archivio", "➕ Nuovo"], horizontal=True, label_visibility="collapsed")
    
    paziente = ""
    if scelta == "Lista Attiva":
        if attivi:
            paziente = st.selectbox("Seleziona", attivi)
        else:
            st.warning("Lista vuota. Aggiungi dal foglio o usa 'Nuovo'.")
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
        msg_help = "Inserisci importo"
        
        if paziente in memoria_prezzi and scelta != "➕ Nuovo":
            prezzo_suggerito = memoria_prezzi[paziente]
            msg_help = f"Prezzo rilevato: € {prezzo_suggerito:.2f}"
            
        prezzo = st.number_input("Prezzo (€)", min_value=0.0, value=prezzo_suggerito, step=5.0, help=msg_help)

    note = st.text_area("Note", height=80)
    st.divider()
    
    if st.button("💾 REGISTRA SEDUTA", type="primary", use_container_width=True, disabled=(not paziente or prezzo == 0)):
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
        
        # Svuotiamo la cache così la prossima volta che carica rileggerà il nuovo paziente/prezzo inserito!
        get_dati_intelligenti.clear()
        
        time.sleep(1.5)
        st.rerun()
        
except Exception as e:
    st.error(f"Errore Critico: {e}")

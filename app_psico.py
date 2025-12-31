import streamlit as st
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import pandas as pd # Ci serve per la tabella

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Diario Psico", page_icon="🟢", layout="centered")

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
        st.error(f"Errore Secrets: {e}")
        st.stop()

# ==============================================================================
# 2. LOGICA LETTURA DATI (CON TABELLA DI CONTROLLO)
# ==============================================================================
def get_dati_e_prezzi(sh):
    prezzi_memoria = {}
    nomi_anagrafica = []
    log_lettura = [] # Per la tabella di controllo

    # --- LEGGI FOGLIO PAZIENTI ---
    try:
        ws = sh.worksheet("Pazienti")
        dati = ws.get_all_values()
        
        # Salta la riga 1 (intestazione)
        for riga in dati[1:]:
            if len(riga) >= 1:
                nome = riga[0].strip()
                if nome:
                    nomi_anagrafica.append(nome)
                    
                    prezzo_letto = "Nessuno"
                    prezzo_valido = 0.0
                    
                    if len(riga) >= 2:
                        raw = riga[1] # Cosa c'è scritto nella cella
                        try:
                            clean = raw.replace("€", "").replace(",", ".").strip()
                            if clean:
                                prezzo_valido = float(clean)
                                prezzi_memoria[nome] = prezzo_valido
                                prezzo_letto = f"€ {prezzo_valido:.2f}"
                        except:
                            prezzo_letto = "❌ Errore numero"
                    
                    # Aggiungiamo alla lista di controllo
                    log_lettura.append({"Paziente": nome, "Prezzo nel Foglio": prezzo_letto})
                    
    except Exception as e:
        st.error(f"Non trovo il foglio 'Pazienti' o è vuoto! ({e})")

    # --- LEGGI DIARIO (STORICO) ---
    ws_diario = sh.worksheet("Diario")
    dati_diario = ws_diario.get_all_values()
    
    # Crea set di attivi
    pazienti_recenti = set()
    oggi = datetime.date.today()
    
    for riga in dati_diario[1:]:
        if len(riga) > 3:
            d_str, nome = riga[0], riga[1].strip()
            # Se nello storico c'è un prezzo diverso, aggiorniamo la memoria
            p_str = riga[3].replace("€", "").replace(",", ".").strip()
            
            if nome and d_str:
                try:
                    dt = datetime.datetime.strptime(d_str, "%d/%m/%Y").date()
                    if (oggi - dt).days <= 90:
                        pazienti_recenti.add(nome)
                    
                    # Lo storico sovrascrive l'anagrafica (se c'è un prezzo valido)
                    if p_str:
                        v = float(p_str)
                        if v > 0:
                            prezzi_memoria[nome] = v
                except:
                    pass

    # Unisce le liste
    lista_finale = list(set(nomi_anagrafica + list(pazienti_recenti)))
    lista_finale.sort()
    
    return lista_finale, prezzi_memoria, log_lettura, ws_diario

# ==============================================================================
# 3. INTERFACCIA
# ==============================================================================
st.title("🟢 DIARIO AGGIORNATO") # <--- SE NON VEDI QUESTO TITOLO, L'APP E' VECCHIA

sh = get_db()
attivi, prezzi, log_dati, ws_diario = get_dati_e_prezzi(sh)

# --- BLOCCO DI CONTROLLO (Visibile subito) ---
with st.expander("🔍 CONTROLLO PREZZI (Clicca qui se non vedi i prezzi)", expanded=True):
    if len(log_dati) > 0:
        st.write("Ecco cosa ho letto nel foglio 'Pazienti':")
        st.dataframe(pd.DataFrame(log_dati)) # Mostra la tabella
    else:
        st.warning("⚠️ Non ho letto nessun nome nel foglio 'Pazienti'. Controlla di aver scritto nella colonna A e B.")

# --- FORM ---
st.divider()
data = st.date_input("Data", datetime.date.today(), format="DD/MM/YYYY")
paziente = st.selectbox("Seleziona Paziente", attivi) if attivi else st.text_input("Nome Paziente")

# Recupera prezzo
prezzo_suggerito = 0.0
if paziente in prezzi:
    prezzo_suggerito = prezzi[paziente]

c1, c2 = st.columns(2)
with c1:
    tipo = st.radio("Tipo", ["Presenza", "Online"])
with c2:
    valore = st.number_input("Prezzo (€)", value=prezzo_suggerito, step=5.0)

note = st.text_area("Note")

if st.button("💾 REGISTRA", type="primary", use_container_width=True):
    if paziente and valore > 0:
        ws_diario.append_row([
            data.strftime("%d/%m/%Y"), 
            paziente, 
            tipo, 
            f"{valore:.2f}".replace(".", ","), 
            note, 
            "DA FARE"
        ])
        st.success("Salvato!")
        time.sleep(1)
        st.rerun()

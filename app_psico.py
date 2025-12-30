import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

st.set_page_config(layout="wide")

# TITOLO GIGANTE PER CONFERMARE L'AGGIORNAMENTO
st.title("🛠️ PAGINA DI TEST CONNESSIONE")
st.subheader("Se leggi questo, il codice è aggiornato!")

# 1. CONNESSIONE
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["psico_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # Apre il foglio
    sh = client.open_by_url(st.secrets["psico"]["spreadsheet_url"])
    st.success("✅ Connessione al File Google riuscita!")
except Exception as e:
    st.error(f"❌ Errore Connessione: {e}")
    st.stop()

# 2. LETTURA FOGLIO PAZIENTI
st.write("---")
st.write("### Tentativo lettura foglio 'Pazienti'...")

try:
    ws = sh.worksheet("Pazienti")
    st.success("✅ Foglio 'Pazienti' trovato!")
    
    # Legge tutto il contenuto grezzo
    dati = ws.get_all_values()
    
    st.write(f"Ho trovato {len(dati)} righe totali.")
    
    if len(dati) > 0:
        st.write("Ecco esattamente cosa vedo nelle celle (Tabella Grezza):")
        # Mostra i dati come tabella
        df = pd.DataFrame(dati)
        st.dataframe(df)
        
        st.write("---")
        st.write("### Analisi Prezzi (Colonna B)")
        # Prova a leggere i prezzi
        for i, riga in enumerate(dati[1:]): # Salta intestazione
            nome = riga[0] if len(riga) > 0 else "NOME MANCANTE"
            prezzo_raw = riga[1] if len(riga) > 1 else "VUOTO"
            
            msg = f"Riga {i+2}: Paziente **{nome}** - Prezzo letto: **'{prezzo_raw}'**"
            
            # Test di conversione numero
            try:
                p_clean = prezzo_raw.replace("€", "").replace(",", ".").strip()
                valore = float(p_clean)
                st.info(f"{msg} -> ✅ Numero valido: {valore}")
            except:
                st.error(f"{msg} -> ❌ Non riesco a capire che numero sia.")
                
    else:
        st.warning("Il foglio 'Pazienti' è completamente bianco!")

except Exception as e:
    st.error(f"❌ ERRORE LETTURA FOGLIO PAZIENTI: {e}")
    st.info("Suggerimento: Controlla che il foglio si chiami esattamente 'Pazienti' (con la P maiuscola).")

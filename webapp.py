import streamlit as st
import datetime
import csv
import io

# --- 1. CONFIGURAZIONE & LOGICA ---
# Prezzi modificati: Prima Spesa a 0
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
    ("Prima Spesa", 0),  # PREZZO ZERO
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

# --- FUNZIONI MATEMATICHE ---
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

# --- INTERFACCIA WEB ---
st.set_page_config(page_title="Preventivi Galbino", page_icon="🏰")

st.title("🏰 Castello di Galbino")
st.subheader("Calcolatore Preventivi")

# --- 1. INPUT DATI ---
with st.container():
    st.markdown("### 📅 Dati Soggiorno")
    col1, col2 = st.columns(2)
    with col1:
        cliente = st.text_input("Nome Cliente")
        checkin = st.date_input("Check-In", datetime.date.today())
    with col2:
        ospiti = st.number_input("Ospiti a Dormire", min_value=1, value=10)
        checkout = st.date_input("Check-Out", datetime.date.today() + datetime.timedelta(days=3))

# --- 2. SERVIZI EXTRA ---
st.markdown("### 🍷 Servizi & Wedding")
st.info("Compila solo i servizi richiesti. Lascia a 0 gli altri.")

servizi_selezionati = []
totale_servizi = 0

for nome, prezzo_def in LISTA_SERVIZI:
    # MODIFICA: Titolo pulito senza prezzo
    with st.expander(f"{nome}"):
        
        # CASO 1: WEDDING FEE
        if "Wedding" in nome:
            c1, c2 = st.columns(2)
            p_unit = c1.number_input(f"Prezzo {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = c2.number_input("Numero Invitati", min_value=0, value=0, key=f"x_{nome}")
            qta = 1 
        
        # CASO 2: PRIMA SPESA (Solo inserimento costo totale)
        elif "Prima Spesa" in nome:
            # Qui mostriamo solo il prezzo. Pax e Qta sono fissi a 1.
            p_unit = st.number_input(f"Costo Totale Servizio/Scontrino", value=0.0, key=f"p_{nome}")
            pax = 1
            qta = 1
            # Se l'utente lascia 0.0, non viene aggiunto nulla. 
            # Se mette es. 100.0, il sistema calcolerà 100 * 1 * 1.

        # CASO 3: STANDARD
        else:
            c1, c2, c3 = st.columns(3)
            p_unit = c1.number_input(f"Prezzo {nome}", value=prezzo_def, key=f"p_{nome}")
            pax = c2.number_input(f"Pax", min_value=0, value=0, key=f"x_{nome}")
            qta = c3.number_input(f"Qta/Volte", min_value=0, value=0, key=f"q_{nome}")
        
        # LOGICA CALCOLO COMUNE
        # Nota: per Prima Spesa, pax e qta sono 1. Quindi se p_unit > 0 entra qui.
        if pax > 0 and qta > 0 and p_unit > 0:
            sub = p_unit * pax * qta
            totale_servizi += sub
            
            # Formattazione stringhe diversa per pulizia
            if "Wedding" in nome:
                 servizi_selezionati.append(f"{nome}: €{p_unit} x {pax} invitati = €{sub:.2f}")
            elif "Prima Spesa" in nome:
                 servizi_selezionati.append(f"{nome}: €{sub:.2f}")
            else:
                 servizi_selezionati.append(f"{nome}: €{p_unit} x {pax}pax x {qta}volte = €{sub:.2f}")

# --- 3. FOOTER ---
st.divider()
col_f1, col_f2 = st.columns(2)
with col_f1:
    sconto = st.number_input("Sconto Manuale (€)", min_value=0.0, step=50.0)
with col_f2:
    note = st.text_area("Note interne")

# --- 4. CALCOLO ---
if st.button("CALCOLA PREVENTIVO", type="primary", use_container_width=True):
    notti = (checkout - checkin).days
    
    if notti < MIN_STAY:
        st.error(f"⚠️ Soggiorno minimo {MIN_STAY} notti. Tu hai selezionato {notti} notti.")
    elif notti <= 0:
        st.error("⚠️ La data di Check-Out deve essere dopo il Check-In!")
    else:
        costo_affitto, log_affitto = calcola_soggiorno(checkin, notti, ospiti)
        
        if costo_affitto is None: 
            st.error(f"❌ {log_affitto}")
        else:
            preventivo_txt = []
            totale_gen = 0
            
            # Affitto
            if notti >= 7:
                costo_affitto *= (1 - SCONTO_LUNGA_DURATA)
                preventivo_txt.append(f"Affitto {notti} notti (Sconto 15%): €{costo_affitto:.2f}")
            else:
                preventivo_txt.append(f"Affitto {notti} notti: €{costo_affitto:.2f}")
            totale_gen += costo_affitto
            
            # Pulizie
            totale_gen += 600
            preventivo_txt.append("Pulizie Finali: €600.00")
            
            # Servizi
            totale_gen += totale_servizi
            preventivo_txt.extend(servizi_selezionati)
            
            # Sconto
            if sconto > 0:
                totale_gen -= sconto
                preventivo_txt.append(f"Sconto Manuale: -€{sconto:.2f}")
            
            # OUTPUT
            st.success(f"✅ TOTALE STIMATO: € {totale_gen:,.2f}")
            
            with st.expander("📝 Visualizza Dettagli Completi", expanded=True):
                for riga in preventivo_txt:
                    st.write(f"- {riga}")
                if note:
                    st.info(f"Note: {note}")

            # FILE CSV
            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(["Data", "Cliente", "CheckIn", "Notti", "Totale", "Dettagli", "Note"])
            writer.writerow([
                datetime.date.today(), cliente, checkin, notti, 
                f"{totale_gen:.2f}", " | ".join(preventivo_txt), note
            ])
            
            st.download_button(
                label="📥 Scarica CSV",
                data=csv_buffer.getvalue(),
                file_name=f"Prev_{cliente}_{datetime.date.today()}.csv",
                mime="text/csv",
                use_container_width=True
            )
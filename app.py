import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
from datetime import datetime

st.set_page_config(page_title="Statisztika Kezelő Web", layout="wide")

# ================= NYOMTATÁSI CSS =================
st.markdown("""
    <style>
    @media print {
        [data-testid="stSidebar"], 
        .stForm, 
        button, 
        [data-testid="stHeader"] {
            display: none !important;
        }
        .main .block-container {
            padding: 0 !important;
            max-width: 100% !important;
        }
        .js-plotly-plot .plotly .main-svg {
            shape-rendering: geometricPrecision !important;
            text-rendering: geometricPrecision !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ================= JELSZÓ BEÁLLÍTÁSA =================
SITE_PASSWORD = "titkosjelszo2026"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    st.markdown("<h2 style='text-align: center;'>🔐 Védett Oldal - Bejelentkezés</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            entered_password = st.text_input("Add meg a jelszót az oldal megtekintéséhez:", type="password")
            submit_button = st.form_submit_button("Belépés")
            
            if submit_button:
                if entered_password == SITE_PASSWORD:
                    st.session_state.authenticated = True
                    st.success("Sikeres belépés!")
                    st.rerun()
                else:
                    st.error("❌ Hibás jelszó! Próbáld újra.")

if not st.session_state.authenticated:
    check_password()
    st.stop()

# ================= ADATTÁROLÁS =================
DB_FILE = "statisztikak.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "data": {
            "Bruttó Beérkezett Bevétel (Ft)": [
                ["2026-08-06", 1200000],
                ["2026-08-13", 1450000],
                ["2026-08-20", 1100000],
                ["2026-08-27", 1600000],
                ["2026-09-03", 1550000],
                ["2026-09-10", 1800000],
                ["2026-09-17", 1300000],
                ["2026-09-24", 2100000],
                ["2026-10-01", 2250000]
            ]
        },
        "settings": {}
    }

def save_data(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

if "db" not in st.session_state:
    st.session_state.db = load_data()

db = st.session_state.db

# ================= OLDALSÁV =================
st.sidebar.header("📊 STATISZTIKA BEÁLLÍTÁSOK")

if st.sidebar.button("🚪 Kijelentkezés"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.markdown("---")

stat_names = list(db.get("data", {}).keys())
if not stat_names:
    db["data"] = {"Bruttó Beérkezett Bevétel (Ft)": []}
    stat_names = list(db["data"].keys())

selected_stat = st.sidebar.selectbox("Válassz Statisztikát:", stat_names)

with st.sidebar.expander("➕ Új statisztika létrehozása"):
    new_stat_name = st.text_input("Új statisztika neve:")
    if st.button("Létrehozás"):
        if new_stat_name and new_stat_name not in db["data"]:
            db["data"][new_stat_name] = []
            save_data(db)
            st.success(f"Létrehozva: {new_stat_name}")
            st.rerun()

stat_settings = db.get("settings", {}).get(selected_stat, {})

period = st.sidebar.radio("Időszak bontás:", ["Napi", "Heti (Cs)", "Havi"], index=1)

st.sidebar.subheader("📐 Érték Tengely")
col_min, col_max, col_step = st.sidebar.columns(3)

with col_min:
    ymin = st.text_input("Min", value=stat_settings.get("ymin", ""))
with col_max:
    ymax = st.text_input("Max", value=stat_settings.get("ymax", ""))
with col_step:
    ystep = st.text_input("Lépés", value=stat_settings.get("ystep", ""))

if st.sidebar.button("💾 Beállítások Mentése"):
    if "settings" not in db:
        db["settings"] = {}
    db["settings"][selected_stat] = {
        "period": period,
        "ymin": ymin,
        "ymax": ymax,
        "ystep": ystep
    }
    save_data(db)
    st.sidebar.success("Beállítások elmentve!")

col_left, col_right = st.columns([1, 2])

# BAL OLDAL: Adatbevitel és Táblázat
with col_left:
    st.subheader("➕ Új adat hozzáadása")
    with st.form("add_data_form", clear_on_submit=True):
        input_date = st.date_input("Dátum")
        input_val = st.number_input("Érték (Ft)", min_value=0.0, step=10000.0)
        submit_btn = st.form_submit_button("Adat Hozzáadása")

        if submit_btn:
            date_str = input_date.strftime("%Y-%m-%d")
            db["data"][selected_stat].append([date_str, input_val])
            save_data(db)
            st.success("Adat elmentve!")
            st.rerun()

    st.subheader("📋 Adat-táblázat")
    if selected_stat in db["data"] and db["data"][selected_stat]:
        df = pd.DataFrame(db["data"][selected_stat], columns=["Dátum", "Mért Érték (Ft)"])
        df = df.sort_values(by="Dátum")
        
        st.dataframe(df, use_container_width=True)

        delete_idx = st.number_input("Törlendő sor száma (index):", min_value=0, max_value=len(df)-1, step=1)
        if st.button("🔴 Sor Törlése"):
            db["data"][selected_stat].pop(delete_idx)
            save_data(db)
            st.rerun()

# JOBB OLDAL: Interaktív Grafikon
with col_right:
    if selected_stat in db["data"] and db["data"][selected_stat]:
        raw_items = sorted(db["data"][selected_stat], key=lambda x: str(x[0]))
        
        # Kezdő és záró dátum kiszámítása
        date_range_str = ""
        if len(raw_items) > 0:
            try:
                start_d = datetime.strptime(raw_items[0][0], "%Y-%m-%d").strftime("%Y.%m.%d.")
                end_d = datetime.strptime(raw_items[-1][0], "%Y-%m-%d").strftime("%Y.%m.%d.")
                date_range_str = f"({start_d} - {end_d})"
            except Exception:
                date_range_str = f"({raw_items[0][0]} - {raw_items[-1][0]})"

        fig = go.Figure()

        # Összekötő vonalak (Csak akkor ZÖLD, ha szigorúan növekszik az érték, egyébként PIROS)
        for i in range(len(raw_items) - 1):
            x1, y1 = raw_items[i][0], raw_items[i][1]
            x2, y2 = raw_items[i+1][0], raw_items[i+1][1]
            
            color = "#116B3A" if y2 > y1 else "#991B1B"
            
            fig.add_trace(go.Scatter(
                x=[x1, x2],
                y=[y1, y2],
                mode='lines',
                line=dict(color=color, width=4),
                showlegend=False,
                hoverinfo='skip'
            ))

        # Adatpontok és értékek
        x_vals = [item[0] for item in raw_items]
        y_vals = [item[1] for item in raw_items]
        text_vals = [f"{int(val):,} Ft".replace(",", " ") for val in y_vals]

        # Magyar dátumok
        hu_months = {
            1: "jan.", 2: "febr.", 3: "márc.", 4: "ápr.",
            5: "máj.", 6: "jún.", 7: "júl.", 8: "aug.",
            9: "szept.", 10: "okt.", 11: "nov.", 12: "dec."
        }
        x_formatted = []
        for x in x_vals:
            try:
                dt = datetime.strptime(str(x), "%Y-%m-%d")
                x_formatted.append(f"{dt.year}. {hu_months[dt.month]} {dt.day}.")
            except Exception:
                x_formatted.append(str(x))

        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers+text',
            marker=dict(size=10, color="#1E293B"),
            text=text_vals,
            textposition="top center",
            textfont=dict(size=14, color="#000000", family="Arial Black"),
            showlegend=False
        ))

        layout_args = dict(
            title=dict(
                text=f"<b>{selected_stat}</b><br><span style='font-size: 18px; color: #1E293B;'>Dátum: {date_range_str}</span>",
                x=0.5,
                xref="paper",
                xanchor='center',
                yanchor='top',
                font=dict(size=28, color="#000000")
            ),
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(t=100, b=60, l=70, r=40),
            # X tengely - Halványabb, vastagabb rácsvonalak
            xaxis=dict(
                title=dict(text="<b>Dátum</b>", font=dict(color="#000000", size=18)),
                tickmode="array",
                tickvals=x_vals,
                ticktext=x_formatted,
                showgrid=True,
                gridcolor="#F1F5F9",
                gridwidth=2.5,
                tickfont=dict(color="#000000", size=15, family="Arial Black"),
                showline=True,
                linecolor="#000000",
                linewidth=2
            ),
            # Y tengely - Halványabb, vastagabb rácsvonalak
            yaxis=dict(
                title=dict(text="<b>Érték (Ft)</b>", font=dict(color="#000000", size=18)),
                showgrid=True,
                gridcolor="#F1F5F9",
                gridwidth=2.5,
                tickfont=dict(color="#000000", size=16, family="Arial Black"),
                showline=True,
                linecolor="#000000",
                linewidth=2
            )
        )

        try:
            if ymin and ymax:
                layout_args["yaxis"]["range"] = [float(ymin), float(ymax)]
            if ystep:
                layout_args["yaxis"]["dtick"] = float(ystep)
        except Exception:
            pass

        fig.update_layout(**layout_args)

        config = {
            'toImageButtonOptions': {
                'format': 'png',
                'filename': f'{selected_stat}_grafikon',
                'height': 1200,
                'width': 1800,
                'scale': 3
            },
            'displayModeBar': True
        }

        st.plotly_chart(fig, use_container_width=True, config=config)

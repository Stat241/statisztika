import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os

st.set_page_config(page_title="Statisztika Kezelő Web", layout="wide")

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
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
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

# ================= FŐOLDAL =================
st.title("📈 Webes Statisztika Dashboard")

col_left, col_right = st.columns([1, 2])

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

    st.subheader("📋 Adatok")
    if selected_stat in db["data"] and db["data"][selected_stat]:
        df = pd.DataFrame(db["data"][selected_stat], columns=["Dátum", "Mért Érték"])
        df = df.sort_values(by="Dátum")
        
        st.dataframe(df, use_container_width=True)

        delete_idx = st.number_input("Törlendő sor száma (index):", min_value=0, max_value=len(df)-1, step=1)
        if st.button("🔴 Sor Törlése"):
            db["data"][selected_stat].pop(delete_idx)
            save_data(db)
            st.rerun()

with col_right:
    st.subheader(f"📊 {selected_stat.upper()}")
    
    if selected_stat in db["data"] and db["data"][selected_stat]:
        raw_items = sorted(db["data"][selected_stat], key=lambda x: x[0])
        
        fig = go.Figure()

        for i in range(len(raw_items) - 1):
            x1, y1 = raw_items[i][0], raw_items[i][1]
            x2, y2 = raw_items[i+1][0], raw_items[i+1][1]
            
            color = "#116B3A" if y2 >= y1 else "#991B1B"
            
            fig.add_trace(go.Scatter(
                x=[x1, x2],
                y=[y1, y2],
                mode='lines+markers',
                line=dict(color=color, width=4),
                marker=dict(size=8, color=color),
                showlegend=False
            ))

        layout_args = dict(
            plot_bgcolor="white",
            paper_bgcolor="white",
            xaxis=dict(title="Dátum", showgrid=True, gridcolor="#E2E8F0"),
            yaxis=dict(title="Érték", showgrid=True, gridcolor="#E2E8F0")
        )

        try:
            if ymin and ymax:
                layout_args["yaxis"]["range"] = [float(ymin), float(ymax)]
            if ystep:
                layout_args["yaxis"]["dtick"] = float(ystep)
        except ValueError:
            pass

        fig.update_layout(**layout_args)
        st.plotly_chart(fig, use_container_width=True)

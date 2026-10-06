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

# ================= FELHASZNÁLÓK KEZELÉSE (JSON ALAPÚ) =================
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    default_users = {
        "admin": {
            "password": "titkosjelszo2026",
            "allowed_stats": ["*"]
        }
    }
    save_users(default_users)
    return default_users

def save_users(users_data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

if "users" not in st.session_state:
    st.session_state.users = load_users()

USERS = st.session_state.users

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

def check_login():
    st.markdown("<h2 style='text-align: center;'>🔐 Bejelentkezés a Statisztika Rendszerbe</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Felhasználónév:")
            password = st.text_input("Jelszó:", type="password")
            submit_button = st.form_submit_button("Belépés")
            
            if submit_button:
                current_users_db = load_users()
                if username in current_users_db and current_users_db[username]["password"] == password:
                    st.session_state.authenticated = True
                    st.session_state.current_user = username
                    st.success(f"Sikeres belépés, üdvözlünk {username}!")
                    st.rerun()
                else:
                    st.error("❌ Hibás felhasználónév vagy jelszó!")

if not st.session_state.authenticated:
    check_login()
    st.stop()

# ================= ADATTÁROLÁS ÉS ARCHIVÁLÁS =================
DB_FILE = "statisztikak.json"
ARCHIVE_FILE = "archivum.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "stats": {
            "Bruttó Beérkezett Bevétel": {
                "unit": "Ft",
                "data": [
                    ["2026-07-23", 650000],
                    ["2026-07-30", 97500],
                    ["2026-08-06", 97500],
                    ["2026-08-13", 547500],
                    ["2026-08-20", 347500],
                    ["2026-08-27", 1570799],
                    ["2026-09-03", 2350000],
                    ["2026-09-10", 390000],
                    ["2026-09-17", 4722200],
                    ["2026-09-24", 0],
                    ["2026-10-01", 945000]
                ]
            },
            "Ügyfelek száma": {
                "unit": "fő",
                "data": [
                    ["2026-08-08", 5],
                    ["2026-08-15", 12],
                    ["2026-08-25", 18],
                    ["2026-08-30", 25],
                    ["2026-09-13", 34]
                ]
            }
        },
        "settings": {}
    }

def save_data(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def load_archive():
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_archive(archive_data):
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)

if "db" not in st.session_state:
    st.session_state.db = load_data()

db = st.session_state.db

if "stats" not in db:
    old_data = db.get("data", {})
    db["stats"] = {}
    for k, v in old_data.items():
        db["stats"][k] = {"unit": "Ft", "data": v}
    save_data(db)

USERS = load_users()
current_user_info = USERS.get(st.session_state.current_user, {"allowed_stats": []})
allowed_stat_names = current_user_info["allowed_stats"]

all_stat_names = list(db["stats"].keys())

if "*" in allowed_stat_names:
    stat_names = all_stat_names
else:
    stat_names = [s for s in all_stat_names if s in allowed_stat_names]

if not stat_names:
    st.warning("⚠️ Ehhez a felhasználóhoz nincs hozzárendelve látható statisztika.")
    if st.sidebar.button("🚪 Kijelentkezés"):
        st.session_state.authenticated = False
        st.session_state.current_user = None
        st.rerun()
    st.stop()

# ================= OLDALSÁV =================
st.sidebar.header("📊 STATISZTIKA BEÁLLÍTÁSOK")
st.sidebar.info(f"Bejelentkezve: **{st.session_state.current_user}**")

if st.sidebar.button("🚪 Kijelentkezés"):
    st.session_state.authenticated = False
    st.session_state.current_user = None
    st.rerun()

st.sidebar.markdown("---")

# --- ADMIN FELÜLET ---
if "*" in allowed_stat_names:
    with st.sidebar.expander("👥 Felhasználók & Jogosultságok"):
        st.write("### ➕ Új felhasználó felvétele")
        new_u_name = st.text_input("Új felhasználónév:", key="new_u_name")
        new_u_pass = st.text_input("Jelszó:", type="password", key="new_u_pass")
        
        available_stats_for_assign = list(db["stats"].keys())
        is_admin_check = st.checkbox("Teljes admin jog (*)", key="new_u_is_admin")
        
        assigned_stats = []
        if not is_admin_check:
            assigned_stats = st.multiselect("Elérhető statisztikák:", options=available_stats_for_assign, key="new_u_multiselect")
        else:
            assigned_stats = ["*"]

        if st.button("Felhasználó mentése / létrehozása"):
            if new_u_name and new_u_pass:
                USERS[new_u_name] = {
                    "password": new_u_pass,
                    "allowed_stats": assigned_stats
                }
                save_users(USERS)
                st.success(f"'{new_u_name}' sikeresen létrehozva!")
                st.rerun()
            else:
                st.warning("Add meg a nevet és a jelszót!")

        st.markdown("---")
        st.write("### ✏ Felhasználó módosítása")
        edit_user_name = st.selectbox("Válassz szerkesztendő felhasználót:", options=list(USERS.keys()), key="edit_u_select")
        
        if edit_user_name:
            current_u_data = USERS[edit_user_name]
            is_currently_admin = "*" in current_u_data["allowed_stats"]
            
            edit_is_admin = st.checkbox("Teljes admin jog (*)", value=is_currently_admin, key="edit_u_is_admin")
            default_selected_stats = [] if is_currently_admin else [s for s in current_u_data["allowed_stats"] if s in available_stats_for_assign]
            edit_assigned_stats = st.multiselect("Elérhető statisztikák:", options=available_stats_for_assign, default=default_selected_stats, key="edit_u_multiselect")
            edit_new_pass = st.text_input("Új jelszó (ha üresen hagyod, marad a régi):", type="password", key="edit_u_pass")

            if st.button("Módosítások mentése"):
                if edit_is_admin:
                    USERS[edit_user_name]["allowed_stats"] = ["*"]
                else:
                    USERS[edit_user_name]["allowed_stats"] = edit_assigned_stats
                
                if edit_new_pass.strip():
                    USERS[edit_user_name]["password"] = edit_new_pass
                    
                save_users(USERS)
                st.success(f"'{edit_user_name}' adatai sikeresen frissítve!")
                st.rerun()

        st.markdown("---")
        st.write("### 🗑️ Felhasználó törlése")
        users_to_delete = [u for u in USERS.keys() if u != st.session_state.current_user]
        if users_to_delete:
            selected_user_to_del = st.selectbox("Válassz törlendő felhasználót:", options=users_to_delete, key="del_u_select")
            if st.button("🔴 Felhasználó Törlése"):
                if selected_user_to_del in USERS:
                    del USERS[selected_user_to_del]
                    save_users(USERS)
                    st.success(f"'{selected_user_to_del}' törölve!")
                    st.rerun()
        else:
            st.info("Nincs más törölhető felhasználó.")

        st.markdown("---")

with st.sidebar.expander("📂 Régi / Archív statisztikák betöltése"):
    archive_db = load_archive()
    if "*" in allowed_stat_names:
        archive_names = list(archive_db.keys())
    else:
        archive_names = [s for s in archive_db.keys() if s in allowed_stat_names]
    
    if archive_names:
        selected_archived_stat = st.selectbox("Válassz az archívumból:", options=archive_names, key="archive_selectbox")
        if st.button("Archivált statisztika átemelése aktívba"):
            if selected_archived_stat in archive_db:
                db["stats"][selected_archived_stat] = archive_db[selected_archived_stat]
                save_data(db)
                st.success(f"'{selected_archived_stat}' sikeresen visszatöltve!")
                st.rerun()
    else:
        st.info("Még nincsenek elérhető archivált elemek.")

if "selected_stat_override" in st.session_state and st.session_state["selected_stat_override"] in stat_names:
    default_stat_idx = stat_names.index(st.session_state["selected_stat_override"])
else:
    default_stat_idx = 0

selected_stat = st.sidebar.selectbox("Aktív Statisztika Szűrése / Kiválasztása:", stat_names, index=default_stat_idx)
st.session_state["selected_stat_override"] = selected_stat

with st.sidebar.expander("➕ Új statisztika létrehozása"):
    new_stat_name = st.text_input("Statisztika neve:", placeholder="pl. Ügyfelek száma")
    new_stat_unit = st.text_input("Mértékegység / Kategória:", placeholder="pl. fő, db, Ft")
    if st.button("Létrehozás"):
        if new_stat_name:
            if new_stat_name not in db["stats"]:
                db["stats"][new_stat_name] = {"unit": new_stat_unit, "data": []}
                save_data(db)
                st.success(f"Létrehozva: {new_stat_name} ({new_stat_unit})")
                st.rerun()
            else:
                st.warning("Ilyen nevű statisztika már létezik!")

st.sidebar.markdown("---")
if st.sidebar.button("📦 Jelenlegi statisztika archiválása"):
    archive_db = load_archive()
    archive_db[selected_stat] = db["stats"][selected_stat]
    save_archive(archive_db)
    st.sidebar.success(f"'{selected_stat}' sikeresen archiválva!")

current_unit = db["stats"][selected_stat].get("unit", "")
stat_settings = db.get("settings", {}).get(selected_stat, {})

period = st.sidebar.radio("Időszak bontás:", ["Napi", "Heti (Cs)", "Havi"], index=1)

# --- AKKUMULÁLT ÉRTÉK BEÁLLÍTÁSOK ---
st.sidebar.subheader("📈 Akkumulált érték")
enable_accumulated = st.sidebar.checkbox("Akkumulált érték számítása", value=False)
accumulated_start_val = 0.0
if enable_accumulated:
    accumulated_start_val = st.sidebar.number_input("Kezdő érték:", value=0.0, step=1.0)

# --- DÁTUM SZŰRÉS ---
st.sidebar.subheader("🗓 Dátum szerinti szűrés")
enable_date_filter = st.sidebar.checkbox("Időszak szűkítése", value=False)

start_date_filter, end_date_filter = None, None
if enable_date_filter:
    stat_data_raw = db["stats"][selected_stat]["data"]
    if stat_data_raw:
        all_dates = [datetime.strptime(item[0], "%Y-%m-%d").date() for item in stat_data_raw]
        min_d, max_d = min(all_dates), max(all_dates)
        start_date_filter = st.sidebar.date_input("Kezdő dátum", value=min_d, min_value=min_d, max_value=max_d)
        end_date_filter = st.sidebar.date_input("Záró dátum", value=max_d, min_value=min_d, max_value=max_d)

st.sidebar.subheader("📐 Érték Tengely & Vonalak")
col_min, col_max, col_step = st.sidebar.columns(3)

with col_min:
    ymin = st.text_input("Min", value=stat_settings.get("ymin", ""))
with col_max:
    ymax = st.text_input("Max", value=stat_settings.get("ymax", ""))
with col_step:
    ystep = st.text_input("Lépés", value=stat_settings.get("ystep", ""))

show_ref_line = st.sidebar.checkbox("Referencia vonal megjelenítése", value=stat_settings.get("show_ref", True))
ref_line_val = st.sidebar.text_input(
    "Referencia vonal értéke:", 
    value=stat_settings.get("ref_line", ""),
    placeholder="Hagyd üresen az utolsó adathoz"
)

if st.sidebar.button("💾 Beállítások Mentése"):
    if "settings" not in db:
        db["settings"] = {}
    db["settings"][selected_stat] = {
        "period": period,
        "ymin": ymin,
        "ymax": ymax,
        "ystep": ystep,
        "show_ref": show_ref_line,
        "ref_line": ref_line_val
    }
    save_data(db)
    st.sidebar.success("Beállítások elmentve!")

col_left, col_right = st.columns([1, 2])

# BAL OLDAL: Adatbevitel és Táblázat (Legfrissebb felül)
with col_left:
    st.subheader(f"➕ Új adat hozzáadása ({selected_stat})")
    with st.form("add_data_form", clear_on_submit=True):
        input_date = st.date_input("Dátum")
        input_val = st.number_input(f"Érték ({current_unit})", min_value=0.0, step=1.0)
        submit_btn = st.form_submit_button("Adat Hozzáadása")

        if submit_btn:
            date_str = input_date.strftime("%Y-%m-%d")
            db["stats"][selected_stat]["data"].append([date_str, input_val])
            save_data(db)
            st.success("Adat elmentve!")
            st.rerun()

    st.subheader("📋 Adat-táblázat")
    stat_data_list = db["stats"][selected_stat]["data"]
    
    if stat_data_list:
        filtered_items = []
        for item in stat_data_list:
            item_date = datetime.strptime(item[0], "%Y-%m-%d").date()
            if enable_date_filter and start_date_filter and end_date_filter:
                if start_date_filter <= item_date <= end_date_filter:
                    filtered_items.append(item)
            else:
                filtered_items.append(item)

        df = pd.DataFrame(filtered_items, columns=["Dátum", f"Érték ({current_unit})"])
        if not df.empty:
            df = df.sort_values(by="Dátum", ascending=False)
            st.dataframe(df, use_container_width=True)

        delete_idx = st.number_input("Törlendő sor száma (index):", min_value=0, max_value=len(df)-1 if len(df) > 0 else 0, step=1)
        if st.button("🔴 Sor Törlése") and len(df) > 0:
            target_to_delete = df.iloc[int(delete_idx)].tolist()
            if target_to_delete in db["stats"][selected_stat]["data"]:
                db["stats"][selected_stat]["data"].remove(target_to_delete)
                save_data(db)
                st.rerun()

# JOBB OLDAL: Interaktív Grafikon (Régi balra, függőleges dátum: 2026 elöl)
with col_right:
    stat_data_list = db["stats"][selected_stat]["data"]
    if stat_data_list:
        raw_items = []
        for item in stat_data_list:
            item_date = datetime.strptime(item[0], "%Y-%m-%d").date()
            if enable_date_filter and start_date_filter and end_date_filter:
                if start_date_filter <= item_date <= end_date_filter:
                    raw_items.append(item)
            else:
                raw_items.append(item)

        # Időrendi sorrend: legrégebbi bal oldalt (növekvő)
        raw_items = sorted(raw_items, key=lambda x: str(x[0]))
        
        date_range_str = ""
        if len(raw_items) > 0:
            try:
                start_d = datetime.strptime(raw_items[0][0], "%Y-%m-%d").strftime("%Y. %B %d.")
                end_d = datetime.strptime(raw_items[-1][0], "%Y-%m-%d").strftime("%Y. %B %d.")
                date_range_str = f"({start_d} - {end_d})"
            except Exception:
                date_range_str = f"({raw_items[0][0]} - {raw_items[-1][0]})"

        fig = go.Figure()

        if len(raw_items) > 0:
            x_numeric = list(range(len(raw_items)))
            y_vals = [item[1] for item in raw_items]

            for i in range(len(raw_items) - 1):
                x1, y1 = x_numeric[i], y_vals[i]
                x2, y2 = x_numeric[i+1], y_vals[i+1]
                
                color = "#00C853" if y2 > y1 else "#FF1744"
                
                fig.add_trace(go.Scatter(
                    x=[x1, x2],
                    y=[y1, y2],
                    mode='lines',
                    line=dict(color=color, width=6),
                    showlegend=False,
                    hoverinfo='skip'
                ))

            line_target_val = None
            if show_ref_line:
                if ref_line_val:
                    try:
                        line_target_val = float(ref_line_val)
                    except ValueError:
                        line_target_val = y_vals[-1]
                else:
                    line_target_val = y_vals[-1]

                if line_target_val is not None:
                    val_str = f"{int(line_target_val):,}".replace(",", " ") if line_target_val.is_integer() else f"{line_target_val}"
                    formatted_ref_text = f" {val_str} {current_unit}".strip()
                    fig.add_hline(
                        y=line_target_val,
                        line_dash="solid",
                        line_color="#FF1744",
                        line_width=6,
                        annotation_text=formatted_ref_text,
                        annotation_position="bottom right",
                        annotation_font=dict(size=21, color="#FF1744", family="Arial Black")
                    )

            formatted_texts = []
            running_acc = accumulated_start_val
            for val in y_vals:
                v_str = f"{int(val):,}".replace(",", " ") if val.is_integer() else f"{val}"
                base_text = f"{v_str} {current_unit}".strip()
                
                if enable_accumulated:
                    running_acc += val
                    acc_str = f"{int(running_acc):,}".replace(",", " ") if running_acc.is_integer() else f"{running_acc}"
                    base_text += f" ({acc_str} {current_unit})".strip()
                
                formatted_texts.append(base_text)

            hu_months_full = {
                1: "Január", 2: "Február", 3: "Március", 4: "Április",
                5: "Május", 6: "Június", 7: "Július", 8: "Augusztus",
                9: "Szeptember", 10: "Október", 11: "November", 12: "December"
            }
            
            # ITT MÓDOSÍTVA: Évszám elöl, majd hónap és nap, függőleges (-90 fokos) elrendezéssel
            x_dates = [datetime.strptime(str(item[0]), "%Y-%m-%d") for item in raw_items]
            x_formatted = [f"{d.year}. {hu_months_full[d.month]} {d.day}." for d in x_dates]

            fig.add_trace(go.Scatter(
                x=x_numeric,
                y=y_vals,
                mode='markers+text',
                marker=dict(size=14, color="#1E293B"),
                text=formatted_texts,
                textposition="top center",
                textfont=dict(size=14, color="#000000", family="Arial Black"),
                showlegend=False
            ))

            layout_args = dict(
                title=dict(
                    text=f"<b>{selected_stat}</b><br><span style='font-size: 26px; color: #1E293B;'>Időszak: {date_range_str}</span>",
                    x=0.5,
                    xref="paper",
                    xanchor='center',
                    yanchor='top',
                    font=dict(size=42, color="#000000")
                ),
                plot_bgcolor="white",
                paper_bgcolor="white",
                margin=dict(t=150, b=150, l=80, r=80),
                xaxis=dict(
                    title=dict(text="", font=dict(color="#000000", size=1)), 
                    tickmode="array",
                    tickvals=x_numeric,
                    ticktext=x_formatted,
                    tickangle=-90,  # Visszaállítva a függőleges (stílusos, áttekinthető) dőlésre
                    showgrid=True,
                    gridcolor="#F1F5F9",
                    gridwidth=2.5,
                    tickfont=dict(color="#000000", size=15, family="Arial Black"),
                    showline=True,
                    linecolor="#000000",
                    linewidth=3,
                    range=[-0.5, len(x_numeric) - 0.5]
                ),
                yaxis=dict(
                    title=dict(text="", font=dict(color="#000000", size=1)), 
                    showgrid=True,
                    gridcolor="#F1F5F9",
                    gridwidth=2.5,
                    tickfont=dict(color="#000000", size=18, family="Arial Black"),
                    showline=True,
                    linecolor="#000000",
                    linewidth=3
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

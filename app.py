import copy
import json
import os
import hashlib
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# ================= OLDAL ALAPBEÁLLÍTÁSAI =================
st.set_page_config(
    page_title="Statisztika Kezelő Rendszer", layout="wide", page_icon="📊"
)

# ================= NYOMTATÁSI CSS =================
st.markdown(
    """
    <style>
    @media print {
        @page {
            size: A4 landscape;
            margin: 5mm !important;
        }
        [data-testid="stSidebar"], 
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-baseweb="tab-list"],
        .stTabs [role="tablist"],
        .stForm, 
        button, 
        iframe,
        hr,
        h1, h2, h3, h4, h5, h6,
        [data-testid="stDataFrame"],
        [data-testid="stDataEditor"],
        .stElementContainer:not(:has(.stPlotlyChart)),
        .no-print {
            display: none !important;
        }
        [data-testid="stMainBlockContainer"] > div:not(:has(.stPlotlyChart)) {
            display: none !important;
        }
        html, body, [data-testid="stAppViewContainer"], .main, .block-container, [data-testid="stVerticalBlock"] {
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
            margin: 0 !important;
            padding: 0 !important;
            background: white !important;
            overflow: visible !important;
        }
        .stPlotlyChart, .js-plotly-plot, .plot-container {
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 auto !important;
            padding: 0 !important;
            page-break-inside: avoid !important;
        }
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ================= ADATTÁROLÁS & FELHASZNÁLÓKEZELÉS =================
DB_FILE = "statisztikak.json"
ARCHIVE_FILE = "archivum.json"
USERS_FILE = "users.json"

def hash_pw(password):
    """SHA-256 jelszó titkosítás."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def load_users():
    """Felhasználók betöltése biztonságos hash ellenőrzéssel és migrációval."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                updated = {}
                changed = False
                for u, val in data.items():
                    if isinstance(val, str):
                        # Régi formátum: csak jelszó string
                        updated[u] = {
                            "password": hash_pw(val),
                            "role": "admin" if u == "admin" else "user",
                            "assigned_stats": [],
                            "assigned_groups": [],
                        }
                        changed = True
                    else:
                        # Titkosítatlan jelszó ellenőrzése (ha nem 64 karakteres hex)
                        if len(val.get("password", "")) != 64:
                            val["password"] = hash_pw(val["password"])
                            changed = True
                        if "assigned_groups" not in val:
                            val["assigned_groups"] = []
                        if "assigned_stats" not in val:
                            val["assigned_stats"] = []
                        updated[u] = val
                
                # Ha migráltunk (titkosítottunk nyílt jelszavakat), rögtön mentsük is el!
                if changed:
                    save_users(updated)
                return updated
        except Exception as e:
            # KRITIKUS JAVÍTÁS: Ha sérült a JSON, NE adjunk alapértelmezett admin hozzáférést!
            st.error(f"🚨 Kritikus hiba a users.json betöltésekor: {e}. A rendszer leáll a biztonság érdekében.")
            st.stop()
            
    # Csak akkor generálunk defaultot, ha a fájl EGYÁLTALÁN NEM létezik.
    default_users = {
        "admin": {
            "password": hash_pw("admin123"), # Titkosítva mentjük
            "role": "admin",
            "assigned_stats": [],
            "assigned_groups": [],
        }
    }
    save_users(default_users)
    return default_users


def save_users(users_dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_dict, f, ensure_ascii=False, indent=2)


def fmt_num(val, unit=""):
    if val is None:
        return ""
    try:
        f_val = float(val)
        if f_val.is_integer():
            s = f"{int(f_val):,}".replace(",", ".")
        else:
            s = f"{f_val}".replace(",", ".")
    except (ValueError, TypeError):
        s = str(val)

    if unit:
        clean_unit = str(unit).strip(".")
        return f"{s} {clean_unit}"
    return s


def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # KRITIKUS JAVÍTÁS: Nincs több csendes elnyelés és demó adat felülírás adatvesztéssel!
            st.error(f"🚨 Kritikus hiba a {DB_FILE} betöltésekor! A fájl sérült. Hiba: {e}. A rendszer leáll az adatok védelme érdekében.")
            st.stop()
            
    return {
        "groups": ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"],
        "stats": {
            "Bruttó Beérkezett Bevétel": {
                "unit": "Ft",
                "group": "Pénzügy",
                "inverted": False,
                "agg_type": "sum",
                "description": "Az adott időszakban a bankszámlára beérkezett bruttó összegek.",
                "data": []
            }
        },
        "settings": {},
    }


def save_data(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# --- BIZTONSÁGOS ADATMÓDOSÍTÓ FUNKCIÓK (Race condition minimalizálása) ---
def safe_append_data(stat_name, date_str, val, note):
    fresh_db = load_data()
    fresh_db["stats"][stat_name]["data"].append([date_str, val, note])
    # Dátum szerinti rendezés
    fresh_db["stats"][stat_name]["data"] = sorted(
        fresh_db["stats"][stat_name]["data"],
        key=lambda x: pd.to_datetime(str(x[0]), format="mixed", errors="coerce")
    )
    save_data(fresh_db)
    st.session_state.db = fresh_db

def safe_update_table(stat_name, new_data):
    fresh_db = load_data()
    fresh_db["stats"][stat_name]["data"] = new_data
    save_data(fresh_db)
    st.session_state.db = fresh_db


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


def calculate_stat_condition(data, survival_line=0, inverted=False):
    if not data or len(data) < 1:
        return "Nincs adat", "gray"

    try:
        sorted_d = sorted(data, key=lambda x: str(x[0]))
        last_val = float(sorted_d[-1][1])

        # Életvonal logikája (fordított statisztikánál az életvonal egy plafon)
        if survival_line > 0:
            if not inverted and last_val < survival_line:
                return "Nem-létezés (Életvonal alatt)", "red"
            elif inverted and last_val > survival_line:
                return "Nem-létezés (Életvonal felett)", "red"

        if len(sorted_d) < 2:
            return "Normál trend", "green"

        window = sorted_d[-4:] if len(sorted_d) >= 4 else sorted_d
        vals = [float(item[1]) for item in window]

        if all(v == 0 for v in vals):
            return "Nem-létezés", "red"

        first_v = vals[0]
        last_v = vals[-1]
        
        # LOGIKAI JAVÍTÁS: Fordított statisztikánál a csökkenés (negatív diff) a jó dolog!
        raw_diff = last_v - first_v
        diff = -raw_diff if inverted else raw_diff

        if diff > 0:
            base = first_v if first_v > 0 else 1.0
            growth_ratio = diff / base
            if growth_ratio >= 0.5:
                return "Bőség trend", "green"
            else:
                return "Normál trend", "green"
        elif diff == 0:
            return "Vészhelyzet trend", "orange"
        else:
            base = first_v if first_v > 0 else 1.0
            drop_ratio = abs(diff) / base
            if drop_ratio >= 0.3:
                return "Veszély trend", "red"
            else:
                return "Vészhelyzet trend", "orange"
    except Exception:
        return "Nincs adat", "gray"


def get_thursday_period_end(dt):
    days_to_thu = 3 - dt.weekday()
    thu_14 = dt.normalize() + pd.Timedelta(days=days_to_thu, hours=14)
    if dt > thu_14:
        thu_14 += pd.Timedelta(days=7)
    return thu_14


# Segédfüggvény a statisztika nevének és egységének megjelenítéséhez
def stat_label(stat_name):
    u = db["stats"].get(stat_name, {}).get("unit", "")
    if u:
        return f"{stat_name} ({u})"
    return stat_name


# ================= BEJELENTKEZÉSI LOGIKA =================
users_db = load_users()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "user_role" not in st.session_state:
    st.session_state.user_role = "user"
if "assigned_stats" not in st.session_state:
    st.session_state.assigned_stats = []
if "assigned_groups" not in st.session_state:
    st.session_state.assigned_groups = []

if not st.session_state.logged_in:
    st.title("Bejelentkezés a Rendszerbe")
    with st.form("login_form"):
        input_user = st.text_input("Felhasználónév:")
        input_pass = st.text_input("Jelszó:", type="password")
        login_btn = st.form_submit_button("Bejelentkezés")

        if login_btn:
            hashed_input = hash_pw(input_pass)
            if (
                input_user in users_db
                and users_db[input_user].get("password") == hashed_input
            ):
                st.session_state.logged_in = True
                st.session_state.username = input_user
                st.session_state.user_role = users_db[input_user].get("role", "user")
                st.session_state.assigned_stats = users_db[input_user].get(
                    "assigned_stats", []
                )
                st.session_state.assigned_groups = users_db[input_user].get(
                    "assigned_groups", []
                )
                st.success("Sikeres bejelentkezés!")
                st.rerun()
            else:
                st.error("Hibás felhasználónév vagy jelszó!")
    st.stop()

# ================= SESSION STATE ADATOK =================
if "db" not in st.session_state:
    st.session_state.db = load_data()
db = st.session_state.db

if "groups" not in db:
    db["groups"] = ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
    save_data(db)

all_stat_names = list(db["stats"].keys())
all_groups = db.get(
    "groups", ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
)

# JOGOSULTSÁG ALAPJÁN ELÉRHETŐ STATISZTIKÁK SZŰRÉSE
if st.session_state.user_role == "admin":
    stat_names = all_stat_names
else:
    user_assigned_s = set(st.session_state.assigned_stats)
    user_assigned_g = set(st.session_state.assigned_groups)

    stat_names = []
    for s in all_stat_names:
        s_group = db["stats"][s].get("group", "Egyéb")
        if s in user_assigned_s or s_group in user_assigned_g:
            stat_names.append(s)

# ================= NAVIGÁCIÓ =================
st.sidebar.title("📌 Navigáció")
role_label = (
    "👑 Adminisztrátor"
    if st.session_state.user_role == "admin"
    else "👤 Sima Felhasználó"
)
st.sidebar.write(f"Bejelentkezve: **{st.session_state.username}**")
st.sidebar.caption(f"Jogosultság: {role_label}")

if st.sidebar.button("🚪 Kijelentkezés"):
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.user_role = "user"
    st.session_state.assigned_stats = []
    st.session_state.assigned_groups = []
    st.rerun()

st.sidebar.markdown("---")

menu_options = [
    "📊 Egyedi Statisztika Nézet",
    "📈 Több Statisztika Összevetése",
    "📋 Összesítő Dashboard (Kártya Nézet)",
]

if st.session_state.user_role == "admin":
    menu_options.extend(
        ["➕ Új Statisztika Létrehozása", "⚙️ Adminisztráció & Archívum"]
    )

selected_menu = st.sidebar.radio("Válassz funkciót:", menu_options)
st.sidebar.markdown("---")

# ================= MODULOK =================

# 1. EGYEDI STATISZTIKA NÉZET
if selected_menu == "📊 Egyedi Statisztika Nézet":
    if not stat_names:
        st.warning(
            "⚠️ Nincs számodra elérhető statisztika hozzárendelve. Kérj hozzáférést"
            " az admintól!"
        )
    else:
        selected_stat = st.sidebar.selectbox(
            "Választott statisztika:", stat_names, format_func=stat_label
        )

        current_unit = db["stats"][selected_stat].get("unit", "")
        stat_group = db["stats"][selected_stat].get("group", "Egyéb")
        stat_settings = db.get("settings", {}).get(selected_stat, {})
        is_inverted = db["stats"][selected_stat].get("inverted", False)
        # JAVÍTÁS: Aggregáció módjának lekérése (alapból összeg)
        agg_type = db["stats"][selected_stat].get("agg_type", "sum")
        stat_desc = db["stats"][selected_stat].get("description", "")

        if st.session_state.user_role == "admin":
            person_name = st.sidebar.text_input(
                "Név (Fejlécbe):",
                value=stat_settings.get("person_name", "Bíró Laura"),
                key=f"pname_{selected_stat}",
            )
            person_post = st.sidebar.text_input(
                "Poszt (Fejlécbe):",
                value=stat_settings.get("person_post", "DIV1"),
                key=f"ppost_{selected_stat}",
            )
            is_stat_inverted_check = st.sidebar.checkbox(
                "Fordított statisztika (0 felül van)",
                value=is_inverted,
                key=f"inv_{selected_stat}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader("📐 Grafikon & Nyomtatás Méretezése")
            chart_height = st.sidebar.slider(
                "Grafikon magassága (px):",
                min_value=300,
                max_value=900,
                value=int(stat_settings.get("chart_height", 550)),
                step=10,
                key=f"ch_{selected_stat}",
            )

            col_m1, col_m2 = st.sidebar.columns(2)
            with col_m1:
                margin_l = st.number_input(
                    "Bal margó (px):",
                    value=int(stat_settings.get("margin_l", 60)),
                    step=5,
                    key=f"ml_{selected_stat}",
                )
                margin_t = st.number_input(
                    "Felső margó (px):",
                    value=int(stat_settings.get("margin_t", 130)),
                    step=5,
                    key=f"mt_{selected_stat}",
                )
            with col_m2:
                margin_r = st.number_input(
                    "Jobb margó (px):",
                    value=int(stat_settings.get("margin_r", 100)),
                    step=5,
                    key=f"mr_{selected_stat}",
                )
                margin_b = st.number_input(
                    "Alsó margó (px):",
                    value=int(stat_settings.get("margin_b", 90)),
                    step=5,
                    key=f"mb_{selected_stat}",
                )

            st.sidebar.markdown("---")
            if st.sidebar.button(
                "🔄 Beállítások átvitele MINDEN statisztikára",
                key=f"apply_all_btn_{selected_stat}",
            ):
                if "settings" not in st.session_state.db:
                    st.session_state.db["settings"] = {}
                curr_settings_copy = json.loads(json.dumps(stat_settings))
                for s_loop in all_stat_names:
                    st.session_state.db["settings"][s_loop] = copy.deepcopy(
                        curr_settings_copy
                    )
                save_data(st.session_state.db)
                st.sidebar.success("Minden statisztika megkapta ezeket a beállításokat!")

        else:
            person_name = stat_settings.get("person_name", "Bíró Laura")
            person_post = stat_settings.get("person_post", "DIV1")
            is_stat_inverted_check = is_inverted
            chart_height = int(stat_settings.get("chart_height", 550))
            margin_l = int(stat_settings.get("margin_l", 60))
            margin_r = int(stat_settings.get("margin_r", 100))
            margin_t = int(stat_settings.get("margin_t", 130))
            margin_b = int(stat_settings.get("margin_b", 90))

        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Időszakos összesítés")
        valid_aggs = [
            "Napi adatok",
            "Heti (Csütörtöki zárás 14:00)", # Fixált kulcs
            "Havi összesítés",
        ]
        indiv_agg = st.sidebar.selectbox(
            "Grafikon nézet:", valid_aggs, key=f"indiv_agg_view_{selected_stat}"
        )

        mode_settings = stat_settings.get(indiv_agg, {})
        valid_goals = ["Nincs", "Fix érték (db/Ft)"]
        valid_chart_types = ["Vonaldiagram", "Oszlopdiagram (Bar)"]

        if st.session_state.user_role == "admin":
            st.sidebar.markdown("---")
            st.sidebar.subheader(f"📊 Diagram Típusa ({indiv_agg})")
            chart_type_val = mode_settings.get("chart_type", "Vonaldiagram")
            chart_type = st.sidebar.selectbox(
                "Diagram formátuma:",
                valid_chart_types,
                index=valid_chart_types.index(chart_type_val)
                if chart_type_val in valid_chart_types
                else 0,
                key=f"chart_type_{selected_stat}_{indiv_agg}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"📐 Skála Tengely Beállítások ({indiv_agg})")
            col_min, col_max, col_step = st.sidebar.columns(3)
            with col_min:
                ymin = st.text_input(
                    "Min",
                    value=str(mode_settings.get("ymin", "")),
                    key=f"ymin_{selected_stat}_{indiv_agg}",
                )
            with col_max:
                ymax = st.text_input(
                    "Max",
                    value=str(mode_settings.get("ymax", "")),
                    key=f"ymax_{selected_stat}_{indiv_agg}",
                )
            with col_step:
                ystep = st.text_input(
                    "Lépés",
                    value=str(mode_settings.get("ystep", "")),
                    key=f"ystep_{selected_stat}_{indiv_agg}",
                )

            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Akkumulált összeg zárójelben")
            show_acc_in_brackets = st.sidebar.checkbox(
                "Akkumulált összeg megjelenítése a pontok alatt",
                value=stat_settings.get("show_acc_in_brackets", False),
                key=f"show_acc_{selected_stat}",
            )
            initial_accumulated_val = st.sidebar.number_input(
                "Kezdő alap:",
                value=float(stat_settings.get("initial_accumulated_val", 0.0)),
                step=1.0,
                key=f"init_acc_{selected_stat}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"🛡️ Életvonal ({indiv_agg})")
            survival_value = st.sidebar.number_input(
                "Életvonal értéke:",
                value=float(mode_settings.get("survival_value", 0.0)),
                step=1.0,
                key=f"surv_val_{selected_stat}_{indiv_agg}",
            )
            show_survival_line = st.sidebar.checkbox(
                "Életvonal rajzolása a grafikonra",
                value=mode_settings.get("show_survival", True),
                key=f"show_surv_{selected_stat}_{indiv_agg}",
            )

            st.sidebar.markdown("---")
            st.sidebar.subheader(f"🎯 Célkitűzés ({indiv_agg})")
            goal_type_val = mode_settings.get("goal_type", "Nincs")
            goal_type = st.sidebar.selectbox(
                "Cél típusa:",
                valid_goals,
                index=valid_goals.index(goal_type_val)
                if goal_type_val in valid_goals
                else 0,
                key=f"goal_type_{selected_stat}_{indiv_agg}",
            )
            goal_value = st.sidebar.number_input(
                "Cél mértéke:",
                value=float(mode_settings.get("goal_val_target", 0.0)),
                step=1.0,
                key=f"goal_val_{selected_stat}_{indiv_agg}",
            )

            if "settings" not in st.session_state.db:
                st.session_state.db["settings"] = {}
            if selected_stat not in st.session_state.db["settings"]:
                st.session_state.db["settings"][selected_stat] = {}

            st.session_state.db["settings"][selected_stat][
                "person_name"
            ] = person_name
            st.session_state.db["settings"][selected_stat][
                "person_post"
            ] = person_post
            st.session_state.db["settings"][selected_stat][
                "chart_height"
            ] = chart_height
            st.session_state.db["settings"][selected_stat]["margin_l"] = margin_l
            st.session_state.db["settings"][selected_stat]["margin_r"] = margin_r
            st.session_state.db["settings"][selected_stat]["margin_t"] = margin_t
            st.session_state.db["settings"][selected_stat]["margin_b"] = margin_b
            st.session_state.db["settings"][selected_stat][
                "show_acc_in_brackets"
            ] = show_acc_in_brackets
            st.session_state.db["settings"][selected_stat][
                "initial_accumulated_val"
            ] = initial_accumulated_val

            st.session_state.db["settings"][selected_stat][indiv_agg] = {
                "chart_type": chart_type,
                "ymin": ymin,
                "ymax": ymax,
                "ystep": ystep,
                "survival_value": survival_value,
                "show_survival": show_survival_line,
                "goal_type": goal_type,
                "goal_val_target": goal_value,
            }

            st.session_state.db["stats"][selected_stat][
                "inverted"
            ] = is_stat_inverted_check
            save_data(st.session_state.db)
        else:
            chart_type = mode_settings.get("chart_type", "Vonaldiagram")
            ymin = str(mode_settings.get("ymin", ""))
            ymax = str(mode_settings.get("ymax", ""))
            ystep = str(mode_settings.get("ystep", ""))
            show_acc_in_brackets = stat_settings.get("show_acc_in_brackets", False)
            initial_accumulated_val = float(
                stat_settings.get("initial_accumulated_val", 0.0)
            )
            survival_value = float(mode_settings.get("survival_value", 0.0))
            show_survival_line = mode_settings.get("show_survival", True)
            goal_type = mode_settings.get("goal_type", "Nincs")
            goal_value = float(mode_settings.get("goal_val_target", 0.0))

        components.html(
            """
            <button onclick="window.parent.print()" style="
                padding: 10px 20px; 
                font-size: 15px; 
                background-color: #000000; 
                color: white; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer;
                font-weight: bold;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
            ">🖨️ Nyomtatás A4-re</button>
        """,
            height=50,
        )

        if stat_desc:
            st.info(f"ℹ️ **Útmutató a statisztikához:** {stat_desc}")

        stat_data_raw = db["stats"][selected_stat]["data"]

        if stat_data_raw:
            df_temp = pd.DataFrame(
                [
                    [item[0], item[1], item[2] if len(item) > 2 else ""]
                    for item in stat_data_raw
                ],
                columns=["Dátum", "Érték", "Megjegyzés"],
            )
            df_temp["Sort_Key"] = pd.to_datetime(
                df_temp["Dátum"], format="mixed", errors="coerce"
            )
            df_temp = df_temp.dropna(subset=["Sort_Key"])
            df_temp["Érték"] = pd.to_numeric(df_temp["Érték"])
            df_temp = df_temp.sort_values("Sort_Key")
            
            # Pandas aggregáció JAVÍTÁSA: 'sum' helyett lehet 'last' is
            agg_func = "last" if agg_type == "last" else "sum"

            if indiv_agg == "Heti (Csütörtöki zárás 14:00)":
                df_temp["Period_End"] = df_temp["Sort_Key"].apply(
                    get_thursday_period_end
                )
                res_df = (
                    df_temp.groupby("Period_End")
                    .agg({
                        "Érték": agg_func,
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Period_End")
                )

                raw_items = []
                for idx, row in res_df.iterrows():
                    d_str = row["Period_End"].strftime("%Y-%m-%d")
                    raw_items.append({
                        "x": len(raw_items),
                        "date_str": d_str,
                        "label": row["Period_End"].strftime("%Y. %m. %d."),
                        "hover_label": row["Period_End"].strftime("%Y. %m. %d."),
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })
                unique_x = list(range(len(raw_items)))
                unique_labels = [item["label"] for item in raw_items]

            elif indiv_agg == "Havi összesítés":
                df_temp["Period_Month"] = (
                    df_temp["Sort_Key"]
                    .dt.to_period("M")
                    .dt.to_timestamp(how="end")
                    .dt.floor("D")
                )
                res_df = (
                    df_temp.groupby("Period_Month")
                    .agg({
                        "Sort_Key": "min",
                        "Érték": agg_func,
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Period_Month")
                )

                raw_items = []
                for idx, row in res_df.iterrows():
                    m_dt = row["Period_Month"]
                    d_str = m_dt.strftime("%Y-%m-%d")
                    raw_items.append({
                        "x": len(raw_items),
                        "date_str": d_str,
                        "label": m_dt.strftime("%Y. %m."),
                        "hover_label": m_dt.strftime("%Y. %m. hó"),
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })
                unique_x = list(range(len(raw_items)))
                unique_labels = [item["label"] for item in raw_items]

            else:
                df_temp["Date_Only"] = df_temp["Sort_Key"].dt.strftime("%Y-%m-%d")

                def get_bucket_type(row):
                    dt = row["Sort_Key"]
                    if dt.weekday() == 3:
                        if dt.hour > 14 or (dt.hour == 14 and dt.minute > 0):
                            return "post_14"
                        else:
                            return "pre_14"
                    return "all"

                df_temp["Bucket_Type"] = df_temp.apply(get_bucket_type, axis=1)

                res_df = (
                    df_temp.groupby(["Date_Only", "Bucket_Type"], sort=False)
                    .agg({
                        "Sort_Key": "min",
                        "Érték": agg_func,
                        "Megjegyzés": lambda x: " | ".join(
                            [str(n) for n in x if n and str(n).strip()]
                        ),
                    })
                    .reset_index()
                    .sort_values("Sort_Key")
                )

                unique_dates = []
                for d in res_df["Date_Only"]:
                    if d not in unique_dates:
                        unique_dates.append(d)

                date_to_x = {d: idx for idx, d in enumerate(unique_dates)}

                raw_items = []
                for _, row in res_df.iterrows():
                    d_only = row["Date_Only"]
                    b_type = row["Bucket_Type"]
                    d_obj = datetime.strptime(d_only, "%Y-%m-%d")
                    fmt_d = f"{d_obj.year}. {d_obj.month:02d}. {d_obj.day:02d}."

                    if b_type == "post_14":
                        hover_lbl = fmt_d + " (14:00 után)"
                    elif b_type == "pre_14":
                        hover_lbl = fmt_d + " (14:00 előtt)"
                    else:
                        hover_lbl = fmt_d

                    raw_items.append({
                        "x": date_to_x[d_only],
                        "date_str": d_only,
                        "label": fmt_d,
                        "hover_label": hover_lbl,
                        "val": float(row["Érték"]),
                        "note": row["Megjegyzés"],
                    })

                unique_x = list(range(len(unique_dates)))
                unique_labels = [
                    datetime.strptime(d, "%Y-%m-%d").strftime("%Y. %m. %d.")
                    for d in unique_dates
                ]

        else:
            raw_items = []
            unique_x = []
            unique_labels = []

        accumulated_vals = []
        if raw_items:
            running_tot = float(initial_accumulated_val)
            for item in raw_items:
                running_tot += item["val"]
                accumulated_vals.append(running_tot)

        calc_survival_val = (
            survival_value if (show_survival_line and survival_value > 0) else 0.0
        )

        calc_goal_val = 0.0
        if goal_type == "Fix érték (db/Ft)":
            calc_goal_val = goal_value

        if stat_data_raw:
            date_range_str = ""
            if len(raw_items) > 0:
                try:
                    start_d = datetime.strptime(
                        raw_items[0]["date_str"], "%Y-%m-%d"
                    ).strftime("%Y. %m. %d.")
                    end_d = datetime.strptime(
                        raw_items[-1]["date_str"], "%Y-%m-%d"
                    ).strftime("%Y. %m. %d.")
                    date_range_str = f"({start_d} - {end_d})"
                except Exception:
                    date_range_str = ""

            fig = go.Figure()

            if len(raw_items) > 0:
                x_numeric = [item["x"] for item in raw_items]
                y_vals = [item["val"] for item in raw_items]
                notes = [item["note"] for item in raw_items]

                formatted_texts = []
                for idx, val in enumerate(y_vals):
                    v_str = fmt_num(val, current_unit)
                    if show_acc_in_brackets and accumulated_vals:
                        acc_val = accumulated_vals[idx]
                        acc_str = fmt_num(acc_val, current_unit)
                        formatted_texts.append(
                            f"{v_str}<br><span style='font-size:13px;"
                            f" color:#475569;'>({acc_str})</span>"
                        )
                    else:
                        formatted_texts.append(v_str)

                hover_texts = []
                for item, val, acc in zip(raw_items, y_vals, accumulated_vals):
                    v_str = fmt_num(val, current_unit)
                    acc_str = fmt_num(acc, current_unit)
                    h_txt = (
                        f"Dátum: {item['hover_label']}<br>Érték: {v_str}<br>Akkumulált:"
                        f" {acc_str}"
                    )
                    if item["note"]:
                        h_txt += f"<br>Megjegyzés: {item['note']}"
                    hover_texts.append(h_txt)

                if chart_type == "Oszlopdiagram (Bar)":
                    bar_colors = []
                    for i, y_val in enumerate(y_vals):
                        if i == 0:
                            bar_colors.append("#00C853")
                        else:
                            prev_y = y_vals[i - 1]
                            if is_stat_inverted_check:
                                c = "#00C853" if y_val < prev_y else "#FF1744"
                            else:
                                c = "#00C853" if y_val > prev_y else "#FF1744"
                            bar_colors.append(c)

                    fig.add_trace(
                        go.Bar(
                            x=x_numeric,
                            y=y_vals,
                            marker=dict(color=bar_colors),
                            hovertext=hover_texts,
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
                else:
                    for i in range(len(raw_items) - 1):
                        x1, y1 = x_numeric[i], y_vals[i]
                        x2, y2 = x_numeric[i + 1], y_vals[i + 1]

                        if is_stat_inverted_check:
                            color = "#00C853" if y2 < y1 else "#FF1744"
                        else:
                            color = "#00C853" if y2 > y1 else "#FF1744"

                        fig.add_trace(
                            go.Scatter(
                                x=[x1, x2],
                                y=[y1, y2],
                                mode="lines",
                                line=dict(color=color, width=6),
                                showlegend=False,
                                hoverinfo="skip",
                            )
                        )

                    fig.add_trace(
                        go.Scatter(
                            x=x_numeric,
                            y=y_vals,
                            mode="markers",
                            marker=dict(size=16, color="#1E293B"),
                            cliponaxis=False,
                            hovertext=hover_texts,
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )

                if show_survival_line and calc_survival_val > 0:
                    fig.add_hline(
                        y=calc_survival_val,
                        line_dash="solid",
                        line_color="#4B5563",
                        line_width=4,
                    )

                for idx, (x_val, y_val, txt) in enumerate(
                    zip(x_numeric, y_vals, formatted_texts)
                ):
                    fig.add_annotation(
                        x=x_val,
                        y=y_val,
                        text=txt,
                        showarrow=False,
                        yshift=12,
                        xshift=18,
                        textangle=-75,
                        font=dict(size=14, color="#000000", family="Arial Black"),
                        xanchor="center",
                        yanchor="bottom",
                    )

                if person_name:
                    fig.add_annotation(
                        xref="paper",
                        yref="paper",
                        x=0.0,
                        y=1.15,
                        text=f"<b>{person_name}</b>",
                        showarrow=False,
                        align="left",
                        xanchor="left",
                        yanchor="bottom",
                        font=dict(size=26, family="Arial Black", color="#000000"),
                    )
                if person_post:
                    fig.add_annotation(
                        xref="paper",
                        yref="paper",
                        x=0.0,
                        y=1.05,
                        text=person_post,
                        showarrow=False,
                        align="left",
                        xanchor="left",
                        yanchor="bottom",
                        font=dict(size=20, family="Arial Black", color="#000A mellékelt professzionális szakmai audit alapján a jelenlegi Streamlit-rendszer kritikus koncepcionális, biztonsági és adatkezelési sebezhetőségeket tartalmaz. A hibák jelentős része nem pusztán szintaktikai jellegű, hanem a választott architektúrából és adatmodellből (egyfájlos, memóriába másolt, JSON-alapú feldolgozás, beégetett és plain-text jelszavak, jogosultsági kontextus nélküli szerkesztés, valamint hiányzó zárolások és validációk) ered, és ezért a jelenlegi formában, egyetlen szkriptfolyamaton belül stabil és biztonságos többfelhasználós termékként nem stabilizálható.

Az auditban részletezett javítások a teljes rendszer újraírását, és ahogy Ön is kezdeményezte, a **WordPress backend (REST API, jogosultság, MySQL) és Construct 3 frontend** architektúrára történő átállást követelik meg. A jelenlegi Streamlit alkalmazásban elvégzett bármilyen "foltozás" – például egy jelszó hashelése, vagy az adatbázis megnyitásakor egy egyszerű fájl-lock alkalmazása – csupán felületi tüneti kezelés lenne a strukturális problémákkal szemben.

A javasolt, és egyetlen fenntartható irány az architekturális átállás. Ehhez a migrációhoz – az FMR rendszer mintájára – az alábbi fejlesztési fázisokra van szükség, amelyeket a kapott szakmai összefoglaló is rögzített:

1. **WordPress Backend Kialakítása:**
   - Adatbázisséma létrehozása (`wp_fhk_stat_groups`, `wp_fhk_stats`, `wp_fhk_stat_values` stb.) a `dbDelta` használatával.
   - A jogosultsági rendszer (capabilities, pl. `fhk_stats_view`, `fhk_stats_edit_own_values`, `fhk_stats_manage_settings`) implementálása a WordPress beépített felhasználókezelésére támaszkodva.
   - REST API végpontok (pl. `GET /wp-json/fhk-stat/v1/stats`) fejlesztése, amelyek validálják a nonce-ot és a jogosultságokat.

2. **A Jelenlegi Adatok Migrációja:**
   - Egy migrációs szkript megírása, amely beolvassa a `statisztikak.json` adatait, és azokat a új WordPress táblákba importálja (a `users.json` sima szöveges jelszavait eldobva, a felhasználókat pedig az új WordPress userekhez rendelve).

3. **Construct 3 Kliens (Frontend) Fejlesztése:**
   - A felhasználói (dashboard, egyedi nézet, adatfelvitel) és az admin (statisztikák, csoportok, jogosultságok kezelése) felületek elkészítése Construct 3-ban.
   - A kliens a WordPress hitelesítési mechanizmusát (Cookie és X-WP-Nonce) használva kommunikál a REST API-val AJAX (fetch) hívásokon keresztül.

Mivel a jelenlegi Python/Streamlit kód nem adapt

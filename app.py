import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
from datetime import datetime
import streamlit.components.v1 as components

# ================= OLDAL ALAPBEÁLLÍTÁSAI =================
st.set_page_config(page_title="Statisztika Kezelő Rendszer", layout="wide", page_icon="📊")

# ================= NYOMTATÁSI CSS (Kizárólag a grafikon nyomtatása A4-re) =================
st.markdown("""
    <style>
    @media print {
        @page { size: A4 landscape; margin: 5mm; }
        [data-testid="stSidebar"], 
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        .stForm, 
        button, 
        iframe,
        .no-print {
            display: none !important;
        }
        body * {
            visibility: hidden !important;
        }
        .js-plotly-plot, .js-plotly-plot * {
            visibility: visible !important;
        }
        .js-plotly-plot {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ================= ADATTÁROLÁS & RENDSZER FÜGGVÉNYEK =================
USERS_FILE = "users.json"
DB_FILE = "statisztikak.json"
ARCHIVE_FILE = "archivum.json"

def load_users():
    users = {}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
        except Exception:
            pass
            
    # Garantáljuk, hogy a 'teszt' felhasználó '123' jelszóval és teljes joggal mindig létezzen!
    users["teszt"] = {
        "password": "123",
        "allowed_stats": ["*"]
    }
    save_users(users)
    return users

def save_users(users_data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

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
                "inverted": False,
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
                "inverted": False,
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

# ================= SESSION STATE INICIALIZÁLÁS =================
if "users" not in st.session_state: st.session_state.users = load_users()
if "db" not in st.session_state: st.session_state.db = load_data()
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "current_user" not in st.session_state: st.session_state.current_user = None

USERS = load_users()
db = st.session_state.db

# ================= BEJELENTKEZÉSI FELÜLET =================
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

# Jogosultságok lekérdezése
current_user_info = USERS.get(st.session_state.current_user, {"allowed_stats": []})
allowed_stat_names = current_user_info["allowed_stats"]
all_stat_names = list(db["stats"].keys())
is_admin = "*" in allowed_stat_names

if is_admin:
    stat_names = all_stat_names
else:
    stat_names = [s for s in all_stat_names if s in allowed_stat_names]

# ================= FŐMENÜ / NAVIGÁCIÓ =================
st.sidebar.title("📌 Navigáció")
st.sidebar.info(f"Bejelentkezve: **{st.session_state.current_user}**")

menu_options = [
    "📊 Egyedi Statisztika Nézet", 
    "📈 Több Statisztika Összevetése", 
    "📋 Összesítő Dashboard (Kártya Nézet)",
    "➕ Új Statisztika Létrehozása"
]
if is_admin:
    menu_options.append("⚙️ Adminisztráció & Archívum")

selected_menu = st.sidebar.radio("Válassz funkciót:", menu_options)
st.sidebar.markdown("---")

if st.sidebar.button("🚪 Kijelentkezés"):
    st.session_state.authenticated = False
    st.session_state.current_user = None
    st.rerun()

st.sidebar.markdown("---")

# ================= MODULOK / OLDALAK =================

# ----------------- 1. EGYEDI STATISZTIKA NÉZET -----------------
if selected_menu == "📊 Egyedi Statisztika Nézet":
    if not stat_names:
        st.warning("⚠️ Nincs elérhető statisztikád. Hozz létre egyet a menüben!")
    else:
        selected_stat = st.sidebar.selectbox("Választott statisztika:", stat_names)
        
        st.sidebar.subheader("⚙️ Grafikon Beállítások")
        current_unit = db["stats"][selected_stat].get("unit", "")
        stat_settings = db.get("settings", {}).get(selected_stat, {})
        is_inverted = db["stats"][selected_stat].get("inverted", False)

        person_name = st.sidebar.text_input("Név (Fejlécbe):", value=stat_settings.get("person_name", ""))
        person_post = st.sidebar.text_input("Poszt (Fejlécbe):", value=stat_settings.get("person_post", ""))
        
        chart_width_val = st.sidebar.number_input("Grafikon szélessége (px):", min_value=600, max_value=4000, value=int(stat_settings.get("chart_width", 1400)), step=100)
        
        col_min, col_max, col_step = st.sidebar.columns(3)
        with col_min: ymin = st.text_input("Min", value=stat_settings.get("ymin", ""))
        with col_max: ymax = st.text_input("Max", value=stat_settings.get("ymax", ""))
        with col_step: ystep = st.text_input("Lépés", value=stat_settings.get("ystep", ""))

        is_stat_inverted_check = st.sidebar.checkbox("Fordított statisztika (0 felül van)", value=is_inverted)
        enable_accumulated = st.sidebar.checkbox("Akkumulált érték számítása", value=False)
        accumulated_start_val = 0.0
        if enable_accumulated:
            accumulated_start_val = st.sidebar.number_input("Kezdő érték:", value=0.0, step=1.0)

        show_ref_line = st.sidebar.checkbox("Referencia vonal", value=stat_settings.get("show_ref", True))
        ref_line_val = st.sidebar.text_input("Referencia értéke:", value=stat_settings.get("ref_line", ""))

        enable_date_filter = st.sidebar.checkbox("Időszak szűkítése", value=False)
        start_date_filter, end_date_filter = None, None
        stat_data_raw = db["stats"][selected_stat]["data"]
        if enable_date_filter and stat_data_raw:
            all_dates = [datetime.strptime(item[0], "%Y-%m-%d").date() for item in stat_data_raw]
            start_date_filter = st.sidebar.date_input("Kezdő dátum", value=min(all_dates))
            end_date_filter = st.sidebar.date_input("Záró dátum", value=max(all_dates))

        if st.sidebar.button("💾 Beállítások Mentése"):
            if "settings" not in db: db["settings"] = {}
            db["settings"][selected_stat] = {
                "person_name": person_name, "person_post": person_post, "chart_width": chart_width_val,
                "ymin": ymin, "ymax": ymax, "ystep": ystep, "show_ref": show_ref_line, "ref_line": ref_line_val
            }
            db["stats"][selected_stat]["inverted"] = is_stat_inverted_check
            save_data(db)
            st.sidebar.success("Beállítások elmentve!")

        col_left, col_right = st.columns([1, 2.5])

        # BAL OLDAL: Adatbevitel és Táblázat
        with col_left:
            st.subheader(f"➕ Új adat ({selected_stat})")
            with st.form("add_data_form", clear_on_submit=True):
                input_date = st.date_input("Dátum")
                input_val = st.number_input(f"Érték ({current_unit})", min_value=0.0, step=1.0)
                if st.form_submit_button("Adat Hozzáadása"):
                    db["stats"][selected_stat]["data"].append([input_date.strftime("%Y-%m-%d"), input_val])
                    save_data(db)
                    st.rerun()

            st.subheader("📋 Adat-táblázat")
            if stat_data_raw:
                filtered_items = []
                for item in stat_data_raw:
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

                    del_idx = st.number_input("Törlendő sor sorszáma (index):", min_value=0, max_value=len(df)-1 if len(df)>0 else 0, step=1)
                    if st.button("🔴 Sor Törlése") and len(df) > 0:
                        target_to_delete = df.iloc[int(del_idx)].tolist()
                        if target_to_delete in db["stats"][selected_stat]["data"]:
                            db["stats"][selected_stat]["data"].remove(target_to_delete)
                            save_data(db)
                            st.rerun()

        # JOBB OLDAL: Interaktív Grafikon
        with col_right:
            components.html("""
                <button onclick="window.parent.print()" style="
                    padding: 10px 24px; 
                    font-size: 16px; 
                    background-color: #000000; 
                    color: white; 
                    border: none; 
                    border-radius: 8px; 
                    cursor: pointer;
                    font-weight: bold;
                    box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
                ">🖨️ Nyomtatás A4-es papírra</button>
            """, height=60)

            if stat_data_raw:
                raw_items = [item for item in stat_data_raw]
                if enable_date_filter and start_date_filter and end_date_filter:
                    raw_items = [item for item in raw_items if start_date_filter <= datetime.strptime(item[0], "%Y-%m-%d").date() <= end_date_filter]

                raw_items = sorted(raw_items, key=lambda x: str(x[0]))
                
                date_range_str = ""
                if len(raw_items) > 0:
                    try:
                        start_d = datetime.strptime(raw_items[0][0], "%Y-%m-%d").strftime("%Y. %m. %d.")
                        end_d = datetime.strptime(raw_items[-1][0], "%Y-%m-%d").strftime("%Y. %m. %d.")
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
                        
                        if is_stat_inverted_check:
                            color = "#00C853" if y2 <= y1 else "#FF1744"
                        else:
                            color = "#00C853" if y2 >= y1 else "#FF1744"
                        
                        fig.add_trace(go.Scatter(
                            x=[x1, x2],
                            y=[y1, y2],
                            mode='lines',
                            line=dict(color=color, width=6),
                            showlegend=False,
                            hoverinfo='skip'
                        ))

                    if show_ref_line:
                        line_target_val = float(ref_line_val) if ref_line_val else y_vals[-1]
                        val_str = f"{int(line_target_val):,}".replace(",", " ") if float(line_target_val).is_integer() else f"{line_target_val}"
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
                        v_str = f"{int(val):,}".replace(",", " ") if float(val).is_integer() else f"{val}"
                        if enable_accumulated:
                            running_acc += val
                            acc_str = f"{int(running_acc):,}".replace(",", " ") if float(running_acc).is_integer() else f"{running_acc}"
                            base_text = f"{v_str} {current_unit}<br>({acc_str} {current_unit})"
                        else:
                            base_text = f"{v_str} {current_unit}".strip()
                        formatted_texts.append(base_text)

                    x_dates = [datetime.strptime(str(item[0]), "%Y-%m-%d") for item in raw_items]
                    x_formatted = [f"{d.year}. {d.month:02d}. {d.day:02d}." for d in x_dates]

                    fig.add_trace(go.Scatter(
                        x=x_numeric,
                        y=y_vals,
                        mode='markers',
                        marker=dict(size=14, color="#1E293B"),
                        showlegend=False
                    ))

                    for x_val, y_val, txt in zip(x_numeric, y_vals, formatted_texts):
                        fig.add_annotation(
                            x=x_val,
                            y=y_val,
                            text=txt,
                            showarrow=False,
                            yshift=15,
                            textangle=-90,
                            font=dict(size=15, color="#000000", family="Arial Black"),
                            xanchor="center",
                            yanchor="bottom"
                        )

                    if person_name or person_post:
                        header_lines = []
                        if person_name:
                            header_lines.append(f"<span style='font-size: 32px;'><b>{person_name}</b></span>")
                        if person_post:
                            header_lines.append(f"<span style='font-size: 24px; color: #334155;'>{person_post}</span>")
                        
                        fig.add_annotation(
                            xref="paper", yref="paper",
                            x=0.01, y=0.99,
                            text="<br>".join(header_lines),
                            showarrow=False,
                            align="left",
                            xanchor="left", yanchor="top",
                            font=dict(family="Arial Black")
                        )

                    yaxis_dict = dict(
                        title=dict(text="", font=dict(color="#000000", size=1)), 
                        showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                        tickfont=dict(color="#000000", size=18, family="Arial Black"),
                        showline=True, linecolor="#000000", linewidth=3
                    )
                    if is_stat_inverted_check:
                        yaxis_dict["autorange"] = "reversed"
                    else:
                        yaxis_dict["rangemode"] = "tozero"

                    layout_args = dict(
                        title=dict(
                            text=f"<b>{selected_stat}</b><br><span style='font-size: 26px; color: #1E293B;'>Időszak: {date_range_str}</span>",
                            x=0.5, xref="paper", xanchor='center', yanchor='top',
                            font=dict(size=42, color="#000000")
                        ),
                        plot_bgcolor="white", paper_bgcolor="white",
                        width=chart_width_val,
                        margin=dict(t=150, b=150, l=60, r=60),
                        xaxis=dict(
                            title=dict(text="", font=dict(color="#000000", size=1)), 
                            tickmode="array", tickvals=x_numeric, ticktext=x_formatted, tickangle=-90,
                            showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                            tickfont=dict(color="#000000", size=15, family="Arial Black"),
                            showline=True, linecolor="#000000", linewidth=3,
                            range=[0, len(x_numeric) - 1] if len(x_numeric) > 1 else [-0.5, 0.5]
                        ),
                        yaxis=yaxis_dict
                    )

                    try:
                        if ymin and ymax: layout_args["yaxis"]["range"] = [float(ymin), float(ymax)]
                        if ystep: layout_args["yaxis"]["dtick"] = float(ystep)
                    except Exception:
                        pass

                    fig.update_layout(**layout_args)

                    config = {
                        'toImageButtonOptions': {
                            'format': 'png',
                            'filename': f'{selected_stat}_grafikon',
                            'height': 1200, 'width': 1800, 'scale': 3
                        },
                        'displayModeBar': True
                    }

                    st.plotly_chart(fig, use_container_width=False, config=config)

# ----------------- 2. TÖBB STATISZTIKA ÖSSZEVETÉSE -----------------
elif selected_menu == "📈 Több Statisztika Összevetése":
    st.title("📈 Statisztikák Dátumfüggetlen Összevetése")
    st.write("Válaszd ki az időszak típusát és a statisztikákat. A rendszer dátumfüggetlenül (az 1., 2., 3. időszaktól kezdve) hasonlítja össze a görbéket egyedi színekkel.")
    
    comp_period_type = st.radio("Összehasonlítás alapja:", ["Napi", "Heti (Cs)", "Havi"], horizontal=True)
    selected_multi_stats = st.multiselect("Válassz statisztikákat az összevetéshez:", stat_names, default=stat_names[:2] if len(stat_names)>=2 else stat_names)
    
    if selected_multi_stats:
        components.html("""
            <button onclick="window.parent.print()" style="
                padding: 10px 24px; 
                font-size: 16px; 
                background-color: #000000; 
                color: white; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer;
                font-weight: bold;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
            ">🖨️ Nyomtatás A4-es papírra</button>
        """, height=60)
        
        fig = go.Figure()
        color_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
        max_len = 0
        processed_series = []
        
        for stat_name in selected_multi_stats:
            stat_data = db["stats"][stat_name]["data"]
            s_unit = db["stats"][stat_name].get("unit", "")
            if not stat_data:
                continue
            
            df = pd.DataFrame(stat_data, columns=["Dátum", "Érték"])
            df["Dátum"] = pd.to_datetime(df["Dátum"])
            df = df.sort_values("Dátum").set_index("Dátum")
            
            try:
                if comp_period_type == "Napi":
                    res = df.resample("D").sum().reset_index()
                elif comp_period_type == "Heti (Cs)":
                    res = df.resample("W-THU").sum().reset_index()
                else:
                    res = df.resample("ME").sum().reset_index()
            except Exception:
                res = df.reset_index()
            
            res["Érték"] = res["Érték"].fillna(0)
            items = res.values.tolist()
            if len(items) > max_len:
                max_len = len(items)
            processed_series.append((stat_name, s_unit, items))
            
        if max_len > 0:
            for idx, (stat_name, s_unit, items) in enumerate(processed_series):
                y_vals = [item[1] for item in items]
                x_idx_current = list(range(1, len(y_vals) + 1))
                formatted_texts = [f"{int(y):,} {s_unit}".replace(",", " ") if float(y).is_integer() else f"{y} {s_unit}" for y in y_vals]
                trace_color = color_palette[idx % len(color_palette)]
                
                fig.add_trace(go.Scatter(
                    x=x_idx_current, y=y_vals, mode='lines+markers',
                    name=stat_name, line=dict(color=trace_color, width=5),
                    marker=dict(size=12, color=trace_color)
                ))
                
                for x_val, y_val, txt in zip(x_idx_current, y_vals, formatted_texts):
                    fig.add_annotation(
                        x=x_val, y=y_val, text=txt, showarrow=False, yshift=15, textangle=-90,
                        font=dict(size=13, color=trace_color, family="Arial Black"),
                        xanchor="center", yanchor="bottom"
                    )
            
            fig.update_layout(
                title=dict(text=f"<b>Statisztikák Összevetése ({comp_period_type})</b>", x=0.5, font=dict(size=36, color="#000000")),
                plot_bgcolor="white", paper_bgcolor="white", margin=dict(t=120, b=120, l=60, r=40),
                xaxis=dict(
                    tickmode="array", tickvals=list(range(1, max_len + 1)),
                    ticktext=[f"{i}." for i in range(1, max_len + 1)],
                    title=dict(text="Időszak sorszáma", font=dict(size=16, color="#000000")),
                    showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                    showline=True, linecolor="#000000", linewidth=3,
                    tickfont=dict(color="#000000", size=15, family="Arial Black")
                ),
                yaxis=dict(
                    rangemode="tozero", showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                    showline=True, linecolor="#000000", linewidth=3,
                    tickfont=dict(color="#000000", size=18, family="Arial Black")
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=16))
            )
            st.plotly_chart(fig, use_container_width=True)

# ----------------- 3. ÖSSZESÍTŐ DASHBOARD (KÁRTYA NÉZET - A KÉP ALAPJÁN) -----------------
elif selected_menu == "📋 Összesítő Dashboard (Kártya Nézet)":
    st.title("📋 Teljesítménymérő Statisztikák Dashboard")
    
    # Felső Keresősáv (mint a képen)
    col_search, col_btn = st.columns([4, 1])
    with col_search:
        search_query = st.text_input("Keresés:", placeholder="Keresés a statisztikák között...", key="dash_search")
    
    filtered_stats = [s for s in stat_names if search_query.lower() in s.lower()] if search_query else stat_names

    if not filtered_stats:
        st.info("Nincs találat a keresésre.")
    else:
        # Kétoszlopos kártya elrendezés (Grid)
        for i in range(0, len(filtered_stats), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(filtered_stats):
                    s_name = filtered_stats[i + j]
                    s_data_raw = db["stats"][s_name]["data"]
                    s_unit = db["stats"][s_name].get("unit", "")
                    s_settings = db.get("settings", {}).get(s_name, {})
                    s_inverted = db["stats"][s_name].get("inverted", False)
                    
                    p_name = s_settings.get("person_name", "")
                    p_post = s_settings.get("person_post", "")
                    assigned_str = f"{p_name} ({p_post})" if p_name or p_post else "Nincs megadva"
                    
                    with cols[j]:
                        with st.container(border=True):
                            # Kártya Fejléc
                            st.markdown(f"### **{s_name}**")
                            st.caption(f"**Assigned to:** {assigned_str}")
                            
                            # Kártyánkénti Mikortól / Meddig szűrők
                            dates_parsed = [datetime.strptime(item[0], "%Y-%m-%d").date() for item in s_data_raw] if s_data_raw else []
                            min_d = min(dates_parsed) if dates_parsed else None
                            max_d = max(dates_parsed) if dates_parsed else None
                            
                            card_items = [item for item in s_data_raw] if s_data_raw else []
                            card_items = sorted(card_items, key=lambda x: str(x[0]))
                            
                            if card_items:
                                fig_card = go.Figure()
                                x_num = list(range(len(card_items)))
                                y_v = [item[1] for item in card_items]
                                
                                for k in range(len(card_items) - 1):
                                    x1, y1 = x_num[k], y_v[k]
                                    x2, y2 = x_num[k+1], y_v[k+1]
                                    color = "#00C853" if (y2 <= y1 if s_inverted else y2 >= y1) else "#FF1744"
                                    fig_card.add_trace(go.Scatter(x=[x1, x2], y=[y1, y2], mode='lines', line=dict(color=color, width=3.5), showlegend=False, hoverinfo='skip'))
                                
                                fig_card.add_trace(go.Scatter(x=x_num, y=y_v, mode='markers', marker=dict(size=8, color="#1E293B"), showlegend=False))
                                
                                formatted_t = [f"{int(y):,} {s_unit}".replace(",", " ") if float(y).is_integer() else f"{y} {s_unit}" for y in y_v]
                                x_fmt = [datetime.strptime(str(item[0]), "%Y-%m-%d").strftime("%b %d") for item in card_items]
                                
                                for x_val, y_val, txt in zip(x_num, y_v, formatted_t):
                                    fig_card.add_annotation(x=x_val, y=y_val, text=txt, showarrow=False, yshift=10, textangle=-90, font=dict(size=10, color="#000000", family="Arial Black"), xanchor="center", yanchor="bottom")
                                
                                yaxis_card = dict(showgrid=True, gridcolor="#F1F5F9", gridwidth=1.5, tickfont=dict(color="#000", size=11, family="Arial Black"), showline=True, linecolor="#000", linewidth=1.5)
                                if s_inverted:
                                    yaxis_card["autorange"] = "reversed"
                                else:
                                    yaxis_card["rangemode"] = "tozero"
                                
                                fig_card.update_layout(
                                    height=340,
                                    plot_bgcolor="white", paper_bgcolor="white",
                                    margin=dict(t=20, b=40, l=40, r=20),
                                    xaxis=dict(tickmode="array", tickvals=x_num, ticktext=x_fmt, tickangle=-45, showgrid=True, gridcolor="#F1F5F9", gridwidth=1.5, tickfont=dict(color="#000", size=10, family="Arial Black"), showline=True, linecolor="#000", linewidth=1.5),
                                    yaxis=yaxis_card
                                )
                                st.plotly_chart(fig_card, use_container_width=True, config={'displayModeBar': False})
                            else:
                                st.info("Nincs megjeleníthető adat ezen a kártyán.")
                                
                            # Kártya alján lévő dátummezők (mint a képen)
                            c_date1, c_date2 = st.columns(2)
                            with c_date1:
                                st.date_input("Mikortól:", value=min_d, key=f"from_{s_name}_{i}_{j}") if min_d else st.text_input("Mikortól:", value="", key=f"from_empty_{s_name}_{i}_{j}")
                            with c_date2:
                                st.date_input("Meddig:", value=max_d, key=f"to_{s_name}_{i}_{j}") if max_d else st.text_input("Meddig:", value="", key=f"to_empty_{s_name}_{i}_{j}")

# ----------------- 4. ÚJ STATISZTIKA LÉTREHOZÁSA -----------------
elif selected_menu == "➕ Új Statisztika Létrehozása":
    st.title("➕ Új Statisztika Kategória Létrehozása")
    st.write("Ezen az oldalon hozhatsz létre új statisztikai kategóriát a rendszerben.")
    
    with st.form("create_stat_form"):
        new_stat_name = st.text_input("Statisztika neve:", placeholder="pl. Új Eladások")
        new_stat_unit = st.text_input("Mértékegység:", placeholder="pl. Ft, db, fő")
        is_new_inverted = st.checkbox("Fordított statisztika (a 0 felül van és lefelé nő)")
        
        submit = st.form_submit_button("Létrehozás")
        if submit:
            if new_stat_name:
                if new_stat_name not in db["stats"]:
                    db["stats"][new_stat_name] = {"unit": new_stat_unit, "inverted": is_new_inverted, "data": []}
                    save_data(db)
                    st.success(f"Létrehozva: {new_stat_name} ({new_stat_unit})")
                else:
                    st.error("Ilyen nevű statisztika már létezik!")
            else:
                st.warning("Adj meg egy nevet!")

# ----------------- 5. ADMINISZTRÁCIÓ & ARCHÍVUM -----------------
elif selected_menu == "⚙️ Adminisztráció & Archívum" and is_admin:
    st.title("⚙️ Rendszer Adminisztráció")
    
    st.subheader("👥 Felhasználók kezelése")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Új felhasználó hozzáadása")
        new_u_name = st.text_input("Felhasználónév:")
        new_u_pass = st.text_input("Jelszó:", type="password")
        is_admin_check = st.checkbox("Teljes admin jog (*)")
        assigned_stats = [] if is_admin_check else st.multiselect("Látható statisztikák:", options=all_stat_names)
        
        if st.button("Létrehozás"):
            if new_u_name and new_u_pass:
                USERS[new_u_name] = {"password": new_u_pass, "allowed_stats": ["*"] if is_admin_check else assigned_stats}
                save_users(USERS)
                st.success(f"Felhasználó '{new_u_name}' létrehozva!")
                st.rerun()

    with col2:
        st.markdown("#### Felhasználók módosítása / törlése")
        edit_user = st.selectbox("Módosítandó felhasználó:", options=list(USERS.keys()))
        if edit_user:
            u_data = USERS[edit_user]
            is_currently_admin = "*" in u_data["allowed_stats"]
            edit_is_admin = st.checkbox("Admin jog", value=is_currently_admin, key="e_adm")
            edit_stats = st.multiselect("Jogosultságok:", options=all_stat_names, default=[] if is_currently_admin else [s for s in u_data["allowed_stats"] if s in all_stat_names], key="e_stat")
            edit_pass = st.text_input("Új jelszó (ha módosítod):", type="password", key="e_pass")
            
            c_m1, c_m2 = st.columns(2)
            with c_m1:
                if st.button("Mentés Módosításai"):
                    USERS[edit_user]["allowed_stats"] = ["*"] if edit_is_admin else edit_stats
                    if edit_pass.strip(): USERS[edit_user]["password"] = edit_pass
                    save_users(USERS)
                    st.success("Módosítva!")
                    st.rerun()
            with c_m2:
                if edit_user != st.session_state.current_user and st.button("Törlés"):
                    del USERS[edit_user]
                    save_users(USERS)
                    st.success("Törölve!")
                    st.rerun()

    st.markdown("---")
    st.subheader("📂 Archívum kezelése")
    archive_db = load_archive()
    
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("#### Statisztika archiválása")
        stat_to_archive = st.selectbox("Archiválandó statisztika:", options=all_stat_names)
        if st.button("📦 Archiválás"):
            archive_db[stat_to_archive] = db["stats"][stat_to_archive]
            save_archive(archive_db)
            st.success("Archiválva!")
            
    with col_a2:
        st.markdown("#### Visszaállítás az archívumból")
        if archive_db:
            stat_to_restore = st.selectbox("Visszaállítandó elem:", options=list(archive_db.keys()))
            if st.button("🔄 Visszaállítás"):
                db["stats"][stat_to_restore] = archive_db[stat_to_restore]
                save_data(db)
                st.success("Visszaállítva!")
                st.rerun()
        else:
            st.info("Az archívum üres.")

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
from datetime import datetime
import streamlit.components.v1 as components

# ================= OLDAL ALAPBEÁLLÍTÁSAI =================
st.set_page_config(page_title="Statisztika Kezelő Rendszer", layout="wide", page_icon="📊")

# ================= NYOMTATÁSI CSS =================
st.markdown("""
    <style>
    @media print {
        @page { 
            size: A4 landscape; 
            margin: 10mm; 
        }
        body, html {
            background-color: #ffffff !important;
            width: 297mm !important;
            height: 210mm !important;
            margin: 0 !important;
            padding: 0 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
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
        .stPlotlyChart, .stPlotlyChart *, .js-plotly-plot, .js-plotly-plot *, .js-plotly-plot svg, .js-plotly-plot .main-svg, .js-plotly-plot .svg-container {
            visibility: visible !important;
        }
        .stPlotlyChart {
            position: absolute !important;
            left: 10mm !important;
            top: 10mm !important;
            width: 277mm !important;
            height: 190mm !important;
            max-width: 277mm !important;
            max-height: 190mm !important;
            border: 4px solid #000000 !important;
            box-sizing: border-box !important;
            padding: 5mm !important;
            background: #ffffff !important;
            margin: 0 !important;
        }
        .js-plotly-plot, .js-plotly-plot .svg-container {
            width: 100% !important;
            height: 100% !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ================= ADATTÁROLÁS & FÜGGVÉNYEK =================
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
        "groups": ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"],
        "stats": {
            "Bruttó Beérkezett Bevétel": {
                "unit": "Ft",
                "group": "Pénzügy",
                "inverted": False,
                "data": [
                    ["2026-07-23", 650000, "Nyitó kampány"],
                    ["2026-07-30", 97500, ""],
                    ["2026-08-06", 97500, ""],
                    ["2026-08-13", 547500, "Új ügyfél szerződés"],
                    ["2026-08-20", 347500, ""],
                    ["2026-08-27", 1570799, "Havi zárás pörgés"],
                    ["2026-09-03", 2350000, "Prémium csomagok"],
                    ["2026-09-10", 390000, ""],
                    ["2026-09-17", 4722200, "Rekord bevétel"],
                    ["2026-09-24", 0, "Ünnepnap / leállás"],
                    ["2026-10-01", 945000, ""]
                ]
            },
            "Ügyfelek száma": {
                "unit": "fő",
                "group": "Értékesítés",
                "inverted": False,
                "data": [
                    ["2026-08-08", 5, "Első körös hívások"],
                    ["2026-08-15", 12, ""],
                    ["2026-08-25", 18, "Ajánlások"],
                    ["2026-08-30", 25, ""],
                    ["2026-09-13", 34, "Marketing akció"]
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

def calculate_stat_condition(data, survival_line=0):
    if not data or len(data) < 1:
        return "Normál", "gray"
    
    sorted_d = sorted(data, key=lambda x: str(x[0]))
    last_val = sorted_d[-1][1]
    
    if survival_line > 0 and last_val < survival_line:
        return "Nem létezés (Életvonal alatt)", "red"
    
    if len(data) < 2:
        return "Normál", "blue"
        
    prev_val = sorted_d[-2][1]
    if last_val == 0 and prev_val == 0:
        return "Nem létezés", "red"
    elif last_val < prev_val:
        return "Vészhelyzet", "orange"
    elif last_val == prev_val:
        return "Veszély", "yellow"
    else:
        return "Bőség / Normál", "green"

# ================= SESSION STATE =================
if "db" not in st.session_state: st.session_state.db = load_data()
db = st.session_state.db

if "groups" not in db:
    db["groups"] = ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
    save_data(db)

all_stat_names = list(db["stats"].keys())
stat_names = all_stat_names
is_admin = True

# ================= NAVIGÁCIÓ =================
st.sidebar.title("📌 Navigáció")
st.sidebar.info("Rendszer: **Admin Mód**")

menu_options = [
    "📊 Egyedi Statisztika Nézet", 
    "📈 Több Statisztika Összevetése", 
    "📋 Összesítő Dashboard (Kártya Nézet)",
    "📖 Eseménynapló",
    "➕ Új Statisztika Létrehozása",
    "⚙️ Adminisztráció & Archívum"
]

selected_menu = st.sidebar.radio("Válassz funkciót:", menu_options)
st.sidebar.markdown("---")

# ================= MODULOK =================

# 1. EGYEDI STATISZTIKA NÉZET
if selected_menu == "📊 Egyedi Statisztika Nézet":
    if not stat_names:
        st.warning("⚠️ Nincs elérhető statisztikád. Hozz létre egyet a menüben!")
    else:
        selected_stat = st.sidebar.selectbox("Választott statisztika:", stat_names)
        
        st.sidebar.subheader("⚙️ Grafikon & Határok Beállítása")
        current_unit = db["stats"][selected_stat].get("unit", "")
        stat_group = db["stats"][selected_stat].get("group", "Egyéb")
        stat_settings = db.get("settings", {}).get(selected_stat, {})
        is_inverted = db["stats"][selected_stat].get("inverted", False)

        person_name = st.sidebar.text_input("Név (Fejlécbe):", value=stat_settings.get("person_name", ""))
        person_post = st.sidebar.text_input("Poszt (Fejlécbe):", value=stat_settings.get("person_post", ""))
        
        col_min, col_max, col_step = st.sidebar.columns(3)
        with col_min: ymin = st.text_input("Min", value=stat_settings.get("ymin", ""))
        with col_max: ymax = st.text_input("Max", value=stat_settings.get("ymax", ""))
        with col_step: ystep = st.text_input("Lépés", value=stat_settings.get("ystep", ""))

        is_stat_inverted_check = st.sidebar.checkbox("Fordított statisztika (0 felül van)", value=is_inverted)
        
        # Akkumulált / Halmozott összeg megjelenítése zárójelben beállítások
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔄 Akkumulált összeg zárójelben")
        show_acc_in_brackets = st.sidebar.checkbox("Akkumulált összeg megjelenítése a pontok alatt", value=stat_settings.get("show_acc_in_brackets", False))
        initial_accumulated_val = st.sidebar.number_input("Kezdő alap:", value=float(stat_settings.get("initial_accumulated_val", 0.0)), step=1.0)
        
        # Életvonal és Célkitűzés beállítások biztonságos fallbackkel
        old_goal_val = stat_settings.get("goal_value", 0.0)
        default_surv_val = stat_settings.get("survival_value", old_goal_val)
        default_surv_type = stat_settings.get("survival_type", "Fix érték (db/Ft)" if default_surv_val > 0 else "Nincs")
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("🛡️ Életvonal (Túlélési határ)")
        survival_type = st.sidebar.selectbox("Életvonal típusa:", ["Nincs", "Fix érték (db/Ft)"], index=0 if default_surv_type == "Nincs" else 1, key="surv_type")
        survival_value = st.sidebar.number_input("Életvonal értéke:", value=float(default_surv_val), step=1.0)
        show_survival_line = st.sidebar.checkbox("Életvonal rajzolása a grafikonra", value=stat_settings.get("show_survival", True))

        st.sidebar.markdown("---")
        st.sidebar.subheader("🎯 Célkitűzés")
        goal_type = st.sidebar.selectbox("Cél típusa:", ["Nincs", "Fix érték (db/Ft)", "Százalékos növekedés (%)"], index=0, key="goal_type")
        goal_value = st.sidebar.number_input("Cél mértéke:", value=float(stat_settings.get("goal_val_target", 0.0)), step=1.0)

        if st.sidebar.button("💾 Beállítások Mentése"):
            if "settings" not in db: db["settings"] = {}
            db["settings"][selected_stat] = {
                "person_name": person_name, "person_post": person_post,
                "ymin": ymin, "ymax": ymax, "ystep": ystep, 
                "survival_type": survival_type, "survival_value": survival_value, "show_survival": show_survival_line,
                "goal_type": goal_type, "goal_val_target": goal_value,
                "show_acc_in_brackets": show_acc_in_brackets,
                "initial_accumulated_val": initial_accumulated_val
            }
            db["stats"][selected_stat]["inverted"] = is_stat_inverted_check
            save_data(db)
            st.sidebar.success("Beállítások elmentve!")

        # Fülek használata, hogy a grafikon teljes szélességben érvényesülhessen
        tab_chart, tab_table = st.tabs(["📊 Grafikon Nézet", "📋 Adatkezelés & Táblázat"])

        with tab_table:
            st.subheader(f"➕ Új adat ({selected_stat})")
            with st.form("add_data_form", clear_on_submit=True):
                input_date = st.date_input("Dátum")
                input_val = st.number_input(f"Érték ({current_unit})", min_value=0.0, step=1.0)
                input_note = st.text_input("Megjegyzés / Esemény ehhez a ponthoz:")
                if st.form_submit_button("Adat Hozzáadása"):
                    db["stats"][selected_stat]["data"].append([input_date.strftime("%Y-%m-%d"), input_val, input_note])
                    save_data(db)
                    st.rerun()

            st.subheader("📋 Adat-táblázat")
            stat_data_raw = db["stats"][selected_stat]["data"]
            if stat_data_raw:
                normalized_data = [[item[0], item[1], item[2] if len(item) > 2 else ""] for item in stat_data_raw]
                db["stats"][selected_stat]["data"] = normalized_data

                df = pd.DataFrame(normalized_data, columns=["Dátum", f"Érték ({current_unit})", "Megjegyzés"])
                df = df.sort_values(by="Dátum", ascending=False)
                st.dataframe(df, use_container_width=True)

                del_idx = st.number_input("Törlendő sor sorszáma (index):", min_value=0, max_value=len(df)-1 if len(df)>0 else 0, step=1)
                if st.button("🔴 Sor Törlése") and len(df) > 0:
                    target_to_delete = df.iloc[int(del_idx)].tolist()
                    for idx, row in enumerate(db["stats"][selected_stat]["data"]):
                        if row[0] == target_to_delete[0] and row[1] == target_to_delete[1]:
                            del db["stats"][selected_stat]["data"][idx]
                            save_data(db)
                            st.rerun()

        with tab_chart:
            components.html("""
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
            """, height=50)

            stat_data_raw = db["stats"][selected_stat]["data"]
            raw_items = sorted(stat_data_raw, key=lambda x: str(x[0])) if stat_data_raw else []
            
            # Akkumulált értékek pontos kiszámítása futó összegként
            accumulated_vals = []
            if raw_items:
                running_tot = float(initial_accumulated_val)
                for item in raw_items:
                    running_tot += float(item[1])
                    accumulated_vals.append(running_tot)

            y_vals_temp = [item[1] for item in raw_items] if raw_items else []
            
            # Életvonal érték
            calc_survival_val = survival_value if survival_type == "Fix érték (db/Ft)" else 0.0

            # Cél érték
            calc_goal_val = 0.0
            if goal_type == "Fix érték (db/Ft)":
                calc_goal_val = goal_value
            elif goal_type == "Százalékos növekedés (%)" and len(y_vals_temp) > 0:
                calc_goal_val = y_vals_temp[-1] * (1 + goal_value / 100)

            if stat_data_raw:
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
                    notes = [item[2] if len(item) > 2 else "" for item in raw_items]

                    for i in range(len(raw_items) - 1):
                        x1, y1 = x_numeric[i], y_vals[i]
                        x2, y2 = x_numeric[i+1], y_vals[i+1]
                        
                        if is_stat_inverted_check:
                            color = "#00C853" if y2 < y1 else "#FF1744"
                        else:
                            color = "#00C853" if y2 > y1 else "#FF1744"
                        
                        fig.add_trace(go.Scatter(
                            x=[x1, x2], y=[y1, y2], mode='lines',
                            line=dict(color=color, width=6), showlegend=False, hoverinfo='skip'
                        ))

                    # Életvonal rajzolása felirat nélkül
                    if show_survival_line and calc_survival_val > 0:
                        fig.add_hline(
                            y=calc_survival_val,
                            line_dash="solid",
                            line_color="#EF4444",
                            line_width=4
                        )

                    # Címkék előkészítése (időszakos érték + zárójelben feketével az akkumulált)
                    formatted_texts = []
                    for idx, val in enumerate(y_vals):
                        v_str = f"{int(val):,} {current_unit}".replace(",", " ") if float(val).is_integer() else f"{val} {current_unit}"
                        if show_acc_in_brackets and accumulated_vals:
                            acc_val = accumulated_vals[idx]
                            acc_str = f"{int(acc_val):,}".replace(",", " ") if float(acc_val).is_integer() else f"{acc_val}"
                            formatted_texts.append(f"{v_str}<br><span style='font-size:14px; color:#000000;'>({acc_str} {current_unit})</span>")
                        else:
                            formatted_texts.append(v_str)

                    x_dates = [datetime.strptime(str(item[0]), "%Y-%m-%d") for item in raw_items]
                    x_formatted = [f"{d.year}. {d.month:02d}. {d.day:02d}." for d in x_dates]

                    hover_texts = []
                    for dt, val, acc, n in zip(x_formatted, y_vals, accumulated_vals, notes):
                        v_str = f"{int(val):,} {current_unit}".replace(",", " ") if float(val).is_integer() else f"{val} {current_unit}"
                        acc_str = f"{int(acc):,}".replace(",", " ") if float(acc).is_integer() else f"{acc}"
                        h_txt = f"Dátum: {dt}<br>Érték: {v_str}<br>Akkumulált: {acc_str} {current_unit}"
                        if n: h_txt += f"<br>Megjegyzés: {n}"
                        hover_texts.append(h_txt)

                    fig.add_trace(go.Scatter(
                        x=x_numeric, y=y_vals, mode='markers',
                        marker=dict(size=14, color="#1E293B"),
                        hovertext=hover_texts, hoverinfo='text', showlegend=False
                    ))

                    # Értékek feliratozása (megnövelt betűméret, első elem picit jobbra tolva, bal szélen kezdődve)
                    for idx, (x_val, y_val, txt) in enumerate(zip(x_numeric, y_vals, formatted_texts)):
                        if idx == 0:
                            fig.add_annotation(
                                x=x_val, y=y_val, text=txt, showarrow=False, yshift=15, xshift=14, textangle=-90,
                                font=dict(size=16, color="#000000", family="Arial Black"),
                                xanchor="left", yanchor="bottom"
                            )
                        else:
                            fig.add_annotation(
                                x=x_val, y=y_val, text=txt, showarrow=False, yshift=15, textangle=-90,
                                font=dict(size=16, color="#000000", family="Arial Black"),
                                xanchor="center", yanchor="bottom"
                            )

                    # Név és Poszt bal felül
                    if person_name or person_post:
                        header_lines = []
                        if person_name: header_lines.append(f"<span style='font-size: 26px;'><b>{person_name}</b></span>")
                        if person_post: header_lines.append(f"<span style='font-size: 20px; color: #000000;'>{person_post}</span>")
                        
                        fig.add_annotation(
                            xref="paper", yref="paper", x=0.0, y=1.12,
                            text="<br>".join(header_lines), showarrow=False,
                            align="left", xanchor="left", yanchor="bottom", font=dict(family="Arial Black", color="#000000")
                        )

                    # Cél kiírása a jobb felső sarokba a grafikonon belül
                    if goal_type != "Nincs" and calc_goal_val > 0:
                        goal_fmt = f"{int(calc_goal_val):,}".replace(",", " ") if float(calc_goal_val).is_integer() else f"{calc_goal_val}"
                        fig.add_annotation(
                            xref="paper", yref="paper", x=1.0, y=1.12,
                            text=f"🎯 Cél: {goal_fmt} {current_unit}",
                            showarrow=False,
                            align="right", xanchor="right", yanchor="bottom",
                            font=dict(size=18, color="#2563EB", family="Arial Black")
                        )

                    yaxis_dict = dict(
                        title=dict(text="", font=dict(color="#000000", size=1)), 
                        showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                        tickfont=dict(color="#000000", size=18, family="Arial Black"),
                        showline=True, linecolor="#000000", linewidth=3,
                        mirror=True
                    )
                    if is_stat_inverted_check: yaxis_dict["autorange"] = "reversed"
                    else: yaxis_dict["rangemode"] = "tozero"

                    layout_args = dict(
                        title=dict(
                            text=f"<b>{selected_stat}</b><br><span style='font-size: 24px; color: #1E293B;'>Időszak: {date_range_str}</span>",
                            x=0.5, xref="paper", xanchor='center', yanchor='top',
                            font=dict(size=34, color="#000000")
                        ),
                        plot_bgcolor="white", paper_bgcolor="white",
                        autosize=True,
                        margin=dict(t=160, b=150, l=60, r=60),
                        xaxis=dict(
                            title=dict(text="", font=dict(color="#000000", size=1)), 
                            tickmode="array", tickvals=x_numeric, ticktext=x_formatted, tickangle=-90,
                            showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5,
                            tickfont=dict(color="#000000", size=15, family="Arial Black"),
                            showline=True, linecolor="#000000", linewidth=3,
                            mirror=True,
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
                    st.plotly_chart(fig, use_container_width=True)

# 2. TÖBB STATISZTIKA ÖSSZEVETÉSE
elif selected_menu == "📈 Több Statisztika Összevetése":
    st.title("📈 Statisztikák Relatív Összevetése")
    st.write("A görbék sorszám szerint egymásra illesztve jelennek meg, megőrizve az eredeti naptári dátumokat.")
    
    comp_period_type = st.radio("Összehasonlítás alapja:", ["Napi", "Heti (Cs)", "Havi"], horizontal=True)
    show_dates_on_chart = st.checkbox("Eredeti dátumok megjelenítése a feliratokban", value=True)
    
    selected_multi_stats = st.multiselect("Válassz statisztikákat az összevetéshez:", stat_names, default=stat_names[:2] if len(stat_names)>=2 else stat_names)
    
    if selected_multi_stats:
        fig = go.Figure()
        color_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
        max_len = 0
        processed_series = []
        
        for stat_name in selected_multi_stats:
            stat_data = db["stats"][stat_name]["data"]
            s_unit = db["stats"][stat_name].get("unit", "")
            if not stat_data: continue
            
            clean_data = [[item[0], item[1]] for item in stat_data]
            df = pd.DataFrame(clean_data, columns=["Dátum", "Érték"])
            df["Dátum"] = pd.to_datetime(df["Dátum"])
            df = df.sort_values("Dátum").set_index("Dátum")
            
            try:
                if comp_period_type == "Napi": res = df.resample("D").sum().reset_index()
                elif comp_period_type == "Heti (Cs)": res = df.resample("W-THU").sum().reset_index()
                else: res = df.resample("ME").sum().reset_index()
            except Exception:
                res = df.reset_index()
            
            res["Érték"] = res["Érték"].fillna(0)
            items = res.values.tolist()
            if len(items) > max_len: max_len = len(items)
            processed_series.append((stat_name, s_unit, items))
            
        if max_len > 0:
            for idx, (stat_name, s_unit, items) in enumerate(processed_series):
                y_vals = [item[1] for item in items]
                orig_dates = [dt.strftime("%Y.%m.%d.") if isinstance(dt, (pd.Timestamp, datetime)) else str(dt) for dt, _ in items]
                
                x_idx_current = list(range(1, len(y_vals) + 1))
                formatted_texts = [f"{int(y):,} {s_unit}".replace(",", " ") if float(y).is_integer() else f"{y} {s_unit}" for y in y_vals]
                trace_color = color_palette[idx % len(color_palette)]
                
                fig.add_trace(go.Scatter(
                    x=x_idx_current, y=y_vals, mode='lines+markers',
                    name=stat_name, customdata=orig_dates,
                    hovertemplate="<b>%{fullData.name}</b><br>Sorszám: %{x}.<br><b>Dátum: %{customdata}</b><br>Érték: %{text}<extra></extra>",
                    text=formatted_texts, line=dict(color=trace_color, width=5), marker=dict(size=12, color=trace_color)
                ))
                
                for x_val, y_val, txt, d_str in zip(x_idx_current, y_vals, formatted_texts, orig_dates):
                    annotation_text = f"{txt}<br><span style='font-size:11px; color:#475569;'>({d_str})</span>" if show_dates_on_chart else txt
                    fig.add_annotation(x=x_val, y=y_val, text=annotation_text, showarrow=False, yshift=18, textangle=-90, font=dict(size=13, color=trace_color, family="Arial Black"), xanchor="center", yanchor="bottom")
            
            fig.update_layout(
                title=dict(text=f"<b>Statisztikák Relatív Összevetése ({comp_period_type})</b>", x=0.5, font=dict(size=36, color="#000000")),
                plot_bgcolor="white", paper_bgcolor="white", margin=dict(t=120, b=120, l=60, r=40),
                xaxis=dict(tickmode="array", tickvals=list(range(1, max_len + 1)), ticktext=[f"{i}." for i in range(1, max_len + 1)], title=dict(text="Relatív Időszak Sorszáma", font=dict(size=16, color="#000000")), showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5, showline=True, linecolor="#000000", linewidth=3, mirror=True, tickfont=dict(color="#000000", size=15, family="Arial Black")),
                yaxis=dict(rangemode="tozero", showgrid=True, gridcolor="#F1F5F9", gridwidth=2.5, showline=True, linecolor="#000000", linewidth=3, mirror=True, tickfont=dict(color="#000000", size=18, family="Arial Black")),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=16))
            )
            st.plotly_chart(fig, use_container_width=True)

# 3. ÖSSZESÍTŐ DASHBOARD (KÁRTYA NÉZET + ÁLLAPOTOK)
elif selected_menu == "📋 Összesítő Dashboard (Kártya Nézet)":
    st.title("📋 Teljesítménymérő Statisztikák Dashboard")
    
    all_groups = db.get("groups", ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"])
    selected_group_filter = st.selectbox("Szűrés csoport / részleg szerint:", ["Összes csoport"] + all_groups)
    
    col_search, _ = st.columns([4, 1])
    with col_search:
        search_query = st.text_input("Keresés:", placeholder="Keresés a statisztikák között...", key="dash_search")
    
    filtered_stats = []
    for s in stat_names:
        s_group = db["stats"][s].get("group", "Egyéb")
        if selected_group_filter != "Összes csoport" and s_group != selected_group_filter: continue
        if search_query and search_query.lower() not in s.lower(): continue
        filtered_stats.append(s)

    if not filtered_stats:
        st.info("Nincs találat a megadott feltételeknek megfelelő statisztikára.")
    else:
        for i in range(0, len(filtered_stats), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(filtered_stats):
                    s_name = filtered_stats[i + j]
                    s_info = db["stats"][s_name]
                    s_data_raw = s_info["data"]
                    s_unit = s_info.get("unit", "")
                    s_group = s_info.get("group", "Egyéb")
                    s_settings = db.get("settings", {}).get(s_name, {})
                    s_inverted = s_info.get("inverted", False)
                    
                    p_name = s_settings.get("person_name", "")
                    p_post = s_settings.get("person_post", "")
                    assigned_str = f"{p_name} ({p_post})" if p_name or p_post else "Nincs megadva"
                    
                    card_surv_val = s_settings.get("survival_value", s_settings.get("goal_value", 0.0))
                    card_items = sorted(s_data_raw, key=lambda x: str(x[0])) if s_data_raw else []
                    
                    if s_settings.get("is_accumulated", False) and card_items:
                        base_v = float(s_settings.get("initial_accumulated_val", 0.0))
                        acc_card_items = []
                        running_tot = base_v
                        for item in card_items:
                            running_tot += float(item[1])
                            acc_card_items.append([item[0], running_tot, item[2] if len(item)>2 else ""])
                        card_items = acc_card_items

                    card_y = [item[1] for item in card_items] if card_items else []
                    
                    condition_text, condition_color = calculate_stat_condition(s_data_raw, card_surv_val)
                    
                    with cols[j]:
                        with st.container(border=True):
                            h_col1, h_col2 = st.columns([3, 1])
                            with h_col1:
                                st.markdown(f"### **{s_name}**")
                                st.caption(f"📁 **Részleg:** {s_group} | 👤 **Assigned to:** {assigned_str}")
                            with h_col2:
                                color_map = {"green": "🟢", "blue": "🔵", "yellow": "🟡", "orange": "🟠", "red": "🔴", "gray": "⚪"}
                                st.markdown(f"<div style='text-align: right; font-weight: bold; font-size: 14px;'>{color_map.get(condition_color, '⚪')} {condition_text}</div>", unsafe_allow_html=True)
                            
                            dates_parsed = [datetime.strptime(item[0], "%Y-%m-%d").date() for item in s_data_raw] if s_data_raw else []
                            min_d = min(dates_parsed) if dates_parsed else None
                            max_d = max(dates_parsed) if dates_parsed else None
                            
                            if card_items:
                                fig_card = go.Figure()
                                x_num = list(range(len(card_items)))
                                c_notes = [item[2] if len(item) > 2 else "" for item in card_items]
                                
                                for k in range(len(card_items) - 1):
                                    x1, y1 = x_num[k], card_y[k]
                                    x2, y2 = x_num[k+1], card_y[k+1]
                                    color = "#00C853" if (y2 < y1 if s_inverted else y2 > y1) else "#FF1744"
                                    fig_card.add_trace(go.Scatter(x=[x1, x2], y=[y1, y2], mode='lines', line=dict(color=color, width=3.5), showlegend=False, hoverinfo='skip'))
                                
                                if card_surv_val > 0:
                                    fig_card.add_hline(y=card_surv_val, line_dash="dash", line_color="#EF4444", line_width=2)

                                formatted_t = [f"{int(y):,} {s_unit}".replace(",", " ") if float(y).is_integer() else f"{y} {s_unit}" for y in card_y]
                                x_fmt = [datetime.strptime(str(item[0]), "%Y-%m-%d").strftime("%b %d") for item in card_items]
                                hover_c = [f"Dátum: {dt}<br>Érték: {txt}<br>Megjegyzés: {n}" if n else f"Dátum: {dt}<br>Érték: {txt}" for dt, txt, n in zip(x_fmt, formatted_t, c_notes)]

                                fig_card.add_trace(go.Scatter(x=x_num, y=card_y, mode='markers', marker=dict(size=8, color="#1E293B"), hovertext=hover_c, hoverinfo='text', showlegend=False))
                                
                                for x_val, y_val, txt in zip(x_num, card_y, formatted_t):
                                    fig_card.add_annotation(x=x_val, y=y_val, text=txt, showarrow=False, yshift=10, textangle=-90, font=dict(size=10, color="#000000", family="Arial Black"), xanchor="center", yanchor="bottom")
                                
                                yaxis_card = dict(showgrid=True, gridcolor="#F1F5F9", gridwidth=1.5, tickfont=dict(color="#000", size=11, family="Arial Black"), showline=True, linecolor="#000", linewidth=1.5, mirror=True)
                                if s_inverted: yaxis_card["autorange"] = "reversed"
                                else: yaxis_card["rangemode"] = "tozero"
                                
                                fig_card.update_layout(
                                    height=300, plot_bgcolor="white", paper_bgcolor="white",
                                    margin=dict(t=10, b=40, l=40, r=20),
                                    xaxis=dict(tickmode="array", tickvals=x_num, ticktext=x_fmt, tickangle=-45, showgrid=True, gridcolor="#F1F5F9", gridwidth=1.5, tickfont=dict(color="#000", size=10, family="Arial Black"), showline=True, linecolor="#000", linewidth=1.5, mirror=True),
                                    yaxis=yaxis_card
                                )
                                st.plotly_chart(fig_card, use_container_width=True, config={'displayModeBar': False})
                            else:
                                st.info("Nincs megjeleníthető adat.")
                                
                            c_date1, c_date2 = st.columns(2)
                            with c_date1:
                                st.date_input("Mikortól:", value=min_d, key=f"from_{s_name}_{i}_{j}") if min_d else st.text_input("Mikortól:", value="", key=f"from_empty_{s_name}_{i}_{j}")
                            with c_date2:
                                st.date_input("Meddig:", value=max_d, key=f"to_{s_name}_{i}_{j}") if max_d else st.text_input("Meddig:", value="", key=f"to_empty_{s_name}_{i}_{j}")

# 4. ESEMÉNYNAPLÓ
elif selected_menu == "📖 Eseménynapló":
    st.title("📖 Rendszer Eseménynapló & Megjegyzések")
    st.write("Itt láthatod az összes statisztikához rögzített eseményt és megjegyzést időrendben.")
    
    all_events = []
    for s_name in stat_names:
        s_data = db["stats"][s_name]["data"]
        s_unit = db["stats"][s_name].get("unit", "")
        for item in s_data:
            if len(item) > 2 and item[2].strip():
                all_events.append({
                    "date": item[0],
                    "stat": s_name,
                    "value": f"{item[1]} {s_unit}",
                    "note": item[2]
                })
    
    if all_events:
        all_events_sorted = sorted(all_events, key=lambda x: x["date"], reverse=True)
        df_events = pd.DataFrame(all_events_sorted)
        df_events.columns = ["Dátum", "Statisztika neve", "Érték", "Esemény / Megjegyzés"]
        st.dataframe(df_events, use_container_width=True, hide_index=True)
    else:
        st.info("Még nincsenek rögzített események vagy megjegyzések a statisztikákhoz.")

# 5. ÚJ STATISZTIKA LÉTREHOZÁSA
elif selected_menu == "➕ Új Statisztika Létrehozása":
    st.title("➕ Új Statisztika Kategória Létrehozása")
    st.write("Itt hozhatsz létre új adatsort és sorolhatod be a megfelelő részlegbe.")
    
    groups_list = db.get("groups", ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"])
    
    with st.form("create_stat_form"):
        new_stat_name = st.text_input("Statisztika neve:", placeholder="pl. Új Eladások")
        new_stat_unit = st.text_input("Mértékegység:", placeholder="pl. Ft, db, fő")
        new_stat_group = st.selectbox("Csoport / Részleg:", options=groups_list)
        is_new_inverted = st.checkbox("Fordított statisztika (a 0 felül van és lefelé nő)")
        
        submit = st.form_submit_button("Létrehozás")
        if submit:
            if new_stat_name:
                if new_stat_name not in db["stats"]:
                    db["stats"][new_stat_name] = {
                        "unit": new_stat_unit, 
                        "group": new_stat_group,
                        "inverted": is_new_inverted, 
                        "data": []
                    }
                    save_data(db)
                    st.success(f"Sikeresen létrehozva: {new_stat_name} ({new_stat_unit}) - Részleg: {new_stat_group}")
                else:
                    st.error("Ilyen nevű statisztika már létezik!")
            else:
                st.warning("Adj meg egy nevet!")

# 6. ADMINISZTRÁCIÓ & ARCHÍVUM
elif selected_menu == "⚙️ Adminisztráció & Archívum":
    st.title("⚙️ Rendszer Adminisztráció")
    
    st.subheader("📁 Csoportok / Részlegek Kezelése")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        new_group_name = st.text_input("Új részleg / csoport neve:")
        if st.button("➕ Részleg Hozzáadása"):
            if new_group_name and new_group_name not in db["groups"]:
                db["groups"].append(new_group_name)
                save_data(db)
                st.success(f"'{new_group_name}' sikeresen létrehozva!")
                st.rerun()
            else:
                st.warning("Add meg a nevet vagy már létezik ilyen részleg!")
                
    with col_g2:
        st.markdown("#### Meglévő részlegek törlése")
        current_groups_list = db.get("groups", [])
        group_to_delete = st.selectbox("Törlendő részleg:", options=current_groups_list if current_groups_list else [""])
        if st.button("🗑️ Részleg Törlése") and group_to_delete:
            if group_to_delete in db["groups"]:
                db["groups"].remove(group_to_delete)
                for s_key in db["stats"]:
                    if db["stats"][s_key].get("group") == group_to_delete:
                        db["stats"][s_key]["group"] = "Egyéb"
                save_data(db)
                st.success(f"'{group_to_delete}' részleg törölve!")
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

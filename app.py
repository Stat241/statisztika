import json
import os
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# ================= OLDAL ALAPBEÁLLÍTÁSAI =================
st.set_page_config(
    page_title="Statisztika Kezelő Rendszer", layout="wide", page_icon="📊"
)

# ================= NYOMTATÁSI CSS (KIZÁRÓLAG A GRAFIKON NYOMTATÁSA) =================
st.markdown(
    """
    <style>
    @media print {
        @page {
            size: A4 landscape;
            margin: 5mm !important;
        }
        
        /* Nyomtatáskor MINDEN rejtve van, ami nem maga a grafikon */
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
        
        /* A főkonténer elemeiből is elrejtjük a grafikont nem tartalmazó blokkokat */
        [data-testid="stMainBlockContainer"] > div:not(:has(.stPlotlyChart)) {
            display: none !important;
        }
        
        /* Tiszta keret és A4 lapra illesztés */
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

# ================= ADATTÁROLÁS & FÜGGVÉNYEK =================
DB_FILE = "statisztikak.json"
ARCHIVE_FILE = "archivum.json"


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
    return f"{s}.{clean_unit}."
  return s


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
                  ["2026-07-23 14:00", 650000, "Nyitó kampány"],
                  ["2026-07-30 14:00", 97500, ""],
                  ["2026-08-06 14:00", 97500, ""],
                  ["2026-08-13 14:00", 547500, "Új ügyfél szerződés"],
                  ["2026-08-20 14:00", 347500, ""],
                  ["2026-08-27 14:00", 1570799, "Havi zárás pörgés"],
                  ["2026-09-03 14:00", 2350000, "Prémium csomagok"],
                  ["2026-09-10 14:00", 390000, ""],
                  ["2026-09-17 14:00", 4722200, "Rekord bevétel"],
                  ["2026-09-24 14:00", 0, "Ünnepnap / leállás"],
                  ["2026-10-01 14:00", 945000, ""],
              ],
          },
          "Ügyfelek száma": {
              "unit": "fő",
              "group": "Értékesítés",
              "inverted": False,
              "data": [
                  ["2026-08-08 14:00", 5, "Első körös hívások"],
                  ["2026-08-15 14:00", 12, ""],
                  ["2026-08-25 14:00", 18, "Ajánlások"],
                  ["2026-08-30 14:00", 25, ""],
                  ["2026-09-13 14:00", 34, "Marketing akció"],
              ],
          },
      },
      "settings": {},
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
    return "Nincs adat", "gray"

  try:
    sorted_d = sorted(data, key=lambda x: str(x[0]))
    last_val = float(sorted_d[-1][1])

    if survival_line > 0 and last_val < survival_line:
      return "Nem-létezés (Életvonal alatt)", "red"

    if len(sorted_d) < 2:
      return "Normál trend", "green"

    window = sorted_d[-4:] if len(sorted_d) >= 4 else sorted_d
    vals = [float(item[1]) for item in window]

    if all(v == 0 for v in vals):
      return "Nem-létezés", "red"

    first_v = vals[0]
    last_v = vals[-1]
    diff = last_v - first_v

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


# ================= SESSION STATE =================
if "db" not in st.session_state:
  st.session_state.db = load_data()
db = st.session_state.db

if "groups" not in db:
  db["groups"] = ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
  save_data(db)

all_stat_names = list(db["stats"].keys())
stat_names = all_stat_names

# ================= NAVIGÁCIÓ =================
st.sidebar.title("📌 Navigáció")
st.sidebar.info("Rendszer: **Admin Mód**")

menu_options = [
    "📊 Egyedi Statisztika Nézet",
    "📈 Több Statisztika Összevetése",
    "📋 Összesítő Dashboard (Kártya Nézet)",
    "➕ Új Statisztika Létrehozása",
    "⚙️ Adminisztráció & Archívum",
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

    current_unit = db["stats"][selected_stat].get("unit", "")
    stat_group = db["stats"][selected_stat].get("group", "Egyéb")
    stat_settings = db.get("settings", {}).get(selected_stat, {})
    is_inverted = db["stats"][selected_stat].get("inverted", False)

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
    st.sidebar.subheader("📅 Időszakos összesítés")
    valid_aggs = [
        "Napi adatok",
        "Heti (Csütörtöki zárás 14:00)",
        "Havi összesítés",
    ]
    indiv_agg = st.sidebar.selectbox(
        "Grafikon nézet:", valid_aggs, key=f"indiv_agg_view_{selected_stat}"
    )

    mode_settings = stat_settings.get(indiv_agg, {})
    valid_surv = ["Nincs", "Fix érték (db/Ft)"]
    valid_goals = ["Nincs", "Fix érték (db/Ft)", "Százalékos növekedés (%)"]

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
    surv_type_val = mode_settings.get("survival_type", "Nincs")
    survival_type = st.sidebar.selectbox(
        "Életvonal típusa:",
        valid_surv,
        index=valid_surv.index(surv_type_val)
        if surv_type_val in valid_surv
        else 0,
        key=f"surv_type_{selected_stat}_{indiv_agg}",
    )
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

    if st.sidebar.button(
        "💾 Beállítások Mentése", key=f"save_btn_{selected_stat}"
    ):
      if "settings" not in db:
        db["settings"] = {}
      if selected_stat not in db["settings"]:
        db["settings"][selected_stat] = {}

      db["settings"][selected_stat]["person_name"] = person_name
      db["settings"][selected_stat]["person_post"] = person_post
      db["settings"][selected_stat]["chart_height"] = chart_height
      db["settings"][selected_stat]["margin_l"] = margin_l
      db["settings"][selected_stat]["margin_r"] = margin_r
      db["settings"][selected_stat]["margin_t"] = margin_t
      db["settings"][selected_stat]["margin_b"] = margin_b
      db["settings"][selected_stat][
          "show_acc_in_brackets"
      ] = show_acc_in_brackets
      db["settings"][selected_stat][
          "initial_accumulated_val"
      ] = initial_accumulated_val

      db["settings"][selected_stat][indiv_agg] = {
          "ymin": ymin,
          "ymax": ymax,
          "ystep": ystep,
          "survival_type": survival_type,
          "survival_value": survival_value,
          "show_survival": show_survival_line,
          "goal_type": goal_type,
          "goal_val_target": goal_value,
      }

      db["stats"][selected_stat]["inverted"] = is_stat_inverted_check
      save_data(db)
      st.sidebar.success(f"Beállítások elmentve ({indiv_agg})!")
      st.rerun()

    # --- GRAFIKON NÉZET ---
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

      if indiv_agg == "Heti (Csütörtöki zárás 14:00)":
        df_temp["Period_End"] = df_temp["Sort_Key"].apply(
            get_thursday_period_end
        )
        res_df = (
            df_temp.groupby("Period_End")
            .agg({
                "Érték": "sum",
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
                "Érték": "sum",
                "Megjegyzés": lambda x: " | ".join(
                    [str(n) for n in x if n and str(n).strip()]
                ),
            })
            .reset_index()
            .sort_values("Period_Month")
        )

        raw_items = []
        for idx, row in res_df.iterrows():
          d_str = row["Period_Month"].strftime("%Y-%m-%d")
          raw_items.append({
              "x": len(raw_items),
              "date_str": d_str,
              "label": row["Period_Month"].strftime("%Y. %m. %d."),
              "hover_label": row["Period_Month"].strftime("%Y. %m. %d."),
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
                "Érték": "sum",
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

    y_vals_temp = [item["val"] for item in raw_items] if raw_items else []
    calc_survival_val = (
        survival_value if survival_type == "Fix érték (db/Ft)" else 0.0
    )

    calc_goal_val = 0.0
    if goal_type == "Fix érték (db/Ft)":
      calc_goal_val = goal_value
    elif goal_type == "Százalékos növekedés (%)" and len(y_vals_temp) > 0:
      calc_goal_val = y_vals_temp[-1] * (1 + goal_value / 100)

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

        if show_survival_line and calc_survival_val > 0:
          fig.add_hline(
              y=calc_survival_val,
              line_dash="solid",
              line_color="#4B5563",
              line_width=4,
          )

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
              font=dict(size=20, family="Arial Black", color="#000000"),
          )

        if goal_type != "Nincs" and calc_goal_val > 0:
          goal_fmt = fmt_num(calc_goal_val, current_unit)
          fig.add_annotation(
              xref="paper",
              yref="paper",
              x=1.0,
              y=1.08,
              text=f"🎯 Cél: {goal_fmt}",
              showarrow=False,
              align="right",
              xanchor="right",
              yanchor="bottom",
              font=dict(size=20, color="#C5A059", family="Arial Black"),
          )

        yaxis_dict = dict(
            title=dict(text="", font=dict(color="#000000", size=1)),
            showgrid=True,
            gridcolor="#F1F5F9",
            gridwidth=3,
            tickfont=dict(color="#000000", size=20, family="Arial Black"),
            showline=True,
            linecolor="#000000",
            linewidth=3.5,
            mirror=True,
        )
        if is_stat_inverted_check:
          yaxis_dict["autorange"] = "reversed"
        else:
          yaxis_dict["rangemode"] = "tozero"

        xaxis_range = (
            [0, max(unique_x) + 0.6] if len(unique_x) > 1 else [0, 0.5]
        )

        layout_args = dict(
            title=dict(
                text=(
                    f"<b>{selected_stat}</b><br><span style='font-size: 20px;"
                    f" color: #1E293B;'>Időszak: {date_range_str}"
                    f" ({indiv_agg})</span>"
                ),
                x=0.5,
                xref="paper",
                xanchor="center",
                yanchor="top",
                font=dict(size=30, color="#000000"),
            ),
            plot_bgcolor="white",
            paper_bgcolor="white",
            autosize=True,
            height=chart_height,
            margin=dict(t=margin_t, b=margin_b, l=margin_l, r=margin_r),
            xaxis=dict(
                title=dict(text="", font=dict(color="#000000", size=1)),
                tickmode="array",
                tickvals=unique_x,
                ticktext=unique_labels,
                tickangle=-30,
                showgrid=True,
                gridcolor="#F1F5F9",
                gridwidth=3,
                tickfont=dict(color="#000000", size=15, family="Arial Black"),
                showline=True,
                linecolor="#000000",
                linewidth=3.5,
                mirror=True,
                range=xaxis_range,
            ),
            yaxis=yaxis_dict,
        )

        try:
          if ymin and ymax:
            layout_args["yaxis"]["range"] = [float(ymin), float(ymax)]
          if ystep:
            layout_args["yaxis"]["dtick"] = float(ystep)
        except Exception:
          pass

        fig.update_layout(**layout_args)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # --- ÚJ ADAT HOZZÁADÁSA ---
    st.subheader(f"➕ Új Adat Hozzáadása ({selected_stat})")

    with st.form("add_data_form", clear_on_submit=True):
      col_d, col_t = st.columns(2)
      with col_d:
        input_date = st.date_input("Dátum")
      with col_t:
        input_time = st.time_input("Időpont", value=datetime.now().time())

      input_val = st.number_input(
          f"Érték ({current_unit})", min_value=0.0, step=1.0
      )
      input_note = st.text_input("Megjegyzés / Esemény ehhez a ponthoz:")
      if st.form_submit_button("Adat Hozzáadása"):
        full_dt_str = (
            f"{input_date.strftime('%Y-%m-%d')} {input_time.strftime('%H:%M')}"
        )
        db["stats"][selected_stat]["data"].append(
            [full_dt_str, input_val, input_note]
        )
        db["stats"][selected_stat]["data"] = sorted(
            db["stats"][selected_stat]["data"],
            key=lambda x: pd.to_datetime(
                str(x[0]), format="mixed", errors="coerce"
            ),
        )
        save_data(db)
        st.success("Adat hozzáadva!")
        st.rerun()

    st.markdown("---")

    # --- ADAT-TÁBLÁZAT ÉS MÓDOSÍTÁS ---
    st.subheader("📋 Adat-táblázat Szerkesztése (Időrendben)")

    stat_data_raw = db["stats"][selected_stat]["data"]

    if stat_data_raw:
      table_rows = []
      for item in stat_data_raw:
        dt_str = str(item[0]).strip()
        parts = dt_str.split()
        d_part = parts[0] if len(parts) > 0 else ""
        t_part = parts[1] if len(parts) > 1 else "00:00"

        try:
          v_part = float(item[1])
          if v_part.is_integer():
            v_part = int(v_part)
        except (ValueError, TypeError):
          v_part = 0

        n_part = (
            str(item[2]).strip()
            if len(item) > 2 and item[2] is not None and str(item[2]) != "nan"
            else ""
        )
        table_rows.append([d_part, t_part, v_part, n_part])

      df_raw = pd.DataFrame(
          table_rows,
          columns=[
              "Dátum",
              "Időpont",
              f"Érték ({current_unit})",
              "Megjegyzés",
          ],
      )

      with st.form(f"edit_table_form_{selected_stat}"):
        edited_df = st.data_editor(
            df_raw,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Dátum": st.column_config.TextColumn(
                    "Dátum (ÉÉÉÉ-HH-NN)", help="pl. 2026-10-06"
                ),
                "Időpont": st.column_config.TextColumn(
                    "Időpont (ÓÓ:PP)", help="pl. 13:28"
                ),
            },
            key=f"editor_{selected_stat}",
        )
        save_table_btn = st.form_submit_button(
            "💾 Táblázat Módosításainak Mentése"
        )

      if save_table_btn:
        updated_data = []
        for _, row in edited_df.iterrows():
          d_val = str(row["Dátum"]).strip() if pd.notnull(row["Dátum"]) else ""
          t_val = (
              str(row["Időpont"]).strip()
              if pd.notnull(row["Időpont"])
              else "00:00"
          )
          if not t_val or t_val == "nan":
            t_val = "00:00"

          if d_val and d_val != "nan":
            full_dt = f"{d_val} {t_val}".strip()
            try:
              v_val = (
                  float(row[f"Érték ({current_unit})"])
                  if pd.notnull(row[f"Érték ({current_unit})"])
                  else 0.0
              )
              if v_val.is_integer():
                v_val = int(v_val)
            except (ValueError, TypeError):
              v_val = 0
            n_val = (
                str(row["Megjegyzés"]).strip()
                if pd.notnull(row["Megjegyzés"])
                and str(row["Megjegyzés"]) != "nan"
                else ""
            )
            updated_data.append([full_dt, v_val, n_val])

        updated_data = sorted(
            updated_data,
            key=lambda x: pd.to_datetime(
                str(x[0]), format="mixed", errors="coerce"
            ),
        )
        db["stats"][selected_stat]["data"] = updated_data
        save_data(db)
        st.success("Táblázat sikeresen elmentve!")
        st.rerun()
    else:
      st.info("Még nincsenek rögzített adatok ebben a statisztikában.")

# 2. TÖBB STATISZTIKA ÖSSZEVETÉSE
elif selected_menu == "📈 Több Statisztika Összevetése":
  st.title("📈 Statisztikák Relatív Összevetése")
  st.write(
      "A görbék sorszám szerint egymásra illesztve jelennek meg, megőrizve az"
      " eredeti naptári dátumokat."
  )

  comp_period_type = st.radio(
      "Összehasonlítás alapja:",
      ["Napi", "Heti (Cs 14:00)", "Havi"],
      horizontal=True,
  )
  show_dates_on_chart = st.checkbox(
      "Eredeti dátumok megjelenítése a feliratokban", value=True
  )

  selected_multi_stats = st.multiselect(
      "Válassz statisztikákat az összevetéshez:",
      stat_names,
      default=stat_names[:2] if len(stat_names) >= 2 else stat_names,
  )

  if selected_multi_stats:
    fig = go.Figure()
    color_palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    max_len = 0
    processed_series = []

    for stat_name in selected_multi_stats:
      stat_data = db["stats"][stat_name]["data"]
      s_unit = db["stats"][stat_name].get("unit", "")
      if not stat_data:
        continue

      clean_data = [[item[0], item[1]] for item in stat_data]
      df = pd.DataFrame(clean_data, columns=["Dátum", "Érték"])
      df["Sort_Key"] = pd.to_datetime(
          df["Dátum"], format="mixed", errors="coerce"
      )
      df = df.dropna(subset=["Sort_Key"])
      df = df.sort_values("Sort_Key")

      try:
        if comp_period_type == "Napi":
          df["Daily_Bucket"] = df["Sort_Key"].apply(
              lambda dt: dt.strftime("%Y-%m-%d")
          )
          res = (
              df.groupby(["Daily_Bucket"], sort=False)
              .agg({"Sort_Key": "min", "Érték": "sum"})
              .reset_index()
              .sort_values("Sort_Key")
              .rename(columns={"Daily_Bucket": "Dátum"})
          )
        elif comp_period_type == "Heti (Cs 14:00)":
          df["Period_End"] = df["Sort_Key"].apply(get_thursday_period_end)
          res = (
              df.groupby("Period_End")
              .agg({"Érték": "sum"})
              .reset_index()
              .rename(columns={"Period_End": "Dátum"})
          )
        else:
          df["Period_Month"] = (
              df["Sort_Key"]
              .dt.to_period("M")
              .dt.to_timestamp(how="end")
              .dt.floor("D")
          )
          res = (
              df.groupby("Period_Month")
              .agg({"Érték": "sum"})
              .reset_index()
              .rename(columns={"Period_Month": "Dátum"})
          )
      except Exception:
        res = df

      res["Érték"] = res["Érték"].fillna(0)
      items = res[["Dátum", "Érték"]].values.tolist()
      if len(items) > max_len:
        max_len = len(items)
      processed_series.append((stat_name, s_unit, items))

    if max_len > 0:
      for idx, (stat_name, s_unit, items) in enumerate(processed_series):
        y_vals = [item[1] for item in items]
        orig_dates = [
            dt.strftime("%Y.%m.%d.")
            if isinstance(dt, (pd.Timestamp, datetime))
            else str(dt)
            for dt, _ in items
        ]

        x_idx_current = list(range(1, len(y_vals) + 1))
        formatted_texts = [fmt_num(y, s_unit) for y in y_vals]
        trace_color = color_palette[idx % len(color_palette)]

        fig.add_trace(
            go.Scatter(
                x=x_idx_current,
                y=y_vals,
                mode="lines+markers",
                name=stat_name,
                customdata=orig_dates,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>Sorszám:"
                    " %{x}.<br><b>Dátum: %{customdata}</b><br>Érték:"
                    " %{text}<extra></extra>"
                ),
                text=formatted_texts,
                line=dict(color=trace_color, width=5),
                marker=dict(size=12, color=trace_color),
                cliponaxis=False,
            )
        )

        for x_val, y_val, txt, d_str in zip(
            x_idx_current, y_vals, formatted_texts, orig_dates
        ):
          annotation_text = (
              f"{txt}<br>({d_str})" if show_dates_on_chart else txt
          )
          fig.add_annotation(
              x=x_val,
              y=y_val,
              text=annotation_text,
              showarrow=False,
              yshift=12,
              xshift=18,
              textangle=-75,
              font=dict(size=11, color=trace_color, family="Arial Black"),
              xanchor="center",
              yanchor="bottom",
          )

      fig.update_layout(
          title=dict(
              text=(
                  "<b>Statisztikák Relatív Összevetése"
                  f" ({comp_period_type})</b>"
              ),
              x=0.5,
              font=dict(size=36, color="#000000"),
          ),
          plot_bgcolor="white",
          paper_bgcolor="white",
          height=650,
          margin=dict(t=120, b=120, l=60, r=40),
          xaxis=dict(
              tickmode="array",
              tickvals=list(range(1, max_len + 1)),
              ticktext=[f"{i}." for i in range(1, max_len + 1)],
              title=dict(
                  text="Relatív Időszak Sorszáma",
                  font=dict(size=16, color="#000000"),
              ),
              showgrid=True,
              gridcolor="#F1F5F9",
              gridwidth=2.5,
              showline=True,
              linecolor="#000000",
              linewidth=3,
              mirror=True,
              tickfont=dict(color="#000000", size=15, family="Arial Black"),
          ),
          yaxis=dict(
              rangemode="tozero",
              showgrid=True,
              gridcolor="#F1F5F9",
              gridwidth=2.5,
              showline=True,
              linecolor="#000000",
              linewidth=3,
              mirror=True,
              tickfont=dict(color="#000000", size=18, family="Arial Black"),
          ),
          legend=dict(
              orientation="h",
              yanchor="bottom",
              y=1.02,
              xanchor="right",
              x=1,
              font=dict(size=16),
          ),
      )
      st.plotly_chart(fig, use_container_width=True)

# 3. ÖSSZESÍTŐ DASHBOARD
elif selected_menu == "📋 Összesítő Dashboard (Kártya Nézet)":
  st.title("📋 Teljesítménymérő Statisztikák Dashboard")

  all_groups = db.get(
      "groups", ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
  )
  selected_group_filter = st.selectbox(
      "Szűrés csoport / részleg szerint:", ["Összes csoport"] + all_groups
  )

  col_search, _ = st.columns([4, 1])
  with col_search:
    search_query = st.text_input(
        "Keresés:",
        placeholder="Keresés a statisztikák között...",
        key="dash_search",
    )

  filtered_stats = []
  for s in stat_names:
    s_group = db["stats"][s].get("group", "Egyéb")
    if (
        selected_group_filter != "Összes csoport"
        and s_group != selected_group_filter
    ):
      continue
    if search_query and search_query.lower() not in s.lower():
      continue
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
          assigned_str = (
              f"{p_name} ({p_post})" if p_name or p_post else "Nincs megadva"
          )

          card_surv_val = 0.0
          card_goal_type = "Nincs"
          card_goal_target = 0.0

          for m_key in [
              "Heti (Csütörtöki zárás 14:00)",
              "Napi adatok",
              "Havi összesítés",
          ]:
            if m_key in s_settings:
              m_dict = s_settings[m_key]
              if m_dict.get("show_survival", True) and float(
                  m_dict.get("survival_value", 0.0)
              ) > 0:
                card_surv_val = float(m_dict.get("survival_value", 0.0))
              if m_dict.get("goal_type", "Nincs") != "Nincs":
                card_goal_type = m_dict.get("goal_type", "Nincs")
                card_goal_target = float(m_dict.get("goal_val_target", 0.0))
              if card_surv_val > 0 or card_goal_type != "Nincs":
                break

          card_items = (
              sorted(s_data_raw, key=lambda x: str(x[0])) if s_data_raw else []
          )
          card_y = (
              [float(item[1]) for item in card_items] if card_items else []
          )

          card_calc_goal = 0.0
          if card_goal_type == "Fix érték (db/Ft)":
            card_calc_goal = card_goal_target
          elif card_goal_type == "Százalékos növekedés (%)" and len(card_y) > 0:
            card_calc_goal = card_y[-1] * (1 + card_goal_target / 100)

          condition_text, condition_color = calculate_stat_condition(
              s_data_raw, card_surv_val
          )

          with cols[j]:
            with st.container(border=True):
              h_col1, h_col2 = st.columns([3, 1])
              with h_col1:
                st.markdown(f"### **{s_name}**")
                st.caption(
                    f"📁 **Részleg:** {s_group} | 👤 **Assigned to:**"
                    f" {assigned_str}"
                )
              with h_col2:
                color_map = {
                    "green": "🟢",
                    "blue": "🔵",
                    "yellow": "🟡",
                    "orange": "🟠",
                    "red": "🔴",
                    "gray": "⚪",
                }
                st.markdown(
                    "<div style='text-align: right; font-weight: bold;"
                    f" font-size: 14px;'>{color_map.get(condition_color, '⚪')}"
                    f" {condition_text}</div>",
                    unsafe_allow_html=True,
                )

              if card_items:
                fig_card = go.Figure()
                x_num = list(range(len(card_items)))
                c_notes = [
                    item[2] if len(item) > 2 else "" for item in card_items
                ]

                for k in range(len(card_items) - 1):
                  x1, y1 = x_num[k], card_y[k]
                  x2, y2 = x_num[k + 1], card_y[k + 1]
                  color = (
                      "#00C853"
                      if (y2 < y1 if s_inverted else y2 > y1)
                      else "#FF1744"
                  )
                  fig_card.add_trace(
                      go.Scatter(
                          x=[x1, x2],
                          y=[y1, y2],
                          mode="lines",
                          line=dict(color=color, width=3.5),
                          showlegend=False,
                          hoverinfo="skip",
                      )
                  )

                if card_surv_val > 0:
                  fig_card.add_hline(
                      y=card_surv_val,
                      line_dash="solid",
                      line_color="#4B5563",
                      line_width=2.5,
                  )

                if card_goal_type != "Nincs" and card_calc_goal > 0:
                  fig_card.add_hline(
                      y=card_calc_goal,
                      line_dash="dash",
                      line_color="#C5A059",
                      line_width=2,
                  )

                formatted_t = [fmt_num(y, s_unit) for y in card_y]
                x_fmt = [
                    pd.to_datetime(
                        str(item[0]), format="mixed", errors="coerce"
                    ).strftime("%b %d")
                    for item in card_items
                ]
                hover_c = [
                    (
                        f"Dátum: {dt}<br>Érték: {txt}<br>Megjegyzés: {n}"
                        if n
                        else f"Dátum: {dt}<br>Érték: {txt}"
                    )
                    for dt, txt, n in zip(x_fmt, formatted_t, c_notes)
                ]

                fig_card.add_trace(
                    go.Scatter(
                        x=x_num,
                        y=card_y,
                        mode="markers",
                        marker=dict(size=8, color="#1E293B"),
                        cliponaxis=False,
                        hovertext=hover_c,
                        hoverinfo="text",
                        showlegend=False,
                    )
                )

                for x_val, y_val, txt in zip(x_num, card_y, formatted_t):
                  fig_card.add_annotation(
                      x=x_val,
                      y=y_val,
                      text=txt,
                      showarrow=False,
                      yshift=8,
                      xshift=5,
                      textangle=-75,
                      font=dict(size=9, color="#000000", family="Arial Black"),
                      xanchor="center",
                      yanchor="bottom",
                  )

                yaxis_card = dict(
                    showgrid=True,
                    gridcolor="#F1F5F9",
                    gridwidth=1.5,
                    tickfont=dict(color="#000", size=11, family="Arial Black"),
                    showline=True,
                    linecolor="#000",
                    linewidth=1.5,
                    mirror=True,
                )
                if s_inverted:
                  yaxis_card["autorange"] = "reversed"
                else:
                  yaxis_card["rangemode"] = "tozero"

                fig_card.update_layout(
                    height=300,
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    margin=dict(t=10, b=40, l=40, r=20),
                    xaxis=dict(
                        tickmode="array",
                        tickvals=x_num,
                        ticktext=x_fmt,
                        tickangle=-30,
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        gridwidth=1.5,
                        tickfont=dict(
                            color="#000", size=10, family="Arial Black"
                        ),
                        showline=True,
                        linecolor="#000",
                        linewidth=1.5,
                        mirror=True,
                    ),
                    yaxis=yaxis_card,
                )
                st.plotly_chart(
                    fig_card,
                    use_container_width=True,
                    config={"displayModeBar": False},
                )
              else:
                st.info("Nincs megjeleníthető adat.")

# 4. ÚJ STATISZTIKA LÉTREHOZÁSA
elif selected_menu == "➕ Új Statisztika Létrehozása":
  st.title("➕ Új Statisztika Kategória Létrehozása")
  st.write(
      "Itt hozhatsz létre új adatsort és sorolhatod be a megfelelő részlegbe."
  )

  groups_list = db.get(
      "groups", ["Pénzügy", "Értékesítés", "Marketing", "Adminisztráció"]
  )

  with st.form("create_stat_form"):
    new_stat_name = st.text_input(
        "Statisztika neve:", placeholder="pl. Új Eladások"
    )
    new_stat_unit = st.text_input("Mértékegység:", placeholder="pl. Ft, db, fő")
    new_stat_group = st.selectbox("Csoport / Részleg:", options=groups_list)
    is_new_inverted = st.checkbox(
        "Fordított statisztika (a 0 felül van és lefelé nő)"
    )

    submit = st.form_submit_button("Létrehozás")
    if submit:
      if new_stat_name:
        if new_stat_name not in db["stats"]:
          db["stats"][new_stat_name] = {
              "unit": new_stat_unit,
              "group": new_stat_group,
              "inverted": is_new_inverted,
              "data": [],
          }
          save_data(db)
          st.success(
              f"Sikeresen létrehozva: {new_stat_name} ({new_stat_unit}) -"
              f" Részleg: {new_stat_group}"
          )
        else:
          st.error("Ilyen nevű statisztika már létezik!")
      else:
        st.warning("Adj meg egy nevet!")

# 5. ADMINISZTRÁCIÓ & ARCHÍVUM
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
    group_to_delete = st.selectbox(
        "Törlendő részleg:",
        options=current_groups_list if current_groups_list else [""],
    )
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
  st.subheader("🗑️ Statisztika kategória végleges törlése")
  stat_to_delete_cat = st.selectbox(
      "Törlendő statisztika kategória:",
      options=all_stat_names if all_stat_names else [""],
  )
  if st.button("🗑️ Statisztika Törlése") and stat_to_delete_cat:
    if stat_to_delete_cat in db["stats"]:
      del db["stats"][stat_to_delete_cat]
      if "settings" in db and stat_to_delete_cat in db["settings"]:
        del db["settings"][stat_to_delete_cat]
      save_data(db)
      st.success(f"'{stat_to_delete_cat}' statisztika sikeresen törölve!")
      st.rerun()

  st.markdown("---")
  st.subheader("📂 Archívum kezelése")
  archive_db = load_archive()

  col_a1, col_a2 = st.columns(2)
  with col_a1:
    st.markdown("#### Statisztika archiválása")
    stat_to_archive = st.selectbox(
        "Archiválandó statisztika:", options=all_stat_names
    )
    if st.button("📦 Archiválás"):
      archive_db[stat_to_archive] = db["stats"][stat_to_archive]
      save_archive(archive_db)
      st.success("Archiválva!")

  with col_a2:
    st.markdown("#### Visszaállítás az archívumból")
    if archive_db:
      stat_to_restore = st.selectbox(
          "Visszaállítandó elem:", options=list(archive_db.keys())
      )
      if st.button("🔄 Visszaállítás"):
        db["stats"][stat_to_restore] = archive_db[stat_to_restore]
        save_data(db)
        st.success("Visszaállítva!")
        st.rerun()
    else:
      st.info("Az archívum üres.")

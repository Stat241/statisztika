import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
from datetime import datetime
import streamlit.components.v1 as components

# ================= OLDAL BEÁLLÍTÁSOK =================
st.set_page_config(page_title="Statisztika Kezelő Rendszer", layout="wide", page_icon="📊")

# ================= NYOMTATÁSI CSS =================
st.markdown("""
    <style>
    @media print {
        @page { size: A4 landscape; margin: 8mm; }
        [data-testid="stSidebar"], 
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        .stForm, 
        button, 
        iframe,
        .no-print {
            display: none !important;
        }
        /* Bal oldali adatbeviteli oszlop elrejtése nyomtatáskor */
        div[data-testid="stHorizontalBlock"] > div:first-child {
            display: none !important;
        }
        /* Jobb oldali grafikon oszlop teljes szélességűvé tétele nyomtatáskor */
        div[data-testid="stHorizontalBlock"] > div:last-child {
            width: 100% !important;
            flex: 1 1 100% !important;
            max-width: 100% !important;
        }
        .main .block-container {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 100% !important;
        }
        .js-plotly-plot, .plotly, .plot-container {
            width: 100% !important;
        }
        .js-plotly-plot .plotly .main-svg {
            shape-rendering: geometricPrecision !important;
            text-rendering: geometricPrecision !important;
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
        except Exception: pass
    if "admin" not in users:
        users["admin"] = {"password": "titkosjelszo2026", "allowed_stats": ["*"]}
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
        except Exception: pass
    return {"stats": {}, "settings": {}}

def save_data(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def load_archive():
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return {}

def save_archive(archive_data):
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)

# ================= SESSION STATE INICIALIZÁLÁS =================
if "users" not in st.session_state: st.session_state.users = load_users()
if "db" not in st.session_state: st.session_state.db = load_data()
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "current_user" not in st.session_state: st.session_state.current_user = None

USERS = st.session_state.users
db = st.session_state.db

# ================= BEJELENTKEZÉS =================
def check_login():
    st.markdown("<h2 style='text-align: center;'>🔐 Bejelentkezés a Rendszerbe</h2>", unsafe_allow_html=True)
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

# Jog

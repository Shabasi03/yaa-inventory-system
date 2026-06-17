import re
import os
import sys
import importlib
import streamlit as st
import pandas as pd
import base64
from collections import defaultdict
from datetime import datetime

# Force reload models and logic to prevent Streamlit Cloud caching issues
if "models" in sys.modules:
    try:
        importlib.reload(sys.modules["models"])
    except:
        pass
if "logic" in sys.modules:
    try:
        importlib.reload(sys.modules["logic"])
    except:
        pass

from database import init_db, get_session
from models import Product, Customer, Order, StockLedger, Expense, DebtSettlement, ActionLog, DeletedRecord
import logic


# ─── HELPER ──────────────────────────────────────────────────────────────────
def load_settings():
    import json
    apps_script_url = ""
    try:
        if "apps_script_url" in st.secrets:
            apps_script_url = st.secrets["apps_script_url"]
    except Exception:
        pass
        
    if os.path.exists("settings.json"):
        try:
            with open("settings.json", "r") as f:
                data = json.load(f)
                if data.get("apps_script_url"):
                    apps_script_url = data["apps_script_url"]
        except Exception:
            pass
    return {"apps_script_url": apps_script_url}

def save_settings(settings):
    import json
    try:
        with open("settings.json", "w") as f:
            json.dump(settings, f)
    except:
        pass

GSHEET_URL = "https://docs.google.com/spreadsheets/d/1goeE1w9QaDuTGXcj1EEClj14gPC_3xRL8wZIU9lFOlY/edit?usp=sharing"

import threading
import time

class BackgroundSyncManager:
    _lock = threading.Lock()
    _thread = None
    _pending_export = False
    _last_sync_time = 0.0
    _gsheet_url = "https://docs.google.com/spreadsheets/d/1goeE1w9QaDuTGXcj1EEClj14gPC_3xRL8wZIU9lFOlY/edit?usp=sharing"

    @classmethod
    def start_sync_thread(cls):
        with cls._lock:
            if cls._thread is None or not cls._thread.is_alive():
                cls._thread = threading.Thread(target=cls._run_sync_loop, daemon=True)
                cls._thread.start()

    @classmethod
    def queue_export(cls):
        cls._pending_export = True
        cls.start_sync_thread()

    @classmethod
    def _run_sync_loop(cls):
        cls._last_sync_time = time.time()
        while True:
            time.sleep(5)
            now = time.time()
            if now - cls._last_sync_time >= 300: # 5 minutes
                # 1. Check for sheet updates
                try:
                    with get_session() as session:
                        logic.check_google_sheet_updates(session, cls._gsheet_url)
                except Exception as e:
                    import logging
                    logging.error(f"Background check updates failed: {e}")
                
                # 2. Export local updates
                if cls._pending_export:
                    try:
                        cls.sync_now_blocking()
                    except Exception as e:
                        import logging
                        logging.error(f"Background sync export failed: {e}")
                
                cls._last_sync_time = time.time()

    @classmethod
    def sync_now_blocking(cls):
        sync_to_google_sheet_if_configured_blocking()
        cls._pending_export = False
        cls._last_sync_time = time.time()

def sync_to_google_sheet_if_configured():
    BackgroundSyncManager.queue_export()

BackgroundSyncManager.start_sync_thread()


def sync_to_google_sheet_if_configured_blocking():
    settings = load_settings()
    url = settings.get("apps_script_url", "")
    if url:
        with get_session() as session:
            if logic.export_to_google_sheet(session, url):
                try:
                    import urllib.request
                    import hashlib
                    import time
                    gsheet_url = "https://docs.google.com/spreadsheets/d/1goeE1w9QaDuTGXcj1EEClj14gPC_3xRL8wZIU9lFOlY/export?format=xlsx"
                    connector = "&" if "?" in gsheet_url else "?"
                    export_url = f"{gsheet_url}{connector}cachebust={int(time.time())}"
                    opener = urllib.request.build_opener()
                    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                    urllib.request.install_opener(opener)
                    data = urllib.request.urlopen(export_url).read()
                    current_hash = hashlib.md5(data).hexdigest()
                    with open("last_gsheet_hash.txt", "w") as f:
                        f.write(current_hash)
                except Exception:
                    pass


def _format_ledger_reason(reason: str) -> str:
    if not reason:
        return "—"
    r = reason.strip()
    m = re.match(r'Order Fulfillment.*Order #(\d+)', r)
    if m:
        return f"🛒 Sale dispatched — Order #{m.group(1)}"
    if "Initial Stock" in r:
        return "📦 Initial stock entry on product registration"
    if r.lower().startswith("restock"):
        return "📥 Restock shipment received"
    if "Revert" in r or "revert" in r:
        return f"↩️ Stock reversal — {r}"
    return r

def style_zebra(df):
    if df.empty:
        return df
    def get_row_styles(row):
        bg = 'background-color: #f8fafc' if row.name % 2 == 0 else 'background-color: #f1f5f9'
        return [bg] * len(row)
    
    header_styles = [
        {'selector': 'th', 'props': [
            ('background-color', '#1e2e3d'),
            ('color', '#9dd2f2'),
            ('font-weight', '700'),
            ('border', '1px solid #2d3e50')
        ]}
    ]
    return df.style.apply(get_row_styles, axis=1).set_table_styles(header_styles)

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Yaa-يَــــــــاء Core - Inventory Control",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_db()

# ─── USER AUTHENTICATION GATE ────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    # Center login UI
    st.markdown("""
    <style>
    .block-container {
        max-width: 480px !important;
        margin: auto !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
        min-height: 85vh !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    #MainMenu, header, footer { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)
    
    with st.container():
        if os.path.exists("yaa_logo.jpg"):
            with open("yaa_logo.jpg", "rb") as f:
                logo_b64 = base64.b64encode(f.read()).decode()
            st.markdown(f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <img src="data:image/jpeg;base64,{logo_b64}" style="width: 110px; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.12);" />
            </div>
            """, unsafe_allow_html=True)
        st.markdown("""
        <h2 style="text-align: center; color: #0f172a; margin-top: 15px; margin-bottom: 5px; font-weight: 700;">Yaa-يَــــــــاء <span style="color: #fa7f2a;">Core</span></h2>
        <p style="text-align: center; color: #64748b; font-size: 0.88rem; margin-top: 0; margin-bottom: 25px;">Yaa Inventory &amp; Orders Management System</p>
        """, unsafe_allow_html=True)
        
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", value="Admin")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("🔓 Authenticate & Enter", type="primary", width='stretch')
            if submitted:
                if (username == "Admin" and password in ["Yaa2813", "Yaa3728"]) or (username == "User" and password == "User2026"):
                    st.session_state["logged_in"] = True
                    st.session_state["user_role"] = username
                    import time
                    st.session_state["last_activity_time"] = time.time()
                    st.success("Login Successful!")
                    time.sleep(0.6)
                    st.rerun()
                else:
                    st.error("Invalid credentials. Access Denied.")
    st.stop()

# ─── SESSION IDLE TIMEOUT CHECK ──────────────────────────────────────────────
import time
current_time = time.time()
if st.session_state.get("logged_in") and st.session_state.get("user_role") == "Admin":
    if "last_activity_time" in st.session_state:
        elapsed = current_time - st.session_state["last_activity_time"]
        if elapsed > 120:  # 2 minutes idle
            st.session_state["user_role"] = "User"
            st.session_state["session_downgraded"] = True
    st.session_state["last_activity_time"] = current_time

# ─── AUTO SYNC REFRESH FOR OTHER USERS ───────────────────────────────────────
db_file = "inventory.db"
if os.path.exists(db_file):
    db_mtime = os.path.getmtime(db_file)
    if "last_db_mtime" not in st.session_state:
        st.session_state["last_db_mtime"] = db_mtime
    elif db_mtime != st.session_state["last_db_mtime"]:
        st.session_state["last_db_mtime"] = db_mtime
        st.cache_data.clear()
        st.rerun()

# ─── SEED DATA REMOVED (Source of truth is Google Sheets) ───

# ─── GLOBAL BACKGROUND LOGIC ──────────────────────────────────────────────────
bg_logo_base64 = ""
if os.path.exists("yaa_logo.jpg"):
    with open("yaa_logo.jpg", "rb") as f:
        bg_logo_base64 = base64.b64encode(f.read()).decode()

# ─── GLOBAL CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown { font-family: 'Outfit', sans-serif; }

/* ── Always show the default Streamlit header (containing the Deploy button) transparently ── */
header[data-testid="stHeader"], header {
    background-color: transparent !important;
    position: absolute !important;
    top: 0;
    left: 0;
    right: 0;
    height: 48px !important;
    opacity: 1 !important;
    visibility: visible !important;
    z-index: 1000 !important;
}

#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 60px !important; }

/* ── Background Logo with 90% Overlay and Cover Fit ── */
[data-testid="stAppViewContainer"] {
    background-image: linear-gradient(rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.9)), url("data:image/jpeg;base64,__BG_LOGO_BASE64__");
    background-size: cover;
    background-repeat: no-repeat;
    background-position: center;
    background-attachment: fixed;
}

/* ── Fluid Animations ── */
@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(16px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.kpi-card, .section-header, [data-testid="stForm"], .element-container, [data-testid="stMarkdownContainer"] {
    animation: fadeInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* ── Premium Tab overrides (Modern Pill Nav) ── */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(15, 23, 42, 0.95) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    border-radius: 16px !important;
    padding: 8px 12px !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    gap: 8px !important;
    box-shadow: 0 10px 30px rgba(0,0,0,0.15) !important;
    margin-bottom: 24px !important;
}
.stTabs [data-baseweb="tab"] {
    color: #94a3b8 !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    padding: 10px 22px !important;
    border-radius: 10px !important;
    border: none !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #fff !important;
    background: rgba(255, 255, 255, 0.08) !important;
}
.stTabs [aria-selected="true"] {
    color: #fff !important;
    background: #fa7f2a !important;
    box-shadow: 0 4px 14px rgba(250, 127, 42, 0.35) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"]    { display: none !important; }

/* ── Glassmorphism KPI cards ── */
.kpi-card {
    background: rgba(255, 255, 255, 0.75);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.45);
    border-radius: 20px;
    padding: 24px;
    box-shadow: 0 8px 32px 0 rgba(250, 127, 42, 0.02);
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
    border-left: 6px solid #fa7f2a;
    border-top: none;
}
.kpi-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 16px 40px 0 rgba(250, 127, 42, 0.06);
    border-left-width: 10px;
    background: rgba(255, 255, 255, 0.85);
}
.kpi-title { font-size: 0.8rem; color: #64748b; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
.kpi-value { font-size: 1.9rem; font-weight: 800; color: #0f172a; margin-top: 6px; }
.kpi-revenue { border-left-color: #fa7f2a; }
.kpi-profit  { border-left-color: #83b2c2; }
.kpi-orders  { border-left-color: #1e2a38; }
.kpi-expenses { border-left-color: #b91c1c; }
.kpi-netprofit { border-left-color: #10b981; }

/* ── Interactive Premium Buttons ── */
div.stButton > button:first-child {
    border-radius: 12px !important;
    font-weight: 600 !important;
    padding: 8px 20px !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
div.stButton > button[kind="primary"]:first-child {
    background: linear-gradient(135deg, #fa7f2a 0%, #d86214 100%) !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(250, 127, 42, 0.3) !important;
    color: white !important;
}
div.stButton > button[kind="primary"]:first-child:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(250, 127, 42, 0.45) !important;
}
div.stButton > button[kind="secondary"]:first-child {
    background: rgba(255, 255, 255, 0.75) !important;
    backdrop-filter: blur(8px) !important;
    border: 1px solid #e2e8f0 !important;
    color: #1e293b !important;
}
div.stButton > button[kind="secondary"]:first-child:hover {
    background: rgba(248, 250, 252, 0.9) !important;
    border-color: #cbd5e1 !important;
    transform: translateY(-2px) !important;
}

/* ── Styled Input Fields ── */
div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input, div[data-testid="stSelectbox"] select {
    border-radius: 12px !important;
    border: 1px solid #cbd5e1 !important;
    background-color: rgba(255, 255, 255, 0.85) !important;
    transition: all 0.2s ease !important;
}
div[data-testid="stTextInput"] input:focus, div[data-testid="stNumberInput"] input:focus {
    border-color: #fa7f2a !important;
    box-shadow: 0 0 0 3px rgba(250, 127, 42, 0.15) !important;
}

/* ── Glassmorphism Alert box ── */
.alert-box {
    background: rgba(254, 226, 226, 0.75);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(254, 205, 205, 0.5);
    border-radius: 16px;
    padding: 20px 24px;
    border-left: 6px solid #ef4444;
    color: #991b1b;
    margin-bottom: 24px;
    box-shadow: 0 6px 20px rgba(220, 38, 38, 0.03);
}
.alert-box h4 { margin: 0 0 6px; color: #7f1d1d; font-weight: 700; }

/* ── Section header ── */
.section-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    border: 1px solid rgba(255, 255, 255, 0.05);
    padding: 24px 28px;
    border-radius: 18px;
    color: white;
    margin-bottom: 28px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
    border-left: 6px solid #fa7f2a;
}
.section-header h2 { margin: 0; font-size: 1.55rem; font-weight: 800;
    background: linear-gradient(to right, #fff, #fad5be);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.section-header p  { margin: 6px 0 0; opacity: 0.75; font-size: 0.9rem; }

/* ── Dialog tweaks ── */
[data-testid="stDialog"] div[role="dialog"] {
    border-radius: 20px !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    box-shadow: 0 25px 60px rgba(0,0,0,0.25) !important;
    background: rgba(255, 255, 255, 0.95) !important;
    backdrop-filter: blur(20px) !important;
    animation: fadeInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
""".replace("__BG_LOGO_BASE64__", bg_logo_base64), unsafe_allow_html=True)

# ─── TOP HEADER (Flexbox Branding Header) ───────────────────────────────────
logo_base64 = ""
if os.path.exists("yaa_logo.jpg"):
    with open("yaa_logo.jpg", "rb") as f:
        logo_base64 = base64.b64encode(f.read()).decode()

st.markdown(f"""
<div style="display: flex; align-items: center; gap: 18px; margin-bottom: 24px;">
    <img src="data:image/jpeg;base64,{logo_base64}" style="width: 58px; height: 58px; border-radius: 14px; box-shadow: 0 8px 20px rgba(0,0,0,0.12);" />
    <div>
        <h1 style="font-size: 2rem; font-weight: 800; color: #0f172a; margin: 0; line-height: 1.1; letter-spacing: -0.025em;">
            Yaa-يَــــــــاء <span style="color: #fa7f2a;">Core</span>
        </h1>
        <p style="color: #64748b; font-size: 0.9rem; margin: 0; padding-top: 2px; font-weight: 600; letter-spacing: 0.01em;">Inventory &amp; Financial Control Hub</p>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("<hr style='margin: 8px 0 16px 0; border: 0; border-top: 1px solid #e2e8f0;' />", unsafe_allow_html=True)

if st.session_state.get("session_downgraded"):
    st.warning("⚠️ Session was idle for more than 2 minutes. Admin privileges downgraded to normal User (Add Only).")
    if st.button("Dismiss & Acknowledge"):
        st.session_state["session_downgraded"] = False
        st.rerun()


# ─── GOOGLE SHEET AUTO-SYNC LOGIC ────────────────────────────────────────────

if "last_sync" not in st.session_state:
    st.session_state["last_sync"] = None

def perform_sync():
    with get_session() as session:
        try:
            logic.sync_google_sheet(session, GSHEET_URL)
            session.commit()
            try:
                sync_to_google_sheet_if_configured()
            except Exception:
                pass
            st.session_state["last_sync"] = datetime.now()
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"Sync failed: {e}")
            return False

# Startup sync: check for sheet updates on startup to pull any extra lines/external edits
if "initial_sync_done" not in st.session_state:
    st.session_state["initial_sync_done"] = True
    with st.spinner("🔄 Synchronizing database with Google Sheet on startup..."):
        with get_session() as session:
            try:
                is_db_empty = (session.query(Product).count() == 0)
                if is_db_empty:
                    # Force full download/sync
                    logic.sync_google_sheet(session, GSHEET_URL)
                    # Update local hash file so subsequent checks work correctly
                    try:
                        import urllib.request, hashlib, time
                        export_url = GSHEET_URL.split("/edit")[0] + "/export?format=xlsx"
                        connector = "&" if "?" in export_url else "?"
                        export_url = f"{export_url}{connector}cachebust={int(time.time())}"
                        opener = urllib.request.build_opener()
                        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                        urllib.request.install_opener(opener)
                        data = urllib.request.urlopen(export_url).read()
                        current_hash = hashlib.md5(data).hexdigest()
                        with open("last_gsheet_hash.txt", "w") as f:
                            f.write(current_hash)
                    except Exception:
                        pass
                else:
                    # Database has data, check if Google Sheet has new external changes (extra lines)
                    logic.check_google_sheet_updates(session, GSHEET_URL)
                session.commit()
                st.session_state["last_sync"] = datetime.now()
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Startup sync failed: {e}")


# Network checks are deferred entirely to the background thread to prevent UI lag.

# Hidden refresh trigger button and JS for 10 seconds auto-check
col_hidden = st.columns([1])[0]
with col_hidden:
    st.markdown("<div style='display:none;'>", unsafe_allow_html=True)
    if st.button("refresh_trigger_btn"):
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("""
<script>
    if (!window.parent.__refresh_interval_set__) {
        window.parent.__refresh_interval_set__ = true;
        setInterval(function() {
            var buttons = window.parent.document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].textContent.trim() === "refresh_trigger_btn") {
                    buttons[i].click();
                    break;
                }
            }
        }, 10000);
    }
</script>
""", unsafe_allow_html=True)

# Thin status bar and sync button right above navigation
col_status, col_btn = st.columns([5, 1])
with col_status:
    if st.session_state["last_sync"]:
        sync_time_str = st.session_state["last_sync"].strftime("%I:%M:%S %p")
        st.markdown(f"<p style='color:#64748b;font-size:0.85rem;margin-top:8px;'>🌐 Google Sheet auto-updated. Last sync: <b>{sync_time_str}</b></p>", unsafe_allow_html=True)
    else:
        st.markdown("<p style='color:#64748b;font-size:0.85rem;margin-top:8px;'>🌐 Not synced with Google Sheet yet.</p>", unsafe_allow_html=True)
with col_btn:
    if st.button("🔄 Sync Now", width='stretch'):
        with st.spinner("Syncing..."):
            if perform_sync():
                st.success("Synced!")
                time.sleep(1)
                st.rerun()

# Initialize edit flags and key version counters in session state
if "edit_sku" not in st.session_state:
    st.session_state["edit_sku"] = None
if "edit_cust_id" not in st.session_state:
    st.session_state["edit_cust_id"] = None
if "edit_order_id" not in st.session_state:
    st.session_state["edit_order_id"] = None
if "edit_expense_id" not in st.session_state:
    st.session_state["edit_expense_id"] = None

if "prod_df_ver" not in st.session_state:
    st.session_state["prod_df_ver"] = 0
if "cust_df_ver" not in st.session_state:
    st.session_state["cust_df_ver"] = 0
if "order_df_ver" not in st.session_state:
    st.session_state["order_df_ver"] = 0
if "exp_df_ver" not in st.session_state:
    st.session_state["exp_df_ver"] = 0

# ─── DIALOG: Edit Product ─────────────────────────────────────────────────────
@st.dialog("✏️ Edit Product", width="large")
def dialog_edit_product(sku):
    is_admin = (st.session_state.get("user_role") == "Admin")
    with get_session() as session:
        product = session.query(Product).filter(Product.sku == sku).first()
        if not product:
            st.error("Product not found.")
            if st.button("Close"):
                st.session_state["edit_sku"] = None
                st.rerun()
            return
        with st.form("edit_prod_form"):
            item_name = st.text_input("Item Name (English) *", value=product.item_name, disabled=not is_admin)
            item_name_arabic = st.text_input("Item Name (Arabic)", value=product.item_name_arabic or "", disabled=not is_admin)
            initial_quantity = st.number_input("Stock Quantity", min_value=0, value=product.initial_quantity, step=1, disabled=not is_admin)
            buying_price = st.number_input("Buying Price (EGP)", min_value=0.0, value=product.buying_price, step=10.0, disabled=not is_admin)
            selling_price = st.number_input("Selling Price (EGP)", min_value=0.0, value=product.selling_price, step=10.0, disabled=not is_admin)
            supplier = st.text_input("Supplier", value=product.supplier or "", disabled=not is_admin)
            
            c1, c2, c3 = st.columns(3)
            if is_admin:
                with c1:
                    submitted = st.form_submit_button("💾 Save Changes", type="primary")
                with c2:
                    deleted = st.form_submit_button("🗑️ Delete Product")
                with c3:
                    cancelled = st.form_submit_button("Cancel")
            else:
                st.warning("⚠️ View-only: Logging in as Admin is required to modify or delete.")
                submitted = False
                deleted = False
                with c1:
                    cancelled = st.form_submit_button("Close / Dismiss")
                
            if submitted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Edit Product", f"SKU: {sku}, Name: {item_name}, Qty: {initial_quantity}")
                product.item_name = item_name
                product.item_name_arabic = item_name_arabic
                product.initial_quantity = initial_quantity
                product.buying_price = buying_price
                product.selling_price = selling_price
                product.supplier = supplier
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_sku"] = None
                st.session_state["prod_df_ver"] += 1
                st.success("Product updated!")
                st.rerun()
            elif deleted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Delete Product", f"SKU: {sku}, Name: {product.item_name}")
                # Clear dependencies
                session.query(StockLedger).filter(StockLedger.sku == sku).delete()
                session.query(Order).filter(Order.sku == sku).delete()
                session.delete(product)
                session.add(DeletedRecord(entity_type="Product", entity_key=sku))
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_sku"] = None
                st.session_state["prod_df_ver"] += 1
                st.success("Product deleted!")
                st.rerun()
            elif cancelled:
                st.session_state["edit_sku"] = None
                st.session_state["prod_df_ver"] += 1
                st.rerun()

# ─── DIALOG: Edit Customer ────────────────────────────────────────────────────
@st.dialog("✏️ Edit Customer", width="large")
def dialog_edit_customer(cust_id):
    is_admin = (st.session_state.get("user_role") == "Admin")
    with get_session() as session:
        customer = session.query(Customer).filter(Customer.customer_id == cust_id).first()
        if not customer:
            st.error("Customer not found.")
            if st.button("Close"):
                st.session_state["edit_cust_id"] = None
                st.rerun()
            return
        with st.form("edit_cust_form"):
            customer_name = st.text_input("Customer Full Name *", value=customer.customer_name, disabled=not is_admin)
            phone = st.text_input("Phone Number * (Unique)", value=customer.customer_phone_number, disabled=not is_admin)
            address = st.text_input("Billing Address", value=customer.customer_address or "", disabled=not is_admin)
            
            c1, c2, c3 = st.columns(3)
            if is_admin:
                with c1:
                    submitted = st.form_submit_button("💾 Save Changes", type="primary")
                with c2:
                    deleted = st.form_submit_button("🗑️ Delete Customer")
                with c3:
                    cancelled = st.form_submit_button("Cancel")
            else:
                st.warning("⚠️ View-only: Logging in as Admin is required to modify or delete.")
                submitted = False
                deleted = False
                with c1:
                    cancelled = st.form_submit_button("Close / Dismiss")
                
            if submitted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Edit Customer", f"ID: {cust_id}, Name: {customer_name}, Phone: {phone}")
                customer.customer_name = customer_name
                customer.customer_phone_number = phone
                customer.customer_address = address
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_cust_id"] = None
                st.session_state["cust_df_ver"] += 1
                st.success("Customer updated!")
                st.rerun()
            elif deleted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Delete Customer", f"ID: {cust_id}, Name: {customer.customer_name}")
                # Clear dependencies
                session.query(Order).filter(Order.customer_id == cust_id).delete()
                session.delete(customer)
                session.add(DeletedRecord(entity_type="Customer", entity_key=str(cust_id)))
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_cust_id"] = None
                st.session_state["cust_df_ver"] += 1
                st.success("Customer deleted!")
                st.rerun()
            elif cancelled:
                st.session_state["edit_cust_id"] = None
                st.session_state["cust_df_ver"] += 1
                st.rerun()

# ─── DIALOG: Edit Order ───────────────────────────────────────────────────────
@st.dialog("✏️ Edit Order", width="large")
def dialog_edit_order(order_id):
    is_admin = (st.session_state.get("user_role") == "Admin")
    with get_session() as session:
        orders = session.query(Order).filter(Order.order_id == order_id).all()
        if not orders:
            st.error("Order not found.")
            if st.button("Close"):
                st.session_state["edit_order_id"] = None
                st.rerun()
            return
        first_order = orders[0]
        
        status_options = ["Pending","Confirmed","Dispatched","Delivered"]
        status_idx = 0
        if first_order.order_status in status_options:
            status_idx = status_options.index(first_order.order_status)
            
        pay_options = ["Pending","Paid","Failed"]
        pay_idx = 0
        if first_order.payment_status in pay_options:
            pay_idx = pay_options.index(first_order.payment_status)

        with st.form("edit_ord_form"):
            order_status = st.selectbox("Fulfillment Status", status_options,
                                        index=status_idx,
                                        disabled=not is_admin)
            payment_status = st.selectbox("Payment Status", pay_options,
                                         index=pay_idx,
                                         disabled=not is_admin)
            
            c1, c2, c3 = st.columns(3)
            if is_admin:
                with c1:
                    submitted = st.form_submit_button("💾 Save Changes", type="primary")
                with c2:
                    deleted = st.form_submit_button("🗑️ Delete Order")
                with c3:
                    cancelled = st.form_submit_button("Cancel")
            else:
                st.warning("⚠️ View-only: Logging in as Admin is required to modify or delete.")
                submitted = False
                deleted = False
                with c1:
                    cancelled = st.form_submit_button("Close / Dismiss")
                
            if submitted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Edit Order", f"Order #{order_id}: Status={order_status}, Payment={payment_status}")
                logic.update_order_status(session, order_id, order_status)
                logic.update_payment_status(session, order_id, payment_status)
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_order_id"] = None
                st.session_state["order_df_ver"] += 1
                st.success("Order updated!")
                st.rerun()
            elif deleted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Delete Order", f"Order #{order_id} deleted")
                for o in orders:
                    if o.order_status == 'Delivered':
                        logic._revert_stock_deduction_for_order(session, o)
                    session.delete(o)
                session.add(DeletedRecord(entity_type="Order", entity_key=str(order_id)))
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_order_id"] = None
                st.session_state["order_df_ver"] += 1
                st.success("Order deleted!")
                st.rerun()
            elif cancelled:
                st.session_state["edit_order_id"] = None
                st.session_state["order_df_ver"] += 1
                st.rerun()

# ─── DIALOG: Edit Expense ─────────────────────────────────────────────────────
@st.dialog("✏️ Edit Expense", width="large")
def dialog_edit_expense(expense_id):
    is_admin = (st.session_state.get("user_role") == "Admin")
    with get_session() as session:
        expense = session.query(Expense).filter(Expense.expense_id == expense_id).first()
        if not expense:
            st.error("Expense not found.")
            if st.button("Close"):
                st.session_state["edit_expense_id"] = None
                st.rerun()
            return
        with st.form("edit_exp_form"):
            item = st.text_input("Expense Item *", value=expense.item, disabled=not is_admin)
            amount = st.number_input("Amount (EGP) *", min_value=0.0, value=expense.amount, step=10.0, disabled=not is_admin)
            wallet_options = ["شباسي", "حجازي"]
            default_index = 0
            if expense.wallet in wallet_options:
                default_index = wallet_options.index(expense.wallet)
            wallet = st.selectbox("Wallet / Account", options=wallet_options, index=default_index, disabled=not is_admin)
            day = st.date_input("Date", value=expense.day or datetime.today(), disabled=not is_admin)
            
            c1, c2, c3 = st.columns(3)
            if is_admin:
                with c1:
                    submitted = st.form_submit_button("💾 Save Changes", type="primary")
                with c2:
                    deleted = st.form_submit_button("🗑️ Delete Expense")
                with c3:
                    cancelled = st.form_submit_button("Cancel")
            else:
                st.warning("⚠️ View-only: Logging in as Admin is required to modify or delete.")
                submitted = False
                deleted = False
                with c1:
                    cancelled = st.form_submit_button("Close / Dismiss")
                
            if submitted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Edit Expense", f"ID: {expense_id}, Item: {item}, Amount: {amount}, Wallet: {wallet}")
                expense.item = item
                expense.amount = amount
                expense.wallet = wallet
                expense.day = datetime.combine(day, datetime.min.time())
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_expense_id"] = None
                st.session_state["exp_df_ver"] += 1
                st.success("Expense updated!")
                st.rerun()
            elif deleted:
                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Delete Expense", f"ID: {expense_id}, Item: {expense.item}, Amount: {expense.amount}")
                day_str = expense.day.strftime("%Y-%m-%d") if expense.day else ""
                key_str = f"{day_str}|{expense.item}|{expense.wallet or ''}|{expense.amount}"
                session.delete(expense)
                session.add(DeletedRecord(entity_type="Expense", entity_key=key_str))
                session.commit()
                try:
                    sync_to_google_sheet_if_configured()
                except Exception:
                    pass
                st.session_state["edit_expense_id"] = None
                st.session_state["exp_df_ver"] += 1
                st.success("Expense deleted!")
                st.rerun()
            elif cancelled:
                st.session_state["edit_expense_id"] = None
                st.session_state["exp_df_ver"] += 1
                st.rerun()

# Trigger edit modals if active
if st.session_state["edit_sku"]:
    dialog_edit_product(st.session_state["edit_sku"])
if st.session_state["edit_cust_id"]:
    dialog_edit_customer(st.session_state["edit_cust_id"])
if st.session_state["edit_order_id"]:
    dialog_edit_order(st.session_state["edit_order_id"])
if st.session_state["edit_expense_id"]:
    dialog_edit_expense(st.session_state["edit_expense_id"])

tabs_list = [
    "📊  Dashboard",
    "📦  Products Catalog",
    "👥  Customers Directory",
    "🛒  Orders & Fulfillment",
    "💸  Expenses Tracker",
]
is_admin_user = (st.session_state.get("user_role") == "Admin")
if is_admin_user:
    tabs_list.append("🕵️ Audit Logs")
tabs_list.append("⚙️ Settings")

tabs = st.tabs(tabs_list)

if is_admin_user:
    tab_dashboard, tab_products, tab_customers, tab_orders, tab_expenses, tab_logs, tab_settings = tabs
else:
    tab_dashboard, tab_products, tab_customers, tab_orders, tab_expenses, tab_settings = tabs



# ─── SIDEBAR (Excel import only) ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📥 Import Data from Excel")
    uploaded_file = st.file_uploader("Upload Yaa.xlsx workbook", type=["xlsx"])
    if uploaded_file is not None:
        clear_db_checked = st.checkbox("Clear existing database before importing", value=True)
        is_admin = (st.session_state.get("user_role") == "Admin")
        if not is_admin:
            st.warning("⚠️ Only Admins can import Excel data.")
        else:
            if st.button("Import Excel Data", type="primary"):
                temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_data.xlsx")
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                with get_session() as session:
                    try:
                        logic.import_excel_data(session, temp_path, clear_db=clear_db_checked)
                        session.commit()
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success("Excel data imported successfully!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to import Excel: {e}")
    st.markdown("---")
    st.markdown("### 🔗 Google Sheet Sync Settings")
    settings = load_settings()
    apps_script_url = st.text_input("Apps Script Web App URL", value=settings.get("apps_script_url", ""), placeholder="https://script.google.com/.../exec")
    if apps_script_url != settings.get("apps_script_url", ""):
        settings["apps_script_url"] = apps_script_url
        save_settings(settings)
        st.success("Web App URL saved!")
        st.rerun()

    with st.expander("ℹ️ How to set up writing to Google Sheet"):
        st.markdown("""
        To sync changes from the app back to the Google Sheet:
        1. Open your Google Sheet.
        2. Go to **Extensions** -> **Apps Script**.
        3. Clear any default code, and paste the code below.
        4. Click **Save** (disk icon).
        5. Click **Deploy** -> **New deployment**.
        6. Select type: **Web app**.
        7. Set:
           - *Execute as*: `Me` (your account)
           - *Who has access*: `Anyone`
        8. Click **Deploy**, authorize permissions, and copy the **Web App URL**.
        9. Paste the URL in the box above!
        
        **🔒 Persistent Deployment (Streamlit Secrets)**:
        Since Streamlit Community Cloud resets its container filesystem periodically (wiping local settings files), you must add this URL to your App Secrets to keep it permanently:
        1. Go to your **Streamlit Cloud Dashboard**.
        2. Click **Settings** next to your app -> **Secrets**.
        3. Paste the following line:
           ```toml
           apps_script_url = "PASTE_YOUR_WEB_APP_URL_HERE"
           ```
        4. Click **Save**.
        """)
        
        apps_script_code = """function doGet(e) {
  return HtmlService.createHtmlOutput("<h1>YAA Inventory Webhook Active</h1><p>This Apps Script Web App is working and ready to receive updates from your Streamlit inventory system via POST requests.</p>");
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    for (var sheetName in data) {
      var sheet = spreadsheet.getSheetByName(sheetName);
      if (!sheet) { sheet = spreadsheet.insertSheet(sheetName); }
      else { sheet.clear(); }
      var rows = data[sheetName];
      if (rows && rows.length > 0) {
        var headers = Object.keys(rows[0]);
        sheet.appendRow(headers);
        var values = rows.map(function(row) {
          return headers.map(function(h) { return row[h] !== null ? row[h] : ""; });
        });
        sheet.getRange(2, 1, values.length, headers.length).setValues(values);
      }
    }
    return ContentService.createTextOutput(JSON.stringify({status: "success"})).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: err.toString()})).setMimeType(ContentService.MimeType.JSON);
  }
}"""
        st.code(apps_script_code, language="javascript")


    st.markdown("---")
    st.info("Connected to local SQLite database: `inventory.db`")


# ─── DIALOG: Add New Product ──────────────────────────────────────────────────
@st.dialog("📦 Add New Product", width="large")
def dialog_add_product():
    with get_session() as session:
        import datetime
        now = datetime.datetime.now()
        yy = str(now.year)[-2:]
        m = str(now.month)
        prefix = f"Y{yy}{m}"
        
        products = session.query(Product).all()
        max_counter = 0
        for p in products:
            if p.sku and p.sku.startswith(prefix):
                suffix = p.sku[len(prefix):]
                if suffix.isdigit():
                    val = int(suffix)
                    if val > max_counter:
                        max_counter = val
        next_counter = max_counter + 1
        auto_sku = f"{prefix}{next_counter:02d}"

    with st.form("dlg_new_product_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            sku = st.text_input("SKU Code *", value=auto_sku, help="Auto-generated using pattern Y-YY-M-DD").strip()
            item_name = st.text_input("Item Name (English) *", placeholder="iPhone 15 Pro")
            initial_quantity = st.number_input("Initial Quantity", min_value=0, value=10, step=1)
            supplier = st.text_input("Supplier Company", placeholder="Apple Distribution")
        with c2:
            item_name_arabic = st.text_input("Item Name (Arabic)", placeholder="آيفون ١٥ برو")
            buying_price  = st.number_input("Buying Price (EGP)",  min_value=0.0, value=500.0, step=10.0)
            selling_price = st.number_input("Selling Price (EGP)", min_value=0.0, value=750.0, step=10.0)

        submitted = st.form_submit_button("✅ Register Product", type="primary", width='stretch')
        if submitted:
            if not sku or not item_name:
                st.error("SKU and English Item Name are required!")
            else:
                with get_session() as session:
                    try:
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Add Product", f"SKU: {sku}, Name: {item_name}, Qty: {initial_quantity}")
                        logic.add_product(session, sku, item_name, item_name_arabic,
                                          initial_quantity, buying_price, selling_price, supplier)
                        session.commit()
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success(f"Product '{item_name}' added successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


# ─── DIALOG: Batch Insert Products ────────────────────────────────────────────
@st.dialog("📥 Batch Insert Products", width="large")
def dialog_batch_insert_products():
    import io
    st.write("Register multiple products at once. Choose a paste method or upload a file.")
    
    with st.expander("ℹ️ Column Names & Guidelines"):
        st.write("""
        **Required Columns:**
        - `SKU`: Unique product identifier (e.g. Y26611)
        - `Item Name`: English name of the product
        
        **Optional Columns:**
        - `Item Name Arabic` / `Arabic Name`
        - `Initial Quantity` / `Qty` / `Stock` (defaults to 0)
        - `Buying Price` (defaults to 0.0)
        - `Selling Price` (defaults to 0.0)
        - `Supplier`
        """)
        
    t1, t2 = st.tabs(["📋 Paste Data", "📤 Upload CSV/Excel"])
    df = None
    
    with t1:
        pasted_text = st.text_area("Paste tab-separated or comma-separated rows here (including header row):", height=200, placeholder="SKU\tItem Name\tInitial Quantity\tBuying Price\tSelling Price\nY26611\tTest Product\t10\t100\t150")
        if pasted_text.strip():
            try:
                df = pd.read_csv(io.StringIO(pasted_text.strip()), sep=None, engine='python')
            except Exception as e:
                st.error(f"Failed to parse text: {e}")
                
    with t2:
        uploaded_file = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx"], key="prod_batch_uploader")
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
            except Exception as e:
                st.error(f"Failed to read file: {e}")
                
    if df is not None:
        st.subheader("Preview Data")
        
        col_mappings = {
            'sku': ['sku', 'SKU', 'Sku', 'SKU Code', 'SKU ID'],
            'item_name': ['item_name', 'Item Name', 'Item Name (English)', 'Name', 'English Name', 'Name (English)'],
            'item_name_arabic': ['item_name_arabic', 'Item Name (Arabic)', 'Arabic Name', 'Name (Arabic)', 'Arabic'],
            'initial_quantity': ['initial_quantity', 'Initial Quantity', 'Qty', 'Quantity', 'Stock', 'Quantity Change'],
            'buying_price': ['buying_price', 'Buying Price', 'Buying', 'Buying (EGP)'],
            'selling_price': ['selling_price', 'Selling Price', 'Selling', 'Selling (EGP)'],
            'supplier': ['supplier', 'Supplier', 'Supplier Company']
        }
        
        mapped_df = pd.DataFrame()
        raw_cols = df.columns.tolist()
        
        for canonical, options in col_mappings.items():
            found = False
            for opt in options:
                for c in raw_cols:
                    if c.strip().lower() == opt.strip().lower():
                        mapped_df[canonical] = df[c]
                        found = True
                        break
                if found:
                    break
            if not found:
                if canonical == 'initial_quantity':
                    mapped_df[canonical] = 0
                elif canonical in ['buying_price', 'selling_price']:
                    mapped_df[canonical] = 0.0
                else:
                    mapped_df[canonical] = ""
                    
        missing = []
        if 'sku' not in mapped_df.columns or mapped_df['sku'].astype(str).str.strip().eq("").all():
            missing.append("SKU")
        if 'item_name' not in mapped_df.columns or mapped_df['item_name'].astype(str).str.strip().eq("").all():
            missing.append("Item Name")
            
        if missing:
            st.error(f"Could not map required columns: {', '.join(missing)}. Please check headers.")
        else:
            mapped_df['sku'] = mapped_df['sku'].astype(str).str.strip()
            mapped_df['item_name'] = mapped_df['item_name'].astype(str).str.strip()
            mapped_df['item_name_arabic'] = mapped_df['item_name_arabic'].fillna("").astype(str).str.strip()
            
            def local_safe_int(v):
                if pd.isna(v) or str(v).strip() == "": return 0
                try: return int(float(v))
                except: return 0
                
            def local_safe_float(v):
                if pd.isna(v) or str(v).strip() == "": return 0.0
                try: return float(v)
                except: return 0.0
                
            mapped_df['initial_quantity'] = mapped_df['initial_quantity'].apply(local_safe_int)
            mapped_df['buying_price'] = mapped_df['buying_price'].apply(local_safe_float)
            mapped_df['selling_price'] = mapped_df['selling_price'].apply(local_safe_float)
            mapped_df['supplier'] = mapped_df['supplier'].fillna("").astype(str).str.strip()
            
            st.dataframe(mapped_df, width='stretch', hide_index=True)
            
            if st.button("🚀 Confirm & Insert Products", type="primary", width='stretch'):
                with get_session() as session:
                    success_count = 0
                    skipped_count = 0
                    errors = []
                    
                    for _, row in mapped_df.iterrows():
                        sku_val = row['sku']
                        if not sku_val or sku_val == "nan":
                            continue
                        
                        exist = session.query(Product).filter(Product.sku == sku_val).first()
                        if exist:
                            skipped_count += 1
                            continue
                            
                        try:
                            logic.add_product(
                                session=session,
                                sku=sku_val,
                                item_name=row['item_name'],
                                item_name_arabic=row['item_name_arabic'],
                                initial_quantity=row['initial_quantity'],
                                buying_price=row['buying_price'],
                                selling_price=row['selling_price'],
                                supplier=row['supplier']
                            )
                            success_count += 1
                        except Exception as row_err:
                            errors.append(f"SKU {sku_val}: {row_err}")
                            
                    if success_count > 0:
                        session.commit()
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Batch Add Products", f"Added {success_count} products, skipped {skipped_count} duplicates")
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success(f"Successfully added {success_count} products! (Skipped {skipped_count} existing duplicates)")
                        if errors:
                            st.warning("Some errors occurred:\n" + "\n".join(errors))
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.warning(f"No products added. (Skipped {skipped_count} existing duplicates)")
                        if errors:
                            st.error("\n".join(errors))


# ─── DIALOG: Restock Product ──────────────────────────────────────────────────
@st.dialog("📥 Restock Existing Product", width="large")
def dialog_restock():
    with get_session() as session:
        all_prods = session.query(Product).all()
        product_options = {p.sku: f"{p.sku} — {p.item_name} (Stock: {p.initial_quantity})" for p in all_prods}

    if not product_options:
        st.warning("No products found. Add products first.")
        return

    with st.form("dlg_restock_form", clear_on_submit=True):
        selected_sku = st.selectbox("Select Product", options=list(product_options.keys()),
                                    format_func=lambda x: product_options[x])
        qty_to_add   = st.number_input("Quantity to Add", min_value=1, value=5, step=1)
        restock_reason = st.text_input("Reason", value="Restock shipment")
        submitted = st.form_submit_button("📥 Apply Restock", type="primary", width='stretch')
        if submitted:
            with get_session() as session:
                try:
                    logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Restock Product", f"SKU: {selected_sku}, Qty: {qty_to_add}, Reason: {restock_reason}")
                    logic.restock_product(session, selected_sku, qty_to_add, restock_reason)
                    session.commit()
                    try:
                        sync_to_google_sheet_if_configured()
                    except Exception:
                        pass
                    st.success(f"Restocked {qty_to_add} units of {selected_sku}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Restock failed: {e}")


# ─── DIALOG: Register Customer ───────────────────────────────────────────────
@st.dialog("👥 Register New Customer", width="large")
def dialog_add_customer():
    with st.form("dlg_new_customer_form", clear_on_submit=True):
        customer_name = st.text_input("Customer Full Name *", placeholder="Jane Doe")
        phone   = st.text_input("Phone Number * (Unique)", placeholder="+20100000000").strip()
        address = st.text_input("Billing Address", placeholder="Cairo, Egypt")
        submitted = st.form_submit_button("✅ Register Customer", type="primary", width='stretch')
        if submitted:
            if not customer_name or not phone:
                st.error("Name and Phone are required!")
            else:
                with get_session() as session:
                    try:
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Add Customer", f"Name: {customer_name}, Phone: {phone}")
                        logic.add_customer(session, customer_name, phone, address)
                        session.commit()
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success(f"Customer '{customer_name}' registered!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")


# ─── DIALOG: Add New Expense ──────────────────────────────────────────────────
@st.dialog("💸 Add New Expense", width="large")
def dialog_add_expense():
    with st.form("dlg_new_expense_form", clear_on_submit=True):
        item_val = st.text_input("Expense Item *", placeholder="أكل / أوبر / إيجار")
        amount_val = st.number_input("Amount (EGP) *", min_value=0.0, value=100.0, step=10.0)
        wallet_val = st.selectbox("Wallet / Account", options=["شباسي", "حجازي"])
        day_val = st.date_input("Date", value=datetime.today())
        submitted = st.form_submit_button("✅ Record Expense", type="primary", width='stretch')
        if submitted:
            if not item_val:
                st.error("Expense Item name is required!")
            else:
                with get_session() as session:
                    try:
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Add Expense", f"Item: {item_val}, Amount: {amount_val}, Wallet: {wallet_val}")
                        expense = Expense(
                            day=datetime.combine(day_val, datetime.min.time()),
                            item=item_val,
                            wallet=wallet_val,
                            amount=amount_val
                        )
                        session.add(expense)
                        session.commit()
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success(f"Expense of EGP {amount_val:,.2f} recorded!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to record expense: {e}")


# ─── DIALOG: Batch Insert Expenses ────────────────────────────────────────────
@st.dialog("📥 Batch Insert Expenses", width="large")
def dialog_batch_insert_expenses():
    import io
    st.write("Record multiple expenses at once. Choose a paste method or upload a file.")
    
    with st.expander("ℹ️ Column Names & Guidelines"):
        st.write("""
        **Required Columns:**
        - `Item`: Name/Details of the expense
        - `Amount`: Numeric cost value (EGP)
        
        **Optional Columns:**
        - `Day` / `Date` (defaults to today)
        - `Wallet` / `Account` (expects 'شباسي' or 'حجازي', defaults to 'شباسي')
        """)
        
    t1, t2 = st.tabs(["📋 Paste Data", "📤 Upload CSV/Excel"])
    df = None
    
    with t1:
        pasted_text = st.text_area("Paste tab-separated or comma-separated rows here (including header row):", height=200, placeholder="Day\tItem\tWallet\tAmount\n2026-06-18\tTest Expense\tشباسي\t150")
        if pasted_text.strip():
            try:
                df = pd.read_csv(io.StringIO(pasted_text.strip()), sep=None, engine='python')
            except Exception as e:
                st.error(f"Failed to parse text: {e}")
                
    with t2:
        uploaded_file = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx"], key="exp_batch_uploader")
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
            except Exception as e:
                st.error(f"Failed to read file: {e}")
                
    if df is not None:
        st.subheader("Preview Data")
        
        col_mappings = {
            'day': ['day', 'Day', 'date', 'Date', 'Day / Date'],
            'item': ['item', 'Item', 'expense_item', 'Expense Item', 'Details', 'Expense'],
            'wallet': ['wallet', 'Wallet', 'wallet_account', 'Wallet / Account', 'Account'],
            'amount': ['amount', 'Amount', 'cost', 'Cost', 'Amount (EGP)']
        }
        
        mapped_df = pd.DataFrame()
        raw_cols = df.columns.tolist()
        
        for canonical, options in col_mappings.items():
            found = False
            for opt in options:
                for c in raw_cols:
                    if c.strip().lower() == opt.strip().lower():
                        mapped_df[canonical] = df[c]
                        found = True
                        break
                if found:
                    break
            if not found:
                if canonical == 'day':
                    mapped_df[canonical] = datetime.today().strftime("%Y-%m-%d")
                elif canonical == 'wallet':
                    mapped_df[canonical] = "شباسي"
                else:
                    mapped_df[canonical] = ""
                    
        missing = []
        if 'item' not in mapped_df.columns or mapped_df['item'].astype(str).str.strip().eq("").all():
            missing.append("Item/Expense name")
        if 'amount' not in mapped_df.columns or mapped_df['amount'].astype(str).str.strip().eq("").all():
            missing.append("Amount")
            
        if missing:
            st.error(f"Could not map required columns: {', '.join(missing)}. Please check headers.")
        else:
            mapped_df['item'] = mapped_df['item'].astype(str).str.strip()
            
            def local_safe_float(v):
                if pd.isna(v) or str(v).strip() == "": return 0.0
                try: return float(v)
                except: return 0.0
                
            mapped_df['amount'] = mapped_df['amount'].apply(local_safe_float)
            
            def clean_wallet(w):
                if pd.isna(w): return "شباسي"
                s = str(w).strip()
                if "حجازي" in s: return "حجازي"
                return "شباسي"
                
            mapped_df['wallet'] = mapped_df['wallet'].apply(clean_wallet)
            
            def parse_date(d):
                if pd.isna(d) or str(d).strip() == "":
                    return datetime.today()
                s = str(d).strip()
                if hasattr(d, 'to_pydatetime'):
                    return d.to_pydatetime()
                try:
                    return datetime.strptime(s.split()[0], "%Y-%m-%d")
                except:
                    try:
                        return datetime.strptime(s.split()[0], "%d/%m/%Y")
                    except:
                        return datetime.today()
                        
            mapped_df['day'] = mapped_df['day'].apply(parse_date)
            
            display_df = mapped_df.copy()
            display_df['day'] = display_df['day'].dt.strftime("%Y-%m-%d")
            st.dataframe(display_df, width='stretch', hide_index=True)
            
            if st.button("🚀 Confirm & Insert Expenses", type="primary", width='stretch'):
                with get_session() as session:
                    success_count = 0
                    for _, row in mapped_df.iterrows():
                        if not row['item'] or row['amount'] <= 0:
                            continue
                            
                        expense = Expense(
                            day=datetime.combine(row['day'].date(), datetime.min.time()),
                            item=row['item'],
                            wallet=row['wallet'],
                            amount=row['amount']
                        )
                        session.add(expense)
                        success_count += 1
                        
                    if success_count > 0:
                        session.commit()
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Batch Add Expenses", f"Added {success_count} expenses")
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        st.success(f"Successfully added {success_count} expenses!")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("No expenses added. Please verify row contents.")


# ─── DIALOG: Process New Order ───────────────────────────────────────────────
@st.dialog("🛒 Process New Order", width="large")
def dialog_new_order(cust_options, prod_options):
    if not cust_options or not prod_options:
        st.warning("You need at least one Customer and one Product to place an order.")
        return

    with st.form("dlg_new_order_form", clear_on_submit=True):
        selected_cust_id = st.selectbox("Customer", options=list(cust_options.keys()),
                                        format_func=lambda x: cust_options[x])
        selected_sku = st.selectbox("Product SKU", options=list(prod_options.keys()),
                                    format_func=lambda x: prod_options[x])
        c1, c2 = st.columns(2)
        with c1:
            quantity     = st.number_input("Quantity", min_value=1, value=1, step=1)
            order_status = st.selectbox("Fulfillment Status", ["Pending","Confirmed","Dispatched","Delivered"])
        with c2:
            payment_status = st.selectbox("Payment Status", ["Pending","Paid","Failed"])

        submitted = st.form_submit_button("🛒 Submit Order", type="primary", width='stretch')
        if submitted:
            with get_session() as session:
                try:
                    product_ref = session.query(Product).filter(Product.sku == selected_sku).first()
                    total_cost  = float(product_ref.selling_price * quantity)

                    if product_ref.initial_quantity < quantity and order_status == "Delivered":
                        st.error(f"Insufficient stock for '{product_ref.item_name}' "
                                 f"(Available: {product_ref.initial_quantity}).")
                    else:
                        new_order = logic.create_order(
                            session=session,
                            customer_id=selected_cust_id,
                            sku=selected_sku,
                            quantity=quantity,
                            total_amount=total_cost,
                            order_status=order_status,
                            payment_status=payment_status,
                        )
                        logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Create Order", f"Order #{new_order.order_id}: SKU={selected_sku}, Qty={quantity}, Status={order_status}")
                        session.commit()
                        try:
                            sync_to_google_sheet_if_configured()
                        except Exception:
                            pass
                        # Generate PDF receipt
                        try:
                            pdf_bytes = logic.generate_receipt_pdf(session, new_order.order_id)
                            st.session_state["receipt_pdf"]      = pdf_bytes
                            st.session_state["receipt_order_id"] = new_order.order_id
                        except Exception as pdf_err:
                            st.session_state.pop("receipt_pdf", None)
                            st.warning(f"Order saved, PDF failed: {pdf_err}")
                        st.success(f"✅ Order #{new_order.order_id} created! Total: EGP {total_cost:,.2f}")
                        st.rerun()
                except Exception as e:
                    st.error(f"Order error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ─── TAB 1: DASHBOARD ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with tab_dashboard:
    st.markdown("""
    <div class="section-header">
        <h2>📊 Financial &amp; Inventory Dashboard</h2>
        <p>Live metrics, revenue aggregates, and low-stock indicators.</p>
    </div>""", unsafe_allow_html=True)

    with get_session() as session:
        metrics        = logic.get_financial_metrics(session)
        low_stock_prods = logic.get_low_stock_products(session, threshold=5)

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown(f"""<div class="kpi-card kpi-revenue">
                <div class="kpi-title">Total Revenue (Paid)</div>
                <div class="kpi-value">EGP {metrics['total_revenue']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""<div class="kpi-card kpi-profit">
                <div class="kpi-title">Gross Profit (Paid)</div>
                <div class="kpi-value">EGP {metrics['total_profit']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""<div class="kpi-card kpi-expenses">
                <div class="kpi-title">Total Expenses</div>
                <div class="kpi-value">EGP {metrics['total_expenses']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col4:
            st.markdown(f"""<div class="kpi-card kpi-netprofit">
                <div class="kpi-title">Net Profit</div>
                <div class="kpi-value">EGP {metrics['net_profit']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col5:
            st.markdown(f"""<div class="kpi-card kpi-orders">
                <div class="kpi-title">Completed Orders (Paid)</div>
                <div class="kpi-value">{metrics['paid_orders_count']}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if low_stock_prods:
            st.markdown(f"""<div class="alert-box">
                <h4>⚠️ Low Stock Alert!</h4>
                <p>{len(low_stock_prods)} product(s) below the 5-unit safety threshold — plan restocking soon.</p>
            </div>""", unsafe_allow_html=True)
            low_stock_data = [{
                "SKU": p.sku, "Product Name": p.item_name, "Arabic Name": p.item_name_arabic,
                "Stock": p.initial_quantity, "Price": f"EGP {p.selling_price:.2f}", "Supplier": p.supplier
            } for p in low_stock_prods]
            st.dataframe(style_zebra(pd.DataFrame(low_stock_data)), width='stretch', hide_index=True)
        else:
            st.success("✅ All products are above the 5-unit safety threshold.")

        st.subheader("Recent Stock Movements")
        ledger_entries = session.query(StockLedger).order_by(StockLedger.ledger_id.desc()).limit(10).all()
        if ledger_entries:
            ledger_data = [{
                "Ledger ID": e.ledger_id,
                "SKU": e.sku,
                "Item Name (Arabic)": e.product.item_name_arabic if e.product else "",
                "Qty Change": f"+{e.quantity_change}" if e.quantity_change > 0 else str(e.quantity_change),
                "Movement Reason": _format_ledger_reason(e.reason),
            } for e in ledger_entries]
            st.dataframe(style_zebra(pd.DataFrame(ledger_data)), width='stretch', hide_index=True)
        else:
            st.info("No stock movements recorded yet.")


# ══════════════════════════════════════════════════════════════════════════════
# ─── TAB 2: PRODUCTS ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with tab_products:
    st.markdown("""
    <div class="section-header">
        <h2>📦 Products &amp; Inventory Catalog</h2>
        <p>Manage product items, SKU registry, prices, and suppliers.</p>
    </div>""", unsafe_allow_html=True)

    # ── Action buttons ────────────────────────────────────────────────────────
    btn_col1, btn_col2, btn_col3, _ = st.columns([1.2, 1.2, 1.2, 3.4])
    with btn_col1:
        if st.button("➕ Add New Product", type="primary", width='stretch'):
            dialog_add_product()
    with btn_col2:
        if st.button("📥 Restock Product", width='stretch'):
            dialog_restock()
    with btn_col3:
        if st.button("📥 Batch Insert", key="btn_batch_insert_products", width='stretch'):
            dialog_batch_insert_products()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Product table ─────────────────────────────────────────────────────────
    with get_session() as session:
        products = session.query(Product).all()
        if products:
            prod_data = [{
                "SKU": p.sku, "Name (EN)": p.item_name, "Name (AR)": p.item_name_arabic,
                "Qty": p.initial_quantity, "Buying (EGP)": f"EGP {p.buying_price:.2f}",
                "Selling (EGP)": f"EGP {p.selling_price:.2f}", "Supplier": p.supplier
            } for p in products]
            df_prod = pd.DataFrame(prod_data)
            evt = st.dataframe(style_zebra(df_prod), width='stretch', hide_index=True, on_select="rerun", selection_mode="single-row", key=f"prod_df_{st.session_state.prod_df_ver}")
            if evt and evt.selection and evt.selection.rows:
                selected_row = evt.selection.rows[0]
                sku = df_prod.iloc[selected_row]["SKU"]
                st.session_state["edit_sku"] = sku
                st.rerun()
        else:
            st.info("No products registered yet. Click **Add New Product** to get started.")


# ══════════════════════════════════════════════════════════════════════════════
# ─── TAB 3: CUSTOMERS ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with tab_customers:
    st.markdown("""
    <div class="section-header">
        <h2>👥 Customers Directory</h2>
        <p>Register and view customer contact sheets.</p>
    </div>""", unsafe_allow_html=True)

    btn_col, _ = st.columns([1, 5])
    with btn_col:
        if st.button("➕ Register Customer", type="primary", width='stretch'):
            dialog_add_customer()

    st.markdown("<br>", unsafe_allow_html=True)

    with get_session() as session:
        customers = session.query(Customer).all()
        if customers:
            cust_data = [{
                "ID": c.customer_id, "Name": c.customer_name,
                "Phone": c.customer_phone_number, "Address": c.customer_address
            } for c in customers]
            df_cust = pd.DataFrame(cust_data)
            evt = st.dataframe(style_zebra(df_cust), width='stretch', hide_index=True, on_select="rerun", selection_mode="single-row", key=f"cust_df_{st.session_state.cust_df_ver}")
            if evt and evt.selection and evt.selection.rows:
                selected_row = evt.selection.rows[0]
                cust_id = int(df_cust.iloc[selected_row]["ID"])
                st.session_state["edit_cust_id"] = cust_id
                st.rerun()
        else:
            st.info("No customers registered yet.")


# ══════════════════════════════════════════════════════════════════════════════
# ─── TAB 4: ORDERS ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with tab_orders:
    st.markdown("""
    <div class="section-header">
        <h2>🛒 Orders, Fulfillment &amp; Ledger Audit</h2>
        <p>Fulfill customer orders, adjust status, and audit stock changes.</p>
    </div>""", unsafe_allow_html=True)

    # Pre-load lookups
    cust_options = {}
    prod_options = {}
    with get_session() as session:
        for c in session.query(Customer).all():
            cust_options[c.customer_id] = f"{c.customer_name} ({c.customer_phone_number})"
        for p in session.query(Product).all():
            prod_options[p.sku] = f"{p.sku} — {p.item_name} (EGP {p.selling_price:.2f})"

    # ── Action button ──────────────────────────────────────────────────────────
    btn_col, receipt_col = st.columns([1, 3])
    with btn_col:
        if st.button("🛒 Process New Order", type="primary", width='stretch'):
            dialog_new_order(cust_options, prod_options)

    # Receipt download banner (persists after order submission)
    with receipt_col:
        if st.session_state.get("receipt_pdf"):
            r_id = st.session_state.get("receipt_order_id", "")
            rc1, rc2 = st.columns([2, 1])
            with rc1:
                st.download_button(
                    label=f"📄 Download Receipt — Order #{r_id}",
                    data=st.session_state["receipt_pdf"],
                    file_name=f"receipt_order_{r_id}.pdf",
                    mime="application/pdf",
                    width='stretch',
                )
            with rc2:
                if st.button("✖ Dismiss", key="dismiss_receipt"):
                    st.session_state.pop("receipt_pdf", None)
                    st.session_state.pop("receipt_order_id", None)
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Order log + Manage order (side by side) ────────────────────────────────
    col_log, col_manage = st.columns([3, 2])

    with col_log:
        st.subheader("📋 Order Log")
        with get_session() as session:
            orders = session.query(Order).order_by(Order.order_id.desc()).all()
            if orders:
                grouped = defaultdict(list)
                for o in orders:
                    grouped[o.order_id].append(o)
                orders_data = []
                for ord_id, items in grouped.items():
                    first = items[0]
                    cust  = session.query(Customer).filter(Customer.customer_id == first.customer_id).first()
                    orders_data.append({
                        "Order ID": ord_id,
                        "Customer": cust.customer_name if cust else f"ID {first.customer_id}",
                        "SKUs": ", ".join(i.sku for i in items),
                        "Qty": sum(i.quantity for i in items),
                        "Total (EGP)": f"EGP {sum(i.total_amount for i in items):,.2f}",
                        "Fulfillment": first.order_status,
                        "Payment": first.payment_status,
                        "Date": first.order_date.strftime("%Y-%m-%d %H:%M"),
                    })
                df_orders = pd.DataFrame(orders_data)
                evt = st.dataframe(style_zebra(df_orders), width='stretch', hide_index=True, on_select="rerun", selection_mode="single-row", key=f"order_df_{st.session_state.order_df_ver}")
                if evt and evt.selection and evt.selection.rows:
                    selected_row = evt.selection.rows[0]
                    order_id = int(df_orders.iloc[selected_row]["Order ID"])
                    st.session_state["edit_order_id"] = order_id
                    st.rerun()
            else:
                st.info("No orders placed yet.")

    with col_manage:
        st.subheader("✏️ Manage Existing Order")
        order_options  = {}
        order_statuses = {}
        order_payments = {}
        with get_session() as session:
            orders_list = session.query(Order).order_by(Order.order_id.desc()).all()
            for o in orders_list:
                if o.order_id not in order_options:
                    cust = session.query(Customer).filter(Customer.customer_id == o.customer_id).first()
                    total = sum(i.total_amount for i in orders_list if i.order_id == o.order_id)
                    cname = cust.customer_name if cust else f"ID {o.customer_id}"
                    order_options[o.order_id]  = f"Order #{o.order_id} — {cname} (EGP {total:,.2f})"
                    order_statuses[o.order_id] = o.order_status
                    order_payments[o.order_id] = o.payment_status

        if order_options:
            sel_id = st.selectbox("Select Order", options=list(order_options.keys()),
                                  format_func=lambda x: order_options[x], key="manage_order_sel")
            curr_ord = order_statuses.get(sel_id, "Pending")
            curr_pay = order_payments.get(sel_id, "Pending")
            st.info(f"**Fulfillment:** {curr_ord}  |  **Payment:** {curr_pay}")
            is_admin = (st.session_state.get("user_role") == "Admin")
            status_options = ["Pending","Confirmed","Dispatched","Delivered"]
            status_idx = 0
            if curr_ord in status_options:
                status_idx = status_options.index(curr_ord)
                
            pay_options = ["Pending","Paid","Failed"]
            pay_idx = 0
            if curr_pay in pay_options:
                pay_idx = pay_options.index(curr_pay)

            with st.form("update_order_form"):
                new_ord = st.selectbox("Update Fulfillment", status_options,
                                       index=status_idx,
                                       disabled=not is_admin)
                new_pay = st.selectbox("Update Payment", pay_options,
                                       index=pay_idx,
                                       disabled=not is_admin)
                if is_admin:
                    if st.form_submit_button("Apply Changes", type="primary"):
                        with get_session() as session:
                            try:
                                logic.update_order_status(session, sel_id, new_ord)
                                logic.update_payment_status(session, sel_id, new_pay)
                                session.commit()
                                try:
                                    sync_to_google_sheet_if_configured()
                                except Exception:
                                    pass
                                st.success(f"Order #{sel_id} updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Update failed: {e}")
                else:
                    st.warning("⚠️ View-only: Logging in as Admin is required to modify or delete.")
                    st.form_submit_button("Close / Dismiss", disabled=True)
        else:
            st.info("No orders to manage yet.")

    # ── Full Ledger ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📚 Complete Stock Ledger Audit Trail")
    with get_session() as session:
        ledger = session.query(StockLedger).order_by(StockLedger.ledger_id.desc()).all()
        if ledger:
            led_data = [{
                "Ledger ID": e.ledger_id,
                "SKU": e.sku,
                "Item Name (Arabic)": e.product.item_name_arabic if e.product else "",
                "Qty Adjustment": f"+{e.quantity_change}" if e.quantity_change > 0 else str(e.quantity_change),
                "Movement Reason": _format_ledger_reason(e.reason),
            } for e in ledger]
            st.dataframe(style_zebra(pd.DataFrame(led_data)), width='stretch', hide_index=True)
        else:
            st.info("No ledger entries recorded.")


# ══════════════════════════════════════════════════════════════════════════════
# ─── TAB 5: EXPENSES & WALLET BALANCE ─────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with tab_expenses:
    st.markdown("""
    <div class="section-header">
        <h2>💸 Expenses Tracker &amp; Wallet Settlement</h2>
        <p>Record expenses, compare wallet balances, and settle debts between Shabasi and Hejazi.</p>
    </div>""", unsafe_allow_html=True)

    with get_session() as session:
        # Get wallet totals and settlements
        wb_data = logic.get_wallet_balance(session)
        shabasi_total = wb_data["shabasi_total"]
        hejazi_total = wb_data["hejazi_total"]
        total_settlements = wb_data["total_settlements"]

        # 1. Display wallet cards
        col_w1, col_w2, col_w3, col_w4 = st.columns(4)
        with col_w1:
            st.markdown(f"""<div class="kpi-card kpi-revenue">
                <div class="kpi-title">Total Paid: شباسي (Shabasi)</div>
                <div class="kpi-value">EGP {shabasi_total:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col_w2:
            st.markdown(f"""<div class="kpi-card kpi-profit">
                <div class="kpi-title">Total Paid: حجازي (Hejazi)</div>
                <div class="kpi-value">EGP {hejazi_total:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col_w3:
            st.markdown(f"""<div class="kpi-card kpi-orders">
                <div class="kpi-title">Total Settled (شباسي ➔ حجازي)</div>
                <div class="kpi-value">EGP {total_settlements:,.2f}</div>
            </div>""", unsafe_allow_html=True)

        # Calculate base debt and outstanding balance
        diff = abs(shabasi_total - hejazi_total)
        base_debt = diff / 2.0
        
        # Outstanding Debt calculation
        if hejazi_total > shabasi_total:
            # Hejazi paid more, Shabasi owes Hejazi
            outstanding_debt = base_debt - total_settlements
            debtor = "شباسي (Shabasi)"
            creditor = "حجازي (Hejazi)"
        else:
            # Shabasi paid more, Hejazi owes Shabasi
            # If Hejazi owes Shabasi, settlements from Shabasi to Hejazi subtract as debt collected 
            outstanding_debt = base_debt - total_settlements
            debtor = "حجازي (Hejazi)"
            creditor = "شباسي (Shabasi)"

        with col_w4:
            card_class = "kpi-expenses" if outstanding_debt > 0 else "kpi-netprofit"
            st.markdown(f"""<div class="kpi-card {card_class}">
                <div class="kpi-title">Outstanding Debt Balance</div>
                <div class="kpi-value">EGP {max(0.0, outstanding_debt):,.2f}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # 2. Status banner
        if diff == 0:
            st.success("⚖️ Both wallets have paid exactly the same amount! The balance is perfect.")
        else:
            if outstanding_debt > 0:
                st.warning(f"⚖️ **{creditor}** paid more. **{debtor}** owes **{creditor}** a base debt of **EGP {base_debt:,.2f}**. After subtracting EGP {total_settlements:,.2f} settled, the remaining debt is **EGP {outstanding_debt:,.2f}**.")
            elif outstanding_debt < 0:
                st.info(f"⚖️ **{creditor}** paid more (Base: EGP {base_debt:,.2f}), but **{debtor}** overpaid settlements by **EGP {abs(outstanding_debt):,.2f}**.")
            else:
                st.success("⚖️ Debt has been fully settled! Both wallets are balanced.")

        st.markdown("---")

        # 3. Actions Row (Add Expense & Password-Protected Settlement)
        col_actions, col_settle = st.columns([1, 1])
        
        with col_actions:
            st.subheader("➕ Record New Expense")
            ex_col1, ex_col2 = st.columns(2)
            with ex_col1:
                if st.button("➕ Add New Expense", type="primary", width='stretch'):
                    dialog_add_expense()
            with ex_col2:
                if st.button("📥 Batch Insert", key="btn_batch_insert_expenses", width='stretch'):
                    dialog_batch_insert_expenses()
                
        with col_settle:
            st.subheader("🔒 Settle Debt / Log Debt Collected")
            pwd = st.text_input("Enter password to unlock debt collection", type="password", key="settle_pwd")
            if pwd == "Yaa2813":
                st.success("Unlocked!")
                with st.form("debt_settlement_form", clear_on_submit=True):
                    settle_amount = st.number_input("Settlement Amount to Subtract (EGP) *", min_value=0.0, value=outstanding_debt if outstanding_debt > 0 else 100.0, step=10.0)
                    settle_notes = st.text_input("Notes", placeholder="Repayment of trip expenses / transfer")
                    if st.form_submit_button("✅ Record Settlement Transfer", type="primary", width='stretch'):
                        if settle_amount <= 0:
                            st.error("Please enter an amount greater than 0.")
                        else:
                            try:
                                new_settlement = DebtSettlement(
                                    amount=settle_amount,
                                    date=datetime.now(),
                                    notes=settle_notes
                                )
                                session.add(new_settlement)
                                logic.log_action(session, st.session_state.get("user_role", "Unknown"), "Record Settlement", f"Amount: {settle_amount}, Notes: {settle_notes}")
                                session.commit()
                                try:
                                    sync_to_google_sheet_if_configured()
                                except Exception:
                                    pass
                                st.success("Settlement recorded successfully!")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            elif pwd != "":
                st.error("Incorrect password! Access denied.")

        st.markdown("---")

        # 4. Tables: Expense Log & Settlement Log
        col_tab1, col_tab2 = st.columns([3, 2])
        
        with col_tab1:
            st.subheader("📋 Expense log")
            expenses = session.query(Expense).order_by(Expense.day.desc(), Expense.expense_id.desc()).all()
            if expenses:
                exp_data = [{
                    "Day": e.day.strftime("%Y-%m-%d") if e.day else "—",
                    "Item": e.item,
                    "Wallet": e.wallet or "—",
                    "Amount": f"EGP {e.amount:,.2f}"
                } for e in expenses]
                df_exp = pd.DataFrame(exp_data)
                evt = st.dataframe(style_zebra(df_exp), width='stretch', hide_index=True, on_select="rerun", selection_mode="single-row", key=f"exp_df_{st.session_state.exp_df_ver}")
                if evt and evt.selection and evt.selection.rows:
                    selected_row = evt.selection.rows[0]
                    expense_id = expenses[selected_row].expense_id
                    st.session_state["edit_expense_id"] = expense_id
                    st.rerun()
            else:
                st.info("No expenses recorded yet. Click **Add New Expense** or Sync to load Google Sheet data.")
                
        with col_tab2:
            st.subheader("🔄 Debt Settlements Log (شباسي ➔ حجازي)")
            settlements = session.query(DebtSettlement).order_by(DebtSettlement.date.desc()).all()
            if settlements:
                settle_data = [{
                    "Date": s.date.strftime("%Y-%m-%d %H:%M"),
                    "Amount (EGP)": f"EGP {s.amount:,.2f}",
                    "Notes": s.notes or "—"
                } for s in settlements]
                st.dataframe(style_zebra(pd.DataFrame(settle_data)), width='stretch', hide_index=True)
            else:
                st.info("No settlements recorded yet.")


if is_admin_user:
    with tab_logs:
        st.markdown("""
        <div class="section-header">
            <h2>🕵️ System Action Audit Logs</h2>
            <p>Track which user did what actions in real-time.</p>
        </div>""", unsafe_allow_html=True)
        
        with get_session() as session:
            logs = session.query(ActionLog).order_by(ActionLog.log_id.desc()).all()
            if logs:
                log_data = [{
                    "Log ID": l.log_id,
                    "Timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "User": l.username,
                    "Action": l.action,
                    "Details": l.details
                } for l in logs]
                st.dataframe(style_zebra(pd.DataFrame(log_data)), width='stretch', hide_index=True)
            else:
                st.info("No system actions logged yet.")

with tab_settings:
    st.markdown("""
    <div class="section-header">
        <h2>⚙️ Settings & Session</h2>
        <p>Manage your login session, active parameters, and configuration options.</p>
    </div>""", unsafe_allow_html=True)
    
    c1, c2 = st.columns([3, 1])
    with c1:
        st.info(f"👤 Currently logged in as: **{st.session_state.get('user_role', 'Unknown')}**")
    with c2:
        if st.button("🚪 Logout", type="primary", width='stretch', key="btn_logout"):
            with st.spinner("Syncing pending changes to Google Sheet before logging out..."):
                try:
                    BackgroundSyncManager.sync_now_blocking()
                except Exception as e:
                    pass
            st.session_state["logged_in"] = False
            st.session_state["user_role"] = None
            st.rerun()





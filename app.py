import re
import os
import streamlit as st
import pandas as pd
import base64
from collections import defaultdict
from datetime import datetime
from database import init_db, get_session
from models import Product, Customer, Order, StockLedger, Expense, DebtSettlement
import logic


# ─── HELPER ──────────────────────────────────────────────────────────────────
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

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DEXEF Core - Inventory Control",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_db()

# ─── SEED DATA ────────────────────────────────────────────────────────────────
with get_session() as session:
    if session.query(Product).count() == 0:
        try:
            logic.add_product(session, "APP-14",  "iPhone 14 Pro",     "آيفون ١٤ برو",              8,  800.0,  999.0, "Apple Inc.")
            logic.add_product(session, "GAL-S23", "Samsung Galaxy S23", "سامسونج جالكسي إس ٢٣",    12,  700.0,  899.0, "Samsung Electronics")
            logic.add_product(session, "MAC-M2",  "MacBook Air M2",     "ماك بوك إير إم ٢",          3, 1000.0, 1299.0, "Apple Inc.")
            logic.add_customer(session, "Ahmad Mansoor",  "+966500000001", "Riyadh, KSA")
            logic.add_customer(session, "Fatima Al-Harbi", "+966500000002", "Jeddah, KSA")
            session.commit()
        except Exception:
            pass

# ─── GLOBAL CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown { font-family: 'Outfit', sans-serif; }

/* ── Hide default Streamlit top decoration ── */
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 0 !important; }

/* ── Top nav bar ── */
.top-navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    padding: 0 32px;
    height: 64px;
    border-bottom: 1px solid #1e40af;
    position: sticky;
    top: 0;
    z-index: 999;
    margin-bottom: 10px;
}
.top-navbar .brand {
    font-size: 1.25rem;
    font-weight: 700;
    color: #fff;
    letter-spacing: 0.02em;
    display: flex;
    align-items: center;
    gap: 10px;
}
.top-navbar .brand span { color: #60a5fa; }

/* ── Tab overrides to look like nav links ── */
.stTabs [data-baseweb="tab-list"] {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important;
    border-bottom: 2px solid #1e40af !important;
    gap: 0 !important;
    padding: 0 8px !important;
}
.stTabs [data-baseweb="tab"] {
    color: #94a3b8 !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
    padding: 14px 22px !important;
    border-radius: 0 !important;
    border-bottom: 3px solid transparent !important;
    transition: color 0.2s, border-color 0.2s !important;
}
.stTabs [data-baseweb="tab"]:hover { color: #e2e8f0 !important; }
.stTabs [aria-selected="true"] {
    color: #60a5fa !important;
    border-bottom: 3px solid #2563eb !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"]    { display: none !important; }

/* ── KPI cards ── */
.kpi-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 22px 24px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.04);
    transition: transform 0.2s, box-shadow 0.2s;
    border-top: 4px solid #2563eb;
}
.kpi-card:hover { transform: translateY(-3px); box-shadow: 0 12px 24px rgba(0,0,0,0.08); }
.kpi-title { font-size: 0.78rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
.kpi-value { font-size: 1.85rem; font-weight: 700; color: #0f172a; margin-top: 6px; }
.kpi-revenue { border-top-color: #2563eb; }
.kpi-profit  { border-top-color: #10b981; }
.kpi-orders  { border-top-color: #f59e0b; }
.kpi-expenses { border-top-color: #ef4444; }
.kpi-netprofit { border-top-color: #06b6d4; }

/* ── Alert box ── */
.alert-box {
    background: #fff1f2; border: 1px solid #fecdd3; border-radius: 12px;
    padding: 18px 24px; border-left: 5px solid #f43f5e; color: #9f1239; margin-bottom: 24px;
}
.alert-box h4 { margin: 0 0 6px; color: #881337; font-weight: 600; }

/* ── Action button row ── */
.action-btn-row {
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px;
}

/* ── Section header ── */
.section-header {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    padding: 20px 26px; border-radius: 12px; color: white; margin-bottom: 24px;
    border-left: 5px solid #2563eb;
}
.section-header h2 { margin: 0; font-size: 1.5rem; font-weight: 700;
    background: linear-gradient(to right,#fff,#93c5fd);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.section-header p  { margin: 4px 0 0; opacity: 0.75; font-size: 0.88rem; }

/* ── Dialog tweaks ── */
[data-testid="stDialog"] div[role="dialog"] {
    border-radius: 16px !important;
    border: 1px solid #1e40af !important;
    box-shadow: 0 25px 60px rgba(0,0,0,0.35) !important;
}
</style>
""", unsafe_allow_html=True)

# ─── TOP HEADER (Yaa Logo + DEXEF Brand Title) ────────────────────────────────
col_logo, col_nav = st.columns([1, 14])
with col_logo:
    if os.path.exists("yaa_logo.jpg"):
        st.image("yaa_logo.jpg", width=68)
with col_nav:
    st.markdown("""
    <div style="padding-top: 4px;">
      <h1 style="font-size: 1.85rem; font-weight: 700; color: #1e293b; margin: 0; line-height: 1.2;">
        DEXEF <span style="color: #2563eb;">Core</span>
      </h1>
      <p style="color: #64748b; font-size: 0.85rem; margin: 0; padding-top: 2px;">Inventory &amp; Orders Management</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin: 8px 0 16px 0; border: 0; border-top: 1px solid #e2e8f0;' />", unsafe_allow_html=True)


# ─── GOOGLE SHEET AUTO-SYNC LOGIC ────────────────────────────────────────────
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1goeE1w9QaDuTGXcj1EEClj14gPC_3xRL8wZIU9lFOlY/edit?usp=sharing"

if "last_sync" not in st.session_state:
    st.session_state["last_sync"] = None

def perform_sync():
    with get_session() as session:
        try:
            logic.sync_google_sheet(session, GSHEET_URL)
            session.commit()
            st.session_state["last_sync"] = datetime.now()
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"Sync failed: {e}")
            return False

# Auto-sync at startup or if 3 minutes have passed since last check
import time
if "last_sync_check" not in st.session_state:
    st.session_state["last_sync_check"] = 0

if time.time() - st.session_state["last_sync_check"] > 180:
    st.session_state["last_sync_check"] = time.time()
    with st.spinner("🔄 Auto-updating data from Google Sheets..."):
        perform_sync()

# Thin status bar and sync button right above navigation
col_status, col_btn = st.columns([5, 1])
with col_status:
    if st.session_state["last_sync"]:
        sync_time_str = st.session_state["last_sync"].strftime("%I:%M:%S %p")
        st.markdown(f"<p style='color:#64748b;font-size:0.85rem;margin-top:8px;'>🌐 Google Sheet auto-updated. Last sync: <b>{sync_time_str}</b></p>", unsafe_allow_html=True)
    else:
        st.markdown("<p style='color:#64748b;font-size:0.85rem;margin-top:8px;'>🌐 Not synced with Google Sheet yet.</p>", unsafe_allow_html=True)
with col_btn:
    if st.button("🔄 Sync Now", use_container_width=True):
        with st.spinner("Syncing..."):
            if perform_sync():
                st.success("Synced!")
                time.sleep(1)
                st.rerun()

tab_dashboard, tab_products, tab_customers, tab_orders, tab_expenses = st.tabs([
    "📊  Dashboard",
    "📦  Products Catalog",
    "👥  Customers Directory",
    "🛒  Orders & Fulfillment",
    "💸  Expenses Tracker",
])


# ─── SIDEBAR (Excel import only) ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📥 Import Data from Excel")
    uploaded_file = st.file_uploader("Upload Yaa.xlsx workbook", type=["xlsx"])
    if uploaded_file is not None:
        clear_db_checked = st.checkbox("Clear existing database before importing", value=True)
        if st.button("Import Excel Data", type="primary"):
            temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_data.xlsx")
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            with get_session() as session:
                try:
                    logic.import_excel_data(session, temp_path, clear_db=clear_db_checked)
                    session.commit()
                    st.success("Excel data imported successfully!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to import Excel: {e}")
    st.markdown("---")
    st.info("Connected to local SQLite database: `inventory.db`")


# ══════════════════════════════════════════════════════════════════════════════
# ─── DIALOG: Add New Product ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@st.dialog("📦 Add New Product", width="large")
def dialog_add_product():
    with st.form("dlg_new_product_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            sku = st.text_input("SKU Code *", placeholder="APP-15").strip()
            item_name = st.text_input("Item Name (English) *", placeholder="iPhone 15 Pro")
            initial_quantity = st.number_input("Initial Quantity", min_value=0, value=10, step=1)
            supplier = st.text_input("Supplier Company", placeholder="Apple Distribution")
        with c2:
            item_name_arabic = st.text_input("Item Name (Arabic)", placeholder="آيفون ١٥ برو")
            buying_price  = st.number_input("Buying Price (EGP)",  min_value=0.0, value=500.0, step=10.0)
            selling_price = st.number_input("Selling Price (EGP)", min_value=0.0, value=750.0, step=10.0)

        submitted = st.form_submit_button("✅ Register Product", type="primary", use_container_width=True)
        if submitted:
            if not sku or not item_name:
                st.error("SKU and English Item Name are required!")
            else:
                with get_session() as session:
                    try:
                        logic.add_product(session, sku, item_name, item_name_arabic,
                                          initial_quantity, buying_price, selling_price, supplier)
                        session.commit()
                        st.success(f"Product '{item_name}' added successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ─── DIALOG: Restock Product ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
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
        submitted = st.form_submit_button("📥 Apply Restock", type="primary", use_container_width=True)
        if submitted:
            with get_session() as session:
                try:
                    logic.restock_product(session, selected_sku, qty_to_add, restock_reason)
                    session.commit()
                    st.success(f"Restocked {qty_to_add} units of {selected_sku}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Restock failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ─── DIALOG: Register Customer ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@st.dialog("👥 Register New Customer", width="large")
def dialog_add_customer():
    with st.form("dlg_new_customer_form", clear_on_submit=True):
        customer_name = st.text_input("Customer Full Name *", placeholder="Jane Doe")
        phone   = st.text_input("Phone Number * (Unique)", placeholder="+20100000000").strip()
        address = st.text_input("Billing Address", placeholder="Cairo, Egypt")
        submitted = st.form_submit_button("✅ Register Customer", type="primary", use_container_width=True)
        if submitted:
            if not customer_name or not phone:
                st.error("Name and Phone are required!")
            else:
                with get_session() as session:
                    try:
                        logic.add_customer(session, customer_name, phone, address)
                        session.commit()
                        st.success(f"Customer '{customer_name}' registered!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ─── DIALOG: Add New Expense ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@st.dialog("💸 Add New Expense", width="large")
def dialog_add_expense():
    with st.form("dlg_new_expense_form", clear_on_submit=True):
        item_val = st.text_input("Expense Item *", placeholder="أكل / أوبر / إيجار")
        amount_val = st.number_input("Amount (EGP) *", min_value=0.0, value=100.0, step=10.0)
        wallet_val = st.text_input("Wallet / Account", placeholder="شباسي / حجازي")
        day_val = st.date_input("Date", value=datetime.today())
        
        submitted = st.form_submit_button("✅ Record Expense", type="primary", use_container_width=True)
        if submitted:
            if not item_val:
                st.error("Expense Item name is required!")
            else:
                with get_session() as session:
                    try:
                        expense = Expense(
                            day=datetime.combine(day_val, datetime.min.time()),
                            item=item_val,
                            wallet=wallet_val,
                            amount=amount_val
                        )
                        session.add(expense)
                        session.commit()
                        st.success(f"Expense of EGP {amount_val:,.2f} recorded!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to record expense: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# ─── DIALOG: Process New Order ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
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

        submitted = st.form_submit_button("🛒 Submit Order", type="primary", use_container_width=True)
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
                        session.commit()
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
            st.dataframe(pd.DataFrame(low_stock_data), use_container_width=True, hide_index=True)
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
            st.dataframe(pd.DataFrame(ledger_data), use_container_width=True, hide_index=True)
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
    btn_col1, btn_col2, _ = st.columns([1, 1, 4])
    with btn_col1:
        if st.button("➕ Add New Product", type="primary", use_container_width=True):
            dialog_add_product()
    with btn_col2:
        if st.button("📥 Restock Product", use_container_width=True):
            dialog_restock()

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
            st.dataframe(pd.DataFrame(prod_data), use_container_width=True, hide_index=True)
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
        if st.button("➕ Register Customer", type="primary", use_container_width=True):
            dialog_add_customer()

    st.markdown("<br>", unsafe_allow_html=True)

    with get_session() as session:
        customers = session.query(Customer).all()
        if customers:
            cust_data = [{
                "ID": c.customer_id, "Name": c.customer_name,
                "Phone": c.customer_phone_number, "Address": c.customer_address
            } for c in customers]
            st.dataframe(pd.DataFrame(cust_data), use_container_width=True, hide_index=True)
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
        if st.button("🛒 Process New Order", type="primary", use_container_width=True):
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
                    use_container_width=True,
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
                st.dataframe(pd.DataFrame(orders_data), use_container_width=True, hide_index=True)
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
            with st.form("update_order_form"):
                new_ord = st.selectbox("Update Fulfillment", ["Pending","Confirmed","Dispatched","Delivered"],
                                       index=["Pending","Confirmed","Dispatched","Delivered"].index(curr_ord))
                new_pay = st.selectbox("Update Payment", ["Pending","Paid","Failed"],
                                       index=["Pending","Paid","Failed"].index(curr_pay))
                if st.form_submit_button("Apply Changes", type="primary"):
                    with get_session() as session:
                        try:
                            logic.update_order_status(session, sel_id, new_ord)
                            logic.update_payment_status(session, sel_id, new_pay)
                            session.commit()
                            st.success(f"Order #{sel_id} updated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Update failed: {e}")
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
            st.dataframe(pd.DataFrame(led_data), use_container_width=True, hide_index=True)
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
            if st.button("➕ Add New Expense", type="primary", use_container_width=True):
                dialog_add_expense()
                
        with col_settle:
            st.subheader("🔒 Settle Debt / Log Debt Collected")
            pwd = st.text_input("Enter password to unlock debt collection", type="password", key="settle_pwd")
            if pwd == "yaa123":
                st.success("Unlocked!")
                with st.form("debt_settlement_form", clear_on_submit=True):
                    settle_amount = st.number_input("Settlement Amount to Subtract (EGP) *", min_value=0.0, value=outstanding_debt if outstanding_debt > 0 else 100.0, step=10.0)
                    settle_notes = st.text_input("Notes", placeholder="Repayment of trip expenses / transfer")
                    if st.form_submit_button("✅ Record Settlement Transfer", type="primary", use_container_width=True):
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
                                session.commit()
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
                    "Date": e.day.strftime("%Y-%m-%d") if e.day else "—",
                    "Expense Item": e.item,
                    "Wallet / Account": e.wallet or "—",
                    "Amount (EGP)": f"EGP {e.amount:,.2f}"
                } for e in expenses]
                st.dataframe(pd.DataFrame(exp_data), use_container_width=True, hide_index=True)
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
                st.dataframe(pd.DataFrame(settle_data), use_container_width=True, hide_index=True)
            else:
                st.info("No settlements recorded yet.")



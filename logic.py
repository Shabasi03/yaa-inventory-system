from models import Product, Customer, Order, StockLedger, Expense, DebtSettlement, ActionLog
from sqlalchemy.orm import Session
from datetime import datetime

def log_action(session: Session, username: str, action: str, details: str):
    """Log an action performed by a user."""
    log = ActionLog(username=username, action=action, details=details, timestamp=datetime.utcnow())
    session.add(log)
    session.flush()

# --- CRUD OPERATIONS FOR PRODUCTS ---

def add_product(session: Session, sku: str, item_name: str, item_name_arabic: str, 
                initial_quantity: int, buying_price: float, selling_price: float, supplier: str) -> Product:
    """Create a new product and log the initial stock in ledger."""
    # Check if SKU is unique
    existing_product = session.query(Product).filter(Product.sku == sku).first()
    if existing_product:
        raise ValueError(f"Product with SKU '{sku}' already exists.")

    product = Product(
        sku=sku,
        item_name=item_name,
        item_name_arabic=item_name_arabic,
        initial_quantity=initial_quantity,
        buying_price=buying_price,
        selling_price=selling_price,
        supplier=supplier
    )
    session.add(product)
    session.flush()  # Generate primary key

    # Log initial stock in ledger if greater than 0
    if initial_quantity > 0:
        ledger_entry = StockLedger(
            sku=sku,
            quantity_change=initial_quantity,
            reason="Initial Stock Setup"
        )
        session.add(ledger_entry)

    return product

def restock_product(session: Session, sku: str, quantity: int, reason: str = "Restock") -> Product:
    """Add stock to a product and log the ledger entry."""
    product = session.query(Product).filter(Product.sku == sku).first()
    if not product:
        raise ValueError(f"Product with SKU '{sku}' not found.")
    
    product.initial_quantity += quantity
    ledger_entry = StockLedger(
        sku=sku,
        quantity_change=quantity,
        reason=reason
    )
    session.add(ledger_entry)
    return product

# --- CRUD OPERATIONS FOR CUSTOMERS ---

def add_customer(session: Session, customer_name: str, customer_phone_number: str, customer_address: str) -> Customer:
    """Create a new customer."""
    existing_customer = session.query(Customer).filter(Customer.customer_phone_number == customer_phone_number).first()
    if existing_customer:
        raise ValueError(f"Customer with phone '{customer_phone_number}' already exists.")
        
    customer = Customer(
        customer_name=customer_name,
        customer_phone_number=customer_phone_number,
        customer_address=customer_address
    )
    session.add(customer)
    session.flush()  # Generate primary key
    return customer

# --- CRUD OPERATIONS FOR ORDERS & TRIGGERS ---

def create_order(session: Session, customer_id: int, sku: str, quantity: int, 
                 total_amount: float, order_status: str = 'Pending', payment_status: str = 'Pending',
                 order_date: datetime = None, order_id: int = None) -> Order:
    """Create a new order. Trigger stock deduction immediately if status is Delivered."""
    product = session.query(Product).filter(Product.sku == sku).first()
    if not product:
        raise ValueError(f"Product with SKU '{sku}' not found.")
        
    customer = session.query(Customer).filter(Customer.customer_id == customer_id).first()
    if not customer:
        raise ValueError(f"Customer with ID {customer_id} not found.")

    if not order_date:
        order_date = datetime.utcnow()

    if not order_id:
        max_order = session.query(Order).order_by(Order.order_id.desc()).first()
        order_id = (max_order.order_id + 1) if max_order else 1

    order = Order(
        order_id=order_id,
        customer_id=customer_id,
        sku=sku,
        quantity=quantity,
        total_amount=total_amount,
        order_status=order_status,
        payment_status=payment_status,
        order_date=order_date
    )
    session.add(order)
    session.flush()  # Generate order_item_id

    # If the order is created with Delivered status, run stock deduction trigger
    if order_status == 'Delivered':
        _deduct_stock_for_order(session, order)

    return order

def update_order_status(session: Session, order_id: int, new_status: str) -> list[Order]:
    """Update status for all items in an order. Trigger stock deduction if status becomes Delivered."""
    orders = session.query(Order).filter(Order.order_id == order_id).all()
    if not orders:
        raise ValueError(f"Order with ID {order_id} not found.")
    
    for order in orders:
        old_status = order.order_status
        order.order_status = new_status
        
        if new_status == 'Delivered' and old_status != 'Delivered':
            _deduct_stock_for_order(session, order)
        elif old_status == 'Delivered' and new_status != 'Delivered':
            _revert_stock_deduction_for_order(session, order)
            
    return orders

def update_payment_status(session: Session, order_id: int, new_status: str) -> list[Order]:
    """Update payment status for all items in an order."""
    orders = session.query(Order).filter(Order.order_id == order_id).all()
    if not orders:
        raise ValueError(f"Order with ID {order_id} not found.")
    for order in orders:
        order.payment_status = new_status
    return orders

def _deduct_stock_for_order(session: Session, order: Order):
    """Internal helper to deduct stock and create StockLedger entry."""
    # Check if we already deducted stock for this order item
    deduction_reason = f"Order Fulfillment - Order #{order.order_id} Item #{order.order_item_id}"
    existing_ledger = session.query(StockLedger).filter(
        StockLedger.sku == order.sku,
        StockLedger.reason == deduction_reason
    ).first()
    
    if not existing_ledger:
        product = session.query(Product).filter(Product.sku == order.sku).first()
        if product:
            product.initial_quantity -= order.quantity
            ledger_entry = StockLedger(
                sku=order.sku,
                quantity_change=-order.quantity,
                reason=deduction_reason
            )
            session.add(ledger_entry)

def _revert_stock_deduction_for_order(session: Session, order: Order):
    """Internal helper to revert stock deduction if order status is updated from Delivered."""
    deduction_reason = f"Order Fulfillment - Order #{order.order_id} Item #{order.order_item_id}"
    existing_ledger = session.query(StockLedger).filter(
        StockLedger.sku == order.sku,
        StockLedger.reason == deduction_reason
    ).first()
    
    if existing_ledger:
        product = session.query(Product).filter(Product.sku == order.sku).first()
        if product:
            product.initial_quantity += order.quantity
        # Remove or negate the ledger entry
        session.delete(existing_ledger)

def import_excel_data(session: Session, file_path: str, clear_db: bool = True):
    """Import data from Yaa.xlsx sheets into SQLite database."""
    import pandas as pd
    
    # 1. Clear database if requested
    if clear_db:
        session.query(StockLedger).delete()
        session.query(Order).delete()
        session.query(Customer).delete()
        session.query(Product).delete()
        session.query(Expense).delete()
        session.query(DebtSettlement).delete()
        session.flush()
        
    xl = pd.ExcelFile(file_path)
    
    # 2. Import Products
    if 'Products' in xl.sheet_names:
        df_prod = pd.read_excel(file_path, sheet_name='Products')
        for _, row in df_prod.iterrows():
            sku = str(row['SKU']).strip()
            if not sku or pd.isna(row['SKU']):
                continue
            item_name = str(row['Item Name']).strip()
            item_name_arabic = str(row['Item Name Arabic']).strip() if not pd.isna(row['Item Name Arabic']) else ""
            initial_qty = int(row['Initial Quantity']) if not pd.isna(row['Initial Quantity']) else 0
            buying = float(row['Buying Price']) if not pd.isna(row['Buying Price']) else 0.0
            selling = float(row['Selling Price']) if not pd.isna(row['Selling Price']) else 0.0
            supplier = str(row['Supplier']).strip() if not pd.isna(row['Supplier']) else ""
            
            existing_prod = session.query(Product).filter(Product.sku == sku).first()
            if not existing_prod:
                add_product(
                    session=session,
                    sku=sku,
                    item_name=item_name,
                    item_name_arabic=item_name_arabic,
                    initial_quantity=initial_qty,
                    buying_price=buying,
                    selling_price=selling,
                    supplier=supplier
                )
                
    # 3. Import Customers
    def format_phone(val):
        if pd.isna(val):
            return ""
        s = str(val).strip()
        if s.endswith('.0'):
            s = s[:-2]
        # Egyptian mobile numbers are 11 digits starting with 01
        if len(s) == 10 and s.startswith('1'):
            s = '0' + s
        return s

    if 'Customers' in xl.sheet_names:
        df_cust = pd.read_excel(file_path, sheet_name='Customers')
        for _, row in df_cust.iterrows():
            cust_id = int(row['Customer ID']) if not pd.isna(row['Customer ID']) else None
            phone = format_phone(row['Customer Phone Number'])
            name = str(row['Customer Name']).strip()
            address = str(row['Customer Address']).strip() if not pd.isna(row['Customer Address']) else ""
            
            if not phone or not name:
                continue
                
            existing_cust = session.query(Customer).filter(Customer.customer_phone_number == phone).first()
            if not existing_cust:
                customer = Customer(
                    customer_id=cust_id,
                    customer_phone_number=phone,
                    customer_name=name,
                    customer_address=address
                )
                session.add(customer)
                session.flush()

    # 4. Import Orders
    if 'Orders' in xl.sheet_names and 'Income' in xl.sheet_names:
        df_orders = pd.read_excel(file_path, sheet_name='Orders')
        df_income = pd.read_excel(file_path, sheet_name='Income')
        
        income_map = {}
        for _, row in df_income.iterrows():
            ord_id = row['Order ID']
            if pd.isna(ord_id):
                continue
            ord_id = int(ord_id)
            
            p_status = str(row['Payment Status']).strip()
            if p_status.lower() == 'paied':
                p_status = 'Paid'
                
            income_map[ord_id] = {
                'status': str(row['Order Status']).strip(),
                'payment': p_status
            }
            
        for _, row in df_orders.iterrows():
            order_no = row['Order No.']
            if pd.isna(order_no):
                continue
            order_no = int(order_no)
            
            cust_id = int(row['Customer ID']) if not pd.isna(row['Customer ID']) else None
            sku = str(row['SKU']).strip()
            qty = int(row['Order Quantity']) if not pd.isna(row['Order Quantity']) else 1
            total_amt = float(row['After Sale']) if not pd.isna(row['After Sale']) else 0.0
            
            date_val = row['Timestamp']
            if pd.isna(date_val):
                date_val = datetime.utcnow()
            elif isinstance(date_val, str):
                try:
                    date_val = datetime.strptime(date_val, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    try:
                        date_val = datetime.strptime(date_val, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        date_val = datetime.utcnow()
            
            status_info = income_map.get(order_no, {'status': 'Pending', 'payment': 'Pending'})
            
            create_order(
                session=session,
                customer_id=cust_id,
                sku=sku,
                quantity=qty,
                total_amount=total_amt,
                order_status=status_info['status'],
                payment_status=status_info['payment'],
                order_date=date_val,
                order_id=order_no
            )

    # 5. Import Expenses
    if 'Expenses' in xl.sheet_names:
        df_exp = pd.read_excel(file_path, sheet_name='Expenses')
        if 'Day' in df_exp.columns:
            df_exp['Day'] = df_exp['Day'].ffill()
        
        for _, row in df_exp.iterrows():
            item_val = str(row['Item']).strip() if not pd.isna(row['Item']) else ""
            if not item_val:
                continue
            
            amount_val = float(row['Amount']) if not pd.isna(row['Amount']) else 0.0
            wallet_val = str(row['Wallet']).strip() if not pd.isna(row['Wallet']) else ""
            
            date_val = row['Day']
            if pd.isna(date_val):
                date_val = datetime.utcnow()
            elif isinstance(date_val, str):
                try:
                    date_val = datetime.strptime(date_val.split()[0], "%Y-%m-%d")
                except ValueError:
                    date_val = datetime.utcnow()
            elif hasattr(date_val, 'to_pydatetime'):
                date_val = date_val.to_pydatetime()
            
            expense = Expense(
                day=date_val,
                item=item_val,
                wallet=wallet_val,
                amount=amount_val
            )
            session.add(expense)
    
    xl.close()


# --- FINANCIAL & REPORTING LOGIC ---

def get_gross_profit(session: Session) -> float:
    """Calculate gross profit by matching total_amount of Paid orders against product buying prices."""
    results = session.query(Order, Product).join(Product, Order.sku == Product.sku).filter(
        Order.payment_status == 'Paid'
    ).all()
    
    gross_profit = sum(order.total_amount - (product.buying_price * order.quantity) for order, product in results)
    return float(gross_profit)

def get_financial_metrics(session: Session) -> dict:
    """Get high-level dashboard metrics (Total Revenue, Total Profit, Expenses, Net Profit)."""
    # Total Revenue: sum of total_amount of all 'Paid' orders
    paid_orders = session.query(Order).filter(Order.payment_status == 'Paid').all()
    total_revenue = sum(order.total_amount for order in paid_orders)
    total_profit = get_gross_profit(session)
    
    # Expenses: sum of amount of all expenses
    all_expenses = session.query(Expense).all()
    total_expenses = sum(exp.amount for exp in all_expenses)
    net_profit = total_profit - total_expenses
    
    distinct_paid_orders_count = session.query(Order.order_id).filter(Order.payment_status == 'Paid').distinct().count()
    return {
        "total_revenue": float(total_revenue),
        "total_profit": total_profit,
        "total_expenses": float(total_expenses),
        "net_profit": float(net_profit),
        "paid_orders_count": distinct_paid_orders_count
    }

def get_low_stock_products(session: Session, threshold: int = 5) -> list:
    """Retrieve products where initial_quantity is less than the threshold."""
    return session.query(Product).filter(Product.initial_quantity < threshold).all()


def generate_receipt_pdf(session: Session, order_id: int) -> bytes:
    """Generate a styled PDF receipt for a given order_id. Returns PDF as bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from io import BytesIO

    orders = session.query(Order).filter(Order.order_id == order_id).all()
    if not orders:
        raise ValueError(f"Order #{order_id} not found.")

    first_order = orders[0]
    customer = session.query(Customer).filter(Customer.customer_id == first_order.customer_id).first()
    cust_name = customer.customer_name if customer else f"Customer #{first_order.customer_id}"
    cust_phone = customer.customer_phone_number if customer else ""
    cust_address = customer.customer_address if customer else ""

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm
    )

    styles = getSampleStyleSheet()
    brand_blue = colors.HexColor('#1e3a8a')
    accent_blue = colors.HexColor('#2563eb')
    light_bg = colors.HexColor('#f0f6ff')
    dark_bg = colors.HexColor('#1e293b')
    mid_grey = colors.HexColor('#64748b')
    row_alt = colors.HexColor('#f8fafc')

    title_style = ParagraphStyle('Title', fontName='Helvetica-Bold', fontSize=22,
                                  textColor=colors.white, alignment=TA_LEFT, spaceAfter=2)
    subtitle_style = ParagraphStyle('Subtitle', fontName='Helvetica', fontSize=10,
                                     textColor=colors.HexColor('#93c5fd'), alignment=TA_LEFT)
    label_style = ParagraphStyle('Label', fontName='Helvetica-Bold', fontSize=9,
                                  textColor=mid_grey, spaceAfter=1)
    value_style = ParagraphStyle('Value', fontName='Helvetica', fontSize=10,
                                  textColor=dark_bg, spaceAfter=4)
    footer_style = ParagraphStyle('Footer', fontName='Helvetica', fontSize=9,
                                   textColor=mid_grey, alignment=TA_CENTER)

    story = []

    # ── Header banner ──────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("📦 Yaa-يَــــــــاء Core", title_style),
        Paragraph(f"RECEIPT #{order_id:04d}", ParagraphStyle(
            'ReceiptNo', fontName='Helvetica-Bold', fontSize=14,
            textColor=colors.white, alignment=TA_RIGHT))
    ]]
    header_table = Table(header_data, colWidths=[100 * mm, 70 * mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), dark_bg),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (0, -1), 14),
        ('RIGHTPADDING', (-1, 0), (-1, -1), 14),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    # ── Order meta + Customer info side by side ────────────────────────────────
    date_str = first_order.order_date.strftime('%d %b %Y  %H:%M')
    meta_data = [
        [Paragraph('ORDER DATE', label_style), Paragraph('CUSTOMER', label_style)],
        [Paragraph(date_str, value_style), Paragraph(cust_name, value_style)],
        [Paragraph('FULFILLMENT STATUS', label_style), Paragraph('PHONE', label_style)],
        [Paragraph(first_order.order_status, value_style), Paragraph(cust_phone, value_style)],
        [Paragraph('PAYMENT STATUS', label_style), Paragraph('ADDRESS', label_style)],
        [Paragraph(first_order.payment_status, value_style), Paragraph(cust_address or '—', value_style)],
    ]
    meta_table = Table(meta_data, colWidths=[85 * mm, 85 * mm])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#bfdbfe')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6 * mm))

    # ── Items table ────────────────────────────────────────────────────────────
    th_style = ParagraphStyle('TH', fontName='Helvetica-Bold', fontSize=9,
                               textColor=colors.white, alignment=TA_CENTER)
    td_style = ParagraphStyle('TD', fontName='Helvetica', fontSize=9,
                               textColor=dark_bg, alignment=TA_CENTER)
    td_left = ParagraphStyle('TDL', fontName='Helvetica', fontSize=9,
                              textColor=dark_bg, alignment=TA_LEFT)

    items_data = [[
        Paragraph('SKU', th_style),
        Paragraph('Item Name', th_style),
        Paragraph('Arabic Name', th_style),
        Paragraph('Qty', th_style),
        Paragraph('Unit Price', th_style),
        Paragraph('Total (EGP)', th_style),
    ]]

    grand_total = 0.0
    for idx, o in enumerate(orders):
        product = session.query(Product).filter(Product.sku == o.sku).first()
        item_name_en = product.item_name if product else o.sku
        item_name_ar = product.item_name_arabic if product else ''
        unit_price = (o.total_amount / o.quantity) if o.quantity else 0.0
        row_bg = colors.white if idx % 2 == 0 else row_alt
        items_data.append([
            Paragraph(o.sku, td_style),
            Paragraph(item_name_en, td_left),
            Paragraph(item_name_ar, td_style),
            Paragraph(str(o.quantity), td_style),
            Paragraph(f"{unit_price:,.2f}", td_style),
            Paragraph(f"{o.total_amount:,.2f}", td_style),
        ])
        grand_total += o.total_amount

    col_w = [25 * mm, 45 * mm, 40 * mm, 15 * mm, 27 * mm, 27 * mm]
    items_table = Table(items_data, colWidths=col_w)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), accent_blue),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, row_alt]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # ── Grand total row ────────────────────────────────────────────────────────
    total_data = [['', '', '', '', 'GRAND TOTAL',
                   Paragraph(f"EGP {grand_total:,.2f}", ParagraphStyle(
                       'Total', fontName='Helvetica-Bold', fontSize=11,
                       textColor=accent_blue, alignment=TA_CENTER))]]
    total_table = Table(total_data, colWidths=col_w)
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), light_bg),
        ('BOX', (0, 0), (-1, -1), 1, accent_blue),
        ('FONTNAME', (4, 0), (4, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (4, 0), (4, 0), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (4, 0), (4, 0), 'RIGHT'),
        ('ALIGN', (5, 0), (5, 0), 'CENTER'),
    ]))
    story.append(total_table)
    story.append(Spacer(1, 10 * mm))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Thank you for your business! · Yaa-يَــــــــاء Core Inventory System", footer_style))
    story.append(Paragraph(f"Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC", footer_style))

    doc.build(story)
    return buffer.getvalue()

def sync_google_sheet(session: Session, url: str) -> bool:
    """Download the Google Sheet as .xlsx and import it into the SQLite database."""
    import urllib.request
    import os
    try:
        import time
        if "/edit" in url:
            export_url = url.split("/edit")[0] + "/export?format=xlsx"
        else:
            export_url = url
            
        connector = "&" if "?" in export_url else "?"
        export_url = f"{export_url}{connector}cachebust={int(time.time())}"
            
        temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_sheet_temp.xlsx")
        # Ensure we set a reasonable User-Agent just in case
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)
        
        urllib.request.urlretrieve(export_url, temp_path)
        import_excel_data(session, temp_path, clear_db=True)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return True
    except Exception as e:
        import logging
        logging.error(f"Error syncing Google Sheet: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        raise e

def export_to_google_sheet(session: Session, url: str) -> bool:
    """Export all SQLite tables to the Google Sheet via the Apps Script Web App URL."""
    import urllib.request
    import json
    
    try:
        products = session.query(Product).all()
        customers = session.query(Customer).all()
        orders = session.query(Order).all()
        expenses = session.query(Expense).all()
        settlements = session.query(DebtSettlement).all()
        logs = session.query(ActionLog).all()
        
        data = {
            "Products": [
                {
                    "SKU": p.sku,
                    "Item Name": p.item_name,
                    "Item Name Arabic": p.item_name_arabic or "",
                    "Initial Quantity": p.initial_quantity,
                    "Buying Price": p.buying_price,
                    "Selling Price": p.selling_price,
                    "Supplier": p.supplier or ""
                } for p in products
            ],
            "Customers": [
                {
                    "Customer ID": c.customer_id,
                    "Customer Phone Number": c.customer_phone_number,
                    "Customer Name": c.customer_name,
                    "Customer Address": c.customer_address or ""
                } for c in customers
            ],
            "Orders": [
                {
                    "Order ID": o.order_id,
                    "Customer ID": o.customer_id,
                    "SKU": o.sku,
                    "Quantity": o.quantity,
                    "Total Amount": o.total_amount,
                    "Order Status": o.order_status,
                    "Payment Status": o.payment_status,
                    "Order Date": o.order_date.strftime("%Y-%m-%d %H:%M:%S")
                } for o in orders
            ],
            "Expenses": [
                {
                    "Expense ID": e.expense_id,
                    "Day": e.day.strftime("%Y-%m-%d") if e.day else "",
                    "Item": e.item,
                    "Wallet": e.wallet or "",
                    "Amount": e.amount
                } for e in expenses
            ],
            "DebtSettlements": [
                {
                    "Settlement ID": s.settlement_id,
                    "Amount": s.amount,
                    "Date": s.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Notes": s.notes or ""
                } for s in settlements
            ],
            "ActionLogs": [
                {
                    "Log ID": l.log_id,
                    "Username": l.username,
                    "Action": l.action,
                    "Timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "Details": l.details or ""
                } for l in logs
            ]
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            return res_data.get("status") == "success"
    except Exception as e:
        import logging
        logging.error(f"Error exporting to Google Sheet: {e}")
        return False


def get_wallet_balance(session: Session) -> dict:
    """Calculate expenses per wallet and the net debt outstanding between Shabasi (شباسي) and Hejazi (حجازي)."""
    all_expenses = session.query(Expense).all()
    shabasi_total = 0.0
    hejazi_total = 0.0
    for e in all_expenses:
        w = e.wallet.strip() if e.wallet else ""
        if "شباسي" in w:
            shabasi_total += e.amount
        elif "حجازي" in w:
            hejazi_total += e.amount
            
    all_settlements = session.query(DebtSettlement).all()
    total_settlements = sum(s.amount for s in all_settlements)
    
    return {
        "shabasi_total": shabasi_total,
        "hejazi_total": hejazi_total,
        "total_settlements": total_settlements
    }

def check_google_sheet_updates(session: Session, url: str) -> bool:
    """Download the Google Sheet and check if it differs from the last imported sheet.
    If it differs, import it and return True. Otherwise return False."""
    import urllib.request
    import hashlib
    import os
    import time
    
    try:
        if "/edit" in url:
            export_url = url.split("/edit")[0] + "/export?format=xlsx"
        else:
            export_url = url
            
        connector = "&" if "?" in export_url else "?"
        export_url = f"{export_url}{connector}cachebust={int(time.time())}"
        
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)
        
        data = urllib.request.urlopen(export_url).read()
        current_hash = hashlib.md5(data).hexdigest()
        
        hash_file = "last_gsheet_hash.txt"
        last_hash = ""
        if os.path.exists(hash_file):
            with open(hash_file, "r") as f:
                last_hash = f.read().strip()
                
        if current_hash != last_hash:
            with open(hash_file, "w") as f:
                f.write(current_hash)
            
            temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_sheet_temp.xlsx")
            with open(temp_path, "wb") as f:
                f.write(data)
                
            import_excel_data(session, temp_path, clear_db=True)
            
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return True
        return False
    except Exception as e:
        import logging
        logging.error(f"Error checking Google Sheet updates: {e}")
        return False



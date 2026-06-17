from database import init_db, get_session
import logic
import os
from models import Product, Customer, Order, StockLedger

init_db()
excel_path = r"C:\Users\Family\Downloads\Yaa.xlsx"

print(f"Verifying existence of Excel file: {os.path.exists(excel_path)}")

with get_session() as session:
    print("\nExecuting Excel Import...")
    logic.import_excel_data(session, excel_path, clear_db=True)
    session.commit()
    print("Import complete!")
    
    prod_count = session.query(Product).count()
    cust_count = session.query(Customer).count()
    order_count = session.query(Order).count()
    ledger_count = session.query(StockLedger).count()
    
    print(f"Products in DB: {prod_count} (Expected: 20)")
    print(f"Customers in DB: {cust_count} (Expected: 4)")
    print(f"Order Items in DB: {order_count} (Expected: 12)")
    print(f"Ledger Entries in DB: {ledger_count}")
    
    assert prod_count == 20
    assert cust_count == 4
    assert order_count == 12
    
    print("\nSample imported order items:")
    orders = session.query(Order).order_by(Order.order_id, Order.order_item_id).all()
    for o in orders:
        print(f"  Parent Order #{o.order_id} | Item ID {o.order_item_id} | SKU: {o.sku} | Qty: {o.quantity} | Total: ${o.total_amount:.2f} | Status: {o.order_status} | Payment: {o.payment_status}")
        
    metrics = logic.get_financial_metrics(session)
    print(f"\nCalculated Financial Metrics: {metrics}")
    
print("\nEXCEL IMPORT VERIFICATION PASSED SUCCESSFULLY!")

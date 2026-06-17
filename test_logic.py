import os
from database import init_db, get_session
from models import Base, Product, Customer, Order, StockLedger
import logic

def run_tests():
    print("Initializing Database...")
    init_db()
    
    with get_session() as session:
        # Clean up database to run tests cleanly
        print("Cleaning old data...")
        session.query(StockLedger).delete()
        session.query(Order).delete()
        session.query(Customer).delete()
        session.query(Product).delete()
        session.commit()
        
        # 1. Add Test Product
        print("\n--- Test 1: Add Product ---")
        sku = "TEST-SKU-1"
        product = logic.add_product(
            session=session,
            sku=sku,
            item_name="Test Item 1",
            item_name_arabic="عنصر اختبار ١",
            initial_quantity=10,
            buying_price=50.0,
            selling_price=80.0,
            supplier="Test Supplier"
        )
        print(f"Added Product: {product.item_name} (SKU: {product.sku}), Qty: {product.initial_quantity}")
        assert product.initial_quantity == 10
        
        # Verify ledger has the initial stock setup
        ledger_count = session.query(StockLedger).filter(StockLedger.sku == sku).count()
        assert ledger_count == 1
        ledger_entry = session.query(StockLedger).filter(StockLedger.sku == sku).first()
        print(f"Ledger entry created: Qty Change={ledger_entry.quantity_change}, Reason='{ledger_entry.reason}'")
        assert ledger_entry.quantity_change == 10
        
        # 2. Add Test Customer
        print("\n--- Test 2: Add Customer ---")
        customer = logic.add_customer(
            session=session,
            customer_name="John Doe",
            customer_phone_number="1234567890",
            customer_address="123 Main St"
        )
        print(f"Added Customer: {customer.customer_name} (Phone: {customer.customer_phone_number})")
        assert customer.customer_name == "John Doe"
        
        # 3. Create Pending Order
        print("\n--- Test 3: Create Order (Pending) ---")
        # Ordered quantity: 2
        order = logic.create_order(
            session=session,
            customer_id=customer.customer_id,
            sku=sku,
            quantity=2,
            total_amount=160.0,  # 2 * 80.0
            order_status="Pending",
            payment_status="Pending"
        )
        print(f"Created Order #{order.order_id}: Status={order.order_status}, Qty={order.quantity}")
        
        # Stock should not be deducted yet
        product_ref = session.query(Product).filter(Product.sku == sku).first()
        print(f"Current Stock (Should be 10): {product_ref.initial_quantity}")
        assert product_ref.initial_quantity == 10
        
        # 4. Update Order Status to Delivered
        print("\n--- Test 4: Update Order to Delivered (Stock Deduction Trigger) ---")
        logic.update_order_status(session, order.order_id, "Delivered")
        
        # Stock should be deducted: 10 - 2 = 8
        product_ref = session.query(Product).filter(Product.sku == sku).first()
        print(f"Current Stock (Should be 8): {product_ref.initial_quantity}")
        assert product_ref.initial_quantity == 8
        
        # Ledger should have the deduction entry
        ledger_entries = session.query(StockLedger).filter(StockLedger.sku == sku).all()
        print(f"Total ledger entries for {sku}: {len(ledger_entries)}")
        assert len(ledger_entries) == 2
        deduction_entry = [le for le in ledger_entries if le.quantity_change == -2][0]
        print(f"Deduction entry found: Qty Change={deduction_entry.quantity_change}, Reason='{deduction_entry.reason}'")
        assert deduction_entry.reason == f"Order Fulfillment - Order #{order.order_id} Item #{order.order_item_id}"

        # 5. Check Gross Profit (Order is Pending Payment, Profit should be 0)
        print("\n--- Test 5: Verify Profit (Order Payment Pending) ---")
        profit = logic.get_gross_profit(session)
        print(f"Gross Profit (Should be 0.0): {profit}")
        assert profit == 0.0
        
        # 6. Update Payment Status to Paid
        print("\n--- Test 6: Update Payment to Paid & Recalculate Profit ---")
        logic.update_payment_status(session, order.order_id, "Paid")
        profit = logic.get_gross_profit(session)
        # Expected profit: 160.0 - (50.0 * 2) = 60.0
        print(f"Gross Profit (Should be 60.0): {profit}")
        assert profit == 60.0
        
        # Check overall metrics
        metrics = logic.get_financial_metrics(session)
        print(f"Financial Metrics: {metrics}")
        assert metrics["total_revenue"] == 160.0
        assert metrics["total_profit"] == 60.0
        assert metrics["paid_orders_count"] == 1
        
        # 7. Low Stock Warnings
        print("\n--- Test 7: Low Stock Warning Trigger ---")
        # Let's change initial_quantity to 4 to trigger warning
        product_ref.initial_quantity = 4
        session.commit()
        
        low_stock = logic.get_low_stock_products(session)
        print(f"Low Stock Products (Should contain TEST-SKU-1): {[p.sku for p in low_stock]}")
        assert len(low_stock) == 1
        assert low_stock[0].sku == sku

    print("\nALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()

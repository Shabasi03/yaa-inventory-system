from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    
    product_id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(50), unique=True, index=True, nullable=False)
    item_name = Column(String(100), nullable=False)
    item_name_arabic = Column(String(100))
    initial_quantity = Column(Integer, default=0, nullable=False)
    buying_price = Column(Float, default=0.0, nullable=False)
    selling_price = Column(Float, default=0.0, nullable=False)
    supplier = Column(String(100))
    
    orders = relationship("Order", back_populates="product")
    ledger_entries = relationship("StockLedger", back_populates="product")

class Customer(Base):
    __tablename__ = 'customers'
    
    customer_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_phone_number = Column(String(20), unique=True, nullable=False)
    customer_name = Column(String(100), nullable=False)
    customer_address = Column(String(200))
    
    orders = relationship("Order", back_populates="customer")

class Order(Base):
    __tablename__ = 'orders'
    
    order_item_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'), nullable=False)
    sku = Column(String(50), ForeignKey('products.sku'), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    total_amount = Column(Float, nullable=False)
    order_status = Column(String(20), default='Pending', nullable=False)  # Allowed: 'Pending', 'Confirmed', 'Dispatched', 'Delivered'
    payment_status = Column(String(20), default='Pending', nullable=False)  # Allowed: 'Pending', 'Paid', 'Failed'
    order_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    customer = relationship("Customer", back_populates="orders")
    product = relationship("Product", back_populates="orders")

class StockLedger(Base):
    __tablename__ = 'stock_ledger'
    
    ledger_id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(50), ForeignKey('products.sku'), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    reason = Column(String(200), nullable=False)
    
    product = relationship("Product", back_populates="ledger_entries")

class Expense(Base):
    __tablename__ = 'expenses'
    
    expense_id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(DateTime)
    item = Column(String(200), nullable=False)
    wallet = Column(String(100))
    amount = Column(Float, nullable=False)

class DebtSettlement(Base):
    __tablename__ = 'debt_settlements'
    
    settlement_id = Column(Integer, primary_key=True, autoincrement=True)
    amount = Column(Float, nullable=False)
    date = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(String(200))

class ActionLog(Base):
    __tablename__ = 'action_logs'
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    details = Column(String(500))


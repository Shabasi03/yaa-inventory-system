from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from models import Base
import os

# Store DB in the same directory as database.py
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=True, bind=engine)

def init_db():
    """Create database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_session():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

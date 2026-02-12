from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
import pytest

# Importiere deine Models und das Base-Objekt
from database import Base

DATABASE_URL = "sqlite:///./qr_ouhud.db"

def test_database_connection():
    """Überprüft, ob eine Verbindung zur Datenbank besteht."""
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
            print("✅ Datenbankverbindung erfolgreich.")
    except OperationalError as e:
        pytest.fail(f"❌ Datenbankverbindung fehlgeschlagen: {e}")

def test_required_tables_exist():
    """Prüft, ob alle erforderlichen Tabellen existieren und legt sie an, falls nicht."""
    db_engine = create_engine(DATABASE_URL)
    # Erstelle fehlende Tabellen automatisch
    Base.metadata.create_all(db_engine)

    insp = inspect(db_engine)
    tables = insp.get_table_names()

    required = ["users", "qr_codes"] # ggf. anpassen an deine echten Models
    missing = [t for t in required if t not in tables]

    if missing:
        print(f"⚠️ Erstelle fehlende Tabellen: {missing}")
        Base.metadata.create_all(db_engine)

    insp = inspect(db_engine)
    tables = insp.get_table_names()
    missing = [t for t in required if t not in tables]
    assert not missing, f"❌ Fehlende Tabellen: {missing}"

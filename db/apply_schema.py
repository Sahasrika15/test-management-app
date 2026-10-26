from pathlib import Path

from sqlalchemy import text

from db.connection import get_engine

SCHEMA = Path(__file__).with_name("schema.sql")

if __name__ == "__main__":
    sql = SCHEMA.read_text(encoding="utf-8")
    with get_engine().begin() as conn:
        conn.execute(text(sql))
    with get_engine().connect() as conn:
        names = conn.execute(text(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by table_name"
        )).scalars().all()
    print("Schema applied. Tables now:")
    for name in names:
        print("  " + name)
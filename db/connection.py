import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def get_engine():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


if __name__ == "__main__":
    with get_engine().connect() as conn:
        row = conn.execute(text("select current_user, current_database()")).fetchone()
        print(row)
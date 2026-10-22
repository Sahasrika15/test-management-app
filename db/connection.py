import datetime
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text

load_dotenv()

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.environ["DATABASE_URL"]
        # Normalize driver prefix for SQLAlchemy compatibility
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://") :]
        elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]

        _engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=15,
            pool_recycle=300,
            pool_pre_ping=False,
            pool_use_lifo=True,
        )

        # ── DB request logger (lightweight, zero-cost frame walk) ───────────────
        if os.environ.get("VERITY_LOG_QUERIES", "1") == "1":
            @event.listens_for(_engine, "before_cursor_execute")
            def _log_query(conn, cursor, statement, parameters, context, executemany):
                caller = "unknown"
                frame = sys._getframe(1)
                while frame:
                    fn = frame.f_code.co_filename
                    if (
                        "sqlalchemy" not in fn
                        and "db/connection" not in fn
                        and "db\\connection" not in fn
                        and fn.endswith(".py")
                    ):
                        try:
                            rel = os.path.relpath(fn)
                        except ValueError:
                            rel = fn
                        caller = f"{rel}:{frame.f_lineno} in {frame.f_code.co_name}()"
                        break
                    frame = frame.f_back

                ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                preview = " ".join(statement.split())[:120]
                print(
                    f"\033[36m[DB]\033[0m {ts}  \033[33m{caller}\033[0m\n"
                    f"     \033[2m{preview}{'…' if len(preview) == 120 else ''}\033[0m",
                    flush=True,
                )

    return _engine


if __name__ == "__main__":
    with get_engine().connect() as conn:
        row = conn.execute(text("select current_user, current_database()")).fetchone()
        print(row)
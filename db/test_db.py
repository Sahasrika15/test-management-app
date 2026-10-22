"""Database Connection Verification Script for Neon / PostgreSQL.

Usage:
    python test_db.py
    python test_db.py "postgresql://user:pass@ep-xyz.neon.tech/dbname?sslmode=require"
"""

import os
import re
import socket
import sys
import time
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url

# Load environment variables
load_dotenv()


def mask_url(raw_url: str) -> str:
    """Mask the password in a database connection string for safe printing."""
    try:
        parsed = make_url(raw_url)
        return parsed.render_as_string(hide_password=True)
    except Exception:
        # Fallback regex masking if URL format isn't standard SQLAlchemy
        return re.sub(r":([^:@]+)@", r":****@", raw_url)


def normalize_neon_url(raw_url: str) -> tuple[str, list[str]]:
    """Validate and normalize Neon connection string, returning notes/warnings."""
    warnings = []
    url = raw_url.strip()

    # Neon dashboards often provide 'postgres://' which SQLAlchemy 2+ rejects
    if url.startswith("postgres://"):
        warnings.append(
            "URL starts with 'postgres://'. Converting prefix to 'postgresql+psycopg://' for SQLAlchemy compatibility."
        )
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        # Explicit psycopg dialect is safer with psycopg v3
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    # Neon requires SSL
    if "sslmode=" not in url:
        warnings.append(
            "Missing 'sslmode=require' in connection string. Neon requires encrypted connections."
        )
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"

    return url, warnings


def test_socket_connectivity(host: str, port: int, timeout: float = 6.0) -> tuple[bool, float, str]:
    """Test raw TCP connection to Neon host:port to isolate network/firewall issues."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            duration = (time.perf_counter() - start) * 1000
            return True, duration, "OK"
    except socket.gaierror:
        return False, 0.0, f"DNS resolution failed for host '{host}'"
    except socket.timeout:
        return False, 0.0, f"Connection timed out after {timeout}s (Neon compute may be waking up or port {port} blocked)"
    except Exception as e:
        return False, 0.0, str(e)


def run_checks(raw_url: str) -> bool:
    print("=" * 65)
    print("        NEON / POSTGRESQL CONNECTION DIAGNOSTIC")
    print("=" * 65)

    if not raw_url:
        print("\n[ERROR] No DATABASE_URL found!")
        print("Please set DATABASE_URL in your .env file or pass it as an argument:")
        print("  python test_db.py <your_neon_database_url>")
        return False

    db_url, warnings = normalize_neon_url(raw_url)

    # 1. Inspect URL components
    print("\n1. Configuration:")
    print(f"   Safe URL:       {mask_url(db_url)}")

    try:
        parsed = make_url(db_url)
        host = parsed.host or "localhost"
        port = parsed.port or 5432
        dbname = parsed.database or ""
        username = parsed.username or ""
        drivername = parsed.drivername

        print(f"   Driver:         {drivername}")
        print(f"   Host:           {host}")
        print(f"   Port:           {port}")
        print(f"   Database:       {dbname}")
        print(f"   User:           {username}")

        # Check for Neon endpoint format
        is_neon = "neon.tech" in host
        is_pooler = "-pooler" in host
        print(f"   Provider:       {'Neon Cloud Postgres' if is_neon else 'Generic Postgres'}")
        if is_neon:
            print(f"   Endpoint Type:  {'Connection Pooler (PgBouncer)' if is_pooler else 'Direct Compute'}")
    except Exception as e:
        print(f"   [WARN] Could not parse URL components: {e}")
        host, port = "localhost", 5432

    if warnings:
        print("\n   Notices / Adjustments:")
        for w in warnings:
            print(f"   * {w}")

    # 2. Network Reachability
    print("\n2. Network Reachability (TCP Socket):")
    if host:
        print(f"   Testing connection to {host}:{port} ...", end=" ", flush=True)
        ok, latency, msg = test_socket_connectivity(host, port)
        if ok:
            print(f"[SUCCESS] (Ping: {latency:.1f}ms)")
        else:
            print(f"[FAILED]\n   Reason: {msg}")
            print("\n   Troubleshooting:")
            print("   - Check if your internet connection is active.")
            print("   - Verify that your corporate network or firewall allows outbound port 5432.")
            print("   - If your Neon project was suspended, Neon will auto-resume on first query, but DNS must resolve.")
            return False

    # 3. SQLAlchemy Connection & Server Verification
    print("\n3. Database Authentication & Query Execution:")
    print("   Connecting via SQLAlchemy engine ...", end=" ", flush=True)

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        t_start = time.perf_counter()
        with engine.connect() as conn:
            query_time = (time.perf_counter() - t_start) * 1000
            print(f"[SUCCESS] (Connect time: {query_time:.1f}ms)")

            # Check database version
            pg_version = conn.execute(text("SELECT version();")).scalar()
            current_db, current_user = conn.execute(
                text("SELECT current_database(), current_user;")
            ).fetchone()
            server_time = conn.execute(text("SELECT NOW();")).scalar()

            print(f"\n   Connected Database: {current_db}")
            print(f"   Connected User:     {current_user}")
            print(f"   Server Time:        {server_time}")
            print(f"   Postgres Version:   {pg_version.split(',')[0] if pg_version else 'Unknown'}")

            # 4. Read / Write permissions check
            print("\n4. Permission Check (Read & Temporary Transaction):")
            conn.execute(text("CREATE TEMP TABLE __conn_test_tmp (id serial primary key, val text);"))
            conn.execute(text("INSERT INTO __conn_test_tmp (val) VALUES ('neon_ok');"))
            test_val = conn.execute(text("SELECT val FROM __conn_test_tmp;")).scalar()
            conn.execute(text("DROP TABLE __conn_test_tmp;"))
            if test_val == "neon_ok":
                print("   [SUCCESS] Full read/write and temporary table creation verified.")

            # 5. Schema & Existing Tables
            print("\n5. Application Tables & Migration Status:")
            inspector = inspect(conn)
            tables = inspector.get_table_names(schema="public")

            if tables:
                print(f"   Found {len(tables)} table(s) in schema 'public':")
                for t in sorted(tables):
                    print(f"     - {t}")

                if "alembic_version" in tables:
                    rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
                    print(f"\n   Alembic Revision:   {rev or 'No revision applied'}")
                else:
                    print("\n   [INFO] 'alembic_version' table not found.")
                    print("   If this is a fresh database, run migrations:")
                    print("     python -m alembic upgrade head")
            else:
                print("   [INFO] Database is currently empty (0 tables found).")
                print("   To initialize your tables and schemas, run:")
                print("     python -m alembic upgrade head")

        print("\n" + "=" * 65)
        print("          ALL CHECKS PASSED: Neon DB is ready to use!")
        print("=" * 65 + "\n")
        return True

    except Exception as e:
        print("[FAILED]")
        print("\n[ERROR] Could not connect to database:")
        print(f"  {type(e).__name__}: {e}")

        err_str = str(e).lower()
        print("\nTroubleshooting Tips for Neon:")
        if "password authentication failed" in err_str:
            print("  - Check your username and password in the connection string.")
            print("  - If your password contains special characters like '@', '#', '%', ensure they are URL-encoded.")
        elif "no pg_hba.conf entry" in err_str or "ssl" in err_str:
            print("  - Neon requires SSL. Append '?sslmode=require' to your DATABASE_URL.")
        elif "database" in err_str and "does not exist" in err_str:
            print("  - The target database name does not exist. The default Neon DB is often 'neondb'.")
        elif "nosuchmoduleerror" in err_str or "postgres" in err_str:
            print("  - Change URL scheme from 'postgres://' to 'postgresql+psycopg://'.")
        elif "compute" in err_str or "endpoint" in err_str:
            print("  - Check your Neon console to make sure your compute endpoint is active and not disabled.")

        print("\n" + "=" * 65 + "\n")
        return False


def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = os.getenv("DATABASE_URL", "")
    success = run_checks(url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

import psycopg

conn = psycopg.connect(
    host="localhost",
    port=5432,
    user="testmgr",
    password="Test@123",
    dbname="test_management",
)
rows = conn.execute(
    "select table_name from information_schema.tables where table_schema = 'public'"
).fetchall()
for (name,) in rows:
    print(name)
conn.close()
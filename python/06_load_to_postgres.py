"""
06_load_to_postgres.py
Loads the CSV files from the data/ folder into the PostgreSQL tables (database fraud_project).
Requires: pip install "psycopg[binary]"  and the tables from sql/00_create_tables.sql
Run from the project root: python python/06_load_to_postgres.py

The script can be run many times: it empties the tables (TRUNCATE) before loading.
data/fact_customer_risk.csv (from 07_generate_customer_history.py) is loaded only if it exists.
You type the PostgreSQL password in the terminal (it is not stored in the file).
"""
import csv
import getpass
from pathlib import Path

import psycopg

DB = {"host": "localhost", "port": 5432, "dbname": "fraud_project", "user": "postgres"}

data_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data

# Order matters (foreign keys): dimensions first, transactions last
TABLES = [
    ("dim_customer", "dim_customer.csv"),
    ("dim_merchant", "dim_merchant.csv"),
    ("dim_device", "dim_device.csv"),
    ("dim_fx_rate", "dim_fx_rate.csv"),
    ("fact_transaction", "fact_transaction.csv"),
    ("fact_customer_risk", "fact_customer_risk.csv"),   # optional, created by 07
]

password = getpass.getpass("Password for user postgres: ")

with psycopg.connect(**DB, password=password) as conn:
    with conn.cursor() as cur:
        # Empty the tables so that a re-run does not duplicate data
        cur.execute("TRUNCATE fact_transaction, fact_customer_risk, dim_device, dim_fx_rate, "
                    "dim_merchant, dim_customer")

        for table, file in TABLES:
            path = data_dir / file
            if not path.exists():
                print(f"Skipped {file} (file not found)")
                continue
            with open(path, newline="", encoding="utf-8") as f:
                columns = next(csv.reader(f))                # CSV header = column names
            col_list = ", ".join(columns)
            with open(path, "rb") as f, cur.copy(
                f"COPY {table} ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                while chunk := f.read(1024 * 1024):
                    copy.write(chunk)
            print(f"Loaded {file} -> {table}")

    # Check: row count in each table
    print("\nRow counts in the database:")
    for table, _ in TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<18} {n:>9,}")

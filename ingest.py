"""Load the rankings CSV into DuckDB and drop columns that are entirely empty."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "data" / "cit_national_ranks_cat30_dept2_3m.csv"
DB_PATH = ROOT / "data" / "products.duckdb"


def main():
    con = duckdb.connect(str(DB_PATH))
    con.execute(
        "CREATE OR REPLACE TABLE products AS SELECT * FROM read_csv_auto(?)",
        [str(CSV_PATH)],
    )

    columns = [row[0] for row in con.execute("DESCRIBE products").fetchall()]
    # A column is empty when every cell is NULL or a blank string.
    filled_sql = ", ".join(
        f"""COUNT(NULLIF(TRIM(CAST("{col}" AS VARCHAR)), '')) AS "{col}\""""
        for col in columns
    )
    filled_counts = con.execute(f"SELECT {filled_sql} FROM products").fetchone()
    empty_columns = [col for col, n in zip(columns, filled_counts) if n == 0]

    for col in empty_columns:
        con.execute(f'ALTER TABLE products DROP COLUMN "{col}"')

    row_count = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    kept = [row[0] for row in con.execute("DESCRIBE products").fetchall()]
    print(f"Dropped empty columns: {empty_columns or 'none'}")
    print(f"Saved products ({row_count} rows, {len(kept)} columns) to {DB_PATH.name}")
    con.close()


if __name__ == "__main__":
    main()

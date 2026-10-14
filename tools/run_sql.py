"""Run one read-only SELECT against products and return the rows."""

from pathlib import Path
import re

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "products.duckdb"
MAX_ROWS = 50

BLOCKED = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "copy",
    "attach",
    "detach",
    "export",
    "pragma",
    "install",
    "load",
    "call",
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
)


def run_sql(sql: str) -> str:
    """Execute one SELECT and return at most 50 rows as text."""
    cleaned = "" if sql is None else str(sql).strip().rstrip(";").strip()
    if not cleaned:
        return "No SQL was provided."

    problem = _guard(cleaned)
    if problem:
        return problem

    limited, cap, peek = _cap_rows(cleaned)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cursor = con.execute(limited)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    except duckdb.Error as exc:
        return f"The query failed: {exc}"
    finally:
        con.close()

    if not rows:
        return "No rows matched."

    extra = peek and len(rows) > cap
    visible = rows[:cap]
    lines = [" | ".join(columns)]
    for row in visible:
        lines.append(" | ".join("" if cell is None else str(cell) for cell in row))
    footer = f"{len(visible)} rows."
    if extra:
        footer += " More rows matched. Add a tighter filter."
    return footer + "\n" + "\n".join(lines)


def _guard(sql: str) -> str | None:
    if ";" in sql:
        return "Send one statement only."

    stripped = re.sub(r"'(?:''|[^'])*'", "''", sql)
    if not re.match(r"(?is)\s*(select|with)\b", stripped):
        return "Only a SELECT is allowed."

    blocked = next(
        (word for word in BLOCKED if re.search(rf"(?i)\b{word}\b", stripped)),
        None,
    )
    if blocked:
        return f"{blocked.upper()} is not allowed. Use a SELECT on products."

    cte_names = {
        name.casefold()
        for name in re.findall(r"(?i)(?:\bwith|,)\s*([a-zA-Z_]\w*)\s+as\s*\(", stripped)
    }
    refs = re.findall(r"(?i)\b(?:from|join)\s+([a-zA-Z_]\w*)", stripped)
    if not refs:
        return "The query must read FROM products."
    foreign = [name for name in refs if name.casefold() not in cte_names | {"products"}]
    if foreign:
        return f"Only the products table can be queried. Not {foreign[0]}."
    return None


def _cap_rows(sql: str) -> tuple[str, int, bool]:
    """Return SQL, how many rows to show, and whether to look for one extra row."""
    match = re.search(r"(?i)\blimit\s+(\d+)\s*$", sql)
    if not match:
        return f"{sql}\nLIMIT {MAX_ROWS + 1}", MAX_ROWS, True
    asked = int(match.group(1))
    if asked <= MAX_ROWS:
        return sql, asked, False
    return sql[: match.start()] + f"LIMIT {MAX_ROWS + 1}", MAX_ROWS, True

"""Look up the stored spelling for a value the model wants to filter on."""

from pathlib import Path
import re

import duckdb
import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "products.duckdb"
DICTIONARY_PATH = ROOT / "prompt" / "data_dictionary.yaml"

# Searched only when the column the model named has no match.
LOOKUP_COLUMNS = ("brand", "color", "product_color", "product_name", "rank_label")
MEASURE_COLUMNS = {
    "rank_absolute",
    "rank_percentile",
    "niche_score",
    "popularity",
    "discount",
    "rating",
    "rating_count",
    "review_count",
    "mrp_USD",
    "mrp_INR",
    "selling_price_USD",
    "selling_price_INR",
}
LIMIT = 15
FUZZY_MIN = 0.84
FUZZY_GAP = 0.05
NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "INT", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
    "FLOAT", "REAL", "DOUBLE", "DECIMAL", "NUMERIC",
}


def _load_cache() -> tuple[dict[str, str], dict[str, list[str]], dict[str, tuple]]:
    """Read distinct lookup values once, so later calls do not rescan the table."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        types = {
            row[0]: row[1]
            for row in con.execute("DESCRIBE products").fetchall()
        }
        values = {
            name: _distinct(con, name)
            for name in LOOKUP_COLUMNS
            if name in types
        }
        ranges = {}
        for name, kind in types.items():
            if _is_number(kind) or _is_temporal(kind):
                quoted = '"' + name.replace('"', '""') + '"'
                ranges[name] = con.execute(
                    f"SELECT MIN({quoted}), MAX({quoted}) FROM products"
                ).fetchone()
        return types, values, ranges
    finally:
        con.close()


def get_values(column: str, value: str) -> str:
    """Return stored values for the column the model named.

    The column must exist. Other lookup columns are searched only when
    that column has no match.
    """
    needle = "" if value is None else str(value).strip()
    if not needle:
        return "No value to look up."

    asked = _real_column(column, COLUMN_TYPES)
    if asked is None:
        names = ", ".join(COLUMN_TYPES)
        return f"There is no column '{column}'. Columns are: {names}."

    kind = COLUMN_TYPES[asked]
    if _is_number(kind):
        return _number_lookup(asked, needle)
    if _is_temporal(kind):
        return _date_lookup(asked, needle)
    return _text_lookup(asked, needle)


def _type_base(kind: str) -> str:
    return kind.upper().split("(", 1)[0].strip()


def _is_number(kind: str) -> bool:
    return _type_base(kind) in NUMERIC_TYPES


def _is_temporal(kind: str) -> bool:
    base = _type_base(kind)
    return base == "DATE" or base.startswith("TIMESTAMP") or base == "DATETIME"


def _real_column(column: str, types: dict[str, str]) -> str | None:
    if column in types:
        return column
    folded = {name.casefold(): name for name in types}
    return folded.get(str(column).strip().casefold())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _word_match(stored: str, query_tokens: list[str]) -> bool:
    # Whole words only, so "zara" does not match "Izara".
    stored_tokens = set(_tokens(stored))
    return all(token in stored_tokens for token in query_tokens)


def _text_hits(stored_values: list[str], needle: str) -> list[str]:
    """Exact matches first, then values that contain every query word."""
    folded = needle.casefold()
    query_tokens = _tokens(needle)
    exact = [stored for stored in stored_values if stored.casefold() == folded]
    if exact:
        return exact
    if not query_tokens:
        return []
    words = [stored for stored in stored_values if _word_match(stored, query_tokens)]
    words.sort(key=lambda stored: (len(stored), stored.casefold()))
    return words


def _distinct(con, column: str) -> list[str]:
    quoted = '"' + column.replace('"', '""') + '"'
    rows = con.execute(
        f"""
        SELECT DISTINCT {quoted}
        FROM products
        WHERE {quoted} IS NOT NULL
          AND TRIM(CAST({quoted} AS VARCHAR)) <> ''
        """
    ).fetchall()
    return [row[0] for row in rows]


COLUMN_TYPES, CACHED_VALUES, CACHED_RANGES = _load_cache()


def _fuzzy(candidates: list[str], needle: str) -> list[str]:
    """Typo match against values already cached in memory."""
    if not candidates:
        return []
    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            SELECT stored, score
            FROM (
                SELECT stored,
                       jaro_winkler_similarity(lower(stored), lower(?)) AS score
                FROM (SELECT UNNEST(?) AS stored)
            )
            WHERE score >= ?
            ORDER BY score DESC, length(stored)
            LIMIT 5
            """,
            [needle, candidates, FUZZY_MIN],
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return []
    best = rows[0][1]
    # One spelling only when it is clearly ahead of the next.
    if len(rows) == 1 or best - rows[1][1] >= FUZZY_GAP:
        chosen = rows[:1]
    else:
        chosen = [row for row in rows if best - row[1] < FUZZY_GAP]
    return [f"{stored} (close spelling {score:.2f})" for stored, score in chosen]


def _retailers() -> list[dict]:
    data = yaml.safe_load(DICTIONARY_PATH.read_text(encoding="utf-8"))
    for entry in data["columns"]:
        if entry["name"] == "channel_id":
            return entry["values"]
    return []


def _retailer_hits(needle: str) -> list[str]:
    retailers = _retailers()
    names = [entry["retailer"] for entry in retailers]
    hits = _text_hits(names, needle) or _fuzzy(names, needle)
    by_name = {entry["retailer"].casefold(): entry for entry in retailers}
    lines = []
    for name in hits:
        clean = name.split(" (close spelling")[0]
        entry = by_name.get(clean.casefold())
        if entry is None:
            continue
        brands = entry["brands"]
        shown = ", ".join(brands[:12])
        extra = f" and {len(brands) - 12} more" if len(brands) > 12 else ""
        lines.append(
            f"{clean} is channel_id {entry['id']}. Brands on that retailer: {shown}{extra}."
        )
    return lines


def _format_hits(column: str, hits: list[str]) -> str:
    shown = hits[:LIMIT]
    lines = [f"{column}:"]
    lines.extend(f"- {item}" for item in shown)
    if len(hits) > LIMIT:
        lines.append(f"and {len(hits) - LIMIT} more. Pass a longer value to narrow this.")
    return "\n".join(lines)


def _column_values(column: str) -> list[str]:
    if column not in CACHED_VALUES:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            CACHED_VALUES[column] = _distinct(con, column)
        finally:
            con.close()
    return CACHED_VALUES[column]


def _lookup_elsewhere(needle: str, skip: str) -> dict[str, list[str]]:
    found = {}
    for name in LOOKUP_COLUMNS:
        if name == skip or name not in CACHED_VALUES:
            continue
        matches = _text_hits(CACHED_VALUES[name], needle)
        if matches:
            found[name] = matches
    if "color" in found and "product_color" in found and set(found["color"]) == set(found["product_color"]):
        del found["product_color"]
    return found


def _text_lookup(asked: str, needle: str) -> str:
    hits = _text_hits(_column_values(asked), needle)
    if hits:
        return f"column: {asked}\n" + _format_hits(asked, hits)

    found = _lookup_elsewhere(needle, asked)

    if found:
        lines = [
            f"column: {asked}",
            "matches: []",
            f"No {asked} value matches {needle!r}. It was found in:",
        ]
        lines.extend(_format_hits(name, matches) for name, matches in found.items())
        lines.append(_column_advice(asked, list(found)))
        return "\n".join(lines)

    close = _fuzzy(_column_values(asked), needle)
    if close:
        lines = [f"column: {asked}", _format_hits(asked, close)]
        if len(close) > 1:
            lines.append("These spellings are too close to pick one.")
        return "\n".join(lines)

    retailers = _retailer_hits(needle)
    if retailers:
        return (
            f"column: {asked}\nmatches: []\n"
            f"No {asked} value matches {needle!r}.\n"
            "Retailer match (this is channel_id, not brand):\n"
            + "\n".join(retailers)
        )
    return (
        f"column: {asked}\nmatches: []\n"
        f"Nothing in {asked}, brand, color, product_name, or rank_label matches {needle!r}."
    )


def _column_advice(asked: str, columns: list[str]) -> str:
    """Name a column only when the text matched that one column."""
    if len(columns) == 1:
        return f"Use {columns[0]} in the query, not {asked}."
    names = ", ".join(columns)
    return f"Matching columns: {names}. The question decides which column to filter."


def _number_lookup(column: str, needle: str) -> str:
    try:
        number = float(needle)
    except ValueError:
        found = _lookup_elsewhere(needle, skip="")
        lines = [
            f"{column} stores numbers, and {needle!r} is not a number.",
            f"Do not put it in {column}.",
            "matches: []",
        ]
        if found:
            lines.append("It was found in:")
            lines.extend(_format_hits(name, matches) for name, matches in found.items())
            lines.append(_column_advice(column, list(found)))
        return "\n".join(lines)

    low, high = CACHED_RANGES[column]
    if column in MEASURE_COLUMNS:
        if number < low or number > high:
            return (
                f"{column} values run from {low} to {high}. "
                f"{needle} is outside that range. Do not replace it with a nearby number."
            )
        return (
            f"{column} values run from {low} to {high}. "
            f"{needle} is inside that range. Filter with it in run_sql."
        )

    stored = _column_values(column)
    shown = needle[:-2] if needle.endswith(".0") else needle
    if shown in {str(item) for item in stored} or str(int(number)) in {str(item) for item in stored}:
        return f"{column} = {int(number) if number.is_integer() else number} is stored."
    return f"{column} has no value {needle}. Stored {column} values: {', '.join(map(str, stored))}."


def _date_lookup(column: str, needle: str) -> str:
    low, high = CACHED_RANGES[column]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle):
        return f"{column} stores dates as YYYY-MM-DD. {needle!r} is not one of those."
    if str(low) <= needle <= str(high):
        return f"{column} dates run from {low} to {high}. {needle} is inside that range."
    return (
        f"{column} dates run from {low} to {high}. "
        f"{needle} is outside that range. Do not replace it with a nearby date."
    )

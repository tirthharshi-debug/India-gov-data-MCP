"""
In-memory DuckDB analytics engine for deterministic aggregations.

Loads a list of records into a transient DuckDB table, runs exact
``SUM``, ``AVG``, ``MIN``, ``MAX``, or ``COUNT`` queries grouped by
one or more columns, and returns structured results.  Also supports
geographic joins across two datasets using normalized state/district
columns.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import duckdb

from datagov_mcp.normalizer import normalize_record_keys, normalize_geo_in_records

logger = logging.getLogger(__name__)

ALLOWED_OPS = {"sum", "avg", "min", "max", "count"}
OperationType = Literal["sum", "avg", "min", "max", "count"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_numeric(records: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    """Best-effort coerce *column* values to float, stripping commas."""
    for rec in records:
        val = rec.get(column)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            continue
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        try:
            rec[column] = float(cleaned)
        except ValueError:
            rec[column] = None
    return records


_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_identifier(name: str, *, strict: bool = True) -> str:
    """Validate and quote an identifier for use in DuckDB SQL."""
    if strict and not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid SQL identifier {name!r}: must match ^[a-zA-Z_][a-zA-Z0-9_]*$"
        )
    return '"' + name.replace('"', '""') + '"'


def _infer_duckdb_type(values: list[Any]) -> str:
    """Infer a DuckDB column type from sample Python values."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "VARCHAR"
    if all(isinstance(v, bool) for v in non_null):
        return "BOOLEAN"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "BIGINT"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "DOUBLE"
    return "VARCHAR"


def _load_table(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    records: list[dict[str, Any]],
) -> list[str]:
    """Create a DuckDB table from *records* and return its column names."""
    cols: list[str] = list(dict.fromkeys(k for r in records for k in r.keys()))
    col_types: dict[str, str] = {}
    for col in cols:
        col_types[col] = _infer_duckdb_type([r.get(col) for r in records])

    col_defs = ", ".join(f"{_safe_identifier(c)} {col_types[c]}" for c in cols)
    safe_table = _safe_identifier(table_name)
    con.execute(f"CREATE TABLE {safe_table} ({col_defs})")

    placeholders = ", ".join("?" for _ in cols)
    rows: list[tuple[Any, ...]] = []
    for rec in records:
        row_vals = []
        for col in cols:
            val = rec.get(col)
            if val is not None and col_types[col] == "VARCHAR" and not isinstance(val, str):
                val = str(val)
            row_vals.append(val)
        rows.append(tuple(row_vals))

    con.executemany(f"INSERT INTO {safe_table} VALUES ({placeholders})", rows)  # nosec B608
    return cols


def _fetch_dicts(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Fetch all rows from the executed DuckDB cursor as a list of dicts."""
    if not cur.description:
        return []
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Core analytics
# ---------------------------------------------------------------------------


def aggregate(
    records: list[dict[str, Any]],
    group_by: str | list[str],
    metric_column: str,
    operation: OperationType = "sum",
) -> list[dict[str, Any]]:
    """Load *records* into DuckDB and compute an aggregation.

    Parameters
    ----------
    records : list[dict]
        Row data (already normalized keys recommended).
    group_by : str or list[str]
        Column(s) to ``GROUP BY``.
    metric_column : str
        The numeric column to aggregate.
    operation : str
        One of ``sum``, ``avg``, ``min``, ``max``, ``count``.

    Returns
    -------
    list[dict]
        Result rows with group-by columns and the computed metric.

    Raises
    ------
    ValueError
        If *operation* is not in the allowed set or columns are missing.
    """
    op = operation.lower().strip()
    if op not in ALLOWED_OPS:
        raise ValueError(f"Unsupported operation '{operation}'. Use one of: {ALLOWED_OPS}")

    if isinstance(group_by, str):
        group_by = [group_by]

    if not records:
        return []

    # Normalize keys
    records = [normalize_record_keys(r) for r in records]
    metric_column = metric_column.strip()

    # Validate columns exist
    sample_keys = set(records[0].keys())
    for col in group_by:
        if col not in sample_keys:
            raise ValueError(
                f"group_by column '{col}' not found. Available: {sorted(sample_keys)}"
            )
    if metric_column not in sample_keys and op != "count":
        raise ValueError(
            f"metric_column '{metric_column}' not found. Available: {sorted(sample_keys)}"
        )

    # Coerce metric to numeric
    if op != "count":
        records = _coerce_numeric(records, metric_column)

    # Build DuckDB query
    con = duckdb.connect(":memory:")
    try:
        _load_table(con, "data", records)

        group_cols_sql = ", ".join(_safe_identifier(c) for c in group_by)
        if op == "count":
            agg_expr = "COUNT(*)"
        else:
            agg_expr = f"{op.upper()}({_safe_identifier(metric_column)})"

        sql = (
            f"SELECT {group_cols_sql}, {agg_expr} AS result "  # nosec B608
            f"FROM data "
            f"GROUP BY {group_cols_sql} "
            f"ORDER BY result DESC"
        )
        logger.debug("DuckDB SQL: %s", sql)
        cur = con.execute(sql)
        return _fetch_dicts(cur)
    finally:
        con.close()


def geographic_join(
    records_a: list[dict[str, Any]],
    records_b: list[dict[str, Any]],
    geo_level: str = "state",
) -> list[dict[str, Any]]:
    """Join two datasets on normalized geographic columns.

    Parameters
    ----------
    records_a, records_b : list[dict]
        Row data from two different resources.
    geo_level : str
        ``"state"`` or ``"district"`` — which geographic level to join on.

    Returns
    -------
    list[dict]
        Inner-joined result rows with columns from both datasets
        (suffixed ``_a`` / ``_b`` where names overlap).
    """
    if not records_a or not records_b:
        return []

    # Normalize keys
    records_a = [normalize_record_keys(r) for r in records_a]
    records_b = [normalize_record_keys(r) for r in records_b]

    # Normalize geographic values
    records_a = normalize_geo_in_records(records_a)
    records_b = normalize_geo_in_records(records_b)

    # Detect join column
    geo_level = geo_level.lower().strip()
    join_col_a = _detect_geo_col(records_a, geo_level)
    join_col_b = _detect_geo_col(records_b, geo_level)

    if not join_col_a or not join_col_b:
        raise ValueError(
            f"Could not detect a '{geo_level}' column in one or both datasets. "
            f"Dataset A columns: {sorted(records_a[0].keys())}; "
            f"Dataset B columns: {sorted(records_b[0].keys())}"
        )

    con = duckdb.connect(":memory:")
    try:
        cols_a = _load_table(con, "a", records_a)
        cols_b = _load_table(con, "b", records_b)

        overlap = set(cols_a) & set(cols_b)
        select_parts = [
            f"a.{_safe_identifier(c)} AS {_safe_identifier(c + '_a' if c in overlap else c)}"
            for c in cols_a
        ] + [
            f"b.{_safe_identifier(c)} AS {_safe_identifier(c + '_b' if c in overlap else c)}"
            for c in cols_b
        ]
        select_sql = ", ".join(select_parts)

        join_a = _safe_identifier(join_col_a)
        join_b = _safe_identifier(join_col_b)

        sql = (
            f"SELECT {select_sql} FROM a "  # nosec B608
            f"INNER JOIN b ON a.{join_a} = b.{join_b}"
        )
        logger.debug("DuckDB join SQL: %s", sql)
        cur = con.execute(sql)
        return _fetch_dicts(cur)
    finally:
        con.close()


def _detect_geo_col(records: list[dict[str, Any]], level: str) -> str | None:
    """Find the best column name matching *level* ('state' or 'district')."""
    keys = list(records[0].keys()) if records else []

    # Exact matches first
    for k in keys:
        if k == level:
            return k
    # Name hints
    hints = {
        "state": ["state", "state_name", "state_ut", "state_or_ut", "statename"],
        "district": ["district", "district_name", "districtname"],
    }
    for k in keys:
        if k in hints.get(level, []):
            return k
    # Substring match
    for k in keys:
        if level in k:
            return k
    return None


ALLOWED_EXPORT_FORMATS = {"csv", "json", "parquet"}
_SENSITIVE_PATH_PREFIXES = (
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/sys",
    "/proc",
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
)


def _validate_export_path(output_path: str, fmt_clean: str) -> Path:
    """Validate *output_path* against traversal, sensitive dirs, and extension."""
    if not output_path or not output_path.strip():
        raise ValueError("output_path must be a non-empty file path.")

    raw_path = Path(output_path)
    if ".." in raw_path.parts:
        raise ValueError(
            f"Directory traversal ('..') is not allowed in output_path: {output_path!r}"
        )

    expected_ext = f".{fmt_clean}"
    if raw_path.suffix.lower() != expected_ext:
        raise ValueError(
            f"output_path extension {raw_path.suffix!r} does not match format "
            f"{fmt_clean!r} (expected {expected_ext!r})."
        )

    resolved = raw_path.resolve()
    resolved_lower = str(resolved).lower()
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if resolved_lower == prefix or resolved_lower.startswith(prefix + "\\") or resolved_lower.startswith(prefix + "/"):
            raise ValueError(
                f"Refusing to write to sensitive system path: {resolved}"
            )

    if resolved.name.lower() in {".env", ".gitignore"} or ".git" in resolved.parts:
        raise ValueError(f"Refusing to overwrite protected file/directory: {resolved}")

    return resolved


def export_records(
    records: list[dict[str, Any]],
    output_path: str,
    fmt: str = "csv",
) -> dict[str, Any]:
    """Export *records* (normalized to snake_case) to CSV, JSON, or Parquet.

    Creates parent directories if they do not exist.
    """
    fmt_clean = fmt.lower().strip()
    if fmt_clean not in ALLOWED_EXPORT_FORMATS:
        raise ValueError(
            f"Unsupported export format '{fmt}'. Use one of: {sorted(ALLOWED_EXPORT_FORMATS)}"
        )

    path = _validate_export_path(output_path, fmt_clean)

    normalized = [normalize_record_keys(r) for r in records]
    normalized = normalize_geo_in_records(normalized)

    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt_clean == "csv":
        fieldnames = list(dict.fromkeys(k for r in normalized for k in r.keys()))
        with path.open("w", encoding="utf-8", newline="") as f:
            if fieldnames:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(normalized)
    elif fmt_clean == "json":
        with path.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False, default=str)
    elif fmt_clean == "parquet":
        if not normalized:
            raise ValueError("Cannot export 0 records to Parquet format.")
        con = duckdb.connect(":memory:")
        try:
            _load_table(con, "export_data", normalized)
            escaped = str(path.resolve()).replace("'", "''")
            con.execute(f"COPY export_data TO '{escaped}' (FORMAT PARQUET)")
        finally:
            con.close()

    return {
        "output_path": str(path.resolve()),
        "format": fmt_clean,
        "rows_exported": len(normalized),
        "file_size_bytes": path.stat().st_size,
    }

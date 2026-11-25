"""
FastMCP server exposing 6 tools for India's Open Government Data portal.

Each tool is documented with rich docstrings so that an AI agent (Claude,
GPT, etc.) can discover datasets, inspect schemas, fetch records, run exact
aggregations, join datasets on geography, and produce citations — all
without hallucinating math or guessing column names.

Usage
-----
    # Run directly
    python -m datagov_mcp.server

    # Or via the installed entry-point
    india-gov-data-mcp

    # Inspect with FastMCP
    fastmcp list src/datagov_mcp/server.py
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from datagov_mcp import catalog, client
from datagov_mcp.analytics import aggregate, export_records, geographic_join
from datagov_mcp.normalizer import (
    get_canonical_state_map,
    infer_column_type,
    match_filter_values,
    normalize_geo_in_records,
    normalize_record_keys,
    resolve_unambiguous_filter,
    to_snake_case,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "india-gov-data-mcp",
    instructions=(
        "MCP server for India's Open Government Data portal (api.data.gov.in). "
        "Use `search_catalog` to discover datasets by keyword, `inspect_schema` "
        "to understand column names and types before querying, `find_filter_values` "
        "to resolve exact filter strings, `query_records` to fetch data with "
        "auto-pagination, `aggregate_dataset` for exact math, `join_on_geography` "
        "to merge two datasets on state/district, `export_dataset` to save "
        "CSV/JSON/Parquet locally, and `get_citation` for reproducible references."
    ),
)


def _extract_column_values(records: list[dict[str, Any]], column: str) -> tuple[str, list[Any]]:
    """Extract values for *column* (matching exact or snake_case key)."""
    if not records:
        return column, []
    sample_keys = list(records[0].keys())
    if column in sample_keys:
        return column, [r.get(column) for r in records]

    target_snake = to_snake_case(column)
    for k in sample_keys:
        if to_snake_case(k) == target_snake:
            return k, [r.get(k) for r in records]
    return column, []


async def _fetch_with_smart_filter_fallback(
    resource_id: str,
    filters: dict[str, str] | None,
    max_rows: int,
) -> tuple[list[dict[str, Any]], int, dict[str, dict[str, str]]]:
    """Fetch records with *filters*; if 0 rows return, sample and resolve
    unambiguous case-insensitive/substring filter values and retry once."""
    records, total = await client.fetch_all_records(
        resource_id, filters=filters, max_rows=max_rows,
    )
    resolved_filters: dict[str, dict[str, str]] = {}

    if not records and filters:
        sample_records, _ = await client.fetch_all_records(
            resource_id, filters=None, max_rows=300,
        )
        if sample_records:
            new_filters = dict(filters)
            for col, val in filters.items():
                _, col_vals = _extract_column_values(sample_records, col)
                resolved = resolve_unambiguous_filter(col_vals, val)
                if resolved and resolved != val:
                    resolved_filters[col] = {"original": val, "resolved": resolved}
                    new_filters[col] = resolved
            if resolved_filters:
                records, total = await client.fetch_all_records(
                    resource_id, filters=new_filters, max_rows=max_rows,
                )

    return records, total, resolved_filters


# ------------------------------------------------------------------
# Tool 1: search_catalog
# ------------------------------------------------------------------


@mcp.tool()
async def search_catalog(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Search data.gov.in for datasets by keyword.

    Returns up to *limit* matching datasets with their `resource_id`,
    title, ministry/sector, and description.  Use this FIRST to discover
    the `resource_id` you need before calling other tools.

    **Examples of good queries:**
    - ``"mandi prices agricultural commodities"``
    - ``"air quality AQI pollution"``
    - ``"census population state wise"``
    - ``"electricity generation power"``
    - ``"rural roads PMGSY"``

    Parameters
    ----------
    query : str
        Keywords to search for (e.g. ``"rainfall crop production"``).
    limit : int
        Maximum number of results to return (default 10, max 50).

    Returns
    -------
    list[dict]
        Each dict has keys: ``resource_id``, ``title``, ``description``,
        ``ministry``, ``sector``, ``source``.
    """
    limit = min(max(limit, 1), 50)
    return await catalog.search(query, limit=limit)


# ------------------------------------------------------------------
# Tool 2: inspect_schema
# ------------------------------------------------------------------


@mcp.tool()
async def inspect_schema(resource_id: str) -> dict[str, Any]:
    """Inspect the schema of a data.gov.in resource before querying it.

    Fetches 5 sample rows, infers each column's type (``numeric``,
    ``date``, ``state``, ``district``, or ``text``), and shows distinct
    sample values for categorical columns so you know the exact casing
    and spelling to use in filters.

    **Always call this before** ``query_records`` or ``aggregate_dataset``
    to avoid guessing column names or filter values.

    Parameters
    ----------
    resource_id : str
        The ``resource_id`` UUID from ``search_catalog`` results.

    Returns
    -------
    dict
        ``columns`` — list of column descriptors (name, snake_name,
        inferred_type, sample_values).
        ``sample_rows`` — 5 sample records with original keys.
        ``total_records`` — server-reported total row count.
        ``field_metadata`` — raw ``field`` array from the API if available.
    """
    data = await client.fetch_resource_info(resource_id)
    records = data.get("records", [])
    total = int(data.get("total", data.get("count", 0)))
    field_meta = data.get("field", [])

    columns: list[dict[str, Any]] = []
    if records:
        for key in records[0].keys():
            values = [r.get(key) for r in records]
            snake = to_snake_case(key)
            col_type = infer_column_type(values, snake)
            distinct = sorted({str(v) for v in values if v is not None})[:15]
            columns.append({
                "original_name": key,
                "snake_name": snake,
                "inferred_type": col_type,
                "sample_values": distinct,
            })

    return {
        "resource_id": resource_id,
        "total_records": total,
        "columns": columns,
        "sample_rows": records[:5],
        "field_metadata": field_meta,
    }


# ------------------------------------------------------------------
# Tool 3: query_records
# ------------------------------------------------------------------


@mcp.tool()
async def query_records(
    resource_id: str,
    filters: dict[str, str] | None = None,
    max_rows: int = 500,
) -> dict[str, Any]:
    """Fetch records from a data.gov.in resource with auto-pagination.

    Automatically paginates past the 100-row API limit in batches,
    normalizes field names to ``snake_case``, and canonicalizes Indian
    state/district names.

    Parameters
    ----------
    resource_id : str
        Dataset ``resource_id`` from ``search_catalog``.
    filters : dict, optional
        Column-value filters (use **original** API column names as keys,
        with exact casing from ``inspect_schema``).
        Example: ``{"State": "Maharashtra", "Year": "2023"}``
    max_rows : int
        Maximum rows to return (default 500, max 5000).  The tool will
        auto-paginate in batches of 100.

    Returns
    -------
    dict
        ``records`` — list of cleaned row dicts with snake_case keys.
        ``total_available`` — server-reported total matching rows.
        ``rows_returned`` — how many rows are in this response.
    """
    max_rows = min(max(max_rows, 1), 5000)
    records, total, resolved_filters = await _fetch_with_smart_filter_fallback(
        resource_id, filters=filters, max_rows=max_rows,
    )

    # Normalize keys
    records = [normalize_record_keys(r) for r in records]

    # Normalize geography columns
    records = normalize_geo_in_records(records)

    response: dict[str, Any] = {
        "resource_id": resource_id,
        "total_available": total,
        "rows_returned": len(records),
        "records": records,
    }
    if resolved_filters:
        response["resolved_filters"] = resolved_filters
        response["note"] = (
            "Exact filter returned 0 rows; automatically resolved unambiguous "
            "filter value(s) from dataset sample."
        )
    return response


# ------------------------------------------------------------------
# Tool 4: aggregate_dataset
# ------------------------------------------------------------------


@mcp.tool()
async def aggregate_dataset(
    resource_id: str,
    group_by: str,
    metric_column: str,
    operation: str = "sum",
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compute an exact aggregation over a data.gov.in dataset using DuckDB.

    Fetches filtered data, loads it into an in-memory DuckDB table, and
    runs a deterministic ``SUM``, ``AVG``, ``MIN``, ``MAX``, or ``COUNT``
    grouped by the specified column.  **Use this instead of asking the LLM
    to do mental math** — results are guaranteed correct.

    Parameters
    ----------
    resource_id : str
        Dataset ``resource_id``.
    group_by : str
        Column to group by (use ``snake_case`` names from ``inspect_schema``).
    metric_column : str
        Numeric column to aggregate (use ``snake_case`` name).
    operation : str
        One of ``"sum"``, ``"avg"``, ``"min"``, ``"max"``, ``"count"``
        (default ``"sum"``).
    filters : dict, optional
        Column-value filters using **original** API column names.

    Returns
    -------
    dict
        ``results`` — list of ``{group_column: value, result: number}`` dicts
        sorted descending by the aggregated value.
        ``operation`` — the aggregation that was performed.
        ``rows_aggregated`` — how many source rows were used.
    """
    records, total, resolved_filters = await _fetch_with_smart_filter_fallback(
        resource_id, filters=filters, max_rows=5000,
    )
    if not records:
        return {
            "resource_id": resource_id,
            "operation": operation,
            "rows_aggregated": 0,
            "results": [],
            "note": "No records matched the given filters.",
        }

    result_rows = aggregate(records, group_by=group_by, metric_column=metric_column, operation=operation)

    response: dict[str, Any] = {
        "resource_id": resource_id,
        "operation": operation,
        "group_by": group_by,
        "metric_column": metric_column,
        "rows_aggregated": len(records),
        "total_available": total,
        "results": result_rows,
    }
    if resolved_filters:
        response["resolved_filters"] = resolved_filters
        response["note"] = (
            "Exact filter returned 0 rows; automatically resolved unambiguous "
            "filter value(s) from dataset sample."
        )
    return response


# ------------------------------------------------------------------
# Tool 5: join_on_geography
# ------------------------------------------------------------------


@mcp.tool()
async def join_on_geography(
    resource_id_a: str,
    resource_id_b: str,
    geo_level: str = "state",
    filters_a: dict[str, str] | None = None,
    filters_b: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Join two data.gov.in datasets on normalized Indian geography.

    Normalizes state or district names in both datasets (e.g. maps
    ``"Bangalore"`` → ``"Bengaluru"``, ``"Orissa"`` → ``"Odisha"``)
    so they match, then performs an inner join via DuckDB.

    **Use case:** Combine AQI data with health data by state, or merge
    crop production with rainfall data by district.

    Parameters
    ----------
    resource_id_a : str
        First dataset ``resource_id``.
    resource_id_b : str
        Second dataset ``resource_id``.
    geo_level : str
        ``"state"`` or ``"district"`` (default ``"state"``).
    filters_a : dict, optional
        Filters for dataset A (original API column names).
    filters_b : dict, optional
        Filters for dataset B (original API column names).

    Returns
    -------
    dict
        ``joined_records`` — list of merged row dicts.
        ``rows_a`` / ``rows_b`` — source row counts.
        ``joined_rows`` — number of rows after the join.
    """
    records_a, _ = await client.fetch_all_records(
        resource_id_a, filters=filters_a, max_rows=5000,
    )
    records_b, _ = await client.fetch_all_records(
        resource_id_b, filters=filters_b, max_rows=5000,
    )

    if not records_a or not records_b:
        return {
            "resource_id_a": resource_id_a,
            "resource_id_b": resource_id_b,
            "geo_level": geo_level,
            "rows_a": len(records_a),
            "rows_b": len(records_b),
            "joined_rows": 0,
            "joined_records": [],
            "note": "One or both datasets returned no records.",
        }

    joined = geographic_join(records_a, records_b, geo_level=geo_level)

    return {
        "resource_id_a": resource_id_a,
        "resource_id_b": resource_id_b,
        "geo_level": geo_level,
        "rows_a": len(records_a),
        "rows_b": len(records_b),
        "joined_rows": len(joined),
        "joined_records": joined,
    }


# ------------------------------------------------------------------
# Tool 6: get_citation
# ------------------------------------------------------------------


async def _build_citation(
    resource_id: str,
    filters: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build an official citation dict for a data.gov.in resource."""
    title = resource_id
    try:
        data = await client.fetch_resource(resource_id, limit=1)
        title = data.get("title", data.get("label", resource_id))
    except Exception:
        logger.debug("Could not fetch title for %s", resource_id, exc_info=True)

    retrieved_at = datetime.now(timezone.utc).isoformat()
    url = f"https://data.gov.in/resource/{resource_id}"

    filter_str = ""
    if filters:
        parts = [f"{k}={v}" for k, v in filters.items()]
        filter_str = f" [Filters: {', '.join(parts)}]"

    citation_text = (
        f'Government of India, Open Government Data Portal. '
        f'"{title}". '
        f'Resource ID: {resource_id}. '
        f'URL: {url}.{filter_str} '
        f'Retrieved: {retrieved_at}.'
    )

    return {
        "citation_text": citation_text,
        "resource_id": resource_id,
        "title": title,
        "url": url,
        "filters_applied": str(filters) if filters else "none",
        "retrieved_at": retrieved_at,
    }


@mcp.tool()
async def get_citation(
    resource_id: str,
    filters: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate an official citation for a data.gov.in dataset.

    Returns a citation block including the dataset title, resource_id,
    portal URL, any applied filters, and the UTC timestamp of retrieval.
    Use this to attribute data properly in reports and answers.

    Parameters
    ----------
    resource_id : str
        Dataset ``resource_id``.
    filters : dict, optional
        Filters that were applied when the data was queried.

    Returns
    -------
    dict
        ``citation_text`` — human-readable citation string.
        ``resource_id`` — the dataset identifier.
        ``url`` — direct link to the dataset on data.gov.in.
        ``retrieved_at`` — ISO-8601 UTC timestamp.
    """
    return await _build_citation(resource_id, filters=filters)


# ------------------------------------------------------------------
# Tool 7: find_filter_values
# ------------------------------------------------------------------


@mcp.tool()
async def find_filter_values(
    resource_id: str,
    column: str,
    search_term: str,
    sample_size: int = 300,
) -> dict[str, Any]:
    """Discover exact, case-sensitive filter values for a dataset column.

    ``api.data.gov.in`` requires exact filter strings (for example
    ``"Bengal Gram(Gram)(Whole)"`` instead of ``"Gram"``, or
    ``"Kozhikode(Calicut)"`` instead of ``"Kozhikode"``).  Use this tool
    before ``query_records`` or ``aggregate_dataset`` whenever a filter
    value might have parenthetical suffixes or non-obvious casing.

    Parameters
    ----------
    resource_id : str
        Dataset ``resource_id`` from ``search_catalog``.
    column : str
        Column name to inspect (original API name or ``snake_case``).
    search_term : str
        Partial or approximate value to search for (e.g. ``"Gram"``).
    sample_size : int
        Number of rows to sample from the dataset (default 300, max 2000).

    Returns
    -------
    dict
        ``exact_matches``, ``matches`` (substring + fuzzy candidates),
        ``total_distinct``, and ``sample_rows_scanned``.
    """
    sample_size = min(max(sample_size, 1), 2000)
    records, _ = await client.fetch_all_records(resource_id, max_rows=sample_size)
    resolved_col, values = _extract_column_values(records, column)
    match_info = match_filter_values(values, search_term)

    return {
        "resource_id": resource_id,
        "column": resolved_col,
        "search_term": search_term,
        "sample_rows_scanned": len(records),
        **match_info,
    }


# ------------------------------------------------------------------
# Tool 8: export_dataset
# ------------------------------------------------------------------


@mcp.tool()
async def export_dataset(
    resource_id: str,
    output_path: str,
    format: str = "csv",
    filters: dict[str, str] | None = None,
    max_rows: int = 2000,
) -> dict[str, Any]:
    """Export records from a data.gov.in resource to CSV, JSON, or Parquet.

    Normalizes column names to ``snake_case``, canonicalizes Indian
    state/district names, creates parent directories if needed, and
    returns file metadata plus an official citation.

    Parameters
    ----------
    resource_id : str
        Dataset ``resource_id`` from ``search_catalog``.
    output_path : str
        Destination file path (e.g. ``"exports/mandi_prices.parquet"``).
    format : str
        Output format: ``"csv"``, ``"json"``, or ``"parquet"`` (default ``"csv"``).
    filters : dict, optional
        Column-value filters (original API column names).
    max_rows : int
        Maximum rows to fetch and export (default 2000, max 10000).

    Returns
    -------
    dict
        ``output_path``, ``format``, ``rows_exported``, ``file_size_bytes``,
        ``total_available``, and ``citation``.
    """
    max_rows = min(max(max_rows, 1), 10000)
    records, total, resolved_filters = await _fetch_with_smart_filter_fallback(
        resource_id, filters=filters, max_rows=max_rows,
    )
    export_info = export_records(records, output_path=output_path, fmt=format)
    citation_info = await _build_citation(resource_id, filters=filters)

    result: dict[str, Any] = {
        **export_info,
        "resource_id": resource_id,
        "total_available": total,
        "citation": citation_info["citation_text"],
    }
    if resolved_filters:
        result["resolved_filters"] = resolved_filters
    return result


# ------------------------------------------------------------------
# MCP Resources
# ------------------------------------------------------------------


@mcp.resource("datagov://geography/states")
def geography_states_resource() -> str:
    """Canonical 36 Indian States/UTs and known spelling/legacy variants."""
    return json.dumps(get_canonical_state_map(), indent=2, ensure_ascii=False)


@mcp.resource("datagov://catalog/featured")
def featured_catalog_resource() -> str:
    """Curated featured datasets from data.gov.in."""
    return json.dumps(
        [entry.to_dict() for entry in catalog.SEED_INDEX],
        indent=2,
        ensure_ascii=False,
    )


# ------------------------------------------------------------------
# MCP Prompts
# ------------------------------------------------------------------


@mcp.prompt()
def compare_states(topic: str, state_a: str, state_b: str) -> str:
    """Guide the assistant to compare two Indian states on a public data topic."""
    return (
        f"Compare **{state_a}** and **{state_b}** on the topic: **{topic}**.\n\n"
        "Follow these steps strictly using the `india-gov-data-mcp` tools:\n"
        f"1. Call `search_catalog(query={topic!r})` to find the most relevant `resource_id`.\n"
        "2. Call `inspect_schema(resource_id=...)` to verify exact column names, types, and state casing.\n"
        "3. Call `aggregate_dataset(resource_id=..., group_by='state', metric_column=..., operation=...)` "
        "(or the exact snake_case state column) to compute deterministic metrics without mental math.\n"
        f"4. Compare the figures for {state_a} and {state_b}, noting any data caveats.\n"
        "5. Call `get_citation(resource_id=...)` and include the official data.gov.in citation at the end."
    )


@mcp.prompt()
def mandi_price_check(commodity: str, state: str = "Gujarat") -> str:
    """Guide the assistant to inspect and aggregate daily APMC mandi prices."""
    mandi_rid = "9ef84268-d588-465a-a308-a864a43d0070"
    return (
        f"Check daily wholesale mandi prices for **{commodity}** in **{state}**.\n\n"
        "Follow these steps strictly using the `india-gov-data-mcp` tools:\n"
        f"1. Call `inspect_schema(resource_id={mandi_rid!r})` to confirm column names.\n"
        f"2. Call `find_filter_values(resource_id={mandi_rid!r}, column='commodity', search_term={commodity!r})` "
        "to resolve the exact API commodity spelling (e.g. parenthetical varieties).\n"
        f"3. Call `aggregate_dataset(resource_id={mandi_rid!r}, group_by='district', "
        "metric_column='modal_price', operation='avg', "
        f"filters={{'state': {state!r}, 'commodity': '<resolved_commodity>'}})` "
        "to compute district-wise average modal prices.\n"
        f"4. Call `get_citation(resource_id={mandi_rid!r})` and include the official citation."
    )


# ------------------------------------------------------------------
# Entry-point
# ------------------------------------------------------------------


def main() -> None:
    """Launch the MCP server (called by ``india-gov-data-mcp`` CLI entry-point)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()

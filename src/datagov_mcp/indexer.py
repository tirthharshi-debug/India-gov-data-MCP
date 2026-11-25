"""
CLI catalog indexer for ``data.gov.in`` datasets.

Fetches catalog resource listings from ``api.data.gov.in`` (using the shared
HTTP/1.1 + browser ``User-Agent`` client to bypass NIC ``uproxy`` WAF stalls)
and upserts them into the local SQLite FTS5 catalog cache.

Usage
-----
    datagov-sync-catalog --pages 10
    datagov-sync-catalog --pages 5 --query agriculture
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
from typing import Any

from datagov_mcp.catalog import (
    _DB_PATH,
    CatalogEntry,
    _ensure_seed,
    _init_cache,
    _upsert_entries,
)
from datagov_mcp.client import PAGE_SIZE, search_catalog_api

logger = logging.getLogger(__name__)


def _extract_entries(payload: dict[str, Any]) -> list[CatalogEntry]:
    """Extract CatalogEntry objects from a catalog API response payload.

    Handles shifting endpoint schemas (``records`` / ``results`` / ``data``
    and varied field names) gracefully.
    """
    raw_items = (
        payload.get("records")
        or payload.get("results")
        or payload.get("data")
        or []
    )
    if not isinstance(raw_items, list):
        return []

    entries: list[CatalogEntry] = []
    for rec in raw_items:
        if not isinstance(rec, dict):
            continue
        rid = (
            rec.get("resource_id")
            or rec.get("index_name")
            or rec.get("id")
            or ""
        )
        title = rec.get("title") or rec.get("name") or ""
        if not rid or not title:
            continue

        ministry = rec.get("org") or rec.get("ministry") or rec.get("department") or ""
        if isinstance(ministry, list):
            ministry = ", ".join(str(m) for m in ministry if m)

        sector = rec.get("sector") or rec.get("catalog_name") or ""
        if isinstance(sector, list):
            sector = ", ".join(str(s) for s in sector if s)

        description = rec.get("desc") or rec.get("description") or rec.get("notes") or ""

        entries.append(
            CatalogEntry(
                resource_id=str(rid),
                title=str(title),
                description=str(description),
                ministry=str(ministry),
                sector=str(sector),
                source="api",
            )
        )
    return entries


async def sync_catalog(pages: int = 10, query: str = "") -> int:
    """Fetch up to *pages* pages of catalog listings and upsert into SQLite FTS5.

    Returns the total number of entries upserted.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    total_upserted = 0
    try:
        _init_cache(conn)
        _ensure_seed(conn)

        for page in range(pages):
            offset = page * PAGE_SIZE
            print(f"[Page {page + 1}/{pages}] Fetching offset={offset} query={query!r}...")
            try:
                payload = await search_catalog_api(
                    query,
                    offset=offset,
                    limit=PAGE_SIZE,
                    timeout=12.0,
                )
            except Exception as exc:
                print(f"  -> Warning: page {page + 1} failed ({exc}); stopping pagination.")
                break

            entries = _extract_entries(payload)
            if not entries:
                print(f"  -> No more entries returned at page {page + 1}; done.")
                break

            _upsert_entries(conn, entries)
            total_upserted += len(entries)
            print(f"  -> Upserted {len(entries)} entries (total synced: {total_upserted}).")
    finally:
        conn.close()

    return total_upserted


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for ``datagov-sync-catalog``."""
    parser = argparse.ArgumentParser(
        prog="datagov-sync-catalog",
        description="Sync data.gov.in dataset catalog metadata into local SQLite FTS5 cache.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=10,
        help="Number of 100-item catalog pages to fetch (default: 10).",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="",
        help="Optional keyword query to filter catalog listings.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")
    pages = max(1, args.pages)
    total = asyncio.run(sync_catalog(pages=pages, query=args.query))
    print(f"Catalog sync complete. Total entries synced: {total} (DB: {_DB_PATH})")


if __name__ == "__main__":
    main()

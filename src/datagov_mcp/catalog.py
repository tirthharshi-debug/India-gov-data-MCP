"""
Catalog search and local seed index for ``data.gov.in`` datasets.

Maintains a curated seed index of high-value, frequently queried
government datasets (Mandi prices, AQI, PMGSY roads, etc.) so an AI
agent can discover resource_ids by keyword without prior knowledge.
Results are cached in an in-process SQLite database for fast repeats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from datagov_mcp.client import search_catalog_api

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CatalogEntry:
    """A single discoverable dataset on data.gov.in."""

    resource_id: str
    title: str
    description: str = ""
    ministry: str = ""
    sector: str = ""
    source: str = ""  # "seed" | "api" | "cache"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Curated seed index — high-value, well-known datasets
# ---------------------------------------------------------------------------

SEED_INDEX: list[CatalogEntry] = [
    CatalogEntry(
        resource_id="9ef84268-d588-465a-a308-a864a43d0070",
        title="Daily Wholesale Prices of Agricultural Commodities (Mandi Prices)",
        description="Daily wholesale prices of agricultural commodities at APMC mandis across India including commodity name, variety, state, district, market, min/max/modal prices.",
        ministry="Ministry of Agriculture and Farmers' Welfare",
        sector="Agriculture",
        source="seed",
    ),
    CatalogEntry(
        resource_id="3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69",
        title="Real-Time Air Quality Index (AQI) from CPCB Monitoring Stations",
        description="Real-time AQI data from CPCB (Central Pollution Control Board) monitoring stations across Indian cities including PM2.5, PM10, NO2, SO2, O3 values.",
        ministry="Ministry of Environment, Forest and Climate Change",
        sector="Environment",
        source="seed",
    ),
    CatalogEntry(
        resource_id="d6525529-ebf9-4cd5-b77f-aab5ccb1e8c3",
        title="PMGSY Road Construction Progress — Pradhan Mantri Gram Sadak Yojana",
        description="State-wise and district-wise progress of rural road construction under PMGSY including sanctioned length, completed length, and habitations connected.",
        ministry="Ministry of Rural Development",
        sector="Infrastructure",
        source="seed",
    ),
    CatalogEntry(
        resource_id="6176ee09-3d56-4a3b-8115-21841576b2f6",
        title="Indian Railways Station Codes and Names",
        description="Complete list of Indian railway station codes, station names, and zones.",
        ministry="Ministry of Railways",
        sector="Transport",
        source="seed",
    ),
    CatalogEntry(
        resource_id="1d19077c-4560-4d84-83b1-691784d1294e",
        title="PIN Code Directory of India",
        description="Complete PIN code directory with office name, district, state, and division details.",
        ministry="Ministry of Communications",
        sector="Communications",
        source="seed",
    ),
    CatalogEntry(
        resource_id="f1950b97-5ed5-4700-b08a-afdb72c960b2",
        title="State-wise and Item-wise Consumer Price Index (CPI) Numbers",
        description="Consumer Price Index numbers for rural, urban, and combined across states and items used for inflation measurement.",
        ministry="Ministry of Statistics and Programme Implementation",
        sector="Economy",
        source="seed",
    ),
    CatalogEntry(
        resource_id="370d6500-d518-4473-98b3-7b4a0e5c48c0",
        title="State-wise Census Population Data",
        description="State-wise population figures from Census of India including rural/urban breakup, decadal growth, density, and sex ratio.",
        ministry="Ministry of Home Affairs",
        sector="Demographics",
        source="seed",
    ),
    CatalogEntry(
        resource_id="bb1ef13a-ad3c-429c-9b1f-4a0e43eed4be",
        title="State-wise Electricity Generation and Consumption",
        description="Monthly and annual electricity generation, installed capacity, consumption, and T&D losses across Indian states and power utilities.",
        ministry="Ministry of Power",
        sector="Energy",
        source="seed",
    ),
    CatalogEntry(
        resource_id="4a46ef0b-5ef6-437d-a3ae-0dbb14e57944",
        title="Health Infrastructure — Hospitals, PHCs, CHCs, Sub-Centres",
        description="State and district-wise count of government hospitals, PHCs (Primary Health Centres), CHCs, sub-centres and beds availability.",
        ministry="Ministry of Health and Family Welfare",
        sector="Health",
        source="seed",
    ),
    CatalogEntry(
        resource_id="a3ddc24d-80df-45a3-a3d3-7c3c0ea2d51c",
        title="State-wise Literacy Rate (Census 2011)",
        description="State-wise total, male, and female literacy rates from Census 2011.",
        ministry="Ministry of Home Affairs",
        sector="Education",
        source="seed",
    ),
    CatalogEntry(
        resource_id="80be9e14-7cbc-4bbb-b2a3-de3025b1b7f8",
        title="Water Quality Monitoring Data — CPCB",
        description="Station-wise water quality parameters (BOD, DO, pH, coliform) for rivers, lakes, and groundwater across India.",
        ministry="Ministry of Jal Shakti",
        sector="Environment",
        source="seed",
    ),
    CatalogEntry(
        resource_id="4d49a9d4-ed75-4597-bb8e-8e32d0c79f1b",
        title="State-wise and Crop-wise Agricultural Production Statistics",
        description="Area, production, and yield of principal crops across states and seasons (Kharif, Rabi, Zaid).",
        ministry="Ministry of Agriculture and Farmers' Welfare",
        sector="Agriculture",
        source="seed",
    ),
]


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

_DB_PATH = Path.home() / ".datagov_mcp_cache.db"


def _init_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog (
            resource_id TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT DEFAULT '',
            ministry    TEXT DEFAULT '',
            sector      TEXT DEFAULT '',
            source      TEXT DEFAULT 'api'
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts "
        "USING fts5(resource_id, title, description, ministry, sector, content=catalog, content_rowid=rowid)"
    )
    conn.commit()


def _upsert_entries(conn: sqlite3.Connection, entries: list[CatalogEntry]) -> None:
    for e in entries:
        conn.execute(
            "INSERT OR REPLACE INTO catalog (resource_id, title, description, ministry, sector, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (e.resource_id, e.title, e.description, e.ministry, e.sector, e.source),
        )
    # Rebuild FTS index
    conn.execute("INSERT INTO catalog_fts(catalog_fts) VALUES('rebuild')")
    conn.commit()


def _sanitize_fts_query(query: str) -> str:
    """Convert an arbitrary user query into safe quoted FTS5 terms."""
    tokens = re.findall(r"[a-zA-Z0-9]+", query)
    if not tokens:
        return ""
    return " ".join(f'"{t}"' for t in tokens)


def _search_cache(conn: sqlite3.Connection, query: str, limit: int) -> list[CatalogEntry]:
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []
    try:
        rows = conn.execute(
            "SELECT resource_id, title, description, ministry, sector, source "
            "FROM catalog_fts WHERE catalog_fts MATCH ? LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        like_term = f"%{query.strip()}%"
        rows = conn.execute(
            "SELECT resource_id, title, description, ministry, sector, source "
            "FROM catalog WHERE title LIKE ? OR description LIKE ? OR sector LIKE ? LIMIT ?",
            (like_term, like_term, like_term, limit),
        ).fetchall()
    return [
        CatalogEntry(
            resource_id=r[0], title=r[1], description=r[2],
            ministry=r[3], sector=r[4], source="cache",
        )
        for r in rows
    ]


def _ensure_seed(conn: sqlite3.Connection) -> None:
    """Insert the seed index if the cache table is empty."""
    count = conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    if count == 0:
        _upsert_entries(conn, SEED_INDEX)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_local(query: str, limit: int = 10) -> list[CatalogEntry]:
    """Search the local seed/cached catalog by keyword.

    Uses SQLite FTS5 full-text search over titles, descriptions, ministries,
    and sectors.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        _init_cache(conn)
        _ensure_seed(conn)
        results = _search_cache(conn, query, limit)
        return results
    finally:
        conn.close()


async def search_remote(query: str, limit: int = 10) -> list[CatalogEntry]:
    """Search the live data.gov.in catalog API and cache results locally."""
    try:
        data = await search_catalog_api(query, limit=limit)
    except Exception as exc:
        logger.warning("Remote catalog search failed (%s), falling back to local.", exc)
        return search_local(query, limit)

    entries: list[CatalogEntry] = []
    # The API returns records under various keys depending on the endpoint
    records = data.get("records", data.get("results", []))
    if isinstance(records, list):
        for rec in records:
            rid = (
                rec.get("resource_id", "")
                or rec.get("index_name", "")
                or rec.get("id", "")
            )
            if not rid:
                continue
            entry = CatalogEntry(
                resource_id=str(rid),
                title=rec.get("title", rec.get("name", "")),
                description=rec.get("desc", rec.get("description", rec.get("notes", ""))),
                ministry=rec.get("org", rec.get("ministry", rec.get("department", ""))),
                sector=rec.get("sector", rec.get("catalog_name", "")),
                source="api",
            )
            entries.append(entry)

    # Cache for future searches
    if entries:
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            _init_cache(conn)
            _upsert_entries(conn, entries)
            conn.close()
        except Exception:
            logger.debug("Cache write failed; non-critical.", exc_info=True)

    return entries[:limit] if entries else search_local(query, limit)


async def search(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Combined search: search local SQLite FTS5 seed/cache index first,
    then optionally query the remote catalog API with a 5-second timeout,
    deduplicate by resource_id, and return up to *limit* results as dicts."""
    local_results = search_local(query, limit=limit)
    if len(local_results) >= limit:
        return [e.to_dict() for e in local_results[:limit]]

    remote_results: list[CatalogEntry] = []
    try:
        remote_results = await asyncio.wait_for(
            search_remote(query, limit=limit),
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("Remote catalog search skipped/timed out (%s).", exc)

    seen: set[str] = set()
    merged: list[CatalogEntry] = []
    for entry in local_results + remote_results:
        if entry.resource_id not in seen:
            seen.add(entry.resource_id)
            merged.append(entry)

    return [e.to_dict() for e in merged[:limit]]

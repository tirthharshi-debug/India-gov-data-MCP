"""
Async HTTP client for the ``api.data.gov.in`` REST API.

Features
--------
* Auto-pagination past the 100-row-per-request limit.
* Configurable retries with exponential back-off.
* Tolerant SSL verification (Indian govt endpoints sometimes have cert issues).
* Respects the ``DATA_GOV_API_KEY`` environment variable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://api.data.gov.in"
PAGE_SIZE = 100  # API hard-limit per request
DEFAULT_TIMEOUT = httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=8.0)
MAX_RETRIES = 1
BACKOFF_FACTOR = 1.5
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _api_key() -> str:
    key = os.getenv("DATA_GOV_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "DATA_GOV_API_KEY is not set. "
            "Get a free key at https://data.gov.in/ogpl_apis and set it in "
            "your environment or a .env file."
        )
    return key


def _build_client(timeout: httpx.Timeout | float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Create a shared ``httpx.AsyncClient`` with HTTP/1.1 browser-compatible
    headers, bounded timeouts, and optional SSL verification bypass."""
    verify = os.getenv("DATA_GOV_VERIFY_SSL", "1").lower() not in ("0", "false", "no")
    return httpx.AsyncClient(
        base_url=BASE_URL,
        http2=False,
        timeout=timeout,
        verify=verify,
        headers=DEFAULT_HEADERS,
    )


async def _request_with_retry(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Issue a GET request with exponential-back-off retries (up to *retries* retries)."""
    last_exc: Exception | None = None
    total_attempts = retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < total_attempts:
                wait = BACKOFF_FACTOR ** attempt
                logger.warning(
                    "Request %s attempt %d/%d failed (%s), retrying in %.1fs…",
                    path, attempt, total_attempts, exc, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("Request %s failed after %d attempts.", path, total_attempts)
    raise RuntimeError(f"Request to {path} failed after {total_attempts} attempts") from last_exc


# ------------------------------------------------------------------
# Public helpers
# ------------------------------------------------------------------


async def fetch_resource(
    resource_id: str,
    *,
    filters: dict[str, str] | None = None,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> dict[str, Any]:
    """Fetch a single page of records from a resource endpoint.

    Returns the raw JSON payload including ``status``, ``count``, ``total``,
    ``records``, and ``field`` (schema metadata).
    """
    params: dict[str, Any] = {
        "api-key": _api_key(),
        "format": "json",
        "offset": offset,
        "limit": min(limit, PAGE_SIZE),
    }
    if filters:
        for col, val in filters.items():
            params[f"filters[{col}]"] = val

    async with _build_client() as client:
        return await _request_with_retry(client, f"/resource/{resource_id}", params)


async def fetch_all_records(
    resource_id: str,
    *,
    filters: dict[str, str] | None = None,
    max_rows: int = 500,
) -> tuple[list[dict[str, Any]], int]:
    """Auto-paginate through a resource and return up to *max_rows* records.

    Returns
    -------
    records : list[dict]
        The collected rows (each a dict of column→value).
    total : int
        The server-reported total number of matching rows.
    """
    all_records: list[dict[str, Any]] = []
    offset = 0
    total = 0

    async with _build_client() as client:
        while offset < max_rows:
            batch_size = min(PAGE_SIZE, max_rows - offset)
            params: dict[str, Any] = {
                "api-key": _api_key(),
                "format": "json",
                "offset": offset,
                "limit": batch_size,
            }
            if filters:
                for col, val in filters.items():
                    params[f"filters[{col}]"] = val

            data = await _request_with_retry(
                client, f"/resource/{resource_id}", params
            )
            total = int(data.get("total", data.get("count", 0)))
            records = data.get("records", [])
            if not records:
                break
            all_records.extend(records)
            offset += len(records)
            if offset >= total:
                break

    return all_records, total


async def search_catalog_api(
    query: str,
    *,
    offset: int = 0,
    limit: int = 10,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Search the data.gov.in catalog listing API for datasets matching
    *query*.

    Returns the raw JSON payload with matched catalog entries.
    """
    params: dict[str, Any] = {
        "api-key": _api_key(),
        "format": "json",
        "search": query,
        "offset": offset,
        "limit": min(limit, PAGE_SIZE),
    }
    async with _build_client(timeout=httpx.Timeout(timeout)) as client:
        return await _request_with_retry(client, "/lists", params, retries=0)


async def fetch_resource_info(resource_id: str) -> dict[str, Any]:
    """Fetch a minimal payload (5 rows) to inspect schema and metadata."""
    return await fetch_resource(resource_id, limit=5)

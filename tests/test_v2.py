"""Tests for india-gov-data-mcp V2 features:
- find_filter_values & smart auto-resolved filter fallback
- export_dataset (CSV, JSON, Parquet)
- MCP resources (datagov://geography/states, datagov://catalog/featured)
- MCP prompts (compare_states, mandi_price_check)
- indexer entry extraction
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import duckdb
import pytest

from datagov_mcp import server
from datagov_mcp.analytics import export_records
from datagov_mcp.indexer import _extract_entries
from datagov_mcp.normalizer import (
    match_filter_values,
    normalize_state,
    resolve_unambiguous_filter,
)


# ---------------------------------------------------------------------------
# 1. Fuzzy filter value discovery & smart fallback
# ---------------------------------------------------------------------------


SAMPLE_MANDI_ROWS = [
    {"state": "Gujarat", "district": "Rajkot", "commodity": "Bengal Gram(Gram)(Whole)", "modal_price": "5200"},
    {"state": "Gujarat", "district": "Surat", "commodity": "Wheat", "modal_price": "2400"},
    {"state": "Kerala", "district": "Kozhikode(Calicut)", "commodity": "Coconut", "modal_price": "3100"},
    {"state": "Kerala", "district": "Ernakulam", "commodity": "Banana - Green", "modal_price": "2800"},
]


class TestFilterValueDiscovery:
    def test_match_filter_values_substring_and_fuzzy(self) -> None:
        values = [r["commodity"] for r in SAMPLE_MANDI_ROWS]
        res = match_filter_values(values, "Gram")
        assert res["exact_matches"] == []
        assert "Bengal Gram(Gram)(Whole)" in res["matches"]
        assert res["total_distinct"] == 4

    def test_match_filter_values_exact(self) -> None:
        values = [r["commodity"] for r in SAMPLE_MANDI_ROWS]
        res = match_filter_values(values, "Wheat")
        assert res["exact_matches"] == ["Wheat"]
        assert res["matches"][0] == "Wheat"

    def test_resolve_unambiguous_filter(self) -> None:
        values = [r["district"] for r in SAMPLE_MANDI_ROWS]
        assert resolve_unambiguous_filter(values, "Kozhikode") == "Kozhikode(Calicut)"
        assert resolve_unambiguous_filter(values, "rajkot") == "Rajkot"
        assert resolve_unambiguous_filter(values, "NonExistent") is None

    async def test_find_filter_values_tool(self) -> None:
        with patch.object(
            server.client,
            "fetch_all_records",
            new=AsyncMock(return_value=(SAMPLE_MANDI_ROWS, len(SAMPLE_MANDI_ROWS))),
        ):
            res = await server.find_filter_values(
                resource_id="9ef84268-d588-465a-a308-a864a43d0070",
                column="commodity",
                search_term="Gram",
                sample_size=100,
            )
        assert res["column"] == "commodity"
        assert res["sample_rows_scanned"] == 4
        assert "Bengal Gram(Gram)(Whole)" in res["matches"]

    async def test_query_records_smart_filter_fallback(self) -> None:
        """When exact filter returns 0 rows, query_records samples, resolves, and retries."""
        calls: list[dict[str, str] | None] = []

        async def fake_fetch_all(
            resource_id: str,
            *,
            filters: dict[str, str] | None = None,
            max_rows: int = 500,
        ) -> tuple[list[dict[str, Any]], int]:
            calls.append(filters)
            if filters == {"commodity": "Gram"}:
                return [], 0
            if filters is None:
                return SAMPLE_MANDI_ROWS, len(SAMPLE_MANDI_ROWS)
            if filters == {"commodity": "Bengal Gram(Gram)(Whole)"}:
                return [SAMPLE_MANDI_ROWS[0]], 1
            return [], 0

        with patch.object(server.client, "fetch_all_records", side_effect=fake_fetch_all):
            res = await server.query_records(
                resource_id="9ef84268-d588-465a-a308-a864a43d0070",
                filters={"commodity": "Gram"},
                max_rows=50,
            )

        assert res["rows_returned"] == 1
        assert res["resolved_filters"] == {
            "commodity": {"original": "Gram", "resolved": "Bengal Gram(Gram)(Whole)"}
        }
        assert len(calls) == 3

    async def test_aggregate_dataset_smart_filter_fallback(self) -> None:
        async def fake_fetch_all(
            resource_id: str,
            *,
            filters: dict[str, str] | None = None,
            max_rows: int = 500,
        ) -> tuple[list[dict[str, Any]], int]:
            if filters == {"district": "Kozhikode"}:
                return [], 0
            if filters is None:
                return SAMPLE_MANDI_ROWS, len(SAMPLE_MANDI_ROWS)
            if filters == {"district": "Kozhikode(Calicut)"}:
                return [SAMPLE_MANDI_ROWS[2]], 1
            return [], 0

        with patch.object(server.client, "fetch_all_records", side_effect=fake_fetch_all):
            res = await server.aggregate_dataset(
                resource_id="9ef84268-d588-465a-a308-a864a43d0070",
                group_by="state",
                metric_column="modal_price",
                operation="avg",
                filters={"district": "Kozhikode"},
            )

        assert res["rows_aggregated"] == 1
        assert res["results"][0]["state"] == "Kerala"
        assert res["results"][0]["result"] == 3100.0
        assert "resolved_filters" in res


# ---------------------------------------------------------------------------
# 2. Local dataset export (CSV, JSON, Parquet)
# ---------------------------------------------------------------------------


class TestExportDataset:
    RAW_ROWS = [
        {"State Name": "Orissa", "Modal Price": "1200"},
        {"State Name": "Keralam", "Modal Price": "3100"},
    ]

    def test_export_csv(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "out.csv"
        info = export_records(self.RAW_ROWS, str(out), fmt="csv")
        assert info["rows_exported"] == 2
        assert info["format"] == "csv"
        assert out.exists()
        with out.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["state_name"] == "Odisha"
        assert rows[1]["state_name"] == "Kerala"

    def test_export_json(self, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        info = export_records(self.RAW_ROWS, str(out), fmt="json")
        assert info["rows_exported"] == 2
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[1]["state_name"] == "Kerala"

    def test_export_parquet(self, tmp_path: Path) -> None:
        out = tmp_path / "out.parquet"
        info = export_records(self.RAW_ROWS, str(out), fmt="parquet")
        assert info["rows_exported"] == 2
        assert info["file_size_bytes"] > 0
        con = duckdb.connect(":memory:")
        try:
            rows = con.execute(f"SELECT state_name, modal_price FROM '{out}'").fetchall()
            assert rows == [("Odisha", "1200"), ("Kerala", "3100")]
        finally:
            con.close()

    async def test_export_dataset_tool(self, tmp_path: Path) -> None:
        out = tmp_path / "mandi.csv"
        with (
            patch.object(
                server.client,
                "fetch_all_records",
                new=AsyncMock(return_value=(self.RAW_ROWS, 2)),
            ),
            patch.object(
                server.client,
                "fetch_resource",
                new=AsyncMock(return_value={"title": "Mandi Prices"}),
            ),
        ):
            res = await server.export_dataset(
                resource_id="9ef84268-d588-465a-a308-a864a43d0070",
                output_path=str(out),
                format="csv",
            )
        assert res["rows_exported"] == 2
        assert "Mandi Prices" in res["citation"]
        assert out.exists()


# ---------------------------------------------------------------------------
# 3. Indexer extraction
# ---------------------------------------------------------------------------


class TestIndexer:
    def test_extract_entries_handles_varied_schemas(self) -> None:
        payload = {
            "records": [
                {
                    "resource_id": "abc-123",
                    "title": "Test Dataset",
                    "org": ["Ministry A", "Dept B"],
                    "sector": ["Agriculture"],
                    "desc": "Some description",
                }
            ]
        }
        entries = _extract_entries(payload)
        assert len(entries) == 1
        assert entries[0].resource_id == "abc-123"
        assert entries[0].ministry == "Ministry A, Dept B"
        assert entries[0].sector == "Agriculture"


# ---------------------------------------------------------------------------
# 4. MCP Resources & Prompts
# ---------------------------------------------------------------------------


class TestResourcesAndPrompts:
    def test_keralam_normalizes_to_kerala(self) -> None:
        assert normalize_state("Keralam") == "Kerala"

    def test_geography_states_resource(self) -> None:
        raw = server.geography_states_resource()
        data = json.loads(raw)
        assert data["total_canonical"] == 36
        assert "Kerala" in data["canonical_states"]
        assert data["variants"]["keralam"] == "Kerala"

    def test_featured_catalog_resource(self) -> None:
        raw = server.featured_catalog_resource()
        data = json.loads(raw)
        assert isinstance(data, list)
        assert any(d["resource_id"] == "9ef84268-d588-465a-a308-a864a43d0070" for d in data)

    def test_compare_states_prompt(self) -> None:
        prompt = server.compare_states("literacy rate", "Kerala", "Bihar")
        assert "search_catalog" in prompt
        assert "inspect_schema" in prompt
        assert "aggregate_dataset" in prompt
        assert "get_citation" in prompt
        assert "Kerala" in prompt and "Bihar" in prompt

    def test_mandi_price_check_prompt(self) -> None:
        prompt = server.mandi_price_check("Gram", state="Gujarat")
        assert "9ef84268-d588-465a-a308-a864a43d0070" in prompt
        assert "find_filter_values" in prompt
        assert "modal_price" in prompt
        assert "Gujarat" in prompt


# ---------------------------------------------------------------------------
# 5. Security hardening tests
# ---------------------------------------------------------------------------


class TestSecurityHardening:
    def test_rejects_sql_injection_identifier(self) -> None:
        from datagov_mcp.analytics import _safe_identifier

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _safe_identifier("state; DROP TABLE data--")

    def test_fts5_malformed_query_does_not_raise(self) -> None:
        from datagov_mcp.catalog import search_local

        # Special FTS5 syntax chars (-, :, *, parentheses, OR) should not raise OperationalError
        res = search_local('mandi: (prices) -foo OR "bar*', limit=5)
        assert isinstance(res, list)

    def test_export_rejects_traversal_and_bad_extension(self, tmp_path: Path) -> None:
        rows = [{"state": "Kerala", "val": "1"}]
        with pytest.raises(ValueError, match="traversal"):
            export_records(rows, str(tmp_path / ".." / "escape.csv"), fmt="csv")
        with pytest.raises(ValueError, match="extension"):
            export_records(rows, str(tmp_path / "wrong.txt"), fmt="csv")
        with pytest.raises(ValueError, match="sensitive system path"):
            export_records(rows, r"C:\Windows\System32\evil.csv", fmt="csv")

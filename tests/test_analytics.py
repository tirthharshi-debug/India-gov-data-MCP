"""Tests for datagov_mcp.analytics — DuckDB aggregations and geographic joins."""

from __future__ import annotations

import pytest

from datagov_mcp.analytics import aggregate, geographic_join


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

CROP_DATA = [
    {"State Name": "Maharashtra", "Crop": "Rice", "Production (tonnes)": "1,500"},
    {"State Name": "Maharashtra", "Crop": "Wheat", "Production (tonnes)": "800"},
    {"State Name": "Kerala", "Crop": "Rice", "Production (tonnes)": "1,200"},
    {"State Name": "Kerala", "Crop": "Wheat", "Production (tonnes)": "300"},
    {"State Name": "Tamil Nadu", "Crop": "Rice", "Production (tonnes)": "2,000"},
    {"State Name": "Tamil Nadu", "Crop": "Wheat", "Production (tonnes)": "150"},
    {"State Name": "Bihar", "Crop": "Rice", "Production (tonnes)": "3,500"},
    {"State Name": "Bihar", "Crop": "Wheat", "Production (tonnes)": "2,800"},
]

POPULATION_DATA = [
    {"State": "Maharashtra", "Population": "112374333"},
    {"State": "Kerala", "Population": "33406061"},
    {"State": "Tamil Nadu", "Population": "72147030"},
    {"State": "Bihar", "Population": "104099452"},
]

AQI_DATA_WITH_VARIANTS = [
    {"state_name": "orissa", "City": "Bhubaneswar", "AQI": "120"},
    {"state_name": "maharastra", "City": "Mumbai", "AQI": "95"},
    {"state_name": "KARNATAKA", "City": "Bangalore", "AQI": "78"},
]

HEALTH_DATA_WITH_VARIANTS = [
    {"State": "Odisha", "Hospitals": "250"},
    {"State": "Maharashtra", "Hospitals": "1200"},
    {"State": "Karnataka", "Hospitals": "800"},
]


# ---------------------------------------------------------------------------
# aggregate()
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_sum_by_state(self) -> None:
        result = aggregate(
            CROP_DATA,
            group_by="state_name",
            metric_column="production_tonnes",
            operation="sum",
        )
        assert len(result) == 4
        # Bihar has 3500 + 2800 = 6300 (highest)
        assert result[0]["state_name"] == "Bihar"
        assert result[0]["result"] == 6300.0

    def test_avg_by_crop(self) -> None:
        result = aggregate(
            CROP_DATA,
            group_by="crop",
            metric_column="production_tonnes",
            operation="avg",
        )
        assert len(result) == 2
        # Rice avg = (1500+1200+2000+3500)/4 = 2050
        rice_row = next(r for r in result if r["crop"] == "Rice")
        assert rice_row["result"] == 2050.0

    def test_min_max(self) -> None:
        result_min = aggregate(
            CROP_DATA, group_by="crop", metric_column="production_tonnes", operation="min",
        )
        result_max = aggregate(
            CROP_DATA, group_by="crop", metric_column="production_tonnes", operation="max",
        )
        wheat_min = next(r for r in result_min if r["crop"] == "Wheat")
        wheat_max = next(r for r in result_max if r["crop"] == "Wheat")
        assert wheat_min["result"] == 150.0
        assert wheat_max["result"] == 2800.0

    def test_count(self) -> None:
        result = aggregate(
            CROP_DATA, group_by="state_name", metric_column="production_tonnes", operation="count",
        )
        # Each state has 2 rows
        for row in result:
            assert row["result"] == 2

    def test_invalid_operation_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported operation"):
            aggregate(CROP_DATA, group_by="crop", metric_column="production_tonnes", operation="median")

    def test_missing_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            aggregate(CROP_DATA, group_by="nonexistent", metric_column="production_tonnes", operation="sum")

    def test_missing_metric_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            aggregate(CROP_DATA, group_by="crop", metric_column="nonexistent_col", operation="sum")

    def test_empty_records(self) -> None:
        assert aggregate([], group_by="x", metric_column="y", operation="sum") == []

    def test_handles_commas_in_numbers(self) -> None:
        """Verify that comma-separated numbers like '1,500' are parsed."""
        data = [
            {"Category": "A", "Value": "1,234,567"},
            {"Category": "A", "Value": "2,000"},
            {"Category": "B", "Value": "500"},
        ]
        result = aggregate(data, group_by="category", metric_column="value", operation="sum")
        a_row = next(r for r in result if r["category"] == "A")
        assert a_row["result"] == 1_236_567.0


# ---------------------------------------------------------------------------
# geographic_join()
# ---------------------------------------------------------------------------


class TestGeographicJoin:
    def test_basic_state_join(self) -> None:
        """Join crop and population data on state names."""
        joined = geographic_join(
            [{"State Name": "Maharashtra", "Crop": "Rice", "Value": "100"},
             {"State Name": "Kerala", "Crop": "Rice", "Value": "200"}],
            [{"State": "Maharashtra", "Pop": "112M"},
             {"State": "Kerala", "Pop": "33M"}],
            geo_level="state",
        )
        assert len(joined) == 2

    def test_join_normalizes_variants(self) -> None:
        """State name variants (orissa → Odisha, maharastra → Maharashtra)
        should be normalized before joining."""
        joined = geographic_join(
            AQI_DATA_WITH_VARIANTS,
            HEALTH_DATA_WITH_VARIANTS,
            geo_level="state",
        )
        # All 3 states should match after normalization
        assert len(joined) == 3

    def test_empty_dataset(self) -> None:
        assert geographic_join([], POPULATION_DATA, geo_level="state") == []

    def test_no_matching_geo_column_raises(self) -> None:
        no_geo = [{"x": 1, "y": 2}]
        with pytest.raises(ValueError, match="Could not detect"):
            geographic_join(no_geo, POPULATION_DATA, geo_level="state")

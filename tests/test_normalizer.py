"""Tests for datagov_mcp.normalizer — snake_case, state/district canonicalization, type inference."""

from __future__ import annotations

import pytest

from datagov_mcp.normalizer import (
    CANONICAL_STATES,
    infer_column_type,
    normalize_district,
    normalize_record_keys,
    normalize_state,
    to_snake_case,
)


# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------


class TestToSnakeCase:
    """Test field-name normalisation to snake_case."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("State Name", "state_name"),
            ("State Name (English)", "state_name_english"),
            ("Avg. Rainfall (mm)", "avg_rainfall_mm"),
            ("  Year  ", "year"),
            ("commodity_name", "commodity_name"),
            ("CamelCaseColumn", "camel_case_column"),
            ("ALL CAPS HEADER", "all_caps_header"),
            ("price (₹/quintal)", "price_quintal"),
            ("S.No.", "s_no"),
            ("District/City", "district_city"),
            ("", ""),
        ],
    )
    def test_conversions(self, raw: str, expected: str) -> None:
        assert to_snake_case(raw) == expected


# ---------------------------------------------------------------------------
# normalize_record_keys
# ---------------------------------------------------------------------------


class TestNormalizeRecordKeys:
    def test_basic(self) -> None:
        rec = {"State Name": "Kerala", "Avg Rainfall (mm)": 42.5, "Year": 2023}
        result = normalize_record_keys(rec)
        assert set(result.keys()) == {"state_name", "avg_rainfall_mm", "year"}
        assert result["state_name"] == "Kerala"
        assert result["avg_rainfall_mm"] == 42.5


# ---------------------------------------------------------------------------
# normalize_state
# ---------------------------------------------------------------------------


class TestNormalizeState:
    """State/UT canonicalization — the workhorse of geographic joins."""

    def test_all_canonical_names_map_to_themselves(self) -> None:
        for state in CANONICAL_STATES:
            assert normalize_state(state) == state

    @pytest.mark.parametrize(
        "variant, expected",
        [
            # Legacy names
            ("orissa", "Odisha"),
            ("ORISSA", "Odisha"),
            ("Orissa", "Odisha"),
            ("uttaranchal", "Uttarakhand"),
            ("Uttaranchal", "Uttarakhand"),
            ("pondicherry", "Puducherry"),
            # Abbreviations
            ("UP", "Uttar Pradesh"),
            ("mp", "Madhya Pradesh"),
            ("J&K", "Jammu and Kashmir"),
            ("TN", "Tamil Nadu"),
            ("WB", "West Bengal"),
            ("DL", "Delhi"),
            # Common mis-spellings
            ("chhattishgarh", "Chhattisgarh"),
            ("chattisgarh", "Chhattisgarh"),
            ("maharastra", "Maharashtra"),
            ("gujrat", "Gujarat"),
            ("telengana", "Telangana"),
            ("rajastan", "Rajasthan"),
            ("jharkand", "Jharkhand"),
            # Short-hands
            ("A.P.", "Andhra Pradesh"),
            ("H.P.", "Himachal Pradesh"),
            ("M.P.", "Madhya Pradesh"),
            ("W.B.", "West Bengal"),
            # UTs
            ("NCT of Delhi", "Delhi"),
            ("New Delhi", "Delhi"),
            ("A & N Islands", "Andaman and Nicobar Islands"),
            ("Daman & Diu", "Dadra and Nagar Haveli and Daman and Diu"),
            # Casing
            ("TAMIL NADU", "Tamil Nadu"),
            ("tamil nadu", "Tamil Nadu"),
            ("  Kerala  ", "Kerala"),
        ],
    )
    def test_variants(self, variant: str, expected: str) -> None:
        assert normalize_state(variant) == expected

    def test_unknown_returns_original(self) -> None:
        assert normalize_state("Wakanda") == "Wakanda"


# ---------------------------------------------------------------------------
# normalize_district
# ---------------------------------------------------------------------------


class TestNormalizeDistrict:
    @pytest.mark.parametrize(
        "variant, expected",
        [
            ("bangalore", "Bengaluru"),
            ("BANGALORE", "Bengaluru"),
            ("Bangalore", "Bengaluru"),
            ("gurgaon", "Gurugram"),
            ("GURGAON", "Gurugram"),
            ("bombay", "Mumbai"),
            ("calcutta", "Kolkata"),
            ("madras", "Chennai"),
            ("trivandrum", "Thiruvananthapuram"),
            ("allahabad", "Prayagraj"),
            ("benaras", "Varanasi"),
            ("poona", "Pune"),
            ("baroda", "Vadodara"),
            ("ahmadabad", "Ahmedabad"),
            ("pondicherry", "Puducherry"),
        ],
    )
    def test_variants(self, variant: str, expected: str) -> None:
        assert normalize_district(variant) == expected

    def test_already_canonical(self) -> None:
        # Title case input that isn't a known variant should pass through
        assert normalize_district("Pune") == "Pune"

    def test_unknown_uppercased_gets_title_cased(self) -> None:
        assert normalize_district("SOME PLACE") == "Some Place"


# ---------------------------------------------------------------------------
# infer_column_type
# ---------------------------------------------------------------------------


class TestInferColumnType:
    def test_numeric(self) -> None:
        assert infer_column_type(["100", "200.5", "3,000", None, "42"]) == "numeric"

    def test_date(self) -> None:
        assert infer_column_type(["2024-01-15", "2024-02-20", "2024-03-10"]) == "date"

    def test_state_by_name_hint(self) -> None:
        assert infer_column_type(["foo", "bar"], col_name="state_name") == "state"

    def test_state_by_values(self) -> None:
        vals = ["Maharashtra", "Kerala", "Tamil Nadu", "Bihar", "Goa"]
        assert infer_column_type(vals) == "state"

    def test_district_by_name_hint(self) -> None:
        assert infer_column_type(["x"], col_name="district") == "district"

    def test_text_fallback(self) -> None:
        assert infer_column_type(["hello", "world", "foo"]) == "text"

    def test_empty_values(self) -> None:
        assert infer_column_type([None, None, ""]) == "text"

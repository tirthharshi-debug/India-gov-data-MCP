"""
Normalizer for Indian geographic names and field keys.

Cleans messy column headers into snake_case, and canonicalizes all 36 Indian
State/UT names and common district spelling variants so that two datasets
using different spellings (e.g. "Bangalore" vs "Bengaluru") can be joined.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# ---------------------------------------------------------------------------
# Field-name cleaning
# ---------------------------------------------------------------------------

_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def to_snake_case(name: str) -> str:
    """Convert an arbitrary header string to a clean ``snake_case`` key.

    Examples
    --------
    >>> to_snake_case("State Name (English)")
    'state_name_english'
    >>> to_snake_case(" Avg. Rainfall (mm) ")
    'avg_rainfall_mm'
    """
    s = name.strip()
    # Insert underscore before upper-case runs (for camelCase inputs)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = s.lower()
    s = _CLEAN_RE.sub("_", s)
    return s.strip("_")


def normalize_record_keys(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *record* with every key converted to snake_case."""
    return {to_snake_case(k): v for k, v in record.items()}


# ---------------------------------------------------------------------------
# Canonical Indian State / UT names  (28 States + 8 UTs = 36)
# ---------------------------------------------------------------------------

CANONICAL_STATES: list[str] = [
    # States (28)
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    # Union Territories (8)
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]

# Mapping of common variants / legacy names → canonical name
_STATE_VARIANTS: dict[str, str] = {
    # Legacy / renamed states
    "orissa": "Odisha",
    "uttaranchal": "Uttarakhand",
    "pondicherry": "Puducherry",
    "keralam": "Kerala",
    # Short forms & abbreviations
    "ap": "Andhra Pradesh",
    "ar": "Arunachal Pradesh",
    "as": "Assam",
    "br": "Bihar",
    "cg": "Chhattisgarh",
    "ct": "Chhattisgarh",
    "ga": "Goa",
    "gj": "Gujarat",
    "hr": "Haryana",
    "hp": "Himachal Pradesh",
    "jh": "Jharkhand",
    "jk": "Jammu and Kashmir",
    "ka": "Karnataka",
    "kl": "Kerala",
    "mp": "Madhya Pradesh",
    "mh": "Maharashtra",
    "mn": "Manipur",
    "ml": "Meghalaya",
    "mz": "Mizoram",
    "nl": "Nagaland",
    "od": "Odisha",
    "or": "Odisha",
    "pb": "Punjab",
    "rj": "Rajasthan",
    "sk": "Sikkim",
    "tn": "Tamil Nadu",
    "ts": "Telangana",
    "tg": "Telangana",
    "tr": "Tripura",
    "up": "Uttar Pradesh",
    "uk": "Uttarakhand",
    "ua": "Uttarakhand",
    "wb": "West Bengal",
    "an": "Andaman and Nicobar Islands",
    "ch": "Chandigarh",
    "dl": "Delhi",
    "dn": "Dadra and Nagar Haveli and Daman and Diu",
    "dd": "Dadra and Nagar Haveli and Daman and Diu",
    "la": "Ladakh",
    "ld": "Lakshadweep",
    "py": "Puducherry",
    # Common spelling / casing variants
    "andhra": "Andhra Pradesh",
    "arunachal": "Arunachal Pradesh",
    "himachal": "Himachal Pradesh",
    "madhya": "Madhya Pradesh",
    "tamil": "Tamil Nadu",
    "tamilnadu": "Tamil Nadu",
    "west bengal": "West Bengal",
    "w bengal": "West Bengal",
    "w.b.": "West Bengal",
    "u.p.": "Uttar Pradesh",
    "m.p.": "Madhya Pradesh",
    "a.p.": "Andhra Pradesh",
    "h.p.": "Himachal Pradesh",
    "j&k": "Jammu and Kashmir",
    "j & k": "Jammu and Kashmir",
    "nct of delhi": "Delhi",
    "nct delhi": "Delhi",
    "new delhi": "Delhi",
    "national capital territory of delhi": "Delhi",
    "a & n islands": "Andaman and Nicobar Islands",
    "a&n islands": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman & nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "d&n haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "chhattishgarh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "chatisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh",
    "jharkand": "Jharkhand",
    "meghlaya": "Meghalaya",
    "megalaya": "Meghalaya",
    "karnatka": "Karnataka",
    "maharastra": "Maharashtra",
    "maharashtr": "Maharashtra",
    "rajastan": "Rajasthan",
    "rajsthan": "Rajasthan",
    "gujrat": "Gujarat",
    "misoram": "Mizoram",
    "telengana": "Telangana",
    "telegana": "Telangana",
    "uttarpradesh": "Uttar Pradesh",
    "madhyapradesh": "Madhya Pradesh",
    "andhrapradesh": "Andhra Pradesh",
    "arunachalpradesh": "Arunachal Pradesh",
    "himachalpradesh": "Himachal Pradesh",
    "laddakh": "Ladakh",
}

# Build lookup: lowercased canonical → canonical
_STATE_LOOKUP: dict[str, str] = {}
for _canon in CANONICAL_STATES:
    _STATE_LOOKUP[_canon.lower()] = _canon
    _STATE_LOOKUP[_canon.lower().replace(" ", "")] = _canon
for _var, _canon in _STATE_VARIANTS.items():
    _STATE_LOOKUP[_var.lower()] = _canon
    _STATE_LOOKUP[_var.lower().replace(" ", "").replace(".", "").replace("&", "")] = _canon


def normalize_state(raw: str) -> str:
    """Return the canonical Indian State/UT name, or the original string if
    no match is found.

    Examples
    --------
    >>> normalize_state("orissa")
    'Odisha'
    >>> normalize_state("J&K")
    'Jammu and Kashmir'
    >>> normalize_state("TAMIL NADU")
    'Tamil Nadu'
    """
    key = raw.strip().lower()
    if key in _STATE_LOOKUP:
        return _STATE_LOOKUP[key]
    # Try without spaces, dots, ampersands
    compressed = key.replace(" ", "").replace(".", "").replace("&", "")
    if compressed in _STATE_LOOKUP:
        return _STATE_LOOKUP[compressed]
    return raw.strip()


# ---------------------------------------------------------------------------
# Common district spelling variants
# ---------------------------------------------------------------------------

_DISTRICT_VARIANTS: dict[str, str] = {
    # Major city rename variants
    "bangalore": "Bengaluru",
    "bangalore urban": "Bengaluru Urban",
    "bangalore rural": "Bengaluru Rural",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "gurgaon": "Gurugram",
    "poona": "Pune",
    "baroda": "Vadodara",
    "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi",
    "calicut": "Kozhikode",
    "trichur": "Thrissur",
    "alleppey": "Alappuzha",
    "quilon": "Kollam",
    "palghat": "Palakkad",
    "cannanore": "Kannur",
    "mangalore": "Dakshina Kannada",
    "mysore": "Mysuru",
    "shimoga": "Shivamogga",
    "bellary": "Ballari",
    "belgaum": "Belagavi",
    "gulbarga": "Kalaburagi",
    "raichur": "Raichur",
    "bijapur": "Vijayapura",
    "hubli-dharwad": "Dharwad",
    "tumkur": "Tumakuru",
    "cuttack": "Cuttack",
    "vizag": "Visakhapatnam",
    "visakapattanam": "Visakhapatnam",
    "vishakhapatnam": "Visakhapatnam",
    "benaras": "Varanasi",
    "benares": "Varanasi",
    "kashi": "Varanasi",
    "allahabad": "Prayagraj",
    "faizabad": "Ayodhya",
    "junagarh": "Junagadh",
    "bhopal": "Bhopal",
    "indore": "Indore",
    "jabalpur": "Jabalpur",
    "jamshedpur": "East Singhbhum",
    "dhanbad": "Dhanbad",
    "patna": "Patna",
    # Ahmedabad variants
    "ahmadabad": "Ahmedabad",
    "amdavad": "Ahmedabad",
    # Kolkata variants
    "howrah": "Howrah",
    "hooghly": "Hooghly",
    "hugli": "Hooghly",
    # Misc
    "pondicherry": "Puducherry",
}

_DISTRICT_LOOKUP: dict[str, str] = {}
for _var, _canon in _DISTRICT_VARIANTS.items():
    _DISTRICT_LOOKUP[_var.lower()] = _canon


def normalize_district(raw: str) -> str:
    """Return the canonical district name, or the title-cased original.

    Examples
    --------
    >>> normalize_district("bangalore")
    'Bengaluru'
    >>> normalize_district("GURGAON")
    'Gurugram'
    >>> normalize_district("Pune")
    'Pune'
    """
    key = raw.strip().lower()
    if key in _DISTRICT_LOOKUP:
        return _DISTRICT_LOOKUP[key]
    return raw.strip().title() if raw.strip().isupper() or raw.strip().islower() else raw.strip()


# ---------------------------------------------------------------------------
# Column-type inference helpers
# ---------------------------------------------------------------------------

_STATE_SET = {s.lower() for s in CANONICAL_STATES}
_STATE_SET.update(_STATE_LOOKUP.keys())

_DATE_RE = re.compile(
    r"^\d{4}[-/]\d{2}[-/]\d{2}$"          # 2024-01-15
    r"|^\d{2}[-/]\d{2}[-/]\d{4}$"          # 15-01-2024
    r"|^\d{2}[-/]\d{2}[-/]\d{2}$"          # 15-01-24
)


def infer_column_type(values: list[Any], col_name: str = "") -> str:
    """Heuristically classify a column as ``numeric``, ``date``, ``state``,
    ``district``, or ``text`` by sampling its values.

    Parameters
    ----------
    values : list
        Sample values from the column (may contain ``None``).
    col_name : str, optional
        The (already snake_cased) column name, used for extra hints.
    """
    non_null = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not non_null:
        return "text"

    # Numeric check
    num_count = 0
    for v in non_null:
        cleaned = v.replace(",", "").replace(" ", "")
        try:
            float(cleaned)
            num_count += 1
        except ValueError:
            pass
    if num_count / len(non_null) >= 0.8:
        return "numeric"

    # Date check
    date_count = sum(1 for v in non_null if _DATE_RE.match(v))
    if date_count / len(non_null) >= 0.6:
        return "date"

    # State check — by name hints or value matching
    state_hints = {"state", "state_name", "state_ut", "state_or_ut", "statename"}
    if col_name in state_hints:
        return "state"
    state_match = sum(1 for v in non_null if v.lower() in _STATE_SET)
    if state_match / len(non_null) >= 0.5:
        return "state"

    # District check — by name hints
    district_hints = {"district", "district_name", "districtname"}
    if col_name in district_hints:
        return "district"

    return "text"


def normalize_geo_in_records(
    records: list[dict[str, Any]],
    state_col: str | None = None,
    district_col: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize state and/or district values in-place across a list of records.

    If column names are ``None``, auto-detect them by looking for keys whose
    inferred type is ``state`` or ``district``.
    """
    if not records:
        return records

    sample = records[0]

    if state_col is None:
        for key in sample:
            vals = [r.get(key) for r in records[:20]]
            if infer_column_type(vals, key) == "state":
                state_col = key
                break

    if district_col is None:
        for key in sample:
            vals = [r.get(key) for r in records[:20]]
            if infer_column_type(vals, key) == "district":
                district_col = key
                break

    for rec in records:
        if state_col and state_col in rec and rec[state_col]:
            rec[state_col] = normalize_state(str(rec[state_col]))
        if district_col and district_col in rec and rec[district_col]:
            rec[district_col] = normalize_district(str(rec[district_col]))

    return records


# ---------------------------------------------------------------------------
# Filter value discovery & fuzzy matching
# ---------------------------------------------------------------------------


def get_canonical_state_map() -> dict[str, Any]:
    """Return canonical Indian States/UTs and their known variant mappings."""
    return {
        "total_canonical": len(CANONICAL_STATES),
        "canonical_states": list(CANONICAL_STATES),
        "variants": dict(_STATE_VARIANTS),
    }


def match_filter_values(
    values: list[Any],
    search_term: str,
    max_results: int = 20,
) -> dict[str, Any]:
    """Find exact, substring, and fuzzy matches for *search_term* in *values*.

    Returns a dict with ``exact_matches``, ``matches`` (ordered by relevance),
    and ``total_distinct``.
    """
    unique = sorted({str(v).strip() for v in values if v is not None and str(v).strip()})
    term = search_term.strip()
    term_lower = term.lower()

    if not term:
        return {
            "exact_matches": [],
            "matches": unique[:max_results],
            "total_distinct": len(unique),
        }

    exact_matches = [v for v in unique if v == term]
    ci_exact = [v for v in unique if v.lower() == term_lower and v not in exact_matches]
    substring_matches = [
        v for v in unique
        if term_lower in v.lower() and v not in exact_matches and v not in ci_exact
    ]

    # Case-insensitive fuzzy matching via difflib
    lower_to_orig: dict[str, list[str]] = {}
    for v in unique:
        lower_to_orig.setdefault(v.lower(), []).append(v)

    fuzzy_lower = difflib.get_close_matches(
        term_lower, list(lower_to_orig.keys()), n=max_results, cutoff=0.45
    )
    fuzzy_matches: list[str] = []
    for fl in fuzzy_lower:
        for orig in lower_to_orig[fl]:
            if orig not in exact_matches and orig not in ci_exact and orig not in substring_matches:
                fuzzy_matches.append(orig)

    combined = (exact_matches + ci_exact + substring_matches + fuzzy_matches)[:max_results]
    return {
        "exact_matches": exact_matches,
        "matches": combined,
        "total_distinct": len(unique),
    }


def resolve_unambiguous_filter(values: list[Any], search_term: str) -> str | None:
    """Resolve *search_term* to a single unambiguous value from *values*, or None.

    Checks in order:
    1. Exact match
    2. Single case-insensitive exact match
    3. Single case-insensitive substring match
    """
    unique = sorted({str(v).strip() for v in values if v is not None and str(v).strip()})
    term = search_term.strip()
    if not term or not unique:
        return None

    if term in unique:
        return term

    term_lower = term.lower()
    ci_exact = [v for v in unique if v.lower() == term_lower]
    if len(ci_exact) == 1:
        return ci_exact[0]

    sub_matches = [v for v in unique if term_lower in v.lower()]
    if len(sub_matches) == 1:
        return sub_matches[0]

    return None

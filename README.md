# india-gov-data-mcp

[![PyPI version](https://img.shields.io/pypi/v/india-gov-data-mcp.svg)](https://pypi.org/project/india-gov-data-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)

Open-source Model Context Protocol (MCP) server giving AI agents direct, queryable, and citation-backed access to India's Open Government Data (`data.gov.in`) platform.

---

## What Is `data.gov.in` & What Can You Search?

**`data.gov.in`** is the **Open Government Data (OGD) Platform India**, set up by the **National Informatics Centre (NIC)** under the **Ministry of Electronics and Information Technology (MeitY)** in line with the **National Data Sharing and Accessibility Policy (NDSAP)**. It serves as a single-window portal where central ministries, departments, and state governments publish shareable, non-sensitive public datasets and APIs—generally made available under the **Government Open Data License – India (GODL)**—for research, analytics, journalism, and application building.

### What Data It Provides
The portal hosts public datasets across central and state bodies at national, state, and district levels across domains such as:
* **Agriculture & Markets:** Daily wholesale APMC mandi prices, arrivals, varieties, grades, and agricultural statistics.
* **Environment & Monitoring:** Real-time/station-level Air Quality Index (AQI) and pollutant readings (such as CPCB monitoring stations) as well as water and environmental datasets.
* **Governance, Schemes & Infrastructure:** Public schemes, development indicators, transport, energy, and regional records.
* **Economy & Social Sectors:** Finance, health, education, demographic, and sectoral datasets.

### Examples of What You Can Search
With this MCP server connected to your AI agent, you can ask natural-language questions instead of hunting through dataset IDs manually:
* **Road safety:** *"Search `data.gov.in` for state-wise road accident datasets, inspect the schema, and summarize trends for Gujarat."*
* **Infrastructure & utilities:** *"Find state-level energy or water datasets, join them by state, and export a CSV summary."*
* **Education & economy:** *"Search education or economic datasets, filter by state or category, and include a citation."*

---

## Why We Built This

Connecting LLMs directly to `api.data.gov.in` typically fails in four ways. `india-gov-data-mcp` solves each of them at the protocol layer:

1. **Opaque UUID Resource IDs** — `data.gov.in` exposes 150,000+ datasets behind opaque UUIDs (e.g., `9ef84268-d588-465a-a308-a864a43d0070`). Our local **SQLite FTS5** seed/cache index paired with live catalog search lets agents discover datasets by natural-language keywords.
2. **Exact-String Filter Traps** — The API enforces strict, case-sensitive filter matching (e.g., `"gram"` returns 0 rows when the dataset stores `"Bengal Gram(Gram)(Whole)"`, or `"Kozhikode"` vs `"Kozhikode(Calicut)"`). `find_filter_values` and automatic smart-fallback resolution discover and apply the exact API strings.
3. **Token Bloat & Arithmetic Hallucinations** — Dumping thousands of raw JSON rows into an LLM context window wastes tokens and leads to mental-math errors. An embedded in-memory **DuckDB** analytical engine (`aggregate_dataset` and `join_on_geography`) computes exact `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, and normalized State/District joins deterministically.
4. **Missing Data Provenance** — Every analysis needs verifiable attribution. `get_citation` returns the official ministry, dataset title, `resource_id`, portal URL, applied filters, and UTC retrieval timestamp.

---

## Available MCP Tools

| Tool | Description |
| :--- | :--- |
| `search_catalog` | Search datasets by keyword across the local SQLite FTS5 index (instant) with a 5-second live `api.data.gov.in` fallback. |
| `inspect_schema` | Fetch 5 sample rows, infer column types (`numeric`, `date`, `state`, `district`, `text`), and list sample categorical values. |
| `find_filter_values` | Sample distinct column values and return exact, substring, and fuzzy matches so filters never miss due to parentheticals or casing. |
| `query_records` | Auto-paginate past the 100-row API limit (up to `max_rows`), normalize keys to `snake_case`, canonicalize Indian State/District names, and auto-resolve unambiguous filters. |
| `aggregate_dataset` | Load filtered records into in-memory DuckDB and compute deterministic `sum`, `avg`, `min`, `max`, or `count` grouped by any column. |
| `join_on_geography` | Canonicalize Indian State/UT or District spelling variants across two datasets (e.g., `Orissa` ↔ `Odisha`, `Bangalore` ↔ `Bengaluru`) and inner-join via DuckDB. |
| `export_dataset` | Export normalized records locally to `csv`, `json`, or `parquet` (via DuckDB `COPY ... TO`) with path-traversal protection and an official citation. |
| `get_citation` | Generate a structured citation block with dataset title, `resource_id`, portal URL, applied filters, and ISO-8601 UTC retrieval timestamp. |

---

## Prerequisites: Get a Free `data.gov.in` API Key

1. Visit [https://www.data.gov.in/](https://www.data.gov.in/) and register for a free account (or sign in).
2. Open **My Account** from the top navigation menu.
3. Generate and copy your personal **API Key** (used as `DATA_GOV_API_KEY`).

---

## Installation

### Method 1: Zero-Install via `uvx` (Recommended)

```bash
uvx india-gov-data-mcp --help
```

### Method 2: Install Globally via `pip`

```bash
pip install india-gov-data-mcp
python -m datagov_mcp.server --help
```

### Method 3: Install from Source (GitHub)

```bash
git clone https://github.com/tirthharshi-debug/India-gov-data-MCP
cd India-gov-data-mcp
python -m venv .venv
```

Activate the virtual environment:

- **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **macOS / Linux:**
  ```bash
  source .venv/bin/activate
  ```

Install in editable mode with dev dependencies and run the test suite:

```bash
pip install -e ".[dev]"
pytest
```

### Optional: Pre-Sync the Local Catalog (`datagov-sync-catalog`)

Pre-populate a local offline SQLite FTS5 index of 1,500+ datasets from `api.data.gov.in`:

```bash
datagov-sync-catalog --pages 15
```

---

## Connecting to Any AI Agent

> **Note on `uvx` vs `python`:** The examples below use `uvx`. If `uvx` is not installed on your system, replace `"command": "uvx"` and `"args": ["india-gov-data-mcp"]` with `"command": "python"` (or the full path to your `.venv` Python executable, e.g., `C:\\path\\to\\.venv\\Scripts\\python.exe`) and `"args": ["-m", "datagov_mcp.server"]`.

### 1. Google Antigravity

Config file: `~/.gemini/config/mcp_config.json` (Windows: `%USERPROFILE%\.gemini\config\mcp_config.json`)

```json
{
  "mcpServers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "your_data_gov_api_key_here"
      }
    }
  }
}
```

### 2. Claude Desktop

Config file:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "your_data_gov_api_key_here"
      }
    }
  }
}
```

### 3. Cursor

Config file: `~/.cursor/mcp.json` (Windows: `%USERPROFILE%\.cursor\mcp.json`)

```json
{
  "mcpServers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "your_data_gov_api_key_here"
      }
    }
  }
}
```

### 4. Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json` (Windows: `%USERPROFILE%\.codeium\windsurf\mcp_config.json`)

```json
{
  "mcpServers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "your_data_gov_api_key_here"
      }
    }
  }
}
```

### 5. Gemini CLI (`@google/gemini-cli`)

Config file: `~/.gemini/settings.json` (Windows: `%USERPROFILE%\.gemini\settings.json`)

```json
{
  "mcpServers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "your_data_gov_api_key_here"
      }
    }
  }
}
```

### 6. VS Code (GitHub Copilot Agent Mode)

Config file: `.vscode/mcp.json` (uses `promptString` inputs so API keys are never hardcoded in workspace files)

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "data_gov_api_key",
      "description": "Your data.gov.in API Key",
      "password": true
    }
  ],
  "servers": {
    "india-gov-data-mcp": {
      "command": "uvx",
      "args": ["india-gov-data-mcp"],
      "env": {
        "DATA_GOV_API_KEY": "${input:data_gov_api_key}"
      }
    }
  }
}
```

---

## Example Prompts to Try

1. **Agriculture / Mandi Prices:**
   > *"Find the current wholesale mandi prices for Bengal Gram in Gujarat, compute the average modal price by district, and include the official data.gov.in citation."*
2. **CPCB Real-Time Air Quality Index (AQI) Telemetry:**
   > *"Search for real-time CPCB Air Quality Index data, inspect the schema, and show the average PM2.5 readings across cities in Maharashtra and Karnataka."*
3. **Multi-Market CSV Export:**
   > *"Query wholesale mandi prices for Wheat across Punjab and Haryana (up to 500 rows), normalize state names, and export the cleaned dataset to `exports/wheat_mandi_prices.csv`."*

---

## Security & Engineering Standards

- **Strict SQL Identifier Validation:** All dynamic DuckDB table and column identifiers are validated against `^[a-zA-Z_][a-zA-Z0-9_]*$` and quoted before query execution; SQLite FTS5 queries sanitize special syntax operators with a parameterized `LIKE` fallback.
- **Export Path-Traversal Hardening:** `export_dataset` rejects `..` traversal, sensitive system directories, protected dotfiles (`.env`, `.git`), and mismatched file extensions (`.csv`, `.json`, `.parquet` only).
- **Environment-Based Secrets:** API keys are read exclusively from `DATA_GOV_API_KEY` and never logged or committed.
- **Verified Quality:** Backed by **100 `pytest` unit tests**, **`bandit`** static security analysis, and **`pip-audit`** dependency vulnerability scanning.

---

## License

Licensed under the [MIT License](LICENSE).

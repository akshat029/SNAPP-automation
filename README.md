# SNAPP Digital Worker — Automation Agent

Playwright-powered bot that reads editor onboarding/offboarding requests from a **Smartsheet** and applies them on the [SNAPP User Manager](https://usermanager.nature.com) platform.

## Features

| Action | Description |
|---|---|
| **Onboard** | Add a new regular or guest editor to a journal |
| **Offboard** | Deactivate / retire an editor |
| **Update** | Change affiliation, role, board sections, keywords |
| **Set Unavailability** | Fill temporary unavailability date range |

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

Copy the template and fill in your values:

```bash
cp .env.example .env
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SNAPP_USERNAME` | ✅ | Springer Nature login email |
| `SNAPP_PASSWORD` | ✅ | Springer Nature login password |
| `SNAPP_URL` | ❌ | Base URL (default: `https://usermanager.nature.com`) |
| `CHROME_PROFILE_PATH` | ❌ | Path to Chrome user-data dir for session reuse |
| `SMARTSHEET_TOKEN` | ✅ | Smartsheet API access token |
| `SMARTSHEET_SHEET_ID` | ✅ | Smartsheet sheet ID containing requests |

### 3. Chrome profile (optional)

To skip manual login by reusing an existing Chrome session:

1. Open Chrome → `chrome://version`
2. Copy the **Profile Path** (e.g. `C:\Users\You\AppData\Local\Google\Chrome\User Data\Profile 1`)
3. Set `CHROME_PROFILE_PATH` in `.env` to that value

## Usage

```bash
# Process all pending Smartsheet requests
python snapp_agent.py

# Preview execution plan without launching browser
python snapp_agent.py --dry-run

# Use a hardcoded mock request for testing
python snapp_agent.py --mock

# Fill all fields but don't click Save (review mode)
python snapp_agent.py --no-save

# Combine flags
python snapp_agent.py --mock --no-save --dry-run
```

## Project structure

```
├── snapp_agent.py          # Main agent — SnappAgent class + CLI entry point
├── helpers.py              # Stealth helpers, parse_editor_name(), retry_async()
├── smartsheet_reader.py    # SmartsheetReader + column/action mappings
├── extract_fields.py       # Utility to extract form fields from HTML dumps
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── tests/                  # Unit tests
│   ├── test_helpers.py
│   └── test_smartsheet.py
├── logs/                   # Runtime logs (gitignored)
└── screenshots/            # Confirmation screenshots (gitignored)
```

## Smartsheet column mapping

The Smartsheet uses generic column names. The mapping is defined in `smartsheet_reader.py`:

| Smartsheet Column | Mapped Field | Description |
|---|---|---|
| `Column10` | `_action_raw` | Action type (On-boarding, Off-boarding, etc.) |
| `Column15` | `journal_id` | Journal numeric ID |
| `Column16` | `journal_name` | Journal title |
| `Column19` | `editor_name` | Editor full name |
| `Column20` | `email` | Editor email |
| `Column23` | `affiliation` | Institution |
| `Column27` | `collection_name` | Collection title (Guest Editor) |
| `Column52` | `role` | Editorial role |

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

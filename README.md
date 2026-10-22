# Textile Resource Intelligence

A local, free and open-source application for monitoring **energy, water, chemicals, steam, fuel, waste and other
production resources** and relating them to **production output**, so that efficiency losses can be found with
traceable, honest calculations.

It runs on your own computer (Windows-first), stores everything in one local SQLite file, needs no account,
no cloud service and makes no network connections of its own.

> **Project status:** version 0.1.0. See [Known limitations](#known-limitations). Calculation and service logic
> is covered by automated tests; run `python -m pytest` after installing (see [Testing](#testing)).

## What it does

- **Resource records** — enter or import consumption (quantity + unit + period + optional scope/reference/notes).
  The quantity and unit you enter are stored exactly as entered; nothing is converted or rounded in storage.
- **Production records** — enter or import production (kg, tonne, g, metres or pieces).
- **Resource intensity** — consumption per unit of production, e.g. **1,200 kWh ÷ 600 kg = 2 kWh/kg**, calculated
  from totals after explicit unit conversion. Unavailable values are shown as *Unavailable*, never as zero.
- **Baseline comparison** — compare a period with a baseline period you choose (absolute difference and percentage
  change, with the reason shown when a comparison is not possible).
- **Trends** — monthly or daily totals and intensity, with gaps (not zeros) for periods without valid data.
- **Data-quality checks** — missing production, partial coverage, possible duplicates, overlapping intervals, zero
  production, unknown units. Every calculated value lists the record IDs it came from.
- **CSV import / export** — validated import with column mapping and preview; export of source records and results.
- **Synthetic demonstration data** — optional, always clearly labelled, removable in one click.

## Requirements

- Windows 10/11 (Linux/macOS also work; commands below are for Windows CMD).
- **Python 3.12** (free, <https://www.python.org/downloads/> — tick *Add python.exe to PATH*).
- Internet access **once**, to download the free Python packages (Streamlit, pandas, SQLAlchemy, Pydantic, Plotly,
  pytest, Ruff). No GPU, paid API or subscription is required.

## Windows setup (Command Prompt)

1. **Extract the ZIP.** In File Explorer right-click the ZIP → *Extract All…*, or in CMD:

   ```bat
   cd %USERPROFILE%\Downloads
   tar -xf textile-resource-intelligence.zip
   cd textile-resource-intelligence
   ```

2. **Create the environment and install** (run in the project folder):

   ```bat
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install --upgrade pip
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

   (Shortcut: `scripts\setup_windows.bat` does the same.)

3. **Run the tests** (recommended on first install):

   ```bat
   .venv\Scripts\python.exe -m pytest
   ```

4. **Start the app:**

   ```bat
   .venv\Scripts\python.exe -m streamlit run app.py
   ```

   (Shortcut: `scripts\run_app.bat`.) Your browser opens at <http://localhost:8501>. If Streamlit asks for an email
   address in the terminal the first time, just press **Enter** to skip. Stop the app with **Ctrl+C**.

5. **Optional — try it with synthetic data:** open **Settings → Demonstration data → Load synthetic demonstration
   data**, or run `.venv\Scripts\python.exe scripts\seed_demo_data.py`.

6. **Optional — freeze the versions you installed** (the dependency ranges in `requirements.txt` are bounded but not
   exact pins): `.venv\Scripts\python.exe -m pip freeze > requirements.lock.txt`

## Using the application

| Page | Purpose |
| --- | --- |
| **Overview** | Totals, production, intensity and data-quality warnings for a month, day or custom range. |
| **Resource Records** | Browse/filter, add, edit, delete and import resource records. |
| **Production Records** | The same for production records. |
| **Analysis** | One resource + scope in detail: results, baseline comparison, trend, and the records behind them. |
| **Reports & Export** | CSV export of source records and calculated results. |
| **Settings** | Resource categories, preferences, demonstration data, database path and backup, limitations. |

Typical workflow: record (or import) resource consumption and production for the same periods → open **Overview** →
open **Analysis** to compare against a baseline → export results.

### Import file format (CSV, UTF-8)

Download a header-only template from the import tab. Dates are `YYYY-MM-DD` only.

| Column | Required | Notes |
| --- | --- | --- |
| `resource_category` | resource files | Must match a category in Settings (case-insensitive). Not used for production files. |
| `quantity` | yes | Plain number, e.g. `1200.5`. No thousands separators. Zero is allowed; negatives are rejected. |
| `unit` | yes | `kWh, MWh, MJ, L, m3 (or m³), kg, g, tonne` for resources; `kg, g, tonne, m, pcs` for production. |
| `period_start` | yes | First day. |
| `period_end` | no | Last day (inclusive). Blank = single date. |
| `scope_key` | no | Optional identifier such as `dyeing-1`. Blank = overall. |
| `reference` | no | Meter/batch/document id. Makes re-imports safe (see duplicate policy). |
| `notes` | no | Free text. |
| `record_type` | no | Only `interval_consumption` is supported; cumulative `meter_reading` rows are rejected. |

Extra columns are ignored and listed. Columns can be mapped by hand if your headers differ. Example files:
`tests/fixtures/` (all synthetic).

## Key behaviours and design decisions

- **Totals** add records only within one resource category, one scope key and one physical dimension (energy, volume,
  mass), after converting units with exact factors. Different chemicals are different categories and are never added.
- **Intensity = total resource ÷ total production** for the *same* period and scope. Production in kg, metres and
  pieces are different *bases*; you choose one and they are never mixed.
- **Overall intensity over several periods** = Σ consumption ÷ Σ production — never an average of period ratios.
- **Records are never split.** A record that crosses the edge of the selected period is excluded and flagged; the
  application does not pro-rate it.
- **Coverage, not "completeness".** The app cannot know which records *should* exist, so it reports how many days of
  the period are covered by records. If resource and production coverage differ, intensity is unavailable.
- **Overlapping records.** Records with identical intervals are treated as separate events (e.g. two meters). Records
  with different but overlapping intervals could double count, so the total becomes unavailable until corrected.
- **Scope keys** are identifiers *you* define (`a-z`, `0-9`, `-`, `_`). Resource and production records match only
  when their keys are identical (blank matches blank). The application never guesses relationships between scopes.
  If your process has stages, give each stage its own scope key so material is not counted twice.
- **Duplicate policy.** *Reliable duplicate*: same reference + category + scope + period → manual entry is rejected,
  import skips the row and reports it. *Possible duplicate*: same scope/period/quantity/unit but no reference to
  distinguish → kept, flagged for review. Nothing is ever deleted automatically.
- **Import is all-or-nothing:** if any row has an error, nothing is saved. The preview and the commit use the same
  validation. Row numbers count data rows after the header (first data row = row 1).
- **Baselines** are reference periods you pick; they are not industry benchmarks. A zero baseline keeps the absolute
  difference but the percentage is shown as unavailable. A difference is an observation, not a diagnosis.
- **Decimals:** quantities are exact (`Decimal`, stored as text). Rounding happens only for display (setting:
  decimal places) and calculations use 50-digit precision.
- **Technical input limits:** quantities below 1e18 with at most 12 decimal places (so values remain exactly storable).
- **Demonstration data** is marked `source_type = demo`, labelled in tables, banners and exports, and is never loaded
  automatically.

## Data location, backups and privacy

- Database: `%LOCALAPPDATA%\TextileResourceIntelligence\textile_resource_intelligence.db`
  (override with the `TRI_DATABASE_PATH` environment variable; `TRI_DATA_DIR` moves the whole data folder).
- Logs: `<data folder>\logs\app.log` (rotating; record contents are not logged). Backups: `<data folder>\backups\`.
- **Backup:** Settings → Database and backup → *Create a backup now* (uses SQLite's online-backup API and verifies the
  copy). **Restore:** close the app and replace the database file with a backup copy.
- The app listens on `127.0.0.1` only, sends no usage statistics (`.streamlit/config.toml`) and has no login — protect
  the computer/user account as you would any file containing business data.
- Optional environment variables: `TRI_LOG_LEVEL`, `TRI_MAX_IMPORT_MB` (default 5), `TRI_MAX_IMPORT_ROWS`
  (default 50,000), `TRI_PAGE_SIZE`.

## Project structure

```text
app.py                      Streamlit entry point and page navigation
pages/                      The six pages (UI only: collect input, display results)
src/textile_resource_intelligence/
  domain/                   Pure logic: units, validation, calculations, comparisons, data quality (no UI/DB imports)
  services/                 Use cases: records, import, analysis, export, categories, preferences, demo data
  models.py, database.py,   SQLite persistence (SQLAlchemy 2.0), schema versioning, unit of work
  repositories.py
  config.py                 Pydantic-validated settings (TRI_* environment variables)
  paths.py, backup.py       Data folder location and safe backups (standard library)
  ui/                       Formatting, tables (pure) and Streamlit/Plotly components
tests/                      unit/, integration/, fixtures/ (synthetic), support/ (in-memory repository)
scripts/                    Windows helper scripts and the demo-data loader
```

Calculation rules live **only** in `domain/`; the interface never recalculates them. The service tests run against
both an in-memory repository and a real temporary SQLite database.

## Testing

```bat
rem all tests
.venv\Scripts\python.exe -m pytest
rem code-style / static checks
.venv\Scripts\python.exe -m ruff check .
```

Tests use only synthetic data and temporary databases — never your real database. Streamlit page smoke tests
(`tests/test_streamlit_app.py`) use Streamlit's `AppTest` harness.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `py` is not recognised | Install Python 3.12 from python.org and tick *Add python.exe to PATH*, then open a new CMD window. |
| `py -3.12` says no suitable Python | Install Python 3.12 (check installed versions with `py -0p`). |
| `pip install` fails / times out | Check your internet connection or proxy; run the install command again. |
| Browser does not open | Open <http://localhost:8501> manually. If the port is busy: `streamlit run app.py --server.port 8502`. |
| "created by a newer version of the application" | The database came from a newer release. Update the app; do not edit the file. |
| "did not create" database error | `TRI_DATABASE_PATH` points at an unrelated SQLite file. Choose another path. |
| CSV rejected as "not valid UTF-8" | In Excel: *Save As → CSV UTF-8 (Comma delimited)*. |
| CSV rejected "Row N has X values…" | A row has too many/few commas; values that contain commas must be in quotes. |
| Dates rejected | Use `YYYY-MM-DD` (e.g. `2025-01-31`), not `31/01/2025`. |
| Intensity shows *Unavailable* | Read the reason shown: missing/zero production, partial coverage, differing scope, overlapping records. |
| Reset everything | Close the app and delete the database file (after making a backup). |

## Maintenance

- **Dependencies:** all free/open source. Update with `pip install --upgrade -r requirements.txt`, then run the tests.
- **Adding a unit:** add one entry to `_UNIT_LIST` in `domain/units.py` (with its exact factor) and a test.
- **Schema changes:** bump `SCHEMA_VERSION` and add an upgrade step to `MIGRATIONS` in `database.py`; the app refuses
  databases from newer versions instead of modifying them.

## Known limitations

- Only **interval consumption** is supported. Cumulative meter readings are rejected rather than summed incorrectly.
- Conversions that need extra data (volume ↔ energy, mass ↔ energy, mass ↔ volume) are not provided; they are refused
  with an explanation.
- No cost, carbon, benchmarking, forecasting, cause diagnosis or savings estimation.
- Single user, no authentication, no cloud sync; rejected import rows are shown in the import screen but not stored.
- Results are only as good as the records entered; synthetic demo values are not benchmarks.

## Publishing to GitHub (multiple-account safe)

Create an **empty** repository named `textile-resource-intelligence` under the account `vipintk2807` on GitHub (no
README/licence), then in CMD from the project folder:

```bat
git init -b main
git config user.name "Vipin T K"
git config user.email "YOUR-ID+vipintk2807@users.noreply.github.com"
git config --local --list
ssh -T git@github-vipintk2807
git remote add origin git@github-vipintk2807:vipintk2807/textile-resource-intelligence.git
git remote -v
git add .
git status
git commit -m "Initial implementation of Textile Resource Intelligence"
git branch --show-current
git push -u origin main
```

Before pushing, check: the `user.name`/`user.email` shown are the *repository-local* ones; `ssh -T` greets
`vipintk2807`; `git remote -v` shows `github-vipintk2807:vipintk2807/...`; `git status` lists no `.db`, `.env`, log or
private planning files (they are in `.gitignore`). Use the no-reply email shown in GitHub → Settings → Emails.
Never put tokens or passwords in files or URLs.

## License

MIT — see [LICENSE](LICENSE).

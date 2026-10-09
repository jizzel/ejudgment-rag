# E-Judgment Scraper for GhaLII

A Python scraper that collects court judgments from the [Ghana Legal Information Institute (GhaLII)](https://ghalii.org/judgments/all/) and saves them as structured data for research, search and analysis.

The project has two stages:

1. **Scraper** (`src/main.py`) crawls GhaLII year by year, collects each judgment's metadata, page text and PDF link, and saves the results as JSON, SQLite and CSV.
2. **PDF extractor** (`src/pdf_extractor.py`) reads the latest scrape, downloads each judgment's source PDF and extracts its text.

## RAG foundation (M1)

The project is becoming a source-grounded legal research assistant; see `AGENTS.md` for the contract. **The scraper below is frozen and must not be run** (GhaLII prohibits scraping and bulk downloading). The new `src/ejudgment` package imports the existing local export into PostgreSQL instead:

```bash
poetry install                       # downloads Python packages
docker compose up -d postgres        # downloads the pgvector/pgvector:pg17 image; host port 5434
poetry run alembic upgrade head
poetry run python -m ejudgment.worker.ingest legacy \
  --source output/pdf/judgments_with_text.db --pdf-base-dir . --dry-run   # drop --dry-run to write
poetry run ruff check . && poetry run mypy && poetry run pytest
```

The import opens the export read-only, verifies each local file against its record, quarantines records it cannot trust, and is idempotent (a second run changes nothing).

### Research UI (M4 slice 1)

Once the corpus is imported, chunked and embedded (see `CLAUDE.md` for every command), run the API and the local web UI:

```bash
poetry run uvicorn ejudgment.api.main:app                 # API on :8000 (answers need Ollama or the opt-in OpenAI provider)
npm --prefix ui install && npm --prefix ui run dev        # UI on http://127.0.0.1:3000 (loopback only)
```

The UI offers search with filters, source-grounded answers with numbered citations and verified page pinpoints, and a passage viewer. Every page credits GhaLII (CC BY-NC 4.0) and links the original judgment. There is no sign-in yet, so keep it on localhost. See `ui/README.md`.

## Features

- **Year discovery:** finds the years that have judgments by reading the year links on the listing page. If there are none, it scans the page text, then probes each year's URL, and as a last resort uses 2020 to the current year.
- **Month-by-month crawling:** walks the month filter within each year and follows the "Next" pagination on every month. If a year has no month filter, it pages through the year listing directly.
- **Incremental updates:** loads the most recent previous scrape and only fetches judgments whose URLs are not already in it. The new results are merged with the old ones and duplicates are removed.
- **Detailed records:** each judgment includes every field in GhaLII's metadata list (citation, court, judges, judgment date and so on), the page's full text, the source PDF link, the page URL and a scrape timestamp.
- **Multiple output formats:** JSON, SQLite (`judgments` table) and CSV.
- **PDF text extraction:** downloads source PDFs with PyPDF2, extracts their text, records a status for each judgment, and can keep the PDFs on disk sorted by year.
- **Rate limiting:** waits between requests (about 1 second) so the server is not overloaded.

## Requirements

- Python **3.13+**
- [Poetry](https://python-poetry.org/) (recommended) or `pip`

Dependencies (declared in `pyproject.toml`):

| Package          | Purpose                          |
| ---------------- | -------------------------------- |
| `requests`       | HTTP requests                    |
| `beautifulsoup4` | HTML parsing                     |
| `lxml`           | Parser backend for BeautifulSoup |
| `pandas`         | Data handling and export         |
| `pypdf2`         | PDF text extraction              |

## Installation

```bash
git clone <repository-url>
cd ejudgment_scraper

# With Poetry
poetry install

# Or with pip
python -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 lxml pandas "pypdf2>=3.0.1,<4.0.0"
```

## Usage

> Run every command from the **repository root**. Both scripts read and write the `output/` directory relative to the current working directory.

### 1. Scrape judgments

```bash
poetry run python src/main.py
```

By default the scraper discovers every available year and scrapes all of them. To scrape only some years, edit the call at the bottom of `src/main.py`:

```python
if __name__ == "__main__":
    # main()                                  # Auto-discover and scrape all years
    main(start_year=2023, end_year=2025)      # Scrape a specific range (inclusive)
```

If you pass only one of the two years, the other one is filled in from the discovered range.

**Re-running the scraper** loads the most recent `output/judgments_*/judgments_*.json` and only scrapes new judgments. Every run that finds new judgments writes a new timestamped folder containing the **full merged dataset**, so the latest folder always holds everything. If no new judgments are found, nothing is written.

When the run finishes, the log shows the total number of judgments and how many there are per year.

### 2. Extract text from the PDFs

```bash
poetry run python src/pdf_extractor.py
```

This script:

1. Finds the most recent `output/judgments_*` folder and loads its JSON file.
2. Downloads each judgment's `pdf_download_link`.
3. Extracts the text and adds these fields to each record:
   - `pdf_text`: the extracted text
   - `pdf_extraction_status`: `success`, `no_url`, `download_failed` or `extraction_failed`
   - `pdf_text_length`: number of characters extracted
   - `pdf_local_path`: where the PDF was saved (when saving is enabled)
4. Saves the PDFs to `output/pdf/downloaded_pdfs_<year>/`, sorted by judgment year.
5. Writes the results to `output/pdf/` and logs a summary of the extraction.

You can change these settings in the `__main__` block of `src/pdf_extractor.py`:

| Parameter          | Default        | Description                                       |
| ------------------ | -------------- | ------------------------------------------------- |
| `pdf_download_dir` | `output/pdf`   | Where to save the PDFs. Set it to `None` to skip saving them. |
| `max_judgments`    | `None`         | Limit how many judgments are processed (e.g. `5` for a test run) |
| `delay_seconds`    | `1.0`          | Wait between PDF downloads                        |

The module also has a `search_in_judgments(df, term)` helper for searching the extracted text with a keyword.

> PyPDF2 only reads text that is embedded in the PDF. Scanned judgments with no text layer will get the status `extraction_failed`, and those need OCR.

## Output

```
output/
├── judgments_<YYYYMMDD_HHMMSS>/       # One folder per scrape run
│   ├── judgments_<timestamp>.json
│   ├── judgments_<timestamp>.db       # SQLite, table: judgments
│   └── judgments_<timestamp>.csv
└── pdf/
    ├── judgments_with_text.json       # pdf_text cut to 500 characters
    ├── judgments_with_text.db         # Full pdf_text (table: judgments)
    ├── judgments_with_text.csv        # Metadata only (pdf_text left out)
    └── downloaded_pdfs_<year>/        # Source PDFs, named by citation
```

The `output/` directory is git-ignored.

### Example: query the SQLite database

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("output/pdf/judgments_with_text.db")
df = pd.read_sql("SELECT citation, judgment_date, pdf_extraction_status FROM judgments", conn)
```

Column names come from GhaLII's metadata labels, which are lowercased with spaces replaced by underscores (e.g. "Judgment date" becomes `judgment_date`). The exact columns depend on what the site shows for each judgment.

## Project structure

```
.
├── src/
│   ├── main.py              # Scraper: year discovery, crawling, export
│   ├── pdf_extractor.py     # PDF download and text extraction
│   └── ejudgment_scraper/   # Package placeholder
├── tests/
├── output/                  # Generated data (git-ignored)
├── pyproject.toml           # Project metadata and dependencies
├── poetry.lock
└── README.md
```

## Codebase guide (for contributors and AI agents)

Both stages are **standalone scripts** with no shared code: they import nothing from each other or from `src/ejudgment_scraper/` (that package is empty). They are only linked through files on disk in `output/`. There are no CLI arguments, config files or environment variables. All configuration is done by editing the `if __name__ == "__main__":` block of each script.

### Data flow

```
ghalii.org/judgments/all/                      ─┐
  └─ /<year>/        (month filter)             │  src/main.py
       └─ /<year>/<month>/?page=N  (listings)   │
            └─ /akn/gh/judgment/...  (detail)   │
                                               ─┘
        ▼
output/judgments_<ts>/judgments_<ts>.{json,db,csv}   ◄── also read back by main.py on the next run (incremental)
        ▼
src/pdf_extractor.py  (reads the newest judgments_<ts>.json, follows pdf_download_link)
        ▼
output/pdf/judgments_with_text.{json,db,csv} + downloaded_pdfs_<year>/*.pdf
```

### `src/main.py` (scraper)

Call order: `main()` → `discover_available_years()` → `get_judgment_links_for_year()` for each year → `_get_links_from_paginated_url()` for each month → `scrape_judgment_details()` for each new link → `save_to_*()`.

| Symbol | Location | Responsibility |
| ------ | -------- | -------------- |
| `BASE_URL` | `src/main.py:19` | Site root (`https://ghalii.org`) |
| `discover_available_years()` | `src/main.py:22` | Works out which years to scrape (year links, then page-text regex, then URL probing, then the 2020–now fallback) |
| `_get_links_from_paginated_url()` | `src/main.py:98` | Follows `?page=N` until there is no "Next" link. Collects judgment URLs and fills the shared `seen_links` set |
| `get_judgment_links_for_year()` | `src/main.py:155` | Reads the month links in `div#monthFilter`. If there are none, pages through the year URL directly |
| `scrape_judgment_details()` | `src/main.py:206` | Parses one judgment page into a flat `dict` |
| `save_to_json/sqlite/csv()` | `src/main.py:258`–`275` | Thin pandas export wrappers |
| `main()` | `src/main.py:281` | Loads the previous scrape, filters out known URLs, merges the results, writes the new output folder and logs the per-year stats |

HTML selectors it depends on (update these if GhaLII changes its markup):

| What | Selector |
| ---- | -------- |
| Listing table | `div#doc-table` |
| Judgment links | `a[href]` matching `/akn/.*/judgment/` |
| Month filter | `div#monthFilter` with links matching `/judgments/all/<year>/<m>/` |
| Pagination | `ul.pagination` containing an `a` with the text `Next` |
| Metadata | `dl.document-metadata-list` (`dt`/`dd` pairs) |
| PDF link | the first `a` whose `href` contains `source` |
| Body text | `div.judgment-content`, or failing that `div.document-content` |

### `src/pdf_extractor.py` (PDF stage)

| Symbol | Location | Responsibility |
| ------ | -------- | -------------- |
| `download_pdf()` | `src/pdf_extractor.py:19` | GETs the PDF bytes, or returns `None` on error |
| `extract_text_from_pdf()` | `src/pdf_extractor.py:39` | Runs PyPDF2 on each page and joins the text with blank lines |
| `process_judgment_with_pdf()` | `src/pdf_extractor.py:71` | Processes one record: download, optionally save, extract, then set the `pdf_*` fields |
| `process_judgments_from_json()` | `src/pdf_extractor.py:126` | Batch driver: loads the JSON, sorts the PDFs into folders by year, logs a summary and writes the 3 outputs |
| `search_in_judgments()` | `src/pdf_extractor.py:240` | Substring search over `pdf_text` |
| `__main__` block | `src/pdf_extractor.py:266` | Finds the latest scrape and holds the run configuration |

### Record schema

Every row is a flat dict. The keys come from two places:

- **Dynamic keys** taken from the `dt` labels on the page (e.g. `citation`, `court`, `judges`, `judgment_date`). They vary from judgment to judgment, so do not assume a fixed column set.
- **Fixed keys** added by the code:
  - `main.py`: `pdf_download_link` (`'N/A'` if missing), `full_text` (`'N/A'` if missing), `url` (the unique key used for dedupe), `scrape_timestamp`
  - `pdf_extractor.py`: `pdf_text`, `pdf_extraction_status`, `pdf_text_length`, `pdf_local_path`

### Conventions and gotchas

- **Paths are relative to the CWD.** `output/` and `debug_page.html` resolve against wherever the script is launched from.
- **"Latest" is decided by the folder's mtime** (`os.path.getmtime`), not by the timestamp in its name. Touching an old folder changes which one counts as the latest.
- **`url` is the identity key.** Incremental filtering and `drop_duplicates(subset=['url'])` both depend on it.
- **The SQLite table is always `judgments`** and is written with `if_exists='replace'`.
- **The PDF stage overwrites** its fixed output filenames in `output/pdf/` on every run, and it reprocesses every record, not just new ones.
- **The JSON from the PDF stage is lossy**: `pdf_text` is cut to 500 characters. Use the `.db` file for the full text. The CSV leaves `pdf_text` out.
- **Logging** goes through the `logging` module at INFO level, with no `print` calls. Keep it that way.
- **Politeness delays** are `time.sleep(1)` between listing pages and between judgments, and `0.5`s while probing years. Keep them when changing the crawl logic.
- **Tests:** `tests/` is only a placeholder for now. There is no test suite.

## Troubleshooting

- **`debug_page.html` shows up in the repo root:** a judgment page had no metadata list. The scraper saves that page's HTML so you can look at it, and then skips the judgment.
- **The scraper re-downloads everything:** check that `output/` holds an earlier `judgments_*` folder with a JSON file in it, and that you are running from the repository root.
- **Many `extraction_failed` statuses:** those PDFs are probably scanned images, which need OCR.

## Responsible use

Please respect GhaLII's terms of use and keep the request delays in place. The judgments are public legal information, but the site is a shared public resource.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The project is evolving from a GhaLII scraper into a source-grounded legal RAG. The full development contract (source rights, schema, pipelines, provider interfaces, testing gates, milestones) lives in AGENTS.md and is binding:

@AGENTS.md

## Legacy scripts (frozen — do not run)

`src/main.py` (scraper) and `src/pdf_extractor.py` (PDF download + PyPDF2 text) produced the local export in `output/` (not in Git). Do **not** run or extend them: GhaLII prohibits scraping and bulk downloading. Work from the existing export, primarily `output/pdf/judgments_with_text.db` (table `judgments`, full `pdf_text`). Open it read-only, e.g. `sqlite3 -readonly output/pdf/judgments_with_text.db`.

Behaviours to keep in mind when reading or adapting them:
- Both resolve `output/` relative to the CWD and pick the "latest" export folder by mtime. New code must take explicit paths instead.
- Record columns come from GhaLII's metadata labels (lowercased, spaces → `_`), so treat the schema as dynamic. `url` (an AKN expression URI) is the unique record identity.
- `judgments_with_text.json` truncates `pdf_text` to 500 characters; never use it as full text.

## Commands

Python 3.13+, Poetry (`poetry install`). There is no ruff/mypy/pytest configuration yet; adding it is part of milestone M1 in AGENTS.md. Once it exists: `poetry run ruff check .`, `poetry run mypy src`, `poetry run pytest` (single test: `poetry run pytest tests/unit/test_x.py::test_name`).

Do not commit to git. Always leave commit task to me.

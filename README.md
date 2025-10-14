# E-Judgment Scraper for Ghalii

This project contains a Python-based web scraper designed to download judgments from the Ghana Legal Information Institute (Ghalii) website (`ghalii.org`). It automates the process of discovering available years, fetching judgment data, and saving it in multiple formats for analysis.

## Features

*   **Automatic Year Discovery:** The scraper intelligently discovers all available years of judgments by scanning the website.
*   **Comprehensive Scraping:** It extracts detailed information for each judgment, including:
    *   Metadata (case number, parties, court, etc.)
    *   Full text of the judgment
    *   A direct link to the source PDF
*   **Multiple Output Formats:** The scraped data is saved in three convenient formats:
    *   JSON (`.json`)
    *   SQLite Database (`.db`)
    *   CSV (`.csv`)
*   **Organized Output:** All output files are stored in a dedicated `output/` directory, with each filename timestamped to prevent overwrites.
*   **Robust and Respectful:** The scraper handles pagination automatically and includes delays between requests to avoid overloading the server.

## Requirements

The project is built with Python and requires the following libraries:

*   `requests`
*   `beautifulsoup4`
*   `pandas`
*   `lxml`

These dependencies are listed in the `pyproject.toml` file.

## How to Use

1.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd ejudgment_scraper
    ```

2.  **Install Dependencies:**
    If you have [Poetry](https://python-poetry.org/) installed, you can install the dependencies with:
    ```bash
    poetry install
    ```

3.  **Run the Scraper:**
    To start the scraping process, run the `main.py` script:
    ```bash
    python src/main.py
    ```
    The scraper will automatically discover all available years and begin fetching judgments.

4.  **Find the Output:**
    Once the process is complete, you will find the timestamped output files (`.json`, `.db`, and `.csv`) in the `output/` directory.

## Configuration

### Manual Year Selection

You can also specify a range of years to scrape by modifying the `main()` function call in `src/main.py`. For example, to scrape only judgments from 2023 to 2025:

```python
if __name__ == "__main__":
    # main()  # Auto-discover all years
    main(start_year=2023, end_year=2025) # Scrape a specific range
```

## Project Structure

```
.
├── output/              # Directory for all scraped data files
├── src/
│   └── main.py          # The main scraper script
├── pyproject.toml       # Project metadata and dependencies
├── README.md            # This file
└── ...
```

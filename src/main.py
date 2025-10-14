import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import time
from typing import List, Dict, Optional, Set
import logging
import re
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BASE_URL = "https://ghalii.org"


def discover_available_years() -> List[int]:
    """
    Discovers available years by checking the main page and extracting years from judgment dates.
    Also tries to validate years by checking if year-specific URLs return results.

    Returns:
        Sorted list of available years
    """
    logging.info("Discovering available years...")
    years = set()

    # Method 1: Extract years from the main "all judgments" page
    try:
        response = requests.get(f"{BASE_URL}/judgments/all/", timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        # Find all judgment dates in the table
        doc_table_div = soup.find('div', id='doc-table')
        if doc_table_div:
            # Look for date patterns (e.g., "16 September 2025", "2025", etc.)
            text_content = doc_table_div.get_text()
            # Find 4-digit years
            year_matches = re.findall(r'\b(20\d{2})\b', text_content)
            for year in year_matches:
                years.add(int(year))

            logging.info(f"Found years from main page: {sorted(years)}")
    except Exception as e:
        logging.error(f"Error discovering years from main page: {e}")

    # Method 2: Try common year ranges to see what exists
    current_year = datetime.now().year
    start_probe_year = 2000  # Adjust based on when the database likely started

    if not years:
        logging.info("No years found on main page. Probing year URLs...")
        for year in range(current_year, start_probe_year - 1, -1):
            try:
                test_url = f"{BASE_URL}/judgments/all/{year}/"
                response = requests.get(test_url, timeout=10)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'lxml')
                    doc_table = soup.find('div', id='doc-table')
                    # Check if there are actual judgments (not just an empty page)
                    if doc_table and doc_table.find('a', href=lambda h: h and '/akn/gh/judgment/' in h):
                        years.add(year)
                        logging.info(f"Found judgments for year: {year}")
                else:
                    logging.debug(f"No content for year {year}")
                time.sleep(0.5)  # Be respectful
            except Exception as e:
                logging.debug(f"Error probing year {year}: {e}")

    if not years:
        # Fallback: return a sensible default range
        logging.warning("Could not discover years automatically. Using default range.")
        return list(range(2020, current_year + 1))

    sorted_years = sorted(years)
    logging.info(f"Available years: {sorted_years}")
    return sorted_years


def get_judgment_links_for_year(year: int) -> List[str]:
    """
    Gets all judgment links for a specific year, handling pagination.

    Args:
        year: The year to scrape judgments from

    Returns:
        List of judgment URLs
    """
    judgment_links = []
    page = 1

    while True:
        list_url = f"{BASE_URL}/judgments/all/{year}/?page={page}"
        logging.info(f"Scraping page {page} for year {year}: {list_url}")

        try:
            response = requests.get(list_url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching {list_url}: {e}")
            break

        soup = BeautifulSoup(response.content, 'lxml')

        # Find the document table
        doc_table_div = soup.find('div', id='doc-table')

        if not doc_table_div:
            logging.warning(f"No document table found for {year} on page {page}")
            break

        # Find all judgment links
        links_on_page = doc_table_div.find_all('a', href=True)

        links_found_on_page = 0
        for link in links_on_page:
            href = link['href']
            if '/akn/gh/judgment/' in href:
                full_link = BASE_URL + href if href.startswith('/') else href
                if full_link not in judgment_links:
                    judgment_links.append(full_link)
                    links_found_on_page += 1

        logging.info(f"Found {links_found_on_page} new judgments on page {page}")

        # Check if there are no judgments on this page (reached the end)
        if links_found_on_page == 0:
            logging.info(f"No new judgments found on page {page}. Ending pagination.")
            break

        # Check for pagination - look for "Next" button or higher page numbers
        pagination = soup.find('ul', class_='pagination')
        if pagination:
            # Check for Next link
            next_link = pagination.find('a', string=lambda t: t and 'Next' in t)
            if not next_link:
                # Try alternative patterns
                next_link = pagination.find('a', attrs={'aria-label': 'Next'})

            if not next_link or 'disabled' in next_link.get('class', []):
                logging.info(f"No more pages for year {year}")
                break
        else:
            # If no pagination found, assume single page
            logging.info(f"No pagination found for year {year}")
            break

        page += 1
        time.sleep(1)  # Be respectful to the server

    logging.info(f"Total judgments found for {year}: {len(judgment_links)}")
    return judgment_links


def scrape_judgment_details(judgment_url: str) -> Optional[Dict]:
    """
    Scrapes the details from a single judgment page.

    Args:
        judgment_url: URL of the judgment page

    Returns:
        Dictionary containing judgment details or None if scraping fails
    """
    logging.info(f"Scraping judgment: {judgment_url}")

    try:
        response = requests.get(judgment_url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching {judgment_url}: {e}")
        return None

    soup = BeautifulSoup(response.content, 'lxml')

    # Find metadata
    metadata_list = soup.find('dl', class_='document-metadata-list')
    if not metadata_list:
        logging.warning(f"Could not find metadata on {judgment_url}")
        # Save problem page for debugging
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        return None

    details = {}

    # Extract all metadata fields
    for dt in metadata_list.find_all('dt'):
        dd = dt.find_next_sibling('dd')
        if dt and dd:
            key = dt.get_text(strip=True).lower().replace(' ', '_').replace(':', '')
            value = dd.get_text(strip=True)
            details[key] = value

    # Extract PDF link
    pdf_link_element = soup.find('a', href=lambda href: href and 'source' in href)
    details['pdf_download_link'] = BASE_URL + pdf_link_element['href'] if pdf_link_element else 'N/A'

    # Extract judgment text content if available
    content_div = soup.find('div', class_='judgment-content') or soup.find('div', class_='document-content')
    if content_div:
        details['full_text'] = content_div.get_text(strip=True, separator='\n')
    else:
        details['full_text'] = 'N/A'

    details['url'] = judgment_url
    details['scrape_timestamp'] = pd.Timestamp.now().isoformat()

    return details


def save_to_json(dataframe: pd.DataFrame, filename: str):
    """Saves a DataFrame to a JSON file."""
    dataframe.to_json(filename, orient='records', indent=4)
    logging.info(f"Data saved to {filename}")


def save_to_sqlite(dataframe: pd.DataFrame, db_name: str, table_name: str):
    """Saves a DataFrame to a SQLite database."""
    try:
        conn = sqlite3.connect(db_name)
        dataframe.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
        logging.info(f"Data saved to {db_name} in table {table_name}")
    except sqlite3.Error as e:
        logging.error(f"Error saving to SQLite: {e}")


def save_to_csv(dataframe: pd.DataFrame, filename: str):
    """Saves a DataFrame to a CSV file."""
    dataframe.to_csv(filename, index=False, encoding='utf-8')
    logging.info(f"Data saved to {filename}")


def main(start_year: Optional[int] = None, end_year: Optional[int] = None):
    """
    Main function to scrape judgments.

    Args:
        start_year: First year to scrape (inclusive). If None, auto-discovers.
        end_year: Last year to scrape (inclusive). If None, auto-discovers.
    """
    # Discover available years if not specified
    if start_year is None or end_year is None:
        available_years = discover_available_years()
        if not available_years:
            logging.error("No years could be discovered. Exiting.")
            return

        start_year = start_year or min(available_years)
        end_year = end_year or max(available_years)

    logging.info(f"Scraping judgments from {start_year} to {end_year}")

    all_judgments = []
    years_to_scrape = range(start_year, end_year + 1)

    for year in years_to_scrape:
        logging.info(f"\n{'=' * 60}")
        logging.info(f"Starting scrape for year {year}")
        logging.info(f"{'=' * 60}\n")

        judgment_links = get_judgment_links_for_year(year)

        for i, link in enumerate(judgment_links, 1):
            logging.info(f"Processing judgment {i}/{len(judgment_links)} for {year}")
            details = scrape_judgment_details(link)
            if details:
                all_judgments.append(details)
            time.sleep(1)  # Be respectful to the server

    if all_judgments:
        df = pd.DataFrame(all_judgments)

        logging.info(f"\n{'=' * 60}")
        logging.info(f"SCRAPING COMPLETE")
        logging.info(f"{'=' * 60}")
        logging.info(f"Total judgments scraped: {len(df)}")

        # Display sample
        logging.info("\nSample of scraped data:")
        print(df.head().to_string())

        # Save to multiple formats
        save_to_json(df, 'judgments.json')
        save_to_sqlite(df, 'judgments.db', 'judgments')
        save_to_csv(df, 'judgments.csv')

        # Print summary statistics
        logging.info("\n" + "=" * 60)
        logging.info("SUMMARY STATISTICS")
        logging.info("=" * 60)

        if 'judgment_date' in df.columns:
            logging.info("\nJudgments by date:")
            print(df['judgment_date'].value_counts().sort_index().head(20))

        logging.info(f"\nColumns in dataset: {list(df.columns)}")
        logging.info(f"\nDataset shape: {df.shape}")
    else:
        logging.warning("No judgments were scraped.")


if __name__ == "__main__":
    # Auto-discover and scrape all available years
    main()

    # Or specify years manually:
    # main(start_year=2023, end_year=2025)
import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import time
from typing import List, Dict, Optional, Set
import logging
import re
import os
import glob
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BASE_URL = "https://ghalii.org"


def discover_available_years() -> List[int]:
    """
    Discovers available years by checking the main page for a list of year links,
    then falling back to other methods like scanning for dates or probing URLs.

    Returns:
        Sorted list of available years.
    """
    logging.info("Discovering available years...")
    years: Set[int] = set()

    try:
        response = requests.get(f"{BASE_URL}/judgments/all/", timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        # Method 1: Look for a dedicated list of years, as described by the user.
        year_links = soup.find_all('a', string=re.compile(r'^\s*\d{4}\s*$'))
        if year_links:
            logging.info("Found year links on the page.")
            for link in year_links:
                try:
                    year = int(link.get_text(strip=True))
                    if 1900 < year < 2100:  # Basic validation
                        years.add(year)
                except ValueError:
                    continue  # Ignore links that are not valid years
            if years:
                logging.info(f"Discovered years from links: {sorted(list(years))}")

        # Method 2: If no year links are found, scan the text for years.
        if not years:
            logging.info("No dedicated year links found. Scanning page content for years.")
            doc_table_div = soup.find('div', id='doc-table')
            if doc_table_div:
                text_content = doc_table_div.get_text()
                year_matches = re.findall(r'\b(19\d{2}|20\d{2})\b', text_content)
                for year in year_matches:
                    years.add(int(year))
                if years:
                    logging.info(f"Found years from main page content: {sorted(list(years))}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Error discovering years from main page: {e}")

    # Method 3: If still no years, probe year-specific URLs.
    if not years:
        logging.info("No years found on main page. Probing year URLs...")
        current_year = datetime.now().year
        for year in range(current_year, 1960 - 1, -1):
            try:
                test_url = f"{BASE_URL}/judgments/all/{year}/"
                response = requests.get(test_url, timeout=10)
                if response.status_code == 200:
                    soup_probe = BeautifulSoup(response.content, 'lxml')
                    doc_table = soup_probe.find('div', id='doc-table')
                    if doc_table and doc_table.find('a', href=re.compile(r'/akn/.*/judgment/')):
                        years.add(year)
                        logging.info(f"Found judgments for year: {year}")
                else:
                    logging.debug(f"No content for year {year}")
                time.sleep(0.5)  # Be respectful
            except requests.exceptions.RequestException as e:
                logging.debug(f"Error probing year {year}: {e}")

    # Fallback to a default range if no years could be discovered
    if not years:
        logging.warning("Could not discover years automatically. Using default range.")
        current_year = datetime.now().year
        return list(range(2020, current_year + 1))

    sorted_years = sorted(list(years))
    logging.info(f"Discovered available years: {sorted_years}")
    return sorted_years


def _get_links_from_paginated_url(start_url: str, seen_links: Set[str]) -> List[str]:
    """
    Helper function to scrape all judgment links from a paginated URL.

    Args:
        start_url: The initial URL to start scraping from (e.g., a month-specific URL).
        seen_links: A set of already collected links to avoid duplicates.

    Returns:
        A list of new, unique judgment URLs found.
    """
    newly_found_links = []
    page = 1
    while True:
        # Append page parameter correctly, handling existing query strings
        paginated_url = f"{start_url}?page={page}" if '?' not in start_url else f"{start_url}&page={page}"
        logging.info(f"Scraping: {paginated_url}")

        try:
            response = requests.get(paginated_url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching {paginated_url}: {e}")
            break

        soup = BeautifulSoup(response.content, 'lxml')
        doc_table_div = soup.find('div', id='doc-table')
        if not doc_table_div:
            logging.warning(f"No document table found on {paginated_url}")
            break

        links_on_page = doc_table_div.find_all('a', href=re.compile(r'/akn/.*/judgment/'))
        if not links_on_page and page == 1:
            logging.info(f"No judgment links found on the first page of {start_url}.")
            break

        links_found_this_page = 0
        for link in links_on_page:
            href = link['href']
            full_link = BASE_URL + href if href.startswith('/') else href
            if full_link not in seen_links:
                newly_found_links.append(full_link)
                seen_links.add(full_link)
                links_found_this_page += 1

        logging.info(f"Found {links_found_this_page} new judgments on page {page}.")

        pagination = soup.find('ul', class_='pagination')
        next_link = pagination.find('a', string='Next') if pagination else None
        if not next_link:
            logging.info(f"No 'Next' button found. Ending pagination for {start_url}.")
            break

        page += 1
        time.sleep(1)
    return newly_found_links

def get_judgment_links_for_year(year: int) -> List[str]:
    """
    Gets all judgment links for a specific year, handling pagination.

    Args:
        year: The year to scrape judgments from

    Returns:
        List of judgment URLs
    """
    all_judgment_links = []
    seen_links = set()
    year_url = f"{BASE_URL}/judgments/all/{year}/"
    logging.info(f"Fetching available months for year {year} from {year_url}")

    try:
        response = requests.get(year_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        # Find the navigation element containing month links
        month_nav = soup.find('div', id='monthFilter')
        if not month_nav:
            logging.warning(f"No month navigation found for {year}. Scraping year directly.")
            # Fallback to scraping the year URL directly if no months are listed
            all_judgment_links.extend(_get_links_from_paginated_url(year_url, seen_links))
        else:
            month_links = month_nav.find_all('a', href=re.compile(rf'/judgments/all/{year}/\d{{1,2}}/?$'))
            if not month_links:
                logging.warning(f"Month navigation present, but no month links found for {year}. Scraping year directly.")
                all_judgment_links.extend(_get_links_from_paginated_url(year_url, seen_links))
            else:
                month_urls = [BASE_URL + link['href'] for link in month_links]
                logging.info(f"Found {len(month_urls)} months with judgments for {year}.")

                for month_url in month_urls:
                    logging.info(f"\n--- Scraping month: {month_url} ---")
                    links_for_month = _get_links_from_paginated_url(month_url, seen_links)
                    all_judgment_links.extend(links_for_month)
                    logging.info(f"Found {len(links_for_month)} new judgments for this month.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Could not fetch month list for year {year}: {e}")
        # Attempt to scrape the year directly as a last resort
        logging.info(f"Attempting to scrape year {year} directly as a fallback.")
        all_judgment_links.extend(_get_links_from_paginated_url(year_url, seen_links))

    logging.info(f"Total unique judgments found for {year}: {len(all_judgment_links)}")
    return all_judgment_links


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

    metadata_list = soup.find('dl', class_='document-metadata-list')
    if not metadata_list:
        logging.warning(f"Could not find metadata on {judgment_url}")
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        return None

    details = {}

    for dt in metadata_list.find_all('dt'):
        dd = dt.find_next_sibling('dd')
        if dt and dd:
            key = dt.get_text(strip=True).lower().replace(' ', '_').replace(':', '')
            value = dd.get_text(strip=True)
            details[key] = value

    pdf_link_element = soup.find('a', href=lambda href: href and 'source' in href)
    details['pdf_download_link'] = BASE_URL + pdf_link_element['href'] if pdf_link_element else 'N/A'

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
    Main function to scrape judgments. Can update an existing scrape.

    Args:
        start_year: First year to scrape (inclusive). If None, auto-discovers.
        end_year: Last year to scrape (inclusive). If None, auto-discovers.
    """
    base_output_dir = "output"
    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)

    existing_judgments_df = pd.DataFrame()
    existing_links = set()
    try:
        judgment_dirs = [d for d in glob.glob(os.path.join(base_output_dir, 'judgments_*')) if os.path.isdir(d)]
        if judgment_dirs:
            latest_judgment_dir = max(judgment_dirs, key=os.path.getmtime)
            json_files = glob.glob(os.path.join(latest_judgment_dir, 'judgments_*.json'))
            if json_files:
                latest_json_file = max(json_files, key=os.path.getmtime)
                logging.info(f"Loading existing data from {latest_json_file} to update.")
                existing_judgments_df = pd.read_json(latest_json_file)
                if 'url' in existing_judgments_df.columns:
                    existing_links = set(existing_judgments_df['url'].dropna())
                logging.info(f"Found {len(existing_links)} existing judgments.")
    except Exception as e:
        logging.warning(f"Could not load existing judgment data: {e}")

    if start_year is None or end_year is None:
        available_years = discover_available_years()
        if not available_years:
            logging.error("No years could be discovered. Exiting.")
            return
        start_year = start_year or min(available_years)
        end_year = end_year or max(available_years)

    logging.info(f"Scraping judgments from {start_year} to {end_year}")

    newly_scraped_judgments = []
    years_to_scrape = range(start_year, end_year + 1)

    for year in years_to_scrape:
        logging.info(f"\n{'=' * 60}")
        logging.info(f"Starting scrape for year {year}")
        logging.info(f"{'=' * 60}\n")

        judgment_links = get_judgment_links_for_year(year)
        
        new_links_for_year = [link for link in judgment_links if link not in existing_links]
        logging.info(f"Found {len(judgment_links)} total links for {year}. {len(new_links_for_year)} are new.")

        for i, link in enumerate(new_links_for_year, 1):
            logging.info(f"Processing new judgment {i}/{len(new_links_for_year)} for {year}")
            details = scrape_judgment_details(link)
            if details:
                newly_scraped_judgments.append(details)
            time.sleep(1)

    if newly_scraped_judgments:
        new_judgments_df = pd.DataFrame(newly_scraped_judgments)
        
        all_judgments_df = pd.concat([existing_judgments_df, new_judgments_df], ignore_index=True)
        
        if 'url' in all_judgments_df.columns:
            all_judgments_df.drop_duplicates(subset=['url'], keep='last', inplace=True)
            all_judgments_df.reset_index(drop=True, inplace=True)

        logging.info(f"\n{'=' * 60}")
        logging.info(f"SCRAPING COMPLETE")
        logging.info(f"{'=' * 60}")
        logging.info(f"Scraped {len(new_judgments_df)} new judgments.")
        logging.info(f"Total judgments now: {len(all_judgments_df)}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_output_dir = os.path.join(base_output_dir, f"judgments_{timestamp}")
        os.makedirs(new_output_dir)

        json_filename = os.path.join(new_output_dir, f"judgments_{timestamp}.json")
        sqlite_filename = os.path.join(new_output_dir, f"judgments_{timestamp}.db")
        csv_filename = os.path.join(new_output_dir, f"judgments_{timestamp}.csv")

        save_to_json(all_judgments_df, json_filename)
        save_to_sqlite(all_judgments_df, sqlite_filename, 'judgments')
        save_to_csv(all_judgments_df, csv_filename)

        # --- Summary Statistics ---
        logging.info("\n" + "=" * 60)
        logging.info("SUMMARY STATISTICS")
        logging.info("=" * 60)
        logging.info(f"Overall Total Judgments: {len(all_judgments_df)}")

        if 'judgment_date' in all_judgments_df.columns:
            # Ensure the column is in datetime format to extract the year
            all_judgments_df['judgment_date_dt'] = pd.to_datetime(all_judgments_df['judgment_date'], errors='coerce')
            all_judgments_df['year'] = all_judgments_df['judgment_date_dt'].dt.year

            logging.info("\nJudgments by Year:")
            yearly_counts = all_judgments_df['year'].value_counts().sort_index()
            for year, count in yearly_counts.items():
                logging.info(f"  - {int(year)}: {count} judgments")
    else:
        logging.info("No new judgments were found to scrape.")


if __name__ == "__main__":
    # Auto-discover and scrape all available years
    main()

    # Or specify years manually:
    # main(start_year=1963, end_year=1988)


import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import time

BASE_URL = "https://ghalii.org"

def get_judgment_links_for_year(year):
    """
    Gets all judgment links for a specific year, handling pagination.
    """
    judgment_links = []
    page = 1
    while True:
        list_url = f"{BASE_URL}/judgments/all/{year}/?page={page}"
        print(f"Scraping page: {list_url}")
        try:
            response = requests.get(list_url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {list_url}: {e}")
            break

        soup = BeautifulSoup(response.content, 'lxml')
        
        doc_table_div = soup.find('div', id='doc-table')

        if not doc_table_div:
            print(f"Could not find the document table for {year} on page {page}. The page structure may have changed.")
            break

        links_on_page = doc_table_div.find_all('a', href=True)
        
        new_links_found = False
        for link in links_on_page:
            href = link['href']
            if '/akn/gh/judgment/' in href:
                full_link = BASE_URL + href
                if full_link not in judgment_links:
                    judgment_links.append(full_link)
                    new_links_found = True

        # Check for a "Next" link to see if we should continue to the next page
        next_link = soup.find('a', string='Next')
        if not next_link:
            print(f"No more pages for year {year}.")
            break
        
        page += 1
        time.sleep(1) # Be respectful to the server

    return judgment_links

def scrape_judgment_details(judgment_url):
    """
    Scrapes the details from a single judgment page.
    """
    print(f"Scraping judgment: {judgment_url}")
    try:
        response = requests.get(judgment_url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {judgment_url}: {e}")
        return None

    soup = BeautifulSoup(response.content, 'lxml')
    
    metadata_list = soup.find('dl', class_='document-metadata-list')
    if not metadata_list:
        print(f"Could not find metadata on {judgment_url}. Saving page to detail_page.html for inspection.")
        with open("detail_page.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        return None

    details = {}
    
    for dt in metadata_list.find_all('dt'):
        dd = dt.find_next_sibling('dd')
        if dt and dd:
            key = dt.get_text(strip=True).lower().replace(' ', '_')
            value = dd.get_text(strip=True)
            details[key] = value

    pdf_link_element = soup.find('a', href=lambda href: href and 'source' in href)
    details['pdf_download_link'] = BASE_URL + pdf_link_element['href'] if pdf_link_element else 'N/A'
    details['url'] = judgment_url

    return details

def save_to_json(dataframe, filename):
    """
    Saves a DataFrame to a JSON file.
    """
    dataframe.to_json(filename, orient='records', indent=4)
    print(f"Data saved to {filename}")


def save_to_sqlite(dataframe, db_name, table_name):
    """
    Saves a DataFrame to a SQLite database.
    """
    try:
        conn = sqlite3.connect(db_name)
        dataframe.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
        print(f"Data saved to {db_name} in table {table_name}")
    except sqlite3.Error as e:
        print(f"Error saving to SQLite: {e}")


if __name__ == "__main__":
    all_judgments = []
    
    for year in range(2023, 2026):
        judgment_links = get_judgment_links_for_year(year)
        for link in judgment_links:
            details = scrape_judgment_details(link)
            if details:
                all_judgments.append(details)
            time.sleep(1) # Be respectful

    if all_judgments:
        df = pd.DataFrame(all_judgments)
        
        # Save to JSON
        save_to_json(df, 'judgments.json')

        # Save to SQLite
        save_to_sqlite(df, 'judgments.db', 'judgments')
    else:
        print("No judgments were scraped.")

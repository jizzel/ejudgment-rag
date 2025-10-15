import requests
import json
import pandas as pd
import sqlite3
from pathlib import Path
import time
import logging
from typing import Dict, List, Optional
import PyPDF2
from io import BytesIO

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def download_pdf(pdf_url: str, timeout: int = 30) -> Optional[bytes]:
    """
    Downloads a PDF from the given URL.

    Args:
        pdf_url: URL of the PDF to download
        timeout: Request timeout in seconds

    Returns:
        PDF content as bytes, or None if download fails
    """
    try:
        response = requests.get(pdf_url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading PDF from {pdf_url}: {e}")
        return None


def extract_text_from_pdf(pdf_content: bytes) -> Optional[str]:
    """
    Extracts text from PDF content using PyPDF2.

    Args:
        pdf_content: PDF file content as bytes

    Returns:
        Extracted text as string, or None if extraction fails
    """
    try:
        pdf_file = BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)

        text_parts = []
        for page_num, page in enumerate(pdf_reader.pages, 1):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            except Exception as e:
                logging.warning(f"Error extracting text from page {page_num}: {e}")
                continue

        full_text = '\n\n'.join(text_parts)
        return full_text if full_text.strip() else None

    except Exception as e:
        logging.error(f"Error reading PDF: {e}")
        return None


def process_judgment_with_pdf(judgment: Dict, download_dir: Optional[Path] = None) -> Dict:
    """
    Downloads and extracts text from a judgment's PDF.

    Args:
        judgment: Dictionary containing judgment metadata
        download_dir: Optional directory to save downloaded PDFs

    Returns:
        Updated judgment dictionary with extracted text
    """
    pdf_url = judgment.get('pdf_download_link', '')

    if not pdf_url or pdf_url == 'N/A':
        logging.warning(f"No PDF URL for judgment: {judgment.get('citation', 'Unknown')}")
        judgment['pdf_text'] = None
        judgment['pdf_extraction_status'] = 'no_url'
        return judgment

    logging.info(f"Processing: {judgment.get('citation', 'Unknown')}")

    # Download PDF
    pdf_content = download_pdf(pdf_url)
    if not pdf_content:
        judgment['pdf_text'] = None
        judgment['pdf_extraction_status'] = 'download_failed'
        return judgment

    # Optionally save PDF to disk
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        # Create safe filename from citation or URL
        citation = judgment.get('citation', 'unknown').replace('/', '_').replace(' ', '_')[:100]
        pdf_path = download_dir / f"{citation}.pdf"
        try:
            pdf_path.write_bytes(pdf_content)
            judgment['pdf_local_path'] = str(pdf_path)
        except Exception as e:
            logging.warning(f"Could not save PDF to disk: {e}")

    # Extract text
    pdf_text = extract_text_from_pdf(pdf_content)
    if pdf_text:
        judgment['pdf_text'] = pdf_text
        judgment['pdf_extraction_status'] = 'success'
        judgment['pdf_text_length'] = len(pdf_text)
        logging.info(f"✓ Extracted {len(pdf_text)} characters")
    else:
        judgment['pdf_text'] = None
        judgment['pdf_extraction_status'] = 'extraction_failed'
        logging.warning(f"✗ Could not extract text")

    return judgment


def process_judgments_from_json(
        json_file: str,
        output_json: str = 'judgments_with_pdf_text.json',
        output_db: str = 'judgments_with_pdf_text.db',
        output_csv: str = 'judgments_with_pdf_text.csv',
        pdf_download_dir: Optional[str] = None,
        max_judgments: Optional[int] = None,
        delay_seconds: float = 1.0
) -> pd.DataFrame:
    """
    Processes all judgments from a JSON file, extracting PDF text.

    Args:
        json_file: Path to input JSON file with judgment metadata
        output_json: Path for output JSON file
        output_db: Path for output SQLite database
        output_csv: Path for output CSV file
        pdf_download_dir: Optional base directory to save PDFs. Year-specific subdirectories will be created inside this directory. (None = don't save)
        max_judgments: Maximum number of judgments to process (None = all)
        delay_seconds: Delay between PDF downloads

    Returns:
        DataFrame with all judgment data including extracted PDF text
    """
    # Load existing judgments
    logging.info(f"Loading judgments from {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        judgments = json.load(f)

    total = len(judgments)
    if max_judgments:
        judgments = judgments[:max_judgments]
        logging.info(f"Processing first {len(judgments)} of {total} judgments")
    else:
        logging.info(f"Processing all {total} judgments")

    # Set up download directory if specified
    base_download_dir = Path(pdf_download_dir) if pdf_download_dir else None

    # Process each judgment
    processed_judgments = []
    for i, judgment in enumerate(judgments, 1):
        logging.info(f"\n[{i}/{len(judgments)}] {'-' * 60}")

        download_dir_for_judgment = None
        if base_download_dir:
            year = 'unknown_year'
            if judgment.get('judgment_date'):
                try:
                    year = pd.to_datetime(judgment['judgment_date']).year
                except (ValueError, TypeError):
                    logging.warning(f"Could not parse year from judgment_date: {judgment.get('judgment_date')}")

            download_dir_for_judgment = base_download_dir / f"downloaded_pdfs_{year}"

        processed = process_judgment_with_pdf(judgment, download_dir_for_judgment)
        processed_judgments.append(processed)

        # Respectful delay between downloads
        if i < len(judgments):
            time.sleep(delay_seconds)

    # Create DataFrame
    df = pd.DataFrame(processed_judgments)

    # Summary statistics
    logging.info(f"\n{'=' * 60}")
    logging.info("EXTRACTION SUMMARY")
    logging.info(f"{'=' * 60}")
    logging.info(f"Total judgments: {len(df)}")

    status_counts = df['pdf_extraction_status'].value_counts()
    for status, count in status_counts.items():
        logging.info(f"  {status}: {count}")

    if 'pdf_text_length' in df.columns:
        successful = df[df['pdf_extraction_status'] == 'success']
        if len(successful) > 0:
            logging.info(f"\nText extraction stats:")
            logging.info(f"  Average text length: {successful['pdf_text_length'].mean():.0f} chars")
            logging.info(f"  Median text length: {successful['pdf_text_length'].median():.0f} chars")
            logging.info(f"  Total text extracted: {successful['pdf_text_length'].sum():,} chars")

    # Save outputs
    logging.info(f"\nSaving results...")

    # JSON (excluding very long text for readability)
    df_for_json = df.copy()
    if 'pdf_text' in df_for_json.columns:
        df_for_json['pdf_text'] = df_for_json['pdf_text'].apply(
            lambda x: x[:500] + '...[truncated]' if x and len(x) > 500 else x
        )
    df_for_json.to_json(output_json, orient='records', indent=2)
    logging.info(f"✓ Saved to {output_json}")

    # SQLite (full text)
    try:
        conn = sqlite3.connect(output_db)
        df.to_sql('judgments', conn, if_exists='replace', index=False)
        conn.close()
        logging.info(f"✓ Saved to {output_db}")
    except Exception as e:
        logging.error(f"Error saving to SQLite: {e}")

    # CSV (excluding full text, too large for CSV)
    df_for_csv = df.copy()
    if 'pdf_text' in df_for_csv.columns:
        df_for_csv = df_for_csv.drop('pdf_text', axis=1)
    df_for_csv.to_csv(output_csv, index=False, encoding='utf-8')
    logging.info(f"✓ Saved metadata to {output_csv}")

    return df


def search_in_judgments(df: pd.DataFrame, search_term: str, case_sensitive: bool = False) -> pd.DataFrame:
    """
    Search for a term in the extracted PDF text.

    Args:
        df: DataFrame with judgments and pdf_text
        search_term: Term to search for
        case_sensitive: Whether search should be case-sensitive

    Returns:
        DataFrame with matching judgments
    """
    if 'pdf_text' not in df.columns:
        logging.error("No pdf_text column found")
        return pd.DataFrame()

    if case_sensitive:
        mask = df['pdf_text'].str.contains(search_term, na=False, regex=False)
    else:
        mask = df['pdf_text'].str.contains(search_term, na=False, case=False, regex=False)

    results = df[mask]
    logging.info(f"Found {len(results)} judgments containing '{search_term}'")
    return results


if __name__ == "__main__":
    # Find the most recent subdirectory in the 'output' directory
    output_dir = Path('output')
    try:
        # Find all directories starting with 'judgments_' in the output directory
        judgment_dirs = [d for d in output_dir.glob('judgments_*') if d.is_dir()]
        if not judgment_dirs:
            raise FileNotFoundError(f"No 'judgments_*' subdirectories found in '{output_dir}'.")

        # Get the most recent directory
        latest_judgment_dir = max(judgment_dirs, key=lambda d: d.stat().st_mtime)
        logging.info(f"Using latest judgments directory: {latest_judgment_dir}")

        # Find the JSON file within that directory
        json_files = list(latest_judgment_dir.glob('judgments_*.json'))
        if not json_files:
            raise FileNotFoundError(f"No 'judgments_*.json' files found in '{latest_judgment_dir}'.")

        # Assuming one json file, or taking the most recent if multiple
        latest_json_file = max(json_files, key=lambda f: f.stat().st_mtime)
        logging.info(f"Using latest judgments file: {latest_json_file}")

        # Define output directory for PDF related files
        pdf_output_dir = output_dir / 'pdf'
        pdf_output_dir.mkdir(exist_ok=True)

        # Process the found JSON file
        df = process_judgments_from_json(
            json_file=str(latest_json_file),
            output_json=str(pdf_output_dir / 'judgments_with_text.json'),
            output_db=str(pdf_output_dir / 'judgments_with_text.db'),
            output_csv=str(pdf_output_dir / 'judgments_with_text.csv'),
            pdf_download_dir=str(pdf_output_dir),  # Pass the parent dir for year-specific folders. Set to None if you don't want to save PDFs
            max_judgments=None,  # Process all; set to 5 for testing
            delay_seconds=1.0  # Be respectful to the server
        )

        # Example of searching in extracted text
        # if not df.empty:
        #     results = search_in_judgments(df, 'negligence')
        #     print(results[['citation', 'judgment_date']])

        # Example of accessing a specific judgment's full text
        # if not df.empty and 'pdf_text' in df.columns and pd.notna(df.iloc[0]['pdf_text']):
        #     print(df.iloc[0]['pdf_text'][:1000])

    except FileNotFoundError as e:
        logging.error(e)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

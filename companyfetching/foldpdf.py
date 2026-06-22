# bse_downloader_final_v3.py

import gradio as gr
import os
import re
import time
import requests
import threading
import queue
import traceback
from datetime import datetime
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- Configuration & Constants ---
CONFIG_FILE = 'company_config.txt'
COMMON_FOLDER_NAME = 'common_folder'

# --- Helper Functions ---

def sanitize_filename(filename: str) -> str:
    """Removes invalid characters from a string to make it a valid filename."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def log_message(output_queue: queue.Queue, message: str, level: str = "LOG"):
    """Formats and sends a log message to the UI queue."""
    if message is None:
        output_queue.put(None) # Sentinel value to stop the listener
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_queue.put(f"[{timestamp}] {level}: {message}")

def load_company_list():
    """
    Loads company list from the configuration file.
    Creates a default config if it doesn't exist.
    """
    default_companies = {
        "RELIANCE": "Reliance Industries Ltd",
        "TCS": "Tata Consultancy Services Ltd",
        "HDFCBANK": "HDFC Bank Ltd",
    }

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            f.write("# Company Configuration File\n")
            f.write("# Format: TICKER:Company Full Name\n")
            f.write("# One company per line\n\n")
            for ticker, name in default_companies.items():
                f.write(f"{ticker}:{name}\n")
        print(f"Created default config file: {CONFIG_FILE}")
        return default_companies

    companies = {}
    with open(CONFIG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and ':' in line:
                ticker, name = line.split(':', 1)
                companies[ticker.strip()] = name.strip()
    return companies if companies else default_companies

def find_ticker_for_company(company_name: str, output_queue: queue.Queue):
    """
    Finds the ticker for a given company name using screener.in's search API.
    Returns (ticker, official_name) or (None, None) if not found.
    """
    log_message(output_queue, f"Searching for ticker for '{company_name}'...", "INFO")
    try:
        search_url = f"https://www.screener.in/api/company/search/?q={company_name.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        results = response.json()

        if not results:
            log_message(output_queue, f"No results found for '{company_name}'. Please try a more specific name.", "ERROR")
            return None, None

        first_result = results[0]
        official_name = first_result.get('name', '')
        company_url = first_result.get('url', '')

        match = re.search(r'/company/(\w+)/', company_url)
        if match:
            ticker = match.group(1)
            log_message(output_queue, f"Found Ticker: {ticker} for {official_name}", "SUCCESS")
            return ticker, official_name
        else:
            log_message(output_queue, f"Could not extract ticker from URL: {company_url}", "ERROR")
            return None, None
    except Exception as e:
        log_message(output_queue, f"An unexpected error occurred during ticker search: {e}", "CRITICAL ERROR")
        return None, None

# --- Core Downloading Logic (Updated from reference) ---

def smart_download_and_save(url: str, filepath: str, output_queue: queue.Queue):
    """
    Intelligently downloads a file, handling landing pages (like ICRA) and validating PDF content.
    """
    if os.path.exists(filepath):
        log_message(output_queue, f"File already exists, skipping: {os.path.basename(filepath)}", "INFO")
        return True

    log_message(output_queue, f"Downloading: {os.path.basename(filepath)}")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.screener.in/"
    })

    try:
        final_url = url
        # Handle ICRA landing pages by finding the embedded PDF in an iframe
        if 'icra.in' in url:
            log_message(output_queue, "ICRA link found. Searching for embedded PDF...", "INFO")
            page_response = session.get(url, timeout=30)
            page_response.raise_for_status()
            page_soup = BeautifulSoup(page_response.text, 'html.parser')
            iframe = page_soup.find('iframe')
            if iframe and iframe.get('src'):
                final_url = urljoin(url, iframe['src'])
                log_message(output_queue, f"Found direct PDF link: {final_url}", "SUCCESS")
            else:
                log_message(output_queue, "Could not find embedded PDF on ICRA page.", "ERROR")
                return False

        pdf_response = session.get(final_url, timeout=120)
        pdf_response.raise_for_status()

        if not pdf_response.content.startswith(b'%PDF-'):
             log_message(output_queue, f"Skipped '{os.path.basename(filepath)}' as content was not a valid PDF.", "WARNING")
             return False

        with open(filepath, 'wb') as f:
            f.write(pdf_response.content)
        log_message(output_queue, f"Successfully saved: {os.path.basename(filepath)}", "SUCCESS")
        return True

    except RequestException as e:
        log_message(output_queue, f"Failed to download '{os.path.basename(filepath)}'. Reason: {e}", "ERROR")
        return False
    except Exception as e:
        log_message(output_queue, f"An unexpected error occurred for '{os.path.basename(filepath)}': {e}", "CRITICAL ERROR")
        return False

def execute_screener_workflow(ticker: str, company_name: str, parent_dir: str, output_queue: queue.Queue):
    """
    Finds and downloads specified documents using the robust logic from the reference script.
    """
    log_message(output_queue, f"--- Starting Workflow for: {company_name} ({ticker}) ---")
    safe_company_name = sanitize_filename(company_name)
    company_dir = os.path.join(parent_dir, safe_company_name)
    os.makedirs(company_dir, exist_ok=True)

    headers = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36" }
    target_years = [2022, 2023, 2024, 2025]
    concall_start_date = datetime(2024, 1, 1)

    try:
        screener_url = f"https://www.screener.in/company/{ticker}/consolidated/"
        response = requests.get(screener_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Process Annual Reports
        ar_header = soup.find('h3', string=re.compile(r'Annual reports', re.I))
        if ar_header:
            ar_dir = os.path.join(company_dir, 'Annual Reports')
            os.makedirs(ar_dir, exist_ok=True)
            list_box = ar_header.find_next_sibling('div', class_='show-more-box')
            if list_box:
                for item in list_box.find_all('li'):
                    link = item.find('a')
                    text = item.get_text(strip=True)
                    if link and link.get('href') and any(str(year) in text for year in target_years):
                        filename = sanitize_filename(f"{text.replace(' ', '-')}.pdf")
                        smart_download_and_save(link['href'], os.path.join(ar_dir, filename), output_queue)

        # 2. Process Concalls (Improved Logic)
        concall_section = soup.find('div', class_=lambda x: x and 'documents' in x and 'concalls' in x)
        if not concall_section:
            concall_header = soup.find('h3', string=re.compile(r'Concalls', re.I))
            if concall_header: concall_section = concall_header.find_parent('div')

        if concall_section:
            log_message(output_queue, f"Processing Concalls from {concall_start_date.strftime('%b %Y')} onwards...", "INFO")
            transcript_dir = os.path.join(company_dir, 'Concalls', 'Transcripts')
            ppt_dir = os.path.join(company_dir, 'Concalls', 'Presentations')
            os.makedirs(transcript_dir, exist_ok=True); os.makedirs(ppt_dir, exist_ok=True)

            concall_list = concall_section.find('ul', class_='list-links')
            if not concall_list: concall_list = concall_section.find('div', class_='show-more-box')

            if concall_list:
                for item in concall_list.find_all('li'):
                    date_element = item.find('div', class_=lambda x: x and 'ink-600' in x) or item.find('div', string=re.compile(r'\w{3}\s+\d{4}'))
                    if not date_element: continue
                    
                    try:
                        date_text = date_element.get_text(strip=True)
                        doc_date = datetime.strptime(date_text, '%b %Y')

                        if doc_date >= concall_start_date:
                            date_prefix = doc_date.strftime('%Y-%m')
                            all_links = item.find_all('a', class_='concall-link')
                            
                            # Find and download Transcript
                            transcript_link = next((link for link in all_links if link.get_text(strip=True).lower() == 'transcript'), None)
                            if transcript_link:
                                filename = sanitize_filename(f"{date_prefix} - Concall Transcript.pdf")
                                smart_download_and_save(transcript_link['href'], os.path.join(transcript_dir, filename), output_queue)

                            # Find and download PPT
                            ppt_link = next((link for link in all_links if link.get_text(strip=True).lower() == 'ppt'), None)
                            if ppt_link:
                                filename = sanitize_filename(f"{date_prefix} - Concall Presentation.pdf")
                                smart_download_and_save(ppt_link['href'], os.path.join(ppt_dir, filename), output_queue)

                    except ValueError:
                        log_message(output_queue, f"Could not parse date '{date_text}'", "WARNING")
                        continue
        else:
            log_message(output_queue, "No concalls section found.", "WARNING")

    except Exception as e:
        log_message(output_queue, f"Workflow failed for {company_name}: {e}", "CRITICAL ERROR")
        log_message(output_queue, f"Full traceback: {traceback.format_exc()}", "DEBUG")
    finally:
        log_message(output_queue, f"--- Workflow for {company_name} complete. ---\n")


# --- Gradio UI and Handlers ---

def start_gradio_app():
    """Launches the Gradio web interface."""
    def handle_log_streaming(log_queue, thread):
        full_log = ""
        while True:
            try:
                message = log_queue.get(timeout=0.1)
                if message is None: break
                full_log += message + "\n"
                yield full_log
            except queue.Empty:
                if not thread.is_alive(): break
        thread.join()

    def run_file_workflow(log_queue):
        parent_dir = COMMON_FOLDER_NAME
        os.makedirs(parent_dir, exist_ok=True)
        log_message(log_queue, f"✅ Saving all files to local folder: '{os.path.abspath(parent_dir)}'", "SUCCESS")
        target_companies = load_company_list()
        log_message(log_queue, f"Loaded {len(target_companies)} companies from '{CONFIG_FILE}'.", "INFO")
        for i, (ticker, name) in enumerate(target_companies.items(), 1):
            log_message(log_queue, f"Processing company {i}/{len(target_companies)}...", "INFO")
            execute_screener_workflow(ticker, name, parent_dir, log_queue)
            time.sleep(2)
        log_message(log_queue, "🎉 ALL TASKS FINISHED.", "SUCCESS")
        log_message(log_queue, None)

    def run_single_company_workflow(company_name, log_queue):
        parent_dir = COMMON_FOLDER_NAME
        os.makedirs(parent_dir, exist_ok=True)
        log_message(log_queue, f"✅ Saving files to local folder: '{os.path.abspath(parent_dir)}'", "SUCCESS")
        if not company_name.strip():
            log_message(log_queue, "Company name cannot be empty.", "ERROR")
            log_message(log_queue, None)
            return
        ticker, official_name = find_ticker_for_company(company_name, log_queue)
        if ticker and official_name:
            execute_screener_workflow(ticker, official_name, parent_dir, log_queue)
            log_message(log_queue, "🎉 TASK FINISHED.", "SUCCESS")
        else:
            log_message(log_queue, f"Could not process '{company_name}'. Aborting.", "ERROR")
        log_message(log_queue, None)

    def process_from_file_handler():
        log_queue = queue.Queue()
        thread = threading.Thread(target=run_file_workflow, args=(log_queue,))
        thread.start()
        yield from handle_log_streaming(log_queue, thread)

    def process_single_company_handler(company_name):
        log_queue = queue.Queue()
        thread = threading.Thread(target=run_single_company_workflow, args=(company_name, log_queue))
        thread.start()
        yield from handle_log_streaming(log_queue, thread)

    with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue"), title="Screener Document Downloader") as iface:
        gr.Markdown(
            """
            # 📂 Screener.in Document Downloader
            Fetch Annual Reports (2022-2025) and recent Concall documents for Indian companies.
            All documents will be saved to a local folder named `common_folder`.
            """
        )
        with gr.Tabs():
            with gr.TabItem("Process Single Company"):
                with gr.Row():
                    company_name_input = gr.Textbox(label="Enter Company Name", placeholder="e.g., Reliance Industries or Tata Motors", scale=3)
                    single_run_button = gr.Button("▶️ Fetch Documents", variant="primary", scale=1)
                single_output_textbox = gr.Textbox(label="Log & Status", interactive=False, lines=20)
            with gr.TabItem("Process from File"):
                gr.Markdown(f"Click the button below to process all companies listed in the `{CONFIG_FILE}` file.")
                file_run_button = gr.Button("▶️ Process All Companies from File", variant="primary")
                file_output_textbox = gr.Textbox(label="Log & Status", interactive=False, lines=20)
        
        single_run_button.click(fn=process_single_company_handler, inputs=company_name_input, outputs=single_output_textbox)
        file_run_button.click(fn=process_from_file_handler, inputs=None, outputs=file_output_textbox)

    print("Launching Gradio Interface... Open the provided URL in your browser.")
    iface.launch(share=True)

if __name__ == "__main__":
    start_gradio_app()
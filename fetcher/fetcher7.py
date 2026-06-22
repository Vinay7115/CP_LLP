import asyncio
import uuid
import os
import time
import tempfile
import pandas as pd
import json

import gradio as gr
from dotenv import load_dotenv

from google.adk import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# Global driver instance for login persistence
global_driver = None
is_logged_in = False

# === Product Segment Scraping Functions ===
def get_driver_with_login():
    """Initialize driver with login capabilities"""
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    try:
        # Use webdriver_manager to automatically handle ChromeDriver installation for the platform
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception as e:
        print(f"Error initializing Chrome driver: {e}")
        # Fallback to ensure compatibility across platforms
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

def ensure_login():
    """Ensure user is logged in to screener.in"""
    global global_driver, is_logged_in
    
    if global_driver is None:
        global_driver = get_driver_with_login()
    
    if not is_logged_in:
        wait = WebDriverWait(global_driver, 9999)
        global_driver.get("https://www.screener.in/login/")
        print("👉 Please log in manually to Screener.in")
        wait.until(lambda d: d.current_url != "https://www.screener.in/login/")
        print("✅ Logged in successfully!")
        is_logged_in = True
    
    return global_driver

def scrape_segment(driver, company_ticker, button_text, suffix=""):
    """Scrape specific segment data"""
    print(f"\n🔍 Looking for '{button_text}'")
    try:
        wait = WebDriverWait(driver, 10)
        btn = driver.find_element(By.XPATH, f"//button[contains(., '{button_text}')]")
        driver.execute_script("arguments[0].click();", btn)
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, 'div[data-segment-table]').is_displayed())
        time.sleep(1)
        
        table = driver.find_element(By.CSS_SELECTOR, 'div[data-segment-table] table')
        headers = [th.text.strip() for th in table.find_elements(By.CSS_SELECTOR, "thead th")]
        rows = []
        for tr in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
            row = [td.text.strip() for td in tr.find_elements(By.TAG_NAME, "td")]
            if row:
                rows.append(row)
        
        df = pd.DataFrame(rows, columns=headers)
        if not df.empty:
            output_dir = "segment_data"
            os.makedirs(output_dir, exist_ok=True)
            filename = f"{output_dir}/{company_ticker}_{button_text.replace(' ', '_').lower()}{suffix}.csv"
            df.to_csv(filename, index=False)
            print(f"✅ Saved {button_text} data to: {filename}")
            return filename, df
        else:
            print(f"⚠️ No data found in {button_text} table.")
            return None, None
    except Exception as e:
        print(f"❌ Failed to scrape {button_text} — {e}")
        return None, None

def scrape_profit_before_tax_growth(driver, company_ticker):
    """Specifically scrape Growth % data for Profit before Tax & Int section"""
    print(f"\n🔍 Looking for Profit before Tax & Int - Growth %")
    try:
        wait = WebDriverWait(driver, 10)
        possible_selectors = [
            "//h3[contains(text(), 'Profit before Tax')]",
            "//h4[contains(text(), 'Profit before Tax')]", 
            "//div[contains(text(), 'Profit before Tax')]",
            "//span[contains(text(), 'Profit before Tax')]",
            "//*[contains(text(), 'Profit before Tax & Int')]",
            "//*[contains(text(), 'Profit before Tax')]",
            "//div[contains(@class, 'segment')]//h3",
            "//div[contains(@class, 'segment')]//h4"
        ]
        
        profit_section = None
        for selector in possible_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    if 'profit' in element.text.lower() and ('tax' in element.text.lower() or 'int' in element.text.lower()):
                        profit_section = element
                        print(f"✅ Found section: {element.text}")
                        break
                if profit_section:
                    break
            except:
                continue
        
        if not profit_section:
            print("❌ Could not find Profit before Tax section. Trying alternative approach...")
            growth_buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Growth %')]")
            print(f"Found {len(growth_buttons)} Growth % buttons total")
            
            for i, btn in enumerate(growth_buttons):
                try:
                    driver.execute_script("arguments[0].scrollIntoView();", btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", btn)
                    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, 'div[data-segment-table]').is_displayed())
                    time.sleep(1)
                    
                    table = driver.find_element(By.CSS_SELECTOR, 'div[data-segment-table] table')
                    table_text = table.text.lower()
                    
                    if 'profit' in table_text and ('tax' in table_text or 'int' in table_text):
                        print(f"✅ Found Profit before Tax Growth % data in button {i+1}")
                        headers = [th.text.strip() for th in table.find_elements(By.CSS_SELECTOR, "thead th")]
                        rows = []
                        for tr in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
                            row = [td.text.strip() for td in tr.find_elements(By.TAG_NAME, "td")]
                            if row:
                                rows.append(row)
                        
                        df = pd.DataFrame(rows, columns=headers)
                        if not df.empty:
                            output_dir = "segment_data"
                            os.makedirs(output_dir, exist_ok=True)
                            filename = f"{output_dir}/{company_ticker}_profit_before_tax_growth_percent.csv"
                            df.to_csv(filename, index=False)
                            print(f"✅ Saved Profit before Tax & Int - Growth % data to: {filename}")
                            return filename, df
                        
                except Exception as e:
                    print(f"Button {i+1} failed: {e}")
                    continue
                    
            print("❌ Could not find Profit before Tax Growth % data in any of the Growth % buttons")
            return None, None
        
        driver.execute_script("arguments[0].scrollIntoView();", profit_section)
        time.sleep(1)
        
        growth_btn = None
        try:
            parent = profit_section.find_element(By.XPATH, "./ancestor::div[contains(@class, 'segment') or contains(@class, 'section')][1]")
            growth_btn = parent.find_element(By.XPATH, ".//button[contains(., 'Growth %')]")
        except:
            try:
                growth_btn = profit_section.find_element(By.XPATH, "./following::button[contains(., 'Growth %')][1]")
            except:
                print("❌ Could not find Growth % button for this section")
                return None, None
        
        if growth_btn:
            driver.execute_script("arguments[0].click();", growth_btn)
            wait.until(lambda d: d.find_element(By.CSS_SELECTOR, 'div[data-segment-table]').is_displayed())
            time.sleep(1)
            
            table = driver.find_element(By.CSS_SELECTOR, 'div[data-segment-table] table')
            headers = [th.text.strip() for th in table.find_elements(By.CSS_SELECTOR, "thead th")]
            rows = []
            for tr in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
                row = [td.text.strip() for td in tr.find_elements(By.TAG_NAME, "td")]
                if row:
                    rows.append(row)
            
            df = pd.DataFrame(rows, columns=headers)
            if not df.empty:
                output_dir = "segment_data"
                os.makedirs(output_dir, exist_ok=True)
                filename = f"{output_dir}/{company_ticker}_profit_before_tax_growth_percent.csv"
                df.to_csv(filename, index=False)
                print(f"✅ Saved Profit before Tax & Int - Growth % data to: {filename}")
                return filename, df
            else:
                print(f"⚠️ No data found in Profit before Tax & Int - Growth % table.")
                return None, None
                
    except Exception as e:
        print(f"❌ Failed to scrape Profit before Tax & Int - Growth % — {e}")
        return None, None

# === Enhanced Tools for ADK ===
def fetch_product_segments_tool(company: str) -> dict:
    """Fetches all product segment data for a company including Product Segments, Growth %, Margin %, and ROCE %"""
    try:
        driver = ensure_login()
        company_ticker = company.strip().upper()
        
        # Navigate to company page
        driver.get(f"https://www.screener.in/company/{company_ticker}/consolidated/")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "quarters")))
        time.sleep(2)
        
        results = []
        files_created = []
        
        # Scrape Product Segments (Amount)
        filename, df = scrape_segment(driver, company_ticker, "Product Segments", "_amount")
        if filename and df is not None:
            files_created.append(filename)
            results.append(f"✅ Product Segments (Amount): {len(df)} rows saved to {filename}")
        
        # Scrape Growth %
        filename, df = scrape_segment(driver, company_ticker, "Growth %")
        if filename and df is not None:
            files_created.append(filename)
            results.append(f"✅ Growth %: {len(df)} rows saved to {filename}")
        
        # Scrape Profit before Tax Growth %
        filename, df = scrape_profit_before_tax_growth(driver, company_ticker)
        if filename and df is not None:
            files_created.append(filename)
            results.append(f"✅ Profit before Tax & Int - Growth %: {len(df)} rows saved to {filename}")
        
        # Scrape Margin %
        filename, df = scrape_segment(driver, company_ticker, "Margin %")
        if filename and df is not None:
            files_created.append(filename)
            results.append(f"✅ Margin %: {len(df)} rows saved to {filename}")
        
        # Scrape ROCE %
        filename, df = scrape_segment(driver, company_ticker, "ROCE %")
        if filename and df is not None:
            files_created.append(filename)
            results.append(f"✅ ROCE %: {len(df)} rows saved to {filename}")
        
        summary = f"Product Segment Analysis for {company_ticker}:\n\n" + "\n".join(results)
        summary += f"\n\n📁 Total files created: {len(files_created)}"
        summary += "\n\n🎉 Product segment data extraction completed successfully!"
        
        return {
            "type": "text",
            "content": summary
        }
        
    except Exception as e:
        return {
            "type": "text",
            "content": f"Failed to fetch product segments for {company}. Error: {e}"
        }

def analyze_csv_data_tool(company: str, query: str) -> dict:
    """Analyzes CSV data based on user query. Reads all available CSV files and provides specific analysis."""
    try:
        company_ticker = company.strip().upper()
        output_dir = "segment_data"
        
        # Define all possible CSV files
        csv_files = {
            "product_segments": f"{company_ticker}_product_segments_amount.csv",
            "growth": f"{company_ticker}_growth_%.csv", 
            "profit_growth": f"{company_ticker}_profit_before_tax_growth_percent.csv",
            "margin": f"{company_ticker}_margin_%.csv",
            "roce": f"{company_ticker}_roce_%.csv"
        }
        
        available_data = {}
        query_lower = query.lower()
        
        # Read all available CSV files
        for data_type, filename in csv_files.items():
            file_path = os.path.join(output_dir, filename)
            if os.path.exists(file_path):
                try:
                    df = pd.read_csv(file_path)
                    available_data[data_type] = df
                except Exception as e:
                    print(f"Error reading {filename}: {e}")
        
        if not available_data:
            return {
                "type": "text",
                "content": f"❌ No CSV data found for {company_ticker}. Please run fetch_product_segments_tool first."
            }
        
        response = f"📊 ANALYSIS FOR {company_ticker} based on your query: '{query}'\n\n"
        
        # Analyze based on query keywords
        relevant_data_found = False
        
        # Check for growth-related queries
        if any(keyword in query_lower for keyword in ['growth', 'grow', 'increase', 'decrease']):
            if 'growth' in available_data:
                df = available_data['growth']
                response += "📈 GROWTH DATA FROM CSV:\n"
                response += "=" * 50 + "\n"
                response += f"Columns: {', '.join(df.columns.tolist())}\n\n"
                
                # Show specific data based on query
                if 'sales' in query_lower or 'revenue' in query_lower:
                    # Look for sales/revenue related rows
                    sales_rows = df[df.iloc[:, 0].str.contains('Sales|Revenue|Net Sales', case=False, na=False)]
                    if not sales_rows.empty:
                        response += "🎯 SALES/REVENUE GROWTH:\n"
                        response += sales_rows.to_string(index=False) + "\n\n"
                        relevant_data_found = True
                
                # Show complete growth data
                response += "📋 COMPLETE GROWTH DATA:\n"
                response += df.to_string(index=False) + "\n\n"
                relevant_data_found = True
            
            # Also check profit growth data
            if 'profit_growth' in available_data:
                df = available_data['profit_growth']
                response += "💰 PROFIT BEFORE TAX GROWTH DATA FROM CSV:\n"
                response += "=" * 50 + "\n"
                response += df.to_string(index=False) + "\n\n"
                relevant_data_found = True
        
        # Check for margin-related queries
        if any(keyword in query_lower for keyword in ['margin', 'profitability', 'profit margin']):
            if 'margin' in available_data:
                df = available_data['margin']
                response += "📊 MARGIN DATA FROM CSV:\n"
                response += "=" * 50 + "\n"
                response += f"Columns: {', '.join(df.columns.tolist())}\n\n"
                response += df.to_string(index=False) + "\n\n"
                relevant_data_found = True
        
        # Check for ROCE-related queries  
        if any(keyword in query_lower for keyword in ['roce', 'return', 'capital employed']):
            if 'roce' in available_data:
                df = available_data['roce']
                response += "💎 ROCE DATA FROM CSV:\n"
                response += "=" * 50 + "\n"
                response += f"Columns: {', '.join(df.columns.tolist())}\n\n"
                response += df.to_string(index=False) + "\n\n"
                relevant_data_found = True
        
        # Check for product segment amount queries
        if any(keyword in query_lower for keyword in ['segment', 'product', 'business', 'division', 'amount']):
            if 'product_segments' in available_data:
                df = available_data['product_segments']
                response += "🏭 PRODUCT SEGMENT AMOUNTS FROM CSV:\n"
                response += "=" * 50 + "\n" 
                response += f"Columns: {', '.join(df.columns.tolist())}\n\n"
                response += df.to_string(index=False) + "\n\n"
                relevant_data_found = True
        
        # If no specific match, show summary of all available data
        if not relevant_data_found:
            response += "📋 ALL AVAILABLE DATA SUMMARY:\n"
            response += "=" * 50 + "\n"
            for data_type, df in available_data.items():
                response += f"\n📄 {data_type.upper().replace('_', ' ')}:\n"
                response += f"Columns: {', '.join(df.columns.tolist())}\n"
                response += f"Rows: {len(df)}\n"
                response += "Sample Data:\n"
                response += df.head(3).to_string(index=False) + "\n"
                if len(df) > 3:
                    response += f"... and {len(df) - 3} more rows\n"
                response += "\n"
        
        response += "🔍 This data is directly from the CSV files scraped from Screener.in\n"
        response += f"📁 Available data types: {', '.join(available_data.keys())}\n"
        
        return {
            "type": "text", 
            "content": response
        }
        
    except Exception as e:
        return {
            "type": "text",
            "content": f"❌ Failed to analyze CSV data for {company}. Error: {e}"
        }

def get_complete_csv_data_tool(company: str, data_type: str = "all") -> dict:
    """Returns complete CSV data for specified type or all types"""
    try:
        company_ticker = company.strip().upper()
        output_dir = "segment_data"
        
        csv_files = {
            "product_segments": f"{company_ticker}_product_segments_amount.csv",
            "growth": f"{company_ticker}_growth_%.csv",
            "profit_growth": f"{company_ticker}_profit_before_tax_growth_percent.csv", 
            "margin": f"{company_ticker}_margin_%.csv",
            "roce": f"{company_ticker}_roce_%.csv"
        }
        
        response = f"📊 COMPLETE CSV DATA for {company_ticker}\n\n"
        
        if data_type.lower() == "all":
            # Show all available data
            for dtype, filename in csv_files.items():
                file_path = os.path.join(output_dir, filename)
                if os.path.exists(file_path):
                    try:
                        df = pd.read_csv(file_path)
                        response += f"📄 {dtype.upper().replace('_', ' ')} DATA:\n"
                        response += "=" * 60 + "\n"
                        response += f"File: {filename}\n"
                        response += f"Columns: {', '.join(df.columns.tolist())}\n"
                        response += f"Total Rows: {len(df)}\n\n"
                        response += "COMPLETE DATA:\n"
                        response += df.to_string(index=False) + "\n\n"
                        response += "-" * 60 + "\n\n"
                    except Exception as e:
                        response += f"❌ Error reading {filename}: {e}\n\n"
                else:
                    response += f"❌ File not found: {filename}\n\n"
        else:
            # Show specific data type
            if data_type in csv_files:
                filename = csv_files[data_type]
                file_path = os.path.join(output_dir, filename)
                if os.path.exists(file_path):
                    try:
                        df = pd.read_csv(file_path)
                        response += f"📄 {data_type.upper().replace('_', ' ')} DATA:\n"
                        response += "=" * 60 + "\n"
                        response += f"File: {filename}\n"
                        response += f"Columns: {', '.join(df.columns.tolist())}\n"
                        response += f"Total Rows: {len(df)}\n\n"
                        response += "COMPLETE DATA:\n"
                        response += df.to_string(index=False) + "\n"
                    except Exception as e:
                        response += f"❌ Error reading {filename}: {e}\n"
                else:
                    response += f"❌ File not found: {filename}\n"
            else:
                available_types = ", ".join(csv_files.keys())
                response += f"❌ Invalid data type: {data_type}\n"
                response += f"Available types: {available_types}\n"
        
        return {
            "type": "text",
            "content": response
        }
        
    except Exception as e:
        return {
            "type": "text",
            "content": f"❌ Failed to get CSV data for {company}. Error: {e}"
        }

# === ADK Agent Setup ===
APP_NAME = "Product Segment Fetcher"
USER_ID = "visitor"
SESSION_ID = str(uuid.uuid4())
session_service = InMemorySessionService()

runner = None
product_segment_agent = None

async def setup():
    global runner, product_segment_agent

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state={"user_goal": "Fetch and analyze product segment data from Screener.in for any company"}
    )

    product_segment_agent = Agent(
        name="Product_Segment_Fetcher",
        model="gemini-2.5-pro",
        instruction="""
You are Product_Segment_Fetcher, a specialized agent for extracting and analyzing product segment data from Screener.in.

🚨 CRITICAL INSTRUCTIONS - MUST FOLLOW STRICTLY:
1. NEVER generate or create data from your own knowledge or database
2. ALWAYS use data ONLY from the CSV files that are scraped from Screener.in  
3. When showing data, it must be the EXACT data from the CSV files - no modifications
4. If CSV data is not available, clearly state this and ask user to fetch data first

Your tools:
1. fetch_product_segments_tool(company): Extract ALL segment data from Screener.in and save as CSV files
2. analyze_csv_data_tool(company, query): Analyze CSV data based on user's specific query 
3. get_complete_csv_data_tool(company, data_type): Get complete CSV data for analysis

Available CSV data types:
- "product_segments": Product segment amounts/revenue
- "growth": Growth percentages for all segments  
- "profit_growth": Profit before tax growth percentages
- "margin": Margin percentages for all segments
- "roce": ROCE percentages for all segments
- "all": All available CSV data

WORKFLOW:
1. When user asks for company data:
   - First use fetch_product_segments_tool to scrape and save CSV data
   - Then use analyze_csv_data_tool or get_complete_csv_data_tool to show the data

2. When user asks specific questions (like "sales growth", "margin data", etc.):
   - Use analyze_csv_data_tool with their exact query
   - This will intelligently find relevant data from the CSV files
   - Show the COMPLETE and EXACT data from CSV files

3. For detailed analysis:
   - Use get_complete_csv_data_tool to show complete CSV data
   - Always specify which CSV file the data comes from

RESPONSE FORMAT:
- Always show data in well-formatted tables
- Include CSV file source information  
- Provide clear section headers
- Show complete data, not summaries
- Never truncate important data

IMPORTANT REMINDERS:
❌ DO NOT create any data from your own knowledge
❌ DO NOT modify or summarize CSV data  
❌ DO NOT use any data source other than the scraped CSV files
✅ ONLY use data from the CSV files created by the scraping tools
✅ Always mention which CSV file the data comes from
✅ Show complete tables when requested
✅ Be precise about data sources
""",
        description="Specialized agent for fetching and analyzing product segment data from Screener.in using CSV files only",
        tools=[fetch_product_segments_tool, analyze_csv_data_tool, get_complete_csv_data_tool]
    )

    runner = Runner(agent=product_segment_agent, app_name=APP_NAME, session_service=session_service)

# === Chat function ===
async def chat(user_message, history):
    internal_history = []
    for u, b in history:
        internal_history.append({"role": "user", "content": u})
        internal_history.append({"role": "assistant", "content": b})

    new_message = types.Content(role="user", parts=[types.Part(text=user_message)])
    bot_reply = ""

    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=new_message):
        if event.is_final_response() and event.content and event.content.parts:
            part = event.content.parts[0]
            if hasattr(part, "text") and part.text:
                bot_reply = part.text
            break

    history.append((user_message, bot_reply))
    return history, ""

def clear_history():
    return [], ""

def cleanup():
    """Cleanup function to close browser when app shuts down"""
    global global_driver
    if global_driver:
        global_driver.quit()

if __name__ == "__main__":
    try:
        asyncio.run(setup())

        with gr.Blocks(
            theme=gr.themes.Base(),
            css="""
            footer {display: none !important;}
            #chatbot {
                font-weight: 600;
            }
            #send-button {
                background-color: #2196F3 !important;
                color: white !important;
                font-weight: bold;
            }
            #clear-button {
                background-color: #e53935 !important;
                color: white !important;
                font-weight: bold;
            }
            """
        ) as demo:

            gr.Markdown("<h1 style='color:#2196F3;'>📊 Product Segment Fetcher Agent</h1>")
            gr.Markdown("### Extract and analyze product segment data from Screener.in")
            gr.Markdown("**Note:** You'll need to manually log in to Screener.in when prompted for the first time.")
            gr.Markdown("**Example queries:** 'Get product segments for ITC', 'Show me sales growth for RELIANCE', 'What are the margin percentages for TCS'")

            chatbot = gr.Chatbot([], elem_id="chatbot", height=500)
            state = gr.State([])

            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Ask me to fetch and analyze product segment data (e.g., 'Get sales growth data for ITC')", 
                    label="Your Message", 
                    scale=4
                )

            with gr.Row():
                send = gr.Button("🚀 Send", elem_id="send-button", scale=1)
                clear = gr.Button("🧹 Clear", elem_id="clear-button", scale=1)

            msg.submit(chat, [msg, chatbot], [chatbot, msg])
            send.click(chat, [msg, chatbot], [chatbot, msg])
            clear.click(fn=clear_history, outputs=chatbot)

        port = int(os.environ.get("PORT", 7860))
        demo.launch(server_name="0.0.0.0", server_port=port)
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        cleanup()
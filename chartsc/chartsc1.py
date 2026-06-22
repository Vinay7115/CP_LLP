import asyncio
import uuid
import os
import time
import tempfile

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

# Global variable to store the latest chart path
latest_chart_path = None

# === Chart scraping function as tool ===
def chart_scraping_tool(company: str, timeframe: str, chart_type: str) -> dict:
    global latest_chart_path
    try:
        company = company.strip().upper()
        url = f"https://www.screener.in/company/{company}/consolidated/"

        # Setup chrome driver
        print("🔷 Setting up ChromeDriver...")
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")

        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 15)
            print("✅ ChromeDriver initialized successfully.")
        except Exception as e:
            print(f"❌ Failed to initialize ChromeDriver: {e}")
            return {
                "type": "text",
                "content": f"⚠ Failed to initialize browser. Error: {e}. Please ensure Google Chrome is installed and try again."
            }

        try:
            print(f"🔷 Opening {url}...")
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.ID, "chart")))

            # Find timeframes
            all_buttons = driver.find_elements(By.CSS_SELECTOR, "#chart-menu button")
            all_texts = [btn.text.strip() for btn in all_buttons if btn.text.strip()]
            timeframes = [txt for txt in all_texts if txt in ["1M", "6M", "1Yr", "3Yr", "5Yr", "10Yr", "Max"]]
            visible_chart_texts = [txt for txt in all_texts if txt not in timeframes and txt != "More"]

            if not timeframes:
                return {
                    "type": "text",
                    "content": f"⚠ Could not find timeframes for {company} on the page."
                }

            # Check for 'More' dropdown
            print("\n⏳ Checking for 'More' dropdown...")
            more_texts = []
            try:
                dropdown_button = driver.find_element(By.XPATH, "//button[normalize-space()='More']")
                dropdown_button.click()
                time.sleep(0.5)
                more_options = driver.find_elements(By.CSS_SELECTOR, "#metrics-dropdown button")
                more_texts = [btn.text.strip() for btn in more_options if btn.text.strip()]
                print(f"✅ Found {len(more_texts)} 'More' charts and added to list.")
                dropdown_button.click()
                time.sleep(0.5)
            except NoSuchElementException:
                print("ℹ No 'More' dropdown found — continuing with visible charts.")

            chart_types = visible_chart_texts + more_texts

            if not timeframe or not chart_type or timeframe.strip() == "" or chart_type.strip() == "":
                timeframes_text = "\n".join([f"  {idx}. {tf}" for idx, tf in enumerate(timeframes, 1)])
                charts_text = "\n".join([f"  {idx}. {name}" for idx, name in enumerate(chart_types, 1)])
                return {
                    "type": "text",
                    "content": f"✅ Available options for {company}:\n\n📅 Available timeframes:\n{timeframes_text}\n\n📈 Available charts:\n{charts_text}\n\nPlease specify both timeframe and chart type to generate a chart."
                }

            if timeframe not in timeframes:
                return {
                    "type": "text",
                    "content": f"⚠ Invalid timeframe '{timeframe}'. Available timeframes: {', '.join(timeframes)}"
                }

            if chart_type not in chart_types:
                return {
                    "type": "text",
                    "content": f"⚠ Invalid chart type '{chart_type}'. Available chart types: {', '.join(chart_types)}"
                }

            # Select timeframe
            print(f"🕒 Selected timeframe: {timeframe}")
            try:
                driver.find_element(By.XPATH, f"//button[normalize-space()='{timeframe}']").click()
                time.sleep(1)
            except NoSuchElementException:
                print(f"⚠ Could not select timeframe: {timeframe} — proceeding anyway.")

            # Select chart
            if chart_type in more_texts:
                print(f"🔷 Selecting from More: {chart_type}")
                dropdown_button = driver.find_element(By.XPATH, "//button[normalize-space()='More']")
                dropdown_button.click()
                time.sleep(0.5)
                driver.find_element(By.XPATH, f"//div[@id='metrics-dropdown']//button[normalize-space()='{chart_type}']").click()
            else:
                print(f"📈 Selecting: {chart_type}")
                driver.find_element(By.XPATH, f"//button[normalize-space()='{chart_type}']").click()

            time.sleep(5)

            # Save chart
            print("📸 Capturing the chart...")
            chart_holder = wait.until(EC.presence_of_element_located((By.ID, "canvas-chart-holder")))
            driver.execute_script("arguments[0].scrollIntoView(true);", chart_holder)
            time.sleep(1)

            driver.execute_script("""
                const holder = arguments[0];
                holder.style.width = '1800px';
                holder.style.height = '900px';
            """, chart_holder)
            time.sleep(1)

            if not os.path.exists("charts"):
                os.makedirs("charts")

            safe_chart = chart_type.replace(" ", "").replace("/", "")
            chart_path = os.path.join("charts", f"{company}{safe_chart}{timeframe}.png")
            chart_holder.screenshot(chart_path)
            latest_chart_path = os.path.abspath(chart_path)  # Use absolute path

            print(f"\n🎉 Saved chart → {chart_path}")
            return {
                "type": "image",
                "content": f"✅ Chart generated successfully! {company} - {chart_type} over {timeframe}",
                "chart_path": chart_path
            }

        finally:
            print("🔷 Closing browser...")
            driver.quit()

    except Exception as e:
        print(f"❌ Error in chart_scraping_tool: {e}")
        return {
            "type": "text",
            "content": f"⚠ Failed to scrape chart for {company}. Error: {e}. Please ensure Google Chrome is installed and up to date."
        }

# === ADK Agent Setup ===
APP_NAME = "Chart Scraper Agent"
USER_ID = "visitor"
SESSION_ID = str(uuid.uuid4())
session_service = InMemorySessionService()

runner = None
root_agent = None

async def setup():
    global runner, root_agent

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state={"user_goal": "Help users scrape charts from screener.in"}
    )

    root_agent = Agent(
        name="Chart_Scraper_Agent",
        model="gemini-2.5-flash",
        instruction="""
You are Chart_Scraper_Agent, an expert assistant that helps users scrape financial charts from screener.in website.

Your capabilities:
- I can scrape charts for any Indian company listed on screener.in
- I can show you all available timeframes (1M, 6M, 1Yr, 3Yr, 5Yr, 10Yr, Max)
- I can show you all available chart types (Price, PE Ratio, Sales & Margin, EV/EBITDA, etc.)
- I can generate specific charts when you provide company name, timeframe, and chart type

How to use me:
1. Just provide a company name (e.g., "TCS") and I'll show you all available options
2. Or provide complete details (e.g., "TCS 5Yr EV/EBITDA") and I'll generate that specific chart
3. If you don't provide complete information, I'll ask you to specify the missing details

Example interactions:
- "Show me charts for RELIANCE" → I'll list all available timeframes and chart types
- "Generate TCS 3Yr Price chart" → I'll create and show you that specific chart
- "HDFC Bank PE Ratio" → I'll ask you to specify the timeframe

Always specify the company name clearly. I'll guide you through the rest!

When you successfully generate a chart, mention that the chart has been generated and is being displayed.
""",
        description="Helps users scrape financial charts from screener.in with available timeframes and chart types.",
        tools=[chart_scraping_tool]
    )

    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

# === Chat function ===
async def chat(user_message, history):
    global latest_chart_path
    
    new_message = types.Content(role="user", parts=[types.Part(text=user_message)])
    bot_reply = ""
    
    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=new_message):
        if event.is_final_response() and event.content and event.content.parts:
            part = event.content.parts[0]
            if hasattr(part, "text") and part.text:
                bot_reply = part.text
            break
    
    # Add response to history
    history.append((user_message, bot_reply))
    
    # Check if a chart was generated and return it
    chart_to_display = None
    if latest_chart_path and os.path.exists(latest_chart_path):
        chart_to_display = latest_chart_path
        # Reset the global variable after use
        latest_chart_path = None
    
    return history, "", chart_to_display

def clear_history():
    global latest_chart_path
    latest_chart_path = None
    return [], "", None

if __name__ == "__main__":
    asyncio.run(setup())
    with gr.Blocks(
        theme=gr.themes.Base(),
        css="""
        footer {display: none !important;}
        #chatbot {
            font-weight: 600;
            height: 400px !important;
        }
        #send-button {
            background-color: #ff9800 !important;
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
        gr.Markdown("<h1 style='color:#ff9800;'>📈 Chart Scraper Agent</h1>")
        with gr.Row():
            with gr.Column(scale=1):
                chatbot = gr.Chatbot([], elem_id="chatbot", height=400, show_label=False)
                with gr.Row():
                    msg = gr.Textbox(placeholder="Type your request here (e.g., 'TCS charts' or 'TCS 5Yr Price')…", label="Your Message", scale=4)
                with gr.Row():
                    send = gr.Button("🚀 Send", elem_id="send-button", scale=1)
                    clear = gr.Button("🧹 Clear", elem_id="clear-button", scale=1)
            with gr.Column(scale=1):
                output_image = gr.Image(label="Generated Chart", height=500)
        msg.submit(chat, [msg, chatbot], [chatbot, msg, output_image])
        send.click(chat, [msg, chatbot], [chatbot, msg, output_image])
        clear.click(fn=clear_history, outputs=[chatbot, msg, output_image])
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port, allowed_paths=["charts"])
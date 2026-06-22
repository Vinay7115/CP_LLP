import asyncio
import uuid
import gradio as gr
from dotenv import load_dotenv
from google.adk import Agent
from google.adk.tools import google_search
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

APP_NAME = "Deep Research"
USER_ID = "visitor"
SESSION_ID = str(uuid.uuid4())
session_service = InMemorySessionService()

runner = None
root_agent = None

# Setup Agent & Runner
async def setup():
    global runner, root_agent

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state={"user_goal": "Learn about the Lost & Found platform"}
    )

    root_agent = Agent(
        name="Deep_Research_Agent",
        model="gemini-2.5-pro",
        instruction=""" You are Deep_Research_Agent your work is to go through all the possible resources (around 50 to 100) resources to perform very good research using the google_search tool you have.
        "About": f"Give a brief overview and background of the company.",
        "News": f"What are the latest news headlines about the company in the last 3 months?",
        "Financials": f"Summarize the recent financial performance of company.",
        "Competitors": f"List and compare top 3 competitors of company.",
        "Outlook": f"What is the future outlook and growth potential of company?"
""",
        description="You are a Deep Research Agent used to do the overall research of the company",
        tools=[google_search]
    )

    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

# Chat function
async def chat(user_message, history):
    # convert history (list of tuples) → internal dict history
    internal_history = []
    for u, b in history:
        internal_history.append({"role": "user", "content": u})
        internal_history.append({"role": "assistant", "content": b})

    new_message = types.Content(role="user", parts=[types.Part(text=user_message)])
    bot_reply = ""

    async for event in runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=new_message):
        if event.is_final_response() and event.content and event.content.parts:
            bot_reply = event.content.parts[0].text
            break

    # append to history in tuple format
    history.append((user_message, bot_reply))
    return history, ""

def clear_history():
    return [], ""

if __name__ == "__main__":
    asyncio.run(setup())

    with gr.Blocks(
        theme=gr.themes.Base(),
        css="""
        footer {display: none !important;}
        #chatbot {
            font-weight: 600;
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

        gr.Markdown("<h1 style='color:#ff9800;'>💬 Deep Research Agent</h1>")

        chatbot = gr.Chatbot([], elem_id="chatbot", height=500)
        state = gr.State([])

        with gr.Row():
            msg = gr.Textbox(placeholder="Type your question here…", label="Your Message", scale=4)

        with gr.Row():
            send = gr.Button("🚀 Send", elem_id="send-button", scale=1)
            clear = gr.Button("🧹 Clear", elem_id="clear-button", scale=1)

        msg.submit(chat, [msg, chatbot], [chatbot, msg])
        send.click(chat, [msg, chatbot], [chatbot, msg])
        clear.click(fn=clear_history, outputs=chatbot)

    import os
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)

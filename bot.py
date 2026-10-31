import os
import asyncio
import logging
import json
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands
from dotenv import load_dotenv
from e2b_code_interpreter import Sandbox
from google import genai

# Load local .env if present (Render will use its own Environment Variables)
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
E2B_API_KEY = os.getenv("E2B_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- 1. KEEP-ALIVE WEB SERVER FOR RENDER ---
app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Xompiler AI Bot is Online and Healthy!", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

# --- 2. INITIALIZE CLIENTS ---
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- SNIPPET STORAGE UTILITIES ---
SNIPPET_FILE = "snippets.json"

def load_snippets():
    if not os.path.exists(SNIPPET_FILE):
        return {}
    try:
        with open(SNIPPET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_snippets_to_disk(data):
    try:
        with open(SNIPPET_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving snippets: {e}")

# --- ROBUST GEMINI CALLER WITH FALLBACKS ---
def ask_gemini(prompt_text: str) -> str:
    models_to_try = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.8-flash"]
    last_error = None
    
    for model_name in models_to_try:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=prompt_text
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue
            
    raise last_error

# --- 3. GEMINI AI BUG EXPLAINER ---
def get_ai_fix(code: str, error: str) -> str:
    prompt = (
        "You are Xompiler AI, an expert coding assistant.\n"
        "A user tried to run this code and it crashed:\n"
        f"```python\n{code}\n```\n\n"
        "Error Output:\n"
        f"```\n{error}\n```\n\n"
        "Provide:\n"
        "1. **Why it failed:** 1-2 concise sentences explaining the bug.\n"
        "2. **Fix:** The corrected code block.\n"
        "Keep the total response under 1500 characters."
    )
    return ask_gemini(prompt)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (Xompiler AI Edition)")

# --- 4. DISCORD COMMANDS (WITH INPUT & FILE SUPPORT) ---
@bot.command()
async def run(ctx, *, code_block: str = None):
    clean_code = ""
    sandbox_files = {}

    # Handle file attachments if uploaded
    if ctx.message.attachments:
        for attachment in ctx.message.attachments:
            try:
                file_bytes = await attachment.read()
                file_content = file_bytes.decode('utf-8')
                if attachment.filename.endswith('.py') and not code_block:
                    clean_code = file_content
                else:
                    sandbox_files[attachment.filename] = file_content
            except Exception as e:
                await ctx.send(f"⚠️ Failed to read attachment `{attachment.filename}`: {e}")
                return

    # Parse code block if text was provided
    if code_block:
        code_text = code_block.strip()
        if code_text.startswith("```"):
            lines = code_text.splitlines()
            if len(lines) >= 2:
                lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
                code_text = "\n".join(lines)
        clean_code = code_text if not clean_code else clean_code + "\n" + code_text

    if not clean_code and not sandbox_files:
        await ctx.send("❌ Please provide some code to run or attach a file! Example: `!run print('Hello')`")
        return

    # Handle interactive input() if present in code
    if "input(" in clean_code:
        await ctx.send("📥 **This program needs input.** Please reply in this channel within 60s with your input value:")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            user_msg = await bot.wait_for('message', timeout=60.0, check=check)
            user_input_value = user_msg.content
            
            # Override built-in input to pipe user's response safely into the sandbox
            clean_code = (
                "import sys\nfrom io import StringIO\n"
                f"_input_stream = StringIO({repr(user_input_value)} + '\\n')\n"
                "def custom_input(prompt=''):\n"
                "    print(prompt, end='')\n"
                "    line = _input_stream.readline()\n"
                "    if not line: return ''\n"
                "    return line.strip()\n"
                "__builtins__.input = custom_input\n\n"
            ) + clean_code
        except asyncio.TimeoutError:
            await ctx.send("⏳ Input prompt timed out. Running without input...")

    msg = await ctx.send(f"⏳ Running code for **{ctx.author.name}**...")

    # Execute inside E2B Sandbox with attached files
    def execute_in_sandbox():
        output_lines = []
        try:
            with Sandbox.create() as sandbox:
                for filename
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
                    # Save data/text files to be loaded into sandbox filesystem
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
            clean_code = f"import sys\nfrom io import StringIO\nsys.stdin = StringIO({repr(user_input_value)})\n\n" + clean_code
        except asyncio.TimeoutError:
            await ctx.send("⏳ Input prompt timed out. Running without input...")

    msg = await ctx.send(f"⏳ Running code for **{ctx.author.name}**...")

    # Execute inside E2B Sandbox with attached files
    def execute_in_sandbox():
        output_lines = []
        try:
            with Sandbox.create() as sandbox:
                # Write any attached files into the sandbox directory
                for filename, content in sandbox_files.items():
                    sandbox.files.write(filename, content)

                execution = sandbox.run_code(clean_code)
                
                if execution.logs.stdout:
                    output_lines.extend(execution.logs.stdout)
                if execution.logs.stderr:
                    output_lines.append("\n⚠️ Runtime Error:\n" + "\n".join(execution.logs.stderr))
                if execution.error:
                    tb_lines = "".join(execution.error.traceback) if execution.error.traceback else ""
                    output_lines.append(f"\n⚠️ Runtime Error:\n{execution.error.name}: {execution.error.value}\n{tb_lines}")
                
                if not output_lines:
                    output_lines.append("✅ Code executed successfully with no output.")
        except Exception as e:
            output_lines.append(f"❌ Sandbox Connection Error: {str(e)}")
        
        return "\n".join(output_lines)

    result = await asyncio.to_thread(execute_in_sandbox)

    if len(result) > 1900:
        result = result[:1900] + "\n...(Output truncated)"

    response_text = f"Output for **{ctx.author.name}**:\n```ansi\n{result}\n```"
    await msg.edit(content=response_text)

    # 🤖 AI Auto-Fix Trigger on Crash
    if "⚠️ Runtime Error:" in result:
        ai_msg = await ctx.send("🤖 **Xompiler AI is analyzing the crash...**")
        try:
            ai_suggestion = await asyncio.to_thread(get_ai_fix, clean_code, result)
            if len(ai_suggestion) > 1900:
                ai_suggestion = ai_suggestion[:1900] + "\n...(truncated)"
            await ai_msg.edit(content=f"💡 **AI Debug Suggestion:**\n{ai_suggestion}")
        except Exception as e:
            await ai_msg.edit(content=f"❌ AI Error: `{e}`")

@bot.command()
async def ask(ctx, *, question: str = None):
    if not question:
        await ctx.send("❌ Please ask a question! Example: `!ask What is a Python decorator?`")
        return
        
    msg = await ctx.send("🧠 **Thinking...**")
    try:
        res = await asyncio.to_thread(
            lambda: ask_gemini(f"Answer concisely with code examples if needed:\n{question}")
        )
        if len(res) > 1950:
            res = res[:1950] + "\n...(truncated)"
        await msg.edit(content=f"🧠 **Answer for {ctx.author.name}:**\n{res}")
    except Exception as e:
        await msg.edit(content=f"❌ AI Error: `{e}`")

# --- 5. SNIPPET MANAGEMENT COMMANDS ---
@bot.command()
async def save(ctx, name: str = None, *, code_block: str = None):
    if not name or not code_block:
        await ctx.send("❌ Usage: `!save <name> <code>`")
        return

    clean_code = code_block.strip()
    if clean_code.startswith("```"):
        lines = clean_code.splitlines()
        if len(lines) >= 2:
            lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            clean_code = "\n".join(lines)

    snippets = load_snippets()
    snippets[name] = {
        "code": clean_code,
        "author": str(ctx.author)
    }
    save_snippets_to_disk(snippets)
    await ctx.send(f"💾 Successfully saved snippet as **`{name}`**!")

@bot.command()
async def load(ctx, name: str = None):
    if not name:
        await ctx.send("❌ Usage: `!load <name>`")
        return

    snippets = load_snippets()
    if name not in snippets:
        await ctx.send(f"❌ Snippet **`{name}`** not found!")
        return

    data = snippets[name]
    output = f"📁 **Snippet: `{name}`** (Saved by {data['author']}):\n```python\n{data['code']}\n```"
    if len(output) > 2000:
        output = output[:1950] + "\n...(truncated)\n```"
    await ctx.send(output)

@bot.command()
async def share(ctx, name: str = None):
    if not name:
        await ctx.send("❌ Usage: `!share <name>`")
        return

    snippets = load_snippets()
    if name not in snippets:
        await ctx.send(f"❌ Snippet **`{name}`** not found to share!")
        return

    data = snippets[name]
    await ctx.send(f"🔗 **{ctx.author.name} shared snippet `{name}`:**\n```python\n{data['code']}\n```")

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
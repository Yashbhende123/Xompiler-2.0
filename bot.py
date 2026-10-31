import os
import asyncio
import logging
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

# Mute noisy Flask ping logs in the console
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Xompiler AI Bot is Online and Healthy!", 200

def run_web():
    # Render automatically provides a PORT environment variable
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
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

# --- 4. E2B SANDBOX EXECUTION LOGIC ---
def execute_code_in_sandbox(code_str: str):
    output_lines = []
    try:
        with Sandbox.create() as sandbox:
            execution = sandbox.run_code(code_str)
            
            # Capture standard console output
            if execution.logs.stdout:
                output_lines.append("\n".join(execution.logs.stdout))
                
            # Capture standard error logs if any
            if execution.logs.stderr:
                output_lines.append("\n⚠️ Runtime Error:\n" + "\n".join(execution.logs.stderr))
                
            # Capture E2B Jupyter-style execution errors (like 1 / 0 or NameError)
            if execution.error:
                tb_lines = "".join(execution.error.traceback) if execution.error.traceback else ""
                output_lines.append(f"\n⚠️ Runtime Error:\n{execution.error.name}: {execution.error.value}\n{tb_lines}")
                
            if not output_lines:
                output_lines.append("✅ Code executed successfully with no output.")
    except Exception as e:
        output_lines.append(f"❌ Sandbox Connection Error: {str(e)}")
    
    return "\n".join(output_lines)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (Xompiler AI Edition)")

# --- 5. DISCORD COMMANDS ---
@bot.command()
async def run(ctx, *, code_block: str = None):
    if not code_block:
        await ctx.send("❌ Please provide some code to run! Example: `!run print('Hello')`")
        return

    # Clean markdown code blocks if present
    clean_code = code_block.strip()
    if clean_code.startswith("```"):
        lines = clean_code.splitlines()
        if len(lines) >= 2:
            lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            clean_code = "\n".join(lines)

    msg = await ctx.send(f"⏳ Running code for **{ctx.author.name}**...")

    # Offload E2B sandbox execution to background thread
    result = await asyncio.to_thread(execute_code_in_sandbox, clean_code)

    if len(result) > 1900:
        result = result[:1900] + "\n...(Output truncated)"

    response_text = f"Output for **{ctx.author.name}**:\n```ansi\n{result}\n```"
    await msg.edit(content=response_text)

    # 🤖 AI Auto-Fix Trigger: If output contains a runtime error, call Gemini!
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
            lambda: ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Answer concisely with code examples if needed:\n{question}"
            ).text
        )
        if len(res) > 1950:
            res = res[:1950] + "\n...(truncated)"
        await msg.edit(content=f"🧠 **Answer for {ctx.author.name}:**\n{res}")
    except Exception as e:
        await msg.edit(content=f"❌ AI Error: `{e}`")

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
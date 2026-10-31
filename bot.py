import os
import asyncio
import logging
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands
from dotenv import load_dotenv
from e2b_code_interpreter import Sandbox

# Load local .env if present (Render will use its own Environment Variables)
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- 1. KEEP-ALIVE WEB SERVER FOR RENDER ---
app = Flask(__name__)

# Mute noisy Flask ping logs in the console
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Xompiler Bot is Online and Healthy!", 200

def run_web():
    # Render automatically provides a PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()
# -------------------------------------------

# --- 2. DISCORD BOT & E2B SANDBOX SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Run E2B in a background thread so Discord never freezes or disconnects
def execute_in_e2b(code_str: str):
    with Sandbox.create() as sandbox:
        execution = sandbox.run_code(code_str)
        stdout = "\n".join(execution.logs.stdout)
        stderr = "\n".join(execution.logs.stderr)
        
        if execution.error:
            return f"⚠️ Runtime Error:\n{execution.error.name}: {execution.error.value}\n{execution.error.traceback}"
        
        combined = "\n".join(filter(None, [stdout, stderr]))
        return combined if combined.strip() else "✅ Code executed successfully (no output)."

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

@bot.command(name="run")
async def run_code(ctx, *, code: str):
    # Clean up Discord markdown codeblocks (e.g., ```python ... ```)
    if code.startswith("```"):
        lines = code.strip("`").split("\n")
        if lines[0].strip().isalpha():
            code = "\n".join(lines[1:])
        else:
            code = "\n".join(lines)

    status_msg = await ctx.send(f"⏳ Running code in a secure E2B sandbox for {ctx.author.mention}...")

    try:
        output_text = await asyncio.to_thread(execute_in_e2b, code)
        await status_msg.edit(content=f"Output for {ctx.author.mention}:\n```py\n{output_text[:1900]}\n```")
    except Exception as e:
        await status_msg.edit(content=f"❌ Sandbox Error: `{str(e)}`")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ ERROR: DISCORD_TOKEN is missing! Check your Environment Variables.")
    else:
        keep_alive()
        bot.run(DISCORD_TOKEN)
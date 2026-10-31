Let's build **Option 2: The Automated Complexity & Performance Profiler (`/profile`)**!

When users run or benchmark their code through Xompiler, it won't just output the result—it will automatically calculate the exact execution time and use Gemini to provide a **Big-O Complexity Audit** (Time & Space analysis), flagging inefficiencies or performance bottlenecks right inside the Discord response.

Here is how we integrate `/profile` into **`bot.py`**:

### Updated `bot.py` with the Performance Profiler & Complexity Analyzer

```python
import os
import asyncio
import logging
import json
import time
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

# --- 2. INITIALIZE CLIENTS & FAIL-SAFE SETUP ---
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"⚠️ Warning: Gemini Client initialization failed: {e}")
    ai_client = None

intents = discord.Intents.default()
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

# --- ROBUST GEMINI CALLER WITH FALLBACKS & FAIL-SAFE ---
def ask_gemini(prompt_text: str) -> str:
    if not ai_client:
        return "AI features are currently unavailable (Missing API Key or Client Init Error)."
    
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
            
    return f"AI Error: Unable to generate response. Details: {str(last_error)}"

def get_code_audit(code: str, execution_time: float, output: str) -> str:
    prompt = (
        "You are Xompiler AI's Performance & Complexity Profiler.\n"
        "Analyze the following Python script:\n"
        f"```python\n{code}\n```\n\n"
        f"Execution Time in Sandbox: {execution_time:.4f} seconds\n"
        f"Execution Output / Result:\n```\n{output}\n```\n\n"
        "Provide a concise performance audit containing:\n"
        "1. **Big-O Complexity:** Estimated Time Complexity and Space Complexity.\n"
        "2. **Bottlenecks / Insights:** 1-2 sentences on efficiency or potential performance pitfalls.\n"
        "3. **Optimization Tip:** A quick way to make it faster if applicable.\n"
        "Keep the response clean and under 1500 characters."
    )
    return ask_gemini(prompt)

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print(f"✅ Logged in as {bot.user} & Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ Failed to sync slash commands: {e}")

# --- 3. SLASH COMMAND: /profile (Performance Profiler & Runner) ---
@bot.tree.command(name="profile", description="Execute code and analyze its execution time, output, and Big-O complexity")
@discord.app_commands.describe(
    code="Your Python source code to profile",
    file="Optional source file to profile (.py or .txt)"
)
async def profile(
    interaction: discord.Interaction, 
    code: str = None, 
    file: discord.Attachment = None
):
    await interaction.response.defer()
    
    try:
        clean_code = ""
        sandbox_files = {}

        if file:
            try:
                file_bytes = await file.read()
                file_content = file_bytes.decode('utf-8', errors='ignore')
                if file.filename.endswith('.py') and not code:
                    clean_code = file_content
                else:
                    sandbox_files[file.filename] = file_content
            except Exception as e:
                await interaction.followup.send(f"⚠️ Failed to read file `{file.filename}`: {e}")
                return

        if code:
            code_text = code.strip()
            if code_text.startswith("```"):
                lines = code_text.splitlines()
                if len(lines) >= 2:
                    lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
                    code_text = "\n".join(lines)
            clean_code = code_text if not clean_code else clean_code + "\n" + code_text

        if not clean_code and not sandbox_files:
            await interaction.followup.send("❌ Please provide some code or upload a file to profile!")
            return

        msg = await interaction.followup.send(f"⏱️ Profiling code execution for **{interaction.user.name}**...")

        def execute_and_measure():
            output_lines = []
            start_time = time.time()
            elapsed_time = 0.0
            try:
                with Sandbox.create() as sandbox:
                    for filename, content in sandbox_files.items():
                        sandbox.files.write(filename, content)

                    t0 = time.time()
                    execution = sandbox.run_code(clean_code)
                    elapsed_time = time.time() - t0
                    
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
                elapsed_time = time.time() - start_time
                output_lines.append(f"❌ Sandbox Connection Error: {str(e)}")
            
            return "\n".join(output_lines), elapsed_time

        result, exec_time = await asyncio.to_thread(execute_and_measure)

        if len(result) > 1500:
            result = result[:1500] + "\n...(Output truncated)"

        response_text = f"📊 **Execution Output ({exec_time:.4f}s):**\n```ansi\n{result}\n```"
        await msg.edit(content=response_text)

        # 🧠 Generate AI Complexity Audit
        audit_msg = await interaction.followup.send("🔍 **Xompiler AI is profiling Big-O complexity & performance...**")
        try:
            complexity_report = await asyncio.to_thread(get_code_audit, clean_code, exec_time, result)
            if len(complexity_report) > 1900:
                complexity_report = complexity_report[:1900] + "\n...(truncated)"
            await audit_msg.edit(content=f"📈 **Performance & Complexity Audit:**\n{complexity_report}")
        except Exception as e:
            await audit_msg.edit(content=f"❌ Profiler AI Error: `{e}`")

    except Exception as e:
        await interaction.followup.send(f"❌ Critical profiling error: `{str(e)}`")

# --- 4. STANDARD RUN & SNIPPET COMMANDS ---
@bot.tree.command(name="run", description="Compile and execute programming code")
@discord.app_commands.describe(code="Your source code", file="Optional attachment")
async def run_slash(interaction: discord.Interaction, code: str = None, file: discord.Attachment = None):
    # Standard quick execution fallback
    await interaction.response.send_message("⚡ Use `/profile` to run code with performance metrics and Big-O analysis!", ephemeral=True)

@bot.command()
async def ask(ctx, *, question: str = None):
    try:
        if not question:
            await ctx.send("❌ Please ask a question! Example: `!ask What is a Python decorator?`")
            return
        msg = await ctx.send("🧠 **Thinking...**")
        res = await asyncio.to_thread(lambda: ask_gemini(question))
        await msg.edit(content=f"🧠 **Answer for {ctx.author.name}:**\n{res[:1950]}")
    except Exception as e:
        await ctx.send(f"❌ Error: `{e}`")

@bot.command()
async def save(ctx, name: str = None, *, code_block: str = None):
    if not name or not code_block:
        await ctx.send("❌ Usage: `!save <name> <code>`")
        return
    snippets = load_snippets()
    snippets[name] = {"code": code_block.strip(), "author": str(ctx.author)}
    save_snippets_to_disk(snippets)
    await ctx.send(f"💾 Saved snippet **`{name}`**!")

@bot.command()
async def load(ctx, name: str = None):
    if not name or name not in load_snippets():
        await ctx.send("❌ Snippet not found!")
        return
    data = load_snippets()[name]
    await ctx.send(f"📁 **`{name}`** (by {data['author']}):\n```python\n{data['code']}\n```")

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)

```
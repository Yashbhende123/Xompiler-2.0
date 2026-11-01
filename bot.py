import os
import asyncio
import logging
import json
import time
import io
import textwrap
import ast
from threading import Thread
from flask import Flask
import discord
from discord.ui import Modal, TextInput, View, Button
from discord.ext import commands
from dotenv import load_dotenv
from e2b_code_interpreter import Sandbox
from google import genai

# Load local .env if present (Render will use its own Environment Variables)
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
E2B_API_KEY = os.getenv("E2B_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- CONFIGURE YOUR PRIVATE LOG CHANNEL ID HERE ---
LOG_CHANNEL_ID = 1566318931864715395 # Replace with your copied Discord Channel ID integer

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

# Your specific Server Guild ID for instant slash command sync
MY_GUILD_ID = discord.Object(id=1555987168470499370)

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

# --- ROBUST GEMINI CALLER ---
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

# --- STRICT CONTENT SAFETY CLASSIFIER ---
def classify_content_safety(text_content: str) -> str:
    if not ai_client:
        return "[SAFE]"
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "You are a strict content moderation AI for a secure code compiler. "
                "Analyze the following code or execution output for safety violations, profanity, explicit words, sexual content, abuse, or threats. "
                "If the content contains ANY sexual terms (like 'sex', explicit anatomy, etc.), profanity, hate speech, or abusive language, you MUST flag it as [SEXUAL/NSFW] or [ABUSE/HARASSMENT]. "
                "Only classify as [SAFE] if it is entirely clean code with zero profanity or sexual references. "
                "Return ONLY the category tag in brackets, chosen from: [SAFE], [ABUSE/HARASSMENT], [VIOLENCE/THREAT], [SEXUAL/NSFW].\n\n"
                f"Content:\n{text_content[:1000]}"
            )
        )
        return response.text.strip() if response and response.text else "[SAFE]"
    except Exception:
        return "[SAFE]"

# --- PRIVATE AUDIT LOG HELPER ---
async def send_execution_log(bot_instance, guild, user_name, code_text, stdin_text, result_text, exec_time):
    if not LOG_CHANNEL_ID or LOG_CHANNEL_ID == 0:
        return
    try:
        channel = bot_instance.get_channel(LOG_CHANNEL_ID)
        if not channel and guild:
            channel = guild.get_channel(LOG_CHANNEL_ID)
        
        if channel:
            combined_text = f"{code_text}\n{result_text}"
            safety_tag = classify_content_safety(combined_text)
            
            alert_prefix = "🟢 **Status: Safe Execution**"
            if any(flag in safety_tag for flag in ["ABUSE", "VIOLENCE", "THREAT", "SEXUAL"]):
                alert_prefix = "🚨 **FLAGGED CONTENT DETECTED!**"

            log_content = (
                f"{alert_prefix}\n"
                f"🏷️ **Category Flag:** `{safety_tag}`\n"
                f"👤 **User:** `{user_name}`\n"
                f"⏱️ **Execution Time:** `{exec_time:.4f}s`\n"
                f"📥 **Stdin Inputs:** `{stdin_text if stdin_text else 'None'}`\n"
                f"💻 **Source Code:**\n```python\n{code_text[:800]}\n```\n"
                f"📊 **Output / Result:**\n```ansi\n{result_text[:1000]}\n```"
            )
            await channel.send(log_content)
    except Exception as e:
        print(f"⚠️ Failed to send execution log: {e}")

@bot.event
async def on_ready():
    try:
        bot.tree.copy_global_to(guild=MY_GUILD_ID)
        await bot.tree.sync(guild=MY_GUILD_ID)
        print(f"✅ Logged in as {bot.user} & Slash Commands synced instantly to your server!")
    except Exception as e:
        print(f"⚠️ Failed to sync slash commands: {e}")

# --- PRE-FLIGHT AST SECURITY GUARDRAIL ---
def security_scan(code: str):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None 

    forbidden_modules = {'subprocess', 'ctypes', 'multiprocessing'}
    forbidden_funcs = {'eval', 'exec'}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules:
                    return f"🔒 **Security Guardrail Violation:** Importing restricted module `{alias.name}` is blocked for safety."
        elif isinstance(node, ast.ImportFrom):
            if node.module in forbidden_modules:
                return f"🔒 **Security Guardrail Violation:** Importing from restricted module `{node.module}` is blocked."
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_funcs:
                return f"🔒 **Security Guardrail Violation:** Use of built-in function `{node.func.id}()` is restricted."
    return None

# --- MULTI-FILE PROJECT PARSER ---
def parse_multi_file_code(raw_code: str):
    files = {}
    current_file = "main.py"
    current_lines = []

    for line in raw_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("# file:") or stripped.startswith("# filename:"):
            if current_lines:
                files[current_file] = "\n".join(current_lines).strip()
                current_lines = []
            current_file = stripped.split(":", 1)[1].strip()
        else:
            current_lines.append(line)
    
    if current_lines or not files:
        files[current_file] = "\n".join(current_lines).strip()

    main_code = files.get("main.py", list(files.values())[0] if files else raw_code)
    sandbox_files = {fname: content for fname, content in files.items() if fname != "main.py"}
    
    return main_code, sandbox_files

# --- INTERACTIVE TOOLBAR VIEW ---
class XompilerToolbarView(View):
    def __init__(self, response_text: str, plot_bytes: bytes = None, clean_code: str = "", author_name: str = "User"):
        super().__init__(timeout=None)
        self.response_text = response_text
        self.plot_bytes = plot_bytes
        self.clean_code = clean_code
        self.author_name = author_name

    @discord.ui.button(label="🌍 Share Publicly", style=discord.ButtonStyle.green, row=0, custom_id="xompiler_share")
    async def share_button(self, interaction: discord.Interaction, button: Button):
        try:
            button.disabled = True
            button.label = "Shared ✅"
            await interaction.response.edit_message(view=self)

            if self.plot_bytes:
                file_obj = discord.File(io.BytesIO(self.plot_bytes), filename="xompiler_plot.png")
                await interaction.channel.send(f"🔓 **Shared output by {self.author_name}:**\n{self.response_text}", file=file_obj)
            else:
                await interaction.channel.send(f"🔓 **Shared output by {self.author_name}:**\n{self.response_text}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error sharing: {e}", ephemeral=True)

    @discord.ui.button(label="🤖 Fix with AI", style=discord.ButtonStyle.blurple, row=0, custom_id="xompiler_fix_ai")
    async def fix_ai_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            msg = await interaction.followup.send("🤖 Xompiler AI is analyzing your error and debugging the code...", ephemeral=True)

            prompt = (
                "You are an expert Python debugging assistant.\n"
                "The following Python code produced an error or failed execution:\n"
                f"```python\n{self.clean_code}\n```\n\n"
                f"Execution Output / Error:\n```\n{self.response_text}\n```\n\n"
                "Fix the bug or error in the code. Return ONLY the corrected Python code inside a clean markdown code block (```python ... ```) without any conversational explanation."
            )

            ai_response = await asyncio.to_thread(lambda: ask_gemini(prompt))
            
            fixed_code = ai_response
            if "```python" in ai_response:
                parts = ai_response.split("```python")
                if len(parts) > 1:
                    fixed_code = parts[1].split("```")[0].strip()
            elif "```" in ai_response:
                parts = ai_response.split("```")
                if len(parts) > 1:
                    fixed_code = parts[1].split("```")[0].strip()

            await msg.edit(content="✨ **AI Fixed Code Generated! Re-running fixed version...**")
            await execute_and_render_code(interaction, fixed_code, {}, "", existing_msg=msg)

        except Exception as e:
            try:
                await interaction.followup.send(f"❌ AI Fix Error: {e}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="📥 Download File", style=discord.ButtonStyle.secondary, row=1, custom_id="xompiler_download")
    async def download_button(self, interaction: discord.Interaction, button: Button):
        try:
            code_file = discord.File(io.BytesIO(self.clean_code.encode('utf-8')), filename="script.py")
            await interaction.response.send_message("📥 Here is your downloadable script file:", file=code_file, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error downloading file: {e}", ephemeral=True)

    @discord.ui.button(label="🔄 Re-run", style=discord.ButtonStyle.primary, row=1, custom_id="xompiler_rerun")
    async def rerun_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            msg = await interaction.followup.send("🔄 Re-running your code snippet...", ephemeral=True)
            await execute_and_render_code(interaction, self.clean_code, {}, "", existing_msg=msg)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Re-run error: {e}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="🧹 Format Code", style=discord.ButtonStyle.secondary, row=1, custom_id="xompiler_format")
    async def format_button(self, interaction: discord.Interaction, button: Button):
        try:
            formatted = textwrap.dedent(self.clean_code).strip()
            formatted_box = f"🧹 **Formatted Clean Code:**\n```python\n{formatted}\n```"
            if len(formatted_box) > 1950:
                formatted_box = formatted_box[:1950] + "\n...(truncated)"
            await interaction.response.send_message(formatted_box, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Formatting error: {e}", ephemeral=True)

# --- CORE EXECUTION & MATPLOTLIB CAPTURE ENGINE ---
async def execute_and_render_code(interaction: discord.Interaction, raw_code: str, sandbox_files: dict, input_data: str, existing_msg: discord.WebhookMessage = None):
    security_error = security_scan(raw_code)
    if security_error:
        if existing_msg:
            await existing_msg.edit(content=security_error)
        else:
            await interaction.followup.send(security_error, ephemeral=True)
        return

    main_code, parsed_files = parse_multi_file_code(raw_code)
    sandbox_files.update(parsed_files)

    matplotlib_wrapper = (
        "import sys\n"
        "try:\n"
        "    import matplotlib\n"
        "    matplotlib.use('Agg')\n"
        "    import matplotlib.pyplot as plt\n"
        "except ImportError:\n"
        "    pass\n\n"
    )

    if input_data or "input(" in main_code:
        main_code = (
            "from io import StringIO\n"
            f"_inputs = {repr(input_data)}.split()\n"
            "_input_iter = iter(_inputs)\n"
            "def custom_input(prompt=''):\n"
            "    print(prompt, end='')\n"
            "    try:\n"
            "        return next(_input_iter)\n"
            "    except StopIteration:\n"
            "        return ''\n"
            "__builtins__.input = custom_input\n\n"
        ) + main_code

    full_code = matplotlib_wrapper + main_code + (
        "\n\n# Xompiler Matplotlib Auto-Capture\n"
        "try:\n"
        "    import matplotlib.pyplot as plt\n"
        "    if plt.get_fignums():\n"
        "        plt.savefig('xompiler_plot.png', bbox_inches='tight', dpi=150)\n"
        "        plt.close('all')\n"
        "except Exception:\n"
        "    pass\n"
    )

    if existing_msg:
        msg = existing_msg
    else:
        msg = await interaction.followup.send(f"⏱️ Executing code privately for **{interaction.user.name}**...", ephemeral=True)

    def run_sandbox():
        output_lines = []
        plot_bytes = None
        start_time = time.time()
        elapsed_time = 0.0
        try:
            with Sandbox.create() as sandbox:
                for filename, content in sandbox_files.items():
                    sandbox.files.write(filename, content)

                t0 = time.time()
                execution = sandbox.run_code(full_code)
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

                try:
                    if sandbox.files.exists("xompiler_plot.png"):
                        plot_bytes = sandbox.files.read("xompiler_plot.png", format="bytes")
                except Exception:
                    pass

        except Exception as e:
            elapsed_time = time.time() - start_time
            output_lines.append(f"❌ Sandbox Connection Error: {str(e)}")
        
        return "\n".join(output_lines), elapsed_time, plot_bytes

    result, exec_time, plot_data = await asyncio.to_thread(run_sandbox)

    # 🚀 SEND DATA TO PRIVATE LOGS CHANNEL WITH STRICT SAFETY CLASSIFICATION
    await send_execution_log(
        bot_instance=interaction.client,
        guild=interaction.guild,
        user_name=interaction.user.name,
        code_text=raw_code,
        stdin_text=input_data,
        result_text=result,
        exec_time=exec_time
    )

    if len(result) > 1500:
        result = result[:1500] + "\n...(Output truncated)"

    response_text = f"📊 **Execution Output ({exec_time:.4f}s):**\n```ansi\n{result}\n```"
    
    toolbar_view = XompilerToolbarView(response_text, plot_data, main_code, interaction.user.name)

    if plot_data:
        file_obj = discord.File(io.BytesIO(plot_data), filename="xompiler_plot.png")
        await msg.edit(content=response_text, attachments=[file_obj], view=toolbar_view)
    else:
        await msg.edit(content=response_text, view=toolbar_view)

# --- INTERACTIVE MULTI-LINE CODEBOX MODAL ---
class CodeBoxModal(Modal, title="Xompiler AI - Secure Codebox"):
    code_input = TextInput(
        label="Python Code",
        style=discord.TextStyle.paragraph,
        placeholder="print('Hello, Xompiler!')",
        required=True,
        max_length=2000
    )
    stdin_input = TextInput(
        label="Stdin / Program Inputs (Optional)",
        style=discord.TextStyle.short,
        placeholder="e.g. yash 21",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏱️ Initializing secure sandbox and executing...", ephemeral=True)
        msg = await interaction.original_response()

        code_text = self.code_input.value.strip()
        
        if code_text.startswith("```"):
            lines = code_text.splitlines()
            if len(lines) >= 2:
                lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
                code_text = "\n".join(lines)

        await execute_and_render_code(interaction, code_text, {}, self.stdin_input.value or "", existing_msg=msg)

# --- 3. SLASH COMMANDS (/run, /profile, /codebox) ---
@bot.tree.command(name="run", description="Execute code quickly")
@discord.app_commands.describe(code="Your Python code to execute")
async def run_slash(interaction: discord.Interaction, code: str):
    await interaction.response.send_message("⏱️ Initializing secure sandbox and executing...", ephemeral=True)
    msg = await interaction.original_response()
    code_text = code.strip()
    if code_text.startswith("```"):
        lines = code_text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            code_text = "\n".join(lines)
    await execute_and_render_code(interaction, code_text, {}, "", existing_msg=msg)

@bot.tree.command(name="profile", description="Privately execute code with multi-file and AST guardrails")
@discord.app_commands.describe(
    code="Your Python source code",
    file="Optional source file (.py or .txt)",
    stdin="Program inputs (e.g. yash 21)"
)
async def profile(
    interaction: discord.Interaction, 
    code: str = None, 
    file: discord.Attachment = None,
    stdin: str = None
):
    await interaction.response.defer(ephemeral=True)
    
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
                await interaction.followup.send(f"⚠️ Failed to read file `{file.filename}`: {e}", ephemeral=True)
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
            await interaction.followup.send("❌ Please provide some code or upload a file to execute!", ephemeral=True)
            return

        await execute_and_render_code(interaction, clean_code, sandbox_files, stdin or "")

    except Exception as e:
        await interaction.followup.send(f"❌ Critical execution error: `{str(e)}`", ephemeral=True)

@bot.tree.command(name="codebox", description="Open a secure multi-line code editor popup window")
async def codebox(interaction: discord.Interaction):
    await interaction.response.send_modal(CodeBoxModal())

# --- 4. STANDARD PREFIX COMMANDS ---
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
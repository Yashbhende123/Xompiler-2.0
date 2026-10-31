# Xompiler-2.0 🚀

Xompiler-2.0 is an advanced, AI-powered Discord bot designed to execute Python code securely in the cloud via **E2B**, while featuring native **Gemini AI** integration for intelligent code assistance, automated crash debugging, and conversational developer support.

---

## 💡 Evolution & Architecture

### Phase 1: Core Execution & Initial Setup
Initially, Xompiler was built purely as a code execution tool. Users could run Python snippets in isolated cloud sandboxes using E2B, ensuring safety and isolation. However, runtime errors and tracebacks were handled strictly at the terminal or standard output level without intelligent remediation — if code crashed, the user received a raw error trace and had to debug manually.

### Phase 2: Native Gemini AI Integration
To elevate Xompiler into a true AI-native coding companion, we integrated the Google GenAI SDK (`google-genai`). The bot now features:
- **Automated Crash Analysis & Auto-Fix:** Whenever a user's code snippet throws a runtime error or Jupyter-style notebook traceback (`execution.error`), Xompiler AI automatically intercepts the error, analyzes the traceback via Gemini, and posts an instant explanation along with corrected code.
- **Interactive `!ask` Queries:** Users can query Gemini directly within Discord for programming concepts, syntax help, and architectural advice using the `!ask` command.
- **Robust Model Fallback Mechanism:** Built-in fault-tolerance that automatically routes requests through active flash model endpoints to ensure 99.9% uptime and prevent traffic spike disruptions.
- **24/7 Render Hosting:** Maintained continuously online using a lightweight Flask keep-alive web server integrated with GitHub webhooks.

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Discord Framework:** `discord.py`
* **AI Engine:** Google GenAI SDK (`google-genai`) using Gemini models with automated fallback routing
* **Execution Environment:** `e2b-code-interpreter` (`Sandbox.create()`)
* **Hosting / Infrastructure:** Render (24/7 deployment via GitHub webhooks with a Flask keep-alive server)
* **Configuration:** `python-dotenv`

---

## ⚙️ Commands

* `!run <code>`: Executes Python code inside an isolated E2B cloud sandbox. If an error occurs, Gemini automatically analyzes the traceback and provides a corrective fix.
* `!ask <question>`: Directly queries Gemini AI for code explanations, debugging help, or general programming knowledge.

# ⚡ Xompiler 2.0 — 24/7 Cloud Code Execution Discord Bot

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/discord.py-2.0+-5865F2?logo=discord&logoColor=white)
![E2B](https://img.shields.io/badge/Sandbox-E2B_Cloud-orange)
![Render](https://img.shields.io/badge/Hosted_on-Render_24%2F7-46E3B7?logo=render&logoColor=black)

**Xompiler** is a lightweight, high-performance Discord bot that compiles and executes code directly inside Discord channels. Instead of running untrusted code on a local machine, every `!run` command dynamically boots an isolated **E2B Cloud Sandbox** micro-VM in milliseconds.

---

## ✨ Features & Capabilities
* **Isolated Cloud Execution:** Every command runs in a secure, disposable Ubuntu Linux micro-VM powered by the **E2B Code Interpreter SDK**.
* **Non-Blocking Event Loop:** Heavy workloads are offloaded via `asyncio.to_thread()` so the Discord Gateway heartbeat never freezes or disconnects.
* **24/7 Cloud Uptime:** Deployed on **Render** with an integrated background **Flask** keep-alive server monitored every 5 minutes by **UptimeRobot**.
* **Multi-Language & Library Support:**
  * **Languages:** Python 3, C/C++ (`gcc`/`g++`), SQL (`sqlite3`), Bash/Linux CLI, and Node.js.
  * **Pre-Installed Libraries:** `numpy`, `pandas`, `scipy`, `scikit-learn`, `matplotlib`, `requests`, `beautifulsoup4`, `psutil`, and more.

---

## 🚀 Usage in Discord

Run a quick one-liner:
```text
!run print("Hello from Xompiler 2.0 Cloud!")
```

Or run full multi-line code blocks with Discord syntax highlighting:
```text
!run ```python
import numpy as np
import pandas as pd

matrix = np.random.rand(500, 500)
print("Matrix Mean:", round(float(np.mean(matrix)), 4))
```
```

---

## ☁️ How We Built & Deployed It (Architecture)
1. **Core Bot & E2B Integration:** Built with `discord.py` and `e2b-code-interpreter` for isolated cloud execution.
2. **Async Threading Fix:** Wrapped E2B sandbox execution in `asyncio.to_thread()` to prevent blocking the main Discord event loop.
3. **Keep-Alive Web Server:** Added a lightweight `Flask` server running on a daemon thread (`keep_alive()`) to expose a `200 OK` health-check endpoint.
4. **Secure Cloud Deployment:** Hosted on **Render** connected directly to this GitHub repository, with sensitive keys (`DISCORD_TOKEN` and `E2B_API_KEY`) stored strictly inside encrypted Environment Variables.
5. **Zero-Downtime Monitoring:** Configured an **UptimeRobot** HTTP monitor to ping the Render endpoint every 5 minutes, bypassing the 15-minute free-tier idle spin-down.

---

## 🛠️ Local Setup (Optional)

1. Clone this repository:
   ```bash
   git clone [https://github.com/Yashbhende123/Xompiler.git](https://github.com/Yashbhende123/Xompiler.git)
   cd Xompiler
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the root folder and add your keys:
   ```env
   DISCORD_TOKEN=your_discord_bot_token_here
   E2B_API_KEY=your_e2b_api_key_here
   ```
4. Start the bot:
   ```bash
   python bot.py
   ```

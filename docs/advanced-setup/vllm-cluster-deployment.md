# Odysseus Setup: Docker Container Cluster Deployment
Odysseus features a built-in `Cookbook` designed to scan system hardware and run inference models locally. However, it uses a background task to fetch the image and spin up a **single** isolated runner instance. It doesn't naturally look ahead to see that you are trying to run a container cluster on a single machine. When running multiple high parameter models concurrently (such as jumping between heavy text generation, deep coding, and vision processing), virtual large language models  `vllms`  tend to claim most of your GPU's VRAM, throwing an immediate `ValueError` or causing the subsequent containers to crash.

This community-maintained recipe is beginner-friendly and designed specfically for Windows gaming pcs that want to run up to three background vllm engines (general text, deep coding, and vision processing) via `docker containers` and proxy Odysseus chat prompts through an automated FastAPI gateway to contextually choose which model is used.

### This recipe automates Odysseus' vLLM cookbook setup in the following ways:
1. Scans your system hardware using NVLM/SMI.
2. Partitions your containers based on GPU VRAM capacity (reserving headroom for your OS and per engine CUDA context).
3. Querys the live Odysseus local backend API to pull all available models (mimicing the Cookbook UI).
5. Ranks models by an `Architectural Fit Score` using a weighted formula, presenting up to 20 "PERFECT" models to select from that are sorted by performance for that slice.
6. Deploys the general text, deep coding, and vision processing models via docker vllm containers.

---

## System Requirements

⚠️ **Confirm that your machine meets the following base dependencies before proceeding.**

### Hardware
* **24GB VRAM (GPU)**
  * Requires an NVIDIA graphics card with deep VRAM pools (RTX 3090, 4090, or 5090) to run multiple high parameter models concurrently.
* **32GB RAM (System Memory)**
  * A minimum of 32GB of system-level RAM to support base Docker cluster overhead and keep your OS workspace stable.

### Software
* **Windows 11 (64-bit)**
  * Legacy operating systems (including all versions of Windows 10) are **unsupported** due to structural limitations in older WSL 2 kernels and virtual network routing required by the current Odysseus framework.
* **GIT**
  * **INSTALL:** https://git-scm.com/
* **Python 3.12 or 3.13**
  * **INSTALL:** https://www.python.org/downloads/
  * During setup, ensure the checkbox  `Add Python to environment variables`  is ticked.
  * Avoid using experimental pre-releases (such as Python 3.14+ testing branches) as library wheels will fail to compile.
* **WSL 2**
  * **INSTALL:** In your terminal, type  `wsl --install`
  * Can also be installed during Docker setup
* **Docker Desktop**
  * **INSTALL:** https://docs.docker.com/desktop/setup/install
  * During setup, ensure the checkbox  `Use the WSL 2 based engine`  is ticked.
* **NVIDIA Container Toolkit**
  * included with Docker Desktop for Windows, unlike Linux or MacOS.
  * Run the toolkit initialization script inside your host WSL 2 terminal to pass GPU specs down to your Docker runtimes.

**🔁Restart your computer and lauch Docker Desktop**  **(ensure that** `Start Docker Desktop when you sign in to your computer` **is enabled in the Docker settings).**

**✅Confirm Docker and Cookbook will recognize your hardware. In your terminal, run:**
```powershell
  docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```


## 🎛️ The Dynamic Hardware Scaling Blueprint

Instead of utilizing hardcoded memory metrics, calculate your VRAM slices using the matrix below. Always reserve roughly **10% of your total hardware capacity as a buffer headroom** for your native Windows desktop display environment, browser graphics acceleration, or streaming tools.

| Total Available VRAM | Text Generation | Deep Coding | Vision Processing | OS Overhead |
| :--- | :--- | :--- | :--- | :--- |
| **24 GB** *(RTX 3090 / 4090)* | **40%** (`0.40`) | **25%** (`0.25`) | **25%** (`0.25`) | 10% (Safe Buffer) |
| **32 GB** *(Flagship / 5090 Class)* | **45%** (`0.45`) | **25%** (`0.25`) | **20%** (`0.20`) | 10% (Safe Buffer) |
| **48 GB+** *(Dual-GPU / Workstation)*| **60%** (`0.60`) | **20%** (`0.20`) | **10%** (`0.10`) | Dedicated OS Allocation |

---

## 🏗️ System Architecture Layout

When you input text or upload images inside the main Odysseus interface, your context payload streams instantly through this isolated, local routing loop:

[Odysseus Web UI (Port 7000)]
             │
             ▼
[Smart VRAM Router Proxy (Port 5000)]
             │
             ├──► (Has Image Array) ──► [vllm-qwen-vision   (Port 8003)] ─► Budget: Adaptive VRAM %
             ├──► (Matches Code RegEx)─► [vllm-deepseek-code (Port 8002)] ─► Budget: Adaptive VRAM %
             └──► (Default Fallback)  ──► [vllm-qwen-general  (Port 8001)] ─► Budget: Adaptive VRAM %
                                                                                │
                                           (Automatic Cascade Fallback Loop) ───┘

---

## 🛑 Critical Pain Points & Port Restrictions

* **Port Mapping Conflicts:** The default Odysseus application stack locks down ports `7000`, `8080`, `8100`, and `8091` to run its core frontend, web tools, search engines, and database nodes. The custom engines outlined below explicitly map to host ports `8001`, `8002`, and `8003`. Ensure no other web utilities are listening on these slots.
* **Zombie Container Collisions:** Attempting to execute a `docker run` statement when a prior container string shares an identical `--name` property results in a fatal name-clash error. Preexisting stalled container instances must be entirely removed before you run clean launch tags.
* **Missing Environment System Paths:** If you skipped checking the "Add Python to variables" installer toggle, executing `python` or `pythonw` commands will throw an unmapped system pathing error.

---

## 🐳 Step 1: Deploy the Dynamic Container Fleet

This recipe includes an automated initialization script that queries the NVIDIA Container Toolkit, reads your exact physical VRAM footprint, and divides the memory targets cleanly to protect your host system headroom.

1. Save the `init_cluster.py` script in your project workspace directory.
2. In your terminal, run the container cluster deployment:
```powershell
   python init_cluster.py
```
3. Review the terminal display window. The system will prompt you with an interactive overview detailing your exact hardware specs, target memory budgets, and scoring math. Press `ENTER` to let the script safely connect to the local Odysseus API backend, rank the live model index, and trigger your multi-engine container deployment automatically.

## 💻 Step 2: Configure the Smart VRAM Proxy Router

Once your three background vLLM containers are up and running, you need a dynamic gateway to intercept incoming Odysseus API payloads and contextually switch between models.

The proxy router script below monitors strings for structural image formats, manual user markdown flags (/code, /chat, /general), or exact regex programming indicators (such as python, react, postgres, or json structure) and shifts the query execution path to the designated engine port without breaking your open web stream.

1. Save the `vram_router.py` script in your project workspace directory.
2. Install the required asynchronous server dependencies via your PowerShell terminal:
   ```powershell
   pip install fastapi uvicorn httpx
   ```
3. In your terminal, run the vram router:
   ```powershell
   python vram_router.py
   ```

## ⚙️ Step 3: Map the Odysseus Web UI to the Proxy Gateway

To route your active workspace chat prompts through the background pipeline, you must alter the default single-model backend connection inside the main Odysseus application settings:

  1. Launch Odysseus in a browser: `http://localhost:7000`
  2. Open the System Configurations Menu in the bottom left-hand corner of the dashboard interface.
  3. Locate the Inference Provider Target Settings Layer and swap the primary configuration entry point away from the default standalone option to custom server connectivity:
      * Base Server URL Destination: `http://localhost:5000/v1`
      * API Authentication Pass-key Token: `odysseus-cluster-token-bypass`
  4. Save the adjustments. Every prompt sent through your UI chat windows will now automatically trigger the background regex scanner and stream tokens directly from the most appropriate specialized hardware engine.

## 🔄 Step 4: Configure Persistent Autostart (Zero-Touch Booting)

To turn your Windows gaming rig into a true self-healing local AI appliance, you can configure both your Docker containers and the custom gateway router to initialize invisibly the second you log into your system.

Docker includes a native parameter setting known as a Restart Policy. When assigned to an active runner instance, the underlying daemon core monitors the container state and forces a self-healing auto-wake sequence upon host system initialization or unexpected process crashes.

Open a standard PowerShell terminal window and execute this global management block to update your existing local engine stack simultaneously:
```powershell
docker update --restart unless-stopped $(docker ps -q)
```

To execute your custom Python proxy engine seamlessly without cluttering your desktop space with unclosable command prompt windows, you can drop an optimized background shortcut directly into your user account's hidden Windows Startup catalog directory.
  1. Press Win + R on your mechanical keyboard to summon the native Windows Run Dialog Window.
  2. Type shell:startup exactly into the input field and press Enter. This will open your user profile's hidden Windows Startup storage folder.
  3. Right-click an open space inside that directory, hover over New, and select Shortcut from the system context panel.
  4. Paste the following tailored command structure inside the target location string box (ensure you update the absolute path segment at the tail end to match the exact project directory where your file is located):
     ```python
     pythonw.exe "C:\Path\To\Your\Project\Folder\vram_router.py"
     ```

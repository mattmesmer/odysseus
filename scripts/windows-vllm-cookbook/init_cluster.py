import subprocess
import os
import json
import sys
import requests

ODYSSEUS_ACTIVE_TOKEN = ""

def display_architectural_overview():
    """Displays conceptual instructions on how the cluster partitioning and ranking math operates before scanning hardware."""
    print("=" * 122)
    print("               ODYSSEUS: vLLM CONTAINER CLUSTER DEPLOYMENT SYSTEM")
    print("=" * 122)
    print(f"  1. CLUSTER PARTITIONING & MEMORY TAXATION")
    print(f"     * HOST VRAM         : ~VRAM capacity is detected via NVML/SMI.")
    print(f"     * OS PARTITION      : ~10% VRAM reserved for OS stability.")
    print(f"     * CLUSTER SLICES    : General Text (ex. 50%) | Deep Coding (ex. 25%) | Vision Processing (ex. 25%)")
    print(f"     * CUDA TAX          : Each active engine is penalized 0.5 GB for base CUDA context instantiation.")
    print("-" * 122)
    print(f"  2. RANKING SYSTEM")
    print(f"     Instead of filtering by file size or sorting by arbitrary popularity metrics,")
    print(f"     the script calculates a custom 'Architectural Fit Score' for every model using a weighted formula and ranks them for each slice:")
    print(f"     ")
    print(f"         Rank = (Intelligence_Score * 0.70) + (VRAM_Alignment_Component * 0.30)")
    print(f"     ")
    print(f"     * 70% Intelligence Weight: Prioritizes absolute reasoning capacity, logical depth, and parameter quality.")
    print(f"     * 30% Resource Alignment : Scores models based on how perfectly they utilize their dynamic slice target.")
    print(f"                                Minimal deltas from your ideal calculated slice target are given perfect marks,")
    print(f"                                allowing high-intel variants to comfortably claim the top menu spots.")
    print("-" * 122)
    print(f"  3. DYNAMIC HEADROOM PROTECTION & SMART SCALING")
    print(f"     * Hard Overrun Intercept: The script monitors your cluster memory as selections are deployed.")
    print(f"     * If a model's static weight file exceeds the real-time maximum usable headroom, it is instantly")
    print(f"       assigned a catastrophic penalty rank (-9999) to drop it out of selection contention completely.")
    print(f"     * KV Cache Fail-Safe: Max context lengths scale down on the fly based on VRAM slice budgets")
    print(f"       to prevent runtime out-of-memory or allocation balance errors during engine initialization.")
    print("=" * 122)
    input("\n  [>>>] System blueprint staged. Press ENTER to scan your hardware and connect to the local app server... ")
    print("=" * 122 + "\n")

def get_total_vram_gb():
    """Queries nvidia-smi to fetch exact VRAM capacity, halting explicitly on failure."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return round(int(result.stdout.strip().split("\n")[0]) / 1024)
    except Exception as e:
        print(f"\nCRITICAL ERROR: HARDWARE SCAN FAILED: {e}")
        print("-" * 60)
        print("1. Ensure NVIDIA proprietary drivers are installed and active.")
        print("2. Add Nvidia-SMI to your System PATH variables if missing.")
        print("3. Test communication by running 'nvidia-smi' directly in terminal.")
        print("-" * 60 + "\n")
        sys.exit(1)

def fetch_odysseus_master_catalog():
    """Fires a SINGLE authenticated request to harvest the global model registry."""
    url = "http://localhost:7000/api/hwfit/models?limit=100&sort=newest"
    token = None

    if ODYSSEUS_ACTIVE_TOKEN and ODYSSEUS_ACTIVE_TOKEN != "PASTE_YOUR_COPIED_TOKEN_HERE":
        token = ODYSSEUS_ACTIVE_TOKEN
    else:
        scan_paths = [
            os.path.expanduser("~/Documents/odysseus/data/sessions.json"),
            os.path.expanduser("~/odysseus/data/sessions.json"),
            os.path.join(os.getcwd(), "data", "sessions.json")
        ]
        for path in scan_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        session_data = json.load(f)
                    if isinstance(session_data, dict) and session_data:
                        session_hashes = list(session_data.keys())
                        if session_hashes:
                            token = session_hashes[-1]
                            break
                except Exception:
                    continue

    if not token:
        print("\n[❌] AUTHENTICATION BOUNDARY REJECTED: No token configuration or local session files found.")
        sys.exit(1)

    headers = {"Cookie": f"odysseus_session={token}"}

    try:
        print("Connecting to local app server backend on port 7000...")
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
         
        master_list = data.get("models", data) if isinstance(data, dict) else data
        if isinstance(master_list, list):
            return master_list
    except Exception as e:
        print(f"\nCRITICAL CACHE CONTEXT FAILURE: {e}")
        sys.exit(1)
    return []

def calculate_weighted_rank(model, target_allocation_gb, maximum_usable_headroom):
    """Dynamic Hardware-Aware Ranking Engine."""
    base_score = float(model.get('score', 0.0))
    vram_req = float(model.get('required_gb', 8.0))
     
    if vram_req > maximum_usable_headroom:
        return (-9999.0, 0.0, 0.0, 0.0)

    vram_delta = abs(vram_req - target_allocation_gb)
    vram_component = max(0.0, 100.0 - (vram_delta * 15.0))

    final_architectural_rank = (base_score * 0.70) + (vram_component * 0.30)

    raw_param = model.get('params_b', 0.0)
    if not raw_param:
        param_str = str(model.get('parameter_count', '0.0')).upper().replace('B', '').strip()
        try:
            raw_param = float(param_str)
        except ValueError:
            raw_param = 0.0
             
    raw_speed = float(model.get('speed_tps', 0.0))
    return (final_architectural_rank, base_score, raw_param, raw_speed)

def display_interactive_menu(category_label, options, available_slice, running_pool_vram, total_gpu_vram):
    """Generates a comprehensive terminal dashboard mirroring the Cookbook layout."""
    CUDA_CONTEXT_TAX = 0.5
    current_container_ceiling = running_pool_vram - CUDA_CONTEXT_TAX

    print("\n" + "=" * 122)
    print(f"  MODEL CATEGORY : {category_label.upper()}")
    print("-" * 122)
    print(f"  -> TARGET VRAM               : {available_slice:.1f} GB")
    print(f"  -> TOTAL HEADROOM            : {running_pool_vram:.1f} GB")
    print(f"  -> SINGLE CONTAINER MAX      : {max(0.0, current_container_ceiling):.1f} GB")
    print("=" * 122)
     
    if not options:
        print(f"  [!] No valid models available for the '{category_label}' slice selection.")
        sys.exit(1)
         
    sorted_options = sorted(
        options, 
        key=lambda m: calculate_weighted_rank(m, available_slice, current_container_ceiling), 
        reverse=True
    )
     
    filtered_options = []
    for model in sorted_options:
        vram_req = float(model.get('required_gb', 8.0))
        fit_level = str(model.get('fit_level', '')).strip().upper()
         
        # Keeps loose score requirements so smaller vision profiles map clean
        if fit_level in ["PERFECT", "GOOD"] and vram_req < current_container_ceiling:
            filtered_options.append(model)
             
    filtered_options = filtered_options[:20]
     
    if not filtered_options:
        print(f"  [!] No 'PERFECT' or 'GOOD' fit variants found in this category that safely match remaining headroom.")
        sys.exit(1)
         
    print(f"  {'IDX':<6} {'FIT':<10} {'MODEL (LATEST)':<40} {'PARAM':<7} {'QUANT':<11} {'VRAM':<7} {'CTX':<6} {'SPEED':<10} {'SCORE':<5}")
    print("-" * 122)
     
    for i, model in enumerate(filtered_options):
        vram_req = model.get('required_gb', 8.0)
        fit_level = str(model.get('fit_level', 'PERFECT')).upper()
         
        param_val = model.get('parameter_count', 'N/A')
        quant_val = model.get('quant', 'N/A')
        ctx_val = model.get('context', 'N/A')
        speed_val = model.get('speed_tps', 'N/A')
         
        score_val = model.get('score', 0.0)
        score_str = f"{score_val:.1f}" if isinstance(score_val, (int, float)) else str(score_val)
             
        raw_name = model['name']
        display_name = raw_name.split('/')[-1] if '/' in raw_name else raw_name
         
        if len(display_name) > 38:
            display_name = display_name[:35] + "..."
             
        vram_str = f"{vram_req:.1f}G" if isinstance(vram_req, (int, float)) else str(vram_req)
         
        headroom_gb = current_container_ceiling - float(vram_req)
        calculated_tokens = int((headroom_gb * 1024) / 1.2) * 1024
        api_ctx = int(ctx_val) if isinstance(ctx_val, (int, float)) else 32768
         
        max_hardware_ctx = min(api_ctx, calculated_tokens, 49152)
        if max_hardware_ctx < 2048:
            max_hardware_ctx = 2048

        model['hardware_max_ctx'] = max_hardware_ctx
         
        total_allocated_slice = vram_req + (max_hardware_ctx * 1.2 / 1024 / 1024)
        gpu_utilization_fraction = min(0.95, total_allocated_slice / total_gpu_vram)
        model['gpu_memory_utilization'] = max(0.15, round(gpu_utilization_fraction, 2))

        ctx_str = f"{max_hardware_ctx // 1024}k" if max_hardware_ctx >= 1024 else f"{max_hardware_ctx}"
         
        if speed_val != 'N/A':
            speed_str = f"{speed_val:.1f} t/s" if isinstance(speed_val, float) else f"{speed_val} t/s"
        else:
            speed_str = "N/A"

        idx_str = f"[{i + 1}]"
        print(f"  {idx_str:<6} {fit_level:<10} {display_name:<40} {param_val:<7} {quant_val:<11} {vram_str:<7} {ctx_str:<6} {speed_str:<10} {score_str:<5}")
         
    while True:
        try:
            choice = int(input(f"\nSelect choice [1-{len(filtered_options)}]: ")) - 1
            if 0 <= choice < len(filtered_options):
                selected = filtered_options[choice]
                if 'vram_required' not in selected:
                    selected['vram_required'] = selected.get('required_gb', 8.0)
                if 'id' not in selected:
                    selected['id'] = selected.get('name')
                return selected
        except ValueError:
            pass
        print("Invalid selection. Try again.")

def calculate_safe_context(model_id: str, gpu_utilization: float, base_total_vram_gb: float, requested_ctx: int) -> int:
    """Dynamically scales max-model-len to protect KV Cache memory constraints under tight slice limits."""
    allocated_vram_gb = base_total_vram_gb * gpu_utilization
    model_lower = model_id.lower()
    
    # Structural context snapshot weight presets (Compressed 4-bit baselines)
    if "26b" in model_lower:
        weight_size_gb = 16.5  
    elif "14b" in model_lower or "13b" in model_lower:
        weight_size_gb = 9.5
    elif "7b" in model_lower or "8b" in model_lower:
        weight_size_gb = 5.2
    elif "2b" in model_lower or "1.9b" in model_lower:
        weight_size_gb = 2.5
    else:
        # Generic safe projection weight line
        return min(requested_ctx, 8192)

    kv_headroom_gb = allocated_vram_gb - weight_size_gb
    
    # Instantly throttle down context bound to safe walls if weights chew through target slice
    if kv_headroom_gb <= 0.6:
        return 4096
        
    # FP8 memory per token step footprint factor constant 
    vram_bytes_per_token = 0.00004 
    calculated_max_len = int(kv_headroom_gb / vram_bytes_per_token)
    
    if calculated_max_len >= requested_ctx:
        return requested_ctx
    elif calculated_max_len >= 16384:
        return 16384
    elif calculated_max_len >= 8192:
        return 8192
    else:
        return 4096

def main():
    display_architectural_overview()

    print("Initializing hardware analysis loop...")
    total_vram = get_total_vram_gb()
    usable_vram = total_vram * 0.90
     
    print(f"\nHost Hardware Confirmed: ~{total_vram} GB Physical VRAM detected.")
    print(f"Assigned Cluster Headroom: ~{usable_vram:.1f} GB.")
     
    master_catalog = fetch_odysseus_master_catalog()
     
    catalog_text   = [m for m in master_catalog if str(m.get("use_case", "")).lower() == "general"]
    catalog_code   = [m for m in master_catalog if str(m.get("use_case", "")).lower() == "code"]
    
    # Combined category search ensuring both tag strings and name string patterns match up cleanly
    catalog_vision = [
        m for m in master_catalog 
        if str(m.get("use_case", "")).lower() == "vision" 
        or any(x in str(m.get("name", "")).lower() for x in ["vision", "-vl", "chat-vl", "llava", "minicpm"])
    ]
     
    if not catalog_code:
         catalog_code = list(master_catalog)
     
    running_pool_vram = usable_vram

    # --------------------------------------------------------------------------
    # ORIGINAL CASCADING HEADROOM ALLOCATION ORDER (Text -> Code -> Vision)
    # --------------------------------------------------------------------------
    FLOOR_CODE_RESERVE = 7.5
    FLOOR_VISION_RESERVE = 8.5

    # Text Target Allocation & Maximum Ceiling
    slice_text_est = usable_vram - (FLOOR_CODE_RESERVE + FLOOR_VISION_RESERVE)

    selected_text = display_interactive_menu("Text Generation", catalog_text, slice_text_est, running_pool_vram, total_gpu_vram=total_vram)
    running_pool_vram -= selected_text["vram_required"]

    # Coding Target Allocation & Maximum Ceiling
    slice_code_est = running_pool_vram - FLOOR_VISION_RESERVE

    selected_code = display_interactive_menu("Deep Coding", catalog_code, slice_code_est, running_pool_vram, total_gpu_vram=total_vram)
    running_pool_vram -= selected_code["vram_required"]

    # Vision captures all final residual pools
    slice_vision_est = running_pool_vram

    selected_vision = display_interactive_menu("Vision Processing", catalog_vision, slice_vision_est, running_pool_vram, total_gpu_vram=total_vram)
    # --------------------------------------------------------------------------
     
    vram_req_text   = selected_text["vram_required"]
    vram_req_code   = selected_code["vram_required"]
    vram_req_vision = selected_vision["vram_required"]
     
    util_text   = selected_text['gpu_memory_utilization']
    util_code   = selected_code['gpu_memory_utilization']
    util_vision = selected_vision['gpu_memory_utilization']
     
    print("\n" + "=" * 122)
    print("FINAL CLUSTER COMPILED")
    print("=" * 122)
    print(f"- Text Generation Model: {selected_text['name']} (Req: {vram_req_text}GB) -> Alloc: {util_text}")
    print(f"- Deep Coding Model: {selected_code['name']} (Req: {vram_req_code}GB) -> Alloc: {util_code}")
    print(f"- Vision Processing Model: {selected_vision['name']} (Req: {vram_req_vision}GB) -> Alloc: {util_vision}")
    print(f"- Total Assigned GPU Utilization: {round((util_text + util_code + util_vision) * 100)}% (Remaining left for OS)")
    print("-" * 122)
     
    confirm = input("Deploy this container cluster now? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Deployment aborted by user.")
        sys.exit(0)
         
    print("\nCommencing container deployment...")
    subprocess.run("docker rm -f odysseus-text-engine odysseus-code-engine odysseus-vision-engine", shell=True)
     
    home_dir = os.path.expanduser("~")
    hf_cache_path = os.path.join(home_dir, ".cache", "huggingface", "hub")

    # Capture interactive layer target lengths before verification step
    ctx_text_requested = selected_text.get('hardware_max_ctx', 16384)
    ctx_code_requested = selected_code.get('hardware_max_ctx', 16384)
    ctx_vis_requested  = min(selected_vision.get('hardware_max_ctx', 4096), 4096)

    # DYNAMIC SIZING STEP EVALUATION
    ctx_text_launch = calculate_safe_context(selected_text["id"], util_text, total_vram, ctx_text_requested)
    ctx_code_launch = calculate_safe_context(selected_code["id"], util_code, total_vram, ctx_code_requested)
    ctx_vis_launch  = calculate_safe_context(selected_vision["id"], util_vision, total_vram, ctx_vis_requested)

    # VLLM ARGV & MULTI-MODAL PATCH LAYER
    is_actual_vision = any(x in selected_vision["id"].lower() for x in ["vision", "-vl", "chat-vl", "minicpm", "llava", "ovis"])

    # Integrated --enforce-eager, --kv-cache-dtype, and --disable-log-stats flags to allow clean multi-instance execution
    base_args = [
        "docker", "run", "-d", "--gpus", "all", 
        "-v", f"{hf_cache_path}:/root/.cache/huggingface"
    ]
    
    runtime_tuning_flags = [
        "--enforce-eager", 
        "--kv-cache-dtype", "fp8", 
        "--disable-log-stats"
    ]

    cmd_text_list = base_args + [
        "-p", "8001:8000", "--name", "odysseus-text-engine", "vllm/vllm-openai:latest",
        selected_text["id"], "--gpu-memory-utilization", str(util_text), "--max-model-len", str(ctx_text_launch)
    ] + runtime_tuning_flags

    cmd_code_list = base_args + [
        "-p", "8002:8000", "--name", "odysseus-code-engine", "vllm/vllm-openai:latest",
        selected_code["id"], "--gpu-memory-utilization", str(util_code), "--max-model-len", str(ctx_code_launch)
    ] + runtime_tuning_flags

    cmd_vision_list = base_args + [
        "-p", "8003:8000", "--name", "odysseus-vision-engine", "vllm/vllm-openai:latest",
        selected_vision["id"], "--gpu-memory-utilization", str(util_vision), "--max-model-len", str(ctx_vis_launch)
    ] + runtime_tuning_flags
    
    if is_actual_vision:
        cmd_vision_list += ["--limit-mm-per-prompt.image", "2"]
     
    deployment_sequence = [
        ("Text Generation", cmd_text_list),
        ("Deep Coding", cmd_code_list),
        ("Vision Processing", cmd_vision_list)
    ]

    for index, (name, cmd_list) in enumerate(deployment_sequence):
        print(f"Bootstrapping {name} Cluster using model target ID: {selected_text['id'] if name == 'Text Generation' else (selected_code['id'] if name == 'Deep Coding' else selected_vision['id'])}...")
        subprocess.run(cmd_list, check=True)

         
    print("\nContainer cluster deployment complete! Run 'docker ps' to confirm state.")

if __name__ == "__main__":
    main()
    main()

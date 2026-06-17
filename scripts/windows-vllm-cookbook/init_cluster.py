import subprocess
import os
import json
import sys

# Path to the Odysseus local hardware scan cache
COOKBOOK_CACHE_PATH = os.path.expanduser("~/.config/odysseus/cache/cookbook_scan.json")

def get_total_vram_gb():
    """Queries nvidia-smi to fetch the exact VRAM capacity of the primary GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return round(int(result.stdout.strip().split("\n")[0]) / 1024)
    except Exception as e:
        print(f"❌ Hardware scan failed: {e}. Defaulting to flagship baseline (32GB).")
        return 32

def load_native_cookbook_catalog():
    """Parses models straight from the active Odysseus app scan cache."""
    if not os.path.exists(COOKBOOK_CACHE_PATH):
        print("⚠️ Local Cookbook cache file not found at the default app data path.")
        print("Please open the Odysseus UI, navigate to the 'Download' tab, and run a fresh hardware scan first.")
        sys.exit(1)
        
    try:
        with open(COOKBOOK_CACHE_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
        catalog = {"general": [], "code": [], "vision": []}
        
        for model in raw_data.get("models", []):
            model_name = model.get("name", "").lower()
            model_entry = {
                "name": model.get("name"),
                "vram_required": float(model.get("vram_usage_gb", 0)),
                "id": model.get("huggingface_id"),
                "fit": model.get("fit_status", "PERFECT")
            }
            
            if "vision" in model_name or "-vl-" in model_name:
                catalog["vision"].append(model_entry)
            elif "coder" in model_name or "code" in model_name:
                catalog["code"].append(model_entry)
            else:
                catalog["general"].append(model_entry)
                
        return catalog
    except Exception as e:
        print(f"❌ Error parsing Odysseus database cache: {e}")
        sys.exit(1)

def display_interactive_menu(category, options, available_slice):
    """Generates an explicit terminal menu pulling directly from the app cache data."""
    print(f"\n📥 SELECT MODEL FOR CATEGORY: [{category.upper()}] (Target Allocation: ~{available_slice:.1f} GB)")
    print("-" * 75)
    
    if not options:
        print("  [!] No matching scanned models found in cache for this type.")
        print("      Please head to the UI and add/scan entries for this domain.")
        sys.exit(1)
        
    display_pool = options[:5]
    for i, model in enumerate(display_pool):
        fit_tag = "[Fit: PERFECT]" if available_slice >= model['vram_required'] else "[Fit: TIGHT (Context Cap Required)]"
        print(f"  [{i + 1}] {model['name']} (Est: ~{model['vram_required']}GB) -> {fit_tag}")
        
    while True:
        try:
            choice = int(input(f"Select choice [1-{len(display_pool)}]: ")) - 1
            if 0 <= choice < len(display_pool):
                return display_pool[choice]
        except ValueError:
            pass
        print("Invalid selection. Try again.")
      
def main():
    total_vram = get_total_vram_gb()
    usable_vram = total_vram * 0.90  # 10% desktop overhead protection
    
    catalog = load_native_cookbook_catalog()
    
    print("=" * 75)
    print("📖 ODYSSEUS HARDWARE INTEGRATION: DYNAMIC COOKBOOK COMPILER")
    print("=" * 75)
    print(f"Scanned Host System Target: NVIDIA GPU (~{total_vram} GB Total Physical VRAM)")
    print(f"Active App Cache Loaded:   Successfully mapped models from Odysseus schema.")
    print(f"Safe Working Headroom Buffer:  ~{usable_vram:.1f} GB Allocated for Cluster")
    
    # Pass 1: Give the interactive menus a rough target baseline to show [Fit] tags
    slice_general_est = usable_vram * 0.50
    slice_code_est    = usable_vram * 0.25
    slice_vision_est  = usable_vram * 0.25
    
    selected_general = display_interactive_menu("general", catalog["general"], slice_general_est)
    selected_code = display_interactive_menu("code", catalog["code"], slice_code_est)
    selected_vision = display_interactive_menu("vision", catalog["vision"], slice_vision_est)
    
    # Pass 2: Calculate precise dynamic VRAM allocations based on the CHOSEN models
    vram_req_general = selected_general["vram_required"]
    vram_req_code    = selected_code["vram_required"]
    vram_req_vision  = selected_vision["vram_required"]
    
    total_requested_vram = vram_req_general + vram_req_code + vram_req_vision
    
    print("\n⚖️ Optimizing VRAM allocations based on model selections...")
    
    # If the chosen models fit comfortably within our budget, give them exactly what they need plus a small cushion
    if total_requested_vram <= usable_vram:
        # Allocate exact VRAM weights scaled cleanly into fractions of the total GPU capacity
        util_general = round((vram_req_general / total_vram) + 0.02, 2)
        util_code    = round((vram_req_code / total_vram) + 0.02, 2)
        util_vision  = round((vram_req_vision / total_vram) + 0.02, 2)
    else:
        # Proportional squeezing: If the user picked a heavy combination, shrink their allocations proportionally to fit the hardware limits
        print("⚠️ Warning: Combined model requirements exceed target headroom. Squeezing allocations proportionally...")
        scale_factor = usable_vram / total_requested_vram
        util_general = round(((vram_req_general * scale_factor) / total_vram), 2)
        util_code    = round(((vram_req_code * scale_factor) / total_vram), 2)
        util_vision  = round(((vram_req_vision * scale_factor) / total_vram), 2)

    # Ensure no calculation floor drops below a stable running threshold
    util_general = max(util_general, 0.15)
    util_code    = max(util_code, 0.15)
    util_vision  = max(util_vision, 0.15)
    
    print("\n" + "=" * 75)
    print("🎯 FINAL MODEL-AWARE REASONING ARCHITECTURE COMPILED")
    print("=" * 75)
    print(f"• General Text Engine: {selected_general['name']} (Req: {vram_req_general}GB) -> Alloc: {util_general}")
    print(f"• Coding Specialist:  {selected_code['name']} (Req: {vram_req_code}GB) -> Alloc: {util_code}")
    print(f"• Multimodal Vision:  {selected_vision['name']} (Req: {vram_req_vision}GB) -> Alloc: {util_vision}")
    print(f"• Total Assigned GPU Utilization: {round((util_general + util_code + util_vision) * 100)}% (Remaining left for Windows OS)")
    print("-" * 75)
    
    confirm = input("Deploy this customized hardware container configuration now? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Deployment aborted by user.")
        sys.exit(0)
        
    print("\n🚀 Commencing container deployment loop...")
    subprocess.run("docker rm -f odysseus-text-engine odysseus-code-engine odysseus-vision-engine", shell=True)
    
# Dynamically resolve the host machine's home directory across Windows/Linux/macOS
    home_dir = os.path.expanduser("~")
    hf_cache_path = os.path.join(home_dir, ".cache", "huggingface", "hub")

    cmd_general = f'docker run -d --gpus all -v "{hf_cache_path}:/root/.cache/huggingface" -p 8001:8000 --name odysseus-text-engine vllm/vllm-openai:latest --model {selected_general["id"]} --gpu-memory-utilization {util_general}'
    cmd_code = f'docker run -d --gpus all -v "{hf_cache_path}:/root/.cache/huggingface" -p 8002:8000 --name odysseus-code-engine vllm/vllm-openai:latest --model {selected_code["id"]} --gpu-memory-utilization {util_code}'
    cmd_vision = f'docker run -d --gpus all -v "{hf_cache_path}:/root/.cache/huggingface" -p 8003:8000 --name odysseus-vision-engine vllm/vllm-openai:latest --model {selected_vision["id"]} --gpu-memory-utilization {util_vision} --max-model-len 4096 --limit-mm-per-prompt image=2'
    
    for name, cmd in [("General Text", cmd_general), ("Coding Specialist", cmd_code), ("Multimodal Vision", cmd_vision)]:
        model_id = selected_general['id'] if name == 'General Text' else (selected_code['id'] if name == 'Coding Specialist' else selected_vision['id'])
        print(f"⚡ Bootstrapping {name} Cluster using model target ID: {model_id}...")
        subprocess.run(["powershell", "-Command", cmd], check=True)
        
    print("\n🟢 Automated dynamic fleet deployment complete! Run 'docker ps' to confirm execution state.")

if __name__ == "__main__":
    main()

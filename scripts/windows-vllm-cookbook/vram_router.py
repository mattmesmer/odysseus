import os
import sys
import json
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Odysseus VRAM Smart Router Gateway")

# Enable CORS to allow the frontend UI to communicate cleanly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Engine mapping aligned with the ports allocated in init_cluster.py
ENGINE_ROUTING_TABLE = {
    "text": "http://host.docker.internal:8001",
    "code": "http://host.docker.internal:8002",
    "vision": "http://host.docker.internal:8003"
}

# ==============================================================================
# REQD CORE HANDLERS (Resolves Odysseus App Connection & 404 Errors)
# ==============================================================================

@app.get("/v1")
async def v1_root():
    """Base API check path probed by frontend clients."""
    return {
        "status": "gateway_active",
        "proxy_target_count": len(ENGINE_ROUTING_TABLE),
        "message": "Odysseus Smart VRAM Router Online"
    }

@app.get("/v1/models")
async def get_combined_models():
    """Aggregates all running model instances from our active backend clusters."""
    combined_models = []
    
    for slice_name, engine_url in ENGINE_ROUTING_TABLE.items():
        try:
            # Poll each container cluster's native vLLM API endpoint
            response = requests.get(f"{engine_url}/v1/models", timeout=1.5)
            if response.status_code == 200:
                data = response.json()
                models_list = data.get("data", [])
                
                # Tag engine metadata so the frontend UI understands layout ownership
                for m in models_list:
                    m["owned_by"] = slice_name
                    combined_models.append(m)
        except Exception:
            # Fallback gracefully if a container is offline or deploying weights
            continue
            
    return {"object": "list", "data": combined_models}

# ==============================================================================
# CONTEXTUAL ROUTING & PROXY FALLTHROUGH ENGINE
# ==============================================================================

def determine_target_engine(payload: dict) -> str:
    """Evaluates payload fingerprints to select the correct vLLM engine port."""
    model_field = str(payload.get("model", "")).lower()
    messages = payload.get("messages", [])
    
    # 1. Multi-Modal Vision Flag Identification
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in ["image", "image_url"]:
                    return ENGINE_ROUTING_TABLE["vision"]
                    
    # 2. Structural Name String Search Checks
    if any(x in model_field for x in ["vision", "-vl", "chat-vl", "llava", "minicpm", "ovis"]):
        return ENGINE_ROUTING_TABLE["vision"]
    elif any(x in model_field for x in ["code", "coder", "instruct-deep", "python", "javascript"]):
        return ENGINE_ROUTING_TABLE["code"]
        
    # Default fallback routing boundary
    return ENGINE_ROUTING_TABLE["text"]

@app.post("/v1/chat/completions")
async def route_chat_completions(request: Request):
    """Intercepts and contextually streams chat payloads to matching target layers."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Malformed JSON payload payload received."})
        
    target_host = determine_target_engine(body)
    target_url = f"{target_host}/v1/chat/completions"
    
    # Forward original authentication and system headers
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
    
    try:
        if body.get("stream", False):
            def stream_generator():
                with requests.post(target_url, json=body, headers=headers, stream=True) as r:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            response = requests.post(target_url, json=body, headers=headers)
            return JSONResponse(status_code=response.status_code, content=response.json())
            
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Target backend cluster engine engine unreachable: {e}")

if __name__ == "__main__":
    import uvicorn
    # Launches loop listening on all interfaces at port 5000
    uvicorn.run("vram_router:app" if "__file__" in locals() else app, host="0.0.0.0", port=5000, reload=True)
    uvicorn.run(app, host="0.0.0.0", port=5000)

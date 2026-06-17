import httpx
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI(title="Odysseus Smart VRAM Router")

ENGINES = {
    "general": "http://localhost:8001/v1/chat/completions",
    "code": "http://localhost:8002/v1/chat/completions",
    "vision": "http://localhost:8003/v1/chat/completions",
}

CODE_INDICATORS = {
    "languages": {"python", "javascript", "typescript", "html", "css", "rust", "golang", "cpp", "csharp", "bash", "powershell"},
    "frameworks": {"fastapi", "nextjs", "react", "vue", "express", "django", "flask", "tailwindcss"},
    "database_systems": {"postgres", "postgresql", "sqlite", "mysql", "mongodb", "redis", "prisma", "sqlalchemy"},
    "infrastructure_dev": {"docker", "yaml", "yml", "docker-compose", "nginx", "git", "github", "ci/cd"},
    "structural_nouns": {"component", "endpoint", "repo", "repository", "schema", "migration", "payload", "json structure", "syntax error"}
}

ALL_CODE_KEYWORDS = set().union(*CODE_INDICATORS.values())

def determine_target_engine(payload: dict) -> str:
    """Analyzes incoming prompt payloads to route intent dynamically."""
    messages = payload.get("messages", [])
    if not messages:
        return "general"

    latest_content = messages[-1].get("content", "")
    
    if isinstance(latest_content, list):
        for item in latest_content:
            if isinstance(item, dict) and item.get("type") in ["image_url", "image"]:
                print("[ROUTER] 👁️ Image payload detected. Routing to Vision Model.")
                return "vision"
        
    prompt_text = str(latest_content).strip().lower()

    if prompt_text.startswith("/code"):
        print("[ROUTER] ⚡ Manual override forced: Routing to Coding Specialist.")
        return "code"
    if prompt_text.startswith("/chat") or prompt_text.startswith("/general"):
        print("[ROUTER] ⚡ Manual override forced: Routing to General MoE.")
        return "general"

    for word in ALL_CODE_KEYWORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', prompt_text):
            print(f"[ROUTER] 💻 Matched code indicator [{word}]. Routing to Coding Specialist.")
            return "code"

    print("[ROUTER] 💬 General conversational text detected. Routing to General MoE.")
    return "general"

async def forward_to_engine(engine_key: str, body: dict, client_headers: dict):
    """Handles the async streaming proxy to down-stream vLLM containers."""
    target_url = ENGINES[engine_key]
    client = httpx.AsyncClient(timeout=120.0)
    headers = {k: v for k, v in client_headers.items() if k.lower() not in ["host", "content-length"]}
    
    async def stream_generator():
        try:
            async with client.stream("POST", target_url, json=body, headers=headers) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk
        finally:
            await client.aclose()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@app.post("/v1/chat/completions")
async def route_chat_completion(request: Request):
    body = await request.json()
    target_key = determine_target_engine(body)
    
    try:
        return await forward_to_engine(target_key, body, request.headers)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        print(f"[⚠️ WARNING] Targeted engine [{target_key}] is offline or timed out! Cascading to General fallback.")
        if target_key != "general":
            try:
                return await forward_to_engine("general", body, request.headers)
            except Exception:
                pass
        raise HTTPException(
            status_code=503, 
            detail="Inference backend mismatch. The requested local model pipeline is currently unreachable."
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

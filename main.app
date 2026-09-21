import os
import uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command

from core.graph import engine, ensure_checkpointer_connection

app = FastAPI(
    title="Multi-Agent AI Workflow Engine",
    description="Production-grade Cyclical Agent Framework with Postgres Checkpoints and HITL",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_HTML = BASE_DIR / "static" / "index.html"

class RunRequest(BaseModel):
    goal: str
    thread_id: Optional[str] = None

class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if not STATIC_HTML.exists():
        raise HTTPException(status_code=500, detail="Dashboard UI file not found.")
    return STATIC_HTML.read_text(encoding="utf-8")

@app.get("/health")
def health_check():
    return {
        "status": "online",
        "framework": "LangGraph v0.2+",
        "checkpointer": "PostgreSQL (Neon) / MemoryFallback"
    }

@app.post("/api/run")
async def run_workflow(req: RunRequest):
    ensure_checkpointer_connection()
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_input = {
        "user_goal": req.goal,
        "iteration": 0,
        "max_iterations": 3,
        "execution_logs": [f"[Init] Dispatched job for thread: {thread_id}"]
    }

    try:
        engine.invoke(initial_input, config=config)
        state_snapshot = engine.get_state(config)
        is_interrupted = len(state_snapshot.tasks) > 0 and len(state_snapshot.tasks[0].interrupts) > 0

        interrupt_details = None
        if is_interrupted:
            interrupt_details = state_snapshot.tasks[0].interrupts[0].value

        return {
            "thread_id": thread_id,
            "is_interrupted": is_interrupted,
            "interrupt_details": interrupt_details,
            "execution_logs": state_snapshot.values.get("execution_logs", []),
            "state": state_snapshot.values
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/resume")
async def resume_workflow(req: ResumeRequest):
    ensure_checkpointer_connection()
    config = {"configurable": {"thread_id": req.thread_id}}

    try:
        engine.invoke(Command(resume={"approved": req.approved}), config=config)
        state_snapshot = engine.get_state(config)

        is_interrupted = len(state_snapshot.tasks) > 0 and len(state_snapshot.tasks[0].interrupts) > 0
        interrupt_details = state_snapshot.tasks[0].interrupts[0].value if is_interrupted else None

        return {
            "thread_id": req.thread_id,
            "is_interrupted": is_interrupted,
            "interrupt_details": interrupt_details,
            "execution_logs": state_snapshot.values.get("execution_logs", []),
            "state": state_snapshot.values
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/state/{thread_id}")
async def get_state(thread_id: str):
    ensure_checkpointer_connection()
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot = engine.get_state(config)
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="Session state not found.")
    return {
        "values": state_snapshot.values,
        "next": state_snapshot.next,
        "tasks": [t.name for t in state_snapshot.tasks]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
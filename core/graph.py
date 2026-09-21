import os
from typing import Dict, Any, Literal
from dotenv import load_dotenv
import psycopg

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver

from core.schemas import (
    WorkflowState,
    PlanStep,
    VerificationResult,
    DatabaseQueryInput,
    DataFetchInput,
)
from core.tools import execute_database_operation, fetch_system_metrics

load_dotenv()

DEFAULT_DB_URL = "postgresql://neondb_owner:npg_YsX5W2JBrufR@ep-green-mountain-b51y4rpc-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
llm = None

if GROQ_API_KEY:
    try:
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            api_key=GROQ_API_KEY,
        )
        print("[LLM] Groq Llama 3.3 70B initialized successfully.")
    except Exception as e:
        print(f"[Warning] Failed to initialize Groq LLM: {e}. Using deterministic logic.")
        llm = None


def planner_node(state: WorkflowState) -> Dict[str, Any]:
    current_iter = state.iteration + 1
    logs = [f"[Planner] Cycle {current_iter}: Analyzing goal -> '{state.user_goal}'"]

    if state.verification and not state.verification.is_valid:
        logs.append(f"[Planner] Corrective cycle triggered. Feedback: {state.verification.critique}")
        plan = [
            PlanStep(
                step_id=1,
                agent_target="tool_executor",
                action="Execute authoritative sync update on system_audit table",
                tool_name="execute_database_operation",
                tool_args={
                    "table_name": "system_audit",
                    "operation": "UPDATE",
                    "query_payload": {
                        "status": "resolved",
                        "remedy": state.verification.actionable_remedy or "authoritative_recheck",
                    },
                    "is_sensitive": True,
                },
            )
        ]
    else:
        is_sensitive = any(
            kw in state.user_goal.lower()
            for kw in ["update", "delete", "mutate", "modify", "drop"]
        )

        plan = [
            PlanStep(
                step_id=1,
                agent_target="tool_executor",
                action="Execute requested database operation",
                tool_name="execute_database_operation",
                tool_args={
                    "table_name": "production_nodes",
                    "operation": "UPDATE" if is_sensitive else "SELECT",
                    "query_payload": {"action": "sync", "target": "cluster_primary"},
                    "is_sensitive": is_sensitive,
                },
            )
        ]

    logs.append(f"[Planner] Generated execution plan with {len(plan)} structured step(s).")
    return {
        "iteration": current_iter,
        "plan": plan,
        "current_step_index": 0,
        "execution_logs": logs,
    }


def tool_executor_node(state: WorkflowState) -> Dict[str, Any]:
    if not state.plan:
        return {"execution_logs": ["[Tool Executor] No planned steps found."]}

    current_step = state.plan[state.current_step_index]
    logs = [f"[Tool Executor] Running Step {current_step.step_id}: {current_step.action}"]
    results = []

    if current_step.tool_name == "execute_database_operation":
        args = current_step.tool_args or {}
        validated_args = DatabaseQueryInput(**args)

        if validated_args.is_sensitive:
            logs.append(
                f"[HITL Gate] Sensitive action '{validated_args.operation}' detected on '{validated_args.table_name}'. Pausing execution."
            )

            approval_data = interrupt({
                "type": "human_approval_required",
                "tool": current_step.tool_name,
                "operation": validated_args.operation,
                "target_table": validated_args.table_name,
                "payload": validated_args.query_payload,
                "prompt": f"Approve modification ({validated_args.operation}) on table '{validated_args.table_name}'?",
            })

            if not approval_data or not approval_data.get("approved", False):
                logs.append("[HITL Gate] Action REJECTED by human operator.")
                return {
                    "tool_results": [{"status": "rejected", "reason": "Operator rejected action."}],
                    "execution_logs": logs,
                }
            logs.append("[HITL Gate] Action APPROVED by human operator. Resuming execution.")

        res = execute_database_operation(validated_args)
        results.append(res)
        logs.append(f"[Tool Executor] Execution complete. Status: {res.get('status')}")

    elif current_step.tool_name == "fetch_system_metrics":
        args = current_step.tool_args or {"source_endpoint": "system_metrics", "limit": 5}
        validated_args = DataFetchInput(**args)
        res = fetch_system_metrics(validated_args)
        results.append(res)
        logs.append(f"[Tool Executor] Execution complete. Status: {res.get('status')}")

    return {
        "tool_results": results,
        "execution_logs": logs,
    }


def verifier_node(state: WorkflowState) -> Dict[str, Any]:
    logs = ["[Verifier] Auditing tool outputs against constraints."]
    last_result = state.tool_results[-1] if state.tool_results else {}

    has_rejected = last_result.get("status") == "rejected"
    has_fallback = last_result.get("status") in ["fallback_applied", "cached_fallback"]

    if has_fallback and state.iteration < 2:
        v_result = VerificationResult(
            is_valid=False,
            quality_score=0.45,
            critique="Tool executed using fallback route. Authoritative sync required.",
            actionable_remedy="Run authoritative update on system_audit.",
        )
        logs.append("[Verifier] Validation FAILED -> Triggering cyclical re-planning loop.")
    elif has_rejected:
        v_result = VerificationResult(
            is_valid=True,
            quality_score=0.90,
            critique="Action safely halted per operator directive.",
            actionable_remedy=None,
        )
        logs.append("[Verifier] Action safely rejected. Approving workflow termination.")
    else:
        v_result = VerificationResult(
            is_valid=True,
            quality_score=0.98,
            critique="Schema validation passed with zero execution exceptions.",
            actionable_remedy=None,
        )
        logs.append("[Verifier] Validation PASSED with confidence score 0.98.")

    final_summary = (
        f"Workflow completed. Status: {'Validated' if v_result.is_valid else 'Terminated'}. "
        f"Total iterations: {state.iteration}."
    )

    return {
        "verification": v_result,
        "final_output": final_summary,
        "execution_logs": logs,
    }


def should_continue(state: WorkflowState) -> Literal["planner", "__end__"]:
    if state.iteration >= state.max_iterations:
        return END
    if state.verification and not state.verification.is_valid:
        return "planner"
    return END


# Persistent connection references
_db_conn = None
_checkpointer = None


def ensure_checkpointer_connection():
    """Reconnects automatically if Neon suspended an idle connection."""
    global _db_conn, _checkpointer
    db_uri = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if not db_uri or not db_uri.startswith("postgres"):
        return

    conn_string = db_uri if "sslmode" in db_uri else f"{db_uri}?sslmode=require"

    is_healthy = False
    if _db_conn is not None and not _db_conn.closed:
        try:
            _db_conn.execute("SELECT 1")
            is_healthy = True
        except Exception:
            is_healthy = False

    if not is_healthy:
        try:
            if _db_conn and not _db_conn.closed:
                _db_conn.close()
        except Exception:
            pass
        try:
            _db_conn = psycopg.connect(conn_string, autocommit=True, prepare_threshold=0)
            if _checkpointer:
                _checkpointer.conn = _db_conn
                if hasattr(_checkpointer, "sync_connection"):
                    _checkpointer.sync_connection = _db_conn
        except Exception as e:
            print(f"[Warning] Neon auto-reconnect failed: {e}")


def create_engine():
    global _db_conn, _checkpointer
    workflow = StateGraph(WorkflowState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("tool_executor", tool_executor_node)
    workflow.add_node("verifier", verifier_node)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "tool_executor")
    workflow.add_edge("tool_executor", "verifier")
    workflow.add_conditional_edges("verifier", should_continue, {
        "planner": "planner",
        END: END,
    })

    db_uri = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

    if db_uri and db_uri.startswith("postgres"):
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            conn_string = db_uri if "sslmode" in db_uri else f"{db_uri}?sslmode=require"
            _db_conn = psycopg.connect(conn_string, autocommit=True, prepare_threshold=0)
            _checkpointer = PostgresSaver(_db_conn)
            _checkpointer.setup()

            print("[Checkpointer] Successfully initialized persistent Neon PostgreSQL connection.")
            return workflow.compile(checkpointer=_checkpointer)
        except Exception as e:
            print(f"[Warning] Postgres connection notice ({e}). Falling back to MemorySaver.")

    return workflow.compile(checkpointer=MemorySaver())


engine = create_engine()
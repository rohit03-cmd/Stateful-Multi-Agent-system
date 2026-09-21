import functools
import logging
from typing import Any, Callable, Dict
from core.schemas import DatabaseQueryInput, DataFetchInput

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WorkflowTools")

def heuristic_fallback(fallback_fn: Callable[[Exception, tuple, dict], Dict[str, Any]]):
    """Intercepts runtime tool errors and routes to a safe deterministic fallback."""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                logger.warning(f"[Fallback Route Triggered] '{func.__name__}' error: {exc}")
                return fallback_fn(exc, args, kwargs)
        return wrapper
    return decorator

def db_query_fallback(exc: Exception, args: tuple, kwargs: dict) -> Dict[str, Any]:
    return {
        "status": "fallback_applied",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "data": [{"mock_id": 999, "status": "simulated_safe_state", "note": "Recovered via heuristic fallback"}]
    }

def fetch_fallback(exc: Exception, args: tuple, kwargs: dict) -> Dict[str, Any]:
    return {
        "status": "cached_fallback",
        "error_message": str(exc),
        "records": [{"metric": "cpu_load", "value": "42%", "timestamp": "cached"}]
    }

@heuristic_fallback(db_query_fallback)
def execute_database_operation(input_data: DatabaseQueryInput) -> Dict[str, Any]:
    if input_data.operation in ["UPDATE", "DELETE", "INSERT"]:
        return {
            "status": "success",
            "operation": input_data.operation,
            "table": input_data.table_name,
            "rows_affected": 1,
            "payload": input_data.query_payload
        }
    return {
        "status": "success",
        "operation": "SELECT",
        "table": input_data.table_name,
        "records": [
            {"id": 101, "name": "Cluster-A", "health": "optimal"},
            {"id": 102, "name": "Cluster-B", "health": "degraded"}
        ]
    }

@heuristic_fallback(fetch_fallback)
def fetch_system_metrics(input_data: DataFetchInput) -> Dict[str, Any]:
    return {
        "status": "success",
        "endpoint": input_data.source_endpoint,
        "count": input_data.limit,
        "data": [{"metric_id": i, "status": "active"} for i in range(input_data.limit)]
    }
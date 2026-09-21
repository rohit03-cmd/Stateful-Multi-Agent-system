import operator
from typing import Annotated, Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class DatabaseQueryInput(BaseModel):
    table_name: str = Field(..., description="Target database table name", pattern=r"^[a-zA-Z0-9_]+$")
    operation: Literal["SELECT", "INSERT", "UPDATE", "DELETE"] = Field(..., description="SQL operation")
    query_payload: Dict[str, Any] = Field(..., description="Query parameters or payload values")
    is_sensitive: bool = Field(default=False, description="True if operation mutates database records")

class DataFetchInput(BaseModel):
    source_endpoint: str = Field(..., description="API endpoint to query", pattern=r"^(analytics|users|system_metrics)$")
    limit: int = Field(default=10, ge=1, le=100, description="Records limit")

class PlanStep(BaseModel):
    step_id: int
    agent_target: Literal["tool_executor", "verifier"]
    action: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None

class VerificationResult(BaseModel):
    is_valid: bool = Field(..., description="Whether output meets user criteria")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    critique: str = Field(..., description="Audit evaluation feedback")
    actionable_remedy: Optional[str] = Field(None, description="Corrective instruction if failed")

class WorkflowState(BaseModel):
    user_goal: str
    iteration: int = 0
    max_iterations: int = 4
    plan: List[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0
    tool_results: Annotated[List[Dict[str, Any]], operator.add] = Field(default_factory=list)
    verification: Optional[VerificationResult] = None
    final_output: Optional[str] = None
    execution_logs: Annotated[List[str], operator.add] = Field(default_factory=list)
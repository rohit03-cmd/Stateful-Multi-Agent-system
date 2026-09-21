# Stateful Multi-Agent AI Workflow Engine

A production-grade, cyclical multi-agent orchestration engine built with **LangGraph**, **FastAPI**, **PostgreSQL (Neon)**, and **Groq (Llama 3.3 70B)**.

The system decomposes complex operational goals into discrete planning, execution, and verification phases. It features persistent database checkpointing, human-in-the-loop review gates for sensitive mutations, and heuristic fallback decorators designed to minimize unhandled runtime crashes across multi-step runs.

---

## The Problem It Solves

Most Generative AI agent prototypes rely on linear chains (DAGs) or single-prompt agent loops. In production, these implementations face distinct architectural bottlenecks:

1. **Context Loss on Interruption:** In-memory agent runs are volatile. If a container restarts, a network timeout occurs, or a multi-minute external task stalls, all intermediate reasoning is lost.
2. **Uncontrolled Destructive Mutations:** Granting autonomous agents direct write or update access to production databases introduces severe hallucination risks. Without deterministic gates, an agent can alter or drop critical records unchecked.
3. **Cascading Tool Failures:** Standard pipelines fail catastrophically if an external API or database returns an unexpected payload or transient error. A single schema mismatch crashes the entire thread.
4. **Lack of Automated Self-Correction:** When an agent takes a wrong turn or produces subpar data, linear architectures have no built-in auditing loop to inspect outputs and trigger targeted re-planning before surfacing results.

### The Solution

This workflow engine solves these challenges through a stateful, cyclical architecture:
* **Decoupled Roles:** Distinct nodes handle planning, tool dispatching, and output verification independently.
* **Resilient State Persistence:** State snapshots are serialized into PostgreSQL at every transition boundary, allowing threads to resume from exact checkpoints.
* **Deterministic Human Gateways:** Sensitive operations halt execution via LangGraph interrupts, persisting the state until an operator approves or rejects the action.
* **Defensive Tool Design:** All tool inputs are strictly validated with Pydantic, and executions are wrapped with custom heuristic fallbacks that provide safe recovery routes instead of throwing unhandled 500 exceptions.

---

## Architecture & Workflow Flow
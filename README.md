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


    +-----------------------+
                         |  User / Client UI     |
                         +-----------+-----------+
                                     |
                                     v
                         +-----------------------+
                         |   FastAPI Gateway     |
                         +-----------+-----------+
                                     |
           +-------------------------v-------------------------+
           |              LangGraph Cyclical State             |
           |                                                   |
           |     +---------------------------------------+     |
           |     |              Planner Node             |     |
           |     |  - Evaluates goal                     |     |
           |     |  - Synthesizes structured steps       |<+   |
           |     +-------------------+-------------------+ |   |
           |                         |                     |   |
           |                         v                     |   |
           |     +---------------------------------------+ |   |
           |     |          Tool Executor Node           | |   |
           |     |  - Pydantic schema validation         | |   |
           |     |  - Heuristic fallback wrapping        | |   |
           |     +-------------------+-------------------+ |   |
           |                         |                     |   |
           |              [Sensitive Operation?]           |   |
           |                 /               \             |   |
           |             YES/                 \NO          |   |
           |               v                   |           |   |
           |      +------------------+         |           |   |
           |      | HITL Review Gate |         |           |   |
           |      |  (interrupt())   |         |   (Replan |   |
           |      +--------+---------+         |    Loop)  |   |
           |               |                   |           |   |
           |       [Approved by Human]         |           |   |
           |               |                   |           |   |
           |               +--------->+<-------+           |   |
           |                          |                    |   |
           |                          v                    |   |
           |     +---------------------------------------+ |   |
           |     |             Verifier Node             | |   |
           |     |  - Scores output quality (0.0 - 1.0)  | |   |
           |     |  - Quality audit gate                 |-+   |
           |     +-------------------+-------------------+     |
           +-------------------------|-------------------------+
                                     |
                          [Passed Quality Gate]
                                     |
                                     v
                                  [ END ]
                                     |
                Checkpoints Synchronized After Every Step
                                     v
                      +-----------------------------+
                      |   Neon Serverless Postgres  |
                      +-----------------------------+

---

## Key Features

### 1. Cyclical Agent Execution & Self-Correction
Unlike unidirectional pipelines, the graph uses conditional edge routing based on the output of the **Verifier Node**. If a tool outputs fallback or degraded data, the Verifier assigns a failing quality score and passes critique directives back to the **Planner Node**, which dynamically re-plans the task.

### 2. Checkpointing & State Recovery (PostgreSQL via Neon)
Every thread transition is saved to a PostgreSQL backend using `PostgresSaver`. 
* Thread state, execution history, and tool outputs remain intact across crashes.
* Persistent connection pooling prevents serverless disconnect timeouts while maintaining direct state inspection.

### 3. Human-in-the-Loop (HITL) Gateways
Destructive operations (such as `UPDATE` or `DELETE` statements) are automatically flagged as sensitive. When detected:
1. LangGraph triggers `interrupt()`, halting runtime execution immediately.
2. The entire thread state is committed to PostgreSQL.
3. The UI surfaces an interactive prompt with the exact proposed payload.
4. Once the operator clicks **Approve** or **Reject**, execution resumes via `Command(resume=...)`.

### 4. Resilient Tooling & Heuristic Fallbacks
Custom `@heuristic_fallback` decorators intercept unexpected runtime errors (network timeouts, query errors, rate limits):
* Prevents unhandled exceptions from terminating the workflow run.
* Emits deterministic, structured fallback payloads that the Verifier can detect and handle systematically.

---

## Project Structure

```text
Stateful-Multi-Agent-system/
├── core/
│   ├── __init__.py         # Package initialization
│   ├── graph.py            # Cyclical LangGraph definition, nodes, and checkpointer
│   ├── schemas.py          # Pydantic input models, state contracts, and evaluation schemas
│   └── tools.py            # Custom tools with error trapping and heuristic fallback decorators
├── static/
│   └── index.html          # Clean dashboard interface with live event streaming and state inspector
├── .env.example            # Environment configuration template
├── .gitignore              # Ignored files (venv, .env, cache)
├── main.py                 # FastAPI application, route definitions, and Uvicorn runner
├── requirements.txt        # Frozen project dependencies
└── README.md               # System documentation                      
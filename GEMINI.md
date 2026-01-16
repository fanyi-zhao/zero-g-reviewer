# Zero-G Reviewer (cr-agent-system)

This is an AI Code Review Agent designed for high-throughput code reviews in monorepo environments. It utilizes **LangGraph** for multi-agent orchestration, enabling it to intelligently route reviews based on complexity and domain.

## Project Overview

The system operates on an "Antigravity" architecture that prioritizes context and drift prevention before code analysis.

*   **Core Framework:** LangGraph (State Machine), LangChain.
*   **Vector Store:** ChromaDB (for User Preferences RAG).
*   **Architecture:**
    1.  **Context Analysis:** Queries knowledge graph for dependencies, design patterns, hotspots, and user preferences.
    2.  **Routing:** Analyzes diff size and domain count.
        *   **Lite Mode:** Routes small changes (≤300 lines, ≤3 domains) to a `General Reviewer`.
        *   **Delegation Mode:** Routes complex changes to specialized parallel sub-agents (`Security`, `Performance`, `Domain`) using the `Send` API.
    3.  **Synthesis:** Aggregates, de-conflicts, and formats findings into a tiered report (Blockers -> Architectural -> Nitpicks).

## Key Files & Directories

*   `src/cr_agent/main.py`: **CLI Entry Point.** Handles argument parsing, PR fetching (GitHub/GitLab), and invoking the LangGraph workflow.
*   `src/cr_agent/graph.py`: **Workflow Definition.** Defines the LangGraph state machine, nodes, and parallel execution logic (`build_graph`).
*   `src/cr_agent/state.py`: **State Management.** Defines `AgentState` (TypedDict) and Pydantic models for context and review results. Includes reducers for parallel state updates.
*   `src/cr_agent/routing/`: Contains logic for routing decisions (`router.py`) and context pruning (`file_filter.py`).
*   `src/cr_agent/agents/`: Implementations of individual agents (`security_agent.py`, `performance_agent.py`, etc.) and output parsers (`output_parsers.py`).
*   `src/cr_agent/tools/`: "Drift Prevention" tools (`dependency_impact.py`, `design_patterns.py`, `hotspot_detector.py`, `user_preferences.py`).
*   `scripts/seed_knowledge.py`: Utility to populate the vector store with historical PR data.
*   `CR_ORCHESTRATOR_PROMPT.md`: The system prompt serving as the PRD/Source of Truth.

## Building and Running

### Installation

```bash
pip install -e .
```

### Configuration

Ensure the following environment variables are set:

```bash
export OPENAI_API_KEY="your-key"
export GITHUB_TOKEN="your-token"      # For GitHub PRs
export GITLAB_TOKEN="your-token"      # For GitLab MRs
```

### Usage Commands

**Review a GitHub PR:**
```bash
python -m cr_agent.main --github owner/repo --pr 123
```

**Review a GitLab MR:**
```bash
python -m cr_agent.main --gitlab project-id --mr 456
```

**Run a Sample Review (Testing):**
```bash
python -m cr_agent.main --sample
```

**Seed Knowledge Base:**
```bash
python scripts/seed_knowledge.py
```

**Run Tests:**
```bash
pytest
```

## Development Conventions

*   **State Management:** All agent data flows through `AgentState`. Parallel writes to `sub_agent_results` must be handled via the defined reducer (`merge_results`) in `state.py`.
*   **Context First:** Never bypass the Context Analysis phase. The agent must "understand" the code context (dependencies, patterns) before "acting" (reviewing).
*   **Structured Output:** Sub-agents must use Pydantic models defined in `output_parsers.py` to ensure reliable downstream synthesis.
*   **Parallelism:** Use LangGraph's `Send` API for fan-out operations when delegating to sub-agents.
*   **Observability:** Use the `ReviewLogger` in `main.py` to maintain structured logging (PHASE 1, PHASE 2, etc.) for CLI output.

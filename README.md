# Zero-G Reviewer

![CI](https://github.com/fanyi-zhao/zero-g-reviewer/actions/workflows/ci.yml/badge.svg)
![Coverage](https://raw.githubusercontent.com/fanyi-zhao/zero-g-reviewer/badges/coverage.svg)

AI Code Review Agent using LangGraph for multi-agent orchestration in monorepo environments.

## Features

- **Context Analysis** - Knowledge graph queries for dependencies, patterns, and hotspots
- **Smart Delegation** - Routes large PRs to specialized sub-agents (Security, Performance, Domain)
- **User Preferences** - Learns from historical PR comments to avoid repeating mistakes
- **Tiered Output** - Blockers → Architectural → Nitpicks

## Quick Start

### Prerequisites

- [uv](https://github.com/astral-sh/uv) installed

### Installation

```bash
# Setup virtual environment
uv venv
source .venv/bin/activate

# Install Dependencies
uv pip install -e .

# [Optional] Install Dev Dependencies for Testing
uv pip install -e ".[dev]"
```

## 1. Seeding Knowledge

> [!IMPORTANT]
> **Recommended:** Seeding the knowledge base is optional but highly recommended. It provides the agent with deep context about dependencies and patterns, significantly improving review quality.

```bash
# GitHub
export GITHUB_TOKEN="token"
python -m cr_agent.main seed --github owner/repo

# GitLab
export GITLAB_URL="https://gitlab.example.com"
export GITLAB_TOKEN="token"
python -m cr_agent.main seed --gitlab 12345
```

<details>
<summary><strong>View Example Output</strong></summary>

```text
============================================================
🌱 CR Agent Knowledge Seeding (Multi-Provider)
============================================================

✓ Configuration loaded (Provider: GITHUB)

📥 Fetching last 20 merged PRs from GitHub...
   Found 20 merged PRs
   ...
📝 Found 23 actionable discussion threads

🧠 Distilling preference rules using LLM...
   [1/23] PR #32444... ✓ architecture
   [2/23] PR #32460... ✓ architecture
   ...
📊 Distilled 23 preference rules from 23 threads

💾 Ingesting into ChromaDB...

✅ SUCCESS!
   Provider: GITHUB
   Ingested: 23 new rules
   Total rules in store: 24
   Collection: user_preferences
   Persist path: ./data/chroma

============================================================
📋 Sample Preference Rules:
============================================================

[ARCHITECTURE] (confidence: 90%)
  Rule: Check for feature availability instead of specific platform checks to ensure portability and adaptability of tests.
  From: PR #32444

[PERFORMANCE] (confidence: 80%)
  Rule: Minimize redundant template instantiations by reorganizing dispatch procedures to improve code efficiency and maintainability.
  From: PR #31968
```
</details>

## 2. Run PR Review



Once the knowledge base is seeded, you can run the agent:

```bash
export OPENAI_API_KEY="your-key"

# Review a GitHub PR
GITHUB_TOKEN="your-token" python -m cr_agent.main --github vllm-project/vllm --pr 32263

# Review a GitLab MR
GITLAB_TOKEN="your-token" python -m cr_agent.main --gitlab 12345 --mr 1

# Run sample review (Offline test)
python -m cr_agent.main --sample
```

<details>
<summary><strong>View Example Review Output</strong></summary>

```text
📥 Fetching PR #32263 from vllm-project/vllm...
✓ Fetched: [cpu][performance] CPU Paged Attention NEON BFMMLA BF16 Impl...
   Files: 8, +981/-25

======================================================================
  CR Agent Review: vllm-project/vllm#PR-32263
======================================================================

📄 Diff: 48,805 chars, 1,159 lines

==================================================
PHASE 1: Workflow Initialization (gpt-5-mini-2025-08-07)
==================================================
✓ Built LangGraph workflow with parallel execution

==================================================
PHASE 2: Executing Review Workflow
==================================================
   Steps: Context Analysis → Routing → [Parallel Agents] → Synthesis
⏳ Running agent workflow (async)...
✓ Workflow completed

==================================================
PHASE 3: Final Output
==================================================

======================================================================
REVIEW RESULTS
======================================================================

# Code Review Results

## 1. Executive Summary: **Request Changes**

## 2. Architectural Impact: **Medium**

## 3. Critical Issues

🔴 **Unsafe reinterpret_cast from tensor data pointer to backend cache type**
   - Location: `csrc/cpu/cpu_attn.cpp:?`
   - The code reinterpret_casts tensor data pointers to a backend-specific cache type (cache_t*) based on a conditional typedef:

    reinterpret_cast<cache_t*>( key_cache.data_ptr<cache_scalar_torch>() )

If cache_t differs in size, alignment, or representation from cache_scalar_torch (or from the actual underlying storage of the tensor), this can cause undefined behavior, unaligned accesses, and memory corruption.

   - *Fix:* Avoid raw reinterpret_cast between potentially-incompatible types. Validate the tensor dtype, element size and alignment before casting.

🔴 **No bounds/argument validation in low-level packing function (reshape_Q_2xK_for_bfmmla)**
   - Location: `csrc/cpu/cpu_attn_neon_bfmmla.hpp:?`
   - The newly-added function reshape_Q_2xK_for_bfmmla performs element reads from r0/r1 and writes into dst according to K with loops and vector loads/stores, but it does not validate that K is non-negative or that the dst buffer is large enough for the produced output.
   - *Fix:* Validate inputs at the function boundary. For example: Require K >= 0 and fail with a clear error if not.

🟠 **Index/size arithmetic lacks explicit overflow/limits checks**
   - Location: `csrc/cpu/cpu_attn_impl.hpp:?`
   - Several places compute offsets and sizes using signed 32-bit integers without overflow checks.
   - *Fix:* Add explicit validation of all user-controllable size/stride/index inputs at API boundaries.

## 4. Suggestions

💡 **Safely map tensor storage to backend cache type**
   - `csrc/cpu/cpu_attn.cpp`

💡 **Add input validation and safe tail handling for packing kernels**
   - `csrc/cpu/cpu_attn_neon_bfmmla.hpp`
```
</details>

## Documentation

- **[Design Document](doc/DESIGN.md)** — Architecture, state machine, tool definitions
- **[Implementation Walkthrough](doc/WALKTHROUGH.md)** — Project structure, validation results

## License

MIT

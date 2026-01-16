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
export GITHUB_REPO="owner/repo"
python scripts/seed_knowledge.py

# GitLab
export GITLAB_URL="https://gitlab.example.com"
export GITLAB_TOKEN="token"
export GITLAB_PROJECT_ID="12345"
python scripts/seed_knowledge.py
```

## 2. Run PR Review

Once the knowledge base is seeded, you can run the agent:

```bash
export OPENAI_API_KEY="your-key"
export GITHUB_TOKEN="your-token"

# Review a GitHub PR
python -m cr_agent.main --github vllm-project/vllm --pr 32263

# Run sample review (Offline test)
python -m cr_agent.main --sample
```

## Documentation

- **[Design Document](doc/DESIGN.md)** — Architecture, state machine, tool definitions
- **[Implementation Walkthrough](doc/WALKTHROUGH.md)** — Project structure, validation results

## License

MIT

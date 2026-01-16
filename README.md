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

export OPENAI_API_KEY="your-key"
export GITHUB_TOKEN="your-token"

# Review a GitHub PR
python -m cr_agent.main --github vllm-project/vllm --pr 32263

# Run sample review
python -m cr_agent.main --sample
```

## Seeding Knowledge

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

## Documentation

- **[Design Document](doc/DESIGN.md)** — Architecture, state machine, tool definitions
- **[Implementation Walkthrough](doc/WALKTHROUGH.md)** — Project structure, validation results

## License

MIT

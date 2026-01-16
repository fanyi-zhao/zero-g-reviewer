# Zero-G Reviewer

AI Code Review Agent using LangGraph for multi-agent orchestration in monorepo environments.

## Features

- **Context Analysis** - Knowledge graph queries for dependencies, patterns, and hotspots
- **Smart Delegation** - Routes large PRs to specialized sub-agents (Security, Performance, Domain)
- **User Preferences** - Learns from historical PR comments to avoid repeating mistakes
- **Tiered Output** - Blockers → Architectural → Nitpicks

## Quick Start

```bash
pip install -e .
export OPENAI_API_KEY="your-key"
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

## License

MIT

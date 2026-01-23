# Claude CR Agent

A Claude-powered GitLab Merge Request code review agent. This agent uses the Anthropic Claude API to analyze MR changes and produce high-quality, actionable code reviews.

## Features

- 🔍 **Two-pass review**: Quick scan for hotspots, then deep dive analysis
- 🔒 **Security-focused**: Prioritizes security-related files and patterns
- 📝 **GitLab-native**: Produces markdown with GitLab `suggestion` blocks
- 🛡️ **Safe execution**: Restricted shell commands with strict allowlists
- 🎯 **Context-aware**: Uses git blame, history, and file context for accurate reviews
- 📊 **Prioritized findings**: Severity levels (Blocker/Major/Minor/Nit) with confidence

## Installation

### Using pip

```bash
pip install -e .
```

### Using uv (recommended)

```bash
uv pip install -e .
```

### Development installation

```bash
# Clone the repository
git clone <repo-url>
cd claude_cr_agent

# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest
```

## Configuration

The agent is configured via environment variables:

### Required

| Variable | Description |
|----------|-------------|
| `CR_AGENT_GITLAB_TOKEN` | GitLab access token with `api` and `read_api` scopes |
| `CR_AGENT_LLM_API_KEY` | Anthropic API key (or compatible endpoint) |
| `CR_AGENT_PROJECT_ID` | GitLab project ID (numeric) or path (e.g., `namespace/project`) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `CR_AGENT_GITLAB_BASE_URL` | `https://gitlab.com` | GitLab instance URL |
| `CR_AGENT_LLM_BASE_URL` | `https://api.anthropic.com` | Claude-compatible API endpoint |
| `CR_AGENT_LLM_MODEL` | `claude-sonnet-4-20250514` | Model to use |
| `CR_AGENT_MAX_FILES` | `50` | Maximum files to review |
| `CR_AGENT_MAX_DIFF_CHARS` | `100000` | Maximum diff characters to process |
| `CR_AGENT_POST_TO_GITLAB` | `false` | Whether to post review as MR comment |

### Example `.env` file

```bash
CR_AGENT_GITLAB_TOKEN=glpat-xxxxxxxxxxxx
CR_AGENT_LLM_API_KEY=sk-ant-xxxxxxxxxxxx
CR_AGENT_PROJECT_ID=12345
CR_AGENT_GITLAB_BASE_URL=https://gitlab.example.com
```

## Usage

### Command Line

```bash
# Basic usage - review MR #42, print to stdout
cr-agent review 42 --repo /path/to/local/repo

# With inline environment variables
CR_AGENT_GITLAB_TOKEN=xxx CR_AGENT_LLM_API_KEY=xxx CR_AGENT_PROJECT_ID=123 \
  cr-agent review 42 --repo .

# Post review to GitLab
cr-agent review 42 --repo . --post

# Write to file
cr-agent review 42 --repo . --output review.md

# Verbose mode
cr-agent review 42 --repo . -vvv

# Override branches
cr-agent review 42 --repo . --target main --source feature/branch

# Validate configuration
cr-agent validate --repo .
```

### As a Python module

```bash
python -m cr_agent.cli review 42 --repo /path/to/repo
```

### Programmatic usage

```python
from cr_agent.agent import run_review
from cr_agent.config import Settings

settings = Settings(
    gitlab_base_url="https://gitlab.example.com",
    gitlab_token="glpat-xxx",
    project_id="12345",
    llm_api_key="sk-ant-xxx",
)

result = run_review(
    mr_iid=42,
    local_repo_path="/path/to/repo",
    settings=settings,
)

# Get the GitLab-ready comment
comment = result.to_gitlab_comment()
print(comment)

# Or access structured data
print(f"Recommendation: {result.recommendation}")
print(f"Findings: {len(result.findings)}")
for finding in result.findings:
    print(f"  - [{finding.severity.value}] {finding.title}")
```

## How It Works

### 1. Data Collection

The agent fetches:
- MR metadata (title, description, author, branches)
- Changed files and diffs via GitLab API
- Commit history
- Pipeline status (if available)

### 2. Review Planning

Files are prioritized based on:
- Security sensitivity (auth, crypto, permissions)
- Change type (new files, API changes, configs)
- Extension priority (Python, Go, etc.)
- Change size

Vendored files, lock files, and generated code are automatically skipped.

### 3. Two-Pass Analysis

**Pass A (Quick Scan):**
- Summarizes changes
- Identifies hotspots
- Creates review plan

**Pass B (Deep Dive):**
- Reviews each file's diff
- Uses tools to fetch additional context (git blame, file history)
- Identifies issues by severity

### 4. Hotspot Investigation

Security-sensitive files and API changes get extra scrutiny with:
- Full file content analysis
- Git blame to understand history
- Related test file inspection

### 5. Synthesis

All findings are compiled into a structured review with:
- Summary and recommendation
- Findings grouped by severity
- GitLab suggestion blocks for code fixes
- Test commands
- Pre-merge checklist

## Output Format

The review is formatted as a GitLab-compatible markdown comment:

```markdown
# 🔍 Code Review

## Summary
**Recommendation:** ✅ **Approve** / ⚠️ **Request Changes** / 💬 **Comment**

## Key Findings

### Blocker
- 🔴 **Issue title** in `file.py` (L10-15)
  - *Confidence: high*
  Description of the issue.
  
  ```suggestion
  <replacement code>
  ```

### Major
...

## Tests / Verification
```bash
pytest tests/ -v
```

## Pre-Merge Checklist
- [ ] All tests pass
- [ ] ...
```

## Safety & Restrictions

### Allowed Operations

- **GitLab API**: GET requests for MR data, POST for notes (if enabled)
- **Local git**: `diff`, `show`, `log`, `blame`, `ls-files`, `fetch`, etc.
- **File reading**: `cat`, `head`, `tail`, `grep`, `find`

### Blocked Operations

- Network access (curl, wget, ssh)
- Destructive operations (rm, mv, chmod)
- Package managers (pip, npm, brew)
- Code execution (python, node)
- Shell operators (|, ;, &, >, $)

## Development

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=cr_agent --cov-report=html

# Run specific tests
pytest tests/test_gitlab_client.py -v
```

### Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## GitLab API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /projects/:id` | Resolve project path to ID |
| `GET /projects/:id/merge_requests/:iid` | MR metadata |
| `GET /projects/:id/merge_requests/:iid/changes` | File diffs |
| `GET /projects/:id/merge_requests/:iid/commits` | Commit list |
| `GET /projects/:id/merge_requests/:iid/discussions` | Existing comments |
| `GET /projects/:id/repository/files/:path/raw` | File content |
| `POST /projects/:id/merge_requests/:iid/notes` | Post review comment |

## Assumptions

1. The local repository is a clone of the GitLab project
2. The GitLab token has `api` and `read_api` scopes
3. The LLM endpoint is Anthropic-compatible (Messages API)
4. Branch names from the MR exist in the remote

## Troubleshooting

### "Not a git repository"

Ensure you're pointing to the root of a git repository:

```bash
cr-agent review 42 --repo /path/to/repo  # Should contain .git/
```

### "GitLab API request failed"

Check your token and project ID:

```bash
cr-agent validate --repo .
```

### "Branches not found locally"

The agent will fall back to GitLab API for diffs. To use local git:

```bash
cd /path/to/repo
git fetch origin
```

## License

MIT

---

*Built with Claude 🤖*

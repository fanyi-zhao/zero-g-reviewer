You are an expert AI agent engineer. Write a complete, production-ready Claude Agent SDK project that implements a Merge Request review agent for GitLab.

## Goal

Build an agent that takes a GitLab Merge Request IID as input and produces a high-quality code review for a local monorepo (~19k LOC). The agent runs in a highly restricted environment:

* Allowed: local shell commands (bash), git commands on a local clone, and GitLab REST API (v4) using a provided access token with scopes: api, read_api
* Disallowed: any internet browsing outside GitLab API, any external SaaS tools, any package managers that require network access at runtime
* LLM access: via a hosted Claude-compatible API endpoint (OpenAI/Anthropic-compatible “messages” style is fine; assume we can configure base_url and api_key)

## Inputs

The agent must accept:

* mr_iid (required)
* gitlab_base_url (required, e.g. [https://gitlab.example.com](https://gitlab.example.com))
* project_id (required, numeric ID preferred; if a path is given, resolve it via GitLab API)
* local_repo_path (required)
* optional: target_branch (default from MR), source_branch (default from MR), max_files, max_diff_chars, verbosity
* optional: post_to_gitlab (default false). If true, the agent posts the review as an MR note via GitLab API; if false, it prints the comment body to stdout.

## Output (MUST be a GitLab MR comment body)

The agent must produce a single Markdown text block suitable to paste directly into a GitLab Merge Request comment.

### Required structure

Use this structure in the comment body:

1. **Summary**

* Overall recommendation: **Approve / Request changes / Comment**
* High-level risks
* What was reviewed (files/areas)

2. **Key Findings**
   Group findings by severity:

* **Blocker**
* **Major**
* **Minor**
* **Nit**

Each finding must reference the file path and (when available) line range or hunk context.

3. **Inline Suggestions (GitLab “suggestion” blocks)**
   Any code change suggestion MUST be provided using GitLab’s inline suggestion syntax:

```suggestion
<replacement code here>
```

Formatting rules for suggestions:

* Put the suggestion block immediately under the bullet describing the issue.
* Include ONLY the replacement code inside the suggestion block (no extra commentary inside).
* Keep suggestions minimal, compile-able, and limited in scope.
* If a fix requires multiple edits in a file, create multiple separate suggestion blocks.
* If you cannot confidently propose exact replacement code (insufficient context), do NOT guess. Instead, describe the change without a suggestion block and state what info is missing.

4. **Tests / Verification**

* List exact commands to run (bounded and realistic)
* Mention expected outcomes / assertions

5. **Checklist**
   A short author checklist to merge safely.

### Additional constraints

* Never hallucinate file contents: only comment on what was retrieved via git/GitLab API.
* Don’t leak secrets: redact tokens, avoid printing env vars.
* Deterministic-ish output: stable ordering (sort files; stable severity order).
* Include confidence for Blocker/Major items (High/Med/Low) based on available context.

## Core Requirements

### 1) GitLab integration (v4)

Implement GitLab API helpers to fetch:

* MR metadata: title, description, author, state, source/target branches
* MR changes (diffs, changed files list) using the best available endpoint
* MR commits and discussions/notes (optional but helpful)
* Pipeline status if available (optional)

All requests must be authenticated using the token provided via environment variable (e.g. GITLAB_TOKEN). Handle pagination, rate limits, and errors gracefully.

If post_to_gitlab=true, implement posting the final comment via:

* POST /projects/:id/merge_requests/:iid/notes
  (Default to read-only if post_to_gitlab=false.)

### 2) Local git repository usage

Use the local repo to enrich context and avoid downloading entire files via API:

* Validate local repo matches the MR source branch (or fetch if remote is configured; if not possible, degrade gracefully)
* Compute diffs locally when possible:

  * Prefer: git fetch + git diff target..source
  * Fallback: use GitLab MR changes endpoint diff
* For each changed file, pull context with git show / git blame / git log -p (bounded)
* Do NOT read the entire monorepo. Focus on changed files and only pull nearby context for referenced symbols if needed.

### 3) Context management for the LLM

Because token/context can blow up:

* Summarize MR description and commit messages first
* Chunk diff by file and limit by configurable max_diff_chars
* If diff is huge, prioritize:

  1. critical files (security/auth, infra, build, dependency changes)
  2. large behavioral changes
  3. public APIs
* Use a two-pass approach:

  * Pass A: quick scan to identify hotspots/questions
  * Pass B: targeted deep dive with extra context from git show/blame/log around hotspots

### 4) Safety + correctness constraints

* Never hallucinate file contents: only comment on what was retrieved via git/GitLab API
* If information is missing (e.g., cannot fetch branches), explicitly say what’s missing and how it affects confidence
* Don’t leak secrets: redact tokens, avoid printing env vars
* Deterministic-ish behavior: stable ordering of files and findings; include confidence levels for major claims

## Claude Agent SDK implementation details

Use Claude Agent SDK patterns:

* Define tools:

  * bash_tool: run restricted shell commands in local_repo_path (only allow git + safe read operations like cat/sed/grep; block rm, curl, network, etc.)
  * gitlab_tool: wrapper for GitLab API GET requests (and optional POST for notes if post_to_gitlab=true; default read-only)
* Define an agent orchestration loop:

  1. Resolve MR -> get metadata
  2. Get diffs/changes -> build review plan
  3. Gather context via git commands (bounded, per plan)
  4. Run LLM review synthesis
  5. Render a single GitLab-ready comment body (with ```suggestion blocks)
  6. Optionally post it to GitLab (if enabled)

Include clear separation between:

* data collection
* analysis/synthesis
* rendering

## Project deliverables (must produce full code)

Create a repository structure with:

* README with setup + usage examples
* configuration (env vars, base_url, token, repo path)
* main entrypoint CLI (e.g., python -m agent review --mr-iid 123 --post-to-gitlab false)
* tool implementations with strict allowlists for shell commands
* unit tests for GitLab API wrapper and diff chunker (can use mocked responses)
* examples: sample GitLab comment output (must include at least one ```suggestion block)

Assume Python implementation unless you strongly prefer TypeScript; pick one and commit to it.

## Review quality rubric (your agent must follow)

When generating findings:

* Identify correctness issues, edge cases, error handling, nullability, logging
* Spot API contract mismatches, breaking changes, backward compatibility
* Flag concurrency/race conditions if relevant
* Suggest tests and expected assertions
* Provide actionable fixes, not generic advice
* Keep tone professional and helpful

## Restrictions reminder

No web browsing, no external calls beyond GitLab API and the hosted Claude-compatible endpoint. Only use bash/git on the local repo.

## Now: produce the complete project code

Return:

* A file tree
* The contents of every file
* Instructions to run locally

Do not omit any required file contents. If you make assumptions (e.g., which GitLab endpoints to use), document them in README.

"""
CR Agent Main Entry Point

Production-ready CLI for code review execution with:
- Dynamic PR/MR input via CLI arguments
- GitHub/GitLab integration for fetching PR data
- Structured observability logging (PHASE 1, 2, 3...)
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from cr_agent.state import FinalReview
from cr_agent.tools import (
    DependencyImpactTool,
    DesignPatternTool,
    HotspotDetectorTool,
    UserPreferencesTool,
)
from cr_agent.routing import routing_decision_node


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MODEL = "gpt-5-mini-2025-08-07"


def load_system_prompt(prompt_path: str | Path | None = None) -> str:
    """Load the orchestrator system prompt from file."""
    if prompt_path is None:
        prompt_path = Path(__file__).parent.parent.parent / "CR_ORCHESTRATOR_PROMPT.md"
    
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"System prompt not found: {path}")
    
    return path.read_text(encoding="utf-8")


def create_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    **kwargs: Any,
) -> BaseChatModel:
    """Create and configure the LLM for code review."""
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        **kwargs,
    )


# =============================================================================
# Observability / Logging
# =============================================================================

class ReviewLogger:
    """Structured logging for the review process."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.phase = 0
    
    def header(self, title: str) -> None:
        """Print a major header."""
        if self.verbose:
            print("\n" + "=" * 70)
            print(f"  {title}")
            print("=" * 70 + "\n")
    
    def phase_start(self, name: str) -> None:
        """Start a new phase with structured logging."""
        self.phase += 1
        if self.verbose:
            print(f"\n{'='*50}")
            print(f"PHASE {self.phase}: {name}")
            print("=" * 50)
    
    def info(self, emoji: str, message: str) -> None:
        """Log an info message."""
        if self.verbose:
            print(f"{emoji} {message}")
    
    def detail(self, message: str) -> None:
        """Log a detail message (indented)."""
        if self.verbose:
            print(f"   {message}")
    
    def success(self, message: str) -> None:
        """Log a success message."""
        if self.verbose:
            print(f"✓ {message}")
    
    def warning(self, message: str) -> None:
        """Log a warning message."""
        print(f"⚠ {message}")
    
    def error(self, message: str) -> None:
        """Log an error message."""
        print(f"❌ {message}")


# =============================================================================
# PR/MR Fetching
# =============================================================================

class PRFetcher:
    """Fetches PR/MR data from GitHub or GitLab."""
    
    def __init__(self, logger: ReviewLogger):
        self.logger = logger
    
    def fetch_github_pr(self, repo: str, pr_number: int) -> dict[str, Any]:
        """
        Fetch PR data from GitHub using gh CLI.
        
        Args:
            repo: Repository in format "owner/repo"
            pr_number: PR number
            
        Returns:
            Dictionary with mr_id, title, diff, related_files, user_notes
        """
        self.logger.info("📥", f"Fetching PR #{pr_number} from {repo}...")
        
        # Fetch PR metadata
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--repo", repo,
                 "--json", "title,body,files,additions,deletions"],
                capture_output=True,
                text=True,
                check=True,
            )
            metadata = __import__("json").loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to fetch PR metadata: {e.stderr}")
        
        # Fetch diff
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number), "--repo", repo],
                capture_output=True,
                text=True,
                check=True,
            )
            diff = result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to fetch PR diff: {e.stderr}")
        
        related_files = [f["path"] for f in metadata.get("files", [])]
        
        self.logger.success(f"Fetched: {metadata['title'][:60]}...")
        self.logger.detail(f"Files: {len(related_files)}, +{metadata['additions']}/-{metadata['deletions']}")
        
        return {
            "mr_id": f"{repo}#PR-{pr_number}",
            "title": metadata["title"],
            "diff": diff,
            "related_files": related_files,
            "user_notes": metadata.get("body", "") or "",
        }
    
    def fetch_gitlab_mr(self, project_id: str, mr_iid: int) -> dict[str, Any]:
        """
        Fetch MR data from GitLab using python-gitlab.
        
        Args:
            project_id: GitLab project ID
            mr_iid: Merge request IID
            
        Returns:
            Dictionary with mr_id, title, diff, related_files, user_notes
        """
        import gitlab
        
        self.logger.info("📥", f"Fetching MR !{mr_iid} from project {project_id}...")
        
        gl = gitlab.Gitlab(
            url=os.environ.get("GITLAB_URL", "https://gitlab.com"),
            private_token=os.environ["GITLAB_TOKEN"],
        )
        
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)
        
        # Get diff
        changes = mr.changes()
        diff_parts = []
        for change in changes.get("changes", []):
            diff_parts.append(change.get("diff", ""))
        diff = "\n".join(diff_parts)
        
        related_files = [c["new_path"] for c in changes.get("changes", [])]
        
        self.logger.success(f"Fetched: {mr.title[:60]}...")
        self.logger.detail(f"Files: {len(related_files)}")
        
        return {
            "mr_id": f"MR-{mr_iid}",
            "title": mr.title,
            "diff": diff,
            "related_files": related_files,
            "user_notes": mr.description or "",
        }


# =============================================================================
# Review Execution
# =============================================================================

REVIEW_PROMPT = """You are a senior code reviewer. Analyze the following PR/MR.

## Context from Knowledge Graph
- Dependencies: {dependencies}
- Patterns: {patterns}
- Hotspots: {hotspots}
- User Preferences: {user_preferences}

## PR Information
- ID: {mr_id}
- Title: {title}
- Files: {related_files}
- Author Notes: {user_notes}

## Diff
```diff
{diff}
```

## Your Task
Provide a thorough code review with:

1. **Critical Issues** (bugs, security, build-breaking)
   - Severity: CRITICAL/HIGH/MEDIUM/LOW
   - File path and line number
   - Description and fix

2. **Performance Concerns**
   - N+1 patterns, memory issues, algorithmic complexity

3. **Architectural Alignment**
   - Pattern violations, design concerns

4. **Suggestions**
   - Specific improvements with code examples

Be thorough, precise, and actionable.
"""


async def run_review(
    pr_data: dict[str, Any],
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> str:
    """
    Execute a full code review with observability logging.
    
    Args:
        pr_data: Dictionary with mr_id, title, diff, related_files, user_notes
        model: LLM model to use
        verbose: Enable detailed logging
        
    Returns:
        The review output as a string
    """
    logger = ReviewLogger(verbose=verbose)
    
    logger.header(f"CR Agent Review: {pr_data['mr_id']}")
    
    # --- Phase 1: Input Validation ---
    logger.phase_start("Input Validation")
    
    diff = pr_data.get("diff", "")
    related_files = pr_data.get("related_files", [])
    
    logger.info("📄", f"Diff: {len(diff):,} chars, {diff.count(chr(10)):,} lines")
    logger.info("📁", f"Files: {len(related_files)}")
    
    if not diff:
        logger.error("No diff content provided")
        return "Error: No diff content"
    
    # --- Phase 2: Context Analysis ---
    logger.phase_start("Context Analysis (Drift Prevention)")
    
    dependency_result = DependencyImpactTool.invoke({
        "modified_files": related_files,
    })
    logger.info("📦", f"Dependencies: {dependency_result['impact_severity']} impact")
    
    pattern_result = DesignPatternTool.invoke({
        "file_paths": related_files,
    })
    logger.info("🏗️", f"Patterns: {pattern_result['pattern_name'] or 'None detected'}")
    
    hotspot_result = HotspotDetectorTool.invoke({
        "file_paths": related_files,
    })
    logger.info("🔥", f"Hotspots: churn={hotspot_result['overall_churn_score']:.2f}")
    
    prefs_result = UserPreferencesTool.invoke({
        "code_context": diff[:2000],
        "file_paths": related_files,
    })
    logger.info("👤", f"Preferences: {len(prefs_result['preference_signals'])} signals")
    for pref in prefs_result.get("preference_signals", [])[:3]:
        logger.detail(f"• {pref[:70]}...")
    
    # --- Phase 3: Routing Decision ---
    logger.phase_start("Routing Decision")
    
    routing = routing_decision_node({
        "mr_id": pr_data["mr_id"],
        "diff": diff,
        "related_files": related_files,
    })
    
    logger.info("📊", f"Lines: {routing['total_lines']} (threshold: 300)")
    logger.info("📊", f"Domains: {routing['domain_count']} - {routing['detected_domains']}")
    logger.info("🚦", f"Decision: {'DELEGATE to sub-agents' if routing['should_delegate'] else 'LITE MODE'}")
    
    # --- Phase 4: LLM Review ---
    logger.phase_start(f"LLM Code Review ({model})")
    
    llm = create_llm(model=model)
    logger.success(f"Initialized LLM: {model}")
    
    # Build prompt with context
    prompt = REVIEW_PROMPT.format(
        dependencies=dependency_result,
        patterns=pattern_result,
        hotspots=hotspot_result,
        user_preferences=prefs_result,
        mr_id=pr_data["mr_id"],
        title=pr_data.get("title", ""),
        related_files=", ".join(related_files),
        user_notes=pr_data.get("user_notes", ""),
        diff=diff[:50000],  # Truncate for token limits
    )
    
    logger.info("📝", f"Prompt: {len(prompt):,} chars")
    logger.info("⏳", "Calling LLM (this may take a minute)...")
    
    response = await llm.ainvoke(prompt)
    
    # --- Phase 5: Output ---
    logger.phase_start("Review Complete")
    logger.success("Review generated successfully")
    
    return response.content


# =============================================================================
# CLI Interface
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="CR Agent - AI Code Review System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review a GitHub PR
  python -m cr_agent.main --github vllm-project/vllm --pr 32263

  # Review a GitLab MR
  python -m cr_agent.main --gitlab 12345 --mr 789

  # Run sample review
  python -m cr_agent.main --sample
        """,
    )
    
    parser.add_argument(
        "--github",
        metavar="REPO",
        help="GitHub repository (e.g., 'owner/repo')",
    )
    parser.add_argument(
        "--pr",
        type=int,
        metavar="NUMBER",
        help="GitHub PR number",
    )
    parser.add_argument(
        "--gitlab",
        metavar="PROJECT_ID",
        help="GitLab project ID",
    )
    parser.add_argument(
        "--mr",
        type=int,
        metavar="IID",
        help="GitLab MR IID",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"LLM model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Run a sample review for testing",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity",
    )
    
    return parser.parse_args()


async def main_async() -> None:
    """Async main function."""
    args = parse_args()
    logger = ReviewLogger(verbose=not args.quiet)
    
    if args.sample:
        # Run sample review
        logger.header("CR Agent - Sample Review Mode")
        
        sample_data = {
            "mr_id": "SAMPLE-001",
            "title": "Sample PR for testing",
            "diff": """\
diff --git a/src/api/users.py b/src/api/users.py
+++ b/src/api/users.py
@@ -10,6 +10,10 @@
+def get_user(user_id: str):
+    # SQL injection vulnerability!
+    return db.query(f"SELECT * FROM users WHERE id = {user_id}")
""",
            "related_files": ["src/api/users.py"],
            "user_notes": "Added user lookup endpoint",
        }
        
        result = await run_review(sample_data, model=args.model, verbose=not args.quiet)
        
    elif args.github and args.pr:
        # GitHub PR review
        fetcher = PRFetcher(logger)
        pr_data = fetcher.fetch_github_pr(args.github, args.pr)
        result = await run_review(pr_data, model=args.model, verbose=not args.quiet)
        
    elif args.gitlab and args.mr:
        # GitLab MR review
        fetcher = PRFetcher(logger)
        pr_data = fetcher.fetch_gitlab_mr(args.gitlab, args.mr)
        result = await run_review(pr_data, model=args.model, verbose=not args.quiet)
        
    else:
        print("CR Agent - AI Code Review System\n")
        print("Usage:")
        print("  python -m cr_agent.main --github OWNER/REPO --pr NUMBER")
        print("  python -m cr_agent.main --gitlab PROJECT_ID --mr IID")
        print("  python -m cr_agent.main --sample")
        print("\nRun with --help for more options.")
        return
    
    # Output results
    print("\n" + "=" * 70)
    print("REVIEW RESULTS")
    print("=" * 70 + "\n")
    print(result)


def main() -> None:
    """CLI entry point."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

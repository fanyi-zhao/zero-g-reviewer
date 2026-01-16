"""
CR Agent Main Entry Point

Production-ready CLI for code review execution with:
- Dynamic PR/MR input via CLI arguments
- GitHub/GitLab integration for fetching PR data
- Structured observability logging (PHASE 1, 2, 3...)
- LangGraph workflow integration
"""

import argparse
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from cr_agent.state import FinalReview
from cr_agent.graph import build_graph, review_merge_request
from cr_agent.tools import (
    DependencyImpactTool,
    DesignPatternTool,
    HotspotDetectorTool,
    UserPreferencesTool,
)


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
        """Fetch PR data from GitHub."""
        self.logger.info("📥", f"Fetching PR #{pr_number} from {repo}...")
        
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
        """Fetch MR data from GitLab."""
        import gitlab
        
        self.logger.info("📥", f"Fetching MR !{mr_iid} from project {project_id}...")
        
        gl = gitlab.Gitlab(
            url=os.environ.get("GITLAB_URL", "https://gitlab.com"),
            private_token=os.environ["GITLAB_TOKEN"],
        )
        
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)
        
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

async def run_review(
    pr_data: dict[str, Any],
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> str:
    """Execute a full code review with observability logging and LangGraph."""
    logger = ReviewLogger(verbose=verbose)
    
    logger.header(f"CR Agent Review: {pr_data['mr_id']}")
    
    # Validate input
    diff = pr_data.get("diff", "")
    related_files = pr_data.get("related_files", [])
    
    if not diff:
        logger.error("No diff content provided")
        return "Error: No diff content"
        
    logger.info("📄", f"Diff: {len(diff):,} chars, {diff.count(chr(10)):,} lines")
    
    # Initialize LLM and Graph
    logger.phase_start(f"Workflow Initialization ({model})")
    llm = create_llm(model=model)
    graph = build_graph(llm)
    logger.success("Built LangGraph workflow with parallel execution")
    
    # Execute Graph
    logger.phase_start("Executing Review Workflow")
    logger.detail("Steps: Context Analysis → Routing → [Parallel Agents] → Synthesis")
    
    logger.info("⏳", "Running agent workflow (async)...")
    
    result: FinalReview = await review_merge_request(
        graph=graph,
        mr_id=pr_data["mr_id"],
        diff=diff,
        related_files=related_files,
        user_notes=pr_data.get("user_notes", ""),
    )
    
    logger.success("Workflow completed")
    
    # Format Output
    logger.phase_start("Final Output")
    return format_review_output(result)


def format_review_output(review: FinalReview) -> str:
    """Format the structured review as markdown."""
    output = []
    output.append("# Code Review Results\n")
    output.append(f"## 1. Executive Summary: **{review.executive_summary}**\n")
    output.append(f"## 2. Architectural Impact: **{review.architectural_impact}**\n")
    
    output.append("## 3. Critical Issues\n")
    if review.critical_issues:
        for issue in review.critical_issues:
            emoji = "🔴" if issue.get("severity") in ("CRITICAL", "HIGH", "BLOCKING") else "🟠"
            output.append(f"{emoji} **{issue.get('title')}**")
            output.append(f"   - Location: `{issue.get('file_path')}:{issue.get('line_number') or '?'}`")
            output.append(f"   - {issue.get('description')}")
            if issue.get("suggested_fix"):
                output.append(f"   - *Fix:* `{issue.get('suggested_fix')}`")
            output.append("")
    else:
        output.append("*No critical issues found.*\n")
    
    output.append("\n## 4. Suggestions\n")
    if review.suggestions:
        for suggestion in review.suggestions:
            output.append(f"💡 **{suggestion.get('title')}**")
            output.append(f"   - `{suggestion.get('file_path')}`")
            output.append(f"   - {suggestion.get('description')}")
            output.append("")
    else:
        output.append("*No additional suggestions.*\n")
    
    return "\n".join(output)


# =============================================================================
# CLI Interface
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="CR Agent - AI Code Review System")
    
    parser.add_argument("--github", metavar="REPO", help="GitHub repo (owner/repo)")
    parser.add_argument("--pr", type=int, metavar="NUMBER", help="GitHub PR number")
    parser.add_argument("--gitlab", metavar="PROJECT_ID", help="GitLab project ID")
    parser.add_argument("--mr", type=int, metavar="IID", help="GitLab MR IID")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"LLM model (default: {DEFAULT_MODEL})")
    parser.add_argument("--sample", action="store_true", help="Run sample review")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    
    return parser.parse_args()


async def main_async() -> None:
    """Async main function."""
    args = parse_args()
    logger = ReviewLogger(verbose=not args.quiet)
    
    if args.sample:
        logger.header("CR Agent - Sample Review Mode")
        sample_data = {
            "mr_id": "SAMPLE-001",
            "title": "Sample PR",
            "diff": """diff --git a/main.py b/main.py
index e69de29..d95c539 100644
--- a/main.py
+++ b/main.py
@@ -1,3 +1,4 @@
 def unsafe(x):
-    return eval(x)
+    # Fixed?
+    return eval(x)
""",
            "related_files": ["main.py"],
            "user_notes": "Sample check",
        }
        result = await run_review(sample_data, model=args.model, verbose=not args.quiet)
        
    elif args.github and args.pr:
        fetcher = PRFetcher(logger)
        pr_data = fetcher.fetch_github_pr(args.github, args.pr)
        result = await run_review(pr_data, model=args.model, verbose=not args.quiet)
        
    elif args.gitlab and args.mr:
        fetcher = PRFetcher(logger)
        pr_data = fetcher.fetch_gitlab_mr(args.gitlab, args.mr)
        result = await run_review(pr_data, model=args.model, verbose=not args.quiet)
        
    else:
        print("Usage: python -m cr_agent.main --github OWNER/REPO --pr NUMBER")
        print("See --help for details.")
        return
    
    print("\n" + "=" * 70)
    print("REVIEW RESULTS")
    print("=" * 70 + "\n")
    print(result)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

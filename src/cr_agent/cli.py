"""Command-line interface for the CR Agent."""

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from . import __version__
from .agent import run_review
from .config import Settings

app = typer.Typer(
    name="cr-agent",
    help="Claude-powered GitLab Merge Request code review agent",
    add_completion=False,
)
console = Console()


def setup_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    level = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
        3: logging.DEBUG,
    }.get(verbosity, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False)],
    )


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"cr-agent version {__version__}")
        raise typer.Exit()


@app.command()
def review(
    mr_iid: int = typer.Argument(..., help="Merge Request IID to review"),
    repo_path: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to local git repository",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    gitlab_url: Optional[str] = typer.Option(
        None,
        "--gitlab-url",
        envvar="CR_AGENT_GITLAB_BASE_URL",
        help="GitLab instance URL",
    ),
    project_id: Optional[str] = typer.Option(
        None,
        "--project",
        "-p",
        envvar="CR_AGENT_PROJECT_ID",
        help="GitLab project ID or path (e.g., 'namespace/project')",
    ),
    target_branch: Optional[str] = typer.Option(
        None,
        "--target",
        "-t",
        help="Target branch (default: from MR)",
    ),
    source_branch: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Source branch (default: from MR)",
    ),
    post_to_gitlab: bool = typer.Option(
        False,
        "--post/--no-post",
        help="Post review as MR comment",
    ),
    max_files: int = typer.Option(
        50,
        "--max-files",
        help="Maximum number of files to review",
    ),
    max_diff_chars: int = typer.Option(
        100000,
        "--max-diff",
        help="Maximum characters of diff to process",
    ),
    verbosity: int = typer.Option(
        1,
        "--verbose",
        "-v",
        count=True,
        help="Increase verbosity (use -v, -vv, or -vvv)",
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write review to file instead of stdout",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """
    Review a GitLab Merge Request.

    Analyzes the MR changes and produces a code review with findings,
    suggestions, and recommendations.

    Environment variables:
      - CR_AGENT_GITLAB_TOKEN: GitLab access token (required)
      - CR_AGENT_LLM_API_KEY: Claude API key (required)
      - CR_AGENT_GITLAB_BASE_URL: GitLab instance URL
      - CR_AGENT_PROJECT_ID: GitLab project ID/path
      - CR_AGENT_LLM_BASE_URL: Claude-compatible API endpoint
      - CR_AGENT_LLM_MODEL: Model to use (default: claude-sonnet-4-20250514)
    """
    setup_logging(verbosity)

    # Validate required settings
    try:
        # Build settings with CLI overrides
        env_overrides = {}
        if gitlab_url:
            env_overrides["gitlab_base_url"] = gitlab_url
        if project_id:
            env_overrides["project_id"] = project_id
        if post_to_gitlab:
            env_overrides["post_to_gitlab"] = post_to_gitlab
        if max_files != 50:
            env_overrides["max_files"] = max_files
        if max_diff_chars != 100000:
            env_overrides["max_diff_chars"] = max_diff_chars
        env_overrides["verbosity"] = verbosity

        settings = Settings(**env_overrides)  # type: ignore[arg-type]

    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("\nMake sure these environment variables are set:")
        console.print("  - CR_AGENT_GITLAB_TOKEN")
        console.print("  - CR_AGENT_LLM_API_KEY")
        console.print("  - CR_AGENT_PROJECT_ID (or use --project)")
        raise typer.Exit(1)

    # Run the review
    console.print(
        Panel(
            f"Reviewing MR !{mr_iid}\n"
            f"Repository: {repo_path}\n"
            f"Project: {settings.project_id}",
            title="🔍 Claude CR Agent",
            border_style="blue",
        )
    )

    try:
        result = run_review(
            mr_iid=mr_iid,
            local_repo_path=str(repo_path),
            settings=settings,
            target_branch=target_branch,
            source_branch=source_branch,
        )

        # Generate the review comment
        comment = result.to_gitlab_comment()

        # Output
        if output_file:
            output_file.write_text(comment)
            console.print(f"[green]Review written to {output_file}[/green]")
        else:
            console.print("\n")
            console.print(Panel(comment, title="Review", border_style="green"))

        # Post to GitLab if requested
        if settings.post_to_gitlab:
            from .gitlab_client import GitLabClient

            with GitLabClient(
                base_url=settings.gitlab_base_url,
                token=settings.gitlab_token.get_secret_value(),
                project_id=settings.project_id,
            ) as gitlab:
                gitlab.post_mr_note(mr_iid, comment)
                console.print("[green]✓ Review posted to GitLab[/green]")

        # Show summary
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Recommendation: {result.recommendation.value}")
        console.print(f"  Files reviewed: {len(result.files_reviewed)}")
        console.print(f"  Findings: {len(result.findings)}")

        # Exit with appropriate code
        if result.recommendation.value == "request_changes":
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error during review:[/red] {e}")
        if verbosity >= 2:
            console.print_exception()
        raise typer.Exit(2)


@app.command()
def validate(
    repo_path: Path = typer.Option(
        Path("."),
        "--repo",
        "-r",
        help="Path to local git repository",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Validate configuration and repository setup."""
    console.print("[bold]Validating configuration...[/bold]\n")

    errors = []
    warnings = []

    # Check environment variables
    import os

    if not os.getenv("CR_AGENT_GITLAB_TOKEN"):
        errors.append("CR_AGENT_GITLAB_TOKEN is not set")
    else:
        console.print("  ✓ GitLab token configured")

    if not os.getenv("CR_AGENT_LLM_API_KEY"):
        errors.append("CR_AGENT_LLM_API_KEY is not set")
    else:
        console.print("  ✓ LLM API key configured")

    if not os.getenv("CR_AGENT_PROJECT_ID"):
        warnings.append("CR_AGENT_PROJECT_ID is not set (can be passed via --project)")
    else:
        console.print(f"  ✓ Project ID: {os.getenv('CR_AGENT_PROJECT_ID')}")

    # Check repository
    from .git_ops import GitRepository, GitError

    try:
        repo = GitRepository(repo_path)
        branch = repo.get_current_branch()
        console.print(f"  ✓ Git repository valid (branch: {branch})")

        remote = repo.get_remote_url()
        if remote:
            console.print(f"  ✓ Remote: {remote}")
        else:
            warnings.append("No git remote configured")

    except GitError as e:
        errors.append(f"Git repository error: {e}")

    # Report results
    console.print("")

    if warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for w in warnings:
            console.print(f"  ⚠ {w}")

    if errors:
        console.print("[red]Errors:[/red]")
        for e in errors:
            console.print(f"  ✗ {e}")
        raise typer.Exit(1)

    console.print("[green]✓ All checks passed[/green]")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()

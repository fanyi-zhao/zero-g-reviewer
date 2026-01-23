"""Safe local git operations for context gathering."""

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Allowlist of safe commands
ALLOWED_COMMANDS = {
    "git": {
        "diff",
        "show",
        "log",
        "blame",
        "ls-files",
        "rev-parse",
        "branch",
        "status",
        "fetch",
        "remote",
        "cat-file",
        "rev-list",
        "merge-base",
        "name-rev",
        "describe",
    },
    "cat": set(),
    "head": set(),
    "tail": set(),
    "grep": set(),
    "wc": set(),
    "find": set(),
    "ls": set(),
    "file": set(),
}

# Commands that are never allowed
BLOCKED_PATTERNS = [
    r"\brm\b",
    r"\bmv\b",
    r"\bcp\b.*-r",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bnc\b",
    r"\bssh\b",
    r"\bscp\b",
    r"\brsync\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bsudo\b",
    r"\bsu\b",
    r"\beval\b",
    r"\bexec\b",
    r"\bsource\b",
    r"\bpip\b",
    r"\bnpm\b",
    r"\byarn\b",
    r"\bapt\b",
    r"\bbrew\b",
    r"\bpython\b",
    r"\bnode\b",
    r"[|;&`$]",  # Shell operators
    r">",  # Redirects
]


class GitError(Exception):
    """Error during git operation."""

    pass


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    command: str
    stdout: str
    stderr: str
    return_code: int
    success: bool


def is_command_safe(command: str) -> tuple[bool, str]:
    """
    Check if a command is safe to execute.

    Returns (is_safe, reason).
    """
    # Check for blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return False, f"Command contains blocked pattern: {pattern}"

    # Parse the command
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return False, f"Could not parse command: {e}"

    if not parts:
        return False, "Empty command"

    base_cmd = parts[0]

    # Check if the base command is allowed
    if base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command '{base_cmd}' is not in the allowlist"

    # For git, check the subcommand
    if base_cmd == "git" and len(parts) > 1:
        subcommand = parts[1]
        # Remove any flags from subcommand check
        if subcommand.startswith("-"):
            # Look for first non-flag argument
            for part in parts[1:]:
                if not part.startswith("-"):
                    subcommand = part
                    break
            else:
                return False, "No git subcommand found"

        if subcommand not in ALLOWED_COMMANDS["git"]:
            return False, f"Git subcommand '{subcommand}' is not allowed"

    return True, "Command is safe"


def run_command(
    command: str,
    cwd: str | Path,
    timeout: float = 30.0,
    max_output_bytes: int = 1_000_000,
) -> CommandResult:
    """
    Run a command safely in the specified directory.

    Args:
        command: The shell command to run
        cwd: Working directory for the command
        timeout: Maximum execution time in seconds
        max_output_bytes: Maximum bytes to capture from stdout/stderr

    Returns:
        CommandResult with stdout, stderr, and return code

    Raises:
        GitError: If command is not safe or execution fails
    """
    # Validate command safety
    is_safe, reason = is_command_safe(command)
    if not is_safe:
        raise GitError(f"Unsafe command rejected: {reason}")

    # Validate working directory
    cwd_path = Path(cwd).resolve()
    if not cwd_path.exists():
        raise GitError(f"Working directory does not exist: {cwd}")
    if not cwd_path.is_dir():
        raise GitError(f"Working directory is not a directory: {cwd}")

    try:
        # Run the command
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd_path),
            capture_output=True,
            timeout=timeout,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",  # Disable git prompts
                "PAGER": "cat",  # Disable paging
            },
        )

        stdout = result.stdout.decode("utf-8", errors="replace")[:max_output_bytes]
        stderr = result.stderr.decode("utf-8", errors="replace")[:max_output_bytes]

        return CommandResult(
            command=command,
            stdout=stdout,
            stderr=stderr,
            return_code=result.returncode,
            success=result.returncode == 0,
        )

    except subprocess.TimeoutExpired as e:
        raise GitError(f"Command timed out after {timeout}s: {command}") from e
    except subprocess.SubprocessError as e:
        raise GitError(f"Command execution failed: {e}") from e


class GitRepository:
    """Interface to a local git repository."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self._validate_repo()

    def _validate_repo(self) -> None:
        """Validate that the path is a git repository."""
        if not self.repo_path.exists():
            raise GitError(f"Repository path does not exist: {self.repo_path}")

        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise GitError(f"Not a git repository: {self.repo_path}")

    def run(self, command: str, timeout: float = 30.0) -> CommandResult:
        """Run a command in the repository."""
        return run_command(command, self.repo_path, timeout)

    def git(self, *args: str, timeout: float = 30.0) -> str:
        """
        Run a git command and return stdout.

        Args:
            *args: Git command arguments (without 'git' prefix)
            timeout: Command timeout

        Returns:
            Command stdout

        Raises:
            GitError: If command fails
        """
        command = "git " + " ".join(shlex.quote(arg) for arg in args)
        result = self.run(command, timeout)

        if not result.success:
            raise GitError(f"Git command failed: {result.stderr or result.stdout}")

        return result.stdout

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def get_remote_url(self, remote: str = "origin") -> str | None:
        """Get the URL for a remote."""
        try:
            return self.git("remote", "get-url", remote).strip()
        except GitError:
            return None

    def branch_exists(self, branch: str) -> bool:
        """Check if a branch exists locally or remotely."""
        try:
            self.git("rev-parse", "--verify", branch)
            return True
        except GitError:
            try:
                self.git("rev-parse", "--verify", f"origin/{branch}")
                return True
            except GitError:
                return False

    def fetch(self, remote: str = "origin", prune: bool = False) -> None:
        """Fetch from remote."""
        args = ["fetch", remote]
        if prune:
            args.append("--prune")
        try:
            self.git(*args, timeout=60.0)
        except GitError as e:
            logger.warning(f"Fetch failed: {e}")

    def get_diff(
        self,
        target_ref: str,
        source_ref: str,
        paths: list[str] | None = None,
        context_lines: int = 3,
    ) -> str:
        """
        Get diff between two refs.

        Args:
            target_ref: Base ref (e.g., 'main')
            source_ref: Head ref (e.g., 'feature-branch')
            paths: Optional list of file paths to diff
            context_lines: Number of context lines

        Returns:
            Unified diff output
        """
        args = ["diff", f"-U{context_lines}", f"{target_ref}...{source_ref}"]

        if paths:
            args.append("--")
            args.extend(paths)

        return self.git(*args, timeout=60.0)

    def get_file_content(self, path: str, ref: str = "HEAD") -> str | None:
        """Get file content at a specific ref."""
        try:
            return self.git("show", f"{ref}:{path}")
        except GitError:
            return None

    def get_blame(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        ref: str = "HEAD",
    ) -> str:
        """
        Get git blame for a file.

        Args:
            path: File path
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed)
            ref: Git ref

        Returns:
            Blame output
        """
        args = ["blame", "--date=short"]

        if start_line and end_line:
            args.extend(["-L", f"{start_line},{end_line}"])

        args.extend([ref, "--", path])

        try:
            return self.git(*args)
        except GitError:
            return ""

    def get_log(
        self,
        path: str | None = None,
        max_count: int = 10,
        format_str: str = "%h %s",
        ref: str | None = None,
    ) -> str:
        """Get git log."""
        args = ["log", f"-n{max_count}", f"--format={format_str}"]

        if ref:
            args.append(ref)

        if path:
            args.extend(["--", path])

        try:
            return self.git(*args)
        except GitError:
            return ""

    def get_merge_base(self, ref1: str, ref2: str) -> str | None:
        """Get the merge base between two refs."""
        try:
            return self.git("merge-base", ref1, ref2).strip()
        except GitError:
            return None

    def list_changed_files(self, target_ref: str, source_ref: str) -> list[str]:
        """List files changed between two refs."""
        try:
            output = self.git("diff", "--name-only", f"{target_ref}...{source_ref}")
            return [f.strip() for f in output.strip().split("\n") if f.strip()]
        except GitError:
            return []

    def get_file_at_ref(self, path: str, ref: str) -> str | None:
        """Get the content of a file at a specific ref."""
        try:
            return self.git("show", f"{ref}:{path}")
        except GitError:
            return None


def get_context_around_lines(
    content: str,
    start_line: int,
    end_line: int,
    context_lines: int = 10,
) -> str:
    """
    Extract context around specific lines in file content.

    Args:
        content: Full file content
        start_line: Starting line (1-indexed)
        end_line: Ending line (1-indexed)
        context_lines: Number of lines of context to include

    Returns:
        Content snippet with line numbers
    """
    lines = content.split("\n")
    total_lines = len(lines)

    # Calculate range with context
    ctx_start = max(1, start_line - context_lines)
    ctx_end = min(total_lines, end_line + context_lines)

    # Extract and format lines
    result_lines = []
    for i in range(ctx_start, ctx_end + 1):
        if i <= len(lines):
            prefix = ">" if start_line <= i <= end_line else " "
            result_lines.append(f"{i:4d}{prefix} {lines[i - 1]}")

    return "\n".join(result_lines)

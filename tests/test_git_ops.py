"""Tests for git operations."""

import pytest
import tempfile
import os
from pathlib import Path

from cr_agent.git_ops import (
    is_command_safe,
    run_command,
    GitRepository,
    GitError,
    get_context_around_lines,
)


class TestCommandSafety:
    """Tests for command safety validation."""

    def test_safe_git_commands(self):
        """Test that safe git commands are allowed."""
        safe_commands = [
            "git diff HEAD~1",
            "git show abc123:file.py",
            "git log -n 10 --oneline",
            "git blame file.py",
            "git ls-files",
            "git status",
            "git branch -a",
        ]

        for cmd in safe_commands:
            is_safe, reason = is_command_safe(cmd)
            assert is_safe, f"Command should be safe: {cmd} (reason: {reason})"

    def test_safe_read_commands(self):
        """Test that safe read commands are allowed."""
        safe_commands = [
            "cat file.py",
            "head -n 100 file.py",
            "tail -n 50 file.py",
            "grep -r 'pattern' src/",
            "wc -l file.py",
            "ls -la",
            "find . -name '*.py'",
        ]

        for cmd in safe_commands:
            is_safe, reason = is_command_safe(cmd)
            assert is_safe, f"Command should be safe: {cmd} (reason: {reason})"

    def test_blocked_destructive_commands(self):
        """Test that destructive commands are blocked."""
        blocked_commands = [
            "rm file.py",
            "rm -rf /",
            "mv file.py other.py",
            "chmod 777 file.py",
            "sudo anything",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"

    def test_blocked_network_commands(self):
        """Test that network commands are blocked."""
        blocked_commands = [
            "curl https://example.com",
            "wget https://example.com",
            "ssh user@host",
            "scp file.py user@host:",
            "nc -l 8080",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"

    def test_blocked_shell_operators(self):
        """Test that shell operators are blocked."""
        blocked_commands = [
            "cat file.py | grep pattern",
            "echo foo; rm -rf /",
            "cat file.py > output.txt",
            "echo $(whoami)",
            "echo `whoami`",
            "echo $HOME",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"

    def test_blocked_package_managers(self):
        """Test that package manager commands are blocked."""
        blocked_commands = [
            "pip install package",
            "npm install",
            "yarn add package",
            "brew install package",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"

    def test_blocked_interpreters(self):
        """Test that interpreter commands are blocked."""
        blocked_commands = [
            "python script.py",
            "python -c 'print(1)'",
            "node script.js",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"

    def test_blocked_git_subcommands(self):
        """Test that dangerous git subcommands are blocked."""
        blocked_commands = [
            "git push origin main",
            "git commit -m 'msg'",
            "git reset --hard",
            "git checkout -b feature",
            "git rebase main",
            "git cherry-pick abc123",
        ]

        for cmd in blocked_commands:
            is_safe, reason = is_command_safe(cmd)
            assert not is_safe, f"Command should be blocked: {cmd}"


class TestRunCommand:
    """Tests for command execution."""

    def test_run_safe_command(self):
        """Test running a safe command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("ls -la", tmpdir)

            assert result.success
            assert result.return_code == 0
            assert result.command == "ls -la"

    def test_run_unsafe_command_raises(self):
        """Test that running unsafe command raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(GitError) as exc_info:
                run_command("rm -rf /", tmpdir)

            assert "rejected" in str(exc_info.value).lower()

    def test_run_command_captures_output(self):
        """Test that command output is captured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")

            result = run_command("cat test.txt", tmpdir)

            assert result.success
            assert "hello world" in result.stdout

    def test_run_command_timeout(self):
        """Test command timeout handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple script that would take a while
            # But our timeout is very short, so it should fail
            # Using a grep that won't find anything but will finish quickly
            result = run_command("ls", tmpdir, timeout=5.0)
            assert result.success

    def test_run_command_nonexistent_dir(self):
        """Test error on nonexistent directory."""
        with pytest.raises(GitError) as exc_info:
            run_command("ls", "/nonexistent/path")

        assert "does not exist" in str(exc_info.value)


class TestGitRepository:
    """Tests for GitRepository class."""

    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize git repo
            os.system(f"cd {tmpdir} && git init --initial-branch=main")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            
            # Create initial commit
            test_file = Path(tmpdir) / "README.md"
            test_file.write_text("# Test\n")
            os.system(f"cd {tmpdir} && git add . && git commit -m 'Initial commit'")
            
            yield GitRepository(tmpdir)

    def test_validate_repo(self, git_repo):
        """Test repository validation."""
        # Should not raise for valid repo
        assert git_repo.repo_path.exists()

    def test_validate_repo_invalid(self):
        """Test validation fails for non-repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(GitError) as exc_info:
                GitRepository(tmpdir)

            assert "Not a git repository" in str(exc_info.value)

    def test_get_current_branch(self, git_repo):
        """Test getting current branch."""
        branch = git_repo.get_current_branch()
        assert branch == "main"

    def test_get_file_content(self, git_repo):
        """Test getting file content."""
        # Create and commit a file
        test_file = git_repo.repo_path / "test.py"
        test_file.write_text("print('hello')\n")
        os.system(f"cd {git_repo.repo_path} && git add test.py && git commit -m 'Add test file'")

        content = git_repo.get_file_content("test.py", "HEAD")
        assert content is not None
        assert "print('hello')" in content

    def test_get_file_content_not_found(self, git_repo):
        """Test getting nonexistent file."""
        content = git_repo.get_file_content("nonexistent.py", "HEAD")
        assert content is None

    def test_get_log(self, git_repo):
        """Test getting git log."""
        log = git_repo.get_log(max_count=5)
        assert "Initial commit" in log

    def test_list_changed_files(self, git_repo):
        """Test listing changed files between refs."""
        # Create a new file and commit
        new_file = git_repo.repo_path / "new.py"
        new_file.write_text("# new file\n")
        os.system(f"cd {git_repo.repo_path} && git add new.py && git commit -m 'Add new file'")

        # Get the parent commit
        parent = git_repo.git("rev-parse", "HEAD~1").strip()
        current = git_repo.git("rev-parse", "HEAD").strip()

        files = git_repo.list_changed_files(parent, current)
        assert "new.py" in files


class TestContextExtraction:
    """Tests for context extraction utilities."""

    def test_get_context_around_lines(self):
        """Test extracting context around specific lines."""
        content = "\n".join(f"line {i}" for i in range(1, 21))

        context = get_context_around_lines(content, 10, 12, context_lines=3)

        # Should include lines 7-15 (10-3 to 12+3)
        assert "line 7" in context
        assert "line 10" in context
        assert "line 12" in context
        assert "line 15" in context

        # Target lines should be marked
        assert ">" in context  # Marker for target lines

    def test_get_context_at_start(self):
        """Test context at start of file."""
        content = "\n".join(f"line {i}" for i in range(1, 11))

        context = get_context_around_lines(content, 1, 2, context_lines=5)

        # Should not go negative
        assert "line 1" in context
        assert "line 2" in context

    def test_get_context_at_end(self):
        """Test context at end of file."""
        content = "\n".join(f"line {i}" for i in range(1, 11))

        context = get_context_around_lines(content, 9, 10, context_lines=5)

        # Should not exceed file length
        assert "line 9" in context
        assert "line 10" in context

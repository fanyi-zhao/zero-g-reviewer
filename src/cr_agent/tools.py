"""Tool definitions for the Claude Agent."""

import json
import logging
from typing import Any

from .config import ReviewConfig
from .git_ops import GitError, GitRepository, is_command_safe, run_command
from .gitlab_client import GitLabClient, GitLabError

logger = logging.getLogger(__name__)


# Tool definitions for Claude Agent SDK
TOOL_DEFINITIONS = [
    {
        "name": "bash_tool",
        "description": """Run a safe shell command in the local repository.
        
ALLOWED commands:
- git (subcommands: diff, show, log, blame, ls-files, rev-parse, branch, status, fetch, remote, cat-file, rev-list, merge-base)
- cat, head, tail (reading files)
- grep, wc, find, ls, file (searching/inspecting)

BLOCKED: rm, mv, cp, curl, wget, ssh, pip, npm, python, and any command with shell operators (|, ;, &, >, $, `).

Use this tool to:
- Get file contents at specific refs: git show <ref>:<path>
- Get blame information: git blame <path>
- Get recent commits: git log -n 10 <path>
- Get diff between branches: git diff target...source
- Search for patterns: grep -r "pattern" <path>

Returns: JSON with stdout, stderr, return_code, and success boolean.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (must be in allowlist)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 30, max: 120)",
                    "default": 30,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "gitlab_api",
        "description": """Make a GET request to the GitLab API v4.

The base URL and authentication are handled automatically.
Provide the endpoint path starting with /.

Examples:
- Get project info: /projects/:id
- Get MR info: /projects/:id/merge_requests/:iid
- Get MR changes: /projects/:id/merge_requests/:iid/changes
- Get file content: /projects/:id/repository/files/:path/raw?ref=:ref

Returns: JSON response from the API or error details.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint path (e.g., /projects/123/merge_requests/1)",
                },
                "params": {
                    "type": "object",
                    "description": "Optional query parameters",
                    "additionalProperties": True,
                },
            },
            "required": ["endpoint"],
        },
    },
    {
        "name": "get_file_context",
        "description": """Get additional context for a specific file.

Retrieves:
- Full file content at head ref
- Git blame for specified line range (if provided)
- Recent commit history for the file

Use this for deeper analysis of specific files identified as needing more context.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to repository root",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line for blame (1-indexed, optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line for blame (1-indexed, optional)",
                },
                "ref": {
                    "type": "string",
                    "description": "Git ref to get content from (default: HEAD)",
                    "default": "HEAD",
                },
            },
            "required": ["file_path"],
        },
    },
]


class ToolExecutor:
    """Executes agent tools with proper context and safety checks."""

    def __init__(
        self,
        config: ReviewConfig,
        gitlab_client: GitLabClient,
        repo: GitRepository,
    ):
        self.config = config
        self.gitlab = gitlab_client
        self.repo = repo

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        try:
            if tool_name == "bash_tool":
                return self._execute_bash(tool_input)
            elif tool_name == "gitlab_api":
                return self._execute_gitlab_api(tool_input)
            elif tool_name == "get_file_context":
                return self._execute_get_file_context(tool_input)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {"error": str(e)}

    def _execute_bash(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a bash command."""
        command = params.get("command", "")
        timeout = min(params.get("timeout", 30), 120)  # Cap at 120s

        # Validate command safety
        is_safe, reason = is_command_safe(command)
        if not is_safe:
            return {
                "error": f"Command rejected: {reason}",
                "command": command,
                "success": False,
            }

        try:
            result = run_command(
                command=command,
                cwd=self.config.local_repo_path,
                timeout=timeout,
            )
            return {
                "command": result.command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.return_code,
                "success": result.success,
            }
        except GitError as e:
            return {
                "error": str(e),
                "command": command,
                "success": False,
            }

    def _execute_gitlab_api(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a GitLab API request."""
        endpoint = params.get("endpoint", "")
        query_params = params.get("params", {})

        if not endpoint:
            return {"error": "No endpoint provided"}

        try:
            # Use the client's internal method for flexibility
            result = self.gitlab._get(endpoint, params=query_params)
            return {"data": result, "success": True}
        except GitLabError as e:
            return {
                "error": str(e),
                "status_code": e.status_code,
                "success": False,
            }

    def _execute_get_file_context(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get comprehensive context for a file."""
        file_path = params.get("file_path", "")
        start_line = params.get("start_line")
        end_line = params.get("end_line")
        ref = params.get("ref", "HEAD")

        if not file_path:
            return {"error": "No file path provided"}

        context: dict[str, Any] = {
            "file_path": file_path,
            "ref": ref,
        }

        # Get file content
        try:
            content = self.repo.get_file_content(file_path, ref)
            if content:
                lines = content.split("\n")
                total_lines = len(lines)
                context["line_count"] = total_lines
                
                # Check for large files
                max_lines = params.get("max_lines", 2000)
                if total_lines > max_lines and not start_line:
                    context["content"] = "\n".join(lines[:max_lines])
                    context["truncated"] = True
                    context["warning"] = f"File truncated. Showing first {max_lines} of {total_lines} lines. Use start_line/end_line to view specific sections."
                else:
                    context["content"] = content
            else:
                context["content_error"] = "File not found at ref"
        except GitError as e:
            context["content_error"] = str(e)

        # Get blame if line range specified
        if start_line and end_line:
            try:
                blame = self.repo.get_blame(file_path, start_line, end_line, ref)
                context["blame"] = blame
            except GitError as e:
                context["blame_error"] = str(e)

        # Get recent commits
        try:
            log = self.repo.get_log(file_path, max_count=5)
            context["recent_commits"] = log
        except GitError as e:
            context["log_error"] = str(e)

        return context


def format_tool_result(result: dict[str, Any]) -> str:
    """Format a tool result for the LLM."""
    return json.dumps(result, indent=2, default=str)

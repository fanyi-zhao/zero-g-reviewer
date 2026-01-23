"""Data models for the CR Agent."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Finding severity levels."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


class Confidence(str, Enum):
    """Confidence levels for findings."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Recommendation(str, Enum):
    """Overall review recommendation."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


@dataclass
class MergeRequestInfo:
    """GitLab Merge Request metadata."""

    iid: int
    title: str
    description: str
    author: str
    state: str
    source_branch: str
    target_branch: str
    web_url: str
    created_at: str
    updated_at: str
    labels: list[str] = field(default_factory=list)
    pipeline_status: str | None = None
    has_conflicts: bool = False

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "MergeRequestInfo":
        """Create from GitLab API response."""
        return cls(
            iid=data["iid"],
            title=data["title"],
            description=data.get("description") or "",
            author=data.get("author", {}).get("username", "unknown"),
            state=data["state"],
            source_branch=data["source_branch"],
            target_branch=data["target_branch"],
            web_url=data["web_url"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            labels=data.get("labels", []),
            pipeline_status=data.get("head_pipeline", {}).get("status")
            if data.get("head_pipeline")
            else None,
            has_conflicts=data.get("has_conflicts", False),
        )


@dataclass
class DiffHunk:
    """A single hunk within a file diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str
    header: str = ""


@dataclass
class ChangedFile:
    """A file changed in the merge request."""

    path: str
    old_path: str
    new_file: bool
    deleted_file: bool
    renamed_file: bool
    diff: str
    hunks: list[DiffHunk] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "ChangedFile":
        """Create from GitLab API response."""
        diff_content = data.get("diff", "")
        hunks = parse_diff_hunks(diff_content) if diff_content else []

        return cls(
            path=data["new_path"],
            old_path=data["old_path"],
            new_file=data.get("new_file", False),
            deleted_file=data.get("deleted_file", False),
            renamed_file=data.get("renamed_file", False),
            diff=diff_content,
            hunks=hunks,
            is_binary="Binary files" in diff_content if diff_content else False,
        )

    @property
    def change_type(self) -> str:
        """Get human-readable change type."""
        if self.new_file:
            return "added"
        elif self.deleted_file:
            return "deleted"
        elif self.renamed_file:
            return "renamed"
        else:
            return "modified"

    @property
    def total_changes(self) -> int:
        """Count approximate number of changed lines."""
        if not self.diff:
            return 0
        lines = self.diff.split("\n")
        return sum(1 for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


@dataclass
class Commit:
    """A commit in the merge request."""

    sha: str
    short_sha: str
    title: str
    message: str
    author_name: str
    author_email: str
    authored_date: str

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Commit":
        """Create from GitLab API response."""
        return cls(
            sha=data["id"],
            short_sha=data["short_id"],
            title=data["title"],
            message=data.get("message", data["title"]),
            author_name=data["author_name"],
            author_email=data["author_email"],
            authored_date=data["authored_date"],
        )


@dataclass
class FileContext:
    """Additional context for a changed file."""

    path: str
    full_content: str | None = None
    blame_info: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)


@dataclass
class CodeSuggestion:
    """A code suggestion with GitLab suggestion block syntax."""

    file_path: str
    line_start: int
    line_end: int | None
    original_code: str
    suggested_code: str
    explanation: str


@dataclass
class Finding:
    """A single review finding."""

    severity: Severity
    title: str
    description: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    confidence: Confidence = Confidence.MEDIUM
    suggestion: CodeSuggestion | None = None
    category: str = "general"

    def to_markdown(self) -> str:
        """Render finding as markdown."""
        parts = []

        # Title with severity badge
        severity_emoji = {
            Severity.BLOCKER: "🔴",
            Severity.MAJOR: "🟠",
            Severity.MINOR: "🟡",
            Severity.NIT: "🔵",
        }
        emoji = severity_emoji.get(self.severity, "")

        location = ""
        if self.file_path:
            location = f" in `{self.file_path}`"
            if self.line_start:
                if self.line_end and self.line_end != self.line_start:
                    location += f" (L{self.line_start}-{self.line_end})"
                else:
                    location += f" (L{self.line_start})"

        parts.append(f"- {emoji} **{self.title}**{location}")

        # Confidence for blockers/majors
        if self.severity in (Severity.BLOCKER, Severity.MAJOR):
            parts.append(f"  - *Confidence: {self.confidence.value}*")

        # Description
        desc_lines = self.description.strip().split("\n")
        for line in desc_lines:
            parts.append(f"  {line}")

        # Suggestion block
        if self.suggestion:
            parts.append("")
            parts.append("  ```suggestion")
            parts.append(self.suggestion.suggested_code)
            parts.append("  ```")

        return "\n".join(parts)


@dataclass
class ReviewResult:
    """Complete review result."""

    recommendation: Recommendation
    summary: str
    risks: list[str]
    files_reviewed: list[str]
    findings: list[Finding]
    test_commands: list[str]
    checklist: list[str]

    def get_findings_by_severity(self, severity: Severity) -> list[Finding]:
        """Get findings filtered by severity."""
        return [f for f in self.findings if f.severity == severity]

    def to_gitlab_comment(self) -> str:
        """Render full review as GitLab comment markdown."""
        parts = []

        # Header
        parts.append("# 🔍 Code Review")
        parts.append("")

        # Summary section
        rec_text = {
            Recommendation.APPROVE: "✅ **Approve**",
            Recommendation.REQUEST_CHANGES: "⚠️ **Request Changes**",
            Recommendation.COMMENT: "💬 **Comment**",
        }
        parts.append("## Summary")
        parts.append("")
        parts.append(f"**Recommendation:** {rec_text.get(self.recommendation, self.recommendation.value)}")
        parts.append("")
        parts.append(self.summary)
        parts.append("")

        # Risks
        if self.risks:
            parts.append("**High-level Risks:**")
            for risk in self.risks:
                parts.append(f"- {risk}")
            parts.append("")

        # Files reviewed
        parts.append("**Files Reviewed:**")
        for file in self.files_reviewed[:20]:  # Cap display
            parts.append(f"- `{file}`")
        if len(self.files_reviewed) > 20:
            parts.append(f"- *...and {len(self.files_reviewed) - 20} more files*")
        parts.append("")

        # Key Findings
        parts.append("## Key Findings")
        parts.append("")

        for severity in [Severity.BLOCKER, Severity.MAJOR, Severity.MINOR, Severity.NIT]:
            findings = self.get_findings_by_severity(severity)
            if findings:
                parts.append(f"### {severity.value.title()}")
                parts.append("")
                for finding in findings:
                    parts.append(finding.to_markdown())
                    parts.append("")
                parts.append("")

        if not self.findings:
            parts.append("*No significant issues found.*")
            parts.append("")

        # Tests/Verification
        parts.append("## Tests / Verification")
        parts.append("")
        if self.test_commands:
            for cmd in self.test_commands:
                parts.append(f"```bash\n{cmd}\n```")
                parts.append("")
        else:
            parts.append("*No specific test commands recommended.*")
        parts.append("")

        # Checklist
        parts.append("## Pre-Merge Checklist")
        parts.append("")
        for item in self.checklist:
            parts.append(f"- [ ] {item}")
        parts.append("")

        # Footer
        parts.append("---")
        parts.append("*Generated by Claude CR Agent*")

        return "\n".join(parts)


def parse_diff_hunks(diff_content: str) -> list[DiffHunk]:
    """Parse diff content into hunks."""
    import re

    hunks: list[DiffHunk] = []
    hunk_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

    lines = diff_content.split("\n")
    current_hunk: DiffHunk | None = None
    hunk_lines: list[str] = []

    for line in lines:
        match = hunk_pattern.match(line)
        if match:
            # Save previous hunk
            if current_hunk is not None:
                current_hunk.content = "\n".join(hunk_lines)
                hunks.append(current_hunk)

            # Start new hunk
            old_start = int(match.group(1))
            old_lines = int(match.group(2)) if match.group(2) else 1
            new_start = int(match.group(3))
            new_lines = int(match.group(4)) if match.group(4) else 1
            header = match.group(5).strip()

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                content="",
                header=header,
            )
            hunk_lines = []
        elif current_hunk is not None:
            hunk_lines.append(line)

    # Don't forget last hunk
    if current_hunk is not None:
        current_hunk.content = "\n".join(hunk_lines)
        hunks.append(current_hunk)

    return hunks

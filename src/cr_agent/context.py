"""Context management for diff chunking and prioritization."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ChangedFile, DiffHunk

logger = logging.getLogger(__name__)


# File patterns for prioritization
CRITICAL_PATTERNS = [
    # Security-related
    r"(auth|security|crypto|password|secret|token|key|credential)",
    r"(permission|access|role|policy)",
    # Infrastructure
    r"(dockerfile|docker-compose|\.ya?ml$|terraform|ansible)",
    r"(nginx|apache|caddy|\.conf$)",
    # CI/CD
    r"(\.github/|\.gitlab-ci|jenkinsfile|circleci|\.drone)",
    # Dependencies
    r"(package\.json|package-lock|yarn\.lock|requirements|pipfile|go\.mod|cargo\.toml)",
    r"(pyproject\.toml|setup\.py|setup\.cfg|gemfile)",
    # Database
    r"(migration|schema|\.sql$|alembic)",
    # Build config
    r"(webpack|vite|rollup|babel|tsconfig|makefile|cmake)",
]

EXTENSION_PRIORITY = {
    # High priority
    ".py": 3,
    ".go": 3,
    ".rs": 3,
    ".java": 3,
    ".ts": 3,
    ".tsx": 3,
    ".js": 2,
    ".jsx": 2,
    ".rb": 2,
    ".php": 2,
    ".cs": 2,
    ".c": 3,
    ".cpp": 3,
    ".h": 3,
    ".hpp": 3,
    # Medium priority
    ".sql": 2,
    ".graphql": 2,
    ".proto": 2,
    # Config files
    ".yaml": 2,
    ".yml": 2,
    ".json": 1,
    ".toml": 2,
    ".ini": 1,
    ".env": 3,  # High because of secrets risk
    # Low priority
    ".md": 0,
    ".txt": 0,
    ".css": 1,
    ".scss": 1,
    ".less": 1,
    ".html": 1,
    ".svg": 0,
}


@dataclass
class FileChunk:
    """A chunk of file diff for processing."""

    file: ChangedFile
    chunk_index: int
    total_chunks: int
    content: str
    hunks: list[DiffHunk]
    priority_score: float
    char_count: int


@dataclass
class ReviewPlan:
    """Plan for reviewing changes."""

    total_files: int
    total_chars: int
    files_to_review: list[ChangedFile]
    skipped_files: list[str] = field(default_factory=list)
    skip_reasons: dict[str, str] = field(default_factory=dict)
    priority_order: list[str] = field(default_factory=list)
    estimated_tokens: int = 0

    def summary(self) -> str:
        """Get a summary of the review plan."""
        lines = [
            f"Review Plan: {len(self.files_to_review)}/{self.total_files} files",
            f"Total diff size: ~{self.total_chars:,} chars ({self.estimated_tokens:,} est. tokens)",
        ]

        if self.skipped_files:
            lines.append(f"Skipped: {len(self.skipped_files)} files")
            for path in self.skipped_files[:5]:
                reason = self.skip_reasons.get(path, "unknown")
                lines.append(f"  - {path}: {reason}")
            if len(self.skipped_files) > 5:
                lines.append(f"  ... and {len(self.skipped_files) - 5} more")

        return "\n".join(lines)


def calculate_file_priority(file: ChangedFile) -> float:
    """
    Calculate priority score for a file.

    Higher score = higher priority for review.
    """
    score = 0.0
    path_lower = file.path.lower()

    # Check critical patterns
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, path_lower, re.IGNORECASE):
            score += 10.0
            break

    # Extension-based priority
    ext = Path(file.path).suffix.lower()
    score += EXTENSION_PRIORITY.get(ext, 1)

    # Change type priority
    if file.new_file:
        score += 2.0  # New files are important
    elif file.deleted_file:
        score += 1.0

    # Size-based (moderate changes are often most important)
    change_count = file.total_changes
    if 10 <= change_count <= 100:
        score += 3.0  # Sweet spot for meaningful changes
    elif change_count > 100:
        score += 1.0  # Large changes need review but may be refactoring
    elif change_count > 0:
        score += 0.5  # Small changes

    # Penalize generated/vendored files
    if any(p in path_lower for p in ["vendor/", "node_modules/", "dist/", "build/", "__pycache__/"]):
        score -= 20.0
    if any(p in path_lower for p in [".min.", ".bundle.", ".generated.", ".lock"]):
        score -= 10.0

    # Boost for test files (important but slightly lower than source)
    if any(p in path_lower for p in ["test", "spec", "_test.", ".test."]):
        score += 1.5

    return score


def should_skip_file(file: ChangedFile) -> tuple[bool, str]:
    """
    Determine if a file should be skipped from review.

    Returns (should_skip, reason).
    """
    path_lower = file.path.lower()

    # Skip binary files
    if file.is_binary:
        return True, "binary file"

    # Skip vendored/generated files
    skip_patterns = [
        ("vendor/", "vendored dependency"),
        ("node_modules/", "node_modules"),
        ("dist/", "build output"),
        ("build/", "build output"),
        ("__pycache__/", "Python cache"),
        (".min.", "minified file"),
        (".bundle.", "bundled file"),
        (".generated.", "generated file"),
        ("package-lock.json", "lock file"),
        ("yarn.lock", "lock file"),
        ("poetry.lock", "lock file"),
        ("Cargo.lock", "lock file"),
        ("go.sum", "lock file"),
    ]

    for pattern, reason in skip_patterns:
        if pattern in path_lower:
            return True, reason

    # Skip very large diffs (likely generated)
    if file.total_changes > 1000:
        return True, "diff too large (>1000 lines)"

    # Skip empty diffs
    if not file.diff or not file.diff.strip():
        return True, "empty diff"

    return False, ""


def create_review_plan(
    files: list[ChangedFile],
    max_files: int = 50,
    max_chars: int = 100000,
) -> ReviewPlan:
    """
    Create a prioritized review plan from changed files.

    Args:
        files: List of changed files from MR
        max_files: Maximum number of files to include
        max_chars: Maximum total characters of diff to include

    Returns:
        ReviewPlan with prioritized files and skip information
    """
    plan = ReviewPlan(
        total_files=len(files),
        total_chars=0,
        files_to_review=[],
    )

    # First pass: filter and calculate priority
    scored_files: list[tuple[ChangedFile, float]] = []

    for file in files:
        skip, reason = should_skip_file(file)
        if skip:
            plan.skipped_files.append(file.path)
            plan.skip_reasons[file.path] = reason
            continue

        priority = calculate_file_priority(file)
        scored_files.append((file, priority))

    # Sort by priority (descending)
    scored_files.sort(key=lambda x: x[1], reverse=True)

    # Second pass: select files within limits
    total_chars = 0

    for file, priority in scored_files:
        diff_chars = len(file.diff) if file.diff else 0

        # Check limits
        if len(plan.files_to_review) >= max_files:
            plan.skipped_files.append(file.path)
            plan.skip_reasons[file.path] = "max files limit reached"
            continue

        if total_chars + diff_chars > max_chars and plan.files_to_review:
            plan.skipped_files.append(file.path)
            plan.skip_reasons[file.path] = "max chars limit reached"
            continue

        plan.files_to_review.append(file)
        plan.priority_order.append(file.path)
        total_chars += diff_chars

    plan.total_chars = total_chars
    plan.estimated_tokens = total_chars // 4  # Rough estimate

    return plan


def chunk_diff(
    file: ChangedFile,
    max_chunk_chars: int = 10000,
) -> list[FileChunk]:
    """
    Split a file diff into manageable chunks.

    Args:
        file: The changed file
        max_chunk_chars: Maximum characters per chunk

    Returns:
        List of FileChunk objects
    """
    if not file.diff or not file.hunks:
        return [
            FileChunk(
                file=file,
                chunk_index=0,
                total_chunks=1,
                content=file.diff or "",
                hunks=file.hunks,
                priority_score=calculate_file_priority(file),
                char_count=len(file.diff) if file.diff else 0,
            )
        ]

    # If diff fits in one chunk, return as-is
    if len(file.diff) <= max_chunk_chars:
        return [
            FileChunk(
                file=file,
                chunk_index=0,
                total_chunks=1,
                content=file.diff,
                hunks=file.hunks,
                priority_score=calculate_file_priority(file),
                char_count=len(file.diff),
            )
        ]

    # Split by hunks
    chunks: list[FileChunk] = []
    current_hunks: list[DiffHunk] = []
    current_chars = 0

    for hunk in file.hunks:
        hunk_chars = len(hunk.content)

        # If adding this hunk would exceed limit, create new chunk
        if current_hunks and current_chars + hunk_chars > max_chunk_chars:
            chunk_content = _format_hunks(current_hunks)
            chunks.append(
                FileChunk(
                    file=file,
                    chunk_index=len(chunks),
                    total_chunks=0,  # Will update later
                    content=chunk_content,
                    hunks=current_hunks.copy(),
                    priority_score=calculate_file_priority(file),
                    char_count=len(chunk_content),
                )
            )
            current_hunks = []
            current_chars = 0

        current_hunks.append(hunk)
        current_chars += hunk_chars

    # Don't forget the last chunk
    if current_hunks:
        chunk_content = _format_hunks(current_hunks)
        chunks.append(
            FileChunk(
                file=file,
                chunk_index=len(chunks),
                total_chunks=0,
                content=chunk_content,
                hunks=current_hunks,
                priority_score=calculate_file_priority(file),
                char_count=len(chunk_content),
            )
        )

    # Update total_chunks
    total = len(chunks)
    for chunk in chunks:
        chunk.total_chunks = total

    return chunks


def _format_hunks(hunks: list[DiffHunk]) -> str:
    """Format hunks as diff text."""
    parts = []
    for hunk in hunks:
        header = f"@@ -{hunk.old_start},{hunk.old_lines} +{hunk.new_start},{hunk.new_lines} @@"
        if hunk.header:
            header += f" {hunk.header}"
        parts.append(header)
        parts.append(hunk.content)
    return "\n".join(parts)


def summarize_changes(files: list[ChangedFile]) -> str:
    """
    Create a summary of all changes for initial context.

    Args:
        files: List of changed files

    Returns:
        Markdown summary of changes
    """
    lines = ["## Changed Files Summary\n"]

    # Group by directory
    by_dir: dict[str, list[ChangedFile]] = {}
    for f in files:
        dir_path = str(Path(f.path).parent)
        if dir_path not in by_dir:
            by_dir[dir_path] = []
        by_dir[dir_path].append(f)

    # Sort directories
    for dir_path in sorted(by_dir.keys()):
        dir_files = by_dir[dir_path]
        lines.append(f"### `{dir_path}/`")

        for f in sorted(dir_files, key=lambda x: x.path):
            name = Path(f.path).name
            change_type = f.change_type
            changes = f.total_changes

            emoji = {"added": "🆕", "deleted": "🗑️", "renamed": "📝", "modified": "✏️"}.get(
                change_type, "📄"
            )

            lines.append(f"- {emoji} `{name}` ({change_type}, ~{changes} lines)")

        lines.append("")

    # Statistics
    total_added = sum(1 for f in files if f.new_file)
    total_deleted = sum(1 for f in files if f.deleted_file)
    total_modified = sum(1 for f in files if not f.new_file and not f.deleted_file)
    total_changes = sum(f.total_changes for f in files)

    lines.append("### Statistics")
    lines.append(f"- **Total files**: {len(files)}")
    lines.append(f"- **Added**: {total_added}")
    lines.append(f"- **Deleted**: {total_deleted}")
    lines.append(f"- **Modified**: {total_modified}")
    lines.append(f"- **Total line changes**: ~{total_changes}")

    return "\n".join(lines)


def identify_hotspots(files: list[ChangedFile]) -> list[tuple[str, str]]:
    """
    Identify potential hotspots that need deeper review.

    Returns list of (file_path, reason) tuples.
    """
    hotspots: list[tuple[str, str]] = []

    for file in files:
        path_lower = file.path.lower()

        # Check for security-sensitive files
        if any(p in path_lower for p in ["auth", "security", "crypto", "password", "secret"]):
            hotspots.append((file.path, "security-sensitive file"))

        # Check for API/interface changes
        if any(p in path_lower for p in ["api", "interface", "proto", "schema", "graphql"]):
            hotspots.append((file.path, "API/interface change"))

        # Check for database changes
        if any(p in path_lower for p in ["migration", "schema", ".sql"]):
            hotspots.append((file.path, "database schema change"))

        # Check for config changes
        if file.path.endswith((".yaml", ".yml", ".json", ".toml", ".env")):
            if "config" in path_lower or "settings" in path_lower:
                hotspots.append((file.path, "configuration change"))

        # Check diff content for concerning patterns
        if file.diff:
            diff_lower = file.diff.lower()
            if "todo" in diff_lower or "fixme" in diff_lower or "hack" in diff_lower:
                hotspots.append((file.path, "contains TODO/FIXME/HACK"))
            if "password" in diff_lower or "secret" in diff_lower or "api_key" in diff_lower:
                hotspots.append((file.path, "potential secret in diff"))

    return hotspots

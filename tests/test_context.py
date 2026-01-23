"""Tests for context management and diff chunking."""

import pytest

from cr_agent.context import (
    calculate_file_priority,
    chunk_diff,
    create_review_plan,
    identify_hotspots,
    should_skip_file,
    summarize_changes,
)
from cr_agent.models import ChangedFile, DiffHunk


@pytest.fixture
def sample_changed_files():
    """Create sample changed files for testing."""
    return [
        ChangedFile(
            path="src/auth/login.py",
            old_path="src/auth/login.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,10 +1,15 @@\n+# Security fix\n def login():\n     pass",
        ),
        ChangedFile(
            path="src/api/endpoints.py",
            old_path="src/api/endpoints.py",
            new_file=True,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -0,0 +1,50 @@\n+" + "\n+".join(["line"] * 50),
        ),
        ChangedFile(
            path="README.md",
            old_path="README.md",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,3 +1,5 @@\n+# Updated docs\n",
        ),
        ChangedFile(
            path="node_modules/package/index.js",
            old_path="node_modules/package/index.js",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,3 +1,5 @@\n+change\n",
        ),
        ChangedFile(
            path="tests/test_login.py",
            old_path="tests/test_login.py",
            new_file=True,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -0,0 +1,30 @@\n+" + "\n+".join(["test line"] * 30),
        ),
    ]


class TestFilePriority:
    """Tests for file priority calculation."""

    def test_security_files_high_priority(self):
        """Test that security-related files get high priority."""
        auth_file = ChangedFile(
            path="src/auth/authenticate.py",
            old_path="src/auth/authenticate.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,5 +1,10 @@\n" + "+\n" * 20,
        )

        regular_file = ChangedFile(
            path="src/utils/helpers.py",
            old_path="src/utils/helpers.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,5 +1,10 @@\n" + "+\n" * 20,
        )

        assert calculate_file_priority(auth_file) > calculate_file_priority(regular_file)

    def test_new_files_higher_priority(self):
        """Test that new files get higher priority."""
        new_file = ChangedFile(
            path="src/feature.py",
            old_path="src/feature.py",
            new_file=True,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -0,0 +1,10 @@\n" + "+\n" * 10,
        )

        modified_file = ChangedFile(
            path="src/feature2.py",
            old_path="src/feature2.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,5 +1,10 @@\n" + "+\n" * 10,
        )

        assert calculate_file_priority(new_file) > calculate_file_priority(modified_file)

    def test_vendored_files_low_priority(self):
        """Test that vendored files get negative priority."""
        vendored = ChangedFile(
            path="vendor/pkg/main.go",
            old_path="vendor/pkg/main.go",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,5 +1,10 @@\n" + "+\n" * 20,
        )

        priority = calculate_file_priority(vendored)
        assert priority < 0


class TestShouldSkipFile:
    """Tests for file skip logic."""

    def test_skip_binary_files(self):
        """Test that binary files are skipped."""
        binary = ChangedFile(
            path="image.png",
            old_path="image.png",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="Binary files differ",
            is_binary=True,
        )

        skip, reason = should_skip_file(binary)
        assert skip is True
        assert "binary" in reason.lower()

    def test_skip_node_modules(self):
        """Test that node_modules are skipped."""
        node_file = ChangedFile(
            path="node_modules/pkg/index.js",
            old_path="node_modules/pkg/index.js",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,3 +1,5 @@\n+change",
        )

        skip, reason = should_skip_file(node_file)
        assert skip is True
        assert "node_modules" in reason

    def test_skip_lock_files(self):
        """Test that lock files are skipped."""
        lock_file = ChangedFile(
            path="package-lock.json",
            old_path="package-lock.json",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,1000 +1,1200 @@\n" + "+\n" * 500,
        )

        skip, reason = should_skip_file(lock_file)
        assert skip is True
        assert "lock" in reason.lower()

    def test_dont_skip_normal_files(self):
        """Test that normal source files are not skipped."""
        source_file = ChangedFile(
            path="src/main.py",
            old_path="src/main.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,10 +1,15 @@\n" + "+\n" * 10,
        )

        skip, _ = should_skip_file(source_file)
        assert skip is False


class TestReviewPlan:
    """Tests for review plan creation."""

    def test_creates_plan_with_priorities(self, sample_changed_files):
        """Test that plan prioritizes correctly."""
        plan = create_review_plan(sample_changed_files, max_files=10, max_chars=100000)

        assert plan.total_files == 5

        # node_modules should be skipped
        assert "node_modules/package/index.js" in plan.skipped_files

        # Auth file should be included
        auth_included = any("auth" in f.path for f in plan.files_to_review)
        assert auth_included

    def test_respects_max_files(self, sample_changed_files):
        """Test that max_files limit is respected."""
        plan = create_review_plan(sample_changed_files, max_files=2, max_chars=100000)

        assert len(plan.files_to_review) <= 2

    def test_respects_max_chars(self):
        """Test that max_chars limit is respected."""
        # Create files with known diff sizes
        files = [
            ChangedFile(
                path=f"file{i}.py",
                old_path=f"file{i}.py",
                new_file=False,
                deleted_file=False,
                renamed_file=False,
                diff="x" * 1000,  # 1000 chars each
            )
            for i in range(10)
        ]

        plan = create_review_plan(files, max_files=100, max_chars=3000)

        # Should include at most 3 files (3000 chars limit, 1000 per file)
        assert len(plan.files_to_review) <= 4  # Some buffer for first file

    def test_plan_summary(self, sample_changed_files):
        """Test plan summary generation."""
        plan = create_review_plan(sample_changed_files)

        summary = plan.summary()
        assert "Review Plan" in summary
        assert "files" in summary.lower()


class TestDiffChunking:
    """Tests for diff chunking."""

    def test_small_diff_single_chunk(self):
        """Test that small diffs remain in a single chunk."""
        file = ChangedFile(
            path="small.py",
            old_path="small.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="@@ -1,5 +1,10 @@\n" + "line\n" * 10,
            hunks=[
                DiffHunk(
                    old_start=1,
                    old_lines=5,
                    new_start=1,
                    new_lines=10,
                    content="line\n" * 10,
                )
            ],
        )

        chunks = chunk_diff(file, max_chunk_chars=10000)

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_large_diff_multiple_chunks(self):
        """Test that large diffs are split into chunks."""
        # Create a file with multiple hunks
        hunks = [
            DiffHunk(
                old_start=i * 100,
                old_lines=10,
                new_start=i * 100,
                new_lines=15,
                content="x" * 5000,
            )
            for i in range(5)
        ]

        file = ChangedFile(
            path="large.py",
            old_path="large.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="x" * 25000,
            hunks=hunks,
        )

        chunks = chunk_diff(file, max_chunk_chars=10000)

        assert len(chunks) > 1
        # All chunks should reference the same file
        assert all(c.file.path == "large.py" for c in chunks)
        # Chunk indices should be sequential
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
            assert chunk.total_chunks == len(chunks)


class TestHotspotIdentification:
    """Tests for hotspot identification."""

    def test_identifies_security_files(self, sample_changed_files):
        """Test identification of security-related files."""
        hotspots = identify_hotspots(sample_changed_files)

        # Auth file should be flagged
        auth_hotspot = any("auth" in h[0] for h in hotspots)
        assert auth_hotspot

    def test_identifies_api_changes(self, sample_changed_files):
        """Test identification of API changes."""
        hotspots = identify_hotspots(sample_changed_files)

        # API file should be flagged
        api_hotspot = any("api" in h[0] for h in hotspots)
        assert api_hotspot


class TestSummarizeChanges:
    """Tests for change summarization."""

    def test_summary_includes_all_files(self, sample_changed_files):
        """Test that summary includes all reviewed files."""
        summary = summarize_changes(sample_changed_files)

        assert "src/auth/login.py" in summary or "login.py" in summary
        assert "README" in summary
        assert "Statistics" in summary

    def test_summary_shows_change_types(self, sample_changed_files):
        """Test that summary shows change types."""
        summary = summarize_changes(sample_changed_files)

        # Should indicate new files
        assert "added" in summary.lower() or "🆕" in summary

    def test_summary_shows_statistics(self, sample_changed_files):
        """Test that summary includes statistics."""
        summary = summarize_changes(sample_changed_files)

        assert "Total files" in summary
        assert "Added" in summary
        assert "Modified" in summary

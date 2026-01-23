"""Tests for the GitLab client."""

import pytest
import respx
from httpx import Response

from cr_agent.gitlab_client import GitLabClient, GitLabError
from cr_agent.models import MergeRequestInfo, ChangedFile, Commit


@pytest.fixture
def gitlab_client():
    """Create a GitLab client for testing."""
    return GitLabClient(
        base_url="https://gitlab.example.com",
        token="test-token",
        project_id="123",
    )


@pytest.fixture
def mock_mr_response():
    """Mock MR API response."""
    return {
        "iid": 42,
        "title": "Add new feature",
        "description": "This MR adds a new feature to the system.",
        "author": {"username": "developer"},
        "state": "opened",
        "source_branch": "feature/new-feature",
        "target_branch": "main",
        "web_url": "https://gitlab.example.com/project/-/merge_requests/42",
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T12:00:00Z",
        "labels": ["enhancement", "needs-review"],
        "head_pipeline": {"status": "success"},
        "has_conflicts": False,
        "diff_refs": {
            "base_sha": "abc123",
            "head_sha": "def456",
            "start_sha": "abc123",
        },
    }


@pytest.fixture
def mock_changes_response():
    """Mock MR changes API response."""
    return {
        "changes": [
            {
                "old_path": "src/main.py",
                "new_path": "src/main.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": """@@ -10,6 +10,8 @@ def main():
    print("Hello")
+    # New feature
+    do_something()
    return 0
""",
            },
            {
                "old_path": "src/utils.py",
                "new_path": "src/utils.py",
                "new_file": True,
                "deleted_file": False,
                "renamed_file": False,
                "diff": """@@ -0,0 +1,5 @@
+def do_something():
+    '''Do something useful.'''
+    pass
""",
            },
        ]
    }


@pytest.fixture
def mock_commits_response():
    """Mock MR commits API response."""
    return [
        {
            "id": "abc123def456",
            "short_id": "abc123d",
            "title": "Add new feature",
            "message": "Add new feature\n\nThis adds the do_something function.",
            "author_name": "Developer",
            "author_email": "dev@example.com",
            "authored_date": "2024-01-15T10:00:00Z",
        },
        {
            "id": "789xyz",
            "short_id": "789xyz",
            "title": "Fix typo",
            "message": "Fix typo",
            "author_name": "Developer",
            "author_email": "dev@example.com",
            "authored_date": "2024-01-15T11:00:00Z",
        },
    ]


class TestGitLabClient:
    """Tests for GitLabClient."""

    @respx.mock
    def test_get_merge_request(self, gitlab_client, mock_mr_response):
        """Test fetching MR metadata."""
        respx.get("https://gitlab.example.com/api/v4/projects/123/merge_requests/42").mock(
            return_value=Response(200, json=mock_mr_response)
        )

        mr = gitlab_client.get_merge_request(42)

        assert isinstance(mr, MergeRequestInfo)
        assert mr.iid == 42
        assert mr.title == "Add new feature"
        assert mr.author == "developer"
        assert mr.source_branch == "feature/new-feature"
        assert mr.target_branch == "main"
        assert mr.pipeline_status == "success"
        assert mr.has_conflicts is False

    @respx.mock
    def test_get_merge_request_changes(self, gitlab_client, mock_changes_response):
        """Test fetching MR changes."""
        respx.get("https://gitlab.example.com/api/v4/projects/123/merge_requests/42/changes").mock(
            return_value=Response(200, json=mock_changes_response)
        )

        changes = gitlab_client.get_merge_request_changes(42)

        assert len(changes) == 2
        assert all(isinstance(c, ChangedFile) for c in changes)
        
        # Check first file
        main_py = changes[0]
        assert main_py.path == "src/main.py"
        assert main_py.new_file is False
        assert main_py.change_type == "modified"
        
        # Check new file
        utils_py = changes[1]
        assert utils_py.path == "src/utils.py"
        assert utils_py.new_file is True
        assert utils_py.change_type == "added"

    @respx.mock
    def test_get_merge_request_commits(self, gitlab_client, mock_commits_response):
        """Test fetching MR commits."""
        respx.get("https://gitlab.example.com/api/v4/projects/123/merge_requests/42/commits").mock(
            return_value=Response(200, json=mock_commits_response)
        )

        commits = gitlab_client.get_merge_request_commits(42)

        assert len(commits) == 2
        assert all(isinstance(c, Commit) for c in commits)
        assert commits[0].title == "Add new feature"
        assert commits[0].short_sha == "abc123d"

    @respx.mock
    def test_api_error_handling(self, gitlab_client):
        """Test API error handling."""
        respx.get("https://gitlab.example.com/api/v4/projects/123/merge_requests/999").mock(
            return_value=Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(GitLabError) as exc_info:
            gitlab_client.get_merge_request(999)

        assert exc_info.value.status_code == 404

    @respx.mock
    def test_post_mr_note(self, gitlab_client):
        """Test posting a note to MR."""
        respx.post("https://gitlab.example.com/api/v4/projects/123/merge_requests/42/notes").mock(
            return_value=Response(201, json={"id": 1, "body": "Test comment"})
        )

        result = gitlab_client.post_mr_note(42, "Test comment")

        assert result["id"] == 1
        assert result["body"] == "Test comment"

    def test_project_path_encoding(self):
        """Test URL encoding of project paths."""
        client = GitLabClient(
            base_url="https://gitlab.example.com",
            token="test",
            project_id="namespace/sub-group/project",
        )

        assert client.project_path == "namespace%2Fsub-group%2Fproject"

    def test_project_id_numeric(self):
        """Test numeric project IDs are used as-is."""
        client = GitLabClient(
            base_url="https://gitlab.example.com",
            token="test",
            project_id="12345",
        )

        assert client.project_path == "12345"


class TestMergeRequestInfo:
    """Tests for MergeRequestInfo model."""

    def test_from_api_response(self, mock_mr_response):
        """Test creating MR info from API response."""
        mr = MergeRequestInfo.from_api_response(mock_mr_response)

        assert mr.iid == 42
        assert mr.title == "Add new feature"
        assert mr.description == "This MR adds a new feature to the system."
        assert mr.author == "developer"
        assert mr.source_branch == "feature/new-feature"
        assert mr.target_branch == "main"
        assert "enhancement" in mr.labels
        assert mr.pipeline_status == "success"

    def test_missing_optional_fields(self):
        """Test handling of missing optional fields."""
        minimal_response = {
            "iid": 1,
            "title": "Test",
            "state": "opened",
            "source_branch": "test",
            "target_branch": "main",
            "web_url": "http://example.com",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }

        mr = MergeRequestInfo.from_api_response(minimal_response)

        assert mr.description == ""
        assert mr.author == "unknown"
        assert mr.labels == []
        assert mr.pipeline_status is None


class TestChangedFile:
    """Tests for ChangedFile model."""

    def test_from_api_response(self):
        """Test creating ChangedFile from API response."""
        response = {
            "old_path": "old.py",
            "new_path": "new.py",
            "new_file": False,
            "deleted_file": False,
            "renamed_file": True,
            "diff": "@@ -1,3 +1,4 @@\n+# New line\n def foo():\n     pass",
        }

        file = ChangedFile.from_api_response(response)

        assert file.path == "new.py"
        assert file.old_path == "old.py"
        assert file.renamed_file is True
        assert file.change_type == "renamed"
        assert len(file.hunks) == 1

    def test_change_type_detection(self):
        """Test change type detection."""
        new_file = ChangedFile(
            path="new.py",
            old_path="new.py",
            new_file=True,
            deleted_file=False,
            renamed_file=False,
            diff="",
        )
        assert new_file.change_type == "added"

        deleted_file = ChangedFile(
            path="old.py",
            old_path="old.py",
            new_file=False,
            deleted_file=True,
            renamed_file=False,
            diff="",
        )
        assert deleted_file.change_type == "deleted"

    def test_total_changes_count(self):
        """Test counting changed lines."""
        file = ChangedFile(
            path="test.py",
            old_path="test.py",
            new_file=False,
            deleted_file=False,
            renamed_file=False,
            diff="""@@ -1,3 +1,4 @@
+# Added line
 def foo():
-    pass
+    return True
""",
        )

        # Should count +/- lines but not @@ or --- or +++
        assert file.total_changes == 3

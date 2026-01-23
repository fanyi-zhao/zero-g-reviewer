"""GitLab API client for MR operations."""

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .models import ChangedFile, Commit, MergeRequestInfo

logger = logging.getLogger(__name__)


class GitLabError(Exception):
    """GitLab API error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GitLabClient:
    """Client for GitLab REST API v4."""

    def __init__(
        self,
        base_url: str,
        token: str,
        project_id: str,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self._project_id_encoded: str | None = None
        self.timeout = timeout

        self._client = httpx.Client(
            base_url=f"{self.base_url}/api/v4",
            headers={
                "PRIVATE-TOKEN": token,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "GitLabClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def project_path(self) -> str:
        """Get URL-encoded project path."""
        if self._project_id_encoded is None:
            # If it's numeric, use as-is; otherwise URL-encode the path
            if self.project_id.isdigit():
                self._project_id_encoded = self.project_id
            else:
                self._project_id_encoded = quote(self.project_id, safe="")
        return self._project_id_encoded

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make an API request with error handling."""
        try:
            response = self._client.request(
                method=method,
                url=endpoint,
                params=params,
                json=json,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            raise GitLabError(
                f"GitLab API request failed: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            logger.error(f"GitLab request error: {e}")
            raise GitLabError(f"GitLab API request failed: {e}") from e

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request."""
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, json: dict[str, Any] | None = None) -> Any:
        """Make a POST request."""
        return self._request("POST", endpoint, json=json)

    def _paginate(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_items: int | None = None,
    ) -> list[Any]:
        """Paginate through API results."""
        params = params or {}
        params.setdefault("per_page", 100)
        params.setdefault("page", 1)

        results: list[Any] = []

        while True:
            try:
                response = self._client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()

                if not data:
                    break

                results.extend(data)

                if max_items and len(results) >= max_items:
                    results = results[:max_items]
                    break

                # Check for next page
                next_page = response.headers.get("x-next-page")
                if not next_page:
                    break

                params["page"] = int(next_page)

            except httpx.HTTPError as e:
                logger.error(f"Pagination error: {e}")
                break

        return results

    def resolve_project_id(self) -> int:
        """Resolve project path to numeric ID if needed."""
        if self.project_id.isdigit():
            return int(self.project_id)

        # Fetch project info to get numeric ID
        data = self._get(f"/projects/{self.project_path}")
        return data["id"]

    def get_merge_request(self, mr_iid: int) -> MergeRequestInfo:
        """Fetch MR metadata."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}"
        data = self._get(endpoint)
        return MergeRequestInfo.from_api_response(data)

    def get_merge_request_changes(
        self,
        mr_iid: int,
        max_files: int | None = None,
    ) -> list[ChangedFile]:
        """Fetch MR changes (diffs)."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}/changes"
        params = {"access_raw_diffs": True}
        data = self._get(endpoint, params=params)

        changes = data.get("changes", [])
        if max_files:
            changes = changes[:max_files]

        return [ChangedFile.from_api_response(c) for c in changes]

    def get_merge_request_commits(
        self,
        mr_iid: int,
        max_commits: int = 50,
    ) -> list[Commit]:
        """Fetch MR commits."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}/commits"
        data = self._paginate(endpoint, max_items=max_commits)
        return [Commit.from_api_response(c) for c in data]

    def get_merge_request_discussions(
        self,
        mr_iid: int,
        max_discussions: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch MR discussions/notes."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}/discussions"
        return self._paginate(endpoint, max_items=max_discussions)

    def get_file_content(
        self,
        file_path: str,
        ref: str = "HEAD",
    ) -> str | None:
        """Fetch file content from repository."""
        encoded_path = quote(file_path, safe="")
        endpoint = f"/projects/{self.project_path}/repository/files/{encoded_path}/raw"
        try:
            response = self._client.get(endpoint, params={"ref": ref})
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"File not found: {file_path} at ref {ref}")
                return None
            raise

    def get_pipeline_status(self, mr_iid: int) -> dict[str, Any] | None:
        """Get pipeline status for MR."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}/pipelines"
        try:
            data = self._get(endpoint)
            if data:
                return data[0]  # Most recent pipeline
        except GitLabError:
            logger.debug("Could not fetch pipeline status")
        return None

    def post_mr_note(self, mr_iid: int, body: str) -> dict[str, Any]:
        """Post a note/comment to the MR."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}/notes"
        return self._post(endpoint, json={"body": body})

    def get_diff_refs(self, mr_iid: int) -> dict[str, str]:
        """Get base/head/start SHA refs for the MR."""
        endpoint = f"/projects/{self.project_path}/merge_requests/{mr_iid}"
        data = self._get(endpoint)
        diff_refs = data.get("diff_refs", {})
        return {
            "base_sha": diff_refs.get("base_sha", ""),
            "head_sha": diff_refs.get("head_sha", ""),
            "start_sha": diff_refs.get("start_sha", ""),
        }

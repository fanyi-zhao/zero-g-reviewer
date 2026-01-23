"""Configuration management for the CR Agent."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="CR_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GitLab settings
    gitlab_base_url: str = Field(
        default="https://gitlab.com",
        description="Base URL of the GitLab instance",
    )
    gitlab_token: SecretStr = Field(
        description="GitLab access token with api and read_api scopes",
    )
    project_id: str = Field(
        description="GitLab project ID (numeric) or path (namespace/project)",
    )

    # LLM settings
    llm_base_url: str = Field(
        default="https://api.anthropic.com",
        description="Base URL for Claude-compatible API endpoint",
    )
    llm_api_key: SecretStr = Field(
        description="API key for the LLM endpoint",
    )
    llm_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model to use for code review",
    )
    llm_max_tokens: int = Field(
        default=8192,
        description="Maximum tokens for LLM response",
    )

    # Review settings
    max_files: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of files to review",
    )
    max_diff_chars: int = Field(
        default=100000,
        ge=1000,
        description="Maximum characters of diff to process",
    )
    max_context_lines: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Maximum lines of context to fetch per file",
    )
    extra_instructions: str | None = Field(
        default="CodeReviewInstructions.md",
        description="Path to a markdown file containing custom review instructions",
    )
    verbosity: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Verbosity level (0=quiet, 1=normal, 2=verbose, 3=debug)",
    )

    # Output settings
    post_to_gitlab: bool = Field(
        default=False,
        description="If true, post review as MR note; if false, print to stdout",
    )

    @field_validator("gitlab_base_url", "llm_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Remove trailing slashes from URLs."""
        return v.rstrip("/")


class ReviewConfig:
    """Configuration for a specific review run."""

    def __init__(
        self,
        mr_iid: int,
        local_repo_path: str,
        target_branch: str | None = None,
        source_branch: str | None = None,
        settings: Settings | None = None,
    ):
        self.mr_iid = mr_iid
        self.local_repo_path = local_repo_path
        self.target_branch = target_branch
        self.source_branch = source_branch
        self.settings = settings or Settings()  # type: ignore[call-arg]

    @property
    def gitlab_base_url(self) -> str:
        return self.settings.gitlab_base_url

    @property
    def gitlab_token(self) -> str:
        return self.settings.gitlab_token.get_secret_value()

    @property
    def project_id(self) -> str:
        return self.settings.project_id

    @property
    def max_files(self) -> int:
        return self.settings.max_files

    @property
    def max_diff_chars(self) -> int:
        return self.settings.max_diff_chars

    @property
    def post_to_gitlab(self) -> bool:
        return self.settings.post_to_gitlab

    @property
    def verbosity(self) -> int:
        return self.settings.verbosity

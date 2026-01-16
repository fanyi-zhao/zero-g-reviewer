"""
Output Parsers for Agent Results

Pydantic models for structured extraction of code review issues
from LLM responses.
"""

from typing import Literal
from pydantic import BaseModel, Field


class CodeIssue(BaseModel):
    """A single code issue found during review."""
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(
        description="Issue severity level"
    )
    file_path: str = Field(
        description="Path to the file containing the issue"
    )
    line_number: int | None = Field(
        default=None,
        description="Line number (if applicable)"
    )
    title: str = Field(
        description="Short title describing the issue"
    )
    description: str = Field(
        description="Detailed description of the issue"
    )
    suggested_fix: str | None = Field(
        default=None,
        description="Recommended fix or code example"
    )


class CodeSuggestion(BaseModel):
    """A non-blocking suggestion for improvement."""
    file_path: str = Field(
        description="Path to the file"
    )
    title: str = Field(
        description="Short title for the suggestion"
    )
    description: str = Field(
        description="Detailed suggestion"
    )
    code_example: str | None = Field(
        default=None,
        description="Example code showing the improvement"
    )


class SecurityReviewResult(BaseModel):
    """Structured output for security agent."""
    issues: list[CodeIssue] = Field(
        default_factory=list,
        description="List of security issues found"
    )
    suggestions: list[CodeSuggestion] = Field(
        default_factory=list,
        description="Security improvement suggestions"
    )
    summary: str = Field(
        default="",
        description="Brief summary of security findings"
    )


class PerformanceReviewResult(BaseModel):
    """Structured output for performance agent."""
    issues: list[CodeIssue] = Field(
        default_factory=list,
        description="List of performance issues found"
    )
    suggestions: list[CodeSuggestion] = Field(
        default_factory=list,
        description="Performance improvement suggestions"
    )
    summary: str = Field(
        default="",
        description="Brief summary of performance findings"
    )


class DomainReviewResult(BaseModel):
    """Structured output for domain agent."""
    issues: list[CodeIssue] = Field(
        default_factory=list,
        description="List of business logic issues found"
    )
    suggestions: list[CodeSuggestion] = Field(
        default_factory=list,
        description="Domain-specific improvement suggestions"
    )
    summary: str = Field(
        default="",
        description="Brief summary of domain findings"
    )


class GeneralReviewResult(BaseModel):
    """Structured output for general reviewer (lite mode)."""
    issues: list[CodeIssue] = Field(
        default_factory=list,
        description="List of issues found"
    )
    suggestions: list[CodeSuggestion] = Field(
        default_factory=list,
        description="Improvement suggestions"
    )
    summary: str = Field(
        default="",
        description="Brief summary of findings"
    )
    approve: bool = Field(
        default=True,
        description="Whether to approve this PR"
    )

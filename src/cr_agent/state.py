"""
Agent State Schema

Defines the TypedDict schema for LangGraph state management throughout
the code review workflow.
"""

from typing import TypedDict, Literal, Any
from pydantic import BaseModel, Field


class DependencyContext(BaseModel):
    """Context from dependency impact analysis."""
    affected_modules: list[str] = Field(default_factory=list)
    impact_severity: Literal["high", "medium", "low"] = "low"


class PatternContext(BaseModel):
    """Context from design pattern retrieval."""
    pattern_name: str | None = None
    examples: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)


class HotspotContext(BaseModel):
    """Context from hotspot detection."""
    change_frequency: int = 0
    recent_authors: list[str] = Field(default_factory=list)
    churn_score: float = 0.0


class UserPreferenceContext(BaseModel):
    """Context from user preferences RAG search."""
    past_feedback: list[str] = Field(default_factory=list)
    preference_signals: list[str] = Field(default_factory=list)
    mistakes_to_avoid: list[str] = Field(default_factory=list)


class KnowledgeGraphContext(BaseModel):
    """Aggregated context from all drift prevention tools."""
    dependencies: DependencyContext = Field(default_factory=DependencyContext)
    patterns: PatternContext = Field(default_factory=PatternContext)
    hotspots: HotspotContext = Field(default_factory=HotspotContext)
    user_preferences: UserPreferenceContext = Field(default_factory=UserPreferenceContext)


class SubAgentResult(BaseModel):
    """Result from a sub-agent review."""
    agent_name: str
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0


class FilteredDiff(BaseModel):
    """A filtered subset of the diff for a specific agent."""
    files: list[str] = Field(default_factory=list)
    diff_content: str = ""
    total_lines: int = 0


class FinalReview(BaseModel):
    """Final synthesized review output."""
    executive_summary: Literal["Safe to merge", "Request Changes", "Needs Discussion"]
    architectural_impact: Literal["High", "Medium", "Low"]
    critical_issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    """
    Main state schema for the LangGraph workflow.
    
    This state flows through all nodes: context analysis, routing,
    sub-agent delegation, and synthesis.
    """
    # --- Input Fields ---
    mr_id: str
    diff: str
    related_files: list[str]
    user_notes: str
    
    # --- Context Analysis Results ---
    context: KnowledgeGraphContext
    
    # --- Routing Decision ---
    should_delegate: bool  # True if >300 lines or >3 domains
    total_lines: int
    domain_count: int
    detected_domains: list[str]
    
    # --- File Filtering (Context Pruning) ---
    security_diff: FilteredDiff
    performance_diff: FilteredDiff
    domain_diff: FilteredDiff
    
    # --- Sub-Agent Results ---
    sub_agent_results: dict[str, SubAgentResult]
    general_review_result: SubAgentResult | None
    
    # --- Final Output ---
    final_review: FinalReview

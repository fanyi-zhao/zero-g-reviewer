"""
Tests for AgentState schema and Pydantic models.
"""

import pytest
from cr_agent.state import (
    AgentState,
    DependencyContext,
    PatternContext,
    HotspotContext,
    UserPreferenceContext,
    KnowledgeGraphContext,
    SubAgentResult,
    FilteredDiff,
    FinalReview,
)


class TestDependencyContext:
    """Tests for DependencyContext model."""
    
    def test_default_values(self):
        ctx = DependencyContext()
        assert ctx.affected_modules == []
        assert ctx.impact_severity == "low"
    
    def test_custom_values(self):
        ctx = DependencyContext(
            affected_modules=["module_a", "module_b"],
            impact_severity="high",
        )
        assert len(ctx.affected_modules) == 2
        assert ctx.impact_severity == "high"


class TestPatternContext:
    """Tests for PatternContext model."""
    
    def test_default_values(self):
        ctx = PatternContext()
        assert ctx.pattern_name is None
        assert ctx.examples == []
        assert ctx.anti_patterns == []
    
    def test_with_pattern(self):
        ctx = PatternContext(
            pattern_name="Factory Pattern",
            anti_patterns=["Avoid Singleton"],
        )
        assert ctx.pattern_name == "Factory Pattern"
        assert "Avoid Singleton" in ctx.anti_patterns


class TestKnowledgeGraphContext:
    """Tests for KnowledgeGraphContext aggregation."""
    
    def test_default_values(self):
        ctx = KnowledgeGraphContext()
        assert isinstance(ctx.dependencies, DependencyContext)
        assert isinstance(ctx.patterns, PatternContext)
        assert isinstance(ctx.hotspots, HotspotContext)
        assert isinstance(ctx.user_preferences, UserPreferenceContext)
    
    def test_nested_assignment(self):
        ctx = KnowledgeGraphContext(
            dependencies=DependencyContext(impact_severity="high"),
        )
        assert ctx.dependencies.impact_severity == "high"


class TestSubAgentResult:
    """Tests for SubAgentResult model."""
    
    def test_creation(self):
        result = SubAgentResult(
            agent_name="security_agent",
            issues=[{"severity": "HIGH", "message": "SQL injection"}],
            confidence=0.9,
        )
        assert result.agent_name == "security_agent"
        assert len(result.issues) == 1
        assert result.confidence == 0.9


class TestFilteredDiff:
    """Tests for FilteredDiff model."""
    
    def test_empty_diff(self):
        diff = FilteredDiff()
        assert diff.files == []
        assert diff.diff_content == ""
        assert diff.total_lines == 0
    
    def test_with_files(self):
        diff = FilteredDiff(
            files=["src/api/users.py", "src/api/auth.py"],
            diff_content="+ new line",
            total_lines=50,
        )
        assert len(diff.files) == 2
        assert diff.total_lines == 50


class TestFinalReview:
    """Tests for FinalReview model."""
    
    def test_safe_to_merge(self):
        review = FinalReview(
            executive_summary="Safe to merge",
            architectural_impact="Low",
        )
        assert review.executive_summary == "Safe to merge"
        assert review.critical_issues == []
    
    def test_request_changes(self):
        review = FinalReview(
            executive_summary="Request Changes",
            architectural_impact="High",
            critical_issues=[{"file": "api.py", "issue": "SQL injection"}],
        )
        assert review.executive_summary == "Request Changes"
        assert len(review.critical_issues) == 1


class TestAgentState:
    """Tests for AgentState TypedDict structure."""
    
    def test_state_creation(self):
        state: AgentState = {
            "mr_id": "MR-123",
            "diff": "+ added line",
            "related_files": ["file.py"],
            "user_notes": "test",
        }
        assert state["mr_id"] == "MR-123"
        assert len(state["related_files"]) == 1
    
    def test_state_with_context(self):
        state: AgentState = {
            "mr_id": "MR-456",
            "diff": "",
            "related_files": [],
            "context": KnowledgeGraphContext(),
            "should_delegate": True,
        }
        assert state["should_delegate"] is True
        assert isinstance(state["context"], KnowledgeGraphContext)

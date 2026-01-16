"""
Agents package for code review sub-agents.

Each sub-agent specializes in a specific aspect of code review
and uses structured output parsing for reliable issue extraction.
"""

from cr_agent.agents.general_reviewer import general_reviewer_node
from cr_agent.agents.security_agent import security_agent_node
from cr_agent.agents.performance_agent import performance_agent_node
from cr_agent.agents.domain_agent import domain_agent_node
from cr_agent.agents.output_parsers import (
    CodeIssue,
    CodeSuggestion,
    SecurityReviewResult,
    PerformanceReviewResult,
    DomainReviewResult,
    GeneralReviewResult,
)

__all__ = [
    "general_reviewer_node",
    "security_agent_node",
    "performance_agent_node",
    "domain_agent_node",
    "CodeIssue",
    "CodeSuggestion",
    "SecurityReviewResult",
    "PerformanceReviewResult",
    "DomainReviewResult",
    "GeneralReviewResult",
]

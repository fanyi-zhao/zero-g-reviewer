"""
Performance Agent

Specialized sub-agent for performance issue detection.
Only receives database/query files (filtered by routing layer).

Uses structured output parsing for reliable issue extraction.
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult, FilteredDiff
from cr_agent.agents.output_parsers import PerformanceReviewResult


PERFORMANCE_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a performance-focused code reviewer specializing in:
- N+1 query patterns (database queries in loops)
- Inefficient algorithms (O(n²) when O(n) is possible)
- Memory leaks and excessive memory allocation
- Blocking I/O in async contexts
- Missing caching opportunities
- Unnecessary data loading
- Index usage and query optimization

You are reviewing ONLY database/query-related files. Other files have been filtered out.

Be precise and avoid false positives. Focus on measurable performance impacts.
Rate each finding by severity: CRITICAL, HIGH, MEDIUM, LOW.

IMPORTANT: Return structured JSON output matching the schema."""),
    ("human", """
Review the following filtered diff for performance issues:

Files being reviewed: {file_list}

```diff
{diff_content}
```

Analyze for performance problems and return your findings.
"""),
])


async def performance_agent_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    Performance-focused code review sub-agent.
    
    Scans for N+1 queries, memory leaks, algorithmic inefficiencies.
    Only receives filtered database/query files from the routing layer.
    Uses structured output parsing for reliable extraction.
    
    Args:
        state: Current agent state with performance_diff (filtered).
        llm: Language model for performance analysis.
        
    Returns:
        Updated state with performance agent results in sub_agent_results.
    """
    performance_diff: FilteredDiff | None = state.get("performance_diff")
    
    if not performance_diff or not performance_diff.files:
        # No relevant files for performance review
        result = SubAgentResult(
            agent_name="performance_agent",
            issues=[],
            suggestions=[],
            confidence=1.0,
        )
        return _merge_result(state, result)
    
    # Use structured output for reliable parsing
    structured_llm = llm.with_structured_output(PerformanceReviewResult)
    chain = PERFORMANCE_AGENT_PROMPT | structured_llm
    
    try:
        response: PerformanceReviewResult = await chain.ainvoke({
            "file_list": ", ".join(performance_diff.files),
            "diff_content": performance_diff.diff_content[:15000],
        })
        
        issues = [
            {
                "severity": issue.severity,
                "file_path": issue.file_path,
                "line_number": issue.line_number,
                "title": issue.title,
                "description": issue.description,
                "suggested_fix": issue.suggested_fix,
                "agent": "performance_agent",
            }
            for issue in response.issues
        ]
        
        suggestions = [
            {
                "file_path": s.file_path,
                "title": s.title,
                "description": s.description,
                "code_example": s.code_example,
                "agent": "performance_agent",
            }
            for s in response.suggestions
        ]
        
        result = SubAgentResult(
            agent_name="performance_agent",
            issues=issues,
            suggestions=suggestions,
            confidence=0.90,
        )
        
    except Exception as e:
        result = SubAgentResult(
            agent_name="performance_agent",
            issues=[{
                "severity": "LOW",
                "title": "Performance analysis incomplete",
                "description": f"Could not complete structured analysis: {str(e)}",
                "agent": "performance_agent",
            }],
            suggestions=[],
            confidence=0.5,
        )
    
    return _merge_result(state, result)


def _merge_result(state: AgentState, result: SubAgentResult) -> dict[str, Any]:
    """Merge new result into existing sub_agent_results."""
    existing = state.get("sub_agent_results", {})
    existing[result.agent_name] = result
    return {"sub_agent_results": existing}

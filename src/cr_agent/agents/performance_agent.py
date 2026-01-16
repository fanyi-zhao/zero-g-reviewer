"""
Performance Agent

Specialized sub-agent for performance issue detection.
Only receives DB/query/model files (filtered by routing layer).
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult, FilteredDiff


PERFORMANCE_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a performance-focused code reviewer specializing in:
- N+1 query detection
- Memory leaks and unbounded allocations
- Inefficient algorithms (O(n²) when O(n) is possible)
- Missing database indexes suggestions
- Unnecessary data fetching
- Connection pool exhaustion risks
- Caching opportunities

You are reviewing ONLY database/query/model files. Unrelated files have been filtered out.

Be precise. Only flag issues with measurable performance impact.
Rate each finding by impact: HIGH, MEDIUM, LOW.
"""),
    ("human", """
Review the following filtered diff for performance issues:

Files being reviewed: {file_list}

```diff
{diff_content}
```

Provide findings with:
- Impact level
- File path and line number
- Description of the performance issue
- Recommended optimization
"""),
])


async def performance_agent_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    Performance-focused code review sub-agent.
    
    Detects N+1 queries, memory leaks, and other performance issues.
    Only receives filtered DB/query/model files from the routing layer.
    
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
    
    chain = PERFORMANCE_AGENT_PROMPT | llm
    
    response = await chain.ainvoke({
        "file_list": ", ".join(performance_diff.files),
        "diff_content": performance_diff.diff_content,
    })
    
    # Parse response into SubAgentResult
    result = SubAgentResult(
        agent_name="performance_agent",
        issues=[],  # TODO: Parse structured issues from response
        suggestions=[],
        confidence=0.80,
    )
    
    return _merge_result(state, result)


def _merge_result(state: AgentState, result: SubAgentResult) -> dict[str, Any]:
    """Merge new result into existing sub_agent_results."""
    existing = state.get("sub_agent_results", {})
    existing[result.agent_name] = result
    return {"sub_agent_results": existing}

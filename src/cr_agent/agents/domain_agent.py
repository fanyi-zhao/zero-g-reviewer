"""
Domain Agent

Specialized sub-agent for business logic validation.
Only receives domain/service/core files (filtered by routing layer).
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult, FilteredDiff


DOMAIN_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a domain-focused code reviewer specializing in:
- Business logic correctness
- Domain model integrity
- Invariant preservation
- State machine transitions
- Business rule violations
- Edge case handling
- Data consistency requirements

You are reviewing ONLY domain/service/core business logic files.

Context about established patterns:
{patterns}

User preferences from past reviews:
{user_preferences}

Be precise. Focus on correctness over style.
Rate each finding by business impact: BLOCKING, IMPORTANT, MINOR.
"""),
    ("human", """
Review the following filtered diff for business logic issues:

Files being reviewed: {file_list}

```diff
{diff_content}
```

User notes about this change: {user_notes}

Provide findings with:
- Business impact level
- File path and line number
- Description of the logic issue
- Recommended correction
"""),
])


async def domain_agent_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    Domain-focused code review sub-agent.
    
    Validates business logic against requirements and domain rules.
    Only receives filtered domain/service/core files from the routing layer.
    
    Args:
        state: Current agent state with domain_diff (filtered).
        llm: Language model for domain analysis.
        
    Returns:
        Updated state with domain agent results in sub_agent_results.
    """
    domain_diff: FilteredDiff | None = state.get("domain_diff")
    context = state.get("context")
    
    if not domain_diff or not domain_diff.files:
        # No relevant files for domain review
        result = SubAgentResult(
            agent_name="domain_agent",
            issues=[],
            suggestions=[],
            confidence=1.0,
        )
        return _merge_result(state, result)
    
    chain = DOMAIN_AGENT_PROMPT | llm
    
    response = await chain.ainvoke({
        "file_list": ", ".join(domain_diff.files),
        "diff_content": domain_diff.diff_content,
        "user_notes": state.get("user_notes", ""),
        "patterns": context.patterns if context else "Not available",
        "user_preferences": context.user_preferences if context else "Not available",
    })
    
    # Parse response into SubAgentResult
    result = SubAgentResult(
        agent_name="domain_agent",
        issues=[],  # TODO: Parse structured issues from response
        suggestions=[],
        confidence=0.75,
    )
    
    return _merge_result(state, result)


def _merge_result(state: AgentState, result: SubAgentResult) -> dict[str, Any]:
    """Merge new result into existing sub_agent_results."""
    existing = state.get("sub_agent_results", {})
    existing[result.agent_name] = result
    return {"sub_agent_results": existing}

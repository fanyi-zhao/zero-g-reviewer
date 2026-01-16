"""
Domain Agent

Specialized sub-agent for business logic validation.
Only receives domain/service files (filtered by routing layer).

Uses structured output parsing for reliable issue extraction.
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult, FilteredDiff
from cr_agent.agents.output_parsers import DomainReviewResult


DOMAIN_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a domain-focused code reviewer specializing in:
- Business logic correctness
- Domain model integrity
- Business rule violations
- Edge case handling
- Data validation completeness
- State management issues
- Contract/invariant violations

You are reviewing ONLY business logic and domain files. Infra and test files have been filtered out.

Focus on logical correctness and business requirements.
Rate each finding by severity: CRITICAL, HIGH, MEDIUM, LOW.

IMPORTANT: Return structured JSON output matching the schema."""),
    ("human", """
Review the following filtered diff for business logic issues:

Files being reviewed: {file_list}

Context from PR author: {user_notes}

```diff
{diff_content}
```

Analyze for business logic problems and return your findings.
"""),
])


async def domain_agent_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    Domain-focused code review sub-agent.
    
    Validates business logic correctness and domain model integrity.
    Only receives filtered domain/service files from the routing layer.
    Uses structured output parsing for reliable extraction.
    
    Args:
        state: Current agent state with domain_diff (filtered).
        llm: Language model for domain analysis.
        
    Returns:
        Updated state with domain agent results in sub_agent_results.
    """
    domain_diff: FilteredDiff | None = state.get("domain_diff")
    user_notes = state.get("user_notes", "")
    
    if not domain_diff or not domain_diff.files:
        result = SubAgentResult(
            agent_name="domain_agent",
            issues=[],
            suggestions=[],
            confidence=1.0,
        )
        return _merge_result(state, result)
    
    # Use structured output for reliable parsing
    structured_llm = llm.with_structured_output(DomainReviewResult)
    chain = DOMAIN_AGENT_PROMPT | structured_llm
    
    try:
        response: DomainReviewResult = await chain.ainvoke({
            "file_list": ", ".join(domain_diff.files),
            "diff_content": domain_diff.diff_content[:15000],
            "user_notes": user_notes or "No additional context provided.",
        })
        
        issues = [
            {
                "severity": issue.severity,
                "file_path": issue.file_path,
                "line_number": issue.line_number,
                "title": issue.title,
                "description": issue.description,
                "suggested_fix": issue.suggested_fix,
                "agent": "domain_agent",
            }
            for issue in response.issues
        ]
        
        suggestions = [
            {
                "file_path": s.file_path,
                "title": s.title,
                "description": s.description,
                "code_example": s.code_example,
                "agent": "domain_agent",
            }
            for s in response.suggestions
        ]
        
        result = SubAgentResult(
            agent_name="domain_agent",
            issues=issues,
            suggestions=suggestions,
            confidence=0.90,
        )
        
    except Exception as e:
        result = SubAgentResult(
            agent_name="domain_agent",
            issues=[{
                "severity": "LOW",
                "title": "Domain analysis incomplete",
                "description": f"Could not complete structured analysis: {str(e)}",
                "agent": "domain_agent",
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

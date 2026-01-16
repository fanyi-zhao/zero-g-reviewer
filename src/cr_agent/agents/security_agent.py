"""
Security Agent

Specialized sub-agent for security vulnerability detection.
Only receives backend/API files (filtered by routing layer).

Uses structured output parsing for reliable issue extraction.
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult, FilteredDiff
from cr_agent.agents.output_parsers import SecurityReviewResult, CodeIssue


SECURITY_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a security-focused code reviewer specializing in:
- SQL Injection (SQLi) vulnerabilities
- Cross-Site Scripting (XSS) attacks
- Authentication and Authorization issues
- Secrets/credentials exposure
- Input validation gaps
- CSRF vulnerabilities
- Insecure deserialization

You are reviewing ONLY backend/API files. Frontend and test files have been filtered out.

Be precise and avoid false positives. Only flag genuine security concerns.
Rate each finding by severity: CRITICAL, HIGH, MEDIUM, LOW.

IMPORTANT: Return structured JSON output matching the schema."""),
    ("human", """
Review the following filtered diff for security issues:

Files being reviewed: {file_list}

```diff
{diff_content}
```

Analyze for security vulnerabilities and return your findings.
"""),
])


async def security_agent_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    Security-focused code review sub-agent.
    
    Scans for SQLi, XSS, Auth issues, and other security vulnerabilities.
    Only receives filtered backend/API files from the routing layer.
    Uses structured output parsing for reliable extraction.
    
    Args:
        state: Current agent state with security_diff (filtered).
        llm: Language model for security analysis.
        
    Returns:
        Updated state with security agent results in sub_agent_results.
    """
    security_diff: FilteredDiff | None = state.get("security_diff")
    
    if not security_diff or not security_diff.files:
        # No relevant files for security review
        result = SubAgentResult(
            agent_name="security_agent",
            issues=[],
            suggestions=[],
            confidence=1.0,
        )
        return _merge_result(state, result)
    
    # Use structured output for reliable parsing
    structured_llm = llm.with_structured_output(SecurityReviewResult)
    chain = SECURITY_AGENT_PROMPT | structured_llm
    
    try:
        response: SecurityReviewResult = await chain.ainvoke({
            "file_list": ", ".join(security_diff.files),
            "diff_content": security_diff.diff_content[:15000],  # Token limit
        })
        
        # Convert to SubAgentResult format
        issues = [
            {
                "severity": issue.severity,
                "file_path": issue.file_path,
                "line_number": issue.line_number,
                "title": issue.title,
                "description": issue.description,
                "suggested_fix": issue.suggested_fix,
                "agent": "security_agent",
            }
            for issue in response.issues
        ]
        
        suggestions = [
            {
                "file_path": s.file_path,
                "title": s.title,
                "description": s.description,
                "code_example": s.code_example,
                "agent": "security_agent",
            }
            for s in response.suggestions
        ]
        
        result = SubAgentResult(
            agent_name="security_agent",
            issues=issues,
            suggestions=suggestions,
            confidence=0.90,
        )
        
    except Exception as e:
        # Fallback if structured parsing fails
        result = SubAgentResult(
            agent_name="security_agent",
            issues=[{
                "severity": "LOW",
                "title": "Security analysis incomplete",
                "description": f"Could not complete structured analysis: {str(e)}",
                "agent": "security_agent",
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

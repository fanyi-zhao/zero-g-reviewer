"""
General Reviewer Agent

Lite-mode reviewer for smaller PRs (≤300 lines, ≤3 domains).
Provides comprehensive but lightweight review when delegation isn't needed.

Uses structured output parsing for reliable issue extraction.
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult
from cr_agent.agents.output_parsers import GeneralReviewResult


GENERAL_REVIEWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a thorough code reviewer conducting a lightweight review.
This PR is small enough (<300 lines, <3 domains) to not require specialized sub-agents.

Check for:
- Code correctness and logic errors
- Security basics (input validation, auth checks)
- Performance red flags (obvious N+1, memory issues)
- Code style and readability
- Documentation completeness

Be constructive and specific. Rate issues by severity: CRITICAL, HIGH, MEDIUM, LOW.

IMPORTANT: Return structured JSON output matching the schema."""),
    ("human", """
Review the following diff:

MR ID: {mr_id}
Files: {related_files}
Author notes: {user_notes}

Context from knowledge graph:
- Patterns: {patterns}
- Preferences to follow: {preferences}
- Mistakes to avoid: {mistakes}

```diff
{diff}
```

Provide your review with issues and suggestions.
"""),
])


async def general_reviewer_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    General code reviewer for lite-mode (small PRs).
    
    Provides comprehensive but lightweight review when specialized
    sub-agents aren't needed.
    Uses structured output parsing for reliable extraction.
    
    Args:
        state: Current agent state with diff and context.
        llm: Language model for review.
        
    Returns:
        Updated state with general_review_result.
    """
    context = state.get("context")
    diff = state.get("diff", "")
    
    # Extract context info
    patterns = context.patterns.pattern_name if context and context.patterns else "None detected"
    preferences = ", ".join(context.user_preferences.preference_signals[:3]) if context and context.user_preferences else "None"
    mistakes = ", ".join(context.user_preferences.mistakes_to_avoid[:3]) if context and context.user_preferences else "None"
    
    # Use structured output for reliable parsing
    structured_llm = llm.with_structured_output(GeneralReviewResult)
    chain = GENERAL_REVIEWER_PROMPT | structured_llm
    
    try:
        response: GeneralReviewResult = await chain.ainvoke({
            "mr_id": state.get("mr_id", "unknown"),
            "related_files": ", ".join(state.get("related_files", [])),
            "user_notes": state.get("user_notes", "No notes"),
            "diff": diff[:20000],  # Token limit
            "patterns": patterns,
            "preferences": preferences,
            "mistakes": mistakes,
        })
        
        issues = [
            {
                "severity": issue.severity,
                "file_path": issue.file_path,
                "line_number": issue.line_number,
                "title": issue.title,
                "description": issue.description,
                "suggested_fix": issue.suggested_fix,
                "agent": "general_reviewer",
            }
            for issue in response.issues
        ]
        
        suggestions = [
            {
                "file_path": s.file_path,
                "title": s.title,
                "description": s.description,
                "code_example": s.code_example,
                "agent": "general_reviewer",
            }
            for s in response.suggestions
        ]
        
        result = SubAgentResult(
            agent_name="general_reviewer",
            issues=issues,
            suggestions=suggestions,
            confidence=0.85,
        )
        
    except Exception as e:
        result = SubAgentResult(
            agent_name="general_reviewer",
            issues=[{
                "severity": "LOW",
                "title": "Review incomplete",
                "description": f"Could not complete structured analysis: {str(e)}",
                "agent": "general_reviewer",
            }],
            suggestions=[],
            confidence=0.5,
        )
    
    return {"general_review_result": result}

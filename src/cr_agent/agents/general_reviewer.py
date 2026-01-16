"""
General Reviewer Agent (Lite Mode)

Handles small PRs (≤300 lines, ≤3 domains) that don't require
specialized sub-agent delegation.
"""

from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from cr_agent.state import AgentState, SubAgentResult


GENERAL_REVIEWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a senior code reviewer performing a comprehensive review.
    
Context from knowledge graph:
- Dependencies: {dependencies}
- Design Patterns: {patterns}
- Hotspots: {hotspots}
- User Preferences: {user_preferences}

Review the following diff for:
1. Logic errors and bugs
2. Security issues (SQLi, XSS, Auth)
3. Performance concerns (N+1, memory leaks)
4. Architectural alignment with established patterns
5. Code quality and maintainability

Be precise. Only flag real issues, not style preferences (linters handle those).
If you cannot determine something from context, say "Missing Context" rather than guessing.
"""),
    ("human", """
MR ID: {mr_id}
User Notes: {user_notes}

Diff:
```
{diff}
```

Related Files: {related_files}

Provide your review with specific file paths and line numbers.
"""),
])


async def general_reviewer_node(
    state: AgentState,
    llm: BaseChatModel,
) -> dict[str, Any]:
    """
    General reviewer for small PRs (Lite Mode).
    
    Performs a comprehensive but lighter-weight review when full
    sub-agent delegation is not required.
    
    Args:
        state: Current agent state with diff and context.
        llm: Language model for review generation.
        
    Returns:
        Updated state with general_review_result.
    """
    # Format context for the prompt
    context = state.get("context")
    
    chain = GENERAL_REVIEWER_PROMPT | llm
    
    response = await chain.ainvoke({
        "mr_id": state.get("mr_id", ""),
        "user_notes": state.get("user_notes", ""),
        "diff": state.get("diff", ""),
        "related_files": ", ".join(state.get("related_files", [])),
        "dependencies": context.dependencies if context else "Not available",
        "patterns": context.patterns if context else "Not available",
        "hotspots": context.hotspots if context else "Not available",
        "user_preferences": context.user_preferences if context else "Not available",
    })
    
    # Parse response into SubAgentResult
    result = SubAgentResult(
        agent_name="general_reviewer",
        issues=[],  # TODO: Parse structured issues from response
        suggestions=[],
        confidence=0.8,
    )
    
    return {"general_review_result": result}

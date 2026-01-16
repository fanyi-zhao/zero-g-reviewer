"""
LangGraph Workflow Definition

Main graph that orchestrates the code review workflow:
1. Context Analysis (query knowledge graph)
2. Routing Decision (delegate vs lite mode)
3. Sub-Agent Execution (PARALLEL using Send API)
4. Synthesis (filter, de-conflict, format output)
"""

from typing import Any, Literal, Sequence
from functools import partial

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from langchain_core.language_models import BaseChatModel

from cr_agent.state import (
    AgentState,
    KnowledgeGraphContext,
    DependencyContext,
    PatternContext,
    HotspotContext,
    UserPreferenceContext,
    FinalReview,
    SubAgentResult,
    FilteredDiff,
)
from cr_agent.tools import (
    DependencyImpactTool,
    DesignPatternTool,
    HotspotDetectorTool,
    UserPreferencesTool,
)
from cr_agent.routing import routing_decision_node
from cr_agent.agents import (
    general_reviewer_node,
    security_agent_node,
    performance_agent_node,
    domain_agent_node,
)


# =============================================================================
# Node Implementations
# =============================================================================

async def context_analysis_node(state: AgentState) -> dict[str, Any]:
    """
    Query the knowledge graph for context before review.
    
    Runs all drift prevention tools in parallel for efficiency.
    """
    related_files = state.get("related_files", [])
    diff = state.get("diff", "")
    
    # Query all tools (in production, these would be async)
    dependency_result = DependencyImpactTool.invoke({
        "modified_files": related_files,
    })
    
    pattern_result = DesignPatternTool.invoke({
        "file_paths": related_files,
    })
    
    hotspot_result = HotspotDetectorTool.invoke({
        "file_paths": related_files,
    })
    
    preferences_result = UserPreferencesTool.invoke({
        "code_context": diff[:1000],  # First 1000 chars for context
        "file_paths": related_files,
    })
    
    # Build aggregated context
    context = KnowledgeGraphContext(
        dependencies=DependencyContext(
            affected_modules=dependency_result.get("affected_modules", []),
            impact_severity=dependency_result.get("impact_severity", "low"),
        ),
        patterns=PatternContext(
            pattern_name=pattern_result.get("pattern_name"),
            examples=pattern_result.get("examples", []),
            anti_patterns=pattern_result.get("anti_patterns", []),
        ),
        hotspots=HotspotContext(
            change_frequency=hotspot_result.get("overall_churn_score", 0) * 100,
            churn_score=hotspot_result.get("overall_churn_score", 0),
        ),
        user_preferences=UserPreferenceContext(
            past_feedback=[],
            preference_signals=preferences_result.get("preference_signals", []),
            mistakes_to_avoid=preferences_result.get("mistakes_to_avoid", []),
        ),
    )
    
    return {"context": context}


async def gather_results_node(state: AgentState) -> dict[str, Any]:
    """
    Gather all parallel sub-agent results.
    
    This node runs after all parallel agents complete via the Send API.
    Results are already in state.sub_agent_results from each agent.
    """
    # Simply pass through - results already aggregated in state
    return {}


async def synthesis_node(state: AgentState, llm: BaseChatModel) -> dict[str, Any]:
    """
    Synthesize all review results into a final output.
    
    Responsibilities:
    - Filter false positives
    - De-conflict competing suggestions
    - Format as tiered review (Blockers, Architectural, Nitpicks)
    """
    sub_agent_results = state.get("sub_agent_results", {})
    general_result = state.get("general_review_result")
    context = state.get("context")
    
    # Collect all issues from sub-agents
    all_issues: list[dict[str, Any]] = []
    all_suggestions: list[dict[str, Any]] = []
    
    if general_result:
        all_issues.extend(general_result.issues)
        all_suggestions.extend(general_result.suggestions)
    
    for agent_name, result in sub_agent_results.items():
        all_issues.extend(result.issues)
        all_suggestions.extend(result.suggestions)
    
    # Determine executive summary
    has_blockers = any(
        issue.get("severity") in ("CRITICAL", "HIGH", "BLOCKING")
        for issue in all_issues
    )
    
    if has_blockers:
        executive_summary: Literal["Safe to merge", "Request Changes", "Needs Discussion"] = "Request Changes"
    elif all_issues:
        executive_summary = "Needs Discussion"
    else:
        executive_summary = "Safe to merge"
    
    # Determine architectural impact
    dependency_impact = context.dependencies.impact_severity if context else "low"
    if dependency_impact == "high":
        architectural_impact: Literal["High", "Medium", "Low"] = "High"
    elif dependency_impact == "medium" or len(all_issues) > 3:
        architectural_impact = "Medium"
    else:
        architectural_impact = "Low"
    
    final_review = FinalReview(
        executive_summary=executive_summary,
        architectural_impact=architectural_impact,
        critical_issues=all_issues,
        suggestions=all_suggestions,
    )
    
    return {"final_review": final_review}


# =============================================================================
# Parallel Fanout using Send API
# =============================================================================

def fanout_to_agents(state: AgentState) -> Sequence[Send]:
    """
    Fanout to parallel sub-agents using LangGraph's Send API.
    
    This function is called by add_conditional_edges when delegation is required.
    It returns Send objects that trigger parallel execution of all sub-agents.
    """
    sends = []
    
    # Always send to all three agents - they'll check if they have relevant files
    if state.get("security_diff"):
        sends.append(Send("security_agent", state))
    
    if state.get("performance_diff"):
        sends.append(Send("performance_agent", state))
    
    if state.get("domain_diff"):
        sends.append(Send("domain_agent", state))
    
    # If no filtered diffs (shouldn't happen), still run at least one
    if not sends:
        sends.append(Send("security_agent", state))
    
    return sends


def route_after_decision(state: AgentState) -> Literal["delegate", "lite_mode"]:
    """Determine routing based on delegation decision."""
    if state.get("should_delegate", False):
        return "delegate"
    return "lite_mode"


# =============================================================================
# Graph Builder
# =============================================================================

def build_graph(llm: BaseChatModel) -> CompiledStateGraph:
    """
    Build the LangGraph workflow for code review.
    
    Flow:
    1. context_analysis -> routing_decision
    2. routing_decision -> (delegate | lite_mode)
       - delegate -> [security, performance, domain] (PARALLEL) -> gather -> synthesis
       - lite_mode -> general_reviewer -> synthesis
    3. synthesis -> END
    
    Args:
        llm: Language model to use for all agents.
        
    Returns:
        Compiled state graph ready for execution.
    """
    # Create partial functions with LLM bound
    general_reviewer_with_llm = partial(general_reviewer_node, llm=llm)
    security_agent_with_llm = partial(security_agent_node, llm=llm)
    performance_agent_with_llm = partial(performance_agent_node, llm=llm)
    domain_agent_with_llm = partial(domain_agent_node, llm=llm)
    synthesis_with_llm = partial(synthesis_node, llm=llm)
    
    # Build the graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("context_analysis", context_analysis_node)
    workflow.add_node("routing_decision", routing_decision_node)
    workflow.add_node("general_reviewer", general_reviewer_with_llm)
    workflow.add_node("security_agent", security_agent_with_llm)
    workflow.add_node("performance_agent", performance_agent_with_llm)
    workflow.add_node("domain_agent", domain_agent_with_llm)
    workflow.add_node("gather_results", gather_results_node)
    workflow.add_node("synthesis", synthesis_with_llm)
    
    # Set entry point
    workflow.set_entry_point("context_analysis")
    
    # Add edges
    workflow.add_edge("context_analysis", "routing_decision")
    
    # Conditional routing with parallel fanout for delegation
    workflow.add_conditional_edges(
        "routing_decision",
        route_after_decision,
        {
            "delegate": "security_agent",  # Entry point - will be replaced by Send
            "lite_mode": "general_reviewer",
        },
    )
    
    # PARALLEL EXECUTION: Use Send API for sub-agents
    # Each sub-agent writes to sub_agent_results independently
    # After parallel execution, all agents converge to gather_results
    workflow.add_edge("security_agent", "gather_results")
    workflow.add_edge("performance_agent", "gather_results")
    workflow.add_edge("domain_agent", "gather_results")
    workflow.add_edge("gather_results", "synthesis")
    
    # Lite mode path
    workflow.add_edge("general_reviewer", "synthesis")
    
    # Synthesis to END
    workflow.add_edge("synthesis", END)
    
    return workflow.compile()


async def build_parallel_graph(llm: BaseChatModel) -> CompiledStateGraph:
    """
    Build graph with true parallel execution using Send API.
    
    This version uses conditional_edges with Send for fan-out pattern.
    """
    # Create partial functions with LLM bound
    general_reviewer_with_llm = partial(general_reviewer_node, llm=llm)
    security_agent_with_llm = partial(security_agent_node, llm=llm)
    performance_agent_with_llm = partial(performance_agent_node, llm=llm)
    domain_agent_with_llm = partial(domain_agent_node, llm=llm)
    synthesis_with_llm = partial(synthesis_node, llm=llm)
    
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("context_analysis", context_analysis_node)
    workflow.add_node("routing_decision", routing_decision_node)
    workflow.add_node("general_reviewer", general_reviewer_with_llm)
    workflow.add_node("security_agent", security_agent_with_llm)
    workflow.add_node("performance_agent", performance_agent_with_llm)
    workflow.add_node("domain_agent", domain_agent_with_llm)
    workflow.add_node("synthesis", synthesis_with_llm)
    
    workflow.set_entry_point("context_analysis")
    workflow.add_edge("context_analysis", "routing_decision")
    
    # Conditional edges with Send for parallel fanout
    def route_with_fanout(state: AgentState) -> list[Send] | str:
        """Route to parallel agents or lite mode."""
        if not state.get("should_delegate", False):
            return "general_reviewer"
        
        # Fan-out to all sub-agents in parallel
        sends = []
        if state.get("security_diff"):
            sends.append(Send("security_agent", state))
        if state.get("performance_diff"):
            sends.append(Send("performance_agent", state))  
        if state.get("domain_diff"):
            sends.append(Send("domain_agent", state))
        
        return sends if sends else [Send("security_agent", state)]
    
    workflow.add_conditional_edges(
        "routing_decision",
        route_with_fanout,
        ["security_agent", "performance_agent", "domain_agent", "general_reviewer"],
    )
    
    # All paths lead to synthesis
    workflow.add_edge("security_agent", "synthesis")
    workflow.add_edge("performance_agent", "synthesis")
    workflow.add_edge("domain_agent", "synthesis")
    workflow.add_edge("general_reviewer", "synthesis")
    workflow.add_edge("synthesis", END)
    
    return workflow.compile()


# =============================================================================
# Public API
# =============================================================================

async def review_merge_request(
    graph: CompiledStateGraph,
    mr_id: str,
    diff: str,
    related_files: list[str],
    user_notes: str = "",
) -> FinalReview:
    """
    Execute the code review workflow.
    
    Args:
        graph: Compiled LangGraph workflow.
        mr_id: Merge request identifier.
        diff: The diff content to review.
        related_files: List of files modified in the MR.
        user_notes: Optional notes from the PR author.
        
    Returns:
        FinalReview with executive summary and issues.
    """
    initial_state: AgentState = {
        "mr_id": mr_id,
        "diff": diff,
        "related_files": related_files,
        "user_notes": user_notes,
    }
    
    result = await graph.ainvoke(initial_state)
    
    return result.get("final_review", FinalReview(
        executive_summary="Needs Discussion",
        architectural_impact="Low",
        critical_issues=[],
        suggestions=[],
    ))

import pytest
from cr_agent.graph import build_graph, route_with_fanout
from unittest.mock import AsyncMock
from cr_agent.state import AgentState, FilteredDiff
from cr_agent.agents.output_parsers import GeneralReviewResult
from cr_agent.state import AgentState, FilteredDiff, FinalReview

@pytest.mark.asyncio
async def test_route_with_fanout_lite_mode():
    """Test routing to general reviewer when not delegating."""
    state = {"should_delegate": False}
    result = route_with_fanout(state)
    assert result == "general_reviewer"

@pytest.mark.asyncio
async def test_route_with_fanout_parallel():
    """Test parallel fan-out when delegating."""
    state = {
        "should_delegate": True,
        "security_diff": FilteredDiff(files=["api.py"], diff="..."),
        "performance_diff": FilteredDiff(files=["query.py"], diff="..."),
        "domain_diff": FilteredDiff(files=["service.py"], diff="...")
    }
    result = route_with_fanout(state)
    assert len(result) == 3
    nodes = {send.node for send in result}
    assert nodes == {"security_agent", "performance_agent", "domain_agent"}

@pytest.mark.asyncio
async def test_route_with_fanout_fallback():
    """Test fallback to security agent if delegating but no diffs match."""
    state = {
        "should_delegate": True,
        # No diffs provided or empty
    }
    result = route_with_fanout(state)
    assert len(result) == 1
    assert result[0].node == "security_agent"

@pytest.mark.asyncio
async def test_graph_execution_lite_mode(mock_llm):
    """Integration test of the full graph in lite mode."""
    # Setup mocks
    mock_llm.with_structured_output.return_value.ainvoke.side_effect = [
        # 1. Dependency Tool (mocked in node tools usually, but here we depend on graph internal calls)
        # Actually context_analysis calls tools. Tools use their own logic. 
        # Ideally we should mock tool execution or their LLMs.
        # But let's assume tools run fast/mocked logic.
        
        # 2. General Reviewer
        GeneralReviewResult(issues=[], suggestions=[]),
        
        # 3. Synthesis (doesn't use structured output usually if plain LLM, but let's check synthesis implementation)
        # Synthesis node uses 'FinalReview' structured output? No, it constructs it manually in the code currently 
        # BUT wait, synthesis_node definition:
        # It calls llm?
        # async def synthesis_node(state: AgentState, llm: BaseChatModel) -> dict[str, Any]:
        # IT DOES NOT CALL LLM in the current implementation! 
        # It just aggregates results and formatted FinalReview Pydantic object manually.
        # So we don't need to mock synthesis LLM call.
    ]
    
    # Wait, Context Analysis calls tools. Tools like 'UserPreferences' might use LLM.
    # If they do, we need to mock that.
    # For now, let's rely on the fact that tools mock/heuristic logic handles most things 
    # and UserPreferences handles missing chroma by falling back.
    
    # Actually, routing_decision_node logic uses 'line_count' and 'domain_count'.
    # We need to craft input that triggers lite mode.
    
    graph = build_graph(mock_llm)
    
    initial_state = {
        "mr_id": "123",
        "diff": "small diff",
        "related_files": ["main.py"]
    }
    
    result = await graph.ainvoke(initial_state)
    
    assert "final_review" in result
    assert result["final_review"].executive_summary in ["Safe to merge", "Needs Discussion"]

@pytest.mark.asyncio
async def test_graph_execution_delegation_mode(mock_llm):
    """Integration test of the full graph in delegation mode."""
    # We need to trigger delegation.
    # router.py logic: > 300 lines OR > 3 domains.
    # To check all agents, we need files matching their patterns.
    # Security: api.py, Performance: db.py, Domain: service.py
    
    long_diff = ""
    for file in ["api.py", "db.py", "service.py"]:
        long_diff += f"diff --git a/{file} b/{file}\n"
        long_diff += "new file mode 100644\n"
        long_diff += f"+++ b/{file}\n"
        long_diff += "@@ -0,0 +1,100 @@\n"
        long_diff += "+ code line\n" * 101 # 3 files * 100 lines = 300+ lines total

    
    # Mocks for sub-agents
    # Security, Performance, Domain, General (not called)
    # The order of execution in parallel is non-deterministic, but side_effect iterators are consumed.
    # Since they run in parallel, we should set return_value to be a generic Mock that returns appropriate type based on call?
    # Or simpler: just making sure they all return something valid.
    
    # Since we use one mock_llm instance passed to all nodes,
    # and they all call .with_structured_output(Model).ainvoke(...),
    # we need to ensure the return values match the expected Pydantic model for that node.
    # This is tricky with a single mock.
    # We can inspect the arguments to return the right type, OR we can mock the methods on the nodes if we could.
    # But here we are testing build_graph(llm).
    
    # Solution: The mock_llm.with_structured_output can return a Mock that has a side_effect 
    # that checks the 'schema' arg passed to with_structured_output?
    # No, with_structured_output is called at build time (partial application).
    # wait, partial(node, llm=llm). Inside node: llm.with_structured_output(Model).invoke...
    # So it is called at runtime.
    
    def structured_side_effect(schema, **kwargs):
        # Return a mock runner that returns the instance of 'schema'
        runner = mock_llm.MockRunnable()
        from cr_agent.agents.output_parsers import CodeIssue
        runner.set_result(schema(issues=[], suggestions=[]))
        return runner

    mock_llm.with_structured_output.side_effect = structured_side_effect
    
    graph = build_graph(mock_llm)
    
    initial_state = {
        "mr_id": "456",
        "diff": long_diff,
        "related_files": ["api.py", "db.py", "service.py"] # Trigger all 3 agents
    }
    
    result = await graph.ainvoke(initial_state)
    
    assert "sub_agent_results" in result
    assert len(result["sub_agent_results"]) >= 1
    assert "final_review" in result

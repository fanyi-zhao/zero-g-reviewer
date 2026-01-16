import pytest
from cr_agent.agents import general_reviewer_node, security_agent_node, performance_agent_node, domain_agent_node
from cr_agent.agents.output_parsers import GeneralReviewResult, SecurityReviewResult, PerformanceReviewResult, DomainReviewResult
from cr_agent.state import AgentState, FilteredDiff, SubAgentResult

@pytest.mark.asyncio
async def test_general_reviewer_node(mock_llm, mock_context):
    """Test general reviewer processing and output parsing."""
    expected_llm_result = GeneralReviewResult(
        issues=[], 
        suggestions=[{
            "title": "Improve naming",
            "description": "Use descriptive variables", 
            "file_path": "main.py", 
            "code_example": "x = 1 -> count = 1"
        }]
    )
    
    def return_mock(*args, **kwargs):
        m = mock_llm.MockRunnable()
        m.set_result(expected_llm_result)
        return m
        
    mock_llm.with_structured_output.side_effect = return_mock
    
    state = {
        "diff": "test diff",
        "related_files": ["main.py"],
        "context": mock_context
    }
    
    result = await general_reviewer_node(state, llm=mock_llm)
    
    assert "general_review_result" in result
    actual = result["general_review_result"]
    assert isinstance(actual, SubAgentResult)
    assert actual.agent_name == "general_reviewer"
    assert len(actual.suggestions) == 1
    assert actual.suggestions[0]["title"] == "Improve naming"

@pytest.mark.asyncio
async def test_security_agent_node(mock_llm, mock_context):
    """Test security agent processing."""
    expected_llm_result = SecurityReviewResult(
        issues=[{
            "severity": "HIGH", 
            "title": "SQL Injection",
            "description": "Unsanitized input", 
            "file_path": "db.py", 
            "line_number": 5
        }],
        suggestions=[]
    )
    
    def return_mock(*args, **kwargs):
        m = mock_llm.MockRunnable()
        m.set_result(expected_llm_result)
        return m
        
    mock_llm.with_structured_output.side_effect = return_mock
    
    state = {
        "security_diff": FilteredDiff(files=["db.py"], diff="db diff"),
        "context": mock_context
    }
    
    result = await security_agent_node(state, llm=mock_llm)
    
    assert "sub_agent_results" in result
    assert "security_agent" in result["sub_agent_results"]
    actual = result["sub_agent_results"]["security_agent"]
    assert actual.agent_name == "security_agent"
    assert len(actual.issues) == 1

@pytest.mark.asyncio
async def test_performance_agent_node(mock_llm, mock_context):
    """Test performance agent processing."""
    expected_llm_result = PerformanceReviewResult(
        issues=[{
            "severity": "MEDIUM", 
            "title": "N+1 Query",
            "description": "Fetching in loop", 
            "file_path": "query.py", 
            "line_number": 20
        }],
        suggestions=[]
    )
    
    def return_mock(*args, **kwargs):
        m = mock_llm.MockRunnable()
        m.set_result(expected_llm_result)
        return m
        
    mock_llm.with_structured_output.side_effect = return_mock
    
    state = {
        "performance_diff": FilteredDiff(files=["query.py"], diff="query diff"),
        "context": mock_context
    }
    
    result = await performance_agent_node(state, llm=mock_llm)
    
    assert "sub_agent_results" in result
    assert "performance_agent" in result["sub_agent_results"]
    actual = result["sub_agent_results"]["performance_agent"]
    assert actual.agent_name == "performance_agent"
    assert len(actual.issues) == 1

@pytest.mark.asyncio
async def test_domain_agent_node(mock_llm, mock_context):
    """Test domain agent processing."""
    expected_llm_result = DomainReviewResult(
        issues=[],
        suggestions=[{
            "title": "Align with bounded context",
            "description": "Service logic mismatch", 
            "file_path": "service.py"
        }]
    )
    
    def return_mock(*args, **kwargs):
        m = mock_llm.MockRunnable()
        m.set_result(expected_llm_result)
        return m
        
    mock_llm.with_structured_output.side_effect = return_mock
    
    state = {
        "domain_diff": FilteredDiff(files=["service.py"], diff="service diff"),
        "context": mock_context
    }
    
    result = await domain_agent_node(state, llm=mock_llm)
    
    assert "sub_agent_results" in result
    assert "domain_agent" in result["sub_agent_results"]
    actual = result["sub_agent_results"]["domain_agent"]
    assert actual.agent_name == "domain_agent"
    assert len(actual.suggestions) == 1



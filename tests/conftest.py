import pytest
from unittest.mock import MagicMock, AsyncMock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

@pytest.fixture
def mock_llm():
    """Fixture to provide a mocked LLM that returns structured output."""
    from langchain_core.runnables import Runnable, RunnableLambda
    
    class MockRunnable(Runnable):
        def __init__(self):
            self._result = AIMessage(content="Mocked response")
            
        def set_result(self, result):
            self._result = result
            
        def invoke(self, input, config=None, **kwargs):
            return self._result

        async def ainvoke(self, input, config=None, **kwargs):
            return self._result


    llm = MagicMock(spec=BaseChatModel)
    llm.MockRunnable = MockRunnable # Expose for tests
    
    # Mock with_structured_output to return a new MockRunnable that can be piped
    def create_structured_mock(schema, **kwargs):
        return MockRunnable()
        
    llm.with_structured_output = MagicMock(side_effect=create_structured_mock)
    
    return llm

@pytest.fixture
def mock_context():
    """Fixture to provide a sample KnowledgeGraphContext."""
    from cr_agent.state import KnowledgeGraphContext, DependencyContext, PatternContext, HotspotContext, UserPreferenceContext
    
    return KnowledgeGraphContext(
        dependencies=DependencyContext(affected_modules=["auth"], impact_severity="high"),
        patterns=PatternContext(pattern_name="Repository", examples=["repo.py"]),
        hotspots=HotspotContext(change_frequency=80.0, churn_score=0.8),
        user_preferences=UserPreferenceContext(past_feedback=["Don't use print()"], preference_signals=[], mistakes_to_avoid=[])
    )

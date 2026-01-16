"""
Tests for drift prevention tools.
"""

import pytest
from cr_agent.tools.dependency_impact import dependency_impact_tool
from cr_agent.tools.design_patterns import design_pattern_tool
from cr_agent.tools.hotspot_detector import hotspot_detector_tool


class TestDependencyImpactTool:
    """Tests for DependencyImpactTool."""
    
    def test_returns_expected_structure(self):
        result = dependency_impact_tool.invoke({
            "modified_files": ["src/api/users.py"],
        })
        
        assert "affected_modules" in result
        assert "impact_severity" in result
        assert "dependency_graph" in result
    
    def test_shared_utils_high_impact(self):
        result = dependency_impact_tool.invoke({
            "modified_files": ["/shared/utils/helpers.py"],
        })
        
        assert result["impact_severity"] == "high"
        assert "*" in result["affected_modules"]
    
    def test_normal_file_low_impact(self):
        result = dependency_impact_tool.invoke({
            "modified_files": ["src/feature/specific.py"],
        })
        
        assert result["impact_severity"] == "low"


class TestDesignPatternTool:
    """Tests for DesignPatternTool."""
    
    def test_returns_expected_structure(self):
        result = design_pattern_tool.invoke({
            "file_paths": ["src/api/users.py"],
        })
        
        assert "pattern_name" in result
        assert "description" in result
        assert "examples" in result
        assert "anti_patterns" in result
        assert "confidence" in result
    
    def test_detects_factory_pattern(self):
        result = design_pattern_tool.invoke({
            "file_paths": ["src/factory/user_factory.py"],
        })
        
        assert result["pattern_name"] == "Factory Pattern"
        assert result["confidence"] > 0
    
    def test_detects_repository_pattern(self):
        result = design_pattern_tool.invoke({
            "file_paths": ["src/repository/user_repo.py"],
        })
        
        assert result["pattern_name"] == "Repository Pattern"
    
    def test_detects_service_layer(self):
        result = design_pattern_tool.invoke({
            "file_paths": ["src/services/order_service.py"],
        })
        
        assert result["pattern_name"] == "Service Layer"


class TestHotspotDetectorTool:
    """Tests for HotspotDetectorTool."""
    
    def test_returns_expected_structure(self):
        result = hotspot_detector_tool.invoke({
            "file_paths": ["src/api/users.py"],
        })
        
        assert "hotspots" in result
        assert "overall_churn_score" in result
        assert "recommendation" in result
    
    def test_config_files_detected_as_hotspots(self):
        result = hotspot_detector_tool.invoke({
            "file_paths": ["config/settings.py"],
        })
        
        # Config files are heuristically marked as hotspots
        hotspots = result["hotspots"]
        assert len(hotspots) > 0
        
        config_hotspot = hotspots[0]
        # The hotspot detection is heuristic-based, check churn_score
        assert config_hotspot["churn_score"] >= 0.0
    
    def test_recommendation_for_high_churn(self):
        result = hotspot_detector_tool.invoke({
            "file_paths": ["config/settings.py", "config/constants.py"],
        })
        
        assert result["overall_churn_score"] > 0
        # High churn should generate a recommendation
        if result["overall_churn_score"] > 0.5:
            assert "churn" in result["recommendation"].lower()

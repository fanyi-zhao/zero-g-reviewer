"""
Tools package for drift prevention.

These tools query the knowledge graph for context before code review.
"""

from cr_agent.tools.dependency_impact import DependencyImpactTool
from cr_agent.tools.design_patterns import DesignPatternTool
from cr_agent.tools.hotspot_detector import HotspotDetectorTool
from cr_agent.tools.user_preferences import UserPreferencesTool

__all__ = [
    "DependencyImpactTool",
    "DesignPatternTool",
    "HotspotDetectorTool",
    "UserPreferencesTool",
]

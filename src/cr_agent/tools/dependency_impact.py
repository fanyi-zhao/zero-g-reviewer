"""
Dependency Impact Tool

Queries the knowledge graph to determine what modules depend on the modified files.
Implementation uses AST-based parsing or Graph DB (Neo4j) for production.
"""

from typing import Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class DependencyImpactResult(BaseModel):
    """Result from dependency impact analysis."""
    affected_modules: list[str] = Field(default_factory=list)
    impact_severity: str = "low"  # high, medium, low
    dependency_graph: dict[str, list[str]] = Field(default_factory=dict)


@tool
def dependency_impact_tool(
    modified_files: list[str],
    repo_root: str = ".",
) -> dict[str, Any]:
    """
    Analyze the dependency impact of modified files.
    
    Queries what other modules depend on the modified files to assess
    the blast radius of the change.
    
    Args:
        modified_files: List of file paths that were modified in the MR.
        repo_root: Root directory of the repository.
        
    Returns:
        Dictionary containing affected modules, impact severity, and dependency graph.
    """
    # TODO: Implement actual graph database query or AST parsing
    # For now, return a placeholder structure
    
    affected_modules: list[str] = []
    dependency_graph: dict[str, list[str]] = {}
    
    for file_path in modified_files:
        # Check for shared utilities - these affect everyone
        if "/shared/" in file_path or "/common/" in file_path or "/utils/" in file_path:
            affected_modules.append("*")  # Wildcard for "affects all"
            
        # Build a simple dependency graph placeholder
        dependency_graph[file_path] = []
    
    # Determine impact severity
    impact_severity = "low"
    if "*" in affected_modules:
        impact_severity = "high"
    elif len(affected_modules) > 5:
        impact_severity = "medium"
    
    return DependencyImpactResult(
        affected_modules=affected_modules,
        impact_severity=impact_severity,
        dependency_graph=dependency_graph,
    ).model_dump()


# Export the tool for LangGraph
DependencyImpactTool = dependency_impact_tool

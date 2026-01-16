"""
Design Patterns Tool

RAG-based retrieval of established design patterns for the module being reviewed.
Uses vector store (Chroma/Pinecone) with pattern embeddings.
"""

from typing import Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class DesignPatternResult(BaseModel):
    """Result from design pattern lookup."""
    pattern_name: str | None = None
    description: str = ""
    examples: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    confidence: float = 0.0


@tool
def design_pattern_tool(
    file_paths: list[str],
    code_snippets: list[str] | None = None,
) -> dict[str, Any]:
    """
    Retrieve the established design patterns for the given module.
    
    Queries a vector store to find documented patterns that should be
    followed in this part of the codebase.
    
    Args:
        file_paths: List of file paths being reviewed.
        code_snippets: Optional code snippets for semantic search.
        
    Returns:
        Dictionary containing pattern name, examples, and anti-patterns to avoid.
    """
    # TODO: Implement actual ChromaDB/Pinecone vector search
    # For now, return pattern hints based on file path heuristics
    
    pattern_name = None
    description = ""
    examples: list[str] = []
    anti_patterns: list[str] = []
    confidence = 0.0
    
    for file_path in file_paths:
        # Simple heuristics for common patterns
        if "/factory/" in file_path or "factory" in file_path.lower():
            pattern_name = "Factory Pattern"
            description = "Use Factory pattern for object creation in this module."
            anti_patterns = ["Avoid direct instantiation", "Do not use Singleton here"]
            confidence = 0.8
            break
            
        elif "/repository/" in file_path or "repo" in file_path.lower():
            pattern_name = "Repository Pattern"
            description = "Data access uses Repository pattern with interface abstraction."
            anti_patterns = ["No raw SQL in service layer", "Avoid ORM queries outside repos"]
            confidence = 0.85
            break
            
        elif "/services/" in file_path:
            pattern_name = "Service Layer"
            description = "Business logic encapsulated in service classes."
            anti_patterns = ["No HTTP/DB code in services", "Services should be stateless"]
            confidence = 0.75
            break
    
    return DesignPatternResult(
        pattern_name=pattern_name,
        description=description,
        examples=examples,
        anti_patterns=anti_patterns,
        confidence=confidence,
    ).model_dump()


# Export the tool for LangGraph
DesignPatternTool = design_pattern_tool

"""
User Preferences Tool

RAG-based search over historical PR comments to learn from past feedback.
Prevents the agent from repeating mistakes by consulting "Please don't do this" comments.

Uses ChromaDB vector store populated by scripts/seed_knowledge.py
"""

import os
from typing import Any

import chromadb
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field


# =============================================================================
# Data Models
# =============================================================================

class PastFeedback(BaseModel):
    """A single piece of past feedback from PR history."""
    pr_id: str
    comment: str
    sentiment: str  # positive, negative, neutral
    pattern_type: str  # e.g., "naming", "architecture", "performance"
    relevance_score: float = 0.0


class UserPreferencesResult(BaseModel):
    """Result from user preferences RAG search."""
    past_feedback: list[PastFeedback] = Field(default_factory=list)
    preference_signals: list[str] = Field(default_factory=list)
    mistakes_to_avoid: list[str] = Field(default_factory=list)
    patterns_encouraged: list[str] = Field(default_factory=list)


# =============================================================================
# ChromaDB Client (Lazy Initialization)
# =============================================================================

_chroma_client: chromadb.ClientAPI | None = None
_embeddings: OpenAIEmbeddings | None = None


def _get_chroma_collection() -> chromadb.Collection | None:
    """Get or create the ChromaDB collection for user preferences."""
    global _chroma_client
    
    persist_path = os.environ.get("CHROMA_PERSIST_PATH", "./data/chroma")
    collection_name = "user_preferences"
    
    try:
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=persist_path)
        
        # Try to get existing collection
        return _chroma_client.get_collection(name=collection_name)
    except Exception:
        # Collection doesn't exist yet (cold start)
        return None


def _get_embeddings() -> OpenAIEmbeddings:
    """Get or create the embeddings model."""
    global _embeddings
    
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    return _embeddings


# =============================================================================
# RAG Query Implementation
# =============================================================================

def _query_preferences(
    query_text: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Query the ChromaDB collection for relevant preference rules.
    
    Args:
        query_text: The code context or query to search for.
        n_results: Number of results to return.
        
    Returns:
        List of matching preference rules with metadata.
    """
    collection = _get_chroma_collection()
    
    if collection is None or collection.count() == 0:
        return []  # Cold start - no preferences yet
    
    # Generate embedding for query
    embeddings = _get_embeddings()
    query_embedding = embeddings.embed_query(query_text)
    
    # Query ChromaDB
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    
    # Format results
    preferences = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 1.0
            
            preferences.append({
                "rule": doc,
                "category": metadata.get("category", "unknown"),
                "confidence": metadata.get("confidence", 0.5),
                "source_mr_id": metadata.get("source_mr_id"),
                "relevance_score": 1.0 - distance,  # Convert distance to similarity
            })
    
    return preferences


# =============================================================================
# Tool Implementation
# =============================================================================

@tool
def user_preferences_tool(
    code_context: str,
    file_paths: list[str],
    author: str | None = None,
) -> dict[str, Any]:
    """
    Search historical PR comments for user preferences and past feedback.
    
    Enables dynamic alignment by learning from "LGTM", "Please don't do this",
    and other feedback patterns to avoid repeating past mistakes.
    
    Args:
        code_context: Code snippet or diff content for semantic search.
        file_paths: List of file paths being reviewed.
        author: Optional PR author to personalize feedback retrieval.
        
    Returns:
        Dictionary with past feedback, preference signals, and mistakes to avoid.
    """
    past_feedback: list[PastFeedback] = []
    preference_signals: list[str] = []
    mistakes_to_avoid: list[str] = []
    patterns_encouraged: list[str] = []
    
    # Query ChromaDB for relevant preferences
    query = f"{code_context}\n\nFiles: {', '.join(file_paths)}"
    preferences = _query_preferences(query, n_results=10)
    
    if preferences:
        # Categorize the retrieved preferences
        for pref in preferences:
            rule = pref["rule"]
            category = pref["category"]
            relevance = pref.get("relevance_score", 0.5)
            
            # Only include high-relevance results
            if relevance < 0.3:
                continue
            
            # Add to past feedback
            past_feedback.append(PastFeedback(
                pr_id=str(pref.get("source_mr_id", "unknown")),
                comment=rule,
                sentiment="instructive",
                pattern_type=category,
                relevance_score=relevance,
            ))
            
            # Categorize as signal or mistake based on rule content
            if any(word in rule.lower() for word in ["avoid", "don't", "never", "shouldn't"]):
                mistakes_to_avoid.append(rule)
            elif any(word in rule.lower() for word in ["prefer", "use", "should", "always"]):
                preference_signals.append(rule)
            else:
                patterns_encouraged.append(rule)
    
    # Fallback: Add file-path-based heuristics if no RAG results
    if not preferences:
        for file_path in file_paths:
            if "/api/" in file_path:
                mistakes_to_avoid.append("Avoid returning raw database IDs in API responses")
                preference_signals.append("Use DTOs for API response shaping")
                
            if "/tests/" in file_path:
                patterns_encouraged.append("Use descriptive test names following 'should_X_when_Y' pattern")
                mistakes_to_avoid.append("Avoid mocking too many dependencies")
                
            if "/models/" in file_path or "/entities/" in file_path:
                preference_signals.append("Validate all required fields in constructors")
                mistakes_to_avoid.append("Don't use mutable default arguments")
        
        # Generic fallback
        if not preference_signals:
            preference_signals = [
                "Prefer explicit over implicit",
                "Add docstrings for public methods",
            ]
    
    return UserPreferencesResult(
        past_feedback=[f.model_dump() for f in past_feedback],
        preference_signals=preference_signals,
        mistakes_to_avoid=mistakes_to_avoid,
        patterns_encouraged=patterns_encouraged,
    ).model_dump()


# Export the tool for LangGraph
UserPreferencesTool = user_preferences_tool

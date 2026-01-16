"""
CR Agent Main Entry Point

Initializes the agent, loads the system prompt, and provides
CLI interface for code review execution.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from cr_agent.graph import build_graph, review_merge_request
from cr_agent.state import FinalReview


# =============================================================================
# System Prompt Loading
# =============================================================================

def load_system_prompt(prompt_path: str | Path | None = None) -> str:
    """
    Load the orchestrator system prompt from file.
    
    Args:
        prompt_path: Path to the prompt file. Defaults to CR_ORCHESTRATOR_PROMPT.md
                    in the project root.
                    
    Returns:
        The system prompt content.
    """
    if prompt_path is None:
        # Default to project root
        prompt_path = Path(__file__).parent.parent.parent / "CR_ORCHESTRATOR_PROMPT.md"
    
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"System prompt not found: {path}")
    
    return path.read_text(encoding="utf-8")


# =============================================================================
# LLM Configuration
# =============================================================================

def create_llm(
    model: str = "gpt-4o",
    temperature: float = 0.1,
    **kwargs: Any,
) -> BaseChatModel:
    """
    Create and configure the LLM for code review.
    
    Uses low temperature for consistent, precise reviews.
    
    Args:
        model: Model name (default: gpt-4o).
        temperature: Sampling temperature (default: 0.1 for precision).
        **kwargs: Additional arguments for ChatOpenAI.
        
    Returns:
        Configured language model.
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        **kwargs,
    )


# =============================================================================
# Sample Data for Testing
# =============================================================================

SAMPLE_MR = {
    "mr_id": "MR-12345",
    "diff": """
diff --git a/src/api/users.py b/src/api/users.py
index abc1234..def5678 100644
--- a/src/api/users.py
+++ b/src/api/users.py
@@ -45,6 +45,15 @@ class UserController:
     def get_user(self, user_id: str) -> User:
-        return self.db.query(f"SELECT * FROM users WHERE id = {user_id}")
+        # Fixed SQL injection vulnerability
+        return self.db.query("SELECT * FROM users WHERE id = ?", [user_id])
     
+    def get_users_by_name(self, name: str) -> list[User]:
+        # New endpoint - potential N+1 issue
+        users = self.db.query("SELECT * FROM users WHERE name LIKE ?", [f"%{name}%"])
+        for user in users:
+            user.orders = self.db.query("SELECT * FROM orders WHERE user_id = ?", [user.id])
+        return users
+
diff --git a/src/services/order_service.py b/src/services/order_service.py
index 111222..333444 100644
--- a/src/services/order_service.py
+++ b/src/services/order_service.py
@@ -20,4 +20,12 @@ class OrderService:
+    def calculate_total(self, order_id: str) -> float:
+        order = self.order_repo.get(order_id)
+        total = 0
+        for item in order.items:
+            total += item.price * item.quantity
+        return total
""",
    "related_files": [
        "src/api/users.py",
        "src/services/order_service.py",
    ],
    "user_notes": "Fixed SQL injection and added new user search endpoint.",
}


# =============================================================================
# Main Execution
# =============================================================================

async def run_sample_review() -> FinalReview:
    """Run a sample code review for demonstration."""
    # Load system prompt (for reference - used by agents internally)
    try:
        system_prompt = load_system_prompt()
        print(f"✓ Loaded system prompt ({len(system_prompt)} chars)")
    except FileNotFoundError:
        print("⚠ System prompt not found, using defaults")
    
    # Create LLM
    llm = create_llm()
    print("✓ Initialized LLM (gpt-4o)")
    
    # Build the graph
    graph = build_graph(llm)
    print("✓ Built LangGraph workflow")
    
    # Run the review
    print("\n" + "=" * 60)
    print("Running Code Review...")
    print("=" * 60 + "\n")
    
    result = await review_merge_request(
        graph=graph,
        mr_id=SAMPLE_MR["mr_id"],
        diff=SAMPLE_MR["diff"],
        related_files=SAMPLE_MR["related_files"],
        user_notes=SAMPLE_MR["user_notes"],
    )
    
    return result


def format_review_output(review: FinalReview) -> str:
    """Format the review as markdown output."""
    output = []
    output.append("# Code Review Results\n")
    output.append(f"## 1. Executive Summary: **{review.executive_summary}**\n")
    output.append(f"## 2. Architectural Impact: **{review.architectural_impact}**\n")
    
    output.append("## 3. Critical Issues\n")
    if review.critical_issues:
        for issue in review.critical_issues:
            output.append(f"- {issue}\n")
    else:
        output.append("*No critical issues found.*\n")
    
    output.append("\n## 4. Suggestions\n")
    if review.suggestions:
        for suggestion in review.suggestions:
            output.append(f"- {suggestion}\n")
    else:
        output.append("*No additional suggestions.*\n")
    
    return "".join(output)


def main() -> None:
    """CLI entry point."""
    import sys
    
    if "--sample" in sys.argv:
        print("CR Agent System - Sample Review Mode\n")
        result = asyncio.run(run_sample_review())
        print(format_review_output(result))
    else:
        print("Usage: python -m cr_agent.main --sample")
        print("\nThis will run a sample code review to demonstrate the workflow.")


if __name__ == "__main__":
    main()

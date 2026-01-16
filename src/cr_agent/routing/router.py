"""
Router

Size/domain analysis and delegation decision logic.
Determines whether to use general_reviewer (lite mode) or spawn sub-agents.
"""

from typing import Any, Literal
import re

from cr_agent.state import AgentState
from cr_agent.routing.file_filter import FileFilter, filter_diff_for_agent


# Thresholds for delegation decision
MAX_LINES_FOR_LITE_MODE = 300
MAX_DOMAINS_FOR_LITE_MODE = 3

# Domain detection patterns
DOMAIN_PATTERNS: dict[str, list[str]] = {
    "database": ["**/db/**", "**/database/**", "**/models/**", "**/migrations/**"],
    "api": ["**/api/**", "**/routes/**", "**/controllers/**", "**/endpoints/**"],
    "frontend": ["**/frontend/**", "**/components/**", "**/pages/**", "*.tsx", "*.jsx"],
    "auth": ["**/auth/**", "**/authentication/**", "**/authorization/**"],
    "infrastructure": ["**/infra/**", "**/deploy/**", "**/k8s/**", "Dockerfile", "*.yaml"],
    "testing": ["**/tests/**", "**/test/**", "*.test.*", "*.spec.*"],
    "config": ["**/config/**", "**/settings/**", "*.env*", "*.json", "*.toml"],
    "services": ["**/services/**", "**/domain/**", "**/core/**"],
}


def count_diff_lines(diff: str) -> int:
    """Count the number of added/removed lines in a diff."""
    lines = diff.split("\n")
    count = 0
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            count += 1
        elif line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


def detect_domains(files: list[str]) -> list[str]:
    """Detect which domains are touched by the modified files."""
    detected: set[str] = set()
    file_filter = FileFilter()
    
    for file_path in files:
        for domain, patterns in DOMAIN_PATTERNS.items():
            if file_filter.matches_pattern(file_path, patterns):
                detected.add(domain)
    
    return list(detected)


def routing_decision_node(state: AgentState) -> dict[str, Any]:
    """
    Analyze the MR and decide whether to delegate to sub-agents.
    
    Decision criteria:
    - If >300 lines OR >3 domains: delegate to specialized sub-agents
    - Otherwise: use general_reviewer (lite mode)
    
    Also performs file filtering to prepare pruned context for each sub-agent.
    
    Args:
        state: Current agent state with diff and related_files.
        
    Returns:
        Updated state with routing decision and filtered diffs.
    """
    diff = state.get("diff", "")
    related_files = state.get("related_files", [])
    
    # Analyze the diff
    total_lines = count_diff_lines(diff)
    detected_domains = detect_domains(related_files)
    domain_count = len(detected_domains)
    
    # Make delegation decision
    should_delegate = (
        total_lines > MAX_LINES_FOR_LITE_MODE or
        domain_count > MAX_DOMAINS_FOR_LITE_MODE
    )
    
    result: dict[str, Any] = {
        "should_delegate": should_delegate,
        "total_lines": total_lines,
        "domain_count": domain_count,
        "detected_domains": detected_domains,
    }
    
    # If delegating, prepare filtered diffs for each sub-agent
    if should_delegate:
        result["security_diff"] = filter_diff_for_agent(
            diff, related_files, "security_agent"
        )
        result["performance_diff"] = filter_diff_for_agent(
            diff, related_files, "performance_agent"
        )
        result["domain_diff"] = filter_diff_for_agent(
            diff, related_files, "domain_agent"
        )
    
    return result

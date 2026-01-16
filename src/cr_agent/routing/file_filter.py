"""
File Filter

Context pruning logic that filters the diff for each sub-agent.
This is critical for high-throughput processing in monorepos.
"""

import fnmatch
from dataclasses import dataclass, field
from typing import Literal

from cr_agent.state import FilteredDiff


@dataclass
class FileFilterRule:
    """A single file filtering rule with include/exclude patterns."""
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


# Agent-specific filtering rules
AGENT_FILTER_RULES: dict[str, FileFilterRule] = {
    "security_agent": FileFilterRule(
        include_patterns=[
            "**/api/**",
            "**/auth/**",
            "**/backend/**",
            "**/server/**",
            "**/routes/**",
            "**/controllers/**",
            "**/middleware/**",
            "**/*.py",  # Python backend files
            "**/*.go",  # Go backend files
            "**/*.java",  # Java backend files
        ],
        exclude_patterns=[
            "*.css",
            "*.scss",
            "*.less",
            "*.test.*",
            "*.spec.*",
            "**/__tests__/**",
            "**/tests/**",
            "**/*.stories.*",
            "**/frontend/**",
            "**/static/**",
        ],
    ),
    "performance_agent": FileFilterRule(
        include_patterns=[
            "**/db/**",
            "**/database/**",
            "**/queries/**",
            "**/models/**",
            "**/repositories/**",
            "**/dao/**",
            "**/*repository*",
            "**/*query*",
            "**/*model*",
        ],
        exclude_patterns=[
            "*.md",
            "*.css",
            "*.scss",
            "**/__mocks__/**",
            "**/fixtures/**",
            "*.test.*",
            "*.spec.*",
        ],
    ),
    "domain_agent": FileFilterRule(
        include_patterns=[
            "**/services/**",
            "**/domain/**",
            "**/core/**",
            "**/business/**",
            "**/usecases/**",
            "**/entities/**",
            "**/*service*",
            "**/*usecase*",
        ],
        exclude_patterns=[
            "**/tests/**",
            "**/config/**",
            "**/__tests__/**",
            "*.test.*",
            "*.spec.*",
            "**/infrastructure/**",
        ],
    ),
}


class FileFilter:
    """
    Filters files and diff content for specific sub-agents.
    
    Ensures each agent only receives the relevant subset of files,
    reducing token usage and improving review quality.
    """
    
    def __init__(self, rules: dict[str, FileFilterRule] | None = None):
        self.rules = rules or AGENT_FILTER_RULES
    
    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool:
        """Check if a file path matches any of the given glob patterns."""
        for pattern in patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True
            # Also check just the filename
            filename = file_path.split("/")[-1]
            if fnmatch.fnmatch(filename, pattern):
                return True
        return False
    
    def should_include_file(
        self,
        file_path: str,
        agent_type: Literal["security_agent", "performance_agent", "domain_agent"],
    ) -> bool:
        """
        Determine if a file should be included for the given agent.
        
        A file is included if:
        1. It matches at least one include pattern, AND
        2. It does NOT match any exclude pattern
        """
        rule = self.rules.get(agent_type)
        if not rule:
            return True  # No rule = include everything
        
        # Check exclusions first (they take priority)
        if self.matches_pattern(file_path, rule.exclude_patterns):
            return False
        
        # Check inclusions
        if rule.include_patterns:
            return self.matches_pattern(file_path, rule.include_patterns)
        
        return True  # No include patterns = include everything not excluded
    
    def filter_files(
        self,
        files: list[str],
        agent_type: Literal["security_agent", "performance_agent", "domain_agent"],
    ) -> list[str]:
        """Filter a list of files for the given agent type."""
        return [f for f in files if self.should_include_file(f, agent_type)]


def filter_diff_for_agent(
    full_diff: str,
    files: list[str],
    agent_type: Literal["security_agent", "performance_agent", "domain_agent"],
    file_filter: FileFilter | None = None,
) -> FilteredDiff:
    """
    Create a filtered diff for a specific agent.
    
    Args:
        full_diff: The complete diff content.
        files: List of all modified files.
        agent_type: The agent to filter for.
        file_filter: Optional custom FileFilter instance.
        
    Returns:
        FilteredDiff with only the relevant files and diff content.
    """
    filter_instance = file_filter or FileFilter()
    filtered_files = filter_instance.filter_files(files, agent_type)
    
    # TODO: In production, parse the diff and extract only the hunks
    # for the filtered files. For now, we pass the full diff with
    # a note about which files are relevant.
    
    # Simple heuristic: count lines in filtered files
    total_lines = 0
    for file in filtered_files:
        # Estimate lines based on diff content
        # In production, parse the actual diff hunks
        total_lines += full_diff.count(f"+++ {file}") * 50  # Rough estimate
    
    return FilteredDiff(
        files=filtered_files,
        diff_content=full_diff if filtered_files else "",
        total_lines=total_lines or len(filtered_files) * 25,
    )

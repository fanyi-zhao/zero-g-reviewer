"""
Tests for routing logic and file filtering.
"""

import pytest
from cr_agent.routing.file_filter import FileFilter, filter_diff_for_agent, AGENT_FILTER_RULES
from cr_agent.routing.router import (
    routing_decision_node,
    count_diff_lines,
    detect_domains,
    MAX_LINES_FOR_LITE_MODE,
    MAX_DOMAINS_FOR_LITE_MODE,
)
from cr_agent.state import AgentState


class TestFileFilter:
    """Tests for FileFilter class."""
    
    @pytest.fixture
    def file_filter(self):
        return FileFilter()
    
    def test_security_agent_includes_api_files(self, file_filter):
        assert file_filter.should_include_file("src/api/users.py", "security_agent")
        assert file_filter.should_include_file("backend/auth/login.py", "security_agent")
    
    def test_security_agent_excludes_css(self, file_filter):
        assert not file_filter.should_include_file("styles/main.css", "security_agent")
        assert not file_filter.should_include_file("src/api/users.test.py", "security_agent")
    
    def test_performance_agent_includes_db_files(self, file_filter):
        assert file_filter.should_include_file("src/db/queries.py", "performance_agent")
        assert file_filter.should_include_file("src/models/user_model.py", "performance_agent")
    
    def test_performance_agent_excludes_markdown(self, file_filter):
        assert not file_filter.should_include_file("README.md", "performance_agent")
    
    def test_domain_agent_includes_services(self, file_filter):
        assert file_filter.should_include_file("src/services/order.py", "domain_agent")
        assert file_filter.should_include_file("core/business/rules.py", "domain_agent")
    
    def test_domain_agent_excludes_tests(self, file_filter):
        assert not file_filter.should_include_file("tests/test_order.py", "domain_agent")
    
    def test_filter_files_list(self, file_filter):
        files = [
            "src/api/users.py",
            "styles/main.css",
            "src/api/auth.py",
            "tests/test_api.py",
        ]
        filtered = file_filter.filter_files(files, "security_agent")
        assert "src/api/users.py" in filtered
        assert "src/api/auth.py" in filtered
        assert "styles/main.css" not in filtered


class TestFilterDiffForAgent:
    """Tests for filter_diff_for_agent function."""
    
    def test_filters_files_correctly(self):
        diff = "+ added line\n- removed line"
        files = ["src/api/users.py", "styles/main.css"]
        
        result = filter_diff_for_agent(diff, files, "security_agent")
        
        assert "src/api/users.py" in result.files
        assert "styles/main.css" not in result.files
    
    def test_empty_result_for_no_matching_files(self):
        diff = "+ added line"
        files = ["styles/main.css", "README.md"]
        
        result = filter_diff_for_agent(diff, files, "security_agent")
        
        assert result.files == []
        assert result.diff_content == ""


class TestCountDiffLines:
    """Tests for diff line counting."""
    
    def test_counts_additions(self):
        diff = "+line1\n+line2\n line3\n"
        assert count_diff_lines(diff) == 2
    
    def test_counts_deletions(self):
        diff = "-line1\n-line2\n line3\n"
        assert count_diff_lines(diff) == 2
    
    def test_ignores_header_lines(self):
        diff = "+++ a/file.py\n--- b/file.py\n+actual change\n"
        assert count_diff_lines(diff) == 1
    
    def test_mixed_changes(self):
        diff = "+added\n-removed\n context\n+another"
        assert count_diff_lines(diff) == 3


class TestDetectDomains:
    """Tests for domain detection."""
    
    def test_detects_database_domain(self):
        files = ["src/db/connection.py", "migrations/001.sql"]
        domains = detect_domains(files)
        assert "database" in domains
    
    def test_detects_api_domain(self):
        files = ["src/api/users.py", "routes/auth.py"]
        domains = detect_domains(files)
        assert "api" in domains
    
    def test_detects_multiple_domains(self):
        files = ["src/api/users.py", "src/db/queries.py", "frontend/App.tsx"]
        domains = detect_domains(files)
        assert len(domains) >= 2
    
    def test_empty_files_returns_empty_domains(self):
        domains = detect_domains([])
        assert domains == []


class TestRoutingDecisionNode:
    """Tests for routing decision logic."""
    
    def test_small_pr_does_not_delegate(self):
        state: AgentState = {
            "diff": "+line1\n+line2\n",  # 2 lines
            "related_files": ["src/api/users.py"],
        }
        result = routing_decision_node(state)
        
        assert result["should_delegate"] is False
        assert result["total_lines"] == 2
    
    def test_large_pr_delegates(self):
        # Create a diff with >300 lines
        large_diff = "\n".join([f"+line{i}" for i in range(350)])
        
        state: AgentState = {
            "diff": large_diff,
            "related_files": ["src/api/users.py"],
        }
        result = routing_decision_node(state)
        
        assert result["should_delegate"] is True
        assert result["total_lines"] > MAX_LINES_FOR_LITE_MODE
    
    def test_many_domains_delegates(self):
        # Files touching many domains (>3 to trigger delegation)
        state: AgentState = {
            "diff": "+line1\n",
            "related_files": [
                "src/api/users.py",
                "src/db/queries.py",
                "frontend/App.tsx",
                "config/settings.py",
                "src/auth/login.py",
            ],
        }
        result = routing_decision_node(state)
        
        assert result["domain_count"] > MAX_DOMAINS_FOR_LITE_MODE
        assert result["should_delegate"] is True
    
    def test_creates_filtered_diffs_when_delegating(self):
        large_diff = "\n".join([f"+line{i}" for i in range(350)])
        
        state: AgentState = {
            "diff": large_diff,
            "related_files": ["src/api/users.py", "src/db/queries.py"],
        }
        result = routing_decision_node(state)
        
        assert "security_diff" in result
        assert "performance_diff" in result
        assert "domain_diff" in result

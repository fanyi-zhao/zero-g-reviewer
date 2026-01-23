"""Core agent implementation using Claude API with tool use."""

import json
import logging
from typing import Any
from pathlib import Path

from anthropic import Anthropic

from .config import ReviewConfig, Settings
from .context import (
    ReviewPlan,
    chunk_diff,
    create_review_plan,
    identify_hotspots,
    summarize_changes,
)
from .git_ops import GitError, GitRepository
from .gitlab_client import GitLabClient
from .models import (
    ChangedFile,
    Commit,
    Confidence,
    Finding,
    MergeRequestInfo,
    Recommendation,
    ReviewResult,
    Severity,
)
from .prompts import (
    DETAILED_REVIEW_PROMPT,
    HOTSPOT_INVESTIGATION_PROMPT,
    INITIAL_ANALYSIS_PROMPT,
    SYNTHESIS_PROMPT,
    SYSTEM_PROMPT,
    format_commits_summary,
    format_pipeline_status,
)
from .tools import TOOL_DEFINITIONS, ToolExecutor, format_tool_result

logger = logging.getLogger(__name__)


class ReviewAgent:
    """Code review agent powered by Claude."""

    def __init__(
        self,
        config: ReviewConfig,
        gitlab_client: GitLabClient,
        repo: GitRepository,
    ):
        self.config = config
        self.gitlab = gitlab_client
        self.repo = repo
        self.settings = config.settings

        # Initialize Anthropic client
        self.anthropic = Anthropic(
            api_key=self.settings.llm_api_key.get_secret_value(),
            base_url=self.settings.llm_base_url,
        )

        # Initialize tool executor
        self.tool_executor = ToolExecutor(config, gitlab_client, repo)

        # Load custom instructions
        self.system_prompt = self._load_system_prompt()

        # Review state
        self.mr_info: MergeRequestInfo | None = None
        self.changes: list[ChangedFile] = []
        self.commits: list[Commit] = []
        self.review_plan: ReviewPlan | None = None
        self.findings: list[Finding] = []
        self.analysis_notes: list[str] = []

    def _load_system_prompt(self) -> str:
        """Load and format the system prompt with custom instructions."""
        custom_instructions = ""
        
        if self.settings.extra_instructions:
            try:
                # Try to find instructions file in repo
                instructions_path = Path(self.config.local_repo_path) / self.settings.extra_instructions
                if instructions_path.exists() and instructions_path.is_file():
                    custom_instructions = instructions_path.read_text(encoding="utf-8")
                    logger.info(f"Loaded custom instructions from {self.settings.extra_instructions}")
                else:
                    logger.debug(f"Custom instructions file not found: {self.settings.extra_instructions}")
            except Exception as e:
                logger.warning(f"Failed to load custom instructions: {e}")

        if not custom_instructions:
            custom_instructions = "No specific custom guidelines provided."

        return SYSTEM_PROMPT.format(custom_instructions=custom_instructions)

    def run(self) -> ReviewResult:
        """
        Execute the complete review process.

        Returns:
            ReviewResult with all findings and recommendations
        """
        logger.info(f"Starting review for MR !{self.config.mr_iid}")

        # Phase 1: Data Collection
        self._collect_data()

        # Phase 2: Create Review Plan
        self._create_plan()

        # Phase 3: Initial Analysis (Pass A)
        self._initial_analysis()

        # Phase 4: Detailed Review (Pass B)
        self._detailed_review()

        # Phase 5: Hotspot Investigation
        self._investigate_hotspots()

        # Phase 6: Synthesize Results
        result = self._synthesize_review()

        logger.info(f"Review complete: {result.recommendation.value}")
        return result

    def _collect_data(self) -> None:
        """Collect MR data from GitLab and local repo."""
        logger.info("Collecting MR data...")

        # Get MR metadata
        self.mr_info = self.gitlab.get_merge_request(self.config.mr_iid)
        logger.info(f"MR: {self.mr_info.title}")

        # Override branches if specified
        source_branch = self.config.source_branch or self.mr_info.source_branch
        target_branch = self.config.target_branch or self.mr_info.target_branch

        # Get commits
        self.commits = self.gitlab.get_merge_request_commits(self.config.mr_iid)
        logger.info(f"Commits: {len(self.commits)}")

        # Try to get diff from local repo first
        try:
            # Fetch latest from remote
            self.repo.fetch()

            # Check if branches exist
            source_exists = self.repo.branch_exists(source_branch)
            target_exists = self.repo.branch_exists(target_branch)

            if source_exists and target_exists:
                logger.info("Using local git for diff")
                # We'll use local git for additional context
            else:
                logger.info("Branches not found locally, will use GitLab API for diffs")

        except GitError as e:
            logger.warning(f"Local git operations failed: {e}")

        # Get changes from GitLab API (most reliable source for MR changes)
        self.changes = self.gitlab.get_merge_request_changes(
            self.config.mr_iid,
            max_files=self.config.max_files,
        )
        logger.info(f"Changed files: {len(self.changes)}")

    def _create_plan(self) -> None:
        """Create a review plan based on the changes."""
        logger.info("Creating review plan...")

        self.review_plan = create_review_plan(
            files=self.changes,
            max_files=self.config.max_files,
            max_chars=self.config.max_diff_chars,
        )

        if self.config.verbosity >= 2:
            logger.info(self.review_plan.summary())

    def _initial_analysis(self) -> None:
        """Perform initial analysis (Pass A) - quick scan."""
        logger.info("Performing initial analysis...")

        if not self.mr_info or not self.review_plan:
            raise RuntimeError("Data collection incomplete")

        # Build the initial prompt
        files_summary = summarize_changes(self.review_plan.files_to_review)
        commits_summary = format_commits_summary(self.commits)
        pipeline_status = format_pipeline_status(self.mr_info.pipeline_status)

        prompt = INITIAL_ANALYSIS_PROMPT.format(
            mr_title=self.mr_info.title,
            mr_author=self.mr_info.author,
            source_branch=self.mr_info.source_branch,
            target_branch=self.mr_info.target_branch,
            mr_state=self.mr_info.state,
            pipeline_status=pipeline_status,
            mr_description=self.mr_info.description or "*No description provided*",
            commits_summary=commits_summary,
            file_count=len(self.review_plan.files_to_review),
            files_summary=files_summary,
        )

        # Run through Claude with tool use
        response = self._run_agent_loop(prompt)
        self.analysis_notes.append(f"## Initial Analysis\n\n{response}")

    def _detailed_review(self) -> None:
        """Perform detailed review (Pass B) - file by file analysis."""
        logger.info("Performing detailed file review...")

        if not self.review_plan:
            return

        for file in self.review_plan.files_to_review:
            if not file.diff:
                continue

            # Chunk if necessary
            chunks = chunk_diff(file, max_chunk_chars=10000)

            for chunk in chunks:
                if self.config.verbosity >= 2:
                    chunk_info = (
                        f" (chunk {chunk.chunk_index + 1}/{chunk.total_chunks})"
                        if chunk.total_chunks > 1
                        else ""
                    )
                    logger.info(f"Reviewing: {file.path}{chunk_info}")

                prompt = DETAILED_REVIEW_PROMPT.format(
                    file_path=file.path,
                    change_type=file.change_type,
                    line_count=file.total_changes,
                    diff_content=chunk.content[:8000],  # Truncate if very long
                )

                response = self._run_agent_loop(prompt, max_iterations=3)

                # Parse findings from response
                file_findings = self._parse_findings(response, file.path)
                self.findings.extend(file_findings)

                self.analysis_notes.append(f"### {file.path}\n\n{response}")

    def _investigate_hotspots(self) -> None:
        """Investigate identified hotspots with deeper analysis."""
        logger.info("Investigating hotspots...")

        if not self.review_plan:
            return

        hotspots = identify_hotspots(self.review_plan.files_to_review)

        # Limit hotspots to avoid excessive API calls
        hotspots = hotspots[:5]

        for file_path, reason in hotspots:
            file = next((f for f in self.review_plan.files_to_review if f.path == file_path), None)
            if not file:
                continue

            if self.config.verbosity >= 2:
                logger.info(f"Hotspot investigation: {file_path} ({reason})")

            prompt = HOTSPOT_INVESTIGATION_PROMPT.format(
                file_path=file_path,
                reason=reason,
                diff_content=file.diff[:5000] if file.diff else "*No diff*",
            )

            response = self._run_agent_loop(prompt, max_iterations=5)

            # Parse additional findings
            hotspot_findings = self._parse_findings(response, file_path)
            self.findings.extend(hotspot_findings)

            self.analysis_notes.append(f"### Hotspot: {file_path}\n\n{response}")

    def _synthesize_review(self) -> ReviewResult:
        """Synthesize all findings into final review."""
        logger.info("Synthesizing review...")

        if not self.review_plan:
            raise RuntimeError("Review plan not created")

        files_reviewed = "\n".join(f"- `{f.path}`" for f in self.review_plan.files_to_review[:30])
        if len(self.review_plan.files_to_review) > 30:
            files_reviewed += f"\n- *...and {len(self.review_plan.files_to_review) - 30} more*"

        # Prepare context for synthesis
        # Instead of generic analysis notes, we feed the structured findings
        # to the LLM so it can write a high-quality executive summary.
        findings_summary = []
        for i, f in enumerate(self.findings, 1):
            findings_summary.append(f"{i}. [{f.severity.value.upper()}] {f.title} ({f.file_path})")
            # Include first line of description for context
            first_line = f.description.split('\n')[0][:100]
            findings_summary.append(f"   {first_line}...")

        # Include initial analysis for context
        initial_context = self.analysis_notes[0] if self.analysis_notes else ""
        
        # Combine into a token-efficient context
        analysis_context = f"""
Initial Analysis:
{initial_context}

Identified Findings ({len(self.findings)}):
{chr(10).join(findings_summary)}
"""
        
        prompt = SYNTHESIS_PROMPT.format(
            files_reviewed=files_reviewed,
            analysis_notes=analysis_context,
        )

        response = self._run_agent_loop(prompt)

        # Parse final review from response
        result = self._parse_final_review(response)

        return result

    def _run_agent_loop(self, user_prompt: str, max_iterations: int = 10) -> str:
        """
        Run the agent loop with tool use.

        Args:
            user_prompt: The user message to send
            max_iterations: Maximum tool use iterations

        Returns:
            Final text response from the model
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        for iteration in range(max_iterations):
            # Call Claude
            response = self.anthropic.messages.create(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                system=self.system_prompt,
                tools=TOOL_DEFINITIONS,  # type: ignore
                messages=messages,
            )

            # Check if we're done (no tool use)
            if response.stop_reason == "end_turn":
                # Extract text content
                text_parts = [block.text for block in response.content if hasattr(block, "text")]
                return "\n".join(text_parts)

            # Process tool calls
            tool_results = []
            text_parts = []

            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    if self.config.verbosity >= 3:
                        logger.debug(f"Tool call: {tool_name}({json.dumps(tool_input)[:100]}...)")

                    # Execute the tool
                    result = self.tool_executor.execute(tool_name, tool_input)  # type: ignore
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": format_tool_result(result),
                        }
                    )

            # Add assistant message and tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # If we hit max iterations, return what we have
        logger.warning(f"Hit max iterations ({max_iterations}) in agent loop")
        return "\n".join(text_parts) if text_parts else "Analysis incomplete due to iteration limit."

    def _parse_findings(self, response: str, default_file: str) -> list[Finding]:
        """
        Parse findings from model response.

        This is a heuristic parser that looks for common patterns in the response.
        """
        findings: list[Finding] = []

        # Look for severity markers
        lines = response.split("\n")

        current_severity: Severity | None = None
        current_finding_lines: list[str] = []

        for line in lines:
            line_lower = line.lower()

            # Detect severity headers
            if "blocker" in line_lower and (":" in line or "#" in line):
                if current_finding_lines and current_severity:
                    findings.append(
                        self._create_finding(current_severity, current_finding_lines, default_file)
                    )
                current_severity = Severity.BLOCKER
                current_finding_lines = []
            elif "major" in line_lower and (":" in line or "#" in line):
                if current_finding_lines and current_severity:
                    findings.append(
                        self._create_finding(current_severity, current_finding_lines, default_file)
                    )
                current_severity = Severity.MAJOR
                current_finding_lines = []
            elif "minor" in line_lower and (":" in line or "#" in line):
                if current_finding_lines and current_severity:
                    findings.append(
                        self._create_finding(current_severity, current_finding_lines, default_file)
                    )
                current_severity = Severity.MINOR
                current_finding_lines = []
            elif "nit" in line_lower and (":" in line or "#" in line):
                if current_finding_lines and current_severity:
                    findings.append(
                        self._create_finding(current_severity, current_finding_lines, default_file)
                    )
                current_severity = Severity.NIT
                current_finding_lines = []
            elif current_severity:
                current_finding_lines.append(line)

        # Don't forget the last finding
        if current_finding_lines and current_severity:
            findings.append(
                self._create_finding(current_severity, current_finding_lines, default_file)
            )

        return findings

    def _create_finding(
        self,
        severity: Severity,
        lines: list[str],
        default_file: str,
    ) -> Finding:
        """Create a Finding from parsed lines."""
        content = "\n".join(lines).strip()

        # Try to extract title from first non-empty line
        title = "Issue found"
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                # Remove leading bullets/markers
                title = line.lstrip("- *").split(":")[0].strip()[:80]
                break

        return Finding(
            severity=severity,
            title=title,
            description=content,
            file_path=default_file,
            confidence=Confidence.MEDIUM,
        )

    def _parse_final_review(self, response: str) -> ReviewResult:
        """Parse the final synthesis response into a ReviewResult."""
        # Determine recommendation
        response_lower = response.lower()

        if "request changes" in response_lower or "request_changes" in response_lower:
            recommendation = Recommendation.REQUEST_CHANGES
        elif "approve" in response_lower and "blocker" not in response_lower:
            recommendation = Recommendation.APPROVE
        else:
            recommendation = Recommendation.COMMENT

        # Extract summary (first paragraph after "summary" if present)
        summary = "Code review completed."
        if "summary" in response_lower:
            idx = response_lower.index("summary")
            summary_section = response[idx:].split("\n\n")[0:2]
            summary = " ".join(summary_section).strip()[:500]

        # Extract risks
        risks: list[str] = []
        if "risk" in response_lower:
            # Look for bullet points after "risk"
            for line in response.split("\n"):
                if line.strip().startswith("- ") and "risk" in line.lower():
                    risks.append(line.strip().lstrip("- "))
        risks = risks[:5]  # Limit

        # Get files reviewed
        files_reviewed = [f.path for f in (self.review_plan.files_to_review if self.review_plan else [])]

        # Extract test commands
        test_commands: list[str] = []
        if "test" in response_lower or "verify" in response_lower:
            for line in response.split("\n"):
                if line.strip().startswith("```") or "run" in line.lower():
                    if any(cmd in line for cmd in ["pytest", "npm test", "make test", "go test"]):
                        test_commands.append(line.strip().strip("`"))
        if not test_commands:
            test_commands = ["# Run relevant tests for changed files"]

        # Default checklist
        checklist = [
            "All tests pass",
            "Code has been self-reviewed",
            "Changes have been tested locally",
            "Documentation updated if needed",
            "No secrets or sensitive data exposed",
        ]

        return ReviewResult(
            recommendation=recommendation,
            summary=summary,
            risks=risks,
            files_reviewed=files_reviewed,
            findings=self.findings,
            test_commands=test_commands,
            checklist=checklist,
        )


def run_review(
    mr_iid: int,
    local_repo_path: str,
    settings: Settings | None = None,
    target_branch: str | None = None,
    source_branch: str | None = None,
) -> ReviewResult:
    """
    Run a code review for a merge request.

    Args:
        mr_iid: Merge request IID
        local_repo_path: Path to local git repository
        settings: Optional Settings instance
        target_branch: Optional target branch override
        source_branch: Optional source branch override

    Returns:
        ReviewResult with findings and recommendations
    """
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]

    config = ReviewConfig(
        mr_iid=mr_iid,
        local_repo_path=local_repo_path,
        target_branch=target_branch,
        source_branch=source_branch,
        settings=settings,
    )

    with GitLabClient(
        base_url=settings.gitlab_base_url,
        token=settings.gitlab_token.get_secret_value(),
        project_id=settings.project_id,
    ) as gitlab:
        repo = GitRepository(local_repo_path)
        agent = ReviewAgent(config, gitlab, repo)
        return agent.run()

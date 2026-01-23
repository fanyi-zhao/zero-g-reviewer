from cr_agent.agent import run_review
from cr_agent.config import Settings

settings = Settings(
    gitlab_base_url="https://gitlab.com",
    gitlab_token="glpat-Kqd7D7Ia2lB09Drm4KKlom86MQp1OmpyMXdjCw.01.12161k7vk",
    project_id="77926863",
    llm_api_key="3992085bf7bb4417b70e8fe263793333.5GjCtLIYLbYh3T4sg3FYieS_",
    llm_base_url="https://api.anthropic.com",  # Change this to your provider's URL
    llm_model="claude-3-5-sonnet-20240620",    # Change this to your preferred model)
)

result = run_review(
    mr_iid=42,
    local_repo_path="/path/to/repo",
    settings=settings,
)

# Get the GitLab-ready comment
comment = result.to_gitlab_comment()
print(comment)

# Or access structured data
print(f"Recommendation: {result.recommendation}")
print(f"Findings: {len(result.findings)}")
for finding in result.findings:
    print(f"  - [{finding.severity.value}] {finding.title}")
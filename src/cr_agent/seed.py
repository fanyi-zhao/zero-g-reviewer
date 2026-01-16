#!/usr/bin/env python3
"""
Knowledge Seeding Script (Multi-Provider)

Solves the "Cold Start" problem by populating the UserPreferencesTool
vector store with historical PR feedback from GitLab or GitHub.

Usage (GitLab):
    export GITLAB_URL="https://gitlab.example.com"
    export GITLAB_TOKEN="your-access-token"
    export GITLAB_PROJECT_ID="12345"
    export OPENAI_API_KEY="your-openai-key"
    python scripts/seed_knowledge.py

Usage (GitHub):
    export GITHUB_TOKEN="your-github-token"
    export GITHUB_REPO="owner/repo"  # e.g., "langchain-ai/langchain"
    export OPENAI_API_KEY="your-openai-key"
    python scripts/seed_knowledge.py
"""

import os
import sys
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import chromadb
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


# =============================================================================
# Configuration
# =============================================================================

class Provider(Enum):
    """Supported code repository providers."""
    GITLAB = "gitlab"
    GITHUB = "github"


@dataclass
class Config:
    """Configuration from environment variables."""
    provider: Provider
    openai_api_key: str
    chroma_persist_path: str = "./data/chroma"
    collection_name: str = "user_preferences"
    max_mrs: int = 20
    
    # GitLab-specific
    gitlab_url: str | None = None
    gitlab_token: str | None = None
    gitlab_project_id: str | None = None
    
    # GitHub-specific
    github_token: str | None = None
    github_repo: str | None = None


def detect_provider() -> Provider | None:
    """Detect which provider's environment variables are set."""
    has_gitlab = all([
        os.environ.get("GITLAB_URL"),
        os.environ.get("GITLAB_TOKEN"),
        os.environ.get("GITLAB_PROJECT_ID"),
    ])
    
    has_github = all([
        os.environ.get("GITHUB_TOKEN"),
        os.environ.get("GITHUB_REPO"),
    ])
    
    if has_gitlab and has_github:
        print("❌ Ambiguous configuration: Both GitLab and GitHub variables are set.")
        print("   Please set only ONE provider's environment variables.")
        sys.exit(1)
    elif has_gitlab:
        return Provider.GITLAB
    elif has_github:
        return Provider.GITHUB
    else:
        return None


def load_config(
    github_repo: str | None = None,
    github_token: str | None = None,
    gitlab_project_id: str | None = None,
    gitlab_token: str | None = None,
) -> Config:
    """Load configuration from environment variables with optional overrides."""
    # Check for OpenAI API key first
    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Missing required: OPENAI_API_KEY")
        sys.exit(1)
    
    # 1. Determine Provider
    # Priority: explicit args > env vars
    has_gitlab = (gitlab_project_id is not None) or all([
        os.environ.get("GITLAB_URL"),
        os.environ.get("GITLAB_TOKEN"),
        os.environ.get("GITLAB_PROJECT_ID"),
    ])
    
    has_github = (github_repo is not None) or all([
        os.environ.get("GITHUB_TOKEN"),
        os.environ.get("GITHUB_REPO"),
    ])
    
    provider = None
    if has_gitlab and has_github:
         # If args specify one, choose that. Else error.
         if gitlab_project_id and not github_repo:
             provider = Provider.GITLAB
         elif github_repo and not gitlab_project_id:
             provider = Provider.GITHUB
         else:
            print("❌ Ambiguous configuration: Both GitLab and GitHub variables/args are set.")
            print("   Please set only ONE provider's environment variables or arguments.")
            sys.exit(1)
    elif has_gitlab:
        provider = Provider.GITLAB
    elif has_github:
        provider = Provider.GITHUB
    
    if provider is None:
        print("❌ No provider configuration found.\n")
        print("For GitLab, set:")
        print("  GITLAB_URL        - GitLab instance URL")
        print("  GITLAB_TOKEN      - Personal access token with api scope")
        print("  GITLAB_PROJECT_ID - Numeric project ID")
        print("\nFor GitHub, set:")
        print("  GITHUB_TOKEN      - GitHub personal access token")
        print("  GITHUB_REPO       - Repository (e.g., 'owner/repo')")
        print("\nAlways required:")
        print("  OPENAI_API_KEY    - OpenAI API key for LLM distillation")
        sys.exit(1)
    
    config = Config(
        provider=provider,
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )
    
    if provider == Provider.GITLAB:
        config.gitlab_url = os.environ.get("GITLAB_URL")
        config.gitlab_token = gitlab_token or os.environ.get("GITLAB_TOKEN")
        config.gitlab_project_id = gitlab_project_id or os.environ.get("GITLAB_PROJECT_ID")
    else:  # GitHub
        config.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        config.github_repo = github_repo or os.environ.get("GITHUB_REPO")
    
    return config


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class MergeItem:
    """Standardized representation of a merged PR/MR."""
    id: int
    title: str
    author: str
    url: str
    provider: Provider
    raw: Any = field(repr=False)  # Original object from provider


class DiscussionThread(BaseModel):
    """A discussion thread from a merge request."""
    mr_id: int
    mr_title: str
    file_path: str | None = None
    original_comment: str
    resolution_comment: str | None = None
    resulted_in_change: bool = False


class PreferenceRule(BaseModel):
    """A distilled preference rule from a discussion."""
    rule: str = Field(description="The distilled coding preference or standard")
    category: str = Field(description="Category: style, architecture, security, performance, naming")
    confidence: float = Field(description="Confidence score 0.0-1.0")
    source_mr_id: int = 0
    original_comment: str = ""


# =============================================================================
# Abstract Base Class for Harvesters
# =============================================================================

class CodeRepoHarvester(ABC):
    """
    Abstract base class for code repository harvesters.
    
    Defines the contract for fetching merged items and extracting discussions
    from different code hosting platforms.
    """
    
    @abstractmethod
    def fetch_merged_mrs(self) -> list[MergeItem]:
        """
        Fetch the last N merged merge requests/pull requests.
        
        Returns:
            List of standardized MergeItem objects.
        """
        pass
    
    @abstractmethod
    def extract_discussions(self, item: MergeItem) -> list[DiscussionThread]:
        """
        Extract discussion threads from a merge item.
        
        Args:
            item: The merge item to extract discussions from.
            
        Returns:
            List of DiscussionThread objects representing actionable discussions.
        """
        pass


# =============================================================================
# GitLab Implementation
# =============================================================================

class GitLabHarvester(CodeRepoHarvester):
    """Fetches and processes MR discussions from GitLab."""
    
    def __init__(self, config: Config):
        import gitlab
        
        self.gl = gitlab.Gitlab(
            url=config.gitlab_url,
            private_token=config.gitlab_token,
        )
        self.project = self.gl.projects.get(config.gitlab_project_id)
        self.max_mrs = config.max_mrs
    
    def fetch_merged_mrs(self) -> list[MergeItem]:
        """Fetch the last N merged merge requests from GitLab."""
        print(f"📥 Fetching last {self.max_mrs} merged MRs from GitLab...")
        
        mrs = self.project.mergerequests.list(
            state="merged",
            order_by="updated_at",
            sort="desc",
            per_page=self.max_mrs,
        )
        
        items = [
            MergeItem(
                id=mr.iid,
                title=mr.title,
                author=mr.author.get("username", "unknown") if mr.author else "unknown",
                url=mr.web_url,
                provider=Provider.GITLAB,
                raw=mr,
            )
            for mr in mrs
        ]
        
        print(f"   Found {len(items)} merged MRs")
        return items
    
    def extract_discussions(self, item: MergeItem) -> list[DiscussionThread]:
        """Extract discussion threads from a GitLab MR."""
        threads: list[DiscussionThread] = []
        mr = item.raw
        
        try:
            discussions = mr.discussions.list(all=True)
        except Exception as e:
            print(f"   ⚠ Could not fetch discussions for MR !{item.id}: {e}")
            return threads
        
        for discussion in discussions:
            notes = discussion.attributes.get("notes", [])
            if not notes:
                continue
            
            # Get the initial comment
            first_note = notes[0]
            if first_note.get("system", False):
                continue  # Skip system-generated notes
            
            original_comment = first_note.get("body", "")
            file_path = first_note.get("position", {}).get("new_path")
            
            # Check if discussion was resolved
            is_resolved = discussion.attributes.get("resolved", False)
            
            # Get resolution comment if exists
            resolution_comment = None
            if len(notes) > 1:
                last_note = notes[-1]
                if not last_note.get("system", False):
                    resolution_comment = last_note.get("body", "")
            
            # A discussion "resulted in change" if resolved or has back-and-forth
            resulted_in_change = is_resolved or len(notes) > 1
            
            if resulted_in_change and len(original_comment) > 20:
                threads.append(DiscussionThread(
                    mr_id=item.id,
                    mr_title=item.title,
                    file_path=file_path,
                    original_comment=original_comment,
                    resolution_comment=resolution_comment,
                    resulted_in_change=resulted_in_change,
                ))
        
        return threads


# =============================================================================
# GitHub Implementation
# =============================================================================

class GitHubHarvester(CodeRepoHarvester):
    """Fetches and processes PR review comments from GitHub."""
    
    def __init__(self, config: Config):
        from github import Github
        
        self.gh = Github(config.github_token)
        self.repo = self.gh.get_repo(config.github_repo)
        self.max_mrs = config.max_mrs
    
    def fetch_merged_mrs(self) -> list[MergeItem]:
        """Fetch the last N merged pull requests from GitHub."""
        print(f"📥 Fetching last {self.max_mrs} merged PRs from GitHub...")
        
        # Get merged PRs (state='closed' + merged)
        pulls = self.repo.get_pulls(
            state="closed",
            sort="updated",
            direction="desc",
        )
        
        items: list[MergeItem] = []
        count = 0
        
        for pr in pulls:
            if count >= self.max_mrs:
                break
            
            # Only include actually merged PRs
            if pr.merged:
                items.append(MergeItem(
                    id=pr.number,
                    title=pr.title,
                    author=pr.user.login if pr.user else "unknown",
                    url=pr.html_url,
                    provider=Provider.GITHUB,
                    raw=pr,
                ))
                count += 1
        
        print(f"   Found {len(items)} merged PRs")
        return items
    
    def extract_discussions(self, item: MergeItem) -> list[DiscussionThread]:
        """
        Extract discussion threads from a GitHub PR.
        
        Focuses on PR Review Comments (comments on specific lines of code),
        not general issue comments.
        """
        threads: list[DiscussionThread] = []
        pr = item.raw
        
        try:
            # Get PR review comments (code-level comments)
            review_comments = list(pr.get_review_comments())
        except Exception as e:
            print(f"   ⚠ Could not fetch review comments for PR #{item.id}: {e}")
            return threads
        
        # Group comments by their review thread (in_reply_to_id)
        # Comments with same in_reply_to_id or original comment id form a thread
        comment_threads: dict[int, list[Any]] = {}
        
        for comment in review_comments:
            # Determine thread ID (either this comment starts thread or replies to one)
            thread_id = comment.in_reply_to_id or comment.id
            
            if thread_id not in comment_threads:
                comment_threads[thread_id] = []
            comment_threads[thread_id].append(comment)
        
        # Process each thread
        for thread_id, comments in comment_threads.items():
            # Sort by created_at to get chronological order
            comments.sort(key=lambda c: c.created_at)
            
            if not comments:
                continue
            
            first_comment = comments[0]
            original_comment = first_comment.body or ""
            file_path = first_comment.path
            
            # Get resolution comment (last in thread)
            resolution_comment = None
            if len(comments) > 1:
                resolution_comment = comments[-1].body
            
            # Determine if it resulted in a change:
            # - Has replies (back-and-forth discussion)
            # - Or contains reaction/resolution indicators
            has_replies = len(comments) > 1
            has_resolution_keywords = any(
                keyword in (resolution_comment or "").lower()
                for keyword in ["fixed", "done", "updated", "changed", "addressed", "good point"]
            )
            
            resulted_in_change = has_replies or has_resolution_keywords
            
            if resulted_in_change and len(original_comment) > 20:
                threads.append(DiscussionThread(
                    mr_id=item.id,
                    mr_title=item.title,
                    file_path=file_path,
                    original_comment=original_comment,
                    resolution_comment=resolution_comment,
                    resulted_in_change=resulted_in_change,
                ))
        
        # Also check PR reviews for general code review feedback
        try:
            reviews = list(pr.get_reviews())
            for review in reviews:
                if review.state == "CHANGES_REQUESTED" and review.body:
                    # Changes requested reviews often contain actionable feedback
                    if len(review.body) > 30:
                        threads.append(DiscussionThread(
                            mr_id=item.id,
                            mr_title=item.title,
                            file_path=None,  # General review, not file-specific
                            original_comment=review.body,
                            resolution_comment=None,
                            resulted_in_change=True,  # Changes were requested
                        ))
        except Exception:
            pass  # Reviews are optional
        
        return threads


# =============================================================================
# Harvester Factory
# =============================================================================

def create_harvester(config: Config) -> CodeRepoHarvester:
    """
    Factory function to create the appropriate harvester.
    
    Args:
        config: Configuration with provider information.
        
    Returns:
        Appropriate CodeRepoHarvester implementation.
    """
    if config.provider == Provider.GITLAB:
        return GitLabHarvester(config)
    elif config.provider == Provider.GITHUB:
        return GitHubHarvester(config)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")


# =============================================================================
# LLM Distillation
# =============================================================================

DISTILLATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a senior engineering manager distilling code review feedback 
into reusable team coding standards.

Given a code review comment, extract a clear, actionable preference rule that can
be applied to future code reviews.

Rules should be:
- Specific and actionable (not vague)
- Generalized beyond the specific instance
- Focused on the underlying principle

Categories:
- style: Code formatting, naming conventions, readability
- architecture: Design patterns, module organization, abstractions
- security: Security best practices, input validation, auth
- performance: Efficiency, memory usage, algorithmic choices
- naming: Variable, function, class naming conventions

If the comment is not suitable for a rule (e.g., too specific, unclear, or just "LGTM"),
return null for the rule field."""),
    ("human", """Code review comment from {provider} {item_type} #{mr_id}:
"{comment}"

File: {file_path}

Extract a preference rule from this comment. If not applicable, return null."""),
])


class PreferenceDistiller:
    """Uses LLM to distill comments into preference rules."""
    
    def __init__(self, config: Config):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.2,
            api_key=config.openai_api_key,
        )
        self.chain = DISTILLATION_PROMPT | self.llm.with_structured_output(
            PreferenceRule,
            include_raw=True,
        )
        self.provider = config.provider
    
    async def distill(self, thread: DiscussionThread) -> PreferenceRule | None:
        """Distill a discussion thread into a preference rule."""
        item_type = "MR" if self.provider == Provider.GITLAB else "PR"
        
        try:
            result = await self.chain.ainvoke({
                "provider": self.provider.value.capitalize(),
                "item_type": item_type,
                "mr_id": thread.mr_id,
                "comment": thread.original_comment,
                "file_path": thread.file_path or "N/A",
            })
            
            # Handle structured output response
            if isinstance(result, dict) and "parsed" in result:
                parsed = result["parsed"]
                if parsed and parsed.rule:
                    parsed.source_mr_id = thread.mr_id
                    parsed.original_comment = thread.original_comment[:200]
                    return parsed
            elif isinstance(result, PreferenceRule) and result.rule:
                result.source_mr_id = thread.mr_id
                result.original_comment = thread.original_comment[:200]
                return result
                
        except Exception as e:
            print(f"   ⚠ Distillation error for #{thread.mr_id}: {e}")
        
        return None


# =============================================================================
# ChromaDB Ingestion
# =============================================================================

class PreferenceStore:
    """Stores preference rules in ChromaDB vector store."""
    
    def __init__(self, config: Config):
        self.client = chromadb.PersistentClient(path=config.chroma_persist_path)
        self.collection = self.client.get_or_create_collection(
            name=config.collection_name,
            metadata={"description": "User coding preferences from PR history"},
        )
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=config.openai_api_key,
        )
        self.provider = config.provider
    
    async def ingest(self, rules: list[PreferenceRule]) -> int:
        """Ingest preference rules into the vector store."""
        if not rules:
            return 0
        
        texts = [rule.rule for rule in rules]
        embeddings = await self.embeddings.aembed_documents(texts)
        
        ids = [f"rule_{self.provider.value}_{rule.source_mr_id}_{i}" for i, rule in enumerate(rules)]
        metadatas = [
            {
                "category": rule.category,
                "confidence": rule.confidence,
                "source_mr_id": rule.source_mr_id,
                "original_comment": rule.original_comment,
                "provider": self.provider.value,
                "ingested_at": datetime.now().isoformat(),
            }
            for rule in rules
        ]
        
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        
        return len(rules)
    
    def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        return {
            "total_rules": self.collection.count(),
            "collection_name": self.collection.name,
        }


# =============================================================================
# Main Execution
# =============================================================================

async def run_seed(args: Any = None) -> None:
    """Main execution flow for seeding."""
    print("=" * 60)
    print("🌱 CR Agent Knowledge Seeding (Multi-Provider)")
    print("=" * 60 + "\n")
    
    # Extract overrides from args if present
    github_repo = getattr(args, "github", None) if args else None
    # We might need to handle token passing via CLI later, but currently main.py doesn't expose a 'token' flag.
    # It relies on env vars usually, but we are enabling "similar" arguments.
    # main.py defines --github, --pr, --gitlab, --mr. 
    # github_repo corresponds to --github (repo name).
    gitlab_project_id = getattr(args, "gitlab", None) if args else None
    
    # Load configuration
    config = load_config(
        github_repo=github_repo,
        gitlab_project_id=gitlab_project_id,
    )
    print(f"✓ Configuration loaded (Provider: {config.provider.value.upper()})\n")
    
    # Initialize components using factory
    harvester = create_harvester(config)
    distiller = PreferenceDistiller(config)
    store = PreferenceStore(config)
    
    # Fetch merged MRs/PRs
    items = harvester.fetch_merged_mrs()
    
    # Extract and process discussions
    all_threads: list[DiscussionThread] = []
    item_type = "MR" if config.provider == Provider.GITLAB else "PR"
    
    for item in items:
        print(f"   Processing {item_type} #{item.id}: {item.title[:50]}...")
        threads = harvester.extract_discussions(item)
        all_threads.extend(threads)
    
    print(f"\n📝 Found {len(all_threads)} actionable discussion threads\n")
    
    if not all_threads:
        print(f"⚠ No discussions found. Ensure {item_type}s have code review comments.")
        return
    
    # Distill into preference rules
    print("🧠 Distilling preference rules using LLM...")
    rules: list[PreferenceRule] = []
    
    for i, thread in enumerate(all_threads):
        print(f"   [{i+1}/{len(all_threads)}] {item_type} #{thread.mr_id}...", end=" ")
        rule = await distiller.distill(thread)
        if rule:
            rules.append(rule)
            print(f"✓ {rule.category}")
        else:
            print("⊘ skipped")
    
    print(f"\n📊 Distilled {len(rules)} preference rules from {len(all_threads)} threads\n")
    
    # Ingest into vector store
    if rules:
        print("💾 Ingesting into ChromaDB...")
        count = await store.ingest(rules)
        stats = store.get_stats()
        
        print(f"\n✅ SUCCESS!")
        print(f"   Provider: {config.provider.value.upper()}")
        print(f"   Ingested: {count} new rules")
        print(f"   Total rules in store: {stats['total_rules']}")
        print(f"   Collection: {stats['collection_name']}")
        print(f"   Persist path: {config.chroma_persist_path}")
    
    # Show sample rules
    if rules:
        print("\n" + "=" * 60)
        print("📋 Sample Preference Rules:")
        print("=" * 60)
        for rule in rules[:5]:
            print(f"\n[{rule.category.upper()}] (confidence: {rule.confidence:.0%})")
            print(f"  Rule: {rule.rule}")
            print(f"  From: {item_type} #{rule.source_mr_id}")


if __name__ == "__main__":
    asyncio.run(run_seed())

#!/usr/bin/env python3
"""
Verbose test script to run the CR Agent against vLLM PR #32263.
Includes detailed logging of each phase.
"""

import asyncio
import os
from functools import partial

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from cr_agent.state import (
    AgentState,
    KnowledgeGraphContext,
    DependencyContext,
    PatternContext,
    HotspotContext,
    UserPreferenceContext,
    FinalReview,
    SubAgentResult,
)
from cr_agent.tools import (
    DependencyImpactTool,
    DesignPatternTool,
    HotspotDetectorTool,
    UserPreferencesTool,
)
from cr_agent.routing import routing_decision_node


# PR #32263 metadata
PR_DATA = {
    "mr_id": "vLLM-PR-32263",
    "title": "[cpu][performance] CPU Paged Attention NEON BFMMLA BF16 Implementation",
    "user_notes": """CPU Paged Attention NEON BFMMLA BF16 Implementation.
Performance: Prefill 2.32x, Decode 2.07x speedup.""",
    "related_files": [
        "csrc/cpu/cpu_attn.cpp",
        "csrc/cpu/cpu_attn_impl.hpp",
        "csrc/cpu/cpu_attn_neon.hpp",
        "csrc/cpu/cpu_attn_neon_bfmmla.hpp",
        "csrc/cpu/torch_bindings.cpp",
        "tests/kernels/attention/test_cpu_attn.py",
        "vllm/_custom_ops.py",
        "vllm/v1/attention/backends/cpu_attn.py",
    ],
}

REVIEW_PROMPT = """You are a senior code reviewer analyzing a PR for vLLM (a high-performance LLM inference engine).

## Context from Knowledge Graph
- Dependencies: {dependencies}
- Patterns: {patterns}
- Hotspots: {hotspots}
- User Preferences: {user_preferences}

## PR Information
- Title: {title}
- Files: {related_files}
- Author Notes: {user_notes}

## Diff
```diff
{diff}
```

## Your Task
Provide a thorough code review. Be specific about:

1. **Critical Issues** (bugs, security, build-breaking)
   - List each with file path and line number
   
2. **Performance Concerns** (this is a performance PR!)
   - N+1 patterns, memory issues, inefficient algorithms
   
3. **Architectural Alignment**
   - Does this follow vLLM patterns?
   - Any design concerns?

4. **Suggestions**
   - Specific improvements with code examples

Be thorough but precise. If something looks good, say so. If there are issues, be specific.
"""


async def run_verbose_review():
    print("=" * 70)
    print("CR Agent - vLLM PR #32263 Verbose Review")
    print("=" * 70 + "\n")
    
    # Load diff
    with open("/tmp/vllm_pr_32263.diff", "r") as f:
        diff = f.read()
    
    print(f"📄 Loaded diff: {len(diff):,} chars, {diff.count(chr(10)):,} lines\n")
    
    # --- Phase 1: Context Analysis ---
    print("=" * 50)
    print("PHASE 1: Context Analysis")
    print("=" * 50)
    
    dependency_result = DependencyImpactTool.invoke({
        "modified_files": PR_DATA["related_files"],
    })
    print(f"📦 Dependencies: {dependency_result['impact_severity']} impact")
    print(f"   Affected: {dependency_result['affected_modules']}")
    
    pattern_result = DesignPatternTool.invoke({
        "file_paths": PR_DATA["related_files"],
    })
    print(f"🏗️  Patterns: {pattern_result['pattern_name'] or 'None detected'}")
    
    hotspot_result = HotspotDetectorTool.invoke({
        "file_paths": PR_DATA["related_files"],
    })
    print(f"🔥 Hotspots: churn={hotspot_result['overall_churn_score']:.2f}")
    
    prefs_result = UserPreferencesTool.invoke({
        "code_context": diff[:2000],
        "file_paths": PR_DATA["related_files"],
    })
    print(f"👤 User Preferences: {len(prefs_result['preference_signals'])} signals, {len(prefs_result['mistakes_to_avoid'])} warnings")
    for pref in prefs_result['preference_signals'][:3]:
        print(f"   • {pref[:80]}...")
    
    # --- Phase 2: Routing ---
    print("\n" + "=" * 50)
    print("PHASE 2: Routing Decision")
    print("=" * 50)
    
    state: AgentState = {
        "mr_id": PR_DATA["mr_id"],
        "diff": diff,
        "related_files": PR_DATA["related_files"],
        "user_notes": PR_DATA["user_notes"],
    }
    
    routing = routing_decision_node(state)
    print(f"📊 Lines: {routing['total_lines']} (threshold: 300)")
    print(f"📊 Domains: {routing['domain_count']} - {routing['detected_domains']}")
    print(f"🚦 Decision: {'DELEGATE to sub-agents' if routing['should_delegate'] else 'LITE MODE'}")
    
    # --- Phase 3: LLM Review ---
    print("\n" + "=" * 50)
    print("PHASE 3: LLM Code Review (gpt-5-mini)")
    print("=" * 50)
    
    llm = ChatOpenAI(
        model="gpt-5-mini-2025-08-07",
        temperature=0.1,
    )
    
    # Build the prompt with all context
    prompt = REVIEW_PROMPT.format(
        dependencies=dependency_result,
        patterns=pattern_result,
        hotspots=hotspot_result,
        user_preferences=prefs_result,
        title=PR_DATA["title"],
        related_files=", ".join(PR_DATA["related_files"]),
        user_notes=PR_DATA["user_notes"],
        diff=diff[:30000],  # Truncate for token limits
    )
    
    print(f"📝 Prompt: {len(prompt):,} chars")
    print("⏳ Calling LLM...")
    
    response = await llm.ainvoke(prompt)
    
    print("\n" + "=" * 70)
    print("REVIEW RESULTS")
    print("=" * 70 + "\n")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(run_verbose_review())

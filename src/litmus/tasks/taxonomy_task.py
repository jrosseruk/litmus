"""Inspect_ai task for taxonomy behavioral evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, MemoryDataset, Sample
from inspect_ai.solver import generate

from litmus.tasks.scorer import rubric_scorer

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "taxonomy"

# Map category names to JSONL file slugs
CATEGORY_SLUGS = {
    "Response Style & Format": "response-style-and-format",
    "Sycophancy & Social Dynamics": "sycophancy-and-social-dynamics",
    "Safety & Refusal": "safety-and-refusal",
    "Reasoning & Cognition": "reasoning-and-cognition",
    "Knowledge & Uncertainty": "knowledge-and-uncertainty",
    "Values & Ethics": "values-and-ethics",
    "Political & Social": "political-and-social",
    "Biases & Stereotypes": "biases-and-stereotypes",
    "Self-Model & Identity": "self-model-and-identity",
    "Instruction Following": "instruction-following",
    "Creativity & Generation": "creativity-and-generation",
    "Domain-Specific": "domain-specific",
    "Agentic & Strategic": "agentic-and-strategic",
    "Robustness & Consistency": "robustness-and-consistency",
    "Cultural & Contextual": "cultural-and-contextual",
    "Emotional & Interpersonal": "emotional-and-interpersonal",
    "Metacognitive & Reflective": "metacognitive-and-reflective",
    "Edge Cases & Unusual Inputs": "edge-cases-and-unusual-inputs",
}

SLUG_TO_CATEGORY = {v: k for k, v in CATEGORY_SLUGS.items()}


def load_taxonomy_dataset(
    categories: list[str] | None = None,
    behaviors: list[str] | None = None,
) -> list[Sample]:
    """Load taxonomy JSONL files, optionally filtering by category slug or behavior name.

    Args:
        categories: List of category slugs to include (e.g. ["response-style-and-format"]).
                    If None, loads all categories.
        behaviors: List of behavior names to include (e.g. ["verbosity"]).
                   Matched case-insensitively. If None, loads all behaviors.
    """
    samples: list[Sample] = []

    if categories:
        files = [DATA_DIR / f"{slug}.jsonl" for slug in categories]
    else:
        files = sorted(DATA_DIR.glob("*.jsonl"))

    behavior_set = {b.lower() for b in behaviors} if behaviors else None

    for filepath in files:
        if not filepath.exists():
            continue
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)

                if behavior_set and record.get("behavior", "").lower() not in behavior_set:
                    continue

                samples.append(
                    Sample(
                        id=record.get("id", ""),
                        input=record["prompt"],
                        metadata={
                            "category": record.get("category", ""),
                            "behavior": record.get("behavior", ""),
                            "behavior_number": record.get("behavior_number", 0),
                            "rubric": record.get("rubric", ""),
                            "scale_anchors": record.get("scale_anchors", {}),
                        },
                    )
                )

    return samples


@task
def taxonomy_eval(
    categories: list[str] | None = None,
    behaviors: list[str] | None = None,
    judge_model: str = "anthropic/claude-sonnet-4-6",
) -> Task:
    """Evaluate a model on taxonomy behavioral dimensions.

    Args:
        categories: Category slugs to evaluate (None = all).
        behaviors: Behavior names to evaluate (None = all in selected categories).
        judge_model: Model to use as LLM judge.
    """
    samples = load_taxonomy_dataset(categories=categories, behaviors=behaviors)
    return Task(
        dataset=MemoryDataset(samples=samples, name="taxonomy"),
        solver=[generate()],
        scorer=rubric_scorer(judge_model=judge_model),
    )

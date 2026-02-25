"""Inspect_ai task for petri seed evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import generate

from litmus.tasks.scorer import rubric_scorer

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "petri"


def load_petri_dataset() -> list[Sample]:
    """Load rewritten petri seeds from JSONL."""
    filepath = DATA_DIR / "petri_seeds.jsonl"
    samples: list[Sample] = []

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            samples.append(
                Sample(
                    id=record.get("id", ""),
                    input=record["prompt"],
                    metadata={
                        "original_id": record.get("original_id", ""),
                        "tags": record.get("tags", []),
                        "rubric": record.get("rubric", ""),
                        "scale_anchors": record.get("scale_anchors", {}),
                    },
                )
            )

    return samples


@task
def petri_eval(
    judge_model: str = "anthropic/claude-sonnet-4-6",
) -> Task:
    """Evaluate a model on rewritten petri safety seeds.

    Args:
        judge_model: Model to use as LLM judge.
    """
    samples = load_petri_dataset()
    return Task(
        dataset=MemoryDataset(samples=samples, name="petri"),
        solver=[generate()],
        scorer=rubric_scorer(judge_model=judge_model),
    )

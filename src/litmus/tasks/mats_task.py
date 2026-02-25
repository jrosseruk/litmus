"""Inspect_ai task for MATs hypothesis and claim evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import system_message

from litmus.tasks.scorer import rubric_scorer
from litmus.tasks.taxonomy_task import OLMO_SYSTEM, think_prefill

MATS_DIR = Path(__file__).resolve().parents[3] / "mats"
HYPOTHESES_DIR = MATS_DIR / "hypotheses"
CLAIMS_DIR = MATS_DIR / "claims"


def load_mats_dataset(
    data_dir: Path,
    slugs: list[str] | None = None,
) -> list[Sample]:
    """Load JSONL files from a MATs data directory.

    Args:
        data_dir: Directory containing JSONL files.
        slugs: Optional list of file stems to load. If None, loads all.
    """
    samples: list[Sample] = []

    if slugs:
        files = [data_dir / f"{slug}.jsonl" for slug in slugs]
    else:
        files = sorted(data_dir.glob("*.jsonl"))

    for filepath in files:
        if not filepath.exists():
            continue
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
def hypotheses_eval(
    slugs: list[str] | None = None,
    judge_model: str = "anthropic/claude-sonnet-4-6",
    name: str | None = None,
) -> Task:
    """Evaluate a model on hypothesis-testing prompts."""
    samples = load_mats_dataset(HYPOTHESES_DIR, slugs=slugs)
    dataset_name = name or "hypotheses"
    return Task(
        dataset=MemoryDataset(samples=samples, name=dataset_name),
        solver=[
            system_message(OLMO_SYSTEM),
            think_prefill(),
        ],
        scorer=rubric_scorer(judge_model=judge_model),
        name=dataset_name,
    )


@task
def claims_eval(
    slugs: list[str] | None = None,
    judge_model: str = "anthropic/claude-sonnet-4-6",
    name: str | None = None,
) -> Task:
    """Evaluate a model on claim-verification prompts."""
    samples = load_mats_dataset(CLAIMS_DIR, slugs=slugs)
    dataset_name = name or "claims"
    return Task(
        dataset=MemoryDataset(samples=samples, name=dataset_name),
        solver=[
            system_message(OLMO_SYSTEM),
            think_prefill(),
        ],
        scorer=rubric_scorer(judge_model=judge_model),
        name=dataset_name,
    )


def all_hypothesis_slugs() -> list[str]:
    """Return sorted list of all hypothesis slugs from JSONL files on disk."""
    return sorted(p.stem for p in HYPOTHESES_DIR.glob("*.jsonl"))


def all_claim_slugs() -> list[str]:
    """Return sorted list of all claim slugs from JSONL files on disk."""
    return sorted(p.stem for p in CLAIMS_DIR.glob("*.jsonl"))

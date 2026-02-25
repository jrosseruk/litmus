"""Eval orchestration - wraps inspect_ai eval calls."""

from __future__ import annotations

from pathlib import Path

from inspect_ai import eval as inspect_eval

from litmus.tasks.mats_task import (
    all_claim_slugs,
    all_hypothesis_slugs,
    claims_eval,
    hypotheses_eval,
)
from litmus.tasks.petri_task import petri_eval
from litmus.tasks.taxonomy_task import all_category_slugs, taxonomy_eval


def run_eval(
    models: list[str],
    categories: list[str] | None = None,
    behaviors: list[str] | None = None,
    petri: bool = False,
    judge_model: str = "anthropic/claude-sonnet-4-6",
    log_dir: str = "./logs",
    max_tasks: int = 5,
    max_samples: int = 100,
    max_connections: int = 100,
) -> list:
    """Run evaluations for the given models and task configuration.

    Args:
        models: List of model identifiers (e.g. ["vllm/allenai/OLMo-3-1025-7B"]).
        categories: Category slugs to evaluate (taxonomy only).
        behaviors: Behavior names to evaluate (taxonomy only).
        petri: If True, run petri seeds evaluation.
        judge_model: Judge model for scoring.
        log_dir: Directory for inspect_ai logs.
        max_tasks: Maximum number of tasks to run concurrently.
        max_samples: Maximum number of samples to run in parallel per task.
        max_connections: Maximum concurrent HTTP connections to the model API.

    Returns:
        List of EvalLog results from inspect_ai.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    tasks = []
    if petri:
        tasks.append(petri_eval(judge_model=judge_model))
    else:
        slugs = categories if categories else all_category_slugs()
        for slug in slugs:
            tasks.append(
                taxonomy_eval(
                    categories=[slug],
                    behaviors=behaviors,
                    judge_model=judge_model,
                    name=slug,
                )
            )

    all_results = []
    for model in models:
        results = inspect_eval(
            tasks,
            model=model,
            log_dir=str(log_path),
            max_tasks=max_tasks,
            max_samples=max_samples,
            max_connections=max_connections,
        )
        all_results.extend(results)

    return all_results


def run_mats_eval(
    models: list[str],
    hypotheses: bool = False,
    claims: bool = False,
    judge_model: str = "anthropic/claude-sonnet-4-6",
    log_dir: str = "./logs",
    max_tasks: int = 5,
    max_samples: int = 100,
    max_connections: int = 100,
) -> list:
    """Run MATs hypothesis and/or claim evaluations.

    Args:
        models: List of model identifiers.
        hypotheses: If True, run hypothesis evals.
        claims: If True, run claim evals.
        judge_model: Judge model for scoring.
        log_dir: Directory for inspect_ai logs.
        max_tasks: Maximum number of tasks to run concurrently.
        max_samples: Maximum number of samples to run in parallel per task.
        max_connections: Maximum concurrent HTTP connections to the model API.

    Returns:
        List of EvalLog results from inspect_ai.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    tasks = []
    if hypotheses:
        for slug in all_hypothesis_slugs():
            tasks.append(
                hypotheses_eval(
                    slugs=[slug],
                    judge_model=judge_model,
                    name=f"hyp-{slug}",
                )
            )
    if claims:
        for slug in all_claim_slugs():
            tasks.append(
                claims_eval(
                    slugs=[slug],
                    judge_model=judge_model,
                    name=f"claim-{slug}",
                )
            )

    all_results = []
    for model in models:
        results = inspect_eval(
            tasks,
            model=model,
            log_dir=str(log_path),
            max_tasks=max_tasks,
            max_samples=max_samples,
            max_connections=max_connections,
        )
        all_results.extend(results)

    return all_results

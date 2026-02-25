"""Eval orchestration - wraps inspect_ai eval calls."""

from __future__ import annotations

from pathlib import Path

from inspect_ai import eval as inspect_eval

from litmus.tasks.petri_task import petri_eval
from litmus.tasks.taxonomy_task import taxonomy_eval


def run_eval(
    models: list[str],
    categories: list[str] | None = None,
    behaviors: list[str] | None = None,
    petri: bool = False,
    judge_model: str = "anthropic/claude-sonnet-4-6",
    log_dir: str = "./logs",
) -> list:
    """Run evaluations for the given models and task configuration.

    Args:
        models: List of model identifiers (e.g. ["vllm/allenai/OLMo-3-1025-7B"]).
        categories: Category slugs to evaluate (taxonomy only).
        behaviors: Behavior names to evaluate (taxonomy only).
        petri: If True, run petri seeds evaluation.
        judge_model: Judge model for scoring.
        log_dir: Directory for inspect_ai logs.

    Returns:
        List of EvalLog results from inspect_ai.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    tasks = []
    if petri:
        tasks.append(petri_eval(judge_model=judge_model))
    else:
        tasks.append(
            taxonomy_eval(
                categories=categories,
                behaviors=behaviors,
                judge_model=judge_model,
            )
        )

    all_results = []
    for model in models:
        results = inspect_eval(
            tasks,
            model=model,
            log_dir=str(log_path),
        )
        all_results.extend(results)

    return all_results

"""Litmus CLI - behavioral diff evaluation for LLM variants."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="litmus",
    help="Behavioral diff evaluation framework for comparing LLM variants.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def eval(
    models: str = typer.Option(
        ...,
        "--models",
        help="Comma-separated model names (e.g. vllm/allenai/OLMo-3-1025-7B,vllm/allenai/OLMo-3-7B-Think-SFT)",
    ),
    all_tasks: bool = typer.Option(False, "--all", help="Run all taxonomy + petri evals"),
    category: Optional[str] = typer.Option(
        None, "--category", help="Run one taxonomy category (e.g. response-style-and-format)"
    ),
    behavior: Optional[str] = typer.Option(
        None, "--behavior", help="Run one specific behavior (e.g. verbosity)"
    ),
    petri: bool = typer.Option(False, "--petri", help="Run petri seeds only"),
    judge: str = typer.Option(
        "anthropic/claude-sonnet-4-6", "--judge", help="Judge model for scoring"
    ),
    max_tasks: int = typer.Option(
        5, "--max-tasks", help="Maximum number of tasks to run concurrently"
    ),
    max_samples: int = typer.Option(
        100, "--max-samples", help="Maximum number of samples to run in parallel per task"
    ),
    max_connections: int = typer.Option(
        100, "--max-connections", help="Maximum concurrent HTTP connections to the model API"
    ),
    log_dir: str = typer.Option("./logs", "--log-dir", help="Output directory for logs"),
) -> None:
    """Run behavioral evaluations against one or more models."""
    from litmus.eval import run_eval

    model_list = [m.strip() for m in models.split(",")]

    if not any([all_tasks, category, behavior, petri]):
        console.print("[red]Error:[/red] Specify --all, --category, --behavior, or --petri")
        raise typer.Exit(1)

    categories = None
    behaviors = None

    if petri:
        console.print(f"[bold]Running petri eval[/bold] against {len(model_list)} model(s)")
        results = run_eval(
            models=model_list,
            petri=True,
            judge_model=judge,
            log_dir=log_dir,
            max_tasks=max_tasks,
            max_samples=max_samples,
            max_connections=max_connections,
        )
    else:
        if all_tasks:
            console.print(f"[bold]Running all taxonomy evals[/bold] against {len(model_list)} model(s)")
        elif category:
            categories = [category]
            console.print(f"[bold]Running category '{category}'[/bold] against {len(model_list)} model(s)")
        elif behavior:
            behaviors = [behavior]
            console.print(f"[bold]Running behavior '{behavior}'[/bold] against {len(model_list)} model(s)")

        results = run_eval(
            models=model_list,
            categories=categories,
            behaviors=behaviors,
            judge_model=judge,
            log_dir=log_dir,
            max_tasks=max_tasks,
            max_samples=max_samples,
            max_connections=max_connections,
        )

    console.print(f"\n[green]Completed {len(results)} eval(s)[/green]")

    table = Table(title="Eval Results")
    table.add_column("Model", style="cyan")
    table.add_column("Task", style="magenta")
    table.add_column("Samples", justify="right")
    table.add_column("Mean Score", justify="right")
    table.add_column("Std Dev", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")

    for r in results:
        samples = r.samples or []
        scores = []
        for s in samples:
            if s.scores:
                for sc in s.scores.values():
                    if sc.value is not None:
                        scores.append(sc.value)

        task_name = r.eval.task if hasattr(r.eval, "task") else "—"
        n = len(scores)
        if n > 0:
            mean = statistics.mean(scores)
            std = statistics.pstdev(scores)
            lo, hi = min(scores), max(scores)
            table.add_row(
                r.eval.model,
                task_name,
                str(len(samples)),
                f"{mean:+.2f}",
                f"{std:.2f}",
                str(lo),
                str(hi),
            )
        else:
            table.add_row(r.eval.model, task_name, str(len(samples)), "—", "—", "—", "—")

    console.print(table)

    # Run comparative ranking if multiple models
    if len(model_list) > 1 and not petri:
        console.print("\n[bold]Running comparative ranking...[/bold]")
        import asyncio

        from litmus.compare import compare_models

        log_paths = [str(r.location) for r in results if r.location]
        behavior_name = behavior or category or "overall"

        ranking = asyncio.run(
            compare_models(
                log_paths=log_paths,
                behavior=behavior_name,
                judge_model=judge,
                output_path=str(Path(log_dir) / f"ranking_{behavior_name}.json"),
            )
        )
        console.print(f"[green]Ranking saved:[/green] {ranking.get('summary', 'done')}")


@app.command()
def view(
    log_dir: str = typer.Option("./logs", "--log-dir", help="Directory containing eval logs"),
    port: int = typer.Option(8501, "--port", help="Port for the viewer server"),
) -> None:
    """Launch the web viewer for browsing and comparing eval results."""
    from litmus.viewer.server import run_server

    console.print(f"[bold]Launching viewer[/bold] at http://localhost:{port}")
    run_server(log_dir=log_dir, port=port)

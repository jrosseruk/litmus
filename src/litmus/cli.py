"""Litmus CLI - behavioral diff evaluation for LLM variants."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

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
        )

    console.print(f"\n[green]Completed {len(results)} eval(s)[/green]")
    for r in results:
        console.print(f"  Model: {r.eval.model} | Samples: {len(r.samples or [])}")

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
    port: int = typer.Option(8501, "--port", help="Streamlit port"),
) -> None:
    """Launch the Streamlit viewer for browsing eval results."""
    viewer_path = Path(__file__).parent / "viewer" / "app.py"
    if not viewer_path.exists():
        console.print(f"[red]Viewer not found at {viewer_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Launching Streamlit viewer[/bold] on port {port}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(viewer_path),
            "--server.port",
            str(port),
            "--",
            "--log-dir",
            log_dir,
        ],
        check=True,
    )

"""Lightweight aiohttp viewer for litmus eval results."""

from __future__ import annotations

import asyncio
import os
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from aiohttp import web

# ---------------------------------------------------------------------------
# Log cache (path+mtime → parsed header / full log)
# ---------------------------------------------------------------------------

_header_cache: dict[tuple[str, float], dict] = {}
_log_cache: dict[tuple[str, float], dict] = {}

LOG_DIR: Path = Path("./logs")


def _resolve_log_path(raw: str) -> Path:
    """Turn an API path param into an absolute filesystem path."""
    # list_eval_logs returns file:// URIs; callers may pass those or plain paths
    if raw.startswith("file://"):
        raw = raw[len("file://"):]
    raw = unquote(raw)
    p = Path(raw)
    if not p.is_absolute():
        p = LOG_DIR / p
    return p.resolve()


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _extract_scores(samples) -> list[float]:
    """Pull all numeric score values from a list of samples."""
    scores = []
    for s in samples:
        sample_scores = s.scores if hasattr(s, "scores") else s.get("scores", {})
        if sample_scores:
            for sc in (sample_scores.values() if isinstance(sample_scores, dict) else [sample_scores]):
                val = sc.value if hasattr(sc, "value") else sc.get("value")
                if val is not None:
                    scores.append(float(val))
                    break  # first scorer only
    return scores


def _serialise_header(log, include_avg: bool = False) -> dict:
    """Extract header-level info from an EvalLog."""
    samples = log.samples or []
    sample_count = len(samples)
    if sample_count == 0 and getattr(log, "results", None):
        sample_count = getattr(log.results, "total_samples", 0) or 0

    hdr = {
        "path": str(getattr(log, "location", "")),
        "model": log.eval.model,
        "task": log.eval.task,
        "created": str(getattr(log.eval, "created", "")),
        "status": str(getattr(log, "status", "")),
        "sample_count": sample_count,
        "avg_score": None,
    }

    if include_avg and samples:
        vals = _extract_scores(samples)
        if vals:
            hdr["avg_score"] = round(sum(vals) / len(vals), 2)

    return hdr


def _serialise_message(msg) -> dict:
    content = msg.content
    if isinstance(content, list):
        # ContentText / ContentImage blocks → flatten to string
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif hasattr(c, "text"):
                parts.append(c.text)
        content = "\n".join(parts)
    return {"role": msg.role, "content": str(content)}


def _serialise_sample(sample) -> dict:
    messages = []
    if sample.messages:
        messages = [_serialise_message(m) for m in sample.messages]

    scores = {}
    if sample.scores:
        for name, sc in sample.scores.items():
            scores[name] = {
                "value": sc.value if sc else None,
                "explanation": getattr(sc, "explanation", None) if sc else None,
            }

    meta = sample.metadata or {}
    completion = ""
    if sample.output and sample.output.completion:
        completion = sample.output.completion

    return {
        "id": sample.id or "",
        "input": str(sample.input) if sample.input else "",
        "completion": completion,
        "messages": messages,
        "scores": scores,
        "metadata": dict(meta),
    }


def _serialise_full_log(log) -> dict:
    samples = [_serialise_sample(s) for s in (log.samples or [])]
    vals = _extract_scores(samples)
    avg_score = round(sum(vals) / len(vals), 2) if vals else None
    return {
        "eval": {
            "model": log.eval.model,
            "task": log.eval.task,
            "created": str(getattr(log.eval, "created", "")),
        },
        "status": str(getattr(log, "status", "")),
        "samples": samples,
        "avg_score": avg_score,
    }


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.Response:
    html_path = Path(__file__).parent / "index.html"
    return web.FileResponse(html_path)


async def handle_logs(request: web.Request) -> web.Response:
    """List all eval logs (header-only) from LOG_DIR."""
    from inspect_ai.log import list_eval_logs, read_eval_log

    def _load_headers():
        results = []
        try:
            log_infos = list_eval_logs(str(LOG_DIR))
        except Exception:
            log_infos = []

        # list_eval_logs returns EvalLogInfo objects with a .name attribute
        # containing a file:// URI
        for info in log_infos:
            try:
                uri = info.name if hasattr(info, "name") else str(info)
                p = _resolve_log_path(uri)
                mt = _mtime(p)
                key = (str(p), mt)
                if key in _header_cache:
                    results.append(_header_cache[key])
                    continue
                log = read_eval_log(str(p))
                hdr = _serialise_header(log, include_avg=True)
                # Use relative path for API consumers
                try:
                    hdr["path"] = str(p.relative_to(LOG_DIR.resolve()))
                except ValueError:
                    hdr["path"] = str(p)
                _header_cache[key] = hdr
                results.append(hdr)
            except Exception:
                continue
        return results

    headers = await asyncio.to_thread(_load_headers)
    return web.json_response(headers)


async def handle_log(request: web.Request) -> web.Response:
    """Return full log with all samples."""
    from inspect_ai.log import read_eval_log

    raw_path = request.match_info["path"]
    p = _resolve_log_path(raw_path)

    if not p.exists():
        return web.json_response({"error": "Log not found"}, status=404)

    mt = _mtime(p)
    key = (str(p), mt)
    if key in _log_cache:
        return web.json_response(_log_cache[key])

    def _load():
        log = read_eval_log(str(p))
        return _serialise_full_log(log)

    data = await asyncio.to_thread(_load)
    _log_cache[key] = data
    return web.json_response(data)


async def handle_compare(request: web.Request) -> web.Response:
    """Aligned comparison of 2+ logs."""
    from inspect_ai.log import read_eval_log

    logs_param = request.query.get("logs", "")
    if not logs_param:
        return web.json_response({"error": "No logs specified"}, status=400)

    raw_paths = [s.strip() for s in logs_param.split(",") if s.strip()]
    if len(raw_paths) < 2:
        return web.json_response({"error": "Need at least 2 logs"}, status=400)

    def _load_all():
        loaded = []
        for rp in raw_paths:
            p = _resolve_log_path(rp)
            if not p.exists():
                continue
            mt = _mtime(p)
            key = (str(p), mt)
            if key in _log_cache:
                loaded.append(_log_cache[key])
            else:
                log = read_eval_log(str(p))
                data = _serialise_full_log(log)
                _log_cache[key] = data
                loaded.append(data)
        return loaded

    loaded = await asyncio.to_thread(_load_all)
    if len(loaded) < 2:
        return web.json_response({"error": "Could not load enough logs"}, status=400)

    # Build aligned comparison
    models = [lg["eval"]["model"] for lg in loaded]

    # Index samples by ID for each log
    by_model: dict[str, dict[str, dict]] = {}
    all_ids: list[str] = []
    seen_ids: set[str] = set()
    categories: set[str] = set()
    behaviors: set[str] = set()

    for lg in loaded:
        model = lg["eval"]["model"]
        by_model[model] = {}
        for s in lg["samples"]:
            sid = s["id"]
            by_model[model][sid] = s
            if sid not in seen_ids:
                all_ids.append(sid)
                seen_ids.add(sid)
            meta = s.get("metadata", {})
            if meta.get("category"):
                categories.add(meta["category"])
            if meta.get("behavior"):
                behaviors.add(meta["behavior"])

    rows = []
    for sid in all_ids:
        # Get prompt from first model that has this sample
        prompt = ""
        meta = {}
        for model in models:
            if sid in by_model[model]:
                prompt = by_model[model][sid].get("input", "")
                meta = by_model[model][sid].get("metadata", {})
                break

        responses = {}
        score_values = []
        for model in models:
            if sid in by_model[model]:
                s = by_model[model][sid]
                # Get first score value
                score_val = None
                score_explanation = None
                for sc_data in s.get("scores", {}).values():
                    if sc_data and sc_data.get("value") is not None:
                        score_val = sc_data["value"]
                        score_explanation = sc_data.get("explanation")
                        break
                responses[model] = {
                    "completion": s.get("completion", ""),
                    "messages": s.get("messages", []),
                    "score": score_val,
                    "explanation": score_explanation,
                }
                if score_val is not None:
                    score_values.append(score_val)
            else:
                responses[model] = None

        score_delta = 0
        if len(score_values) >= 2:
            score_delta = max(score_values) - min(score_values)

        rows.append({
            "id": sid,
            "prompt": prompt,
            "category": meta.get("category", ""),
            "behavior": meta.get("behavior", ""),
            "responses": responses,
            "score_delta": score_delta,
        })

    # Compute per-model average scores
    model_scores: dict[str, list[float]] = {m: [] for m in models}
    for row in rows:
        for model in models:
            resp = row["responses"].get(model)
            if resp and resp.get("score") is not None:
                model_scores[model].append(resp["score"])

    averages = {}
    for model in models:
        vals = model_scores[model]
        if vals:
            averages[model] = {
                "mean": round(sum(vals) / len(vals), 2),
                "count": len(vals),
            }
        else:
            averages[model] = {"mean": None, "count": 0}

    # Per-behavior summary for heatmap
    from collections import defaultdict
    beh_groups: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: {m: [] for m in models}
    )
    for row in rows:
        key = (row["category"], row["behavior"])
        for model in models:
            resp = row["responses"].get(model)
            if resp and resp.get("score") is not None:
                beh_groups[key][model].append(resp["score"])

    behavior_summary = []
    for (cat, beh), scores_by_model in sorted(beh_groups.items()):
        entry: dict = {"category": cat, "behavior": beh, "models": {}, "delta": None}
        means = []
        for model in models:
            vals = scores_by_model[model]
            if vals:
                m = sum(vals) / len(vals)
                entry["models"][model] = round(m, 2)
                means.append(m)
            else:
                entry["models"][model] = None
        if len(means) >= 2:
            entry["delta"] = round(abs(means[0] - means[1]), 2)
        behavior_summary.append(entry)

    return web.json_response({
        "models": models,
        "rows": rows,
        "categories": sorted(categories),
        "behaviors": sorted(behaviors),
        "averages": averages,
        "behavior_summary": behavior_summary,
    })


# ---------------------------------------------------------------------------
# App factory & runner
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/log/{path:.+}", handle_log)
    app.router.add_get("/api/compare", handle_compare)
    return app


def run_server(log_dir: str = "./logs", port: int = 8501) -> None:
    global LOG_DIR
    LOG_DIR = Path(log_dir).resolve()

    app = create_app()

    async def _on_startup(app: web.Application) -> None:
        webbrowser.open(f"http://localhost:{port}")

    app.on_startup.append(_on_startup)
    web.run_app(app, host="0.0.0.0", port=port, print=lambda *a: None)

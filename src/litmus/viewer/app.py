"""Streamlit viewer for litmus eval results."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find_log_dir() -> Path:
    """Determine log directory from CLI args or default."""
    for i, arg in enumerate(sys.argv):
        if arg == "--log-dir" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return Path("./logs")


@st.cache_data
def load_eval_logs(log_dir: str) -> list[dict]:
    """Load all .eval log files from the directory."""
    log_path = Path(log_dir)
    logs = []
    for p in sorted(log_path.glob("*.eval")):
        try:
            from inspect_ai.log import read_eval_log

            log = read_eval_log(str(p))
            logs.append(
                {
                    "path": str(p),
                    "model": log.eval.model,
                    "task": log.eval.task,
                    "samples": log.samples or [],
                    "created": str(getattr(log.eval, "created", "")),
                }
            )
        except Exception as e:
            st.warning(f"Failed to load {p.name}: {e}")
    return logs


@st.cache_data
def load_rankings(log_dir: str) -> list[dict]:
    """Load ranking JSON files."""
    rankings = []
    for p in sorted(Path(log_dir).glob("ranking_*.json")):
        try:
            with open(p) as f:
                rankings.append(json.load(f))
        except Exception:
            pass
    return rankings


def score_color(score: float) -> str:
    """Return CSS color for a score from -5 to +5."""
    if score <= -3:
        return "#d32f2f"
    if score <= -1:
        return "#f57c00"
    if score < 1:
        return "#757575"
    if score < 3:
        return "#388e3c"
    return "#1b5e20"


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(page_title="Litmus Viewer", layout="wide")
    st.title("Litmus: Behavioral Diff Viewer")

    log_dir = str(find_log_dir())

    # Sidebar
    st.sidebar.header("Configuration")
    log_dir = st.sidebar.text_input("Log directory", value=log_dir)

    logs = load_eval_logs(log_dir)
    rankings = load_rankings(log_dir)

    if not logs:
        st.info(f"No eval logs found in `{log_dir}`. Run `litmus eval` first.")
        return

    # Select models
    models = sorted(set(l["model"] for l in logs))
    selected_models = st.sidebar.multiselect("Models", models, default=models)

    # Filter logs by selected models
    filtered_logs = [l for l in logs if l["model"] in selected_models]

    # Collect categories and behaviors from samples
    all_categories = set()
    all_behaviors = set()
    for log in filtered_logs:
        for sample in log["samples"]:
            meta = sample.metadata or {}
            if meta.get("category"):
                all_categories.add(meta["category"])
            if meta.get("behavior"):
                all_behaviors.add(meta["behavior"])

    selected_category = st.sidebar.selectbox(
        "Category", ["All"] + sorted(all_categories)
    )
    selected_behavior = st.sidebar.selectbox(
        "Behavior", ["All"] + sorted(all_behaviors)
    )

    # Score range filter
    score_range = st.sidebar.slider("Score range", -5, 5, (-5, 5))

    # Ranking banner
    if rankings:
        st.header("Rankings")
        for r in rankings:
            behavior = r.get("behavior", "?")
            agg = r.get("aggregate_ranking", [])
            summary = r.get("summary", "")
            st.subheader(f"Ranking: {behavior}")
            if agg:
                for i, model in enumerate(agg):
                    st.write(f"**#{i+1}** {model}")
            if summary:
                st.caption(summary)
        st.divider()

    # Main area: side-by-side comparison
    st.header("Response Comparison")

    # Group samples by prompt ID across models
    prompt_map: dict[str, dict] = {}
    for log in filtered_logs:
        model = log["model"]
        for sample in log["samples"]:
            meta = sample.metadata or {}

            # Apply filters
            if selected_category != "All" and meta.get("category") != selected_category:
                continue
            if selected_behavior != "All" and meta.get("behavior") != selected_behavior:
                continue

            pid = sample.id or ""
            if pid not in prompt_map:
                prompt_map[pid] = {
                    "input": sample.input,
                    "category": meta.get("category", ""),
                    "behavior": meta.get("behavior", ""),
                    "models": {},
                }

            score_val = None
            if sample.scores:
                for s in sample.scores.values():
                    if s and s.value is not None:
                        score_val = s.value
                        break

            if score_val is not None and not (score_range[0] <= score_val <= score_range[1]):
                continue

            prompt_map[pid]["models"][model] = {
                "response": sample.output.completion if sample.output else "",
                "score": score_val,
            }

    if not prompt_map:
        st.info("No matching samples found for the current filters.")
        return

    # Sort by score delta if multiple models
    items = list(prompt_map.items())
    if len(selected_models) > 1:
        sort_by = st.sidebar.selectbox("Sort by", ["ID", "Score delta (descending)"])
        if sort_by == "Score delta (descending)":
            def _delta(item):
                scores = [
                    v["score"]
                    for v in item[1]["models"].values()
                    if v["score"] is not None
                ]
                return max(scores) - min(scores) if len(scores) >= 2 else 0

            items.sort(key=_delta, reverse=True)

    for pid, data in items:
        with st.expander(
            f"**{pid}** | {data['category']} > {data['behavior']}", expanded=False
        ):
            st.markdown(f"**Prompt:** {data['input']}")
            cols = st.columns(len(selected_models))
            for col, model in zip(cols, selected_models):
                with col:
                    mdata = data["models"].get(model)
                    if mdata:
                        color = score_color(mdata["score"]) if mdata["score"] is not None else "#757575"
                        score_str = str(mdata["score"]) if mdata["score"] is not None else "N/A"
                        st.markdown(
                            f"**{model}** "
                            f"<span style='color:{color};font-weight:bold'>[{score_str}]</span>",
                            unsafe_allow_html=True,
                        )
                        st.text(mdata["response"][:2000])
                    else:
                        st.caption(f"{model}: no response")


if __name__ == "__main__":
    main()

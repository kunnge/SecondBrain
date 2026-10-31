"""Build an SVG tuning report without native plotting dependencies."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


METRICS = ("recall", "precision", "mrr", "ndcg")
METRIC_LABELS = {"recall": "Recall@K", "precision": "Precision@K", "mrr": "MRR", "ndcg": "nDCG@K"}
COLORS = ("#2d8c72", "#4878a8", "#d59a35", "#b76583")
WIDTH = 1200
HEIGHT = 1080
PANEL_WIDTH = 560
PANEL_HEIGHT = 320


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _text(x: float, y: float, value: Any, *, size: int = 14, color: str = "#263238", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}">{_escape(value)}</text>'
    )


def _panel(x: int, y: int, title: str) -> list[str]:
    return [
        f'<rect x="{x}" y="{y}" width="{PANEL_WIDTH}" height="{PANEL_HEIGHT}" fill="#ffffff" stroke="#cfd8dc"/>',
        _text(x + 18, y + 28, title, size=17),
    ]


def _line_chart(
    x: int,
    y: int,
    title: str,
    series: list[tuple[str, list[float | None], str]],
    x_label: str,
) -> list[str]:
    parts = _panel(x, y, title)
    left, top = x + 54, y + 54
    plot_width, plot_height = PANEL_WIDTH - 80, PANEL_HEIGHT - 112
    for tick in (0.0, 0.5, 1.0):
        py = top + plot_height * (1 - tick)
        parts.append(f'<line x1="{left}" y1="{py:.1f}" x2="{left + plot_width}" y2="{py:.1f}" stroke="#e4eaed"/>')
        parts.append(_text(left - 8, py + 4, f"{tick:.1f}", size=11, color="#54656d", anchor="end"))

    point_count = max((len(values) for _, values, _ in series), default=0)
    point_count = max(point_count, 1)
    for name, values, color in series:
        points: list[tuple[float, float]] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            px = left + (plot_width * index / max(point_count - 1, 1))
            py = top + plot_height * (1 - max(0.0, min(1.0, float(value))))
            points.append((px, py))
        if len(points) > 1:
            encoded = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            parts.append(f'<polyline points="{encoded}" fill="none" stroke="{color}" stroke-width="2"/>')
        for px, py in points:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}"/>')

    parts.append(_text(left + plot_width / 2, top + plot_height + 24, x_label, size=12, color="#54656d", anchor="middle"))
    legend_y = y + PANEL_HEIGHT - 16
    legend_x = x + 28
    for index, (name, _, color) in enumerate(series):
        item_x = legend_x + index * 128
        parts.append(f'<line x1="{item_x}" y1="{legend_y - 4}" x2="{item_x + 18}" y2="{legend_y - 4}" stroke="{color}" stroke-width="3"/>')
        parts.append(_text(item_x + 24, legend_y, name, size=11))
    return parts


def _parameter_distribution(x: int, y: int, trials: list[dict[str, Any]]) -> list[str]:
    parts = _panel(x, y, f"Parameter samples (n={len(trials)})")
    names = ("child_top_k", "rrf_k", "reranker_candidates")
    for row, name in enumerate(names):
        values = [int(item[name]) for item in trials if item.get(name) is not None]
        cy = y + 92 + row * 68
        parts.append(_text(x + 20, cy + 4, name, size=12))
        start, end = x + 205, x + PANEL_WIDTH - 30
        parts.append(f'<line x1="{start}" y1="{cy}" x2="{end}" y2="{cy}" stroke="#d9e1e5"/>')
        if values:
            low, high = min(values), max(values)
            for value in values:
                ratio = 0.5 if high == low else (value - low) / (high - low)
                px = start + ratio * (end - start)
                parts.append(f'<circle cx="{px:.1f}" cy="{cy}" r="5" fill="#4878a8" opacity="0.78"/>')
            parts.append(_text(start, cy + 20, low, size=10, color="#54656d"))
            parts.append(_text(end, cy + 20, high, size=10, color="#54656d", anchor="end"))
            if len(set(values)) == 1:
                parts.append(_text(start + 8, cy - 9, values[0], size=11, color="#263238"))
    return parts


def _bar_chart(
    x: int,
    y: int,
    title: str,
    labels: list[str],
    values: list[float],
    colors: list[str] | None = None,
) -> list[str]:
    parts = _panel(x, y, title)
    left, top = x + 52, y + 58
    chart_height = PANEL_HEIGHT - 112
    for tick in (0.0, 0.5, 1.0):
        py = top + chart_height * (1 - tick)
        parts.append(f'<line x1="{left}" y1="{py:.1f}" x2="{x + PANEL_WIDTH - 22}" y2="{py:.1f}" stroke="#e4eaed"/>')
        parts.append(_text(left - 8, py + 4, f"{tick:.1f}", size=11, color="#54656d", anchor="end"))
    if not values:
        parts.append(_text(x + PANEL_WIDTH / 2, y + PANEL_HEIGHT / 2, "No data", size=14, color="#54656d", anchor="middle"))
        return parts
    slot = (PANEL_WIDTH - 92) / len(values)
    bar_width = min(48, slot * 0.58)
    for index, (label, value) in enumerate(zip(labels, values)):
        color = colors[index] if colors else "#6b8fb3"
        value = max(0.0, min(1.0, float(value)))
        bar_height = chart_height * value
        bx = left + index * slot + (slot - bar_width) / 2
        by = top + chart_height - bar_height
        parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{color}"/>')
        parts.append(_text(bx + bar_width / 2, by - 6, f"{value:.3f}", size=11, anchor="middle"))
        parts.append(_text(bx + bar_width / 2, top + chart_height + 21, label, size=11, anchor="middle"))
    return parts


def _comparison_chart(x: int, y: int, comparison: dict[str, Any] | None) -> list[str]:
    parts = _panel(x, y, "Held-out test: baseline vs selected")
    if not comparison:
        parts.append(_text(x + PANEL_WIDTH / 2, y + PANEL_HEIGHT / 2, "Held-out test not run", size=14, color="#54656d", anchor="middle"))
        return parts

    left, top = x + 48, y + 58
    chart_height = PANEL_HEIGHT - 112
    slot = (PANEL_WIDTH - 82) / len(METRICS)
    bar_width = 25
    for tick in (0.0, 0.5, 1.0):
        py = top + chart_height * (1 - tick)
        parts.append(f'<line x1="{left}" y1="{py:.1f}" x2="{x + PANEL_WIDTH - 22}" y2="{py:.1f}" stroke="#e4eaed"/>')
        parts.append(_text(left - 8, py + 4, f"{tick:.1f}", size=11, color="#54656d", anchor="end"))
    for index, metric in enumerate(METRICS):
        baseline = float(comparison.get("baseline", {}).get("metrics", {}).get(metric, 0))
        selected = float(comparison.get("selected", {}).get("metrics", {}).get(metric, 0))
        center = left + index * slot + slot / 2
        for offset, value, color in ((-bar_width - 2, baseline, "#8b9f6a"), (2, selected, "#c77d91")):
            height = chart_height * max(0.0, min(1.0, value))
            bx, by = center + offset, top + chart_height - height
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_width}" height="{height:.1f}" fill="{color}"/>')
            parts.append(_text(bx + bar_width / 2, by - 5, f"{value:.2f}", size=10, anchor="middle"))
        parts.append(_text(center, top + chart_height + 21, METRIC_LABELS[metric].replace("@K", ""), size=11, anchor="middle"))
    parts.append('<rect x="{}" y="{}" width="10" height="10" fill="#8b9f6a"/>'.format(x + 34, y + PANEL_HEIGHT - 20))
    parts.append(_text(x + 49, y + PANEL_HEIGHT - 11, "Baseline", size=10))
    parts.append('<rect x="{}" y="{}" width="10" height="10" fill="#c77d91"/>'.format(x + 125, y + PANEL_HEIGHT - 20))
    parts.append(_text(x + 140, y + PANEL_HEIGHT - 11, "Selected", size=10))
    return parts


def _summary_panel(x: int, y: int, trials: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[str]:
    parts = _panel(x, y, "Run summary")
    completed = [item for item in trials if item.get("state") == "COMPLETE" and item.get("score") is not None]
    best_trial = max(completed, key=lambda item: float(item["score"])) if completed else None
    selected = max(candidates, key=lambda item: float(item.get("validation", {}).get("score", -1))) if candidates else None
    lines = [
        f"Completed trials: {len(completed)} / {len(trials)}",
        f"Validation candidates: {len(candidates)}",
        f"Best train score: {float(best_trial['score']):.4f}" if best_trial else "Best train score: pending",
        f"Best validation score: {float(selected['validation']['score']):.4f}" if selected else "Best validation score: pending",
    ]
    if selected:
        params = selected.get("parameters", {})
        lines.append("Selected parameters:")
        lines.append(", ".join(f"{key}={value}" for key, value in params.items()))
    for index, line in enumerate(lines):
        parts.append(_text(x + 24, y + 82 + index * 32, line, size=13))
    return parts


def create_report(
    output_path: Path,
    train_trials: list[dict[str, Any]],
    validation_candidates: list[dict[str, Any]],
    test_comparison: dict[str, Any] | None = None,
) -> Path:
    output_path = output_path.with_suffix(".svg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = [item for item in train_trials if item.get("state") == "COMPLETE" and item.get("score") is not None]
    completed.sort(key=lambda item: int(item.get("number", 0)))
    best_scores: list[float] = []
    best = float("-inf")
    for item in completed:
        best = max(best, float(item["score"]))
        best_scores.append(best)

    metric_series = [
        (
            METRIC_LABELS[metric],
            [item.get("metrics", {}).get(metric) for item in completed],
            COLORS[index],
        )
        for index, metric in enumerate(METRICS)
    ]
    ranked = sorted(
        validation_candidates,
        key=lambda item: float(item.get("validation", {}).get("score", -1)),
        reverse=True,
    )[:5]
    candidate_scores = [float(item.get("validation", {}).get("score", 0)) for item in ranked]
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#f5f7f8"/>',
        _text(32, 38, "Retrieval tuning report", size=24),
        *_line_chart(24, 56, f"Best training score (n={len(completed)})", [("Best so far", best_scores, COLORS[0])], "Completed trial"),
        *_line_chart(616, 56, "Core training metrics", metric_series, "Completed trial"),
        *_parameter_distribution(24, 400, completed),
        *_bar_chart(616, 400, f"Top validation candidates (n={len(ranked)})", [f"#{i + 1}" for i in range(len(ranked))], candidate_scores),
        *_comparison_chart(24, 744, test_comparison),
        *_summary_panel(616, 744, train_trials, ranked),
        "</svg>",
    ]
    output_path.write_text("\n".join(elements), encoding="utf-8")
    return output_path

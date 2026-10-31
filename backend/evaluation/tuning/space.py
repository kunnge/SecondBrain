"""Validation helpers for the independently editable tuning search space."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TUNING_DIR = Path(__file__).resolve().parent
DEFAULT_SEARCH_SPACE = TUNING_DIR / "search_space.json"


def load_search_config(path: Path = DEFAULT_SEARCH_SPACE) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取搜索空间配置 {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("搜索空间配置必须是 JSON 对象")
    space = config.get("search_space")
    if not isinstance(space, dict) or set(space) != {"child_top_k", "rrf_k", "reranker_candidates"}:
        raise ValueError("search_space 必须且只能配置 child_top_k、rrf_k、reranker_candidates")
    for name, spec in space.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{name} 配置必须是对象")
        values = (spec.get("low"), spec.get("high"), spec.get("step"))
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError(f"{name} 的 low/high/step 必须为整数")
        low, high, step = values
        if low < 1 or high < low or step < 1:
            raise ValueError(f"{name} 的范围或步长无效：{spec}")
        maximum = {"child_top_k": 100, "rrf_k": 1000, "reranker_candidates": 100}[name]
        if high > maximum:
            raise ValueError(f"{name} 最大值不能超过评测 API 限制 {maximum}")
        if not list(range(low, high + 1, step)):
            raise ValueError(f"{name} 没有可采样取值")
    return config


def values_for(spec: dict[str, int], minimum: int | None = None, maximum: int | None = None) -> list[int]:
    """Return values on the configured integer grid, optionally constrained."""
    low = spec["low"]
    high = spec["high"]
    step = spec["step"]
    values = list(range(low, high + 1, step))
    return [value for value in values if (minimum is None or value >= minimum) and (maximum is None or value <= maximum)]


def conditional_integer_bounds(
    spec: dict[str, int], minimum: int, maximum: int
) -> tuple[int, int, int] | None:
    """Return a suggest_int range retaining the configured step/grid."""
    choices = values_for(spec, minimum=minimum, maximum=maximum)
    if not choices:
        return None
    return choices[0], choices[-1], spec["step"]


def validate_parameter_set(parameters: dict[str, Any], parent_top_k: int) -> None:
    child_top_k = parameters.get("child_top_k")
    reranker_candidates = parameters.get("reranker_candidates")
    if not isinstance(child_top_k, int) or child_top_k < 1:
        raise ValueError("child_top_k 必须为正整数")
    if not isinstance(reranker_candidates, int) or not parent_top_k <= reranker_candidates <= child_top_k:
        raise ValueError("必须满足 parent_top_k <= reranker_candidates <= child_top_k")
    if not isinstance(parameters.get("rrf_k"), int) or parameters["rrf_k"] < 1:
        raise ValueError("rrf_k 必须为正整数")

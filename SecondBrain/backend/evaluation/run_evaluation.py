"""运行 RAG 检索评测并生成逐题、阶段、历史汇总报告。

示例（从 backend 目录运行）：
    python -m evaluation.run_evaluation
    python -m evaluation.run_evaluation --suite fact
    python -m evaluation.run_evaluation --file evaluation/suites/heading.json
    python -m evaluation.run_evaluation --child-top-k 30 --parent-top-k 6 --compare-run result3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import requests

from config.settings import (
    API_BASE_URL,
    CONTEXT_MAX_CHUNKS_PER_PARENT,
    CONTEXT_MAX_TOTAL_CHUNKS,
    CONTEXT_NEIGHBOR_WINDOW,
    EVALUATION_REQUEST_TIMEOUT,
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_PATH,
    PARENT_CHUNK_SIZE,
    RETRIEVAL_CHILD_TOP_K,
    RETRIEVAL_PARENT_TOP_K,
    RERANK_MIN_PARENT_K,
    RERANK_PARENT_MULTIPLIER,
    RERANKER_BATCH_SIZE,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL_PATH,
)


BASE_DIR = Path(__file__).resolve().parent
GENERATED_REVIEW_DIR = BASE_DIR / "generated_review"
# 优先使用根据当前 evaluation_chunks 生成的题集，避免默认入口继续读取过期的根目录题集。
DEFAULT_TEST_CASE_FILE = (
    GENERATED_REVIEW_DIR / "test_cases.json"
    if (GENERATED_REVIEW_DIR / "test_cases.json").exists()
    else BASE_DIR / "test_cases.json"
)
RESULT_DIR = BASE_DIR / "results"
HISTORY_DIR = RESULT_DIR / "history"
API_URL = f"{API_BASE_URL.rstrip('/')}/evaluation/retrieval"
REQUEST_TIMEOUT = EVALUATION_REQUEST_TIMEOUT
METRIC_VERSION = 2
STAGE_COLUMNS = {
    "Vector": "vector_recall",
    "BM25": "bm25_recall",
    "RRF": "rrf_recall",
    "Reranker": "reranker_after",
    "Context": "context_chunk_recall",
}


def get_run_id() -> int:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ids = [
        int(path.name[6:])
        for path in RESULT_DIR.iterdir()
        if path.is_dir() and path.name.startswith("result") and path.name[6:].isdigit()
    ]
    return max(ids, default=0) + 1


def save_json(data: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return path


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list):
        raise ValueError(f"测试集必须是 JSON 数组：{path}")
    return cases


def validate_cases(cases: list[dict[str, Any]], chunk_dir: Path = BASE_DIR / "evaluation_chunks") -> None:
    exports: dict[str, dict[str, Any]] = {}
    for path in chunk_dir.glob("*.json"):
        with path.open("r", encoding="utf-8") as file:
            document = json.load(file)
        exports[str(document.get("document_id"))] = document

    errors: list[str] = []
    seen_case_ids: set[str] = set()
    for case in cases:
        case_id = case.get("question_id") or case.get("id", "<missing-id>")
        if case_id in seen_case_ids:
            errors.append(f"{case_id}: 测试题 id 重复")
        seen_case_ids.add(case_id)
        document_id = str(case.get("document_id") or "")
        document = exports.get(document_id)
        if not case.get("query"):
            errors.append(f"{case_id}: 缺少 query")
        if not case.get("relevant_parent_ids"):
            errors.append(f"{case_id}: 缺少 relevant_parent_ids，无法计算检索指标")
        if not document:
            errors.append(f"{case_id}: document_id 不存在于 evaluation_chunks: {document_id}")
            continue
        parents = {str(parent["parent_id"]): parent for parent in document.get("parents", [])}
        missing_parents = set(map(str, case.get("relevant_parent_ids", []))) - set(parents)
        if missing_parents:
            errors.append(f"{case_id}: 父块标签不存在: {sorted(missing_parents)}")
        for ref in case.get("relevant_chunk_refs", []):
            parent = parents.get(str(ref.get("parent_id")))
            if not parent:
                errors.append(f"{case_id}: 子块引用的 parent_id 不存在: {ref.get('parent_id')}")
                continue
            matches = [
                child for child in parent.get("children", [])
                if child.get("block_id") == ref.get("block_id")
                and child.get("chunk_index", 0) == ref.get("chunk_index", 0)
            ]
            if len(matches) != 1:
                errors.append(
                    f"{case_id}: 稳定子块映射应唯一，实际 {len(matches)} 条，"
                    f"parent={ref.get('parent_id')} block={ref.get('block_id')} index={ref.get('chunk_index')}"
                )
    if errors:
        preview = "\n".join(f"- {error}" for error in errors[:30])
        raise ValueError(f"测试集校验失败，共 {len(errors)} 个问题：\n{preview}")


def call_retrieval_api(
    test_case: dict[str, Any],
    child_top_k: int,
    parent_top_k: int,
    rrf_k: int | None = None,
    reranker_candidates: int | None = None,
) -> dict[str, Any]:
    payload = {
        "query": test_case["query"],
        "child_top_k": child_top_k,
        "parent_top_k": parent_top_k,
    }
    if rrf_k is not None:
        payload["rrf_k"] = rrf_k
    if reranker_candidates is not None:
        payload["reranker_candidates"] = reranker_candidates
    started = time.perf_counter()
    try:
        response = requests.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
        elapsed = time.perf_counter() - started
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text}
        return {
            "success": response.ok,
            "request": payload,
            "status_code": response.status_code,
            "latency_ms": round(elapsed * 1000, 2),
            "response": body,
        }
    except requests.RequestException as exc:
        return {
            "success": False,
            "request": payload,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
            "response": {},
        }


def recall(retrieved: list[Any], relevant: set[str], id_getter) -> float:
    if not relevant:
        return 0.0
    found = {
        normalize_id(id_getter(item))
        for item in retrieved
        if id_getter(item) is not None
    }
    return len(found & relevant) / len(relevant)


def normalize_id(value: Any) -> Any:
    return tuple(map(str, value)) if isinstance(value, tuple) else str(value)


def precision(retrieved: list[Any], relevant: set[str], k: int, id_getter) -> float:
    if k <= 0:
        return 0.0
    found = {str(id_getter(item)) for item in retrieved[:k] if id_getter(item) is not None}
    return len(found & relevant) / k


def reciprocal_rank(retrieved: list[Any], relevant: set[str], k: int, id_getter) -> float:
    for rank, item in enumerate(retrieved[:k], start=1):
        if str(id_getter(item)) in relevant:
            return 1 / rank
    return 0.0


def ndcg(retrieved: list[Any], relevant: set[str], k: int, id_getter) -> float:
    dcg = sum(
        (1 / math.log2(rank + 1))
        for rank, item in enumerate(retrieved[:k], start=1)
        if str(id_getter(item)) in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal if ideal else 0.0


def stable_child_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("parent_id") or ""),
        str(item.get("block_id") or ""),
        str(item.get("chunk_index", 0)),
    )


def evaluate_case(case: dict[str, Any], run_dir: Path, index: int, total: int, args: argparse.Namespace) -> dict[str, Any]:
    case_id = str(case.get("question_id") or case.get("id", f"case-{index}"))
    child_top_k = args.child_top_k if args.child_top_k is not None else RETRIEVAL_CHILD_TOP_K
    parent_top_k = args.parent_top_k if args.parent_top_k is not None else RETRIEVAL_PARENT_TOP_K
    sys.stdout.write(f"\r[{index:>3}/{total}] {case_id} 处理中")
    sys.stdout.flush()
    result = call_retrieval_api(
        case,
        child_top_k,
        parent_top_k,
        args.rrf_k,
        args.reranker_candidates,
    )
    result["case_id"] = case_id
    result["suite"] = case.get("suite", "unspecified")
    result["document_id"] = case.get("document_id")
    result["query"] = case.get("query")
    result["relevant_parent_ids"] = case.get("relevant_parent_ids", [])
    sys.stdout.write(f"\r[{index:>3}/{total}] {'完成' if result['success'] else '请求失败'}       ")
    sys.stdout.flush()
    if not result["success"]:
        save_json(result, run_dir / "cases" / f"{case_id}.json")
        return result

    payload = result["response"].get("results", {})
    relevant_parents = set(map(str, case.get("relevant_parent_ids", [])))
    k = parent_top_k
    final_results = payload.get("results", [])
    vector_results = payload.get("vector_results", [])
    bm25_results = payload.get("bm25_results", [])
    rrf_results = payload.get("rrf_results", [])
    rerank_candidates = payload.get("rerank_candidates", [])
    context_chunks = payload.get("context_chunks", [])
    candidate_k = child_top_k

    relevant_child_keys = {
        (
            str(ref.get("parent_id") or ""),
            str(ref.get("block_id") or ""),
            str(ref.get("chunk_index", 0)),
        )
        for ref in case.get("relevant_chunk_refs", [])
    }
    context_matches = [item for item in context_chunks if stable_child_key(item) in relevant_child_keys]
    context_recall = recall(context_chunks, relevant_child_keys, stable_child_key)
    reranked_child_keys = {
        (
            str(item.get("parent_id") or item.get("id") or ""),
            str(item.get("representative_block_id") or ""),
            str(item.get("representative_chunk_index", 0)),
        )
        for item in final_results
    }
    reranker_child_recall = len(reranked_child_keys & relevant_child_keys) / len(relevant_child_keys) if relevant_child_keys else 0.0

    result["effective_parameters"] = result["response"].get("effective_parameters", {})
    result["evaluation"] = {
        "recall_at_k": recall(final_results[:k], relevant_parents, lambda item: item.get("id")),
        "precision_at_k": precision(final_results, relevant_parents, k, lambda item: item.get("id")),
        "mrr": reciprocal_rank(final_results, relevant_parents, k, lambda item: item.get("id")),
        "ndcg_at_k": ndcg(final_results, relevant_parents, k, lambda item: item.get("id")),
        "relevant_parent_ids": sorted(relevant_parents),
        "missed_parent_ids": sorted(relevant_parents - {str(item.get("id")) for item in final_results}),
        "hybrid": {
            "vector_recall_at_k": recall(vector_results[:candidate_k], relevant_parents, lambda item: item.get("parent_id")),
            "bm25_recall_at_k": recall(bm25_results[:candidate_k], relevant_parents, lambda item: item.get("parent_id")),
            "rrf_recall_at_k": recall(rrf_results[:candidate_k], relevant_parents, lambda item: item.get("parent_id")),
            "candidate_k": candidate_k,
        },
        "reranker": {
            "before_recall": recall(rerank_candidates[:k], relevant_parents, lambda item: item.get("id")),
            "after_recall": recall(final_results[:k], relevant_parents, lambda item: item.get("id")),
            "recall_gain": recall(final_results[:k], relevant_parents, lambda item: item.get("id")) - recall(rerank_candidates[:k], relevant_parents, lambda item: item.get("id")),
            "candidate_count": len(rerank_candidates),
        },
        "context": {
            "chunk_recall": context_recall,
            "neighbor_relevance": len(context_matches) / len(context_chunks) if context_chunks else 0.0,
            "neighbor_gain": context_recall - reranker_child_recall,
            "context_chunk_count": len(context_chunks),
            "relevant_chunk_count": len(relevant_child_keys),
            "matched_chunk_refs": [list(stable_child_key(item)) for item in context_matches],
            "missed_chunk_refs": [list(key) for key in sorted(relevant_child_keys - {stable_child_key(item) for item in context_chunks})],
        },
    }
    rrf_parent_ids = [str(item.get("parent_id")) for item in rrf_results[:candidate_k] if item.get("parent_id")]
    result["evaluation"]["hybrid"]["parent_duplicate_rate"] = (
        (len(rrf_parent_ids) - len(set(rrf_parent_ids))) / len(rrf_parent_ids) if rrf_parent_ids else 0.0
    )
    result["evaluation"]["hybrid"]["rrf_gain_vs_vector"] = (
        result["evaluation"]["hybrid"]["rrf_recall_at_k"] - result["evaluation"]["hybrid"]["vector_recall_at_k"]
    )
    result["evaluation"]["hybrid"]["rrf_gain_vs_bm25"] = (
        result["evaluation"]["hybrid"]["rrf_recall_at_k"] - result["evaluation"]["hybrid"]["bm25_recall_at_k"]
    )
    save_json(result, run_dir / "cases" / f"{case_id}.json")
    return result


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def summarize(results: list[dict[str, Any]], run_id: int, test_file: Path) -> dict[str, Any]:
    successful = [item for item in results if item.get("success") and item.get("evaluation")]
    summary: dict[str, Any] = {
        "metric_version": METRIC_VERSION,
        "run_id": run_id,
        "run_name": f"result{run_id}",
        "test_file": str(test_file),
        "total_questions": len(results),
        "successful_questions": len(successful),
        "failed_questions": len(results) - len(successful),
        "retrieval": {},
        "stages": {},
    }
    retrieval_keys = {"recall": "recall_at_k", "precision": "precision_at_k", "mrr": "mrr", "ndcg": "ndcg_at_k"}
    summary["retrieval"] = {
        name: mean([item["evaluation"][key] for item in successful])
        for name, key in retrieval_keys.items()
    }
    columns = {
        "Vector": ("hybrid", "vector_recall_at_k"),
        "BM25": ("hybrid", "bm25_recall_at_k"),
        "RRF": ("hybrid", "rrf_recall_at_k"),
        "Reranker before": ("reranker", "before_recall"),
        "Reranker after": ("reranker", "after_recall"),
        "Reranker gain": ("reranker", "recall_gain"),
        "Context child recall": ("context", "chunk_recall"),
        "Context neighbor precision": ("context", "neighbor_relevance"),
        "Context gain": ("context", "neighbor_gain"),
        "Context chunks": ("context", "context_chunk_count"),
        "RRF gain vs Vector": ("hybrid", "rrf_gain_vs_vector"),
        "RRF gain vs BM25": ("hybrid", "rrf_gain_vs_bm25"),
        "RRF parent duplicate rate": ("hybrid", "parent_duplicate_rate"),
    }
    for label, (section, key) in columns.items():
        summary["stages"][label] = mean([item["evaluation"][section][key] for item in successful])
    summary["stage_counts"] = {
        "reranker_improved": sum(item["evaluation"]["reranker"]["recall_gain"] > 0 for item in successful),
        "reranker_degraded": sum(item["evaluation"]["reranker"]["recall_gain"] < 0 for item in successful),
        "reranker_unchanged": sum(item["evaluation"]["reranker"]["recall_gain"] == 0 for item in successful),
        "context_positive_gain": sum(item["evaluation"]["context"]["neighbor_gain"] > 0 for item in successful),
        "context_negative_gain": sum(item["evaluation"]["context"]["neighbor_gain"] < 0 for item in successful),
    }
    latencies = [item["latency_ms"] for item in successful]
    summary["performance"] = {
        "avg_latency_ms": mean(latencies),
        "max_latency_ms": max(latencies) if latencies else None,
        "min_latency_ms": min(latencies) if latencies else None,
    }
    effective = [item.get("effective_parameters", {}) for item in successful]
    summary["effective_parameters"] = effective[0] if effective and all(item == effective[0] for item in effective) else {"varies": True, "samples": effective}
    summary["request_parameters"] = {
        "child_top_k": sorted({item["request"]["child_top_k"] for item in results if item.get("request")}),
        "parent_top_k": sorted({item["request"]["parent_top_k"] for item in results if item.get("request")}),
        "rrf_k": sorted({item["request"].get("rrf_k") for item in results if item.get("request") and item["request"].get("rrf_k") is not None}),
        "reranker_candidates": sorted({item["request"].get("reranker_candidates") for item in results if item.get("request") and item["request"].get("reranker_candidates") is not None}),
    }
    return summary


def metrics_row(summary: dict[str, Any]) -> dict[str, Any]:
    row = {
        "run_id": summary["run_id"],
        "run_name": summary["run_name"],
        "dataset_hash": summary["dataset_hash"],
        "test_file": summary["test_file"],
        "total_questions": summary["total_questions"],
        "successful_questions": summary["successful_questions"],
        "failed_questions": summary["failed_questions"],
        "metric_version": summary["metric_version"],
    }
    row.update({f"avg_{key}": value for key, value in summary["retrieval"].items()})
    stage_columns = {
        "Vector": "avg_vector_recall",
        "BM25": "avg_bm25_recall",
        "RRF": "avg_rrf_recall",
        "Reranker before": "avg_reranker_before",
        "Reranker after": "avg_reranker_after",
        "Reranker gain": "avg_reranker_gain",
        "Context child recall": "avg_context_chunk_recall",
        "Context neighbor precision": "avg_context_neighbor_precision",
        "Context gain": "avg_context_gain",
        "Context chunks": "avg_context_chunk_count",
        "RRF gain vs Vector": "avg_rrf_gain_vs_vector",
        "RRF gain vs BM25": "avg_rrf_gain_vs_bm25",
        "RRF parent duplicate rate": "avg_parent_duplicate_rate",
    }
    row.update({stage_columns[key]: value for key, value in summary["stages"].items() if key in stage_columns})
    row.update(summary["performance"])
    row["child_top_k"] = summary["request_parameters"]["child_top_k"][0] if len(summary["request_parameters"]["child_top_k"]) == 1 else None
    row["parent_top_k"] = summary["request_parameters"]["parent_top_k"][0] if len(summary["request_parameters"]["parent_top_k"]) == 1 else None
    for key in ("rrf_k", "reranker_candidates"):
        values = summary["request_parameters"].get(key, [])
        row[key] = values[0] if len(values) == 1 else None
    for key, value in summary.get("configured_parameters", {}).items():
        if isinstance(value, (str, int, float, bool)):
            row[f"param_{key}"] = value
    for key, value in summary.get("effective_parameters", {}).items():
        if isinstance(value, (str, int, float, bool)):
            row[f"param_{key}"] = value
    row["avg_max_latency_ms"] = summary["performance"]["max_latency_ms"]
    row["avg_min_latency_ms"] = summary["performance"]["min_latency_ms"]
    row["avg_success_rate"] = (
        summary["successful_questions"] / summary["total_questions"]
        if summary["total_questions"] else 0.0
    )
    row.update({
        "avg_reranker_improved_cases": summary["stage_counts"]["reranker_improved"],
        "avg_reranker_degraded_cases": summary["stage_counts"]["reranker_degraded"],
        "avg_reranker_unchanged_cases": summary["stage_counts"]["reranker_unchanged"],
        "avg_context_positive_gain_cases": summary["stage_counts"]["context_positive_gain"],
        "avg_context_negative_gain_cases": summary["stage_counts"]["context_negative_gain"],
    })
    return row


def build_question_dataframe(results: list[dict[str, Any]], run_id: int) -> pd.DataFrame:
    rows = []
    for item in results:
        row: dict[str, Any] = {
            "run_id": run_id,
            "question_id": item.get("case_id"),
            "document_id": item.get("document_id"),
            "suite": item.get("suite"),
            "success": item.get("success", False),
            "latency_ms": item.get("latency_ms", 0),
        }
        evaluation = item.get("evaluation", {})
        if evaluation:
            row.update({
                "recall": evaluation["recall_at_k"],
                "precision": evaluation["precision_at_k"],
                "mrr": evaluation["mrr"],
                "ndcg": evaluation["ndcg_at_k"],
                "vector_recall": evaluation["hybrid"]["vector_recall_at_k"],
                "bm25_recall": evaluation["hybrid"]["bm25_recall_at_k"],
                "rrf_recall": evaluation["hybrid"]["rrf_recall_at_k"],
                "rrf_gain_vs_vector": evaluation["hybrid"]["rrf_gain_vs_vector"],
                "rrf_gain_vs_bm25": evaluation["hybrid"]["rrf_gain_vs_bm25"],
                "reranker_before": evaluation["reranker"]["before_recall"],
                "reranker_after": evaluation["reranker"]["after_recall"],
                "reranker_gain": evaluation["reranker"]["recall_gain"],
                "context_chunk_recall": evaluation["context"]["chunk_recall"],
                "neighbor_relevance": evaluation["context"]["neighbor_relevance"],
                "neighbor_gain": evaluation["context"]["neighbor_gain"],
                "context_chunk_count": evaluation["context"]["context_chunk_count"],
                "parent_duplicate_rate": evaluation["hybrid"]["parent_duplicate_rate"],
                "reranker_improved": evaluation["reranker"]["recall_gain"] > 0,
                "reranker_degraded": evaluation["reranker"]["recall_gain"] < 0,
                "missed_parent_ids": ",".join(evaluation["missed_parent_ids"]),
                "missed_chunk_refs": json.dumps(evaluation["context"]["missed_chunk_refs"], ensure_ascii=False),
            })
        elif item.get("error"):
            row["error"] = item["error"]
        rows.append(row)
    return pd.DataFrame(rows)


def load_history() -> pd.DataFrame:
    history_path = HISTORY_DIR / "all_runs_summary.csv"
    if not history_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(history_path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def legacy_run_matches(run_name: str, cases: list[dict[str, Any]]) -> bool:
    run_dir = RESULT_DIR / run_name
    for case in cases:
        case_id = str(case.get("id", ""))
        path = run_dir / f"{case_id}.json"
        if not path.exists():
            return False
        try:
            with path.open("r", encoding="utf-8") as file:
                result = json.load(file)
        except (OSError, json.JSONDecodeError):
            return False
        if result.get("request", {}).get("query") != case.get("query"):
            return False
        if str(result.get("request", {}).get("document_id") or "") != str(case.get("document_id") or ""):
            return False
        old_relevant = set(map(str, result.get("evaluation", {}).get("relevant_parent_ids", [])))
        new_relevant = set(map(str, case.get("relevant_parent_ids", [])))
        if old_relevant != new_relevant:
            return False
    return True


def include_compatible_legacy_runs(history: pd.DataFrame, cases: list[dict[str, Any]], dataset_hash: str) -> pd.DataFrame:
    if history.empty:
        return history
    if "dataset_hash" not in history.columns:
        history["dataset_hash"] = pd.NA
    if "metric_version" not in history.columns:
        history["metric_version"] = pd.NA
    if "run_name" not in history.columns:
        history["run_name"] = history["run_id"].map(lambda value: f"result{int(value)}" if pd.notna(value) else "")
    for index, row in history.iterrows():
        if pd.notna(row.get("dataset_hash")):
            continue
        run_name = str(row.get("run_name") or "")
        if legacy_run_matches(run_name, cases):
            history.at[index, "dataset_hash"] = dataset_hash
            history.at[index, "metric_version"] = METRIC_VERSION
            history.at[index, "metric_compatibility"] = "legacy-context-excluded"
            for column in (
                "avg_context_chunk_recall",
                "avg_context_neighbor_precision",
                "avg_context_gain",
                "avg_context_chunk_count",
            ):
                if column in history.columns:
                    history.at[index, column] = pd.NA
            for old_column, new_column in (
                ("reranker_before", "avg_reranker_before"),
                ("reranker_after", "avg_reranker_after"),
                ("reranker_gain", "avg_reranker_gain"),
            ):
                if old_column in history.columns and new_column not in history.columns:
                    history[new_column] = history[old_column]
    return history


def history_average(history: pd.DataFrame, dataset_hash: str) -> dict[str, Any]:
    if history.empty or "dataset_hash" not in history.columns or "metric_version" not in history.columns:
        return {"compatible_run_count": 0, "reason": "无使用同版指标、相同测试集的历史轮次"}
    compatible = history[(history["dataset_hash"] == dataset_hash) & (history["metric_version"] == METRIC_VERSION)]
    metric_columns = [
        "avg_recall", "avg_precision", "avg_mrr", "avg_ndcg",
        "avg_vector_recall", "avg_bm25_recall", "avg_rrf_recall",
        "avg_rrf_gain_vs_vector", "avg_rrf_gain_vs_bm25", "avg_parent_duplicate_rate",
        "avg_reranker_before", "avg_reranker_after", "avg_reranker_gain",
        "avg_context_chunk_recall", "avg_context_neighbor_precision", "avg_context_gain",
        "avg_context_chunk_count", "avg_latency_ms", "avg_max_latency_ms", "avg_min_latency_ms",
        "avg_success_rate", "avg_reranker_improved_cases", "avg_reranker_degraded_cases",
        "avg_reranker_unchanged_cases", "avg_context_positive_gain_cases", "avg_context_negative_gain_cases",
    ]
    metric_columns = [column for column in metric_columns if column in compatible.columns]
    return {
        "compatible_run_count": int(len(compatible)),
        "run_ids": compatible["run_name"].astype(str).tolist() if "run_name" in compatible.columns else [],
        "metrics": {column: round(float(compatible[column].mean()), 6) for column in metric_columns if compatible[column].notna().any()},
        "note": "按评测轮次的指标做算术平均；只合并相同测试集哈希和指标版本。旧轮次仅在题目、问题和父块标签一致时纳入；旧版 Context 指标已排除。",
    }


def plot_stages(summary: dict[str, Any], run_dir: Path, historical_average: dict[str, Any]) -> None:
    labels = ["Vector", "BM25", "RRF", "Reranker", "Context"]
    values = [
        summary["stages"].get("Vector"),
        summary["stages"].get("BM25"),
        summary["stages"].get("RRF"),
        summary["stages"].get("Reranker after"),
        summary["stages"].get("Context child recall"),
    ]
    valid = [(label, value) for label, value in zip(labels, values) if value is not None]
    if not valid:
        return
    labels, values = zip(*valid)
    plt.figure(figsize=(9, 5))
    bars = plt.bar(labels, values, color=["#4776a8", "#52a788", "#d6a448", "#bc6c8a", "#7a8f5a"][:len(labels)])
    plt.ylim(0, 1)
    plt.ylabel("Recall (higher is better)")
    plt.title(f"Retrieval stage recall | {summary['run_name']} | n={summary['successful_questions']}")
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width() / 2, min(value + 0.025, 0.98), f"{value:.1%}", ha="center")
    plt.tight_layout()
    plt.savefig(run_dir / "stage_recall.png", dpi=150)
    plt.close()

    if historical_average.get("compatible_run_count", 0) < 2:
        return
    compatible = historical_average.get("metrics", {})
    average_values = [
        compatible.get("avg_vector", compatible.get("avg_vector_recall")),
        compatible.get("avg_bm25", compatible.get("avg_bm25_recall")),
        compatible.get("avg_rrf", compatible.get("avg_rrf_recall")),
        compatible.get("avg_reranker_after"),
        compatible.get("avg_context_chunk_recall"),
    ]
    if not any(value is not None for value in average_values):
        return
    x = list(range(len(labels)))
    width = 0.38
    plt.figure(figsize=(10, 5))
    current_bars = plt.bar([value - width / 2 for value in x], values, width, label="Current run")
    average_bars = plt.bar([value + width / 2 for value in x], [value or 0 for value in average_values], width, label=f"All compatible runs (n={historical_average['compatible_run_count']})")
    for bars, annotations in ((current_bars, values), (average_bars, average_values)):
        for bar, value in zip(bars, annotations):
            if value is not None:
                plt.text(bar.get_x() + bar.get_width() / 2, min(value + 0.02, 0.98), f"{value:.1%}", ha="center", va="bottom", fontsize=9)
    plt.xticks(x, labels)
    plt.ylim(0, 1)
    plt.ylabel("Recall (higher is better)")
    plt.title("Current run vs cumulative run average")
    plt.legend()
    plt.tight_layout()
    plt.savefig(run_dir / "history_comparison.png", dpi=150)
    plt.close()


def plot_retrieval_comparison(summary: dict[str, Any], run_dir: Path, historical_average: dict[str, Any]) -> None:
    if summary["successful_questions"] == 0:
        return
    metric_names = ["recall", "precision", "mrr", "ndcg"]
    average = historical_average.get("metrics", {})
    labels = [name.upper() for name in metric_names]
    current = [summary["retrieval"].get(name) for name in metric_names]
    overall = [average.get(f"avg_{name}") for name in metric_names]
    has_history = historical_average.get("compatible_run_count", 0) >= 2 and any(
        value is not None for value in overall
    )
    x = list(range(len(labels)))
    plt.figure(figsize=(9, 5))
    if has_history:
        width = 0.38
        current_bars = plt.bar([value - width / 2 for value in x], [value or 0 for value in current], width, label="Current run")
        average_bars = plt.bar(
            [value + width / 2 for value in x],
            [value or 0 for value in overall],
            width,
            label=f"All compatible runs (n={historical_average['compatible_run_count']})",
        )
        for bars, annotations in ((current_bars, current), (average_bars, overall)):
            for bar, value in zip(bars, annotations):
                if value is not None:
                    plt.text(bar.get_x() + bar.get_width() / 2, min(value + 0.02, 0.98), f"{value:.1%}", ha="center", va="bottom", fontsize=9)
    else:
        bars = plt.bar(x, [value or 0 for value in current], width=0.55, label=summary["run_name"])
        for bar, value in zip(bars, current):
            if value is not None:
                plt.text(
                    bar.get_x() + bar.get_width() / 2,
                    min(value + 0.025, 0.98),
                    f"{value:.1%}",
                    ha="center",
                )
    plt.xticks(x, labels)
    plt.ylim(0, 1)
    plt.ylabel("Score (higher is better)")
    plt.title(
        "Overall retrieval metrics: current run vs cumulative average"
        if has_history
        else f"Overall retrieval metrics | {summary['run_name']} | n={summary['successful_questions']}"
    )
    plt.legend()
    plt.tight_layout()
    plt.savefig(run_dir / "retrieval_comparison.png", dpi=150)
    plt.close()


def plot_history_trend(history: pd.DataFrame, dataset_hash: str, run_dir: Path) -> None:
    if history.empty or "dataset_hash" not in history.columns:
        return
    compatible = history[
        (history["dataset_hash"] == dataset_hash)
        & (history["metric_version"] == METRIC_VERSION)
    ].copy()
    if len(compatible) < 2 or not any(column in compatible.columns and compatible[column].notna().any() for column in ("avg_recall", "avg_mrr", "avg_ndcg", "avg_rrf_recall", "avg_reranker_after")):
        return
    metric_columns = [
        ("avg_recall", "Recall"),
        ("avg_mrr", "MRR"),
        ("avg_ndcg", "NDCG"),
        ("avg_rrf_recall", "RRF recall"),
        ("avg_reranker_after", "Reranker recall"),
    ]
    plt.figure(figsize=(10, 5))
    for column, label in metric_columns:
        if column in compatible.columns and compatible[column].notna().any():
            line = plt.plot(compatible["run_name"], compatible[column], marker="o", label=label)[0]
            for run_name, value in zip(compatible["run_name"], compatible[column]):
                if pd.notna(value):
                    plt.annotate(f"{float(value):.1%}", (run_name, value), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, color=line.get_color())
    plt.ylim(0, 1)
    plt.ylabel("Score (higher is better)")
    plt.xlabel("Evaluation run")
    plt.title(f"Metric trend across compatible runs (n={len(compatible)})")
    plt.xticks(rotation=30)
    plt.legend()
    plt.tight_layout()
    plt.savefig(run_dir / "run_trends.png", dpi=150)
    plt.close()


def select_test_file(args: argparse.Namespace) -> Path:
    if args.file:
        path = Path(args.file)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    if args.suite:
        generated_suite_file = GENERATED_REVIEW_DIR / "suites" / f"{args.suite}.json"
        suite_file = generated_suite_file if generated_suite_file.exists() else BASE_DIR / "suites" / f"{args.suite}.json"
        if not suite_file.exists():
            raise FileNotFoundError(f"找不到 suite：{suite_file}")
        return suite_file
    return DEFAULT_TEST_CASE_FILE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 SecondBrain RAG 检索评测")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--suite", choices=["fact", "heading", "synthesis"], help="运行指定测试集")
    group.add_argument("--file", help="运行指定 JSON 测试文件")
    parser.add_argument("--child-top-k", type=int, help="覆盖配置中的 RETRIEVAL_CHILD_TOP_K")
    parser.add_argument("--parent-top-k", type=int, help="覆盖配置中的 RETRIEVAL_PARENT_TOP_K")
    parser.add_argument("--rrf-k", type=int, help="临时覆盖 RRF_K")
    parser.add_argument("--reranker-candidates", type=int, help="临时覆盖重排阶段父块候选数")
    parser.add_argument("--compare-run", help="指定一个 resultN 目录用于逐题差异对比，默认比较上一轮")
    parser.add_argument("--validate-only", action="store_true", help="只校验测试集的文档、父块和子块标签，不调用检索 API")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    test_file = select_test_file(args)
    cases = load_cases(test_file)
    validate_cases(cases)
    if args.validate_only:
        print(f"测试集校验通过：{len(cases)} 道题，覆盖 {len({case['document_id'] for case in cases})} 份文档。")
        return
    if args.child_top_k is not None and args.child_top_k <= 0:
        raise ValueError("--child-top-k 必须是正整数")
    if args.parent_top_k is not None and args.parent_top_k <= 0:
        raise ValueError("--parent-top-k 必须是正整数")
    if args.rrf_k is not None and args.rrf_k <= 0:
        raise ValueError("--rrf-k 必须是正整数")
    effective_parent_top_k = args.parent_top_k if args.parent_top_k is not None else RETRIEVAL_PARENT_TOP_K
    effective_child_top_k = args.child_top_k if args.child_top_k is not None else RETRIEVAL_CHILD_TOP_K
    if args.reranker_candidates is not None and not effective_parent_top_k <= args.reranker_candidates <= effective_child_top_k:
        raise ValueError("--reranker-candidates 必须位于 parent_top_k 和 child_top_k 之间")
    global plt, pd
    import matplotlib.pyplot as plt
    import pandas as pd

    dataset_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    run_id = get_run_id()
    run_dir = RESULT_DIR / f"result{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    save_json({
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "test_file": str(test_file),
        "dataset_hash": dataset_hash,
        "total_questions": len(cases),
        "request_parameters": {
            "child_top_k": args.child_top_k if args.child_top_k is not None else RETRIEVAL_CHILD_TOP_K,
            "parent_top_k": args.parent_top_k if args.parent_top_k is not None else RETRIEVAL_PARENT_TOP_K,
            "rrf_k": args.rrf_k if args.rrf_k is not None else None,
            "reranker_candidates": args.reranker_candidates,
        },
        "configured_parameters": {
            "retrieval_child_top_k": RETRIEVAL_CHILD_TOP_K,
            "retrieval_parent_top_k": RETRIEVAL_PARENT_TOP_K,
            "rerank_min_parent_k": RERANK_MIN_PARENT_K,
            "rerank_parent_multiplier": RERANK_PARENT_MULTIPLIER,
            "context_neighbor_window": CONTEXT_NEIGHBOR_WINDOW,
            "context_max_chunks_per_parent": CONTEXT_MAX_CHUNKS_PER_PARENT,
            "context_max_total_chunks": CONTEXT_MAX_TOTAL_CHUNKS,
            "parent_chunk_size": PARENT_CHUNK_SIZE,
            "child_chunk_size": CHILD_CHUNK_SIZE,
            "child_chunk_overlap": CHILD_CHUNK_OVERLAP,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_model_path": EMBEDDING_MODEL_PATH,
            "reranker_model_path": RERANKER_MODEL_PATH,
            "reranker_max_length": RERANKER_MAX_LENGTH,
            "reranker_batch_size": RERANKER_BATCH_SIZE,
        },
    }, run_dir / "run_metadata.json")

    print(f"评测轮次：result{run_id}")
    print(f"测试集：{test_file}")
    print(f"测试题数：{len(cases)}")
    print(f"请求参数：child_top_k={effective_child_top_k}, parent_top_k={effective_parent_top_k}, rrf_k={args.rrf_k or '服务默认'}, reranker_candidates={args.reranker_candidates or '服务默认'}")
    print("进度：", flush=True)
    results = [evaluate_case(case, run_dir, index, len(cases), args) for index, case in enumerate(cases, start=1)]
    print()
    summary = summarize(results, run_id, test_file)
    summary["dataset_hash"] = dataset_hash
    summary["suite"] = args.suite or ("custom" if args.file else "all")
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary["configured_parameters"] = {
        "retrieval_child_top_k": RETRIEVAL_CHILD_TOP_K,
        "retrieval_parent_top_k": RETRIEVAL_PARENT_TOP_K,
        "rerank_min_parent_k": RERANK_MIN_PARENT_K,
        "rerank_parent_multiplier": RERANK_PARENT_MULTIPLIER,
        "context_neighbor_window": CONTEXT_NEIGHBOR_WINDOW,
        "context_max_chunks_per_parent": CONTEXT_MAX_CHUNKS_PER_PARENT,
        "context_max_total_chunks": CONTEXT_MAX_TOTAL_CHUNKS,
        "parent_chunk_size": PARENT_CHUNK_SIZE,
        "child_chunk_size": CHILD_CHUNK_SIZE,
        "child_chunk_overlap": CHILD_CHUNK_OVERLAP,
        "embedding_model": EMBEDDING_MODEL,
        "reranker_max_length": RERANKER_MAX_LENGTH,
        "reranker_batch_size": RERANKER_BATCH_SIZE,
    }
    summary["request_parameters"] = {
        "child_top_k": [effective_child_top_k],
        "parent_top_k": [effective_parent_top_k],
        "rrf_k": [args.rrf_k] if args.rrf_k is not None else [],
        "reranker_candidates": [args.reranker_candidates] if args.reranker_candidates is not None else [],
    }

    question_df = build_question_dataframe(results, run_id)
    question_df["dataset_hash"] = dataset_hash
    question_df["metric_version"] = METRIC_VERSION
    question_df.to_csv(run_dir / "question_metrics.csv", index=False, encoding="utf-8-sig")
    save_json(results, run_dir / "results.json")
    history = include_compatible_legacy_runs(load_history(), cases, dataset_hash)
    current_row = metrics_row(summary)
    history_with_current = pd.concat([history, pd.DataFrame([current_row])], ignore_index=True) if not history.empty else pd.DataFrame([current_row])
    average = history_average(history_with_current, dataset_hash)
    summary["historical_average"] = average
    save_json(average, run_dir / "overall_average.json")
    save_json(average, HISTORY_DIR / "overall_average.json")

    failed = [
        {"case_id": item.get("case_id"), "query": item.get("query"), "error": item.get("error", item.get("response", {}).get("error"))}
        for item in results if not item.get("success")
    ]
    summary["failed_details"] = failed
    next_history = history_with_current
    next_history.to_csv(HISTORY_DIR / "all_runs_summary.csv", index=False, encoding="utf-8-sig")
    history_records = next_history.astype(object).where(pd.notna(next_history), None).to_dict(orient="records")
    save_json(history_records, HISTORY_DIR / "all_runs_summary.json")
    previous_questions_path = HISTORY_DIR / "all_questions_history.csv"
    try:
        old_questions = pd.read_csv(previous_questions_path) if previous_questions_path.exists() else pd.DataFrame()
    except (pd.errors.EmptyDataError, pd.errors.ParserError):
        old_questions = pd.DataFrame()
    all_questions = pd.concat([old_questions, question_df], ignore_index=True)
    all_questions.to_csv(previous_questions_path, index=False, encoding="utf-8-sig")

    comparison_name = args.compare_run or (f"result{run_id - 1}" if run_id > 1 else None)
    if comparison_name:
        comparison_dir = RESULT_DIR / comparison_name
        previous_file = comparison_dir / "question_metrics.csv"
        if previous_file.exists():
            previous = pd.read_csv(previous_file)
            if set(question_df["question_id"]) != set(previous["question_id"]):
                summary["comparison_skipped"] = f"{comparison_name} 使用了不同的问题集合；为避免把不同数据集误作逐题对比，已跳过。"
                save_json(summary, run_dir / "summary.json")
                previous = pd.DataFrame()
            if not previous.empty:
                comparison = question_df.merge(previous, on="question_id", how="outer", suffixes=("_current", "_previous"), indicator=True)
                metric_pairs = [("recall", "recall_current", "recall_previous"), ("vector_recall", "vector_recall_current", "vector_recall_previous"), ("bm25_recall", "bm25_recall_current", "bm25_recall_previous"), ("rrf_recall", "rrf_recall_current", "rrf_recall_previous"), ("reranker_after", "reranker_after_current", "reranker_after_previous"), ("context_chunk_recall", "context_chunk_recall_current", "context_chunk_recall_previous")]
                for metric, current_col, previous_col in metric_pairs:
                    if current_col in comparison and previous_col in comparison:
                        comparison[f"delta_{metric}"] = comparison[current_col] - comparison[previous_col]
                comparison.to_csv(run_dir / "question_comparison.csv", index=False, encoding="utf-8-sig")
                summary["compared_to"] = comparison_name
                summary["question_comparison_file"] = "question_comparison.csv"
                save_json(summary, run_dir / "summary.json")

    plot_stages(summary, run_dir, average)
    plot_retrieval_comparison(summary, run_dir, average)
    plot_history_trend(history_with_current, dataset_hash, run_dir)
    save_json(summary, run_dir / "summary.json")
    print("\n评测完成")
    print(f"成功 {summary['successful_questions']}/{summary['total_questions']}，失败 {summary['failed_questions']}")
    print("当前轮指标:")
    for label, value in summary["retrieval"].items():
        print(f"  {label}: {value if value is not None else 'N/A'}")
    print("阶段召回:")
    for label, value in summary["stages"].items():
        print(f"  {label}: {value if value is not None else 'N/A'}")
    print(f"历史兼容轮次平均：{average['compatible_run_count']} 轮")
    if average.get("metrics"):
        for name, value in average["metrics"].items():
            print(f"  {name}: {value}")
    elif average.get("reason"):
        print(f"  {average['reason']}")
    if failed:
        print(f"失败明细见：{run_dir / 'summary.json'}")
    print(f"结果目录：{run_dir}")


if __name__ == "__main__":
    main()

"""Evaluation API client, retrieval metrics, and immutable-snapshot checks."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable

import requests

from config.settings import API_BASE_URL, EVALUATION_REQUEST_TIMEOUT


class EvaluationRequestError(RuntimeError):
    pass


class SnapshotChangedError(RuntimeError):
    pass


class EvaluationClient:
    def __init__(self, retry_count: int = 3, retry_backoff_seconds: float = 1.0):
        self.retry_count = retry_count
        self.retry_backoff_seconds = retry_backoff_seconds
        self.base_url = API_BASE_URL.rstrip("/")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        for attempt in range(self.retry_count + 1):
            try:
                response = requests.request(
                    method,
                    url,
                    json=payload,
                    timeout=EVALUATION_REQUEST_TIMEOUT,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.retry_count:
                    raise EvaluationRequestError(f"请求失败，已重试 {self.retry_count} 次：{exc}") from exc
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
                continue
            except requests.RequestException as exc:
                raise EvaluationRequestError(f"不可重试的请求异常：{exc}") from exc

            if response.status_code >= 500:
                if attempt >= self.retry_count:
                    raise EvaluationRequestError(
                        f"服务端返回 HTTP {response.status_code}，已重试 {self.retry_count} 次：{response.text[:500]}"
                    )
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
                continue
            if not response.ok:
                raise EvaluationRequestError(
                    f"请求返回 HTTP {response.status_code}，不重试：{response.text[:500]}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise EvaluationRequestError("评测 API 返回的内容不是有效 JSON") from exc
            if not isinstance(body, dict):
                raise EvaluationRequestError("评测 API 响应必须是 JSON 对象")
            return body
        raise EvaluationRequestError("评测 API 请求未完成")

    def snapshot(self) -> dict[str, Any]:
        body = self._request_json("GET", "/evaluation/snapshot")
        if not body.get("bm25_cache_matches_database"):
            raise SnapshotChangedError("BM25 内存索引与数据库内容不一致，请重启后端并刷新索引后重试")
        if body.get("missing_source_files"):
            raise SnapshotChangedError(f"服务端缺少用于代码指纹的文件：{body['missing_source_files']}")
        if not body.get("snapshot_id"):
            raise SnapshotChangedError("评测快照接口没有返回 snapshot_id")
        return body

    def assert_snapshot(self, expected_id: str) -> dict[str, Any]:
        current = self.snapshot()
        if current["snapshot_id"] != expected_id:
            raise SnapshotChangedError(
                f"评测期间知识库、模型、代码或固定参数发生变化：预期 {expected_id}，当前 {current['snapshot_id']}"
            )
        return current

    def retrieve(self, case: dict[str, Any], parameters: dict[str, int]) -> dict[str, Any]:
        payload = {
            "query": case["query"],
            "child_top_k": parameters["child_top_k"],
            "parent_top_k": parameters["parent_top_k"],
            "rrf_k": parameters["rrf_k"],
            "reranker_candidates": parameters.get("reranker_candidates"),
        }
        if payload["reranker_candidates"] is None:
            payload.pop("reranker_candidates")
        if "document_id" in payload:
            raise AssertionError("document_id must remain evaluation metadata, not a retrieval filter")

        started = time.perf_counter()
        body = self._request_json("POST", "/evaluation/retrieval", payload)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if body.get("child_top_k") != payload["child_top_k"]:
            raise EvaluationRequestError("服务端实际使用的 child_top_k 与请求不一致")
        if body.get("parent_top_k") != payload["parent_top_k"]:
            raise EvaluationRequestError("服务端实际使用的 parent_top_k 与请求不一致")
        if "reranker_candidates" in payload:
            actual = body.get("reranker_candidates_actual")
            if actual is None or actual > payload["reranker_candidates"]:
                raise EvaluationRequestError("服务端没有按预期执行 reranker_candidates")
            if body.get("reranker_candidates_requested") != payload["reranker_candidates"]:
                raise EvaluationRequestError("服务端请求的 reranker_candidates 与请求不一致")
        effective = body.get("effective_parameters", {})
        if effective.get("rrf_k") != payload["rrf_k"]:
            raise EvaluationRequestError("服务端实际使用的 rrf_k 与请求不一致")
        return {"response": body, "latency_ms": latency_ms, "request": payload}


def _id_set(items: list[dict[str, Any]], key: str) -> set[str]:
    return {str(item[key]) for item in items if item.get(key) is not None}


def recall(retrieved: set[str], relevant: set[str]) -> float:
    return len(retrieved & relevant) / len(relevant) if relevant else 0.0


def precision_at_k(items: list[dict[str, Any]], relevant: set[str], k: int) -> float:
    found = _id_set(items[:k], "id")
    return len(found & relevant) / k if k else 0.0


def reciprocal_rank(items: list[dict[str, Any]], relevant: set[str], k: int) -> float:
    for rank, item in enumerate(items[:k], start=1):
        if str(item.get("id")) in relevant:
            return 1 / rank
    return 0.0


def ndcg_at_k(items: list[dict[str, Any]], relevant: set[str], k: int) -> float:
    import math

    dcg = sum(1 / math.log2(rank + 1) for rank, item in enumerate(items[:k], start=1) if str(item.get("id")) in relevant)
    ideal_count = min(len(relevant), k)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal if ideal else 0.0


def _child_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("parent_id") or ""),
        str(item.get("block_id") or ""),
        str(item.get("chunk_index", 0)),
    )


def score_response(case: dict[str, Any], body: dict[str, Any], parent_top_k: int) -> dict[str, Any]:
    result = body.get("results") or {}
    final = result.get("results") or []
    vector = result.get("vector_results") or []
    bm25 = result.get("bm25_results") or []
    fused = result.get("rrf_results") or []
    candidates = result.get("rerank_candidates") or []
    context = result.get("context_chunks") or []
    relevant_parents = {str(value) for value in case.get("relevant_parent_ids", [])}

    retrieved_final = _id_set(final[:parent_top_k], "id")
    stage = {
        "vector_recall": recall(_id_set(vector, "parent_id"), relevant_parents),
        "bm25_recall": recall(_id_set(bm25, "parent_id"), relevant_parents),
        "rrf_recall": recall(_id_set(fused, "parent_id"), relevant_parents),
        "reranker_before_recall": recall(_id_set(candidates[:parent_top_k], "id"), relevant_parents),
        "reranker_after_recall": recall(retrieved_final, relevant_parents),
    }

    relevant_children = {
        (
            str(ref.get("parent_id") or ""),
            str(ref.get("block_id") or ""),
            str(ref.get("chunk_index", 0)),
        )
        for ref in case.get("relevant_chunk_refs", [])
    }
    context_keys = {_child_key(item) for item in context}
    matching_context = context_keys & relevant_children
    stage["context_chunk_recall"] = len(matching_context) / len(relevant_children) if relevant_children else 0.0
    stage["context_neighbor_precision"] = len(matching_context) / len(context_keys) if context_keys else 0.0
    stage["context_chunk_count"] = len(context)

    metrics = {
        "recall": recall(retrieved_final, relevant_parents),
        "precision": precision_at_k(final, relevant_parents, parent_top_k),
        "mrr": reciprocal_rank(final, relevant_parents, parent_top_k),
        "ndcg": ndcg_at_k(final, relevant_parents, parent_top_k),
    }
    return {
        "question_id": str(case.get("question_id") or case.get("id")),
        "document_id": case.get("document_id"),
        "suite": case.get("suite"),
        "query": case.get("query"),
        "metrics": metrics,
        "stage_metrics": stage,
        "latency_ms": body.get("latency_ms"),
        "reranker_candidates_requested": body.get("reranker_candidates_requested"),
        "reranker_candidates_actual": body.get("reranker_candidates_actual"),
        "effective_parameters": body.get("effective_parameters", {}),
        "retrieved_parent_ids": sorted(retrieved_final),
        "missed_parent_ids": sorted(relevant_parents - retrieved_final),
    }


def summarize(results: list[dict[str, Any]], parameters: dict[str, int]) -> dict[str, Any]:
    if not results:
        raise ValueError("没有可汇总的成功检索结果")
    metric_names = ("recall", "precision", "mrr", "ndcg")
    stage_names = sorted({name for result in results for name in result["stage_metrics"]})
    metrics = {
        name: sum(result["metrics"][name] for result in results) / len(results)
        for name in metric_names
    }
    stage_metrics = {
        name: sum(result["stage_metrics"].get(name, 0.0) for result in results) / len(results)
        for name in stage_names
    }
    return {
        "parameters": parameters,
        "question_count": len(results),
        "metrics": metrics,
        "stage_metrics": stage_metrics,
        "score": sum(metrics.values()) / len(metric_names),
        "mean_latency_ms": sum(result.get("latency_ms") or 0.0 for result in results) / len(results),
        "results": results,
    }


def evaluate_dataset(
    cases: list[dict[str, Any]],
    parameters: dict[str, int],
    parent_top_k: int,
    client: EvaluationClient,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    progress_prefix: str = "",
) -> dict[str, Any]:
    results = []
    for index, case in enumerate(cases, start=1):
        retrieved = client.retrieve(case, parameters)
        evaluated = score_response(case, retrieved["response"], parent_top_k)
        evaluated["latency_ms"] = retrieved["latency_ms"]
        evaluated["request"] = retrieved["request"]
        results.append(evaluated)
        if on_result:
            on_result(evaluated)
        if progress_prefix:
            print(f"\r{progress_prefix} [{index}/{len(cases)}]", end="", flush=True)
    if progress_prefix:
        print()
    return summarize(results, parameters)

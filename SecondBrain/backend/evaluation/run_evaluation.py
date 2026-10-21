import json
import math
import os
import time

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import matplotlib.pyplot as plt
import pandas as pd
import requests
from config.settings import API_BASE_URL, EVALUATION_REQUEST_TIMEOUT


# ==================== 配置 ====================
API_URL = f"{API_BASE_URL.rstrip('/')}/evaluation/retrieval"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_CASE_FILE = os.path.join(BASE_DIR, "test_cases.json")
RESULT_DIR = os.path.join(BASE_DIR, "results")
HISTORY_DIR = os.path.join(RESULT_DIR, "history")
# 是否开启各阶段测试
ENABLE_HYBRID_EVALUATION = True
ENABLE_RERANKER_EVALUATION = True
ENABLE_CONTEXT_EVALUATION = True
# 单次请求超时时间
REQUEST_TIMEOUT = EVALUATION_REQUEST_TIMEOUT
# ==================== 测试轮次 ====================
"""获取下一次 result 编号"""
def get_run_id():
    os.makedirs(RESULT_DIR, exist_ok=True)
    result_dirs = [ name for name in os.listdir(RESULT_DIR) if name.startswith("result") and name[6:].isdigit() and os.path.isdir(os.path.join(RESULT_DIR, name)) ]
    if not result_dirs:
        return 1
    numbers = [int(name[6:]) for name in result_dirs]
    return max(numbers) + 1

RUN_ID = get_run_id()
CURRENT_RESULT_DIR = os.path.join(RESULT_DIR, f"result{RUN_ID}")

"""保存 JSON 到当前测试目录"""
def save_json(data, filename):
    os.makedirs(CURRENT_RESULT_DIR, exist_ok=True)
    filepath = os.path.join(CURRENT_RESULT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath
# ==================== API 调用 ====================
"""调用 Retrieval 测试接口"""
def call_retrieval_api(test_case):
    payload = {
        "query": test_case["query"],
        "document_id": test_case.get("document_id"),
        "child_top_k": test_case.get("child_top_k"),
        "parent_top_k": test_case.get("parent_top_k")
    }
    start_time = time.perf_counter()
    try:
        response = requests.post( API_URL, json=payload, timeout=REQUEST_TIMEOUT )
        elapsed_time = time.perf_counter() - start_time
        try:
            result = response.json()
        except ValueError:
            result = {"error": response.text}
        return {
            "success": response.ok,
            "request": payload,
            "status_code": response.status_code,
            "latency_ms": round(elapsed_time * 1000, 2),
            "response": result
        }
    except requests.RequestException as e:
        elapsed_time = time.perf_counter() - start_time
        return {
            "success": False,
            "request": payload,
            "status_code": None,
            "latency_ms": round(elapsed_time * 1000, 2),
            "error": str(e),
            "response": {}
        }
# ==================== 最终 Parent 指标 ====================
"""获取最终 Parent 结果"""
def get_final_results(response):
    return response["results"]["results"] if ENABLE_HYBRID_EVALUATION else response["results"]
"""计算 Recall@K"""
def calculate_recall_at_k(response, relevant_parent_ids, k):
    # 获取最终 Parent 结果
    results = get_final_results(response)
    # 获取 Top-K Parent ID
    retrieved_ids = {str(item.get("id")) for item in results[:k] if item.get("id")}
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # 没有相关 Parent 时返回 0
    if not relevant_ids:
        return 0.0
    # Recall = 命中的相关 Parent / 相关 Parent 总数
    return len(retrieved_ids & relevant_ids) / len(relevant_ids)
"""计算 Precision@K"""
def calculate_precision_at_k(response, relevant_parent_ids, k):
    # 获取最终 Parent 结果
    results = get_final_results(response)
    # 获取 Top-K Parent ID
    retrieved_ids = {str(item.get("id")) for item in results[:k] if item.get("id")}
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # K 不合法时返回 0
    if k <= 0:
        return 0.0
    # Precision = Top-K 中相关 Parent / K
    return len(retrieved_ids & relevant_ids) / k
"""计算 MRR"""
def calculate_mrr(response, relevant_parent_ids, k):
    # 获取最终 Parent 结果
    results = get_final_results(response)
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # 查找第一个相关 Parent
    for rank, item in enumerate(results[:k], start=1):
        if str(item.get("id")) in relevant_ids:
            return 1.0 / rank
    return 0.0
"""计算 NDCG@K"""
def calculate_ndcg_at_k(response, relevant_parent_ids, k):
    # 获取最终 Parent 结果
    results = get_final_results(response)
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # 计算 DCG
    dcg = 0.0
    for rank, item in enumerate(results[:k], start=1):
        relevance = 1 if str(item.get("id")) in relevant_ids else 0
        dcg += relevance / math.log2(rank + 1)
    # 计算理想 IDCG
    relevant_count = min(len(relevant_ids), k)
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, relevant_count + 1))
    # 没有相关结果时返回 0
    if idcg == 0:
        return 0.0
    return dcg / idcg
# ==================== Hybrid 指标 ====================
"""计算 Child Top-K 对应的 Parent Recall"""
def calculate_parent_recall_at_k(results, relevant_parent_ids, k):
    # 提取 Top-K Child 对应的 Parent ID
    retrieved_parent_ids = {str(item.get("parent_id")) for item in results[:k] if item.get("parent_id")}
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # 没有相关 Parent 时返回 0
    if not relevant_ids:
        return 0.0
    # Recall = 命中的 Parent / 相关 Parent 总数
    return len(retrieved_parent_ids & relevant_ids) / len(relevant_ids)
"""计算 Parent Top-K Recall"""
def calculate_parent_result_recall(results, relevant_parent_ids, k):
    # 获取 Top-K Parent ID
    retrieved_parent_ids = {str(item.get("id")) for item in results[:k] if item.get("id")}
    # 获取人工标注 Parent ID
    relevant_ids = {str(item) for item in relevant_parent_ids}
    # 没有相关 Parent 时返回 0
    if not relevant_ids:
        return 0.0
    # Recall = 命中的 Parent / 相关 Parent 总数
    return len(retrieved_parent_ids & relevant_ids) / len(relevant_ids)
"""统计 RRF 中 Parent 重复情况"""
def calculate_parent_duplicate_stats(rrf_results):
    parent_ids = [str(item.get("parent_id")) for item in rrf_results if item.get("parent_id")]
    total_children = len(parent_ids)
    if total_children == 0:
        return {
            "total_children": 0,
            "unique_parent_count": 0,
            "duplicate_child_count": 0,
            "parent_duplicate_rate": 0.0
        }
    # 统计唯一 Parent 数量
    unique_parent_count = len(set(parent_ids))
    # 统计重复 Child 数量
    duplicate_child_count = total_children - unique_parent_count
    return {
        "total_children": total_children,
        "unique_parent_count": unique_parent_count,
        "duplicate_child_count": duplicate_child_count,
        "parent_duplicate_rate": duplicate_child_count / total_children
    }
# ==================== Context 指标 ====================
"""计算 Context 中相关 Child 的比例"""
def calculate_neighbor_relevance(context_chunks, relevant_chunk_ids):
    # 获取 Context Child ID
    context_ids = {str(chunk.get("id")) for chunk in context_chunks if chunk.get("id")}
    # 获取人工标注 Child ID
    relevant_ids = {str(chunk_id) for chunk_id in relevant_chunk_ids}
    # 没有 Context 时返回 0
    if not context_ids:
        return 0.0
    # 相关 Child / Context Child 总数
    return len(context_ids & relevant_ids) / len(context_ids)
"""计算 ContextExpander 相比 Reranker 的 Recall 增益"""
def calculate_neighbor_gain(context_chunks, relevant_chunk_ids, reranked_results):
    # 获取人工标注 Child ID
    relevant_ids = {str(chunk_id) for chunk_id in relevant_chunk_ids}
    # 没有相关 Child 时返回 0
    if not relevant_ids:
        return 0.0
    # 获取 Reranker 命中的代表 Child
    reranker_child_ids = {
        str(item.get("representative_child_id"))
        for item in reranked_results
        if item.get("representative_child_id")
    }
    # 获取 ContextExpander 扩展后的 Child
    context_ids = {
        str(chunk.get("id"))
        for chunk in context_chunks
        if chunk.get("id")
    }
    # 计算 Reranker Recall
    reranker_recall = len(reranker_child_ids & relevant_ids) / len(relevant_ids)
    # 计算 Context Recall
    context_recall = len(context_ids & relevant_ids) / len(relevant_ids)
    # Context Recall - Reranker Recall
    return context_recall - reranker_recall
# ==================== 单题测试 ====================
    """测试单个问题"""
def evaluate_case(test_case):
    case_id = test_case.get("id")
    print("\n" + "=" * 60)
    print(f"正在测试：{case_id}")
    print(f"问题：{test_case['query']}")
    print("=" * 60)
    # 调用 Retrieval API
    result = call_retrieval_api(test_case)
    # 保存测试问题 ID
    result["case_id"] = case_id
    # API 请求失败
    if not result["success"]:
        filepath = save_json(result, f"{case_id}.json")
        print("❌ 请求失败")
        print(f"错误：{result.get('error', '未知错误')}")
        print(f"响应文件：{filepath}")
        return result
    # 获取测试参数
    relevant_parent_ids = test_case.get("relevant_parent_ids", [])
    parent_top_k = test_case.get("parent_top_k")
    child_top_k = test_case.get("child_top_k")

    # ==================== 最终检索 ====================
    # Recall@K
    recall_at_k = calculate_recall_at_k(result["response"], relevant_parent_ids, parent_top_k)
    # Precision@K
    precision_at_k = calculate_precision_at_k(result["response"], relevant_parent_ids, parent_top_k)
    # MRR
    mrr = calculate_mrr(result["response"], relevant_parent_ids, parent_top_k)
    # NDCG@K
    ndcg_at_k = calculate_ndcg_at_k(result["response"], relevant_parent_ids, parent_top_k)
    # 保存最终检索指标
    result["evaluation"] = {
        "recall_at_k": recall_at_k,
        "precision_at_k": precision_at_k,
        "mrr": mrr,
        "ndcg_at_k": ndcg_at_k,
        "k": parent_top_k,
        "relevant_parent_ids": relevant_parent_ids
    }
    # 获取统一结果对象
    response_results = result["response"]["results"]
    # ==================== Hybrid ====================
    if ENABLE_HYBRID_EVALUATION:
        # Hybrid 候选数量，与后端保持一致
        candidate_k = child_top_k
        # 获取 Vector 检索结果
        vector_results = response_results.get("vector_results", [])
        # 获取 BM25 检索结果
        bm25_results = response_results.get("bm25_results", [])
        # 获取 RRF 检索结果
        rrf_results = response_results.get("rrf_results", [])
        # 只统计当前候选池
        candidate_rrf_results = rrf_results[:candidate_k]
        # Parent 重复统计
        parent_stats = calculate_parent_duplicate_stats(candidate_rrf_results)
        # Vector Recall
        vector_recall = calculate_parent_recall_at_k(vector_results, relevant_parent_ids, candidate_k)
        # BM25 Recall
        bm25_recall = calculate_parent_recall_at_k(bm25_results, relevant_parent_ids, candidate_k)
        # RRF Recall
        rrf_recall = calculate_parent_recall_at_k(rrf_results, relevant_parent_ids, candidate_k)
        # RRF 相比 Vector 的提升
        rrf_gain_vs_vector = rrf_recall - vector_recall
        # RRF 相比 BM25 的提升
        rrf_gain_vs_bm25 = rrf_recall - bm25_recall
        # 保存 Hybrid 指标
        result["evaluation"]["hybrid"] = {
            "vector_recall_at_k": vector_recall,
            "bm25_recall_at_k": bm25_recall,
            "rrf_recall_at_k": rrf_recall,
            "rrf_gain_vs_vector": rrf_gain_vs_vector,
            "rrf_gain_vs_bm25": rrf_gain_vs_bm25,
            "candidate_k": candidate_k,
            "parent_duplicate": parent_stats
        }
    # ==================== Reranker ====================
    if ENABLE_RERANKER_EVALUATION:
        # 获取 Reranker 前的 Parent 候选
        rerank_candidates = response_results.get( "rerank_candidates", [] )
        # 获取 Reranker 后的最终 Parent
        reranked_results = response_results.get( "results", []  )
        # Reranker 前 Recall@K
        before_recall = calculate_parent_result_recall( rerank_candidates, relevant_parent_ids, parent_top_k )
        # Reranker 后 Recall@K
        after_recall = calculate_parent_result_recall( reranked_results, relevant_parent_ids, parent_top_k )
        # Reranker 对 Recall@K 的提升
        recall_gain = after_recall - before_recall
        # 保存 Reranker 指标
        result["evaluation"]["reranker"] = {
            "before_recall": before_recall,
            "after_recall": after_recall,
            "recall_gain": recall_gain,
            "candidate_count": len(rerank_candidates),
            "top_k": parent_top_k
        }
    # ==================== Context ====================
    if ENABLE_CONTEXT_EVALUATION:
        # 获取人工标注的相关 Child
        relevant_chunk_ids = test_case.get( "relevant_chunk_ids", [] )
        # 获取 Reranker 最终结果
        reranked_results = response_results.get( "results", [] )
        # 获取 ContextExpander 结果
        context_chunks = response_results.get( "context_chunks", [] )
        # Neighbor 相关率
        neighbor_relevance = calculate_neighbor_relevance( context_chunks, relevant_chunk_ids )
        # Neighbor 增益
        neighbor_gain = calculate_neighbor_gain( context_chunks, relevant_chunk_ids, reranked_results )
        # 保存 Context 指标
        result["evaluation"]["context"] = {
            "neighbor_relevance": neighbor_relevance,
            "neighbor_gain": neighbor_gain,
            "context_chunk_count": len(context_chunks),
            "relevant_chunk_ids": relevant_chunk_ids
        }
    # 保存当前问题结果
    filepath = save_json(result, f"{case_id}.json")
    # 输出当前问题结果
    print("✅ 请求成功")
    print(f"Recall@{parent_top_k}：{recall_at_k:.4f}")
    print(f"Precision@{parent_top_k}：{precision_at_k:.4f}")
    print(f"MRR：{mrr:.4f}")
    print(f"NDCG@{parent_top_k}：{ndcg_at_k:.4f}")
    if ENABLE_HYBRID_EVALUATION:
        hybrid = result["evaluation"]["hybrid"]
        print(f"Vector Recall@{candidate_k}：{hybrid['vector_recall_at_k']:.4f}")
        print(f"BM25 Recall@{candidate_k}：{hybrid['bm25_recall_at_k']:.4f}")
        print(f"RRF Recall@{candidate_k}：{hybrid['rrf_recall_at_k']:.4f}")
        print(f"RRF Gain vs Vector：{hybrid['rrf_gain_vs_vector']:+.4f}")
        print(f"RRF Gain vs BM25：{hybrid['rrf_gain_vs_bm25']:+.4f}")
        print(f"Parent 重复率：{hybrid['parent_duplicate']['parent_duplicate_rate']:.4f}")
    if ENABLE_RERANKER_EVALUATION:
        reranker = result["evaluation"]["reranker"]
        print(f"Reranker Before Recall@{parent_top_k}：{reranker['before_recall']:.4f}")
        print(f"Reranker After Recall@{parent_top_k}：{reranker['after_recall']:.4f}")
        print(f"Reranker Recall Gain：{reranker['recall_gain']:+.4f}")
    if ENABLE_CONTEXT_EVALUATION:
        context = result["evaluation"]["context"]
        print(f"Context Chunk 数量：{context['context_chunk_count']}")
        print(f"Neighbor 相关率：{context['neighbor_relevance']:.4f}")
        print(f"Neighbor 增益：{context['neighbor_gain']:+.4f}")
    print(f"响应文件：{filepath}")
    return result

# ==================== 当前轮次汇总 ====================
def calculate_summary(results):
    """统计当前测试轮次总体指标"""
    # 只统计成功请求
    success_results = [ item for item in results if item.get("success") and "evaluation" in item ]
    total = len(success_results)
    summary = {
        "run_id": RUN_ID,
        "total_questions": len(results),
        "successful_questions": total,
        "failed_questions": len(results) - total
    }
    if total == 0:
        return summary
    # ==================== 最终检索 ====================
    summary["retrieval"] = {
        "avg_recall": sum(item["evaluation"]["recall_at_k"] for item in success_results) / total,
        "avg_precision": sum(item["evaluation"]["precision_at_k"] for item in success_results) / total,
        "avg_mrr": sum(item["evaluation"]["mrr"] for item in success_results) / total,
        "avg_ndcg": sum(item["evaluation"]["ndcg_at_k"] for item in success_results) / total
    }

    # ==================== Hybrid ====================
    if ENABLE_HYBRID_EVALUATION:
        hybrid = [ item["evaluation"]["hybrid"] for item in success_results if "hybrid" in item["evaluation"] ]
        if hybrid:
            summary["hybrid"] = {
                "avg_vector_recall": sum(item["vector_recall_at_k"] for item in hybrid) / len(hybrid),
                "avg_bm25_recall": sum(item["bm25_recall_at_k"] for item in hybrid) / len(hybrid),
                "avg_rrf_recall": sum(item["rrf_recall_at_k"] for item in hybrid) / len(hybrid),
                "avg_rrf_gain_vs_vector": sum(item["rrf_gain_vs_vector"] for item in hybrid) / len(hybrid),
                "avg_rrf_gain_vs_bm25": sum(item["rrf_gain_vs_bm25"] for item in hybrid) / len(hybrid),
                "avg_parent_duplicate_rate": sum(item["parent_duplicate"]["parent_duplicate_rate"] for item in hybrid) / len(hybrid)
            }

    # ==================== Reranker ====================
    if ENABLE_RERANKER_EVALUATION:
        reranker = [ item["evaluation"]["reranker"] for item in success_results if "reranker" in item["evaluation"] ]
        if reranker:
            gains = [item["recall_gain"] for item in reranker]
            summary["reranker"] = {
                "avg_before_recall": sum(item["before_recall"] for item in reranker) / len(reranker),
                "avg_after_recall": sum(item["after_recall"] for item in reranker) / len(reranker),
                "avg_recall_gain": sum(gains) / len(gains),
                "improved_cases": sum(gain > 0 for gain in gains),
                "degraded_cases": sum(gain < 0 for gain in gains),
                "unchanged_cases": sum(gain == 0 for gain in gains)
            }

    # ==================== Context ====================
    if ENABLE_CONTEXT_EVALUATION:
        context = [ item["evaluation"]["context"] for item in success_results if "context" in item["evaluation"] ]
        if context:
            summary["context"] = {
                "avg_neighbor_relevance": sum(item["neighbor_relevance"] for item in context) / len(context),
                "avg_neighbor_gain": sum(item["neighbor_gain"] for item in context) / len(context),
                "avg_context_chunk_count": sum(item["context_chunk_count"] for item in context) / len(context),
                "positive_gain_cases": sum(item["neighbor_gain"] > 0 for item in context),
                "negative_gain_cases": sum(item["neighbor_gain"] < 0 for item in context),
                "unchanged_cases": sum(item["neighbor_gain"] == 0 for item in context)
            }
    # ==================== 性能 ====================
    latencies = [item["latency_ms"] for item in success_results]
    summary["performance"] = {
        "avg_latency_ms": sum(latencies) / total,
        "max_latency_ms": max(latencies),
        "min_latency_ms": min(latencies)
    }
    return summary

# ==================== 每题指标 ====================
"""生成当前轮次每道题的指标"""
def build_question_dataframe(results):
    rows = []
    for item in results:
        row = {
            "run_id": RUN_ID,
            "question_id": item.get("case_id"),
            "success": item.get("success", False),
            "latency_ms": item.get("latency_ms", 0)
        }
        if not item.get("success") or "evaluation" not in item:
            rows.append(row)
            continue
        evaluation = item["evaluation"]
        # 最终检索指标
        row.update({
            "recall": evaluation["recall_at_k"],
            "precision": evaluation["precision_at_k"],
            "mrr": evaluation["mrr"],
            "ndcg": evaluation["ndcg_at_k"]
        })
        # Hybrid 指标
        if "hybrid" in evaluation:
            hybrid = evaluation["hybrid"]
            row.update({
                "vector_recall": hybrid["vector_recall_at_k"],
                "bm25_recall": hybrid["bm25_recall_at_k"],
                "rrf_recall": hybrid["rrf_recall_at_k"],
                "rrf_gain_vs_vector": hybrid["rrf_gain_vs_vector"],
                "rrf_gain_vs_bm25": hybrid["rrf_gain_vs_bm25"],
                "parent_duplicate_rate": hybrid["parent_duplicate"]["parent_duplicate_rate"]
            })
        # Reranker 指标
        if "reranker" in evaluation:
            reranker = evaluation["reranker"]
            row.update({
                "reranker_before": reranker["before_recall"],
                "reranker_after": reranker["after_recall"],
                "reranker_gain": reranker["recall_gain"]
            })
        # Context 指标
        if "context" in evaluation:
            context = evaluation["context"]
            row.update({
                "context_chunk_count": context["context_chunk_count"],
                "neighbor_relevance": context["neighbor_relevance"],
                "neighbor_gain": context["neighbor_gain"]
            })

        rows.append(row)
    return pd.DataFrame(rows)

# ==================== 保存当前轮次 ====================
"""保存当前轮次汇总"""
def save_summary(results):
    # 计算总体指标
    summary = calculate_summary(results)
    # 保存总体 JSON
    save_json(summary, "summary.json")
    # 生成每题指标
    df = build_question_dataframe(results)
    # 保存每题 CSV
    df.to_csv( os.path.join(CURRENT_RESULT_DIR, "question_metrics.csv"), index=False, encoding="utf-8-sig" )
    return summary, df

# ==================== 历史数据 ====================
"""保存所有测试轮次和问题历史数据"""
def update_history(summary, question_df):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    retrieval = summary.get("retrieval", {})
    hybrid = summary.get("hybrid", {})
    reranker = summary.get("reranker", {})
    context = summary.get("context", {})
    performance = summary.get("performance", {})
    # 当前轮次总体数据
    run_row = {
        "run_id": RUN_ID,
        "total_questions": summary.get("total_questions", 0),
        "successful_questions": summary.get("successful_questions", 0),
        "failed_questions": summary.get("failed_questions", 0),
        "avg_recall": retrieval.get("avg_recall", 0),
        "avg_precision": retrieval.get("avg_precision", 0),
        "avg_mrr": retrieval.get("avg_mrr", 0),
        "avg_ndcg": retrieval.get("avg_ndcg", 0),
        "avg_vector_recall": hybrid.get("avg_vector_recall", 0),
        "avg_bm25_recall": hybrid.get("avg_bm25_recall", 0),
        "avg_rrf_recall": hybrid.get("avg_rrf_recall", 0),
        "avg_rrf_gain_vs_vector": hybrid.get("avg_rrf_gain_vs_vector", 0),
        "avg_rrf_gain_vs_bm25": hybrid.get("avg_rrf_gain_vs_bm25", 0),
        "avg_parent_duplicate_rate": hybrid.get("avg_parent_duplicate_rate", 0),
        "reranker_before": reranker.get("avg_before_recall", 0),
        "reranker_after": reranker.get("avg_after_recall", 0),
        "reranker_gain": reranker.get("avg_recall_gain", 0),
        "reranker_improved": reranker.get("improved_cases", 0),
        "reranker_degraded": reranker.get("degraded_cases", 0),
        "reranker_unchanged": reranker.get("unchanged_cases", 0),
        "avg_context_chunk_count": context.get("avg_context_chunk_count", 0),
        "avg_neighbor_relevance": context.get("avg_neighbor_relevance", 0),
        "avg_neighbor_gain": context.get("avg_neighbor_gain", 0),
        "avg_latency_ms": performance.get("avg_latency_ms", 0),
        "max_latency_ms": performance.get("max_latency_ms", 0),
        "min_latency_ms": performance.get("min_latency_ms", 0)
    }
    # 保存所有轮次总体数据
    run_file = os.path.join(HISTORY_DIR, "all_runs_summary.csv")
    run_df = pd.DataFrame([run_row])
    if os.path.exists(run_file):
        old_run_df = pd.read_csv(run_file)
        run_df = pd.concat([old_run_df, run_df], ignore_index=True)
    run_df.to_csv( run_file, index=False, encoding="utf-8-sig"  )
    # 保存历史 JSON
    with open( os.path.join(HISTORY_DIR, "all_runs_summary.json"), "w", encoding="utf-8" ) as f:
        json.dump( run_df.to_dict(orient="records"), f, ensure_ascii=False, indent=2 )
    # 保存所有问题历史数据
    question_file = os.path.join( HISTORY_DIR, "all_questions_history.csv" )
    if os.path.exists(question_file):
        old_question_df = pd.read_csv(question_file)
        question_df = pd.concat( [old_question_df, question_df], ignore_index=True )
    question_df.to_csv( question_file, index=False, encoding="utf-8-sig" )
    return run_df, question_df

# ==================== 图表 ====================
"""生成最终检索指标图"""
def plot_retrieval_metrics(df):
    columns = [ ("recall", "Recall"), ("precision", "Precision"), ("mrr", "MRR"), ("ndcg", "NDCG") ]
    data = [ (label, df[column].mean()) for column, label in columns if column in df.columns ]
    if not data:
        print("⚠️ 没有最终检索数据，跳过 metrics.png")
        return
    labels, values = zip(*data)
    plt.figure(figsize=(8, 5))
    plt.bar(labels, values)
    plt.ylim(0, 1)
    plt.ylabel("Score")
    plt.title(f"RAG Retrieval Metrics - Result {RUN_ID}")
    for index, value in enumerate(values):
        plt.text( index, value + 0.02, f"{value:.2%}", ha="center"  )
    filepath = os.path.join( CURRENT_RESULT_DIR, "metrics.png" )
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f"✅ 已生成：{filepath}")
"""生成 Vector、BM25、RRF 对比图"""
def plot_hybrid_metrics(df):
    columns = [ ("vector_recall", "Vector"), ("bm25_recall", "BM25"), ("rrf_recall", "RRF") ]
    data = [ (label, df[column].mean()) for column, label in columns if column in df.columns ]
    if not data:
        print("⚠️ 没有 Hybrid 数据，跳过 hybrid.png")
        return
    labels, values = zip(*data)
    plt.figure(figsize=(8, 5))
    plt.bar(labels, values)
    plt.ylim(0, 1)
    plt.ylabel("Recall")
    plt.title(f"Hybrid Retrieval - Result {RUN_ID}")
    for index, value in enumerate(values):
        plt.text( index, value + 0.02, f"{value:.2%}",  ha="center" )
    filepath = os.path.join( CURRENT_RESULT_DIR,  "hybrid.png" )
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f"✅ 已生成：{filepath}")
"""生成 Reranker 前后对比图"""
def plot_reranker_metrics(df):
    if "reranker_before" not in df.columns or "reranker_after" not in df.columns:
        print("⚠️ 没有 Reranker 数据，跳过 reranker.png")
        return
    values = [ df["reranker_before"].mean(), df["reranker_after"].mean() ]
    labels = ["Before", "After"]
    plt.figure(figsize=(8, 5))
    plt.bar(labels, values)
    plt.ylim(0, 1)
    plt.ylabel("Recall")
    plt.title(f"Reranker Before vs After - Result {RUN_ID}")
    for index, value in enumerate(values):
        plt.text( index, value + 0.02, f"{value:.2%}", ha="center" )
    filepath = os.path.join( CURRENT_RESULT_DIR, "reranker.png" )
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f"✅ 已生成：{filepath}")
"""生成每道题 Recall 图"""
def plot_question_recall(df):
    if "recall" not in df.columns:
        print("⚠️ 没有 Recall 数据，跳过 question_recall.png")
        return
    valid_df = df[df["success"] == True]
    if valid_df.empty:
        print("⚠️ 没有成功测试数据，跳过 question_recall.png")
        return
    plt.figure(figsize=(12, 6))
    plt.bar( valid_df["question_id"], valid_df["recall"] )
    plt.ylim(0, 1)
    plt.ylabel("Recall")
    plt.xlabel("Question")
    plt.title(f"Recall@K by Question - Result {RUN_ID}")
    plt.xticks(rotation=45)
    filepath = os.path.join( CURRENT_RESULT_DIR, "question_recall.png" )
    plt.tight_layout()
    plt.savefig(filepath, dpi=150)
    plt.close()
    print(f"✅ 已生成：{filepath}")
# ==================== 输出汇总 ====================
"""输出当前轮次总体结果"""
def print_summary(summary):
    print("\n" + "=" * 60)
    print("RAG 总体评估结果")
    print("=" * 60)
    print(f"测试轮次：result{RUN_ID}")
    print(f"测试问题：{summary.get('total_questions', 0)}")
    print(f"成功问题：{summary.get('successful_questions', 0)}")
    print(f"失败问题：{summary.get('failed_questions', 0)}")
    retrieval = summary.get("retrieval", {})
    if retrieval:
        print("\n【最终检索】")
        print(f"平均 Recall：{retrieval['avg_recall']:.4f}")
        print(f"平均 Precision：{retrieval['avg_precision']:.4f}")
        print(f"平均 MRR：{retrieval['avg_mrr']:.4f}")
        print(f"平均 NDCG：{retrieval['avg_ndcg']:.4f}")
    hybrid = summary.get("hybrid", {})
    if hybrid:
        print("\n【Hybrid Retrieval】")
        print(f"Vector Recall：{hybrid['avg_vector_recall']:.4f}")
        print(f"BM25 Recall：{hybrid['avg_bm25_recall']:.4f}")
        print(f"RRF Recall：{hybrid['avg_rrf_recall']:.4f}")
        print(f"RRF vs Vector：{hybrid['avg_rrf_gain_vs_vector']:+.4f}")
        print(f"RRF vs BM25：{hybrid['avg_rrf_gain_vs_bm25']:+.4f}")
        print(f"Parent 重复率：{hybrid['avg_parent_duplicate_rate']:.4f}")
    reranker = summary.get("reranker", {})
    if reranker:
        print("\n【Reranker】")
        print(f"Before Recall：{reranker['avg_before_recall']:.4f}")
        print(f"After Recall：{reranker['avg_after_recall']:.4f}")
        print(f"Recall Gain：{reranker['avg_recall_gain']:+.4f}")
        print(f"提升：{reranker['improved_cases']}题")
        print(f"下降：{reranker['degraded_cases']}题")
        print(f"不变：{reranker['unchanged_cases']}题")
    context = summary.get("context", {})
    if context:
        print("\n【Context Expansion】")
        print(f"平均 Context Chunk：{context['avg_context_chunk_count']:.2f}")
        print(f"平均 Neighbor 相关率：{context['avg_neighbor_relevance']:.4f}")
        print(f"平均 Neighbor Gain：{context['avg_neighbor_gain']:+.4f}")
    performance = summary.get("performance", {})
    if performance:
        print("\n【性能】")
        print(f"平均延迟：{performance['avg_latency_ms']:.2f} ms")
        print(f"最大延迟：{performance['max_latency_ms']:.2f} ms")
        print(f"最小延迟：{performance['min_latency_ms']:.2f} ms")
# ==================== 主函数 ====================
def main():
    print("=" * 60)
    print("RAG 自动化问题测试")
    print("=" * 60)
    print(f"当前测试轮次：result{RUN_ID}")
    # 读取测试问题
    with open(TEST_CASE_FILE, "r", encoding="utf-8") as f:
        test_cases=json.load(f)
    print(f"测试数量：{len(test_cases)}")
    # 创建结果目录
    os.makedirs(CURRENT_RESULT_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    # 逐题测试
    results = [ evaluate_case(test_case) for test_case in test_cases ]
    # 保存当前轮次汇总
    summary, question_df = save_summary(results)
    # 保存历史数据
    update_history(summary, question_df)
    # 生成当前轮次图表
    plot_retrieval_metrics(question_df)
    if ENABLE_HYBRID_EVALUATION:
        plot_hybrid_metrics(question_df)
    if ENABLE_RERANKER_EVALUATION:
        plot_reranker_metrics(question_df)
    plot_question_recall(question_df)
    # 输出总体结果
    print_summary(summary)
    print("\n" + "=" * 60)
    print("全部测试完成")
    print("=" * 60)
    print(f"当前结果：{CURRENT_RESULT_DIR}")
    print(f"历史数据：{HISTORY_DIR}")
if __name__ == "__main__":
    main()

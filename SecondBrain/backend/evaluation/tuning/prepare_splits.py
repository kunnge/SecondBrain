"""Create deterministic document-grouped train, validation, and test splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.tuning.space import load_search_config


EVALUATION_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = EVALUATION_DIR / "test_cases.json"
CHUNK_DIR = EVALUATION_DIR / "evaluation_chunks"
SPLIT_DIR = EVALUATION_DIR / "splits"
MANIFEST_PATH = EVALUATION_DIR / "split_manifest.json"
RATIOS = {"train": 0.6, "validation": 0.2, "test": 0.2}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_question_id(case: dict[str, Any]) -> str:
    existing = case.get("question_id")
    if existing:
        return str(existing)
    source = "|".join(
        (
            str(case.get("document_id") or ""),
            str(case.get("suite") or ""),
            str(case.get("id") or ""),
            str(case.get("query") or ""),
        )
    )
    return "legacy-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def validate_case_labels(cases: list[dict[str, Any]], chunk_dir: Path | None = None) -> None:
    chunk_dir = chunk_dir or CHUNK_DIR
    documents: dict[str, dict[str, Any]] = {}
    documents_by_filename: dict[str, list[str]] = defaultdict(list)
    for path in sorted(chunk_dir.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取切分导出 {path}: {exc}") from exc
        document_id = str(document.get("document_id") or "")
        if document_id:
            documents[document_id] = document
            filename = str(document.get("filename") or path.name)
            documents_by_filename[Path(filename).name].append(document_id)

    errors: list[str] = []
    for case in cases:
        question_id = stable_question_id(case)
        document_id = str(case.get("document_id") or "")
        document = documents.get(document_id)
        if not case.get("query"):
            errors.append(f"{question_id}: 缺少 query")
        if not document:
            source_filename = Path(str(case.get("source_filename") or "")).name
            current_ids = documents_by_filename.get(source_filename, [])
            hint = f"；文件 {source_filename} 当前对应 document_id：{current_ids}" if current_ids else ""
            errors.append(
                f"{question_id}: document_id 不存在于 evaluation_chunks：{document_id}{hint}"
            )
            continue

        parents = {str(parent.get("parent_id")): parent for parent in document.get("parents", [])}
        relevant_parent_ids = {str(value) for value in case.get("relevant_parent_ids", [])}
        if not relevant_parent_ids:
            errors.append(f"{question_id}: 缺少 relevant_parent_ids")
        for parent_id in relevant_parent_ids - set(parents):
            errors.append(f"{question_id}: 父块标签不存在：{parent_id}")

        refs = case.get("relevant_chunk_refs") or []
        if not refs:
            errors.append(f"{question_id}: 缺少 relevant_chunk_refs")
        for ref in refs:
            parent_id = str(ref.get("parent_id") or "")
            parent = parents.get(parent_id)
            if not parent:
                errors.append(f"{question_id}: 子块父标签不存在：{parent_id}")
                continue
            if parent_id not in relevant_parent_ids:
                errors.append(f"{question_id}: 子块父标签 {parent_id} 不在 relevant_parent_ids 中")
            matches = [
                child
                for child in parent.get("children", [])
                if str(child.get("block_id") or "") == str(ref.get("block_id") or "")
                and int(child.get("chunk_index", 0)) == int(ref.get("chunk_index", 0))
            ]
            if len(matches) != 1:
                errors.append(
                    f"{question_id}: 子块标签映射应唯一，实际 {len(matches)} 条，"
                    f"parent={parent_id} block={ref.get('block_id')} index={ref.get('chunk_index', 0)}"
                )
    if errors:
        preview = "\n".join(f"- {error}" for error in errors[:30])
        raise ValueError(f"评测题标签校验失败，共 {len(errors)} 个问题：\n{preview}")


def configured_ratios() -> dict[str, float]:
    config = load_search_config()
    ratios = config.get("split_ratios", RATIOS)
    if not isinstance(ratios, dict) or set(ratios) != set(RATIOS):
        raise ValueError("split_ratios 必须包含 train、validation、test")
    values = {name: float(ratios[name]) for name in RATIOS}
    if any(value <= 0 for value in values.values()) or abs(sum(values.values()) - 1.0) > 1e-9:
        raise ValueError("split_ratios 必须为正数且总和为 1")
    return values


def assignment_cost(counts: dict[str, int], targets: dict[str, float], ratios: dict[str, float]) -> float:
    return sum(((counts[name] - targets[name]) / max(targets[name], 1.0)) ** 2 for name in ratios)


def assign_documents(
    cases: list[dict[str, Any]], seed: int, ratios: dict[str, float] | None = None
) -> dict[str, str]:
    ratios = ratios or RATIOS
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        document_id = str(case.get("document_id") or "")
        if not document_id:
            raise ValueError(f"{stable_question_id(case)}: 缺少 document_id，无法按文档分组")
        groups[document_id].append(case)
    if len(groups) < 3:
        raise ValueError("至少需要 3 份不同文档，才能让 train、validation、test 都有数据")

    targets = {name: len(cases) * ratio for name, ratio in ratios.items()}
    best_assignment: dict[str, str] | None = None
    best_cost = float("inf")
    rng = random.Random(seed)

    for _ in range(512):
        order = list(groups)
        rng.shuffle(order)
        order.sort(key=lambda document_id: -len(groups[document_id]))
        counts = {name: 0 for name in ratios}
        assigned_docs = {name: 0 for name in ratios}
        assignment: dict[str, str] = {}

        for index, document_id in enumerate(order):
            remaining_docs = len(order) - index - 1
            empty_names = [name for name in ratios if assigned_docs[name] == 0]
            candidate_names = list(ratios)
            if remaining_docs <= len(empty_names) - 1:
                candidate_names = empty_names

            case_count = len(groups[document_id])
            scored = []
            for split_name in candidate_names:
                counts[split_name] += case_count
                scored.append((assignment_cost(counts, targets, ratios), split_name))
                counts[split_name] -= case_count
            lowest = min(score for score, _ in scored)
            tied = [name for score, name in scored if abs(score - lowest) < 1e-12]
            chosen = rng.choice(tied)
            assignment[document_id] = chosen
            counts[chosen] += case_count
            assigned_docs[chosen] += 1

        score = assignment_cost(counts, targets, ratios)
        if score < best_cost:
            best_cost = score
            best_assignment = assignment

    assert best_assignment is not None
    return best_assignment


def prepare_splits(
    input_path: Path,
    seed: int,
    ratios: dict[str, float] | None = None,
    split_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    ratios = ratios or configured_ratios()
    split_dir = split_dir or SPLIT_DIR
    manifest_path = manifest_path or MANIFEST_PATH
    raw_bytes = input_path.read_bytes()
    try:
        cases = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取评测题集 {input_path}: {exc}") from exc
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"评测题集必须是非空 JSON 数组：{input_path}")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise ValueError("评测题集中的每条记录都必须是 JSON 对象")
        case = dict(raw_case)
        question_id = stable_question_id(case)
        if question_id in seen_ids:
            raise ValueError(f"question_id 重复：{question_id}")
        seen_ids.add(question_id)
        case["question_id"] = question_id
        normalized.append(case)

    validate_case_labels(normalized)
    assignment = assign_documents(normalized, seed, ratios)
    split_cases: dict[str, list[dict[str, Any]]] = {name: [] for name in ratios}
    split_documents: dict[str, list[str]] = {name: [] for name in ratios}
    for case in normalized:
        split_name = assignment[str(case["document_id"])]
        split_cases[split_name].append(case)
    for document_id, split_name in assignment.items():
        split_documents[split_name].append(document_id)

    for values in split_cases.values():
        values.sort(key=lambda item: item["question_id"])
    for values in split_documents.values():
        values.sort()

    dataset_hash = hashlib.sha256(raw_bytes).hexdigest()
    split_payload = {
        "seed": seed,
        "ratios": ratios,
        "assignment": assignment,
        "question_ids": {
            name: [case["question_id"] for case in values]
            for name, values in split_cases.items()
        },
    }
    split_hash = canonical_hash(split_payload)
    split_dir.mkdir(parents=True, exist_ok=True)
    split_stats = {}
    for name, values in split_cases.items():
        output = split_dir / f"{name}.json"
        output.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        split_stats[name] = {
            "question_count": len(values),
            "document_count": len(split_documents[name]),
            "document_ids": split_documents[name],
            "question_ids": [case["question_id"] for case in values],
            "data_hash": canonical_hash(values),
        }

    manifest = {
        "schema_version": 1,
        "seed": seed,
        "ratios": ratios,
        "dataset_path": str(input_path.resolve()),
        "dataset_hash": dataset_hash,
        "split_hash": split_hash,
        "total_question_count": len(normalized),
        "total_document_count": len(assignment),
        "splits": split_stats,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="按文档分组拆分检索评测题集")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="完整题集 JSON 路径")
    parser.add_argument("--seed", type=int, help="固定随机种子，默认读取 search_space.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="拆分输出目录；默认使用 evaluation/splits 和 evaluation/split_manifest.json",
    )
    args = parser.parse_args()
    config = load_search_config()
    seed = args.seed if args.seed is not None else int(config.get("split_seed", 42))
    ratios = configured_ratios()
    output_dir = args.output_dir.resolve() if args.output_dir else None
    manifest = prepare_splits(
        args.input.resolve(),
        seed,
        ratios,
        split_dir=output_dir / "splits" if output_dir else None,
        manifest_path=output_dir / "split_manifest.json" if output_dir else None,
    )
    for name, split in manifest["splits"].items():
        print(f"{name}: {split['question_count']} 题 / {split['document_count']} 份文档")
    print(f"数据哈希：{manifest['dataset_hash']}")
    print(f"拆分哈希：{manifest['split_hash']}")


if __name__ == "__main__":
    main()

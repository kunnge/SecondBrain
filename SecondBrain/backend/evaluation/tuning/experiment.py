"""Experiment identity, input integrity, and durable JSON output helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.tuning.prepare_splits import canonical_hash


BACKEND_DIR = Path(__file__).resolve().parents[2]
EVALUATION_DIR = BACKEND_DIR / "evaluation"
TUNING_DIR = EVALUATION_DIR / "tuning"
SPLIT_DIR = EVALUATION_DIR / "splits"
MANIFEST_PATH = EVALUATION_DIR / "split_manifest.json"
DEFAULT_DATASET_PATH = EVALUATION_DIR / "test_cases.json"
LOCAL_FINGERPRINT_FILES = (
    "evaluation/tuning/space.py",
    "evaluation/tuning/experiment.py",
    "evaluation/tuning/runtime.py",
    "evaluation/tuning/run_tuning.py",
    "evaluation/tuning/finalize_test.py",
    "evaluation/tuning/report.py",
    "evaluation/tuning/prepare_splits.py",
    "evaluation/generate_test_cases.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_hash(value: Any) -> str:
    return canonical_hash(value)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc


def source_digest() -> str:
    digest = hashlib.sha256()
    for relative in LOCAL_FINGERPRINT_FILES:
        path = BACKEND_DIR / relative
        if not path.is_file():
            raise FileNotFoundError(f"实验指纹源文件不存在：{relative}")
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def read_verified_splits(
    manifest_path: Path = MANIFEST_PATH,
    split_dir: Path = SPLIT_DIR,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    names: tuple[str, ...] = ("train", "validation"),
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("splits"), dict):
        raise ValueError(f"拆分清单结构无效：{manifest_path}")
    manifest_document_owners: dict[str, str] = {}
    manifest_question_owners: dict[str, str] = {}
    for split_name in ("train", "validation", "test"):
        stats = manifest["splits"].get(split_name)
        if not isinstance(stats, dict):
            raise ValueError(f"split_manifest.json 缺少 {split_name} 集")
        document_ids = list(map(str, stats.get("document_ids", [])))
        question_id_list = list(map(str, stats.get("question_ids", [])))
        if len(document_ids) != stats.get("document_count") or len(set(document_ids)) != len(document_ids):
            raise ValueError(f"{split_name} 文档清单与数量不一致")
        if len(question_id_list) != stats.get("question_count") or len(set(question_id_list)) != len(question_id_list):
            raise ValueError(f"{split_name} 题目清单与数量不一致")
        for document_id in document_ids:
            previous = manifest_document_owners.setdefault(document_id, split_name)
            if previous != split_name:
                raise ValueError(f"文档 {document_id} 跨 {previous}/{split_name} 集，存在数据泄漏")
        for question_id in question_id_list:
            previous = manifest_question_owners.setdefault(question_id, split_name)
            if previous != split_name:
                raise ValueError(f"题目 {question_id} 跨 {previous}/{split_name} 集，存在数据泄漏")
    raw_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if raw_hash != manifest.get("dataset_hash"):
        raise ValueError("test_cases.json 已变化，请重新生成 splits 后再开始实验")

    datasets: dict[str, list[dict[str, Any]]] = {}
    document_owners: dict[str, str] = {}
    question_ids: set[str] = set()
    for name in names:
        stats = manifest["splits"].get(name)
        if not isinstance(stats, dict):
            raise ValueError(f"split_manifest.json 缺少 {name} 集")
        cases = load_json(split_dir / f"{name}.json")
        if not isinstance(cases, list) or len(cases) != stats.get("question_count"):
            raise ValueError(f"{name}.json 与拆分清单题数不一致")
        if canonical_hash(cases) != stats.get("data_hash"):
            raise ValueError(f"{name}.json 哈希与拆分清单不一致")
        found_ids = []
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError(f"{name}.json 中存在非对象题目")
            question_id = str(case.get("question_id") or case.get("id") or "")
            document_id = str(case.get("document_id") or "")
            if not question_id or not document_id:
                raise ValueError(f"{name} 集中的题目缺少 question_id 或 document_id")
            if question_id in question_ids:
                raise ValueError(f"题目跨集合重复：{question_id}")
            question_ids.add(question_id)
            found_ids.append(question_id)
            previous = document_owners.setdefault(document_id, name)
            if previous != name:
                raise ValueError(f"文档 {document_id} 跨 {previous}/{name} 集，存在数据泄漏")
            case.setdefault("question_id", question_id)
        if sorted(found_ids) != sorted(stats.get("question_ids", [])):
            raise ValueError(f"{name} 集的 question_id 与拆分清单不一致")
        if sorted({str(case["document_id"]) for case in cases}) != sorted(stats.get("document_ids", [])):
            raise ValueError(f"{name} 集的 document_id 与拆分清单不一致")
        datasets[name] = cases
    return manifest, datasets


def build_experiment_identity(
    manifest: dict[str, Any],
    snapshot: dict[str, Any],
    search_config: dict[str, Any],
    formal_parameters: dict[str, Any],
    experiment_id: str | None,
) -> tuple[str, dict[str, Any]]:
    split_hashes = {
        name: details.get("data_hash")
        for name, details in sorted(manifest.get("splits", {}).items())
    }
    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "dataset_hash": manifest.get("dataset_hash"),
        "split_hash": manifest.get("split_hash"),
        "split_data_hashes": split_hashes,
        "seed": manifest.get("seed"),
        "ratios": manifest.get("ratios"),
        "retrieval_snapshot_id": snapshot.get("snapshot_id"),
        "retrieval_snapshot_components": snapshot.get("components"),
        "local_code_digest": source_digest(),
        "formal_parameters": formal_parameters,
        "search_config": search_config,
        "objective_version": search_config.get("objective_version"),
    }
    fingerprint = canonical_hash(payload)
    return fingerprint, payload


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(line + "\n")
        file.flush()
        os.fsync(file.fileno())

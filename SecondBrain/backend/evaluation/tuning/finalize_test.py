"""Evaluate the selected configuration on the held-out test split exactly once."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from config import settings
from evaluation.run_evaluation import validate_cases
from evaluation.tuning.experiment import (
    DEFAULT_DATASET_PATH,
    MANIFEST_PATH,
    SPLIT_DIR,
    TUNING_DIR,
    atomic_write_json,
    load_json,
    read_verified_splits,
    utc_now,
)
from evaluation.tuning.report import create_report
from evaluation.tuning.runtime import EvaluationClient, SnapshotChangedError, evaluate_dataset


def baseline_parameters() -> dict[str, Any]:
    return {
        "child_top_k": settings.RETRIEVAL_CHILD_TOP_K,
        "parent_top_k": settings.RETRIEVAL_PARENT_TOP_K,
        "rrf_k": settings.RRF_K,
        "reranker_candidates": None,
    }


def resolve_experiment_dir(value: str | None, fingerprint: str | None) -> Path:
    if value and fingerprint:
        raise ValueError("--experiment-dir 与 --fingerprint 只能指定一个")
    if value:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    if fingerprint:
        if Path(fingerprint).name != fingerprint:
            raise ValueError("--fingerprint 只能传实验目录名")
        return TUNING_DIR / fingerprint
    raise ValueError("必须指定 --experiment-dir 或 --fingerprint")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用验证集选出的参数执行一次独立测试集评估")
    parser.add_argument("--experiment-dir", help="run_tuning 输出的实验目录")
    parser.add_argument("--fingerprint", help="run_tuning 输出的实验指纹目录名")
    parser.add_argument("--dataset", type=Path, help="覆盖实验记录中的评测题集路径")
    parser.add_argument("--split-dir", type=Path, help="覆盖实验记录中的拆分目录")
    parser.add_argument("--manifest", type=Path, help="覆盖实验记录中的拆分清单路径")
    return parser.parse_args()


def evaluate_test(
    experiment_dir: Path,
    manifest_path: Path | None = None,
    split_dir: Path | None = None,
    client: EvaluationClient | None = None,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    experiment_path = experiment_dir / "experiment.json"
    experiment = load_json(experiment_path)
    data_sources = experiment.get("data_sources", {})
    manifest_path = manifest_path or Path(data_sources.get("manifest_path", MANIFEST_PATH))
    split_dir = split_dir or Path(data_sources.get("split_dir", SPLIT_DIR))
    dataset_path = dataset_path or Path(data_sources.get("dataset_path", DEFAULT_DATASET_PATH))
    if experiment.get("locked"):
        existing = experiment_dir / "test_results.json"
        if existing.exists():
            return load_json(existing)
        raise RuntimeError("该实验已锁定，但缺少最终测试结果；请检查实验文件")
    if experiment.get("status") not in {"awaiting_test", "testing"}:
        raise RuntimeError("实验尚未完成训练搜索与验证集选优，不能读取测试集")

    best_config = load_json(experiment_dir / "best_config.json")
    if best_config.get("experiment_fingerprint") != experiment.get("fingerprint"):
        raise ValueError("best_config.json 不属于当前实验")
    expected_snapshot = str(best_config.get("snapshot_id") or "")
    if not expected_snapshot:
        raise ValueError("best_config.json 中缺少检索快照")
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        identity = experiment.get("identity", {})
        if manifest.get("dataset_hash") != identity.get("dataset_hash") or manifest.get("split_hash") != identity.get("split_hash"):
            raise ValueError("测试集拆分已变化；拒绝在不同数据上完成旧实验")
    _, datasets = read_verified_splits(
        manifest_path=manifest_path,
        split_dir=split_dir,
        dataset_path=dataset_path,
        names=("test",),
    )
    validate_cases(datasets["test"])
    client = client or EvaluationClient()
    client.assert_snapshot(expected_snapshot)
    snapshot = {"snapshot_id": expected_snapshot}
    parent_top_k = int(best_config["parameters"]["parent_top_k"])
    baseline = baseline_parameters()
    selected = dict(best_config["parameters"])

    output_path = experiment_dir / "test_results.json"
    existing_result = None
    if output_path.exists():
        existing_result = load_json(output_path)
        if existing_result.get("snapshot_id") != expected_snapshot:
            raise ValueError("已有测试结果的快照不匹配")
        if existing_result.get("status") == "complete":
            experiment.update({"status": "complete", "locked": True, "updated_at": utc_now()})
            atomic_write_json(experiment_path, experiment)
            return existing_result
        if existing_result.get("status") != "baseline_complete":
            raise RuntimeError("已有测试结果状态未知；拒绝覆盖以免丢失测试集运行记录")
    started_marker = experiment_dir / "test_started.json"
    if not started_marker.exists():
        atomic_write_json(started_marker, {
            "started_at": utc_now(),
            "snapshot_id": expected_snapshot,
            "parameters": selected,
        })
    experiment.update({"status": "testing", "updated_at": utc_now()})
    atomic_write_json(experiment_path, experiment)

    try:
        if existing_result:
            baseline_summary = existing_result["baseline"]
            print("复用已完成的测试集基线")
        else:
            baseline_summary = evaluate_dataset(
                datasets["test"], baseline, settings.RETRIEVAL_PARENT_TOP_K,
                client, progress_prefix="Test baseline",
            )
            client.assert_snapshot(expected_snapshot)
            atomic_write_json(output_path, {
                "status": "baseline_complete",
                "snapshot_id": expected_snapshot,
                "experiment_fingerprint": experiment["fingerprint"],
                "question_count": len(datasets["test"]),
                "baseline": baseline_summary,
                "updated_at": utc_now(),
            })
        selected_summary = evaluate_dataset(
            datasets["test"], selected, parent_top_k,
            client, progress_prefix="Test selected",
        )
        client.assert_snapshot(expected_snapshot)
    except SnapshotChangedError as exc:
        atomic_write_json(experiment_dir / "invalid.json", {"reason": str(exc), "at": utc_now()})
        experiment.update({"status": "invalid", "updated_at": utc_now()})
        atomic_write_json(experiment_path, experiment)
        raise
    except Exception as exc:
        atomic_write_json(experiment_dir / "test_error.json", {
            "error": f"{type(exc).__name__}: {exc}",
            "at": utc_now(),
            "snapshot_id": expected_snapshot,
        })
        raise

    result = {
        "status": "complete",
        "snapshot_id": snapshot["snapshot_id"],
        "experiment_fingerprint": experiment["fingerprint"],
        "completed_at": utc_now(),
        "question_count": len(datasets["test"]),
        "selection_split": "validation",
        "baseline": baseline_summary,
        "selected": selected_summary,
    }
    create_report(
        experiment_dir / "report.svg",
        load_training_trials(experiment_dir),
        load_validation_candidates(experiment_dir),
        result,
    )
    atomic_write_json(output_path, result)
    experiment.update({
        "status": "complete",
        "locked": True,
        "test_completed_at": result["completed_at"],
        "updated_at": utc_now(),
    })
    atomic_write_json(experiment_path, experiment)
    print(f"测试集最终评估完成：baseline={baseline_summary['score']:.4f}, selected={selected_summary['score']:.4f}")
    print(f"结果：{output_path}")
    return result


def load_training_trials(experiment_dir: Path) -> list[dict[str, Any]]:
    train_results = load_json(experiment_dir / "train_results.json")
    return train_results.get("trials", [])


def load_validation_candidates(experiment_dir: Path) -> list[dict[str, Any]]:
    validation = load_json(experiment_dir / "validation_results.json")
    return validation.get("candidates", [])


def main() -> None:
    args = parse_args()
    evaluate_test(
        resolve_experiment_dir(args.experiment_dir, args.fingerprint),
        manifest_path=args.manifest.resolve() if args.manifest else None,
        split_dir=args.split_dir.resolve() if args.split_dir else None,
        dataset_path=args.dataset.resolve() if args.dataset else None,
    )


if __name__ == "__main__":
    main()

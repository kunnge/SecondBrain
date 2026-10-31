"""Search retrieval parameters against train data and select on validation data."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from config import settings
from evaluation.run_evaluation import validate_cases
from evaluation.tuning.experiment import (
    DEFAULT_DATASET_PATH,
    MANIFEST_PATH,
    SPLIT_DIR,
    TUNING_DIR,
    append_jsonl,
    atomic_write_json,
    build_experiment_identity,
    load_json,
    read_verified_splits,
    utc_now,
)
from evaluation.tuning.report import create_report
from evaluation.tuning.runtime import EvaluationClient, SnapshotChangedError, evaluate_dataset
from evaluation.tuning.space import conditional_integer_bounds, load_search_config, values_for


def canonical_parameters(trial) -> dict[str, int]:
    value = trial.user_attrs.get("parameters")
    if value:
        return {name: int(number) for name, number in value.items()}
    child_top_k = trial.params.get("child_top_k")
    dynamic_name = f"reranker_candidates_child_{child_top_k}"
    return {
        "child_top_k": int(child_top_k),
        "rrf_k": int(trial.params["rrf_k"]),
        "reranker_candidates": int(trial.params[dynamic_name]),
    }


def trial_summary(trial) -> dict[str, Any]:
    return {
        "number": trial.number,
        "state": trial.state.name,
        "parameters": trial.user_attrs.get("parameters"),
        "score": trial.value if trial.state.name == "COMPLETE" else None,
        "metrics": trial.user_attrs.get("metrics"),
        "stage_metrics": trial.user_attrs.get("stage_metrics"),
        "duration_seconds": trial.user_attrs.get("duration_seconds"),
        "error": trial.user_attrs.get("error"),
        "finished_at": trial.user_attrs.get("finished_at"),
    }


def persist_trial_log(experiment_dir: Path, study, trial) -> None:
    log_path = experiment_dir / "trials.jsonl"
    known_numbers: set[int] = set()
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                known_numbers.add(int(json.loads(line)["number"]))
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    for finished in study.trials:
        if finished.state.name == "RUNNING" or finished.number in known_numbers:
            continue
        append_jsonl(log_path, trial_summary(finished))
    summaries = [trial_summary(item) for item in study.trials if item.state.name != "RUNNING"]
    atomic_write_json(
        experiment_dir / "train_results.json",
        {
            "baseline": load_json(experiment_dir / "baseline_train.json")["summary"],
            "trials": summaries,
        },
    )
    if trial is not None:
        completed = len([item for item in study.trials if item.state.name != "RUNNING"])
        durations = [
            float(item.user_attrs["duration_seconds"])
            for item in study.trials
            if item.state.name != "RUNNING" and item.user_attrs.get("duration_seconds") is not None
        ]
        average = sum(durations) / len(durations) if durations else None
        remaining = max(0, int(experiment_dir.joinpath("target_trials.txt").read_text(encoding="utf-8")) - completed)
        eta = f", 预计剩余 {remaining * average / 60:.1f} 分钟" if average is not None else ""
        best = study.best_value if any(item.state.name == "COMPLETE" for item in study.trials) else None
        best_text = f"{best:.4f}" if best is not None else "暂无有效结果"
        print(f"\r试验进度 {completed}/{remaining + completed}，当前最佳 {best_text}{eta}", end="", flush=True)


def load_existing_phase(path: Path, snapshot_id: str, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = load_json(path)
    if value.get("snapshot_id") != snapshot_id or value.get("experiment_fingerprint") != fingerprint:
        raise ValueError(f"已保存的阶段结果与当前快照不匹配：{path}")
    return value


def evaluate_phase(
    name: str,
    cases: list[dict[str, Any]],
    parameters: dict[str, Any],
    experiment_dir: Path,
    snapshot_id: str,
    fingerprint: str,
    parent_top_k: int,
    client: EvaluationClient,
) -> dict[str, Any]:
    output_path = experiment_dir / f"{name}.json"
    existing = load_existing_phase(output_path, snapshot_id, fingerprint)
    if existing:
        print(f"复用已完成阶段：{name}（{existing['summary']['question_count']} 题）")
        return existing
    summary = evaluate_dataset(
        cases,
        parameters,
        parent_top_k,
        client,
        progress_prefix=name,
    )
    result = {
        "phase": name,
        "snapshot_id": snapshot_id,
        "experiment_fingerprint": fingerprint,
        "parameters": parameters,
        "summary": summary,
        "completed_at": utc_now(),
    }
    atomic_write_json(output_path, result)
    return result


def baseline_parameters() -> dict[str, Any]:
    return {
        "child_top_k": settings.RETRIEVAL_CHILD_TOP_K,
        "parent_top_k": settings.RETRIEVAL_PARENT_TOP_K,
        "rrf_k": settings.RRF_K,
        "reranker_candidates": None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 Optuna TPE 自动调优检索参数")
    parser.add_argument("--trials", type=int, help="目标总试验数，默认取 search_space.json")
    parser.add_argument("--experiment-id", help="显式实验标签；改变标签会创建隔离的新实验")
    parser.add_argument("--search-space", type=Path, help="覆盖独立 JSON 搜索空间配置")
    parser.add_argument("--dataset", type=Path, help="评测题集 JSON；默认 evaluation/test_cases.json")
    parser.add_argument("--split-dir", type=Path, help="train/validation/test 拆分目录；默认 evaluation/splits")
    parser.add_argument("--manifest", type=Path, help="拆分清单；默认 evaluation/split_manifest.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.search_space.resolve() if args.search_space else None
    search_config = load_search_config(config_path) if config_path else load_search_config()
    target_trials = args.trials if args.trials is not None else int(search_config["default_trials"])
    if target_trials < 1:
        raise ValueError("--trials 必须至少为 1")
    parent_top_k = settings.RETRIEVAL_PARENT_TOP_K
    config_child_values = values_for(search_config["search_space"]["child_top_k"])
    candidate_grid = search_config["search_space"]["reranker_candidates"]
    valid_child_values = [
        child
        for child in config_child_values
        if conditional_integer_bounds(candidate_grid, parent_top_k, child) is not None
    ]
    if not valid_child_values:
        raise ValueError("搜索空间没有满足 parent_top_k <= reranker_candidates <= child_top_k 的组合")

    dataset_path = (args.dataset or DEFAULT_DATASET_PATH).resolve()
    split_dir = (args.split_dir or SPLIT_DIR).resolve()
    manifest_path = (args.manifest or MANIFEST_PATH).resolve()

    # Importing the held-out test split is deliberately deferred to finalize_test.
    manifest, datasets = read_verified_splits(
        manifest_path=manifest_path,
        split_dir=split_dir,
        dataset_path=dataset_path,
        names=("train", "validation"),
    )
    validate_cases(datasets["train"] + datasets["validation"])
    if manifest.get("seed") != search_config.get("split_seed"):
        raise ValueError(
            f"拆分 seed={manifest.get('seed')} 与搜索配置 seed={search_config.get('split_seed')} 不同；"
            "请使用 python -m evaluation.tuning.prepare_splits 重新生成固定拆分"
        )
    configured_split_ratios = {
        name: float(value)
        for name, value in search_config.get("split_ratios", {}).items()
    }
    if manifest.get("ratios") != configured_split_ratios:
        raise ValueError("拆分比例与 search_space.json 不一致，请重新生成固定拆分")

    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError("缺少 Optuna，请在 backend 环境安装 requirements.txt 中的 optuna 依赖") from exc

    client = EvaluationClient(
        retry_count=int(search_config["retry_attempts"]),
        retry_backoff_seconds=float(search_config["retry_backoff_seconds"]),
    )
    snapshot = client.snapshot()
    formal = baseline_parameters()
    fingerprint, identity = build_experiment_identity(
        manifest,
        snapshot,
        search_config,
        formal,
        args.experiment_id,
    )
    experiment_dir = TUNING_DIR / fingerprint
    experiment_dir.mkdir(parents=True, exist_ok=True)
    experiment_path = experiment_dir / "experiment.json"
    data_sources = {
        "dataset_path": str(dataset_path),
        "split_dir": str(split_dir),
        "manifest_path": str(manifest_path),
    }
    if experiment_path.exists():
        experiment = load_json(experiment_path)
        if experiment.get("identity") != identity:
            raise ValueError("现有实验目录指纹内容与当前条件不同，停止续跑以避免复用错误 Study")
        if (experiment_dir / "test_started.json").exists() or experiment.get("status") == "testing":
            raise RuntimeError("该实验已启动测试集最终评估，不能继续搜索或调整参数")
        if experiment.get("locked"):
            raise RuntimeError(
                "该实验已完成测试集最终评估并锁定。要开始新实验，请提供新的 --experiment-id。"
            )
    else:
        experiment = {
            "schema_version": 1,
            "fingerprint": fingerprint,
            "identity": identity,
            "data_sources": data_sources,
            "created_at": utc_now(),
            "status": "preparing",
            "locked": False,
        }
    experiment.update({
        "updated_at": utc_now(),
        "target_trials": target_trials,
        "data_sources": data_sources,
    })
    atomic_write_json(experiment_path, experiment)
    (experiment_dir / "target_trials.txt").write_text(str(target_trials), encoding="utf-8")

    print(f"实验指纹：{fingerprint}")
    print(f"训练题数：{len(datasets['train'])}；验证题数：{len(datasets['validation'])}")
    print(f"评测题集：{dataset_path}")
    print(f"目标总试验数：{target_trials}；结果目录：{experiment_dir}")

    try:
        client.assert_snapshot(snapshot["snapshot_id"])
        baseline_train = evaluate_phase(
            "baseline_train", datasets["train"], formal, experiment_dir,
            snapshot["snapshot_id"], fingerprint, parent_top_k, client,
        )
        client.assert_snapshot(snapshot["snapshot_id"])
        baseline_validation = evaluate_phase(
            "baseline_validation", datasets["validation"], formal, experiment_dir,
            snapshot["snapshot_id"], fingerprint, parent_top_k, client,
        )
        client.assert_snapshot(snapshot["snapshot_id"])
    except SnapshotChangedError as exc:
        atomic_write_json(experiment_dir / "invalid.json", {"reason": str(exc), "at": utc_now()})
        experiment.update({"status": "invalid", "updated_at": utc_now()})
        atomic_write_json(experiment_path, experiment)
        raise

    baseline_validation_payload = {
        "snapshot_id": snapshot["snapshot_id"],
        "experiment_fingerprint": fingerprint,
        "summary": baseline_validation["summary"],
    }
    atomic_write_json(experiment_dir / "baseline_validation_summary.json", baseline_validation_payload)
    atomic_write_json(experiment_dir / "baseline_train_summary.json", {
        "snapshot_id": snapshot["snapshot_id"],
        "experiment_fingerprint": fingerprint,
        "summary": baseline_train["summary"],
    })

    study_path = experiment_dir / "study.db"
    storage = f"sqlite:///{study_path.as_posix()}"
    study = optuna.create_study(
        study_name=f"retrieval-{fingerprint[:16]}",
        storage=storage,
        direction="maximize",
        sampler=optuna.samplers.TPESampler(
            seed=int(search_config.get("split_seed", 42)),
            n_startup_trials=int(search_config.get("startup_trials", 10)),
        ),
        load_if_exists=True,
    )
    experiment.update({"status": "searching", "updated_at": utc_now()})
    atomic_write_json(experiment_path, experiment)
    for unfinished in list(study.get_trials(deepcopy=False)):
        if unfinished.state == optuna.trial.TrialState.RUNNING:
            study.tell(unfinished.number, state=optuna.trial.TrialState.FAIL)

    persist_trial_log(experiment_dir, study, None)
    tried = len([item for item in study.trials if item.state != optuna.trial.TrialState.RUNNING])
    remaining = max(0, target_trials - tried)
    space = search_config["search_space"]

    def objective(trial) -> float:
        started = time.perf_counter()
        trial.set_user_attr("started_at", utc_now())
        try:
            client.assert_snapshot(snapshot["snapshot_id"])
            child_top_k = trial.suggest_int(
                "child_top_k",
                valid_child_values[0],
                valid_child_values[-1],
                step=space["child_top_k"]["step"],
            )
            bounds = conditional_integer_bounds(
                space["reranker_candidates"], parent_top_k, child_top_k
            )
            if bounds is None:
                raise ValueError(f"child_top_k={child_top_k} 下不存在有效 reranker_candidates")
            low, high, step = bounds
            reranker_candidates = trial.suggest_int(
                f"reranker_candidates_child_{child_top_k}", low, high, step=step
            )
            rrf_k = trial.suggest_int(
                "rrf_k", space["rrf_k"]["low"], space["rrf_k"]["high"], step=space["rrf_k"]["step"]
            )
            parameters = {
                "child_top_k": child_top_k,
                "rrf_k": rrf_k,
                "reranker_candidates": reranker_candidates,
                "parent_top_k": parent_top_k,
            }
            trial.set_user_attr("parameters", parameters)
            result = evaluate_dataset(
                datasets["train"], parameters, parent_top_k, client,
                progress_prefix=f"Trial {trial.number + 1}/{target_trials}",
            )
            client.assert_snapshot(snapshot["snapshot_id"])
            atomic_write_json(experiment_dir / "train_results" / f"trial_{trial.number:04d}.json", result)
            duration = round(time.perf_counter() - started, 3)
            trial.set_user_attr("metrics", result["metrics"])
            trial.set_user_attr("stage_metrics", result["stage_metrics"])
            trial.set_user_attr("question_count", result["question_count"])
            trial.set_user_attr("duration_seconds", duration)
            trial.set_user_attr("finished_at", utc_now())
            return float(result["score"])
        except Exception as exc:
            trial.set_user_attr("duration_seconds", round(time.perf_counter() - started, 3))
            trial.set_user_attr("finished_at", utc_now())
            trial.set_user_attr("error", f"{type(exc).__name__}: {exc}"[:2000])
            raise

    def callback(current_study, trial) -> None:
        persist_trial_log(experiment_dir, current_study, trial)
        error = trial.user_attrs.get("error", "")
        if error.startswith("SnapshotChangedError:"):
            raise SnapshotChangedError(error)

    try:
        client.assert_snapshot(snapshot["snapshot_id"])
        if remaining:
            study.optimize(
                objective,
                n_trials=remaining,
                callbacks=[callback],
                catch=(Exception,),
                show_progress_bar=False,
            )
        else:
            print(f"Study 已有 {tried} 轮试验，达到目标总轮数 {target_trials}，不重复执行。")
        if study.trials:
            persist_trial_log(experiment_dir, study, study.trials[-1])
        client.assert_snapshot(snapshot["snapshot_id"])
    except SnapshotChangedError as exc:
        atomic_write_json(experiment_dir / "invalid.json", {"reason": str(exc), "at": utc_now()})
        experiment.update({"status": "invalid", "updated_at": utc_now()})
        atomic_write_json(experiment_path, experiment)
        raise

    completed_trials = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    best_by_config: dict[str, Any] = {}
    for trial in completed_trials:
        parameters = canonical_parameters(trial)
        key = json.dumps(parameters, sort_keys=True)
        previous = best_by_config.get(key)
        if previous is None or float(trial.value) > float(previous.value):
            best_by_config[key] = trial
    top_trials = sorted(best_by_config.values(), key=lambda item: float(item.value), reverse=True)[
        : int(search_config.get("validation_candidates", 5))
    ]
    if not top_trials:
        experiment.update({"status": "search_failed", "updated_at": utc_now()})
        atomic_write_json(experiment_path, experiment)
        raise RuntimeError("没有成功完成的训练试验，查看 trials.jsonl 中的失败原因")

    validation_path = experiment_dir / "validation_results.json"
    if validation_path.exists():
        validation_data = load_json(validation_path)
        if validation_data.get("snapshot_id") != snapshot["snapshot_id"]:
            raise ValueError("历史 validation_results.json 的检索快照不匹配")
        validation_by_config = {
            json.dumps(item.get("parameters", {}), sort_keys=True): item
            for item in validation_data.get("candidates", [])
        }
    else:
        validation_by_config = {}
    validation_candidates = []
    try:
        client.assert_snapshot(snapshot["snapshot_id"])
        for rank, trial in enumerate(top_trials, start=1):
            parameters = canonical_parameters(trial)
            parameters["parent_top_k"] = parent_top_k
            key = json.dumps(parameters, sort_keys=True)
            previous = validation_by_config.get(key)
            if previous is None:
                client.assert_snapshot(snapshot["snapshot_id"])
                print(f"验证候选 {rank}/{len(top_trials)}（训练分数 {trial.value:.4f}）")
                summary = evaluate_dataset(
                    datasets["validation"], parameters, parent_top_k, client,
                    progress_prefix=f"Validation {rank}/{len(top_trials)}",
                )
                client.assert_snapshot(snapshot["snapshot_id"])
                previous = {
                    "rank": rank,
                    "trial_number": trial.number,
                    "train_score": float(trial.value),
                    "train_metrics": trial.user_attrs.get("metrics", {}),
                    "parameters": parameters,
                    "validation": summary,
                }
                validation_by_config[key] = previous
                atomic_write_json(validation_path, {
                    "snapshot_id": snapshot["snapshot_id"],
                    "experiment_fingerprint": fingerprint,
                    "candidate_count": len(top_trials),
                    "candidates": list(validation_by_config.values()),
                    "updated_at": utc_now(),
                })
            previous["rank"] = rank
            previous["trial_number"] = trial.number
            previous["train_score"] = float(trial.value)
            previous["train_metrics"] = trial.user_attrs.get("metrics", {})
            previous["parameters"] = parameters
            validation_candidates.append(previous)
        client.assert_snapshot(snapshot["snapshot_id"])
    except SnapshotChangedError as exc:
        atomic_write_json(experiment_dir / "invalid.json", {"reason": str(exc), "at": utc_now()})
        experiment.update({"status": "invalid", "updated_at": utc_now()})
        atomic_write_json(experiment_path, experiment)
        raise

    selected = max(validation_candidates, key=lambda item: float(item["validation"]["score"]))
    best_config = {
        "experiment_fingerprint": fingerprint,
        "snapshot_id": snapshot["snapshot_id"],
        "selected_at": utc_now(),
        "selection_split": "validation",
        "training_trial_number": selected["trial_number"],
        "training_score": selected["train_score"],
        "validation_score": selected["validation"]["score"],
        "validation_metrics": selected["validation"]["metrics"],
        "parameters": selected["parameters"],
    }
    atomic_write_json(experiment_dir / "best_config.json", best_config)
    validation_report = {
        "snapshot_id": snapshot["snapshot_id"],
        "experiment_fingerprint": fingerprint,
        "candidate_count": len(validation_candidates),
        "candidates": validation_candidates,
        "selected": best_config,
        "updated_at": utc_now(),
    }
    atomic_write_json(validation_path, validation_report)
    all_trial_records = [trial_summary(item) for item in study.trials if item.state != optuna.trial.TrialState.RUNNING]
    create_report(experiment_dir / "report.svg", all_trial_records, validation_candidates)

    experiment.update({
        "status": "awaiting_test",
        "selected_config": best_config["parameters"],
        "updated_at": utc_now(),
    })
    atomic_write_json(experiment_path, experiment)
    print(f"\n验证集选出的配置：{best_config['parameters']}")
    print(f"训练综合分：{best_config['training_score']:.4f}；验证综合分：{best_config['validation_score']:.4f}")
    print(f"下一步执行：python -m evaluation.tuning.finalize_test --experiment-dir {experiment_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n收到中断；SQLite Study 和每轮 JSONL 已保留，可用相同参数续跑。", file=sys.stderr)
        raise

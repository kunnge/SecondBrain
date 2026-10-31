"""Deterministic unit checks for tuning data and metric helpers."""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from evaluation.generate_test_cases import extract_terms
from evaluation.tuning import prepare_splits

if "config.settings" not in sys.modules:
    try:
        import config.settings  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name != "dotenv":
            raise
        # The lightweight system interpreter used for pure unit checks may not
        # have backend requirements installed. Retrieval client settings are
        # mocked; these checks do not start the app or make network requests.
        mock_settings = types.ModuleType("config.settings")
        mock_settings.API_BASE_URL = "http://localhost:8000"
        mock_settings.EVALUATION_REQUEST_TIMEOUT = 1
        sys.modules["config.settings"] = mock_settings

from evaluation.tuning.runtime import EvaluationClient, EvaluationRequestError, score_response, summarize
from evaluation.tuning.space import (
    conditional_integer_bounds,
    load_search_config,
    validate_parameter_set,
    values_for,
)


class SearchSpaceTests(unittest.TestCase):
    def test_default_search_config_has_independent_steps(self) -> None:
        config = load_search_config()
        self.assertEqual(config["default_trials"], 100)
        self.assertEqual(values_for(config["search_space"]["child_top_k"]), list(range(6, 33, 2)))
        self.assertEqual(values_for(config["search_space"]["rrf_k"]), [20, 40, 60, 80, 100])
        self.assertEqual(values_for(config["search_space"]["reranker_candidates"]), list(range(4, 41, 2)))

    def test_conditional_ranges_keep_independent_steps(self) -> None:
        self.assertEqual(
            conditional_integer_bounds({"low": 4, "high": 40, "step": 2}, 4, 13),
            (4, 12, 2),
        )
        self.assertEqual(
            conditional_integer_bounds({"low": 3, "high": 11, "step": 1}, 5, 7),
            (5, 7, 1),
        )
        self.assertIsNone(conditional_integer_bounds({"low": 4, "high": 8, "step": 2}, 5, 5))

    def test_parameter_constraints(self) -> None:
        validate_parameter_set({"child_top_k": 12, "rrf_k": 60, "reranker_candidates": 8}, 4)
        with self.assertRaises(ValueError):
            validate_parameter_set({"child_top_k": 8, "rrf_k": 60, "reranker_candidates": 10}, 4)


class QuestionGenerationTests(unittest.TestCase):
    def test_generic_code_fields_are_not_used_as_question_topics(self) -> None:
        self.assertEqual(extract_terms("text content 记忆提取", limit=1), ["记忆提取"])


class MetricTests(unittest.TestCase):
    def test_macro_metrics_and_equal_weight_score(self) -> None:
        case = {
            "question_id": "q-1",
            "document_id": "doc-1",
            "relevant_parent_ids": ["p1", "p2"],
            "relevant_chunk_refs": [{"parent_id": "p1", "block_id": "b1", "chunk_index": 0}],
        }
        body = {
            "results": {
                "results": [{"id": "p2"}, {"id": "p3"}],
                "vector_results": [{"parent_id": "p1"}],
                "bm25_results": [{"parent_id": "p2"}],
                "rrf_results": [{"parent_id": "p1"}, {"parent_id": "p2"}],
                "rerank_candidates": [{"id": "p1"}, {"id": "p2"}],
                "context_chunks": [{"parent_id": "p1", "block_id": "b1", "chunk_index": 0}],
            },
        }
        result = score_response(case, body, parent_top_k=2)
        self.assertEqual(result["metrics"]["recall"], 0.5)
        self.assertEqual(result["metrics"]["precision"], 0.5)
        self.assertEqual(result["metrics"]["mrr"], 1.0)
        self.assertAlmostEqual(result["stage_metrics"]["context_chunk_recall"], 1.0)
        summary = summarize([result], {"child_top_k": 8, "parent_top_k": 2, "rrf_k": 60})
        self.assertAlmostEqual(summary["score"], sum(result["metrics"].values()) / 4)


class SplitTests(unittest.TestCase):
    def test_stale_document_id_reports_filename_mapping_without_rewriting_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chunk_dir = Path(directory)
            export = {
                "document_id": "current-doc-id",
                "filename": "notes.md",
                "parents": [],
            }
            (chunk_dir / "current-doc-id.json").write_text(json.dumps(export), encoding="utf-8")
            case = {
                "question_id": "q-stale",
                "document_id": "old-doc-id",
                "source_filename": "notes.md",
                "query": "question",
            }
            with self.assertRaisesRegex(ValueError, "current-doc-id"):
                prepare_splits.validate_case_labels([case], chunk_dir=chunk_dir)
            self.assertEqual(case["document_id"], "old-doc-id")

    def test_fixed_seed_is_deterministic_and_documents_do_not_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "cases.json"
            chunk_dir = root / "chunks"
            chunk_dir.mkdir()
            cases = [
                {
                    "question_id": f"q-{document}-{index}",
                    "document_id": f"doc-{document}",
                    "suite": "fact",
                    "query": f"question {document}-{index}",
                    "relevant_parent_ids": [f"parent-{document}"],
                    "relevant_chunk_refs": [
                        {
                            "parent_id": f"parent-{document}",
                            "block_id": f"block-{document}",
                            "chunk_index": 0,
                        }
                    ],
                }
                for document in range(10)
                for index in range(document % 3 + 1)
            ]
            dataset_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
            for document in range(10):
                export = {
                    "document_id": f"doc-{document}",
                    "parents": [
                        {
                            "parent_id": f"parent-{document}",
                            "children": [
                                {"block_id": f"block-{document}", "chunk_index": 0}
                            ],
                        }
                    ],
                }
                (chunk_dir / f"doc-{document}.json").write_text(
                    json.dumps(export), encoding="utf-8"
                )
            split_dir = root / "splits"
            manifest_path = root / "split_manifest.json"
            with (
                patch.object(prepare_splits, "CHUNK_DIR", chunk_dir),
                patch.object(prepare_splits, "SPLIT_DIR", split_dir),
                patch.object(prepare_splits, "MANIFEST_PATH", manifest_path),
            ):
                first = prepare_splits.prepare_splits(dataset_path, seed=19)
                first_assignments = {
                    document_id: split_name
                    for split_name, split in first["splits"].items()
                    for document_id in split["document_ids"]
                }
                second = prepare_splits.prepare_splits(dataset_path, seed=19)
            second_assignments = {
                document_id: split_name
                for split_name, split in second["splits"].items()
                for document_id in split["document_ids"]
            }
            self.assertEqual(first["split_hash"], second["split_hash"])
            self.assertEqual(first_assignments, second_assignments)
            self.assertEqual(len(first_assignments), 10)
            self.assertEqual(sum(item["question_count"] for item in first["splits"].values()), len(cases))


class EvaluationRequestTests(unittest.TestCase):
    def test_retries_transient_errors_but_not_client_errors(self) -> None:
        client = EvaluationClient(retry_count=2, retry_backoff_seconds=0)
        success = Mock(ok=True, status_code=200)
        success.json.return_value = {"ok": True}
        with patch("evaluation.tuning.runtime.requests.request", side_effect=[requests.ConnectionError("offline"), success]) as request:
            with patch("evaluation.tuning.runtime.time.sleep"):
                self.assertEqual(client._request_json("GET", "/snapshot"), {"ok": True})
        self.assertEqual(request.call_count, 2)

        bad_request = Mock(ok=False, status_code=422, text="invalid")
        with patch("evaluation.tuning.runtime.requests.request", return_value=bad_request) as request:
            with self.assertRaises(EvaluationRequestError):
                client._request_json("POST", "/retrieval", {})
        self.assertEqual(request.call_count, 1)

    def test_retrieval_payload_never_uses_target_document_filter(self) -> None:
        client = EvaluationClient(retry_count=0)
        captured: dict[str, object] = {}

        def fake_request(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
            captured.update(payload or {})
            return {
                "child_top_k": 8,
                "parent_top_k": 4,
                "effective_parameters": {"rrf_k": 40},
                "reranker_candidates_requested": 6,
                "reranker_candidates_actual": 5,
            }

        client._request_json = fake_request  # type: ignore[method-assign]
        client.retrieve(
            {"query": "test", "document_id": "label-only"},
            {"child_top_k": 8, "parent_top_k": 4, "rrf_k": 40, "reranker_candidates": 6},
        )
        self.assertNotIn("document_id", captured)
        self.assertEqual(captured["reranker_candidates"], 6)


if __name__ == "__main__":
    unittest.main()

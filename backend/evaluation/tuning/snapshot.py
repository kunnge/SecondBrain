"""Fingerprints the retrieval data and runtime used by evaluation requests."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sqlalchemy import text

from config import settings


BACKEND_DIR = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "config/settings.py",
    "api/evaluation.py",
    "evaluation/tuning/snapshot.py",
    "rag/retriever.py",
    "retrieval/hybrid.py",
    "retrieval/vector_search.py",
    "retrieval/bm25_search.py",
    "retrieval/rrf.py",
    "retrieval/context_expander.py",
    "retrieval/reranker.py",
    "services/embedding_service.py",
    "services/reranker_service.py",
)


def _update_hash(digest: Any, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _model_stat_signature(path_text: str) -> tuple[Any, ...]:
    path = Path(path_text)
    if not path.exists():
        return (False,)
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    return tuple(
        (item.name if path.is_file() else item.relative_to(path).as_posix(), item.stat().st_size, item.stat().st_mtime_ns)
        for item in files
    )


@lru_cache(maxsize=16)
def _model_artifact_hash(path_text: str, signature: tuple[Any, ...]) -> dict[str, Any]:
    path = Path(path_text)
    if not signature or signature == (False,):
        return {"path": path_text, "exists": False, "sha256": None}

    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    for item, (relative, _, _) in zip(files, signature):
        _update_hash(digest, relative)
        with item.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
    return {"path": path_text, "exists": True, "file_count": len(files), "sha256": digest.hexdigest(), "stat_signature": signature}


def _resolved_model_path(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (BACKEND_DIR / path).resolve()


def _bm25_record(row: Any) -> list[Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return [
        str(mapping["id"]),
        str(mapping["document_id"]),
        str(mapping["parent_id"]),
        str(mapping["block_id"] or ""),
        mapping["text"] or "",
        mapping["chunk_metadata"] or {},
        mapping["chunk_index"],
    ]


def _records_hash(records: list[list[Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item[0]):
        _update_hash(digest, record)
    return digest.hexdigest()


def _database_snapshot(engine) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    bm25_rows: list[list[Any]] = []
    with engine.connect() as connection:
        result = connection.execution_options(stream_results=True).execute(
            text(
                """
                SELECT id, document_id, parent_id, block_id, chunk_index, text,
                       chunk_metadata, embedding::text AS embedding,
                       heading_embedding::text AS heading_embedding
                FROM document_chunks
                ORDER BY id
                """
            )
        )
        for row in result.mappings():
            _update_hash(
                digest,
                [
                    str(row["id"]),
                    str(row["document_id"]),
                    str(row["parent_id"]) if row["parent_id"] is not None else None,
                    str(row["block_id"]) if row["block_id"] is not None else None,
                    row["chunk_index"],
                    row["text"] or "",
                    row["chunk_metadata"] or {},
                    row["embedding"],
                    row["heading_embedding"],
                ],
            )
            row_count += 1
            if row["parent_id"] is not None and row["text"] is not None:
                bm25_rows.append(_bm25_record(row))

        index_definitions = connection.execute(
            text(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = current_schema() AND tablename = 'document_chunks'
                ORDER BY indexname
                """
            )
        ).scalars().all()

    index_hash = hashlib.sha256()
    _update_hash(index_hash, index_definitions)
    _update_hash(digest, index_definitions)
    return {
        "data_hash": digest.hexdigest(),
        "bm25_data_hash": _records_hash(bm25_rows),
        "index_hash": index_hash.hexdigest(),
        "chunk_count": row_count,
        "bm25_row_count": len(bm25_rows),
    }


def _package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def get_retrieval_snapshot(engine, retriever, embedding_service, reranker_service) -> dict[str, Any]:
    database = _database_snapshot(engine)
    loaded_bm25_rows = [_bm25_record(row) for row in retriever.bm25_search.bm25_rows]
    loaded_bm25_hash = _records_hash(loaded_bm25_rows)

    embedding_path = _resolved_model_path(embedding_service.model_path)
    reranker_path = _resolved_model_path(reranker_service.model_path)
    code_digest = hashlib.sha256()
    missing_source_files = []
    for relative in SOURCE_FILES:
        path = BACKEND_DIR / relative
        if not path.is_file():
            missing_source_files.append(relative)
            continue
        _update_hash(code_digest, relative)
        code_digest.update(path.read_bytes())

    fixed_parameters = {
        "child_top_k": settings.RETRIEVAL_CHILD_TOP_K,
        "parent_top_k": settings.RETRIEVAL_PARENT_TOP_K,
        "rrf_k": settings.RRF_K,
        "rerank_min_parent_k": settings.RERANK_MIN_PARENT_K,
        "rerank_parent_multiplier": settings.RERANK_PARENT_MULTIPLIER,
        "context_neighbor_window": settings.CONTEXT_NEIGHBOR_WINDOW,
        "context_max_chunks_per_parent": settings.CONTEXT_MAX_CHUNKS_PER_PARENT,
        "context_max_total_chunks": settings.CONTEXT_MAX_TOTAL_CHUNKS,
        "reranker_max_length": settings.RERANKER_MAX_LENGTH,
        "reranker_batch_size": settings.RERANKER_BATCH_SIZE,
    }
    active_parameters = {
        "rrf_k": retriever.rrf_fuser.RRF_K,
        "context_neighbor_window": retriever.hybrid.context_expander.neighbor_window,
        "context_max_chunks_per_parent": retriever.hybrid.context_expander.max_chunks_per_parent,
        "context_max_total_chunks": retriever.hybrid.context_expander.max_total_chunks,
        "reranker_max_length": reranker_service.max_length,
        "reranker_batch_size": reranker_service.batch_size,
    }
    components = {
        "database": database,
        "loaded_bm25_hash": loaded_bm25_hash,
        "embedding_model": {
            "name": settings.EMBEDDING_MODEL,
            "path": str(embedding_path),
            "artifact": _model_artifact_hash(str(embedding_path), _model_stat_signature(str(embedding_path))),
        },
        "reranker_model": {
            "path": str(reranker_path),
            "artifact": _model_artifact_hash(str(reranker_path), _model_stat_signature(str(reranker_path))),
        },
        "fixed_parameters": fixed_parameters,
        "active_parameters": active_parameters,
        "code_digest": code_digest.hexdigest(),
        "app_version": settings.APP_VERSION,
        "library_versions": {
            name: _package_version(name)
            for name in (
                "sentence-transformers",
                "transformers",
                "torch",
                "numpy",
                "rank-bm25",
                "jieba",
                "pgvector",
                "SQLAlchemy",
            )
        },
    }
    snapshot_id = hashlib.sha256(
        json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "snapshot_id": snapshot_id,
        "components": components,
        "bm25_cache_matches_database": loaded_bm25_hash == database["bm25_data_hash"],
        "loaded_bm25_row_count": len(loaded_bm25_rows),
        "missing_source_files": missing_source_files,
    }

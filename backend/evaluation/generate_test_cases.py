"""从 evaluation_chunks 生成可审核、可复现的检索评测数据集。
问题使用规则模板，相关父块和子块直接来自导出数据。
运行后可人工编辑 test_cases.json 或 suites 下的文件，不依赖模型服务。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


# 定义评测数据的输入目录和输出文件路径。
BASE_DIR = Path(__file__).resolve().parent
CHUNK_DIR = BASE_DIR / "evaluation_chunks"
GENERIC_TERMS = {
    "text", "content", "value", "data", "name", "type", "id", "class", "object",
    "string", "integer", "self", "return", "true", "false", "null", "none", "key",
    "result", "results", "input", "output", "item", "items", "http", "https",
}


def clean_text(value: str) -> str:
    """合并连续空白字符并去除首尾空格。"""
    return re.sub(r"\s+", " ", value or "").strip()


def extract_terms(text: str, limit: int = 3) -> list[str]:
    """按规则提取不重复的中文词语或英文技术术语。"""
    text = clean_text(text)
    if not text:
        return []

    terms: list[str] = []
    # 匹配中文词语及英文、数字和常见技术符号组成的术语。
    for token in re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_./+#-]{1,24}", text):
        if token.casefold() not in GENERIC_TERMS and token not in terms:
            terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def child_ref(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """生成子块引用，保留关联父块和原始切分索引。"""
    return {
        "parent_id": parent["parent_id"],
        "document_id": parent["document_id"],
        "block_id": child.get("block_id"),
        "chunk_index": child.get("chunk_index", 0),
        "child_index": child.get("index"),
        "export_child_id": child.get("child_id"),
    }


def parent_heading(parent: dict[str, Any], fallback: str) -> str:
    """优先使用标题路径，缺少标题时从正文提取关键词。"""
    heading = clean_text(parent.get("heading_path", ""))
    if heading:
        return heading

    content = clean_text(parent.get("content", ""))
    terms = extract_terms(content, 2)
    return "、".join(terms) if terms else fallback


def select_target_children(parent: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """优先选择文字信息较多的子块，避免将纯图片引用当作答案标签。"""
    children = parent.get("children", [])
    ranked = sorted(
        children,
        key=lambda child: (
            bool(re.search(r"!\[[^\]]*\]\([^)]*\)|!\[\[[^\]]+\]\]", child.get("content", ""))),
            -len(re.sub(r"\s+", "", child.get("content", ""))),
            child.get("index", 0),
        ),
    )
    nonempty = [child for child in ranked if clean_text(child.get("content", ""))]
    return nonempty[:count] or children[:count]


def build_case(
    case_id: str,
    question_key: str,
    suite: str,
    query: str,
    document: dict[str, Any],
    parents: list[dict[str, Any]],
    target_children: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """构建单条评测用例，包含问题、相关块、关键词和检索参数。"""
    relevant_parent_ids = [parent["parent_id"] for parent in parents]
    refs = [child_ref(parent, child) for parent, child in target_children]

    # 从标题和正文提取关键词，并去重后最多保留 8 个。
    keywords: list[str] = []
    for parent in parents:
        keywords.extend(extract_terms(parent.get("heading_path", ""), 3))
        keywords.extend(extract_terms(parent.get("content", ""), 3))
    deduped_keywords = list(dict.fromkeys(keywords))[:8]

    question_id_source = "|".join((str(document["document_id"]), suite, question_key))
    question_id = "q-" + hashlib.sha256(question_id_source.encode("utf-8")).hexdigest()[:20]
    return {
        "id": case_id,
        "question_id": question_id,
        "suite": suite,
        "query": query,
        "document_id": document["document_id"],
        "source_filename": document.get("filename"),
        "relevant_parent_ids": relevant_parent_ids,
        "relevant_chunk_refs": refs,
        "expected_keywords": deduped_keywords,
    }


def generate_document_cases(document: dict[str, Any], number: int) -> dict[str, list[dict[str, Any]]]:
    """为单份文档生成事实、章节定位和综合分析三类评测用例。"""
    parents = document.get("parents", [])
    if not parents:
        return {"fact": [], "heading": [], "synthesis": []}

    title = Path(document.get("filename", f"document-{number}")).stem

    # 选取首个、中间和最后一个父块，构造不同类型的问题。
    first = parents[0]
    middle = parents[len(parents) // 2]
    last = parents[-1]
    first_heading = parent_heading(first, "相关内容")
    middle_heading = parent_heading(middle, "相关内容")
    last_heading = parent_heading(last, "相关内容")
    first_children = select_target_children(first, 2)
    middle_children = select_target_children(middle, 2)
    last_children = select_target_children(last, 1)
    first_term = (extract_terms(first_children[0].get("content", "") if first_children else first.get("content", ""), 1) or [first_heading])[0]
    second_term = (extract_terms(first_children[1].get("content", "") if len(first_children) > 1 else first_term, 1) or [first_term])[0]
    middle_term = (extract_terms(middle_children[0].get("content", "") if middle_children else middle.get("content", ""), 1) or [middle_heading])[0]
    position_term = (extract_terms(middle_children[1].get("content", "") if len(middle_children) > 1 else middle_term, 1) or [middle_term])[0]
    prefix = f"doc{number:02d}"

    def hide_title(value: str) -> str:
        return re.sub(re.escape(title), "相关内容", value, flags=re.IGNORECASE) if title else value

    first_term, second_term = hide_title(first_term), hide_title(second_term)
    middle_term, position_term = hide_title(middle_term), hide_title(position_term)
    middle_heading, last_heading = hide_title(middle_heading), hide_title(last_heading)
    last_term = hide_title(
        (extract_terms(last_children[0].get("content", ""), 1) or [last_heading])[0]
        if last_children else last_heading
    )

    return {
        "fact": [
            build_case(
                f"{prefix}_fact", "fact", "fact",
                f"关于“{first_term}”的内容主要说明了什么？请概括关键结论。",
                document, [first], [(first, first_children[0])] if first_children else [],
            ),
            build_case(
                f"{prefix}_detail", "detail", "fact",
                f"提到的“{second_term}”具体指什么？请说明它的作用或要点。",
                document, [first], [(first, first_children[1] if len(first_children) > 1 else first_children[0])] if first_children else [],
            ),
        ],
        "heading": [
            build_case(
                f"{prefix}_heading", "heading", "heading",
                f"在“{middle_heading}”部分，关于“{middle_term}”记录了哪些要点？",
                document, [middle], [(middle, middle_children[0])] if middle_children else [],
            ),
            build_case(
                f"{prefix}_position", "position", "heading",
                f"提到的“{position_term}”主要位于哪个章节或内容块？该处主要说明什么？",
                document, [middle], [(middle, middle_children[1] if len(middle_children) > 1 else middle_children[0])] if middle_children else [],
            ),
        ],
        "synthesis": [
            build_case(
                f"{prefix}_synthesis", "synthesis", "synthesis",
                f"请结合“{first_term}”与“{last_term}”相关内容，概括主题和处理思路。",
                document,
                [first, last] if first["parent_id"] != last["parent_id"] else [first],
                ([(first, first_children[0])] if first_children else []) + ([(last, last_children[0])] if last_children and last["parent_id"] != first["parent_id"] else []),
            ),
        ],
    }


def main() -> None:
    """读取切分数据，生成分组用例、完整数据集和数据清单。"""
    parser = argparse.ArgumentParser(description="从 evaluation_chunks 生成检索评测题集")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "generated_review",
        help="输出目录；默认写入 generated_review，保留现有 test_cases.json 和 suites",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    suite_dir = output_dir / "suites"

    documents = []
    # 按文件名排序，确保每次生成的用例编号保持稳定。
    for path in sorted(CHUNK_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            documents.append(json.load(file))

    if not documents:
        raise RuntimeError(f"没有找到 evaluation_chunks 文件：{CHUNK_DIR}")
    document_ids = [str(document.get("document_id") or "") for document in documents]
    if not all(document_ids) or len(set(document_ids)) != len(document_ids):
        raise RuntimeError("evaluation_chunks 中的 document_id 缺失或重复")

    suites: dict[str, list[dict[str, Any]]] = {"fact": [], "heading": [], "synthesis": []}
    for index, document in enumerate(documents, start=1):
        generated = generate_document_cases(document, index)
        for suite, cases in generated.items():
            suites[suite].extend(cases)

    # 合并所有用例并排序，方便审核、版本管理和重复运行对比。
    all_cases = suites["fact"] + suites["heading"] + suites["synthesis"]
    all_cases.sort(key=lambda item: item["question_id"])
    suite_dir.mkdir(parents=True, exist_ok=True)

    # 分别输出分类数据集和完整数据集。
    for suite, cases in suites.items():
        with (suite_dir / f"{suite}.json").open("w", encoding="utf-8") as file:
            json.dump(cases, file, ensure_ascii=False, indent=2)
    with (output_dir / "test_cases.json").open("w", encoding="utf-8") as file:
        json.dump(all_cases, file, ensure_ascii=False, indent=2)

    # 记录数据集规模及各文档的切分数量，便于追踪评测数据来源。
    manifest = {
        "document_count": len(documents),
        "case_count": len(all_cases),
        "suite_counts": {name: len(cases) for name, cases in suites.items()},
        "data_hash": hashlib.sha256(
            json.dumps(all_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "documents": [
            {
                "document_id": doc["document_id"],
                "filename": doc.get("filename"),
                "parent_count": doc.get("parent_count"),
                "child_count": doc.get("child_count"),
            }
            for doc in documents
        ],
    }
    manifest["output_dir"] = str(output_dir)
    with (output_dir / "test_cases_manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)

    # 打印清单，方便确认本次生成结果。
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

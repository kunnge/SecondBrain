"""分析导出的 Parent/Child 切分质量并生成 JSON、CSV 报告。"""

from __future__ import annotations

import json
import argparse
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

# 定义切分数据输入目录和质量报告输出目录。
BASE_DIR = Path(__file__).resolve().parent
CHUNK_DIR = BASE_DIR / "evaluation_chunks"
OUTPUT_DIR = BASE_DIR / "results" / "chunk_quality"

def plot_quality_reports(
    reports: list[dict[str, Any]], report: dict[str, Any], output_dir: Path
) -> None:
    """生成 Parent/Child 数量、长度和异常项图表。"""
    if not reports:
        return
    # 汇总各文档的块数量、平均长度和切分异常数量。
    labels = [Path(item["filename"]).stem[:24] for item in reports]
    positions = list(range(len(labels)))
    parent_counts = [item["parent_count"] for item in reports]
    child_counts = [item["child_count"] for item in reports]
    parent_means = [item["parent_length"]["mean"] for item in reports]
    child_means = [item["child_length"]["mean"] for item in reports]
    issue_labels = ["Empty parent", "Empty child", "Duplicate child", "Parent without child", "Missing heading"]
    issue_values = [
        sum(item["empty_parent_count"] for item in reports),
        sum(item["empty_child_count"] for item in reports),
        sum(item["duplicate_child_text_count"] for item in reports),
        sum(item["parent_without_children_count"] for item in reports),
        sum(item["missing_heading_count"] for item in reports),
    ]

    # 即使未安装 matplotlib，也先生成可直接查看的 SVG 图表。
    def svg_bar_chart(
        filename: str,
        title: str,
        categories: list[str],
        series: list[tuple[str, list[float], str]],
        value_suffix: str = "",
        rotate_labels: bool = False,
    ) -> None:
        # 根据类别数量计算坐标、柱宽和数值缩放比例。
        width, height = 1200, 650
        left, right, top, bottom = 72, 30, 72, 150 if rotate_labels else 90
        plot_width, plot_height = width - left - right, height - top - bottom
        maximum = max((value for _, values, _ in series for value in values), default=0)
        scale_max = max(1.0, maximum * 1.18)
        group_width = plot_width / max(1, len(categories))
        bar_width = min(34.0, group_width * 0.72 / max(1, len(series)))
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#263238}.axis{stroke:#8b949e;stroke-width:1}.grid{stroke:#e5e7eb;stroke-width:1}.value{font-size:13px;font-weight:bold}.label{font-size:12px}.title{font-size:21px;font-weight:bold}</style>',
            f'<text class="title" x="{width / 2}" y="35" text-anchor="middle">{title}</text>',
        ]
        # 绘制水平网格线和纵轴刻度。
        for tick in range(6):
            value = scale_max * tick / 5
            y = top + plot_height * (1 - tick / 5)
            svg.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}"/>')
            svg.append(f'<text class="label" x="{left-10}" y="{y+4:.1f}" text-anchor="end">{value:.0f}</text>')
        svg.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_height}"/>')
        svg.append(f'<line class="axis" x1="{left}" y1="{top+plot_height}" x2="{width-right}" y2="{top+plot_height}"/>')
        colors = [entry[2] for entry in series]
        # 按类别和系列绘制柱形、数值标签及横轴标签。
        for category_index, category in enumerate(categories):
            center = left + group_width * (category_index + 0.5)
            total_width = bar_width * len(series)
            for series_index, (series_name, values, color) in enumerate(series):
                value = values[category_index] if category_index < len(values) else 0
                bar_height = plot_height * value / scale_max
                x = center - total_width / 2 + series_index * bar_width
                y = top + plot_height - bar_height
                svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width-3:.1f}" height="{bar_height:.1f}" fill="{color}"/>')
                value_text = f"{value:.1f}{value_suffix}" if isinstance(value, float) and not value.is_integer() else f"{int(value)}{value_suffix}"
                svg.append(f'<text class="value" x="{x+(bar_width-3)/2:.1f}" y="{max(top+14,y-6):.1f}" text-anchor="middle">{value_text}</text>')
            label_y = top + plot_height + 22
            if rotate_labels:
                svg.append(f'<text class="label" transform="translate({center:.1f},{label_y}) rotate(35)" text-anchor="start">{category}</text>')
            else:
                svg.append(f'<text class="label" x="{center:.1f}" y="{label_y}" text-anchor="middle">{category}</text>')
        legend_y = height - 24
        legend_total = len(series) * 190
        legend_start = (width - legend_total) / 2
        for index, (series_name, _, color) in enumerate(series):
            x = legend_start + index * 190
            svg.append(f'<rect x="{x:.1f}" y="{legend_y-12}" width="13" height="13" fill="{color}"/>')
            svg.append(f'<text class="label" x="{x+20:.1f}" y="{legend_y}">{series_name}</text>')
        svg.append('</svg>')
        (output_dir / filename).write_text("\n".join(svg), encoding="utf-8")

    svg_bar_chart(
        "chunk_counts.svg", "Chunk counts by document", labels,
        [("Parent", parent_counts, "#4776a8"), ("Child", child_counts, "#52a788")],
        rotate_labels=True,
    )
    svg_bar_chart(
        "chunk_lengths.svg", "Average Parent and Child length by document", labels,
        [("Parent mean chars", parent_means, "#d6a448"), ("Child mean chars", child_means, "#bc6c8a")],
        rotate_labels=True,
    )
    svg_bar_chart(
        "chunk_issues.svg", "Chunk quality issues", issue_labels,
        [("Issue count", issue_values, "#c95c5c")],
    )

    # matplotlib 可选；缺少依赖时保留 SVG 报告并跳过 PNG。
    if plt is None:
        return

    plt.figure(figsize=(12, 6))
    width = 0.38
    parent_bars = plt.bar([p - width / 2 for p in positions], parent_counts, width, label="Parent", color="#4776a8")
    child_bars = plt.bar([p + width / 2 for p in positions], child_counts, width, label="Child", color="#52a788")
    for bars in (parent_bars, child_bars):
        for bar in bars:
            plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=8)
    plt.xticks(positions, labels, rotation=45, ha="right")
    plt.ylabel("Block count")
    plt.title(f"Chunk counts by document | documents={report['document_count']}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "chunk_counts.png", dpi=150)
    plt.close()

    plt.figure(figsize=(10, 6))
    width = 0.38
    parent_bars = plt.bar([p - width / 2 for p in positions], parent_means, width, label="Parent mean chars", color="#d6a448")
    child_bars = plt.bar([p + width / 2 for p in positions], child_means, width, label="Child mean chars", color="#bc6c8a")
    for bars in (parent_bars, child_bars):
        for bar in bars:
            plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=8)
    plt.xticks(positions, labels, rotation=45, ha="right")
    plt.ylabel("Characters")
    plt.title("Average Parent and Child length by document")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "chunk_lengths.png", dpi=150)
    plt.close()

    plt.figure(figsize=(10, 6))
    bars = plt.bar(issue_labels, issue_values, color=["#c95c5c", "#d98c4a", "#bc6c8a", "#7a8f5a", "#6d83b5"])
    for bar, value in zip(bars, issue_values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, str(value), ha="center", va="bottom", fontsize=9)
    plt.ylabel("Count")
    plt.title("Chunk quality issues")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(output_dir / "chunk_issues.png", dpi=150)
    plt.close()

def percentile(values: list[int], fraction: float) -> float:
    """按排序后的近似索引计算指定分位数。"""
    if not values:
        return 0.0
    # 使用最近整数索引取得对应分位数值。
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return float(ordered[index])

def analyze_document(data: dict[str, Any], filename: str) -> dict[str, Any]:
    """统计单份文档的切分数量、长度分布和质量异常。"""
    parents = data.get("parents", [])
    parent_lengths = [len(parent.get("content") or "") for parent in parents]
    # 将所有父块下的子块展平，便于统一统计。
    child_records = [
        (parent, child)
        for parent in parents
        for child in parent.get("children", [])
    ]
    child_lengths = [len(child.get("content") or "") for _, child in child_records]
    child_texts = [" ".join((child.get("content") or "").split()) for _, child in child_records]
    # 对空白格式归一化后的子块文本计数，识别重复内容。
    duplicate_counts = Counter(text for text in child_texts if text)
    empty_parents = [parent for parent in parents if not (parent.get("content") or "").strip()]
    empty_children = [
        {"parent_id": parent.get("parent_id"), "child_id": child.get("child_id"), "child_index": child.get("index")}
        for parent, child in child_records
        if not (child.get("content") or "").strip()
    ]
    missing_headings = [parent.get("parent_id") for parent in parents if not (parent.get("heading_path") or "").strip()]
    no_children = [parent.get("parent_id") for parent in parents if not parent.get("children")]
    block_types = Counter(child.get("block_type") or "unknown" for _, child in child_records)
    # 收集过长父块、过短子块及重复子块的示例，方便人工检查。
    long_parents = [
        {"parent_id": parent.get("parent_id"), "length": len(parent.get("content") or ""), "heading_path": parent.get("heading_path", "")}
        for parent in parents
        if len(parent.get("content") or "") > 2400
    ]
    tiny_children = [
        {"parent_id": parent.get("parent_id"), "child_id": child.get("child_id"), "length": len(child.get("content") or ""), "heading_path": parent.get("heading_path", "")}
        for parent, child in child_records
        if 0 < len(child.get("content") or "") < 40
    ]
    repeated_children = [
        {"text_preview": text[:100], "count": count}
        for text, count in duplicate_counts.most_common()
        if count > 1
    ]

    def length_stats(values: list[int]) -> dict[str, float | int]:
        """计算数量、最小值、P50、均值、P90 和最大值。"""
        return {
            "count": len(values),
            "min": min(values, default=0),
            "p50": percentile(values, 0.5),
            "mean": round(statistics.mean(values), 2) if values else 0,
            "p90": percentile(values, 0.9),
            "max": max(values, default=0),
        }

    return {
        "document_id": data.get("document_id"),
        "filename": data.get("filename") or filename,
        "parent_count": len(parents),
        "child_count": len(child_records),
        "heading_coverage": round((len(parents) - len(missing_headings)) / len(parents), 4) if parents else 0,
        "missing_heading_count": len(missing_headings),
        "parent_length": length_stats(parent_lengths),
        "child_length": length_stats(child_lengths),
        "long_parent_count": len(long_parents),
        "tiny_child_count": len(tiny_children),
        "block_types": dict(block_types),
        "empty_parent_count": len(empty_parents),
        "empty_child_count": len(empty_children),
        "duplicate_child_text_count": sum(count - 1 for count in duplicate_counts.values() if count > 1),
        "parent_without_children_count": len(no_children),
        "missing_heading_parent_ids": missing_headings[:20],
        "parent_without_children_ids": no_children[:20],
        "empty_examples": {"parents": [parent.get("parent_id") for parent in empty_parents[:10]], "children": empty_children[:10]},
        "duplicate_examples": repeated_children[:10],
        "long_parent_examples": long_parents[:10],
        "tiny_child_examples": tiny_children[:10],
    }

def main() -> None:
    """遍历切分导出文件，输出 JSON、CSV 和图表报告。"""
    parser = argparse.ArgumentParser(description="分析 evaluation_chunks 的切分质量")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="报告输出目录；默认 evaluation/results/chunk_quality",
    )
    output_dir = parser.parse_args().output_dir.resolve()

    # 每个 evaluation_chunks JSON 文件对应一份文档质量报告。
    reports = []
    for path in sorted(CHUNK_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            reports.append(analyze_document(json.load(file), path.name))

    # 汇总所有文档的块数量和标题覆盖率。
    parent_count = sum(report["parent_count"] for report in reports)
    child_count = sum(report["child_count"] for report in reports)
    total_missing_headings = sum(report["missing_heading_count"] for report in reports)
    report = {
        "document_count": len(reports),
        "parent_count": parent_count,
        "child_count": child_count,
        "heading_coverage": round((parent_count - total_missing_headings) / parent_count, 4) if parent_count else 0,
        "documents": reports,
    }
    # 创建输出目录并写入完整 JSON 报告。
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "chunk_quality.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    with (output_dir / "chunk_quality.csv").open("w", encoding="utf-8-sig", newline="") as file:
        import csv

        # CSV 保留常用汇总指标，方便用 Excel 筛选和比较文档。
        fields = ["filename", "document_id", "parent_count", "child_count", "heading_coverage", "parent_length_mean", "parent_length_p90", "parent_length_max", "child_length_mean", "child_length_p90", "child_length_max", "long_parent_count", "tiny_child_count", "empty_parent_count", "empty_child_count", "duplicate_child_text_count", "parent_without_children_count"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in reports:
            writer.writerow({
                "filename": item["filename"],
                "document_id": item["document_id"],
                "parent_count": item["parent_count"],
                "child_count": item["child_count"],
                "heading_coverage": item["heading_coverage"],
                "parent_length_mean": item["parent_length"]["mean"],
                "parent_length_p90": item["parent_length"]["p90"],
                "parent_length_max": item["parent_length"]["max"],
                "child_length_mean": item["child_length"]["mean"],
                "child_length_p90": item["child_length"]["p90"],
                "child_length_max": item["child_length"]["max"],
                "long_parent_count": item["long_parent_count"],
                "tiny_child_count": item["tiny_child_count"],
                "empty_parent_count": item["empty_parent_count"],
                "empty_child_count": item["empty_child_count"],
                "duplicate_child_text_count": item["duplicate_child_text_count"],
                "parent_without_children_count": item["parent_without_children_count"],
            })
    # 同时生成图表，并在控制台输出本次统计摘要。
    plot_quality_reports(reports, report, output_dir)
    print(f"切分质量报告已生成：{output_dir}")
    print(f"文档 {len(reports)} 份，Parent {parent_count} 个，Child {child_count} 个，标题覆盖率 {report['heading_coverage']:.1%}")

if __name__ == "__main__":
    main()

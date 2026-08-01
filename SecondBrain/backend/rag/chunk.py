from typing import List, Dict, Any, Tuple
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

# 导入 marko 相关库，用于解析 Markdown 抽象语法树（AST）
from marko.ext.gfm import gfm
from marko.block import Heading, Paragraph, FencedCode, List as ListBlock
from marko.ext.gfm.elements import Table

# 导入 LangChain 相关组件
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document  # LangChain 的标准文档类

import uuid
# ==========================================
# 数据结构定义：实现 Parent-Child 关联机制
# ==========================================
class ParentChunk:
    """
    【步骤 1-1】定义父块：存储较大的文本块，包含完整的上下文逻辑。
    用于在检索命中时，最终丢给大模型阅读的内容。
    """
    def __init__(self, text: str, node_type: str, metadata: dict):
        self.parent_id = f"p_{uuid.uuid4().hex[:8]}" # 生成唯一父节点 ID
        self.text = text                             # 完整的段落/代码/表格内容
        self.node_type = node_type                   # 节点类型标识
        self.metadata = metadata                     # 包含层级标题等元数据


class ChildChunk:
    """
    【步骤 1-2】定义子块：从父块中继续切分出来的小文本块。
    用于进行 Embedding 向量化，因为文本短，语义更集中，检索更精准。
    """
    def __init__(self, text: str, parent_id: str, metadata: dict):
        self.child_id = f"c_{uuid.uuid4().hex[:8]}"
        self.parent_id = parent_id                   # 核心！绑定对应的父块 ID
        self.text = text
        self.metadata = metadata


# ==========================================
# 核心切分器：基于 AST 的智能文档处理
# ==========================================
class AdvancedRAGSplitter:
    """
    高级 RAG 文档切分器。
    与传统暴力切分不同，该切分器利用 AST（抽象语法树）解析 Markdown 文档的结构，
    能够智能识别标题、表格、代码、列表和段落，从而在切分时保护语义完整性，
    防止表格断裂或代码块执行失败。
    """

    def __init__(self, parent_chunk_size=1000, child_chunk_size=300, child_overlap=30):
        # 1. 初始化 Markdown 解析器。这里使用 gfm (GitHub Flavored Markdown) 以支持表格解析
        self.markdown_parser = gfm

        # 2. 初始化用于处理【长段落】的切分器
        # 父块通常较大，提供完整的上下文供 LLM 阅读
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_chunk_size,
            chunk_overlap=0,  # 父块之间不需要重叠，因为有层级标题串联
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

        # 3. 初始化用于处理【子块】的切分器（注：当前代码片段未直接使用，通常在生成 ChildChunk 时调用）
        # 子块较小，用于向量化和高精度检索
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_overlap,  # 子块需要重叠，防止关键句子在交界处被切断
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

        # 4. 全局状态机
        # header_stack 用于记录当前解析所处的“章节路径”（如 H1 -> H2）
        self.header_stack = {}
        # parent_chunks 用于暂存当前文档切分出来的所有父块
        self.parent_chunks: List[ParentChunk] = []

    def _get_current_metadata(self) -> dict:
        """
        获取当前解析位置的层级上下文。
        例如，如果当前解析到了某段落，而这个段落属于 "# 数据库" 下的 "## 索引"，
        则返回 {'H1': '数据库', 'H2': '索引'}。这能极大缓解大模型的“上下文丢失”问题。
        """
        return {f"H{level}": title for level, title in self.header_stack.items()}

    def _extract_raw_text(self, node) -> str:
        """
        递归提取 AST 节点的纯文本。
        Markdown 的节点可能包含嵌套（如段落中嵌套了加粗、链接），
        此方法不断向下遍历，将内部的所有纯文本拼接到一起。
        """
        if hasattr(node, 'children') and isinstance(node.children, list):
            return "".join([self._extract_raw_text(child) for child in node.children])
        elif hasattr(node, 'children') and isinstance(node.children, str):
            return node.children
        return ""

    # ================= 第1步 & 第2步：AST 解析与类型路由 =================
    def process_documents(self, documents: List[Document]) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        """
        主处理入口：接收 LangChain 的 Document 列表，输出切分好的 ParentChunk 列表。
        """
        all_parent_chunks = []

        # 遍历传入的每个文档
        for doc in documents:
            # 1. 提取文档内容和原始元数据（例如来源路径、作者等信息）
            markdown_text = doc.page_content
            base_metadata = doc.metadata.copy() if doc.metadata else {}

            # 2. 将整个 Markdown 字符串解析成 AST（树状结构对象）
            ast = self.markdown_parser.parse(markdown_text)

            # 3. 【关键】处理新文档前，必须清空上一篇文档的解析状态，防止数据污染
            self.header_stack = {}
            self.parent_chunks = []

            # 4. 遍历 Markdown 树的第一层节点
            for node in ast.children:
                # 融合原始 Document 元数据与当前解析出的 Markdown 层级元数据
                current_metadata = {**base_metadata, **self._get_current_metadata()}

                # --- 路由分发 ---

                # 路由 1：如果遇到标题节点
                if isinstance(node, Heading):
                    level = node.level
                    title = self._extract_raw_text(node).strip()
                    # 将当前标题推入栈中
                    self.header_stack[level] = title
                    # 状态维护：清空比当前层级更深的记录（例如进入新的 H2，就清空旧的 H3、H4）
                    self.header_stack = {k: v for k, v in self.header_stack.items() if k <= level}

                # 路由 2：如果遇到表格节点
                elif isinstance(node, Table):
                    self._split_table(node, current_metadata)

                # 路由 3：如果遇到代码块节点
                elif isinstance(node, FencedCode):
                    self._split_code(node, current_metadata)

                # 路由 4：如果遇到列表节点
                elif isinstance(node, ListBlock):
                    self._split_list(node, current_metadata)

                # 路由 5：如果遇到普通段落节点
                elif isinstance(node, Paragraph):
                    self._split_paragraph(node, current_metadata)

            # 5. 将当前文档解析得到的所有 chunk 追加到总列表中
            all_parent_chunks.extend(self.parent_chunks)

            # 6. 执行"引导语向下合并"逻辑
        optimized_chunks = self._post_merge_chunks(all_parent_chunks)

        # 7. 从父块中切出子块：子块更短、语义更集中，用于向量化与高精度检索
        child_chunks = self._generate_child_chunks(optimized_chunks)

        return optimized_chunks, child_chunks

    def _generate_child_chunks(self, parent_chunks: List[ParentChunk]) -> List[ChildChunk]:
        """
        从父块中切分出子块。
        子块文本更短、语义更集中，用于向量化与高精度检索；
        父块保留完整上下文，供检索命中后回溯原文给大模型阅读。
        """
        child_chunks = []
        for parent in parent_chunks:
            for child_text in self.child_splitter.split_text(parent.text):
                child_chunks.append(ChildChunk(child_text, parent.parent_id, parent.metadata))
        return child_chunks

    # ================= 专属节点切分逻辑 =================


    def _row_to_md(self, row_node) -> str:
        """
        辅助方法：将一行 AST 节点转换为标准的 Markdown 表格行格式：| col1 | col2 |
        """
        # 提取当前行中每个单元格的文本
        # strip() 去除首尾空格，replace('\n', ' ') 防止单元格内的换行破坏 Markdown 表格结构
        cells = [self._extract_raw_text(cell).strip().replace('\n', ' ') for cell in row_node.children]

        # 拼接成 Markdown 格式
        return "| " + " | ".join(cells) + " |"

    def _split_table(self, node: Table, metadata: dict, chunk_size=20):
        """
        表格专用切分：如果表格太长，强行切断会导致后面的数据失去表头定义。
        此方法会在切断后，强制为每一小块数据拼上原来的表头并恢复 Markdown 格式（20行切分）。
        """
        # 容错处理：确保表格至少有内容
        if not node.children:
            return

        # marko 解析 Table 时，children 默认直接就是 TableRow 的列表
        # 第 0 个子节点是表头行，后续的是数据行
        header_row_node = node.children[0]
        data_row_nodes = node.children[1:]

        # 1. 组装表头 (例如：| 速度 | 文件格式 | 原因 |)
        header_md = self._row_to_md(header_row_node)

        # 2. 动态生成 Markdown 表格的分隔线 (例如：|---|---|---|)
        num_cols = len(header_row_node.children)
        separator_md = "| " + " | ".join(["---"] * num_cols) + " |"

        # 3. 提取并组装所有数据行
        data_rows = [self._row_to_md(row) for row in data_row_nodes]

        # 4. 按 chunk_size（如每 20 行）分批切断表格
        for i in range(0, len(data_rows), chunk_size):
            batch_rows = data_rows[i: i + chunk_size]

            # 【核心逻辑】组装标准 Markdown 表格：表头 + 分隔线 + 当前批次的数据行
            table_text = f"{header_md}\n{separator_md}\n" + "\n".join(batch_rows)

            chunk_metadata = metadata.copy()
            chunk_metadata['node_type'] = 'table'  # 标记为表格块
            self.parent_chunks.append(ParentChunk(table_text, 'table', chunk_metadata))

    def _split_code(self, node: FencedCode, metadata: dict, max_code_length=2000):
        """
        代码块专用切分：优先保护代码整体性，超长代码再动态识别多语言结构进行切分。
        """
        # 1. 提取并标准化语言类型与代码内容
        raw_lang = (node.lang or "text").lower()
        code_text = node.children[0].children if node.children else ""

        # 准备专门针对该代码块的元数据
        chunk_metadata = metadata.copy()
        chunk_metadata.update({'node_type': 'code', 'language': raw_lang})

        # ==========================================
        # 优化点 1：代码块整体性绝对保护机制
        # 适当放宽代码块的长度容忍度。只要低于设定的最大安全阈值（如2000字符），
        # 即使超过了常规的 1000 chunk_size，也绝对不切分，直接整体保留！
        # ==========================================
        if len(code_text) <= max_code_length:
            protected_code = f"```{raw_lang}\n{code_text.strip()}\n```"
            self.parent_chunks.append(ParentChunk(protected_code, 'code', chunk_metadata))
            return

        # 2. 建立语言映射表
        lang_mapping = {
            "python": Language.PYTHON, "py": Language.PYTHON,
            "java": Language.JAVA,
            "cpp": Language.CPP, "c++": Language.CPP, "c": Language.CPP,
            "go": Language.GO,
            "js": Language.JS, "javascript": Language.JS,
            "ts": Language.TS, "typescript": Language.TS,
            "rust": Language.RUST, "rs": Language.RUST,
            "php": Language.PHP,
            "ruby": Language.RUBY, "rb": Language.RUBY,
            "html": Language.HTML,
            "markdown": Language.MARKDOWN, "md": Language.MARKDOWN,
        }

        # 3. 针对“超巨型”代码的降级智能切分
        if raw_lang in lang_mapping:
            code_splitter = RecursiveCharacterTextSplitter.from_language(
                language=lang_mapping[raw_lang],
                chunk_size=1200,
                chunk_overlap=100  # 优化点 2：增加重叠度，防止函数/类定义在交界处断裂
            )
        else:
            code_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1200,
                chunk_overlap=100,
                # 优化点 3：去掉 " " 和 ""，禁止在没有换行符的超长字符串（如Cookie、Base64）中间强行斩断
                separators=["\n\n", "\n"]
            )

        # 4. 执行切分
        splits = code_splitter.split_text(code_text)

        # 5. 组装返回，补齐 Markdown 代码包裹符号
        for split in splits:
            protected_code = f"```{raw_lang}\n{split.strip()}\n```"
            self.parent_chunks.append(ParentChunk(protected_code, 'code', chunk_metadata))

    def _split_paragraph(self, node: Paragraph, metadata: dict):
        """普通段落切分：使用通用切分器按标点符号等进行降级切断。"""
        text = self._extract_raw_text(node)
        splits = self.text_splitter.split_text(text)

        for split in splits:
            chunk_metadata = metadata.copy()
            chunk_metadata['node_type'] = 'paragraph'
            self.parent_chunks.append(ParentChunk(split, 'paragraph', chunk_metadata))

    def _split_list(self, node: ListBlock, metadata: dict):
        """
        列表专用切分：列表太长时，避免长句子从中间断裂。
        优先在列表符号（如 - , *, 1. ）处进行切断。
        """
        text = self._extract_raw_text(node)
        # 针对列表定制的分隔符
        list_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=50,
            separators=["\n- ", "\n* ", "\n1. ", "\n\n", "\n"]
        )
        splits = list_splitter.split_text(text)

        for split in splits:
            chunk_metadata = metadata.copy()
            chunk_metadata['node_type'] = 'list'
            self.parent_chunks.append(ParentChunk(split, 'list', chunk_metadata))

    def _post_merge_chunks(self, chunks: List[ParentChunk], merge_threshold: int = 100) -> List[ParentChunk]:
        """
        后处理：将过短的“引导性段落”向下合并到相邻的代码块或表格块中，防止语义断裂。
        :param chunks: 切分好的 ParentChunk 列表
        :param merge_threshold: 触发合并的字符数阈值，默认为 100
        """
        # 初始化合并后的块列表，用于存放最终处理完的文本块
        merged_chunks = []

        # 遍历输入的每一个文本块
        for chunk in chunks:
            # 如果当前是第一个块，直接放入结果列表中，进入下一次循环
            if not merged_chunks:
                merged_chunks.append(chunk)
                continue

            # 获取结果列表中上一个已经处理的块，作为潜在的被合并对象
            prev_chunk = merged_chunks[-1]

            # 【核心逻辑】：如果上一个块是“普通段落”或“列表”，并且其文本长度小于设定的阈值（merge_threshold）
            if prev_chunk.node_type in ['paragraph', 'list'] and len(prev_chunk.text) < merge_threshold:
                # 将上一个短段落的文本，强行拼接到当前块（如代码块、表格等）的上方
                chunk.text = f"{prev_chunk.text}\n\n{chunk.text}"

                # 用拼接后的当前块替换掉结果列表中的上一个短段落（相当于把短段落“吞并”到当前块中）
                merged_chunks[-1] = chunk
                continue

            # 如果不满足合并条件，则直接将当前块追加到结果列表中
            merged_chunks.append(chunk)

        # 返回处理完成的文本块列表
        return merged_chunks
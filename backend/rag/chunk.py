from typing import List, Dict, Tuple
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from marko.ext.gfm import gfm
from marko.block import Heading, Paragraph, FencedCode, List as ListBlock
from marko.ext.gfm.elements import Table
import uuid
from config.settings import CHILD_CHUNK_OVERLAP, CHILD_CHUNK_SIZE, PARENT_CHUNK_SIZE

class ParentChunk:
    def __init__(self,blocks: List[Tuple[str, str]],metadata: dict):
        self.parent_id = f"p_{uuid.uuid4().hex[:8]}"
        self.blocks = blocks
        self.metadata = metadata
        # 父块完整的文本
        self.text="\n\n".join( block for _,block in blocks)
class ChildChunk:
    def __init__( self, text: str, parent_id: str, block_id:str | None, block_type, chunk_index:int, metadata: dict ):
        self.child_id = f"c_{uuid.uuid4().hex[:8]}"
        self.parent_id = parent_id
        self.block_id=block_id
        self.block_type=block_type
        self.chunk_index=chunk_index
        self.text = text
        self.metadata = metadata

class AdvancedRAGSplitter:
    def __init__( self, parent_chunk_size=PARENT_CHUNK_SIZE, child_chunk_size=CHILD_CHUNK_SIZE, child_overlap=CHILD_CHUNK_OVERLAP ):
        self.markdown_parser = gfm
        self.parent_chunk_size = parent_chunk_size
        self.child_chunk_size = child_chunk_size
        self.child_overlap = child_overlap
        # Child 切分器
        self.child_splitter = RecursiveCharacterTextSplitter( chunk_size=child_chunk_size, chunk_overlap=child_overlap,  separators=[ "\n\n", "\n", "。", "！", "？",  " ",  "" ] )
        # 当前标题层级
        self.header_stack: Dict[int, str] = {}
        # 当前文档的 Parent
        self.parent_chunks: List[ParentChunk] = []
    """获取当前标题层级"""
    def _get_current_metadata(self) -> dict:
        metadata = { f"H{level}": title for level, title in sorted( self.header_stack.items()  ) }
        metadata["heading_path"] = " > ".join( title for _, title in sorted( self.header_stack.items() ) )
        return metadata
    """从 Marko AST 节点中提取纯文本。"""
    def _extract_raw_text(self, node) -> str:
        if hasattr(node, "children") and isinstance(node.children,list):
            return "".join( self._extract_raw_text(child)for child in node.children)
        if hasattr(node, "children") and isinstance(node.children,str):
            return node.children
        return ""
    """根据不同的类型的数据进行具体的切割"""
    def _node_to_block(self, node) -> Tuple[str, str]:
        if isinstance(node, Paragraph):
            return "text", self._extract_raw_text(node).strip()
        if isinstance(node, FencedCode):
            lang = (node.lang or "text").strip()
            code = ""
            if node.children:
                child = node.children[0]
                if hasattr(child, "children"):
                    code = child.children
            return "code", f"```{lang}\n{code.rstrip()}\n```"
        if isinstance(node, ListBlock):
            return "list", self._list_to_markdown(node)
        if isinstance(node, Table):
            return "table", self._table_to_markdown(node)
        return "text", ""
    """将列表转换成 Markdown"""
    def _list_to_markdown(self,node: ListBlock ) -> str:
        result = []
        for item in node.children:
            text = self._extract_raw_text( item ).strip()
            if not text:
                continue
            result.append(f"- {text}")
        return "\n".join(result)
    """将表格的一行转换成 Markdown。"""
    def _row_to_md(self, row_node) -> str:
        cells = [  self._extract_raw_text(cell) .strip() .replace("\n", " ") for cell in row_node.children  ]
        return "| " + " | ".join(cells) + " |"
    """将表格转换成 Markdown"""
    def _table_to_markdown( self, node: Table ) -> str:
        if not node.children:
            return ""
        header_row = node.children[0]
        data_rows = node.children[1:]
        # 表头
        header_md = self._row_to_md( header_row)
        # 分隔线
        separator_md = ( "| " + " | ".join( ["---"] * len(header_row.children) )  + " |" )
        # 数据行
        rows = [ self._row_to_md(row) for row in data_rows ]
        return "\n".join( [header_md, separator_md] + rows  )
    """更新标题层级"""
    def _update_header_stack( self, level: int, title: str ):
        self.header_stack[level] = title
        # 删除当前标题下面的所有低级标题
        self.header_stack = { k: v for k, v in self.header_stack.items() if k <= level }

    """Block列表 ， 不断往当前Parent添加Block ， 接近1000 ， 再添加会超过1000 ， 创建新的Parent """
    def _create_parent_chunks( self, blocks: List[Tuple[str, str]], base_metadata: dict ) -> List[ParentChunk]:
        metadata = base_metadata.copy()
        # 添加当前标题层级
        metadata.update(self._get_current_metadata())
        parent_chunks = []
        current_blocks = []
        current_length = 0
        for block_type,block in blocks:
            block=block.strip()
            if not block:
                continue
            block_length = len(block)
            # 组合长度要>parent_chunk_size就创建新父块
            if current_blocks and (current_length+len(block)+2>self.parent_chunk_size):
                parent_chunks.append(ParentChunk(blocks=current_blocks,metadata=metadata.copy()))
                # 重置
                current_blocks = []
                current_length = 0
            current_blocks.append((block_type,block))
            current_length+=block_length+2
        # 处理最后一个块的内容
        if current_blocks:
            parent_chunks.append(ParentChunk(blocks=current_blocks,metadata=metadata.copy()))
        return parent_chunks

    """将当前标题下面的所有内容创建成 Parent。文本、代码、列表、表格按照Markdown 原来的顺序进行拼接。 """
    def _flush_current_content(self,current_content: List[Tuple[str, str]],base_metadata: dict):

        if not current_content:
            return
        chunks = self._create_parent_chunks(blocks=current_content,base_metadata=base_metadata)
        self.parent_chunks.extend(chunks)
        current_content.clear()
    def process_documents(self,documents: List[Document]) -> Tuple[ List[ParentChunk], List[ChildChunk] ]:
        all_parent_chunks = []
        for doc in documents:
            markdown_text = doc.page_content
            base_metadata = ( doc.metadata.copy() if doc.metadata else {} )
            # Markdown → AST
            ast = self.markdown_parser.parse(markdown_text)
            # 每个文档重新开始
            self.header_stack = {}
            self.parent_chunks = []
            # 当前标题下面的内容
            current_content = []
            for node in ast.children:
                # 标题
                if isinstance(node, Heading):
                    # 遇到新标题之前，
                    # 先保存之前标题下面的正文
                    self._flush_current_content(current_content,base_metadata)
                    level = node.level
                    title = self._extract_raw_text(node).strip()
                    # 更新标题层级
                    self._update_header_stack(level,title)
                    continue
                # 文本 / 代码 / 列表 / 表格
                block_type,content = self._node_to_block(node)
                if content:
                    current_content.append((block_type,content))
            # 文档结束
            self._flush_current_content(current_content,base_metadata)
            all_parent_chunks.extend(self.parent_chunks)
        # Parent → Child
        child_chunks = self._generate_child_chunks(all_parent_chunks)
        return all_parent_chunks, child_chunks
    def _generate_child_chunks( self, parent_chunks: List[ParentChunk] ) -> List[ChildChunk]:
        child_chunks = []
        for parent in parent_chunks:
            # Parent <= 300
            # 直接作为一个 Child
            if len(parent.text) <= self.child_chunk_size:
                child_chunks.append(
                    ChildChunk( text=parent.text, parent_id=parent.parent_id, block_id=None, block_type="parent", chunk_index=0, metadata=parent.metadata.copy() ) )
                continue
            # 普通文本切割
            # Parent > 300
            # 继续切分 Child
            for block_type, block in parent.blocks:
                # 一个原始 Block 对应一个 block_id
                block_id = f"b_{uuid.uuid4().hex[:8]}"
                if block_type == "code":
                    chunks=self._split_code_block(block)
                elif block_type=="table":
                    chunks=self._split_table(block)
                elif block_type=="text" or block_type=="list":
                    chunks=self.child_splitter.split_text(block)
                else:
                    chunks=[block]
                for index,chunk in enumerate(chunks):
                    child_chunks.append( ChildChunk( text=chunk, parent_id=parent.parent_id, block_id=block_id, block_type=block_type, chunk_index=index, metadata=parent.metadata.copy() ) )
        return child_chunks
    """切割代码块，并保证每个子块都有 Markdown 代码围栏"""
    def _split_code_block(self, code_block: str) -> List[str]:
        lines = code_block.splitlines()
        if len(lines) < 2:
            return [code_block]
        # 第一行：```java / ```python / ```text
        fence = lines[0].strip()
        # 最后一行：```
        if not fence.startswith("```") or lines[-1].strip() != "```":
            return [code_block]
        # 获取代码语言
        language = fence[3:].strip()
        # 去掉首尾 ```，只切内部代码
        code = "\n".join(lines[1:-1])
        # 切割代码内容
        chunks = self.child_splitter.split_text(code)
        result = []
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            # 每一个切片重新加上 Markdown 代码围栏
            result.append(f"```{language}\n{chunk}\n```")
        return result
    """ 把大的md表格切割成多个小md表格 规则： 1. 保留表头 2. 保留分隔线 3. 按数据行切割  4. 每个子表格都是完整 Markdown 表格 """
    def _split_table(self,table_block:str)-> List[str]:
        lines = [ line.strip() for line in table_block.splitlines() if line.strip() ]
        # 非标准表格，直接返回
        if len(lines) < 3:
            return [table_block]
        # 第一行：表头
        header = lines[0]
        # 第二行：分隔线
        separator = lines[1]
        # 后面的都是数据
        rows = lines[2:]
        result = []
        current_rows = []
        current_length = len(header) + len(separator)
        for row in rows:
            row_length = len(row)
            # 当前表格加入这一行会超过 child 大小
            if current_rows and current_length + row_length > self.child_chunk_size:
                result.append("\n".join([header,separator,*current_rows]))
                current_rows = []
                current_length = len(header) + len(separator)
            current_rows.append(row)
            current_length += row_length + 1
        # 最后一批数据
        if current_rows:
            result.append("\n".join([header,separator,*current_rows]))
        return result

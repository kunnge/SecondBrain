from pathlib import Path
import shutil
from typing import List

from fastapi import UploadFile, HTTPException
from langchain_community.document_loaders import UnstructuredMarkdownLoader, TextLoader
from langchain_core.documents import Document

# 临时上传目录
UPLOAD_DIR = Path("backend/temp")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def parse_markdown(file: UploadFile)->List[Document]:
    """
    根据上传的 Markdown 文件解析内容
    :param file: 上传md文件
    :return: 解析后的数据
    """

    # 检查文件类型
    if not file.filename.endswith(".md"):
        raise HTTPException(
            status_code=400,
            detail="请上传 .md 文件"
        )

    # 上传后的临时文件路径
    file_path = UPLOAD_DIR / file.filename

    try:
        # 保存上传文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 创建TextLoader
        loader = TextLoader(
            file_path=str(file_path),
            encoding="utf-8",
        )

        # 进行解析
        docs = loader.load()
        # 你还可以手动补充一些自定义的全局元数据(如：文件名)，方便后续切分器使用
        for doc in docs:
            doc.metadata["filename"] = file.filename

        return docs

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Markdown 解析失败：{e}"
        )

    finally:
        # 删除临时文件
        if file_path.exists():
            file_path.unlink()

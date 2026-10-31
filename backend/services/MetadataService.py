import json
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from config.settings import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, LLM_MAX_TOKENS, LLM_TEMPERATURE, METADATA_MODEL

"""
定义文档元数据的结构模型。
使用 Pydantic 可以严格校验大模型返回的 JSON 数据结构是否符合预期。
"""
class DocumentMetadata(BaseModel):
    title: str = Field(description="文档标题")
    summary: str = Field(description="文档核心内容摘要")
    category: str = Field(description="文档所属分类")
    tags: list[str] = Field(description="3到5个主题标签")
    keywords: list[str] = Field(description="5到10个核心关键词")
"""
调用 DeepSeek 接口，分析文本内容并提取结构化元数据的服务类
"""
class MetadataService:
    def __init__(self):
        # 加载本地环境变量（需确保项目根目录下存在 .env 文件，并配置 DEEPSEEK_API_KEY）
        # 初始化 API 客户端
        # 注意：此处 base_url 需指向 DeepSeek 的服务地址，而非 OpenAI 官方地址
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        # 指定使用的 DeepSeek 模型版本
        self.model = METADATA_MODEL
    """
    接收文档内容，调用大模型生成元数据，并进行格式校验。
    :param content: 待处理的文档纯文本内容
    :return: 包含 title, summary, category, tags, keywords 的字典
    """
    def generate_metadata(self, content: str) -> dict:
        # 前置校验：确保传入的文本非空
        if not content or not content.strip():
            raise ValueError("文档内容不能为空")
        # 构建给大模型的 Prompt 提示词，明确任务目标和输出规则
        prompt = f"""
        你是一个个人知识库管理助手，请阅读文档并提取元数据。
        
        要求：
        1. title：根据整篇文档的主要内容生成简洁、准确的标题。
        2. summary：概括文档的主题、主要内容和实际用途，不要逐条罗列所有细节。
        3. category：从指定分类中选择最合适的一项。
        4. tags：提取3到5个能够代表整篇文档主要主题的标签。
        5. keywords：提取5到10个重要术语、技术名词、工具名称或核心概念。
        
        标签与关键词的区别：
        - tags 用于知识归类，回答“这篇文档主要属于哪些主题”。
        - keywords 用于内容检索，回答“通过哪些具体术语可以找到这篇文档”。
        - 标签优先选择覆盖整篇文档的主题，不要过度关注局部内容。
        - 关键词应兼顾具体工具名称和抽象技术概念。
        - 不要为了凑够数量而重复或添加无关信息。
        
        文档内容：
        {content}
        """
        # 发起 API 请求
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你负责分析知识库文档，并严格按照要求返回JSON。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            # 强制模型输出 JSON 格式（DeepSeek 支持该参数）
            response_format={"type": "json_object"},
            # 降低温度值（Temperature=0.1）以保证输出结果的稳定性和确定性
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS
        )
        # 提取模型返回的消息内容
        result = response.choices[0].message.content
        if not result:
            raise ValueError("AI 未返回有效内容")
        try:
            # 第一步：将返回的字符串解析为 Python 字典 (json.loads)
            # 第二步：使用 Pydantic 模型进行格式校验 (model_validate)
            metadata = DocumentMetadata.model_validate(json.loads(result))
        except (json.JSONDecodeError, ValidationError) as exc:
            # 捕获 JSON 解析错误或结构不匹配错误，并抛出明确的异常
            raise ValueError(f"AI 元数据格式校验失败：{exc}") from exc
        # 校验成功后，将 Pydantic 模型转换回普通字典进行返回
        return metadata.model_dump()

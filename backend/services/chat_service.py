from agents.knowledge_agent import knowledge_agent
from config.settings import CHAT_DEFAULT_TOP_K

"""Adapter used by the existing chat SSE API."""
class ChatService:

    @staticmethod
    def stream_answer(query: str,history: list | None = None,top_k: int = CHAT_DEFAULT_TOP_K,document_id: str | None = None,thread_id: str | None = None):
        return knowledge_agent.stream(query=query,history=history,top_k=top_k,document_id=document_id,thread_id=thread_id )

chat_service = ChatService()

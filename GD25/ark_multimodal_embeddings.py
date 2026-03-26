"""
Ark multimodal embeddings 的 LangChain 适配器。

用途：
- 作为 Mem0 `embedder.provider="langchain"` 的 `config.model` 实例传入；
- 统一按 Ark multimodal 接口契约发请求，避免 OpenAI 兼容层的 endpoint/body 差异。
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.embeddings import Embeddings
from volcenginesdkarkruntime import Ark


class ArkMultimodalEmbeddings(Embeddings):
    """LangChain Embeddings 适配类：封装 Ark multimodal embeddings 调用。"""

    def __init__(self, api_key: str, model: str, dimensions: Optional[int] = None) -> None:
        """
        初始化 Ark embeddings 客户端。

        Args:
            api_key: Ark API Key。
            model: Embedding 模型名，例如 `doubao-embedding-vision-251215`。
            dimensions: 向量维度（可选）。传入后会显式写入 Ark 请求参数。
        """
        if not api_key:
            raise ValueError("api_key 不能为空")
        if not model:
            raise ValueError("model 不能为空")
        if dimensions is not None and dimensions <= 0:
            raise ValueError("dimensions 必须是正整数")
        self._client = Ark(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成向量（逐条调用 Ark，确保请求体符合 multimodal 契约）。

        Args:
            texts: 待向量化文本列表。

        Returns:
            每条文本对应的向量列表。
        """
        if not texts:
            return []

        vectors: List[List[float]] = []
        for text in texts:
            payload = [{"type": "text", "text": text}]
            kwargs = {
                "model": self._model,
                "input": payload,
            }
            if self._dimensions is not None:
                kwargs["dimensions"] = self._dimensions
            resp = self._client.multimodal_embeddings.create(**kwargs)

            if not hasattr(resp, "data") or not hasattr(resp.data, "embedding"):
                raise ValueError("Ark embeddings 返回格式异常：缺少 data.embedding")

            embedding = resp.data.embedding
            if isinstance(embedding, list) and embedding and isinstance(embedding[0], list):
                vectors.append(embedding[0])
            elif isinstance(embedding, list):
                vectors.append(embedding)
            else:
                raise ValueError("Ark embeddings 返回格式异常：embedding 不是列表")
        return vectors

    def embed_query(self, text: str) -> List[float]:
        """
        生成单条查询向量。

        Args:
            text: 查询文本。

        Returns:
            单条向量。
        """
        results = self.embed_documents([text])
        return results[0] if results else []


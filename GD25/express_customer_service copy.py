# 快递行业智能客服助手 - 使用通义千问和 Mem0
# 运行方式：在 week04 目录下执行
#   conda activate py311_langGraph_1_0
#   python p30/express_customer_service.py

import os
import logging
from typing import List, Dict

from openai import OpenAI
from mem0 import Memory
from mem0.configs.base import MemoryConfig
from mem0.embeddings.configs import EmbedderConfig
from mem0.llms.configs import LlmConfig
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ark_multimodal_embeddings import ArkMultimodalEmbeddings

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ExpressCustomerService:
    """快递行业智能客服助手，集成通义千问与 Mem0 持久化记忆。"""

    def __init__(self) -> None:
        """初始化快递客服助手。"""
        self.api_key = self._get_api_key()
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"

        self.openai_client: OpenAI | None = None
        self.llm = None
        self.mem0: Memory | None = None
        self.prompt = None

        self._initialize_components()

    def _get_api_key(self) -> str:
        """获取 API 密钥并验证。"""
        api_key = os.getenv("ARK_API_KEY")
        if not api_key:
            raise ValueError(
                "未找到 ARK_API_KEY 环境变量。\n"
                "请设置环境变量：export ARK_API_KEY='your_api_key_here'"
            )
        logger.info("API 密钥已加载")
        return api_key

    def _test_api_connection(self) -> bool:
        """测试 API 连接。"""
        try:
            self.openai_client.chat.completions.create(
                model="doubao-seed-2-0-pro-260215",
                messages=[{"role": "user", "content": "测试连接"}],
                max_tokens=10,
            )
            logger.info("API 连接测试成功")
            return True
        except Exception as e:
            logger.error("API 连接测试失败: %s", str(e))
            return False

    def _initialize_components(self) -> None:
        """初始化所有组件。"""
        try:
            # 1. 初始化 OpenAI 客户端（兼容 DashScope）
            self.openai_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            logger.info("OpenAI 客户端初始化成功")

            # 2. 测试 API 连接
            if not self._test_api_connection():
                raise RuntimeError("API 连接失败，请检查 API 密钥和网络连接")

            # 3. 初始化 LangChain LLM
            self.llm = ChatOpenAI(
                temperature=0.3,
                openai_api_key=self.api_key,
                openai_api_base=self.base_url,
                model="doubao-seed-2-0-pro-260215",
            )
            logger.info("LangChain LLM 初始化成功")

            # 4. 初始化 Mem0 配置（显式使用本地 PostgreSQL + pgvector 进行持久化）
            from mem0.vector_stores.configs import VectorStoreConfig
            from mem0.graphs.configs import GraphStoreConfig

            ark_embedding_model = "doubao-embedding-vision-251215"
            embedding_dims = 1024
            ark_embeddings = ArkMultimodalEmbeddings(
                api_key=self.api_key,
                model=ark_embedding_model,
                dimensions=embedding_dims,
            )

            config = MemoryConfig(
                llm=LlmConfig(
                    provider="openai",
                    config={
                        "model": "doubao-seed-1-8-251228",
                        "api_key": self.api_key,
                        "openai_base_url": self.base_url,
                    },
                ),
                embedder=EmbedderConfig(
                    provider="langchain",
                    config={
                        "model": ark_embeddings,
                    },
                ),
                vector_store=VectorStoreConfig(
                    provider="pgvector",
                    config={
                        "user": "postgres",
                        "password": "sxl_pwd_123",
                        "host": "localhost",
                        "port": 5433,
                        "dbname": "gd25_biz_agent01_python",
                        "embedding_model_dims": embedding_dims,
                        # 可选：collection_name, embedding_model_dims 等
                    },
                ),
                graph_store=GraphStoreConfig(
                    provider="neo4j",
                    config={
                        "url": os.getenv("NEO4J_URL", "bolt://localhost:8687"),
                        "username": os.getenv("NEO4J_USERNAME", "neo4j"),
                        "password": os.getenv("NEO4J_PASSWORD", "mem0graph"),
                    },
                )
            )

            # 5. 初始化 Mem0
            self.mem0 = Memory(config=config)
            logger.info("Mem0 记忆系统初始化成功")

            # 6. 初始化提示词模板
            self._initialize_prompt()

        except Exception as e:
            logger.error("组件初始化失败: %s", str(e))
            raise

    def _initialize_prompt(self) -> None:
        """初始化提示词模板。"""
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="""您是一位专业的快递行业智能客服助手。请使用提供的上下文信息来个性化您的回复，记住用户的偏好和历史交互记录。

您的主要职责包括：
1. 快递查询服务：帮助用户查询包裹状态、物流轨迹、预计送达时间
2. 寄件服务：提供寄件指导、价格咨询、时效说明、包装建议
3. 问题解决：处理快递延误、丢失、损坏等问题，提供解决方案
4. 服务咨询：介绍各类快递服务、收费标准、服务范围
5. 投诉建议：接收用户反馈，记录投诉信息并提供处理方案

回复时请保持：
- 专业、礼貌、耐心的服务态度
- 准确、及时的信息提供
- 个性化的服务体验
- 如果没有具体信息，可以基于快递行业常识提供建议

请用中文回复，语气亲切专业。"""),
            MessagesPlaceholder(variable_name="context"),
            HumanMessage(content="{input}"),
        ])

    def retrieve_context(self, query: str, user_id: str) -> List[Dict]:
        """从 Mem0 检索相关上下文信息。"""
        try:
            # Mem0 内部：query 处理 → 向量化 → 向量库检索（按 user_id）→ 过滤/排序 → 返回
            # 可扩展参数：filters, top_k, threshold, rerank（见 cursor_docs/031002 第 4、5、14 节）
            memories = self.mem0.search(query, user_id=user_id)

            if memories and "results" in memories and memories["results"]:
                serialized_memories = " ".join(
                    mem.get("memory", "") for mem in memories["results"]
                )
            else:
                serialized_memories = "暂无相关历史记录"

            return [
                {"role": "system", "content": f"相关历史信息: {serialized_memories}"},
                {"role": "user", "content": query},
            ]
        except Exception as e:
            logger.warning("检索上下文时出错: %s", str(e))
            return [
                {"role": "system", "content": "相关历史信息: 暂无相关历史记录"},
                {"role": "user", "content": query},
            ]

    def generate_response(self, user_input: str, context: List[Dict]) -> str:
        """使用语言模型生成回复。"""
        try:
            chain = self.prompt | self.llm
            response = chain.invoke({"context": context, "input": user_input})
            return response.content
        except Exception as e:
            logger.error("生成回复时出错: %s", str(e))
            return "抱歉，我现在遇到了一些技术问题，请稍后再试。如有紧急情况，请联系人工客服。"

    def save_interaction(
        self, user_id: str, user_input: str, assistant_response: str
    ) -> None:
        """将交互记录保存到 Mem0。"""
        try:
            interaction = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": assistant_response},
            ]
            # Mem0 内部：LLM 信息抽取 → 冲突解决（去重/更新）→ 向量化并写入向量库
            # 可扩展参数：infer=False（原样存）, metadata, includes/excludes（见 cursor_docs/031002 第 4、5、14 节）
            self.mem0.add(interaction, user_id=user_id)
            logger.debug("交互记录已保存 - 用户ID: %s", user_id)
        except Exception as e:
            logger.warning("保存交互记录时出错: %s", str(e))

    def chat_turn(self, user_input: str, user_id: str) -> str:
        """处理一轮对话。"""
        try:
            context = self.retrieve_context(user_input, user_id)
            response = self.generate_response(user_input, context)
            self.save_interaction(user_id, user_input, response)
            return response
        except Exception as e:
            logger.error("处理对话时出错: %s", str(e))
            return "抱歉，处理您的请求时出现了问题。请重新尝试或联系技术支持。"

    def run_interactive_chat(self) -> None:
        """运行交互式聊天。"""
        print("=" * 60)
        print("欢迎使用智能快递客服助手！")
        print("=" * 60)
        print("我可以帮您处理各种快递相关问题：")
        print("快递查询、寄件服务、问题处理、服务介绍等")
        print("输入 'quit'、'exit' 或 '再见' 结束对话")
        print("=" * 60)

        user_id = input("请输入您的客户ID（或直接回车使用默认ID）: ").strip()
        if not user_id:
            user_id = "customer_001"

        print(f"您好！您的客户ID是: {user_id}")
        print("-" * 60)

        while True:
            try:
                user_input = input("您: ").strip()

                if user_input.lower() in ("quit", "exit", "再见", "退出", "bye"):
                    print("快递客服: 感谢您使用我们的服务！祝您生活愉快，期待下次为您服务！")
                    break

                if not user_input:
                    print("快递客服: 请输入您的问题，我很乐意为您提供帮助。")
                    continue

                response = self.chat_turn(user_input, user_id)
                print(f"快递客服: {response}\n")

            except KeyboardInterrupt:
                print("\n快递客服: 感谢您使用我们的服务！再见！")
                break
            except Exception as e:
                logger.error("交互过程中出错: %s", str(e))
                print("快递客服: 系统出现异常，请稍后重试。")


def main() -> None:
    """主程序入口。"""
    try:
        service = ExpressCustomerService()
        service.run_interactive_chat()
    except Exception as e:
        print(f"程序启动失败: {e}")
        print("\n请检查以下事项：")
        print("1. 确保已设置 ARK_API_KEY 环境变量")
        print("2. 确保网络连接正常")
        print("3. 确保 API 密钥有效且有足够权限")
        print("4. 确保已安装所有必需的依赖包（见 p30/requirements_p30.txt）")


if __name__ == "__main__":
    main()

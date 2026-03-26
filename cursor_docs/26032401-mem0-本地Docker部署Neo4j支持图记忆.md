# mem0 本地 Docker 部署 Neo4j（用于图记忆）

本文给你一套可直接落地的本地方案：在 Docker 中启动 Neo4j，让 mem0 的 `graph_store` 走 Neo4j，从而启用图记忆能力。

## 1. 前置条件

- 已安装 Docker Desktop（或 Docker Engine + Docker Compose）
- 本地可访问 `localhost:7474`（Neo4j Browser）和 `localhost:7687`（Bolt）
- 项目中已安装 mem0 相关依赖（至少包含 `langchain-neo4j`）

> 说明：当前仓库的默认图实现 `default` 实际也是 Neo4j，因此你要启用图功能时，部署 Neo4j 是最直接的方式。

## 2. 方案 A：直接使用仓库已有 docker-compose（推荐）

仓库已提供 `server/docker-compose.yaml`，其中已有 Neo4j 服务：

- 镜像：`neo4j:5.26.4`
- 认证：`neo4j/mem0graph`
- 端口映射：
  - `8474:7474`（HTTP 控制台）
  - `8687:7687`（Bolt）

在项目根目录执行：

```bash
docker compose -f server/docker-compose.yaml up -d neo4j
```

查看状态：

```bash
docker compose -f server/docker-compose.yaml ps neo4j
```

访问浏览器：

- URL: `http://localhost:8474`
- 用户名: `neo4j`
- 密码: `mem0graph`

如果你同时跑 `server/main.py` 默认配置，需要对应设置：

- `NEO4J_URI=bolt://localhost:8687`
- `NEO4J_USERNAME=neo4j`
- `NEO4J_PASSWORD=mem0graph`

## 3. 方案 B：独立最小 Docker Compose（只跑 Neo4j）

如果你只想单独启动 Neo4j，可新建一个 `docker-compose.neo4j.yml`：

```yaml
services:
  neo4j:
    image: neo4j:5.26.4
    container_name: mem0-neo4j
    restart: unless-stopped
    ports:
      - "7474:7474"  # Neo4j Browser
      - "7687:7687"  # Bolt
    environment:
      - NEO4J_AUTH=neo4j/mem0graph
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_apoc_export_file_enabled=true
      - NEO4J_apoc_import_file_enabled=true
      - NEO4J_apoc_import_file_use__neo4j__config=true
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
volumes:
  neo4j_data:
  neo4j_logs:
```

启动：

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

停止：

```bash
docker compose -f docker-compose.neo4j.yml down
```

## 4. 在 mem0 中配置 Neo4j 图存储

### 4.1 Python 配置示例

```python
from mem0 import Memory

config = {
    "version": "v1.1",
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": "YOUR_OPENAI_API_KEY",
            "model": "gpt-4.1-nano-2025-04-14",
            "temperature": 0.2
        }
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "api_key": "YOUR_OPENAI_API_KEY",
            "model": "text-embedding-3-small"
        }
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": "localhost",
            "port": 8432,
            "dbname": "postgres",
            "user": "postgres",
            "password": "postgres",
            "collection_name": "memories"
        }
    },
    "graph_store": {
        "provider": "neo4j",
        "config": {
            "url": "bolt://localhost:8687",
            "username": "neo4j",
            "password": "mem0graph",
            "database": "neo4j",
            "base_label": True
        },
        "threshold": 0.7
    }
}

memory = Memory.from_config(config)
```

> 若你使用“方案 B（端口 7687）”，请改为：`url = "bolt://localhost:7687"`。

### 4.2 为什么要配 `graph_store`

`graph_store.provider = "neo4j"` 后，mem0 会走图记忆实现，抽取实体关系并写入 Neo4j，用于后续关系检索与增强召回。

## 5. 本地连通性与功能验证

## 5.1 先验证 Neo4j 容器

```bash
docker ps | grep neo4j
```

```bash
docker logs mem0-neo4j --tail 100
```

如果你是用仓库自带 compose，容器名可能不是 `mem0-neo4j`，可先执行：

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"
```

## 5.2 再验证 mem0 是否可写图

可做一次最小调用：`memory.add(...)` 后，在 Neo4j Browser 中执行：

```cypher
MATCH (n) RETURN n LIMIT 20;
```

若有节点出现，说明图写入链路正常。

## 6. 常见问题排查

### 6.1 连接失败（`Connection refused`）

- 检查端口是否写对：`8687`（仓库 compose）或 `7687`（独立 compose）
- 检查 URL 是否为 `bolt://...`，不是 `http://...`
- 检查容器是否健康启动（日志里无持续报错）

### 6.2 鉴权失败（`Unauthorized`）

- 核对用户名密码：`neo4j/mem0graph`
- 若改过密码，确保 mem0 配置同步更新

### 6.3 依赖缺失（`langchain_neo4j is not installed`）

- 安装缺失包（在你的项目 Python 环境中）：
  - `langchain-neo4j`
  - `rank-bm25`

### 6.4 图里没数据

- 确认调用的是 `Memory.from_config(config)` 且 `graph_store.provider` 为 `neo4j`
- 确认 `add` 时带了 `user_id` / `agent_id` / `run_id` 之一（避免被过滤条件影响）
- 检查 LLM/Embedding 是否可用（图抽取依赖模型）

## 7. 推荐的最小启动顺序

1. 启动 Neo4j（Docker）
2. 打开 Neo4j Browser 确认可登录
3. 启动你的 mem0 应用
4. 发送一条 `add` 数据
5. 在 Neo4j Browser 查询验证节点/关系

---

如果你需要，我可以再给你补一份“与你当前 `GD25/express_customer_service copy.py` 对齐的 Neo4j 配置改造清单”（只列修改点，不改你现有代码）。

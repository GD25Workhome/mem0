# mem0 `graph_memory.search()` 代码阅读地图

本文聚焦 `mem0/memory/graph_memory.py` 的 `search()` 方法（`96-130` 附近），目标是帮助你快速理解：

- 方法到底做了什么；
- 每一步依赖哪些内部函数；
- 输入输出数据长什么样；
- 哪些点最容易影响正确性与性能；
- 如何高效打断点和验证。

---

## 1. 一句话总览

`MemoryGraph.search(query, filters, limit)` 的本质是一个“三段式流程”：

1. **实体抽取**：把用户 query 解析成实体列表（LLM + tool calling）
2. **图谱检索**：按实体 embedding 去 Neo4j 做相似节点检索，再展开关系边
3. **轻量重排**：用 BM25 对关系三元组做排序，返回 top5

返回值是一个列表，每项为：

- `{"source": "...", "relationship": "...", "destination": "..."}`。

---

## 2. 调用链路（建议按此顺序阅读）

建议阅读顺序：

1. `MemoryGraph.search()`
2. `MemoryGraph._retrieve_nodes_from_data()`
3. `MemoryGraph._search_graph_db()`
4. `BM25Okapi` 重排片段（仍在 `search()` 内）

对应伪流程：

```text
query + filters
  -> _retrieve_nodes_from_data
       -> entity_type_map
  -> _search_graph_db(node_list=entity_type_map.keys())
       -> raw relations (source, relationship, destination, similarity...)
  -> BM25 rerank
  -> top 5 triples
```

---

## 3. 核心步骤拆解

## 3.1 `search()` 主方法

关键逻辑：

- `entity_type_map = self._retrieve_nodes_from_data(query, filters)`
- `search_output = self._search_graph_db(node_list=list(entity_type_map.keys()), filters=filters)`
- 若无结果，直接 `return []`
- 将 `search_output` 转成三元组序列用于 BM25：
  - `[source, relationship, destination]`
- `tokenized_query = query.split(" ")` 后执行 `bm25.get_top_n(..., n=5)`
- 组装并返回 top5

阅读要点：

- 这里忽略了 `limit` 参数在重排阶段的传递，最终硬编码为 `n=5`；
- 返回值不包含 `similarity`，只保留三元组文本。

---

## 3.2 `_retrieve_nodes_from_data()`：实体抽取

输入：

- `data`（通常就是 query 文本）
- `filters`（需包含 `user_id`）

流程：

1. 选择工具定义：
  - 默认 `EXTRACT_ENTITIES_TOOL`
  - structured provider 下用 `EXTRACT_ENTITIES_STRUCT_TOOL`
2. 调用 `self.llm.generate_response(..., tools=_tools)`
3. 从 `tool_calls` 中提取 `extract_entities` 的 `entities`
4. 归一化：
  - 实体、类型全部 `lower()`
  - 空格替换为 `_`

输出：

- `entity_type_map: Dict[str, str]`，例如：
  - `{"舒小龙": "person"}` 归一后会变成 `{"舒小龙": "person"}`（中文通常不受空格替换影响）

注意点：

- 如果 LLM tool call 失败，函数会吞异常并返回空 map；
- 空 map 会导致后续图检索不执行实体循环，最终 `search()` 返回空列表。

---

## 3.3 `_search_graph_db()`：按实体 embedding 检索关系

输入：

- `node_list`（来自实体抽取结果）
- `filters`（`user_id` 必需，可选 `agent_id/run_id`）
- `limit`（默认 100）

流程（对每个 node）：

1. `self.embedding_model.embed(node)` 生成实体向量
2. 执行 Cypher：
  - 在用户范围内匹配候选节点
  - 计算 `vector.similarity.cosine(...)`
  - 过滤 `similarity >= threshold`（默认来自 `graph_store.threshold`, 常见 0.7）
  - 分别展开出边和入边（`UNION`）
  - 去重后按相似度排序并限制 `LIMIT $limit`
3. 把每个实体查询结果追加到 `result_relations`

输出：

- 包含关系与相似度信息的原始列表（字段比最终返回更全）。

注意点：

- 每个实体都要做一次 embedding + 一次图查询，实体数越多越慢；
- 若图中同一关系被多个 命中，会在总列表中重复出现（重排前未去重）。

---

## 3.4 BM25 重排阶段

当前实现：

- 语料：`[source, relationship, destination]` 三元组 token 列表
- query 分词：`query.split(" ")`
- 结果：`get_top_n(..., n=5)`

阅读时要重点关注：

1. **分词问题**：对中文 query，`split(" ")` 往往只得到整句一个 token，BM25 区分度会偏弱；
2. **结果上限固定**：忽略调用方传入的 `limit`；
3. **排序依据混合**：先按图相似度筛，再按 BM25 排，最终不暴露任何分值给上层。

---

## 4. 方法输入输出与数据契约

## 输入契约（必须满足）

- `query`: str，任意自然语言文本
- `filters`: dict，至少包含 `user_id`
- `limit`: int（目前只在图查询内部生效）

## 输出契约

- `List[Dict[str, str]]`，元素字段固定为：
  - `source`
  - `relationship`
  - `destination`

上层 `mem0/memory/main.py` 在 `Memory.search()` 中把它放到 `relations` 字段返回。

---

## 5. 正确性与性能检查清单（阅读时可对照）

### 正确性

1. 当 `tool_calls` 缺失时是否符合预期（当前会静默返回空）；
2. `filters["user_id"]` 缺失是否会触发异常；
3. 返回字段命名是否与上层消费一致（`destination` vs `target`）；
4. 中文 query 的 BM25 质量是否可接受。

### 性能

1. 每次 search 的 LLM 调用耗时（实体抽取）；
2. 每个实体 embedding 耗时；
3. 每个实体 Cypher 查询耗时；
4. `node_list` 长度对整体时延影响；
5. 图查询 `limit=100` 与最终 `n=5` 的浪费比例。

---

## 6. 推荐的断点/日志阅读路径

建议加断点或观察日志点：

1. `search()` 入口：看 `query`, `filters`, `limit`
2. `_retrieve_nodes_from_data()` 返回后：看 `entity_type_map`
3. `_search_graph_db()` 循环内：
  - 当前 node
  - embedding 生成耗时
  - Cypher 返回条数
4. BM25 之前/之后：
  - `search_output` 数量
  - `reranked_results` 数量与内容

若你要快速定位“为什么慢”，优先比较：

- `LLM实体抽取` vs `Neo4j检索` 两段耗时占比。

---

## 7. 与你业务脚本的对接关系（关键）

在你的业务脚本里，`mem0.search()` 的 `relations` 已经来自该方法。  
如果上层只拼接 `results` 不使用 `relations`，则会出现：

- 图检索链路已产生耗时；
- 但没有转化成回答上下文收益。

也就是说，阅读此方法时要同步考虑上层消费路径，而不只是函数内部正确性。

---

## 8. 阅读后可立即做的小实验

建议用同一 query 做三组对照：

1. `graph_store` 关闭；
2. `graph_store` 开启但上层不消费 `relations`；
3. `graph_store` 开启并消费 `relations`（结构化注入 prompt）。

对比：

- 端到端时延；
- 回答中是否出现关系型证据；
- 信息冲突时的稳定性。

这样能最快判断该函数在你当前业务中的“真实价值/成本比”。
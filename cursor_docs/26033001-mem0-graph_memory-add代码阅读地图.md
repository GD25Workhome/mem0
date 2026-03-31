# mem0 `graph_memory.add()` 代码阅读地图

本文聚焦 `mem0/memory/graph_memory.py` 的 `add()` 方法（约 `76-94` 行），结构与 `26032702-mem0-graph_memory-search代码阅读地图.md` 对齐，帮助你快速理解：

- 方法到底做了什么；
- 每一步依赖哪些内部函数；
- 输入输出数据长什么样；
- 哪些点最容易影响正确性与性能；
- 如何高效打断点和验证。

---

## 1. 一句话总览

`MemoryGraph.add(data, filters)` 的本质是一个**“抽取 → 冲突检测 → 先删后加”**的图记忆写入流程：

1. **实体抽取**：从 `data` 中抽出实体及类型（LLM + `extract_entities` tool）
2. **关系抽取**：在实体集合上建立三元组 `(source, relationship, destination)`（LLM + `establish_relationships` tool）
3. **图谱检索**：用与 `search()` 相同的 `_search_graph_db`，拉取当前用户作用域内与这些实体相关的已有关系（用于后续删改决策）
4. **删除决策**：LLM 根据「已有关系 + 新文本」决定要删哪些边（`delete_graph_memory` tool）
5. **执行删除**：对每条待删关系执行 Cypher `DELETE r`
6. **执行写入**：对每条待加关系做 embedding、相似节点对齐、`MERGE` 节点与边，并写入节点向量

返回值是一个字典：

- `{"deleted_entities": [...], "added_entities": [...]}`

其中两项分别是删除与新增各步 `graph.query` 的结果列表（具体结构以 Neo4j 返回为准）。

---

## 2. 调用链路（建议按此顺序阅读）

建议阅读顺序：

1. `MemoryGraph.add()`
2. `MemoryGraph._retrieve_nodes_from_data()`（与 `search()` 共用）
3. `MemoryGraph._establish_nodes_relations_from_data()`
4. `MemoryGraph._search_graph_db()`（与 `search()` 共用）
5. `MemoryGraph._get_delete_entities_from_search_output()`
6. `MemoryGraph._delete_entities()`
7. `MemoryGraph._add_entities()`（内含 `_search_source_node` / `_search_destination_node`）

对应伪流程：

```text
data + filters
  -> _retrieve_nodes_from_data
       -> entity_type_map
  -> _establish_nodes_relations_from_data(data, filters, entity_type_map)
       -> to_be_added（三元组列表，已做空格/关系名清洗）
  -> _search_graph_db(node_list=entity_type_map.keys())
       -> search_output（含相似度、一跳关系等）
  -> _get_delete_entities_from_search_output(search_output, data, filters)
       -> to_be_deleted
  -> _delete_entities(to_be_deleted, filters)
  -> _add_entities(to_be_added, filters, entity_type_map)
  -> return { deleted_entities, added_entities }
```

---

## 3. 核心步骤拆解

### 3.1 `add()` 主方法

关键代码顺序（不可调换语义：先算待删待加，再删再加）：

- `entity_type_map = self._retrieve_nodes_from_data(data, filters)`
- `to_be_added = self._establish_nodes_relations_from_data(data, filters, entity_type_map)`
- `search_output = self._search_graph_db(node_list=list(entity_type_map.keys()), filters=filters)`
- `to_be_deleted = self._get_delete_entities_from_search_output(search_output, data, filters)`
- `deleted_entities = self._delete_entities(to_be_deleted, filters)`
- `added_entities = self._add_entities(to_be_added, filters, entity_type_map)`

阅读要点：

- **写入路径比检索路径更重**：至少包含多次 LLM tool 调用 + 大量 embedding + 多条 Cypher；
- 与 `search()` 共用 `_search_graph_db`，但用途不同：这里是**为删除决策提供“当前图里有什么”的上下文**，不是给最终用户看的 BM25 重排结果。

---

### 3.2 `_retrieve_nodes_from_data()`：实体抽取（与 search 共用）

详见 `26032702` 第 3.2 节；在 `add()` 中：

- 输入 `data` 一般为拼接后的用户/助手文本（由 `Memory._add_to_graph` 传入）；
- 输出 `entity_type_map` 同时驱动：**关系抽取的实体列表** 与 **`_search_graph_db` 的查询种子**。

---

### 3.3 `_establish_nodes_relations_from_data()`：关系三元组抽取

流程概要：

1. 组装 `user_identity`（`user_id`，可选 `agent_id` / `run_id`），写入 `EXTRACT_RELATIONS_PROMPT`；
2. 若配置了 `graph_store.custom_prompt`，会插入到提示中的 `CUSTOM_PROMPT` 占位；
3. 用户消息：默认带 `List of entities: ...` + 原文；自定义 prompt 时可能只用原文；
4. `self.llm.generate_response(..., tools=[RELATIONS_TOOL 或 RELATIONS_STRUCT_TOOL])`；
5. 从首个 `tool_calls` 中取 `arguments.entities`；
6. `_remove_spaces_from_entities`：`source`/`destination` 小写+空格改下划线，`relationship` 另经 `sanitize_relationship_for_cypher`（**关系类型会作为 Cypher 中关系类型使用**，与删除、合并边一致）。

阅读要点：

- 若 LLM 未返回合法 `tool_calls`，`to_be_added` 可能为空，后续只可能走删除或空操作；
- 关系名必须合法，否则后续 `-[r:{relationship}]->` 可能执行失败。

---

### 3.4 `_search_graph_db()`：为删除决策拉取已有关系（与 search 共用）

逻辑与 `26032702` 第 3.3 节一致：对每个种子实体 embedding，在图内做相似节点匹配并展开一跳出/入边。

在 `add()` 中的差异仅是**用途**：产出 `search_output` → 格式化后喂给删除 LLM，而不是 BM25 截断 top5。

---

### 3.5 `_get_delete_entities_from_search_output()`：删边决策

流程概要：

1. `format_entities(search_output)` 转成可读字符串；
2. `get_delete_messages(...)` 生成 system/user 提示（定义在 `mem0/graphs/utils.py`，强调矛盾/过时再删）；
3. LLM + `DELETE_MEMORY_TOOL_GRAPH` / 结构化版本；
4. 收集 `name == "delete_graph_memory"` 的 `arguments` 列表；
5. `_remove_spaces_from_entities` 与新增侧格式对齐。

阅读要点：

- 无 `tool_calls` 或没有 `delete_graph_memory` 时，`to_be_deleted` 为空，跳过物理删除；
- 删除 Cypher 使用**动态关系类型** `-[r:{relationship}]->`，必须与图中实际 `type(r)` 一致（经过 sanitize 后的字符串）。

---

### 3.6 `_delete_entities()`：执行删边

对 `to_be_deleted` 中每条 `{source, destination, relationship}`：

- 用 `name` + `user_id`（及可选 agent/run）定位两个端点；
- `MATCH ... -[r:REL]-> ... DELETE r`。

阅读要点：

- 若关系类型或节点名与图内不一致，删除可能静默匹配 0 条；
- 多条删除顺序执行，**非批量**（文件内 TODO 提到可用 APOC 批处理）。

---

### 3.7 `_add_entities()`：合并节点、写 embedding、`MERGE` 关系

对 `to_be_added` 中每条三元组：

1. 从 `entity_type_map` 取 `source`/`destination` 的类型；缺省为 `__User__`；
2. 根据 `base_label` 决定节点标签策略：`__Entity__` 统一标签 + 属性区分类型，或按类型做动态标签；
3. `embed(source)`、`embed(destination)`；
4. `_search_source_node` / `_search_destination_node`（默认阈值 **0.9**，与图检索 `self.threshold` 可不同）在库中找最相似已有节点；
5. 四分支 Cypher（简化理解）：
   - 仅命中 source：在已知 source 上 `MERGE` destination，写 destination 向量，再 `MERGE` 边；
   - 仅命中 destination：对称处理 source；
   - 两端都命中：两节点按 `elementId` 定位，只 `MERGE` 边（含 mentions 统计）；
   - 两端都未命中：`MERGE` 两个节点，分别 `setNodeVectorProperty`，再 `MERGE` 边。

阅读要点：

- **消歧与合并**依赖向量相似度；阈值 0.9 较严，新实体更容易新建节点而非合并；
- 每条待加关系至少 **2 次 embed + 最多 2 次相似节点查询 + 1 次写入查询**，关系多时延迟线性放大；
- `ON CREATE` / `ON MATCH` 维护 `mentions`、时间戳等，便于后续分析或去重策略扩展。

---

## 4. 方法输入输出与数据契约

### 输入契约

- `data`: `str`，一段待写入图的文本（常见为多行 user/assistant 内容拼接）。
- `filters`: `dict`，**必须包含** `user_id`；可选 `agent_id`、`run_id`（与 Cypher 中节点属性过滤一致）。

### 输出契约

- `dict`：
  - `deleted_entities`: `list`，每个元素为单次删除查询的返回（通常嵌套列表）；
  - `added_entities`: `list`，每个元素为单次写入查询的返回。

上层 `mem0/memory/main.py` 中 `Memory._add_to_graph` 会把该返回值作为 `add(...)` 的 `relations` 部分（与向量侧 `results` 并列）。

---

## 5. 正确性与性能检查清单（阅读时可对照）

### 正确性

1. 实体抽取为空时，`_search_graph_db` 的循环次数为 0，`search_output` 为空，删除决策仅依赖「空上下文 + 新文本」，行为是否符合预期；
2. `relationship` 经 `sanitize_relationship_for_cypher` 后是否与写入、删除、查询三处一致；
3. `_add_entities` 中相似节点检索阈值 **0.9** 与 `self.threshold`（图搜索默认 0.7）不一致，是否会导致「搜索能命中、写入却新建」类现象；
4. LLM 删除建议是否过于激进（需结合 `DELETE_RELATIONS_SYSTEM_PROMPT` 细读）。

### 性能

1. **LLM 调用次数**：实体抽取 + 关系抽取 + 删除决策，至少 3 次（每次网络往返）；
2. **Embedding 次数**：每个待加关系的 source、destination 各 1 次，再加 `_search_source_node` / `_search_destination_node` 所用向量；
3. **Cypher 次数**：删除条数 + 新增条数，且新增前还有相似节点查询（每条关系 2 次）；
4. 与 `Memory.add` 中向量路径**并行**执行时，图路径往往成为尾延迟来源之一。

---

## 6. 推荐的断点/日志阅读路径

建议观察点：

1. `add()` 入口：`data` 长度、`filters`；
2. `_retrieve_nodes_from_data` 返回后：`entity_type_map` 的 key 数量与内容；
3. `_establish_nodes_relations_from_data` 返回后：`to_be_added` 条数及样例三元组；
4. `_search_graph_db` 返回后：`search_output` 条数（判断删除上下文是否充足）；
5. `_get_delete_entities_from_search_output` 返回后：`to_be_deleted` 是否非空；
6. `_add_entities` 循环内：每条的 `source_node_search_result` / `destination_node_search_result` 命中情况（理解走了哪条 Cypher 分支）。

若排查「为什么 add 很慢」，建议分段计时：**三段 LLM**、**embedding 总和**、**Neo4j 查询总和**。

---

## 7. 与 `search()` 的对比小结（同文件内对照阅读）

| 维度 | `search()` | `add()` |
|------|------------|---------|
| 主要目的 | 召回关系供上层使用 | 增量写入并维护一致性（删旧加新） |
| LLM 次数 | 约 1 次（实体） | 约 3 次（实体 + 关系 + 删除） |
| `_search_graph_db` | 是，结果经 BM25 取 top5 | 是，结果供删除 LLM，无 BM25 |
| 写库 | 否 | 是（删边 + MERGE 节点/边 + 向量） |

---

## 8. 阅读后可立即做的小实验

1. **最小 data**：单句事实，观察 `to_be_added` 条数与图中实际边数是否一致；
2. **矛盾句**：先写入 `A -[lives_in]-> B`，再写入否定/更正，观察 `to_be_deleted` 是否非空及边是否被删掉；
3. **关闭删除**：若临时注释 `_get_delete_entities` / `_delete_entities`（仅本地实验），对比图膨胀速度与业务正确性。

---

## 9. 相关文档

- 同结构检索侧阅读地图：`cursor_docs/26032702-mem0-graph_memory-search代码阅读地图.md`
- 向量与图在上层的并发与返回字段：`mem0/memory/main.py` 中 `Memory.add()`、`_add_to_graph()`

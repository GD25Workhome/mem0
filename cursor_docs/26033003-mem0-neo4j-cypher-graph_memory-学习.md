# mem0 图记忆：Neo4j Browser 中一步步学会 Cypher（对照 `graph_memory.py`）

> 你说的“CQL”在 Neo4j 语境里通常指的是 **Cypher**。

这份文档的目标是两件事：
1. 让你在网页（Neo4j Browser）里能稳定写出“节点/边/关系类型”的查询
2. 最终能把 `mem0/memory/graph_memory.py` 里出现的每一段 Cypher “翻译成你能读懂的图查询动作”

---

## 0. 开始前：确认你连到的是哪个数据库

Neo4j Browser 左上角的提示符通常会显示类似 `neo4j$` 或 `system$`。

- 如果是 `neo4j$`，通常表示你在业务图写入/读取所在的库（mem0 默认就是这个）
- 如果切到 `system$`，很多业务数据/过程可能不在这里，查询就可能失败或查不到

在 Browser 控制台先执行以下命令（强烈建议每次切换后都做一次）：

```cypher
:use neo4j
```

如果你不确定 Neo4j 当前实例有哪些库，可用：

```cypher
SHOW DATABASES;
```

---

## 1. 三条最基础 Cypher：看到“边”而不是只看到“节点”

你已经会：

```cypher
MATCH (n) RETURN n LIMIT 25;
```

它只能看到节点对象，不能看到边。

下面三条是“看边”的最小集合：

1. 看所有边（只要你连对库，且图里确实有关系）
```cypher
MATCH ()-[r]->()
RETURN r
LIMIT 25;
```

2. 看边类型（关系类型）
```cypher
MATCH ()-[r]->()
RETURN DISTINCT type(r) AS rel_type
ORDER BY rel_type
LIMIT 200;
```

3. 看节点 + 关系（三元组）
```cypher
MATCH (a)-[r]->(b)
RETURN a, type(r) AS rel_type, b
LIMIT 25;
```

只要你能跑通第 1~3 条，接下来“对照 `graph_memory.py`”就会非常顺。

---

## 2. 你的 mem0 图：先找 user_id，再查某个 user 的边

`graph_memory.py` 在写入/读取时，几乎总会带过滤条件 `user_id`（可选 `agent_id`、`run_id`）。

先找有哪些 `user_id`：

```cypher
MATCH (n)
RETURN DISTINCT n.user_id AS user_id
ORDER BY user_id
LIMIT 50;
```

假设你发现某个用户是 `customer_001`，你就可以查这个用户的边：

```cypher
MATCH (a {user_id: 'customer_001'})-[r]->(b {user_id: 'customer_001'})
RETURN a.name AS source, type(r) AS rel_type, b.name AS destination,
       r.mentions AS mentions, r.created AS created
LIMIT 50;
```

如果你还没看到 `a.name` / `b.name`，说明节点属性命名可能不同。你可以先看任意节点有哪些键：

```cypher
MATCH (n)
RETURN keys(n) AS node_keys
LIMIT 1;
```

---

## 3. 查“某个节点跟谁连着”：出边、入边、邻居全图

### 3.1 查出边（从该节点指向哪些节点）

```cypher
MATCH (a {user_id: 'customer_001', name: '某个实体名'})-[r]->(b)
RETURN a.name AS source, type(r) AS rel_type, b.name AS destination, properties(r) AS rel_props
LIMIT 50;
```

### 3.2 查入边（哪些节点指向它）

```cypher
MATCH (a {user_id: 'customer_001', name: '某个实体名'})<-[r]-(b)
RETURN b.name AS source, type(r) AS rel_type, a.name AS destination, properties(r) AS rel_props
LIMIT 50;
```

### 3.3 只看“邻居列表”（不关心方向）

```cypher
MATCH (a {user_id: 'customer_001', name: '某个实体名'})-[r]-(b)
RETURN DISTINCT a.name AS focus, type(r) AS rel_type, b.name AS neighbor, properties(r) AS rel_props
LIMIT 50;
```

---

## 4. mem0 的关系类型：为什么有时你写 `type(r)` 对不上

在 `graph_memory.py` 里，关系抽取出来的 `relationship` 会做两类清洗：

1. 全部转小写，并把空格替换为下划线
2. 再经过 `sanitize_relationship_for_cypher()`，把很多标点替换成类似 `_period_`、`_comma_` 等 token

因此你在 Browser 里要用的关系类型，必须和数据库里实际 `type(r)` 完全一致。

当你不确定关系类型到底叫什么，就回到第 1 节的“列出所有 rel_type”：

```cypher
MATCH ()-[r]->()
RETURN DISTINCT type(r) AS rel_type
ORDER BY rel_type
LIMIT 200;
```

---

## 5. 对照 `graph_memory.py`：把每段 Cypher 翻译成“图动作”

下面按 `graph_memory.py` 里出现的 Cypher 块来讲解。你可以把这些理解为 mem0 的“图记忆 CRUD+检索逻辑”。

---

### 5.1 `delete_all(self, filters)`：按 user/agent/run 整块删节点（带边一起删）

对应代码结构：

```cypher
MATCH (n <node_label> {user_id: $user_id, ...})
DETACH DELETE n
```

关键点：
1. `MATCH (n ...)` 只匹配某个租户范围内的节点
2. `DETACH DELETE n` 会同时删除该节点上的所有入边/出边（所以你不会留下孤立边）

如果你要手工验证，你可以先看将被删除的节点数：

```cypher
MATCH (n {user_id: 'customer_001'})
RETURN count(n) AS cnt;
```

---

### 5.2 `get_all(self, filters, limit)`：返回“(source)-[r]->(target)”三元组

对应代码结构：

```cypher
MATCH (n <node_label> {props})-[r]->(m <node_label> {props})
RETURN n.name AS source, type(r) AS relationship, m.name AS target
LIMIT $limit;
```

理解方式：
1. 只取“从 n 指向 m”的有向边
2. 输出里把边类型当成字符串 `relationship`

你可以自己复刻（这里省略 `<node_label>`，因为你的 `base_label` 配置可能不同）：

```cypher
MATCH (n {user_id: 'customer_001'})-[r]->(m {user_id: 'customer_001'})
RETURN n.name AS source, type(r) AS relationship, m.name AS target
LIMIT 50;
```

---

### 5.3 `_search_graph_db(self, node_list, filters, limit)`：向量相似度 + 展开一跳入/出边

这是最核心的一段检索 Cypher。它做的事可以拆成四步：

1. 找候选节点 `n`（在租户范围内）
2. 用 `vector.similarity.cosine(n.embedding, $n_embedding)` 计算相似度，过滤掉相似度低的节点
3. 对每个命中的 `n`，分别取：
   1) 出边 `n-[r]->m`
   2) 入边 `n<-[r]-m`
   并用 `UNION` 合并结果
4. `WITH distinct ...` 去重后，再按相似度排序输出

对应代码结构（保留关键句）：

```cypher
MATCH (n <node_label> {props})
WHERE n.embedding IS NOT NULL
WITH n,
     round(2 * vector.similarity.cosine(n.embedding, $n_embedding) - 1, 4) AS similarity
WHERE similarity >= $threshold

CALL {
  WITH n
  MATCH (n)-[r]->(m <node_label> {props})
  RETURN n.name AS source,
         elementId(n) AS source_id,
         type(r) AS relationship,
         elementId(r) AS relation_id,
         m.name AS destination,
         elementId(m) AS destination_id

  UNION

  WITH n
  MATCH (n)<-[r]-(m <node_label> {props})
  RETURN m.name AS source,
         elementId(m) AS source_id,
         type(r) AS relationship,
         elementId(r) AS relation_id,
         n.name AS destination,
         elementId(n) AS destination_id
}

WITH distinct source, source_id, relationship, relation_id, destination, destination_id, similarity
RETURN source, source_id, relationship, relation_id, destination, destination_id, similarity
ORDER BY similarity DESC
LIMIT $limit;
```

你需要重点理解的 Cypher 点：
1. `elementId(n)` / `elementId(r)`：用“稳定内部标识”定位节点或边（后面 DELETE/UPDATE 会用到）
2. `CALL { ... }`：在 Neo4j 里实现子查询（把“出边”和“入边”的逻辑封装起来）
3. `UNION`：把出边和入边结果合并成一份
4. `WITH distinct ...`：避免同一条关系被重复输出

手工复刻时，你不太容易自己造 `$n_embedding`，所以这里的学习重点是“结构理解”，不是一定要你立刻手跑出向量检索的结果。

---

### 5.4 `_delete_entities(self, to_be_deleted, filters)`：按 (source, relationship, destination) 删除指定边

对应代码结构：

```cypher
MATCH (n <node_label> {source_props})-[r:{relationship}]->(m <node_label> {dest_props})
DELETE r
```

关键点：
1. 关系类型用的是动态字符串：`-[r:{relationship}]->`
2. 节点匹配同样带 user_id（可选 agent_id/run_id），所以必须在相同租户范围内删除才会命中
3. 这里只删边 `DELETE r`，不会删节点（和 `DETACH DELETE n` 不同）

---

### 5.5 `_add_entities(self, to_be_added, filters, entity_type_map)`：写入边 + mentions/created，并做节点合并去重

写入逻辑里最重要的是 4 个分支（取决于向量相似搜索结果里 source/destination 是否已命中到现有节点）：

为了让你能“逐条对照所有 SQL”，下面我把 4 个分支的 Cypher 片段补齐（把 Python 动态拼接的 `<node_label>/<...>` 记为占位符即可）。

分支 A：source 命中，destination 未命中（目标侧会 `MERGE` 创建节点）

```cypher
MATCH (source)
WHERE elementId(source) = $source_id
SET source.mentions = coalesce(source.mentions, 0) + 1
WITH source
MERGE (destination <destination_label> {<merge_props_str>})
ON CREATE SET
    destination.created = timestamp(),
    destination.mentions = 1,
    <destination_extra_set>
ON MATCH SET
    destination.mentions = coalesce(destination.mentions, 0) + 1
WITH source, destination
CALL db.create.setNodeVectorProperty(destination, 'embedding', $destination_embedding)
WITH source, destination
MERGE (source)-[r:{relationship}]->(destination)
ON CREATE SET
    r.created = timestamp(),
    r.mentions = 1
ON MATCH SET
    r.mentions = coalesce(r.mentions, 0) + 1
RETURN source.name AS source, type(r) AS relationship, destination.name AS target
```

分支 B：destination 命中，source 未命中（源侧会 `MERGE` 创建节点）

```cypher
MATCH (destination)
WHERE elementId(destination) = $destination_id
SET destination.mentions = coalesce(destination.mentions, 0) + 1
WITH destination
MERGE (source <source_label> {<merge_props_str>})
ON CREATE SET
    source.created = timestamp(),
    source.mentions = 1,
    <source_extra_set>
ON MATCH SET
    source.mentions = coalesce(source.mentions, 0) + 1
WITH source, destination
CALL db.create.setNodeVectorProperty(source, 'embedding', $source_embedding)
WITH source, destination
MERGE (source)-[r:{relationship}]->(destination)
ON CREATE SET
    r.created = timestamp(),
    r.mentions = 1
ON MATCH SET
    r.mentions = coalesce(r.mentions, 0) + 1
RETURN source.name AS source, type(r) AS relationship, destination.name AS target
```

分支 C：source、destination 都命中（只 `MERGE` 边，不新建端点）

```cypher
MATCH (source)
WHERE elementId(source) = $source_id
SET source.mentions = coalesce(source.mentions, 0) + 1
WITH source
MATCH (destination)
WHERE elementId(destination) = $destination_id
SET destination.mentions = coalesce(destination.mentions, 0) + 1
MERGE (source)-[r:{relationship}]->(destination)
ON CREATE SET
    r.created_at = timestamp(),
    r.updated_at = timestamp(),
    r.mentions = 1
ON MATCH SET
    r.mentions = coalesce(r.mentions, 0) + 1
RETURN source.name AS source, type(r) AS relationship, destination.name AS target
```

分支 D：source、destination 都未命中（两端都 `MERGE` 创建节点并写 embedding）

```cypher
MERGE (source <source_label> {<source_props>})
ON CREATE SET
    source.created = timestamp(),
    source.mentions = 1,
    <source_extra_set>
ON MATCH SET
    source.mentions = coalesce(source.mentions, 0) + 1
WITH source
CALL db.create.setNodeVectorProperty(source, 'embedding', $source_embedding)
WITH source
MERGE (destination <destination_label> {<dest_props>})
ON CREATE SET
    destination.created = timestamp(),
    destination.mentions = 1,
    <destination_extra_set>
ON MATCH SET
    destination.mentions = coalesce(destination.mentions, 0) + 1
WITH source, destination
CALL db.create.setNodeVectorProperty(destination, 'embedding', $dest_embedding)
WITH source, destination
MERGE (source)-[rel:{relationship}]->(destination)
ON CREATE SET rel.created = timestamp(), rel.mentions = 1
ON MATCH SET rel.mentions = coalesce(rel.mentions, 0) + 1
RETURN source.name AS source, type(rel) AS relationship, destination.name AS target
```

你接下来要做的事是把这些占位符替换成你实际库里的值：
- `<node_label>` / `<source_label>` / `<destination_label>`：取决于你的 `base_label` 配置（`__Entity__` 还是类型动态标签）
- `<source_props>/<dest_props>`：至少包含 `name` + `user_id`，如果你开启了 agent/run 隔离，还会包含 `agent_id/run_id`
- `{relationship}`：必须用 sanitize 后的真实关系类型字符串

一句话总理解（帮助你把 4 个分支串起来）：
1. 先用 embedding 找“最相似节点”（只返回 elementId）
2. 命中情况决定端点是否需要创建
3. 最后用 `MERGE` 写入有向关系，并通过 `ON CREATE/ON MATCH` 维护 `created/mentions/created_at/updated_at`

关于 `CALL db.create.setNodeVectorProperty(...)`：
1. 这不是标准 Cypher 语法，而是 Neo4j 的某个过程/插件提供的能力
2. 作用是把节点属性写成向量索引可用的形式（具体依赖你 Neo4j 是否安装对应插件/向量功能）

---

### 5.6 `_search_source_node(...)` / `_search_destination_node(...)`：向量检索时只返回 elementId

这两个函数结构几乎相同，只是变量名从 source_candidate / destination_candidate 不一样。

对应关键结构：

```cypher
MATCH (source_candidate <node_label>)
WHERE source_candidate.embedding IS NOT NULL
  AND source_candidate.user_id = $user_id
  AND (可选 agent_id/run_id)

WITH source_candidate,
     round(2 * vector.similarity.cosine(source_candidate.embedding, $source_embedding) - 1, 4) AS source_similarity

WHERE source_similarity >= $threshold
WITH source_candidate, source_similarity
ORDER BY source_similarity DESC
LIMIT 1
RETURN elementId(source_candidate)
```

理解要点：
1. 它只找“最相似的一个节点”（`LIMIT 1`）
2. 它返回的是节点的内部标识 `elementId(...)`，而不是节点本体
3. 后续写入分支用 elementId 定位节点，避免再次模糊匹配带来的不一致

---

### 5.7 `reset(self)`：清空整个图（不带 user_id 过滤）

对应代码结构：

```cypher
MATCH (n)
DETACH DELETE n
```

注意：这是“全库级别”的清空操作，不带任何过滤条件。

---

## 6. 给你一套“可操作练习”：从零查出边，再复刻 `get_all`

假设你的 user_id 是 `customer_001`。

1. 列出关系类型
```cypher
MATCH ()-[r]->()
RETURN DISTINCT type(r) AS rel_type
ORDER BY rel_type
LIMIT 200;
```

2. 查该用户的三元组（等价于 `get_all` 的核心语义）
```cypher
MATCH (n {user_id: 'customer_001'})-[r]->(m {user_id: 'customer_001'})
RETURN n.name AS source, type(r) AS relationship, m.name AS target
LIMIT 50;
```

3. 选一个你感兴趣的实体名，查它的出边
```cypher
MATCH (a {user_id: 'customer_001', name: '某个实体名'})-[r]->(b)
RETURN a.name AS source, type(r) AS relationship, b.name AS destination,
       r.mentions AS mentions
LIMIT 50;
```

4. 查它的入边
```cypher
MATCH (a {user_id: 'customer_001', name: '某个实体名'})<-[r]-(b)
RETURN b.name AS source, type(r) AS relationship, a.name AS destination,
       r.mentions AS mentions
LIMIT 50;
```

---

## 7. 常见“查询失败”原因（按你最可能遇到的来）

1. 默认数据库选错
   - 你看到 `system$` 而 mem0 实际写在 `neo4j` 库
   - 解决：` :use neo4j `
2. 你写的关系类型 `type(r)` 不等于实际存储的 `type(r)`
   - 原因：mem0 对 relationship 做了 sanitize（标点替换为 token）
   - 解决：先跑 `RETURN DISTINCT type(r)` 再用结果中的 rel_type
3. 节点标签匹配不到（`base_label` 差异）
   - 解决：先用 `MATCH (n) RETURN labels(n), count(*) ...` 看实际标签
4. 向量过程/索引没启用或不可用
   - 触发点：`CALL db.create.setNodeVectorProperty(...)`、`vector.similarity.cosine(...)`
   - 解决：确保你 Neo4j 部署了 mem0 需要的向量能力/插件

---

## 8. 我建议你下一步把这些信息发我（我就能把查询“定制到你当前库”）

你在 Neo4j Browser 里把以下 3 条的输出（前几行即可）贴出来，我就能判断你的 `base_label`、关系类型命名、以及字段是否是 `name/user_id/mentions`：

1. 关系类型列表（前 10）
```cypher
MATCH ()-[r]->()
RETURN DISTINCT type(r) AS rel_type
ORDER BY rel_type
LIMIT 10;
```

2. 节点标签情况（前 10 个标签组合）
```cypher
MATCH (n)
RETURN labels(n) AS node_labels, count(*) AS cnt
ORDER BY cnt DESC
LIMIT 10;
```

3. user_id 样例（前 10）
```cypher
MATCH (n)
RETURN DISTINCT n.user_id AS user_id
ORDER BY user_id
LIMIT 10;
```


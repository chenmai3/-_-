# rule_construct.vue 重构进度

本目录只承接 `rule_construct.vue` 页面实际使用的后端功能，不再从旧的 `rule_construct.py`、`zhihai_qa`、`zhihaiQA_api.py`、`chatzxl.py` 直接 import。

## 当前接口

- `api.py`
  - 只保留 FastAPI 路由入口。
- `permissions.py`
  - `get_koqathemeWithpermission`
  - `get_koqascenariosWithpermission`
- `rule_repository.py`
  - `new_rule_submit`
  - `sql_polling`
  - `rule_delete`
- `graph_match.py`
  - `neo4j_match`
  - `neo4j_match_1`
- `rule_generate_stream.py`
  - `rule_generate`
- `batch_rule_generation.py`
  - `rule_generation`
  - `uploadRule`

## 公共代码

- `common.py`
  - 项目相对路径、配置读取、数据库连接、前端响应、SSE 队列输出。
- `rule_database.py`
  - 规则表保存、删除、主题 label 查询、规则入口实体向量化。
- `rule_path_core.py`
  - 规则生成和规则试算中共用的图谱路径查询、路径格式化、Cypher 生成、家谱特殊查询。
- `dependencies/`
  - 当前页面所需的本地依赖副本，避免继续引用老目录。

## 已处理

- 删除占位 `pending_migration`。
- 删除旧项目直接 import。
- 删除固定盘符路径，改为项目相对路径。
- 大模型调用处显式给出 `model`、`temperature`、`stream`。
- SSE 接口增加异常兜底，异常会返回错误事件，整体流不会静默断开。
- `rule_path_core.py` 已抽出 Neo4j 数据源选择、查询执行、路径格式化、路径拆分、实体模糊匹配公共函数。
- `dependencies/rule_graph_engine.py` 已裁掉图谱录入遗留的插入/删除类函数，只保留规则构建页需要的读取图谱、模板挖掘、文件规则解析、规则校验逻辑。
- `dependencies/rule_graph_engine.py` 已补充 Neo4j 查询关闭兜底、LLM 调用兜底、文件规则 JSON 解析兜底、规则校验单条异常兜底。
- 已移除 `rule_path_core.py` 中未被新接口调用的 `Neo4jQueryBuilder` 家谱旧查询表。
- `file_rule_parse` 已拆成关系集合查询、提示词构造、LLM 结果解析三段。
- `llm_semantic_validate` 已拆成提示词构造、默认失败结果、校验结果归一化三段。
- `validate_single_rule_v2` 已拆出统一返回结构、图谱命中查询、语义结果应用三段。
- 新增 `dependencies/prompts.py`，集中存放规则模板命名、文件规则解析、语义校验、规则修复四类提示词。
- `dependencies/rule_graph_engine.py` 已不再内联长提示词，只调用 `prompts.py` 中的 prompt builder。
- 新增 `dependencies/template_mining.py`，集中存放路径模板挖掘、候选规则构造、规则模板 LLM 命名逻辑。
- `dependencies/rule_graph_engine.py` 已移除模板挖掘类和命名函数，只保留规则构建编排、文件规则解析、规则校验。
- `read_graph_from_neo4j` 已拆成 Neo4j driver 创建、简单路径读取、规则模板命名三段。
- `validate_single_rule_v2` 已拆出语义校验/修复循环，并抽出最大轮次失败、修复失败等结果构造函数。
- 新增 `dependencies/graph_queries.py`，集中存放 Neo4j driver 创建、查询执行、简单路径查询、入口候选查询、规则路径执行、最佳子路径选择。
- `dependencies/rule_graph_engine.py` 已移除 Neo4j 查询细节，只通过 `graph_queries.py` 调用查询能力。
- `dependencies/llm_clients.py` 已集中封装 `call_qwen_max` 和 `call_qwen_small`。
- `dependencies/rule_graph_engine.py` 已移除 OpenAI SDK 和模型配置直接依赖，只通过 `llm_clients.py` 调用大模型。
- 新增 `dependencies/rule_utils.py`，集中存放 LLM JSON 解析、文件规则响应解析、规则字段归一化、关系链 Cypher 生成。
- `dependencies/rule_graph_engine.py` 已移除纯工具函数，只保留规则构建和规则校验编排。

## 向量依赖边界

- 规则模块原有的 `knowledge_base_chatbot.py`、`file_text_extractor.py` 和 `vector_store_builder.py` 副本已删除。
- 新增规则提交后调用公共 `build_rule_entity_vector_store`，根据持久化规则执行入口查询并构建对应 RID 的实体向量库。
- 图谱构建和规则构建共享 `kdzn_hciqa.engine_dependencies.embedding_service` 中的嵌入、分批重试和安全保存。
- 规则实体采集及向量库构建统一归属 `kdzn_hciqa.engine_dependencies.rule_vector_builder`；`knowledge_base_chatbot` 仅保留兼容导出。
- 问答后自动生成规则直接把新 RID、主题标签和入口查询交给公共构建器，不再回查同一行或调用 `Chatzxl.entity_vector`。

## Neo4j 依赖边界

- 规则模块原有的 `dependencies/graph_rule_queries/cypher_tool.py` 重复实现已删除。
- 页面实体查询直接使用 `vue_api.common.neo4j_client`；规则生成中的领域错误兼容由 `dependencies/graph_queries.py` 包装。
- Neo4j 查询超时、三图谱路由、驱动关闭和旧 APOC 查询参数化均由公共客户端负责。

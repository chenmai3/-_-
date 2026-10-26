# graph_construct.vue 接口归档

本目录只放 `graph_construct.vue` 页面实际触发的 Python 接口和调用链代码。

Neo4j 驱动和只读查询统一由 `vue_api.common.neo4j_client` 提供；本领域的
`dependencies/graph_rule_queries/cypher_tool.py` 只保留图数据规范化、约束创建和批量写入算法。

## 当前已迁移接口

- `api.py`
  - 暴露给前端的统一入口文件，只保留路由函数。

- `file_analysis.py`
  - 对应接口：`save_analysis_and_enterData`、`analysis_progress`、`analysis_result`。
  - 迁移链路：任务创建、任务状态缓存、原始文件相对路径保存、docx 分章解析、普通文件解析、外部三元组抽取、结果轮询。

- `graph_data.py`
  - 对应接口：`insert_new_rule`、`delete_kdzn_test_data`。
  - 迁移链路：参数兼容、表格校验、图谱入库、原始文件向量化、入口实体向量化、Neo4j 场景删除、MySQL 规则清理。
  - 入口实体向量化直接调用 `kdzn_hciqa.engine_dependencies.entity_vector_builder`，不再加载在线 RAG 聚合模块。

- `permissions.py`
  - 对应接口：`get_koqathemeWithpermission`、`get_koqascenariosWithpermission`。
  - 迁移链路：用户主题权限查询、主题下场景权限查询。

- `dependencies/`
  - 当前页面完整链路所需依赖：图谱写入、Neo4j 查询、权限查询、原始文件向量化、入口实体向量化。
  - 已裁剪掉问答检索、历史问答、无关规则搜索等不属于本页面的代码。

- `common.py`
  - 本目录公共代码：配置读取、数据库连接、路径安全处理、前端统一响应、文件解析任务状态表。

## 页面 import 但本页未直接调用的接口

`rule_generate`、`rule_submit`、`neo4j_match`、`sql_polling`、`neo4j_match_1`、`get_graph_names`、`get_koqatheme`、`get_koqascenarios`、`deleteConversationById` 暂不迁入本目录，除非后续确认页面真实触发。

## 路径策略

- 本目录新增保存路径统一从 `ko_qa_server` 服务根目录推导，不再写固定电脑盘符。
- 文件解析上传原件保存到：`ko_qa_server/graph_construct_files/{userId}_file_vectorstorges/{主题}/`。
- 运行时生成的向量库仍跟随服务根目录下的 `user_vector_stores`。

# kdzn_hciqa.vue 后端接口归档

本目录只放 `kdzn_hciqa.vue` 页面实际使用的 Python 接口和完整调用链代码。

## 目录结构

- `api.py`
  - 本页面所有 FastAPI 暴露接口入口。
- `shared.py`
  - 页面公共代码：配置路径、数据库连接、SSE 队列、历史解析/写入、模型选择、`Chatzxl` 延迟初始化。
  - 所有运行路径都从当前文件位置推导，不依赖固定盘符。
- `qa_answer/`
  - 问答流式接口。
- `document_upload/`
  - 上传文件并写入用户向量库。
- `conversation_history/`
  - 历史会话增删查。
- `speech_recognition/`
  - 语音转文本。
- `permissions/`
  - 主题权限查询。
- `standard_document/`
  - 标准生成和生成文件下载。
- `engine_dependencies/`
  - QA 引擎、图谱查询、向量库、模型客户端、prompt 构建、web 检索等页面局部依赖。

## 引擎内部边界

- `engine_dependencies/llm_clients.py`
  - 统一管理问答链路的模型客户端和消息调用，包括通义千问调用入口 `call_qwen_messages`。
- `engine_dependencies/embedding_service.py`
  - 统一管理 Qwen Embedding 客户端、重试、错误归一、维度探测和 Windows FAISS 安全保存。
- `engine_dependencies/rule_vector_builder.py`
  - 统一管理规则入口实体采集、标签纠错、RID 范围选择、规则实体向量库构建和命令行入口。
- `engine_dependencies/entity_vector_builder.py`
  - 统一管理图谱入口实体去重、主题/场景向量路径选择、空库创建和增量索引。
- `engine_dependencies/knowledge_base_chatbot.py`
  - 仅保留在线 RAG、用户知识库检索和文档增量索引；嵌入、入口实体及规则向量能力仅作兼容导出。
- `engine_dependencies/prompt_builders.py`
  - 统一管理提示词配置、领域描述读取和提示词拼装。
- `vue_api/common/neo4j_client.py`
  - 统一管理通用、轨交和家谱 Neo4j 连接、查询、超时和结果收集。
- `engine_dependencies/graph_rule_queries/family_graph_queries.py`
  - 独立管理家谱实体信息、亲属关系、字辈关系、同名人物消歧和家谱规则分派；人物输入使用参数化 Neo4j 查询。
  - 多轮人物候选和字辈状态按请求 `qid` 隔离，一小时未使用自动过期；删除历史会话时同步清理。
- `engine_dependencies/graph_rule_queries/vector_matching.py`
  - 统一管理 FAISS 检查与读取、规则实体向量库补建、规则候选嵌入匹配和通用候选相似度；规则候选每批最多 10 条。
- `engine_dependencies/graph_rule_queries/rail_graph_queries.py`
  - 管理轨交规则匹配、异常事件兜底、轨交路径抽取和固定诊断链查询。
- `engine_dependencies/graph_rule_queries/general_graph_queries.py`
  - 管理自定义主题权限标签解析、规则匹配、规则入口实体匹配及规则执行。
- `engine_dependencies/graph_rule_queries/general_query_state.py`
  - 多轮路径缓存按 `qid + 文件场景` 隔离，同一状态内串行访问，一小时未使用自动过期。
- `engine_dependencies/graph_rule_queries/tog_path_explorer.py`
  - 管理 TOG 缓存复用、入口实体向量匹配、路径方向判断、多跳扩展和并发候选探索。
  - TOG 缓存判断和逐轮路径筛选统一调用 `llm_clients.call_qwen_messages`；模型不可用时按确定性规则降级。
  - TOG 初始实体和路径扩展节点使用 Neo4j 参数，动态图标签先通过标识符白名单校验。
- `engine_dependencies/graph_rule_queries/graph_query_utils.py`
  - 管理各图查询模块共用的记录解包、路径归一化、拼音标签和节点属性工具。

旧问答 `engine_dependencies/graph_rule_queries/cypher_tool.py` 已删除。模型调用、提示词元数据和 Neo4j 查询不得再向该旧模块回流。

## 接口映射

- `ko4csg_hci`
  - 新入口：`api.py::ko4csg_hci`
  - 主逻辑：`qa_answer/graph_stream_answer.py`
  - 引擎依赖：`engine_dependencies/kdzn_graph_qa_engine.py`

- `receive_question`
  - 新入口：`api.py::receive_question`
  - 主逻辑：`qa_answer/rag_stream_answer.py`
  - 公共依赖：`shared.py::get_kochatbot`、`shared.py::get_model`、`shared.py::update_sql_history`

- `upload`
  - 新入口：`api.py::upload`
  - 主逻辑：`document_upload/user_file_vector_store.py`
  - 路径：`shared.py::USER_VECTOR_STORES_ROOT`、`shared.py::UPLOAD_FILE_ROOT`

- `speechToText`
  - 新入口：`api.py::speech_to_text`
  - 主逻辑：`speech_recognition/speech_to_text.py`
  - ASR 客户端：`speech_recognition/xfyun_asr_client.py`
  - ffmpeg 路径：优先读取环境变量 `FFMPEG_PATH`，否则使用系统 PATH 中的 `ffmpeg`

- `gen_biaozhun`
  - 新入口：`api.py::gen_biaozhun`
  - 主逻辑：`standard_document/generate_standard_document.py`
  - 标准生成引擎：`standard_document/generation_engine/`
  - BGE 模型路径：优先读取环境变量 `STANDARD_BGE_MODEL_PATH`，否则使用 `standard_document/generation_engine/bge-large-zh`

- `download_word`
  - 新入口：`api.py::download_word`
  - 主逻辑：`standard_document/download_generated_document.py`
  - 下载目录：`standard_document/generation_engine/result/`

- `get_conversations`
  - 新入口：`api.py::get_conversations`
  - 主逻辑：`conversation_history/get_conversation_detail.py`

- `getHistoryConversations`
  - 新入口：`api.py::get_history_conversations`
  - 主逻辑：`conversation_history/list_user_conversations.py`

- `upsertConversation`
  - 新入口：`api.py::upsert_conversation`
  - 主逻辑：`conversation_history/create_conversation.py`

- `deleteConversationById`
  - 新入口：`api.py::delete_conversation_by_id`
  - 主逻辑：`conversation_history/delete_conversation.py`
  - 数据库删除提交后同步清理该 `qid` 的家谱关系状态和通用图查询缓存。

- `get_koqathemeWithpermission`
  - 新入口：`api.py::get_koqatheme_with_permission`
  - 主逻辑：`permissions/theme_permission.py`

## 路径约定

- `config.yaml`：`ko_qa_server/config.yaml`
- 用户向量库：`ko_qa_server/user_vector_stores/`
- 上传文件：`ko_qa_server/upload_file_user/`
- 上传文件 JSON：`ko_qa_server/upload_files_json_all/`
- 音频临时文件：`ko_qa_server/temp_audio/`
- 标准生成结果：`vue_api/kdzn_hciqa/standard_document/generation_engine/result/`

这些路径统一在 `shared.py` 中维护。

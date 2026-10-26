# KO_QA 重构功能对齐审计报告

> 初始审计日期：2026-07-20  
> 最近更新：2026-07-24  
> 重构前：`D:\KO_QA\KO_QA\ko_qa_server`  
> 重构后：`D:\KO_QA-1\KO_QA\ko_qa_server`  
> 配套前端：`D:\KO_QA-1\KO-前端`  
> Python：`D:\anaconda\envs\KO\python.exe`

> 迁移进展：已完成二十四批整改及最终对齐复审。第 2-13 节保留整改前审计基线，当前状态以本节及第 14-37 节为准。

## 1. 审计结论

**当前判定：当前前端和生产调用范围内的代码功能迁移已经完成，可以结束继续迁移；Git 仓库交付仍需完成变更纳管、数据备份和一次正式提交。**

核心结论：

1. 单体脚本已经拆为 `kdzn_hciqa`、`jiapu_qa`、`rule_construct`、`graph_construct`、`common` 五个领域；旧 `neo4j_hpt.py`、旧问答 `cypher_tool.py` 和重复向量逻辑已经退出生产链路。
2. 家谱、轨交和通用图查询分别独立；家谱关系状态与通用 TOG 缓存均按 `qid` 隔离，删除会话时同步清理。
3. 规则 Cypher 占位符、规则实体向量库、向量路径和 FAISS 完整性检查已经统一；通用 TOG 运行时实体查询已参数化。
4. Java 代理实际调用 Python 的 51 个路径与 OpenAPI 51 / 51 对齐；轨交实体子图返回 30 / 30，家谱实体子图返回 6 / 6。
5. 标准库完整回归为 107 / 107，Python 编译、关键 Ruff、TODO/空实现、重复顶层定义、旧模块生产引用和运行日志错误扫描均为 0。
6. 829 条数据库规则中，522 条内置家谱规则按新架构不使用规则实体库；其余 307 / 307 条规则向量资产完整。
7. 代码迁移没有剩余阻断项；仓库发布阻断项是当前 699 个 Git 变更尚未形成统一提交，另外需要备份部署数据并在供应商后台轮换历史凭据。

当前进度摘要：

| 指标 | 当前结果 |
|---|---:|
| 当前生产范围功能对齐 | **100%** |
| OpenAPI 路径 | 60 |
| Java → Python 路径契约 | 51 / 51 |
| 自动化回归 | 107 / 107 |
| 核心在线探针 | 全部通过 |
| 代码迁移阶段 | 可结束 |
| Git 仓库交付 | 待纳管提交 |

## 2. 整改前审计口径与迁移率

以下数值是 2026-07-20 整改前基线，用于追溯，不代表当前进度。函数统计使用 AST，忽略注释和格式；运行率使用实际启动、HTTP、MySQL、Neo4j 和 FAISS 只读检查。

| 指标 | 结果 | 计算口径 | 判定 |
|---|---:|---|---|
| 模块/文件迁移率 | 79.5% | 35 / 44 个旧业务函数文件存在明确新归属 | 较高，但部分仅为替代或残留拷贝 |
| 函数签名迁移率 | 64.5% | 489 / 758 个旧 callable 在新版找到同名且参数数量一致实现 | 未完成 |
| 函数名称覆盖率 | 66.4% | 503 / 758 个旧 callable 在新版找到同名实现 | 未完成 |
| 函数体精确一致率 | 44.2% | 335 / 758 个旧 callable 的规范化 AST 函数体一致 | 仅作复制迁移参考 |
| 旧后端接口逻辑迁移率 | 56.5% | 约 35 / 62 个旧 FastAPI 路由同名或有明确替代入口 | 未完成 |
| 当前前后端地址兼容率 | 46.3% | 25 / 54 个前端实际目标路径可在新版找到 | 不可直接替换 |
| 核心链路完全通过率 | 40.0% | 规则列表、Neo4j 查询通过；轨交问答失败；家谱仅核心流通过；向量资产不完整 | 未达到发布门槛 |
| 综合进度 | **约 60%** | 上述模块、函数、接口、核心链路四项等权估算 | **部分迁移** |

## 3. 新架构模块说明

| 新模块 | 主要功能 | 旧代码来源 | 当前状态 |
|---|---|---|---|
| `ko_qa_server.py` | FastAPI 应用入口、挂载总路由、兼容根路径 `/neo4j_query` | `ko_qa_server.py`、`zhihaiQA_api.py` | 部分完成；缺 CORS、旧根路径兼容层，仍开启 `debug=True` |
| `vue_api/common` | 配置加载、数据库连接、统一路径、通用工具 | 多个旧脚本中的全局配置和硬编码路径 | 基本完成 |
| `vue_api/kdzn_hciqa` | 轨交/科大智能问答、LLM、向量检索、图规则查询、语音、标准文档生成 | `chatzxl.py`、`kdzn_qa.py`、`zhihai_qa/*`、`zhongshaoxuan/*` 等 | 主体已迁，关键轨交规则执行行为未对齐 |
| `vue_api/jiapu_qa` | 家谱问答 API 门面和服务编排 | `jiapu_qa.py`、旧 `zhihaiQA_api.py` 家谱接口 | 核心流可用，辅助能力大量简化/占位，旧接口未兼容 |
| `vue_api/rule_construct` | 规则列表、规则增删改、规则匹配、Neo4j 路径查询 | `rule_construct.py`、`zhihaiQA_api.py` | 主要 CRUD/查询已拆分，部分旧能力缺失，存在重复定义 |
| `vue_api/graph_construct` | 图谱文件上传、解析、批量导入、图谱构建接口 | `rule_construct.py`、旧图谱上传接口 | 部分迁移；旧接口名称和工作流未全保留 |
| `standard_document/generation_engine` | 标准文档生成、模板/图片处理及相关 API | `zhongshaoxuan/*` | 大量代码已复制迁移，但仍有 Flask 残留和未定义符号 |

## 4. 旧模块迁移清单

| 旧模块 | 新归属 | 功能 | 迁移判定 |
|---|---|---|---|
| `Ifasr_new.py` | `speech_recognition/xfyun_asr_client.py` | 讯飞语音识别 | 已迁移，接口改名 |
| `LLM_config.py` | `engine_dependencies/llm_clients.py` | 模型客户端和调用封装 | 基本迁移 |
| `build_vector_store.py` | `vector_store_builder.py` 及图谱/规则模块副本 | 文档向量库构建 | 基本迁移，但重复副本需收敛 |
| `chatzxl.py` | `knowledge_base_chatbot.py` | 文档入库、嵌入、FAISS、RAG | 基本迁移；`get_record_value`、`build_entity_docs` 未同名迁入 |
| `kdzn_qa.py` | `kdzn_graph_qa_engine.py` | 轨交图谱问答编排 | 部分迁移；部分旧入口消失 |
| `prompt_utils.py` | `prompt_builders.py` | 提示词构建 | 完整度高 |
| `web_search_api.py` | `web_search.py` | 联网检索 | 基本迁移 |
| `web.py` | 无明确新实现 | 百度/Selenium 检索 | 未迁移，可能为有意删除但未形成废弃决策记录 |
| `rule_construct.py` | `rule_construct/*`、`graph_construct/*` | 规则 CRUD、图谱构建、文件规则构建 | 部分迁移 |
| `zhihaiQA_api.py` | 各领域 `api.py`/`service.py` | 旧统一 API 门面 | 拆分完成，接口能力未完全迁移 |
| `jiapu_qa.py` | `jiapu_qa/*` + 共用图谱问答引擎 | 家谱意图、关系、合并、多问答 | 未按原功能完整迁移 |
| `zhihai_qa/cypher_tool.py` | `graph_rule_queries/cypher_tool.py` | Neo4j 连接、查询和导入 | 基本迁移 |
| `zhihai_qa/neo4j_hpt.py` | `family_graph_queries.py`、`rail_graph_queries.py`、`general_graph_queries.py`、`vector_matching.py` | 家谱/轨交/通用规则检索 | 已按领域拆分完成，旧 `neo4j_hpt.py` 已删除 |
| `zhihai_qa/ent2rule.py` | 无完整新归属 | 实体转规则 | 大部分未迁移 |
| `zhihai_qa/rel2rule.py` | 无完整新归属 | 关系转规则 | 大部分未迁移 |
| `zhongshaoxuan/*` | `standard_document/generation_engine/*` | 标准文档生成 | 迁移率高，但包含不可运行残留代码 |
| `ko_chatbot.py` | 无完整新归属 | 通用聊天/RAG/NER/关系抽取 API | 大部分未迁移 |
| `check_system.py`、`monitor_check_system.py` | 无 | 系统、API、MySQL、Neo4j 监控及告警 | 未迁移 |
| `huaPuTong.py` | 无明确新实现 | 家谱外部请求/数据预处理 | 未迁移 |
| `relation_extraction.py` | 无 | 关系抽取 | 未迁移 |

## 5. 函数迁移结论

### 5.1 高完整度函数组

- `build_vector_store.py`：14 / 15 个函数体精确一致。
- `prompt_utils.py`：7 / 7 个函数体精确一致。
- `zhihai_qa/cypher_tool.py`：60 / 70 个函数体精确一致。
- `zhihai_qa/neo4j_hpt.py`：46 / 69 个函数体精确一致，但关键轨交增强逻辑缺失。
- `zhongshaoxuan` 标准文档生成函数多数已复制到 `standard_document/generation_engine`。

### 5.2 低完整度函数组

| 旧文件 | 精确一致数 | 旧 callable 数 | 说明 |
|---|---:|---:|---|
| `jiapu_qa.py` | 1 | 25 | 新家谱层主要改成门面和共用引擎，旧意图/关系/答案合并逻辑未完整保留 |
| `zhihaiQA_api.py` | 12 | 141 | API 已拆层，但大量旧接口和服务函数消失或改名 |
| `rule_construct.py` | 15 | 88 | CRUD、图谱、文件处理只迁移部分 |
| `kdzn_qa.py` | 3 | 12 | 核心编排被重写，旧入口和处理函数缺失 |

### 5.3 重点未同名迁移函数

以下列表覆盖需要人工确认的主要业务函数；自动扫描共发现 255 个旧 callable 无同名新版实现，其中还包含局部辅助函数和已改名实现。

- 家谱：`splitChenshuWenti`、`mergeAns`、`merge_ans_choice`、`merge_ans_choice_multiQA`、`extra_name_from_q`、`judgeYitu`、`judgePerRel`、`check_lemma_id_exists`、`get_description_by_name`、`analysis_wenti`、`rel_stream`、`per1_stream`、`per2_stream`、`per3_stream`、`toushiti_stream`、`get_path_inKO_byQuest_multiQA_stream`、`check_init_state`、`init_rule`、`add_to_allRelsTris`。
- 轨交：`csg_port`、`csg_no_chat`、`csg_event_port`、`kdzn_select.process_results_1`、`kdzn_select.process_results`、`kedazhineng`。
- 通用问答：`chat2kb`、`chat2url`、`get_relation`、`relations_extraction`、`get_question_type`、`extract_terms`，以及 `ko_chatbot.py` 中 19 / 21 个 callable。
- 规则/图谱构建：`sql_update`、`insert_graph`、`delete_graph_data`、`rule_construct`、`file_rule_construct`、`vectorize_original_file_by_existing_code`，以及旧 `Neo4jQueryBuilder` 的部分方法和路径模糊匹配辅助函数。
- 系统能力：`send_alert_email`、`check_api`、`check_db`、`check_neo4j`、`check_system`、监控调度函数。
- 旧联网检索：`web.py` 全部 16 个 callable。
- 规则生成：`zhihai_qa/ent2rule.py` 9 / 10、`rel2rule.py` 18 / 20 个 callable 未找到同名实现。
- 其他：`huaPuTong.pro_data`、`huaPuTong.request_hpt`、`relation_extract`、`zhongshaoxuan.input_process`。

**判定：函数没有全部迁移完成。** 改名或重写函数必须逐项补充“旧函数 -> 新函数 -> 测试用例”的追踪关系，不能仅凭目录存在认定迁移完成。

## 6. 接口对齐审计

### 6.1 后端路由

- 旧 FastAPI 活跃路由：62 个；旧标准文档 Flask 另有 4 个活跃路由。
- 新 FastAPI OpenAPI 路径：44 个。
- 旧 FastAPI 路由中约 30 个方法和末级路径直接对应；计入明确改名/组合实现后约 35 / 62，对齐率 56.5%。
- `/neo4j_query`、`/api/neo4j_query`、`/api/rule/neo4j_query`、`/api/graph/neo4j_query` 当前均有入口。
- `/api/rule/sql_polling` 当前同时返回 `data` 和 `results`，已兼容 Java 前端读取 `results` 的行为。

### 6.2 当前前端仍调用但新版缺失的主要路径

`/add_koqatheme`、`/add_theme_permission`、`/api/graph/analysis_progress`、`/api/graph/analysis_result`、`/chat`、`/chat2kb`、`/chat2url`、`/deepseek_hci`、`/del_koqatheme`、`/del_permission`、`/enterDataWithFile`、`/extract_tri`、`/getByWeb`、`/getHPTById`、`/getHuaPUDaMoXingAnswer`、`/getStage`、`/get_koqascenarios`、`/get_koqatheme`、`/has_permissiontoadd`、`/judgeYitu`、`/ko_kg_mul_qa`、`/ko_kg_mul_qa_check`、`/ko_kg_mul_qa_stream`、`/mergeAnsMul`、`/normalAns`、`/rule_submit`、`/save_analysisFile`、`/splitChenshuWenti`，以及旧流式根路径 `/`。

其中多项家谱接口在新版存在 `/api/jiapu_qa/*` 等价名称，但 Java 前端没有同步改地址。因此“新接口存在”不等于“当前页面可用”。

## 7. 配置与路径审计

### 7.1 已完成

`vue_api/common/paths.py` 已统一管理并支持环境变量覆盖：

- 服务根目录和 `config.yaml`
- 用户向量库根目录
- 实体向量库和家谱实体向量库
- 规则实体向量库 `rule_entity_vector_store_kdzn`
- 上传、图谱构建、音频临时目录
- `entity_vector_store_path()`、`rule_entity_vector_store_path()` 路径生成函数

新版 Python 和配置中未检出 `D:\KO_QA\...` 等旧工程绝对路径。新旧 `requirements.txt` 一致；配置结构仅少了 `qa_models.qwen.qwen3-30b-a3b`，其余非敏感配置结构基本对齐。

### 7.2 未完成或有风险

- 新工作区缺少 `user_vector_stores`、`entity_vector`、`upload_file_user`、`upload_files_json_all`、`graph_construct_files`；知识库/RAG 会跳过这些资产。
- `config.yaml` 仍保存数据库、Neo4j、模型平台的明文凭据。作为新代码仓库发布前必须改为环境变量或密钥管理，并立即轮换已经进入旧仓库历史的凭据。
- `.gitignore` 已忽略运行数据目录，这是正确方向，但必须提供初始化脚本、目录自建逻辑和部署数据清单。

## 8. 向量库审计

### 8.1 文件完整性

- 新规则实体向量库共有 283 个 RID 目录。
- 279 个目录同时存在 `index.faiss` 和 `index.pkl`。
- 4 个空目录：RID `56`、`592`、`603`、`604`。
- 279 个完整 FAISS 索引均能被原生读取，维度统一为 1024，未发现损坏或零向量索引。
- 旧规则实体向量库有 197 个目录，均存在成对索引文件。

### 8.2 与当前数据库规则对齐

- `轨交诊断/kedazhineng` 当前有 157 条规则。
- 其中 154 条有完整 RID 向量库。
- 当前缺失 RID：`56`、`592`、`4326`；前两个目录为空，`4326` 目录不存在。
- `家谱问答/huaputong` 有 522 条规则，但没有逐 RID 规则实体向量库。当前家谱核心链路主要依赖规则/图谱查询，不宜简单将 522 个目录全部判为缺陷，但部署设计必须明确它是否需要单独向量化。

**判定：向量库不是“全部为空”。大部分轨交索引有效，但数据覆盖不完整，且运行链路另有 Cypher 渲染缺陷。**

## 9. 运行态验证结果

审计时以 `127.0.0.1:8998` 临时启动新版服务，仅执行读取和问答验证。

| 测试 | 结果 | 证据/说明 |
|---|---|---|
| 应用启动 | 通过 | OpenAPI 返回 200，共 44 个路径；启动约 15 秒，工作集约 615 MiB |
| Python 语法编译 | 通过 | 97 个新版 Python 文件，0 个语法错误 |
| `/api/rule/sql_polling` 轨交诊断 | 通过 | 200；`data=157`、`results=157`、标签 `kedazhineng` |
| `/api/rule/sql_polling` 家谱问答 | 通过 | 200；522 条、标签 `huaputong` |
| 根 `/neo4j_query` 轨交 | 通过 | 200；“油浸式电力变压器试验”返回 30 条路径/三元组 |
| 根 `/neo4j_query` 家谱 | 通过 | 200；“罗泽南”返回 6 条路径/三元组 |
| `/api/rule/neo4j_match` | 通过 | 200；家谱只读查询返回 2 个匹配项 |
| 家谱核心流式问答 | 部分通过 | 新路径 `/api/jiapu_qa/ko_kg_mul_qa_stream` 对“罗泽南的儿子是谁”检索图谱并回答“罗允吉” |
| 家谱旧前端路径 | 失败 | 根 `/ko_kg_mul_qa`、`/judgeYitu` 等返回 404 |
| 家谱辅助接口 | 失败 | `/api/jiapu_qa/judgeYitu`、`extract_triplets` 返回 500 |
| 轨交核心问答 | 失败 | 规则和实体匹配成功，但路径及 `KO_context` 为空，最后退化为通用模型回答 |
| 规则实体 FAISS | 部分通过 | 279 个索引可读；当前轨交规则缺 3 个 RID |
| 用户文档 RAG | 未通过 | 运行日志显示标准化和旧兼容路径均无用户向量资产 |

## 10. 关键缺陷与直接原因

### P0：仓库不可发布

1. **新版主体未被 Git 跟踪。** `vue_api/` 当前为 untracked，旧逻辑则大量处于删除状态。若直接提交不完整暂存区，可能得到一个没有新版主体的仓库。
2. **配置包含明文凭据。** 新仓库不能在保留真实密码/API Key 的情况下发布；必须迁移到环境变量并轮换。

### P1：核心功能不对齐

1. **轨交规则 Cypher 占位符迁移不完整。**
   - 数据库 RID 2401 的 `rulepath` 使用 `{r2name}`。
   - 新版 `neo4j_hpt.py:1007` 只执行 `cypher.replace("{entityname}", match_ent)`。
   - 因此 `{r2name}` 未被替换，Neo4j 查不到路径，`kdzn_graph_qa_engine.py:715-731` 得到空 `state.paths` 和空上下文。
   - 旧版 `neo4j_hpt.py:999-1050` 已有 `render_cypher()`，支持 `{r1name}`、`{r2name}`、`{riname}`、`{partname}`、`{cyclename}`、`{itemname}`、`{faultname}`、`{phenomenon}`、`{entityname}` 等变量；这段能力没有迁入新版。
2. **家谱前端和新版路由未对齐。** 新后端使用 `/api/jiapu_qa/*`，当前 Java 仍调用根路径，核心页面直接 404。
3. **家谱辅助接口统一返回模型错误。** `jiapu_qa/service.py:25` 总是传入 `errorMessage=None`，而 `shared.py:49` 声明为 `str`；当前 Pydantic 版本拒绝显式 `None`，导致多个接口 500。
4. **家谱辅助能力是占位实现。** `extract_tri`/`extract_triplets` 返回空三元组，`mergeAns`/`mergeAnsMul` 只选输入，`getStage` 固定返回 1，`ko_kg_mul_qa_check` 固定返回 `ready`，与旧业务逻辑不等价。
5. **轨交向量覆盖不完整。** RID 56、592、4326 缺完整索引，命中时会触发在线生成或失败；在线生成又受模型额度、网络和目录权限影响。

### P2：代码质量和稳定性

1. Ruff `F811/F821/F822/F823` 检查发现 24 个问题。
2. `kdzn_graph_qa_engine.py:536` 在 `return` 后引用未定义 `results`，属于不可达残留代码。
3. 重复定义会静默覆盖前一个实现：`rule_repository.py:55/87 handle_sql_polling`、`neo4j_def.py:175/218 KO_tupu`、`neo4j_hpt.py:743/830 get_best_match`。
4. 标准文档 `server.py` 残留 Flask 代码，引用未导入的 `pymysql`、`request`、`Response`、`jsonify`、`send_file`、`send_from_directory`。
5. `shared.py` 存在重复字段声明；入口仍为 `FastAPI(debug=True)`，生产环境可能暴露堆栈。
6. 新入口未迁移旧版 CORS 配置。若浏览器绕过 Java 代理直连 Python，会产生行为差异。
7. 启动阶段导入较重，审计机上约 15 秒、615 MiB；需要按需加载模型/引擎。

### P3：工程治理

1. 新版 Python 未发现字面 `TODO`、`FIXME`、`NotImplementedError`，但存在大量逻辑占位、死代码和静默异常兜底；不能据此认为没有 TODO。
2. 未发现覆盖接口契约、规则模板、向量库和核心问答链路的自动化测试。
3. 缺迁移追踪表、接口废弃清单、部署数据清单和回滚说明。

## 11. 数据源连通性

| 数据源 | 审计结果 |
|---|---|
| MySQL | 可连接；`ko_kdzn_rule_construct` 共 829 条，轨交 157 条、家谱 522 条；`ko_theme_permission` 80 条 |
| Neo4j default/家谱 | 可连接，可查询 `huaputong` 节点 |
| Neo4j kdzn/轨交 | 可连接，可查询 `kedazhineng` 节点和路径 |
| Neo4j new_kdzn | 可连接，但抽样未查到 `kedazhineng` 节点；需确认它是否仍是目标库 |
| FAISS 规则实体库 | 279 个完整索引均可读取，维度 1024 |
| 用户/主题向量资产 | 新工程目录缺失，未达到部署完整状态 |

## 12. 建议整改顺序与验收标准

### 第一批：恢复可用性

1. 将旧版 metadata 向量检索和 `render_cypher()` 按新路径架构迁入，不恢复其中的硬编码 `VECTOR_ROOT`。
2. 为数据库现存规则模板收集全部占位符，建立白名单渲染器和参数化测试；未知占位符必须显式报错，不能静默查询为空。
3. 修复 `Result.errorMessage` 为可空类型，删除重复字段；逐个实测所有家谱辅助接口。
4. 统一前端调用到 `/api/jiapu_qa/*`，或在后端增加带弃用标记的旧根路径兼容路由。

验收：

- “变压器发出吱吱声，如何处理”必须命中 RID 2401，生成的 Cypher 不含 `{...}`，返回非空路径和 `KO_context`，答案引用图谱原因/处理方法。
- 当前前端家谱页面不再出现 404；`judgeYitu`、`extract_triplets` 等接口不再 500。
- 家谱辅助接口输出需与旧版固定样例逐字段对齐，不能仅返回空数组或固定状态。

### 第二批：补齐资产和接口

1. 重建 RID 56、592、4326；生成后验证成对文件、维度、文档数和一次真实检索。
2. 明确 `user_vector_stores`、`entity_vector` 等目录是部署资产还是可重建缓存，并提供初始化/迁移脚本。
3. 对 24 个前端缺失路径逐项选择：迁移、前端改址、兼容别名或正式废弃；每项必须有验收结果。
4. 对家谱旧 25 个 callable、规则构建旧 88 个 callable 做业务级人工归并，形成函数追踪矩阵。

### 第三批：仓库收口

1. 清理重复定义、Flask 残留、不可达代码和宽泛异常吞噬。
2. 将凭据移出 `config.yaml` 并轮换；提交 `.env.example` 或配置说明，不提交真实值。
3. 增加最小自动化套件：OpenAPI 契约、MySQL 规则读取、Neo4j 双场景查询、FAISS 加载/检索、轨交问答、家谱问答、前端代理路径。
4. 审核 Git 暂存区和未跟踪文件，确认新版主体、迁移文档和必要初始化脚本均进入仓库，运行数据仍保持忽略。

发布门槛建议：

- P0/P1 缺陷为 0。
- 前端实际路径兼容率 100%，或所有废弃路径有已批准清单。
- 核心链路测试 100% 通过。
- 当前数据库有效轨交规则的向量资产覆盖率 100%。
- 配置扫描无真实凭据，Git 工作区不存在遗漏的新版源码。

## 13. 最终问答

| 问题 | 回答 |
|---|---|
| 重构完成了吗？ | **没有，约 60%，属于部分迁移。** |
| 模块是否已经拆分？ | **是，领域拆分基本完成。** |
| 模块功能是否完全迁移？ | **否。家谱辅助能力、通用问答、监控、旧 Web 检索、部分规则/图谱构建能力未完整迁移。** |
| 函数是否全部迁移？ | **否。签名级覆盖约 64.5%，有 255 个旧 callable 未找到同名实现。** |
| 接口是否对齐？ | **否。旧后端逻辑迁移约 56.5%，当前前后端地址完全兼容率约 46.3%。** |
| 代码功能是否正常运行？ | **部分正常。规则列表和 Neo4j 查询正常；家谱核心流可用；轨交核心上下文、家谱辅助接口和旧前端路径存在阻断。** |
| 向量库路径统一了吗？ | **基本统一，但部署资产没有完全迁移，部分旧增强逻辑仍含历史硬编码且尚未迁入。** |
| 规则实体向量库是空的吗？ | **不是。279 个索引完整可读；轨交当前缺 3 个 RID，核心空结果的主要原因是规则占位符未渲染。** |
| 是否存在 TODO？ | **没有显式 TODO 标记，但存在实质 TODO：占位实现、死代码、重复定义、接口缺失和测试缺失。** |
| 可以直接删除旧项目并发布新版吗？ | **不可以。应先完成 P0/P1 整改和回归验收。** |

## 14. 迁移执行记录

### 2026-07-20：第一批 P1 可用性整改

已完成：

1. 新增 `graph_rule_queries/rule_template.py`，统一保存入口实体的 `R1Name/R2Name/RIName` 元数据并渲染规则模板。
2. 支持 `{entityname}`、`{itemname}`、`{partname}`、`{phenomenon}`、`{r1name}`、`{r2name}`、`{riname}`，同时保留旧增强逻辑使用的其他别名；未知占位符会抛出明确错误。
3. `find_kdzn()` 不再只替换 `{entityname}`，而是从 FAISS 命中文本恢复完整实体元数据后执行渲染后的 Cypher。
4. 修复 `Result.errorMessage` 的可空类型和重复 `response` 字段，兼容当前 Python 3.9/Pydantic 环境。
5. 将 Java 控制器中 8 个已有新版实现的家谱调用切换到 `/api/jiapu_qa/*`。
6. 新增 4 个标准库 `unittest`，覆盖响应模型、模板渲染、别名、转义和未知占位符拒绝行为。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 4 / 4 通过 |
| 新版 Python 语法编译 | 通过 |
| 本批文件 Ruff `F821/F822/F823` | 通过 |
| 数据库 157 条轨交规则模板扫描 | 7 种实际占位符全部支持，未知占位符 0 |
| RID 2401 轨交端到端 | 200；`{r2name}` 已替换；Neo4j 返回 2 条路径；回答读取规则知识 |
| 家谱 6 个辅助接口 | 均由 500 恢复为 200 |
| 家谱核心流式问答 | 200；“罗泽南的儿子是谁”命中图谱并包含“罗允吉” |
| 前后端实际地址兼容率 | 从 25 / 54（46.3%）提升到 33 / 54（61.1%） |

本批尚未完成：

- `extract_tri`、`extract_triplets`、`mergeAns`、`mergeAnsMul`、`getStage`、`ko_kg_mul_qa_check` 虽已不再 500，但仍是简化实现，尚未达到旧版行为对齐。
- 仍有 21 个 Java -> Python 目标地址不能直接命中新版路由。
- RID 56、592、4326 的向量资产仍缺失。
- 用户文档向量资产、Git 纳管、凭据治理、重复定义和标准文档 Flask 残留尚未处理。

下一批优先级：完整迁移家谱辅助逻辑和状态管理，随后处理剩余前端接口与缺失向量资产。

## 15. 第二批迁移执行记录

### 2026-07-20：家谱辅助逻辑与状态管理

已完成：

1. 新增 `jiapu_qa/domain.py`，将旧单体中的陈述/问题拆分、代词消解、三元组抽取、多源答案合并和多轮消息合并迁入独立领域层。
2. 领域层优先使用新版 Qwen 客户端获取结构化 JSON；模型异常、返回非 JSON 或服务不可用时，使用确定性解析回退，不再返回固定空数组。
3. 三元组结果统一为 `[头实体, 关系, 尾实体]`，`extract_triplets` 会过滤含未知项 `？` 的三元组生成 `know_tri`。
4. 多源合并对陈述、图谱、网页条目统一去重编号，只允许返回真实存在于输入中的引用条目；多轮接口保留原历史并追加 assistant 回答。
5. 新增线程安全的 `FamilySessionStateStore`，按 `qid/session_id` 隔离 `processing/completed/failed` 状态，并自动淘汰超过 24 小时的记录。
6. 家谱流式和非流式问答已接入状态存储；流完成、异常和客户端断开均会更新状态。
7. `parse_history()` 增加单个消息对象兼容，修复单元素历史 JSON 被解析为空的问题。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 12 / 12 通过，其中第二批新增 8 个 |
| Python 语法编译 | 通过 |
| 家谱模块 Ruff `F401/F821/F822/F823` | 通过 |
| `splitChenshuWenti` | 200；正确拆出陈述，并将“他的儿子”消解为“罗泽南的儿子” |
| `extract_tri` | 200；返回 `罗泽南-儿子-罗允吉` |
| `extract_triplets` | 200；`triples` 和 `know_tri` 均返回有效三元组 |
| `mergeAns` | 200；返回包含“罗允吉”的答案及实际引用条目 |
| `mergeAnsMul` | 200；保留 user 历史并追加 assistant 答案 |
| 会话阶段轮询 | 流进行时为 `stage=0/processing`，完成后为 `stage=1/completed` |
| 家谱核心流回归 | 200；图谱路径和“罗允吉”答案仍正常 |

第二批完成后，第一批遗留的 6 个家谱占位接口已具备实际业务行为。仍需后续处理：

- `judgeYitu` 当前为确定性家谱关键词分类，尚未覆盖旧版模型支持的全部意图类别。
- `normalAns`、华谱通外部接口及其余 21 个前端目标地址仍未完全迁移。
- RID 56、592、4326、用户文档向量资产和仓库治理问题未处理。

下一批优先级：处理剩余前端接口，先迁移 `normalAns`、主题/权限接口和图谱分析任务查询，再对外部华谱通与旧 Web 能力作迁移或正式废弃决策。

## 16. 第三批迁移执行记录

### 2026-07-20：普通问答、主题权限与前端接口对齐

已完成：

1. 新增 `NormalAnswerService`，将旧 `/normalAns` 的最后问题提取、Qwen 流式调用和 SSE 输出迁入 `jiapu_qa` 领域；正式地址为 `/api/jiapu_qa/normalAns`。
2. 修复共用 Qwen 流客户端硬编码过期模型 `qwen2-72b-instruct` 的问题，默认模型改为读取 `small_models.qwen.qwen2_model_name`；真实请求已恢复。
3. 新增 `rule_construct/theme_repository.py`，集中实现主题/场景查询、管理员与创建者删除权限、授权人员新增权限、主题场景新增和删除。
4. 主题新增使用单连接事务完成查重、主题描述复用和写入；内置主题标签稳定为 `kedazhineng`、`huaputong`，自定义主题按创建人隔离标签。
5. 新增 `/api/rule/get_koqatheme`、`get_koqascenarios`、`has_permissiontoadd`、`add_theme_permission`、`del_permission`、`del_koqatheme` 六组正式入口；原有两个带权限查询改用新仓储，不再依赖复制的旧 `kdzn_rule_ent.py`。
6. Java 代理统一改到 `/api/rule/*` 和 `/api/jiapu_qa/*`；旧 `add_koqatheme` 转发到唯一的主题权限新增入口，旧 `rule_submit` 转发到 `new_rule_submit`。
7. 修正规则界面遗漏的 `/neo4j_query` 根路径，现统一调用 `/api/rule/neo4j_query`。
8. 确认 `/api/graph/analysis_progress/{task_id}`、`analysis_result/{task_id}` 已存在且 Java 动态 URL 正确；此前清单中的两项缺失属于静态扫描误报。
9. 删除 `handle_sql_polling` 的不可达重复定义、规则领域未被引用的 `kdzn_rule_ent.py` 副本，以及本批确认无引用的导入。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 17 / 17 通过，本批新增 5 个 |
| Python 语法编译 | 通过 |
| 本批文件 Ruff `F401/F821/F822/F823` | 通过 |
| `normalAns` 假客户端契约测试 | 只发送最后一条 user 问题，按 `data: ...\n\n` 输出 |
| `normalAns` 真实模型回归 | 200；`text/event-stream`；“1+1”分片返回 `1`、`+1=`、`2` |
| 轨交主题场景查询 | 200；当前数据库返回 29 个场景，包含“声音异常检查” |
| 新增权限判断 | 200；用户 `6000971` 对“声音异常检查”返回 `true` |
| 删除权限判断 | 200；用户 `6000971` 对“声音异常检查”返回 `true` |
| 主题场景写入/删除 | 临时记录创建成功并由新接口删除，最终数据库残留 0 |
| 图谱任务动态路由 | 两个 `{task_id}` 路由均存在于 OpenAPI |
| 前端字面目标路径兼容率 | 45 / 54（83.3%），从首轮基线 25 / 54 提升 20 个调用点 |

当前仍有 9 个 Java 字面目标路径未迁移：

`/deepseek_hci`、`/getByWeb`、`/getHuaPUDaMoXingAnswer`、`/getHPTById`、`/chat`、`/chat2kb`、`/chat2url`、`/enterDataWithFile`、`/save_analysisFile`。

其中前三组分别涉及旧模型入口、旧 Web 检索和华谱通外部服务；后三组涉及通用聊天/RAG 和旧文件入图流程。下一批应先做业务归属和依赖可用性判断，再选择迁移到现有领域、实现新服务或正式废弃。

全项目 Ruff 仍报告 13 个既存 `F821`：`kdzn_graph_qa_engine.py` 的 `results` 一处，以及标准文档 `generation_engine/server.py` 的 Flask/MySQL 残留 12 处。本批文件无新增静态错误，这 13 项列入下一批代码可运行性清理。

## 17. 第四批迁移执行记录

### 2026-07-20：剩余接口、外部服务与死代码收口

已完成：

1. 新增 `general_qa` 领域，正式提供 `/api/general_qa/chat`、`chat2kb`、`chat2url`；普通问答使用当前 Qwen 配置，知识库问答使用本地用户 FAISS 与 Whoosh 资产，URL 问答严格依据抓取正文回答。
2. URL 问答只允许可解析的公网 HTTP/HTTPS 地址，拒绝本机和内网 IP，限制响应内容为 2 MiB、正文为 30000 字符，并清除脚本与样式内容。
3. 新增 `/api/kdzn_qa/deepseek_hci`，恢复按 `qid` 隔离历史的可选模型 SSE 直答；修复 `Qwen` 仍映射到失效 `qwen-turbo-1101` 的问题，改用配置中的 `qwen-max`。
4. 新增家谱外部来源层，提供 `/api/jiapu_qa/getByWeb`、`getHuaPUDaMoXingAnswer`、`getHPTById`。华谱通任务不再使用跨请求全局变量，并能解析 JSON 后附带 HTML、回答中含原始换行的响应。
5. 网页补充检索优先使用 DashScope 应用，权限失效或无结果时自动回退到 DDG；未恢复旧 Selenium 浏览器抓取代码。
6. 将 `/enterDataWithFile`、`/save_analysisFile` 收敛到 `graph_construct`，复用当前上传、FileAnalysis、GraphConstruction 和三元组结果格式化函数。
7. 适配外部 GraphConstruction 新增的必填 `graphStructure` 字段；该修复同时覆盖文本图谱抽取和组合文件分析任务。
8. Java 控制器中最后 9 个旧根路径全部改到新领域地址；`chat2kb` 增加可选 `userId` 转发。
9. 删除标准文档模块中无调用方的 Flask `request/Response/jsonify/send_file` 路由、重复会话存储和 SQL 历史逻辑；删除轨交引擎 `return` 后的不可达变量引用。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 27 / 27 通过，本批新增 10 个 |
| Python 语法编译 | 通过 |
| 全项目 Ruff `F821/F822/F823` | 通过，未定义符号从 13 降至 0 |
| 本批文件 Ruff `F401` | 通过；标准文档另清理 11 个无用导入 |
| OpenAPI 路径 | 60 个 |
| Java 字面目标路径兼容率 | 54 / 54（100%） |
| Java 全部 Python 调用点 | 56 / 56 可匹配，包括 2 个裸根地址调用 |
| 通用聊天真实回归 | 200；“1+2”正确回答 3 |
| URL 问答真实回归 | 200；读取 `example.com` 后正确回答页面标题 |
| 多模型流真实回归 | 200；Qwen SSE 对“1+3”返回 4 |
| 网页补充检索 | DashScope 应用返回 403 后成功切换 DDG并返回搜索内容 |
| 华谱通按 ID 查询 | 200；无效 ID 被解析为 `flag=0/gotAns=false`，未触发异常 |
| 文本图谱抽取 | 200；“罗泽南的儿子是罗允吉”返回 3 条结构化关系 |
| 文件上传解析 | 200；测试文本文件经上传和 FileAnalysis 返回正文 |
| 在线服务 | `127.0.0.1:8998`，PID `13944`，9 个新增路由均已加载 |

仍未完全可运行的项目：

- `chat2kb` 的代码链路已迁移，但新版 `user_vector_stores` 不存在；调用会明确返回 `status=404`。需要由上传接口重新构建或从部署资产恢复后才能完成成功问答验收。
- 旧远端公共知识库 `http://ko.zhonghuapu.com:5500/v1/query2kb` 当前实测为 502，新版不再依赖它。
- DashScope 搜索应用当前返回 403，DDG 回退可用；应更新 `dashscope_application.app_id` 授权后恢复主通道。
- 华谱通完整“提交并轮询到最终答案”未使用真实业务账号发起，当前仅完成解析单测、无效 ID 查询和并发安全重构。
- 全项目仍有约 45 个 `F401`，主要是 `shared/common` 为复制依赖保留的重导出和旧标准文档文件的无用导入；未定义符号已清零，但导入边界仍需继续收敛。

下一批优先级：恢复用户知识库资产并完成 `chat2kb` 成功回归；重建 RID 56、592、4326；随后处理配置凭据、剩余重导出和 Git 纳管。

## 18. 第五批迁移执行记录

### 2026-07-20：用户知识库恢复与规则向量资产治理

已完成：

1. 新增 `common/vector_assets.py`，统一检查 FAISS 完整性、真实维度和文档数；当前维度由 `KO_QA_EMBEDDING_DIMENSION` 管理，默认 1024。
2. 新增 `scripts/manage_vector_assets.py`，支持审计用户向量库、从旧服务迁移兼容索引并同步上传源文件；迁移采用临时目录校验后切换，不覆盖非空的不完整目标目录。
3. 扫描旧用户库后确认只有 `6000701` 与当前模型兼容；已迁移其 1024 维、191 条 FAISS 文档和 8 个上传源文件。`1111`、`1123`、`123456`、`undefined` 的旧索引为 1536 维，已拒绝直接加载，其上传源文件已保留供重建。
4. 旧 Whoosh 索引序列化了已删除模块 `chatzxl.JiebaTokenizer`。新增稳定公共分词器和关键词索引重建函数，已从 FAISS docstore 重建 `6000701` 的 191 条关键词索引，不再需要旧 `chatzxl.py` 兼容垫片。
5. `chat2kb` 资产检查现在同时校验 FAISS 文件、1024 维度和 Whoosh 目录，避免将不兼容旧库误判为可用；FAISS + Whoosh 双路检索已生成包含真实知识片段的 RAG 提示。
6. 将规则向量生成拆为数据库规则读取、Neo4j 记录归一化、实体文本提取、单 RID 构建和批量调度；保留 `vector_generate` 兼容入口，并新增可重复的 `--rid`、`--all`、`--force` 命令行参数。
7. 修复 Neo4j `Record` 被误当元组拆解导致实体列表为空的问题；修复百炼嵌入接口每批最多 10 条的限制，26 条规则实体会自动按 `10 + 10 + 6` 分批。
8. 已定点补建 RID 56、592、4326。前两者各为 1024 维、1 条，RID 4326 为 1024 维、26 条，三者均可由 LangChain FAISS 真实加载和相似检索。
9. 当前数据库 157 条“轨交诊断”规则已达到 `157/157` 向量资产完整；农业 QA、杨梅、杨梅与土豆、轨交诊断1、遥测越限故障诊断也已完整。522 条“家谱问答”按新架构不使用规则实体向量库。
10. 清理 20 个业务文件中的确定性无用导入；全项目 `F401` 从约 45 降至 25，剩余均为 `shared/common` 公共重导出和一个包级公开符号。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 34 / 34 通过，本批新增 7 个 |
| Python 语法编译 | 通过 |
| 全项目 Ruff `F821/F822/F823` | 通过，保持 0 |
| 全项目 Ruff `F401` | 25，均为明确保留的公共重导出 |
| 用户库资产审计 | `6000701`：1024 维、191 条，FAISS 与 Whoosh 均可加载 |
| 规则库资产审计 | 轨交诊断 157 / 157 完整；RID 56、592、4326 实际检索通过 |
| `chat2kb` 真实 HTTP 回归 | 200；依据本地“向量库本地构建流程”文档返回有来源约束的回答 |
| 待实现标记扫描 | `TODO/FIXME/NotImplementedError` 为 0 |
| 在线服务 | `127.0.0.1:8998`，PID `8004`，OpenAPI 60 条路径 |

常用命令：

```powershell
# 审计用户向量库
D:\anaconda\envs\KO\python.exe scripts/manage_vector_assets.py audit

# 从旧服务迁移兼容用户库并同步上传源文件
D:\anaconda\envs\KO\python.exe scripts/manage_vector_assets.py migrate-users `
  --source-server "D:\KO_QA\KO_QA\ko_qa_server" --copy-uploads

# 定点补建规则实体向量库
D:\anaconda\envs\KO\python.exe `
  vue_api/kdzn_hciqa/engine_dependencies/knowledge_base_chatbot.py `
  --rid 56 --rid 592 --rid 4326
```

仍需后续处理：

- 用户 `1111`、`1123`、`123456`、`undefined` 的旧 1536 维索引不能迁移，需要用已复制的上传源文件在当前 1024 维模型下重建；`1123` 原库本身为空且没有源文件。
- “农作物”2 条和“医疗数据集”29 条规则尚无预生成向量资产；在线规则链路支持命中时懒构建，也可在确认外部嵌入调用成本后使用 `--rid` 或 `--all` 预热。
- `config.yaml` 仍包含数据库、Neo4j 和外部模型真实凭据。进入正式代码仓库前必须迁移到不纳管的本地/环境配置，并轮换当前已出现过的全部密钥；仅把字符串替换为空会让现有服务静默失效，因此本批未做破坏性伪清理。
- 旧版 1536 维用户索引不应通过修改 `KO_QA_EMBEDDING_DIMENSION` 强行启用，因为查询嵌入仍由当前 1024 维模型生成。
- 当前重构服务关键文件相对父 Git 仓库仍为未跟踪状态，父仓库同时存在大量旧逻辑删除记录。应在凭据迁移完成后按审计清单精确暂存，不应直接执行全目录 `git add`。

## 19. 第六批迁移执行记录

### 2026-07-20：旧用户库重建、规则资产补全与配置脱敏

已完成：

1. 新增用户知识库安全重建服务和 `rebuild-users` 命令。全部源文件先在临时目录完成文本提取、FAISS、`doc_rangs.json` 和 Whoosh 构建，维度与文档数校验通过后再原子安装；默认不覆盖已有目标，可显式使用 `--replace`。
2. 修复日常上传每次调用 `create_in` 覆盖 Whoosh 的问题。现在文件加入 FAISS 后，会依据完整 docstore 重建关键词索引，多文件用户不会只剩最后一份文件。
3. 用户重建支持解析缓存复用、逐文件失败/跳过报告、远端文件解析超时、嵌入请求超时、429/5xx 单层退避和 API 每批 10 条限制；关闭 SDK 内部重试，避免两层重试叠加成长时间假死。
4. 对纯文本源增加默认 2 MiB 上限。遗留 `undefined` 用户中的 8.5 MiB 数值矩阵和不受旧系统支持的 `Chat.vue` 被明确跳过，避免生成 6147 条无意义知识分片。
5. 完成旧用户库重建：`1111` 为 1024 维、1 条有效 OCR 内容；`123456` 为 1024 维、23 条，与旧库一致；`undefined` 为 1024 维、3 条，与旧库内容逐条对齐；`6000701` 保持 1024 维、191 条。`1123` 的旧库为 0 条且没有上传源文件，因此不创建空知识库。
6. 三个重建用户均通过真实 FAISS + Whoosh 双路检索，分别命中“中科国金”、城市轨道交通维护办法和“曾国藩的儿子”。重启后 `123456` 的 `/api/general_qa/chat2kb` 真实请求返回 `status=200`。
7. 补建“医疗数据集”RID 4327-4355 共 29 个规则实体库，当前该主题达到 `29/29` 完整。“农作物”RID 603/604 的 Neo4j 入口查询均为空，未生成伪空索引，归类为图谱数据阻断。
8. 新增 `config.local.yaml` 私密配置机制：存在时自动优先读取，也可由 `KO_QA_CONFIG_PATH` 覆盖；该文件和 `.env` 已加入 `.gitignore`。
9. 仓库内 `config.yaml` 已脱敏为结构模板，数据库、Neo4j、模型、语音和文件解析凭据字段全部清空。讯飞 ASR 凭据和 DashScope 搜索应用 ID 不再硬编码，改从本地配置或环境变量读取。
10. 新增 `CONFIGURATION.md`，记录本地配置、外部服务覆盖变量、嵌入/解析超时和仓库安全要求。已知密钥字面量扫描为 0；历史密钥仍需在供应商后台轮换。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 37 / 37 通过，本批新增 3 个 |
| Python 语法编译 | 通过 |
| 全项目 Ruff `F821/F822/F823` | 通过，保持 0 |
| 仓库已知凭据字面量扫描 | 0 |
| 私密配置忽略 | `config.local.yaml` 命中 `.gitignore`，运行时确认优先加载 |
| 用户向量库 | `1111=1`、`123456=23`、`6000701=191`、`undefined=3`，全部 1024 维 |
| 规则向量库 | 除家谱明确跳过及农作物 2 条图谱空数据外，其余主题全部完整 |
| `chat2kb` 真实 HTTP 回归 | 用户 `123456` 返回 `status=200` 且答案非空 |
| 在线服务 | `127.0.0.1:8998`，PID `15732`，OpenAPI 60 条路径 |

新增命令：

```powershell
# 从上传源文件重建用户库
D:\anaconda\envs\KO\python.exe scripts/manage_vector_assets.py rebuild-users `
  --user-id 123456

# 复用已提取 JSON，并在校验成功后替换已有库
D:\anaconda\envs\KO\python.exe scripts/manage_vector_assets.py rebuild-users `
  --user-id undefined --reuse-extracted --replace
```

仍需后续处理：

- 为“农作物”RID 603/604 在通用 Neo4j 图谱补齐 `getin4simi` 所需入口实体后，再执行定点向量构建。
- 在 OpenAI 兼容、DashScope、智谱、讯飞、MySQL 和 Neo4j 后台轮换历史上已暴露的凭据；代码脱敏不能使旧密钥自动失效。
- 当前重构目录仍有大量未跟踪文件及旧逻辑删除记录。应在确认凭据轮换和部署资产备份后按模块精确暂存，不能直接全目录提交。

## 20. 第七批迁移执行记录

### 2026-07-20：农作物规则补齐、配置入口收口与仓库净化

已完成：

1. 查明“农作物”RID 603/604 为空并非图谱缺数据，而是数据库 `getin4simi` 中的主题标签 `nongzuowu_600677` 少了一个 `0`。正确标签 `nongzuowu_6000677` 可召回萌芽期、开花期、坐果期、膨果期、成熟期和采摘期共 6 个入口实体。
2. 规则向量构建器现在读取 `theme_label`，只在查询同时包含规范标签且另一个标签与其恰好相差一个字符时执行校正；不会对无关标签做模糊替换。新增两个回归用例覆盖修复与防误改。
3. 已真实构建 RID 603/604，两者均为 1024 维、6 条文档，`index.faiss` 和 `index.pkl` 完整并可由 FAISS 读取。“农作物”主题达到 2/2 完整。
4. 修复三个领域图谱依赖仍直接读取 `config.yaml` 的遗漏。问答、规则构建、图谱构建和规则辅助模块现在统一经 `common.paths.CONFIG_PATH` 选择 `config.local.yaml` 或环境变量覆盖。
5. 为公共路径重导出增加显式 `__all__`，保留已有模块导入兼容性；全项目 Ruff `F401/F821/F822/F823` 从剩余 25 项降为 0。
6. 删除标准文档模块遗留的手工调试入口、测试输入缓存、冗余 SQL 和说明草稿；保留正式运行需要的术语 CSV、嵌入矩阵、提示词及 LaTeX 模板。
7. 删除 Git 根目录误留且包含旧明文凭据的第二份 `config.yaml`，新增 `REPOSITORY_MANIFEST.md` 明确源码、必要资产和部署数据的提交边界，并忽略 `.ruff_cache/`。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 39 / 39 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 待实现标记扫描 | `TODO/FIXME/NotImplementedError` 为 0 |
| 农作物规则向量库 | RID 603/604 均为 1024 维、6 条文档 |
| OpenAPI 路径 | 60 条 |
| Neo4j 页面接口 | 根路径、`/api`、规则页和图谱页四个入口均为 HTTP 200 |
| 轨交实体子图真实查询 | “油浸式电力变压器试验”返回 30 条路径和 30 组三元组 |
| `sql_polling` 真实查询 | HTTP 200，返回数据库中的规则列表 |
| 在线服务 | `127.0.0.1:8998`，PID `18744` |

当前代码迁移待办已清零。仓库发布前仍需完成两项外部操作：在各供应商后台轮换历史凭据；备份部署向量库和上传文件后，按 `REPOSITORY_MANIFEST.md` 审查并暂存 Git 变更。

## 21. 第八批迁移执行记录

### 2026-07-20：领域依赖去重与可重复部署

已完成：

1. 删除 `graph_construct` 中重复的文件提取、LLM、向量构建和知识库实现，以及 `rule_construct` 中重复的文件提取、向量构建和知识库实现，共 7 个无独立调用方的旧依赖副本。
2. 图谱入库的原始文件向量化和入口实体向量化统一复用 `kdzn_hciqa.engine_dependencies.knowledge_base_chatbot` 中已验证的超时、分批、重试、安全保存和统一路径逻辑。
3. 修复新增规则后的向量化语义：旧实现把 `getin4simi` Cypher 文本本身当成实体写入向量库；新实现提交数据库后读取完整规则行，执行入口查询，并按新 RID 构建真实规则实体库。
4. 新增规则持久化和图谱向量调用边界测试，覆盖持久化规则字段传递、公共 `Chatzxl` 调用和公共实体向量构建器调用。
5. 重建 Git 根目录 `requirements.txt`，从旧版 150 余项环境快照收敛为 41 个代码直接依赖和必要约束；LangChain、OpenAI、FastAPI、智谱及文档处理版本与当前验证代码对齐。新增 `requirements-dev.txt` 单独声明 Ruff。
6. 旧 README 已替换为新架构说明，包含安装、配置、启动、模块职责、向量资产恢复、标准文档外部模型、Pandoc/LaTeX、ffmpeg 和验证命令。
7. 标准文档 BGE 模型明确作为部署资产，由 `STANDARD_BGE_MODEL_PATH` 指定，不再将大型模型权重提交到源码仓库。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 42 / 42 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 待实现标记扫描 | 0 |
| 依赖清单 | 41 个固定版本；清单内传递约束冲突为 0 |
| OpenAPI 路径 | 60 条 |
| 图谱实体查询 | HTTP 200，30 条路径和 30 组三元组 |
| `sql_polling` | HTTP 200，返回 157 条轨交规则 |
| 在线服务 | `127.0.0.1:8998`，PID `10720` |

说明：当前共享 `KO` Conda 环境还安装了仓库之外的组件，并存在 `langsmith`、`PyJWT`、`grpcio` 的环境级元数据冲突；现有服务回归通过，但正式部署应按新的 `requirements.txt` 创建独立环境，不应把共享环境的完整 `pip freeze` 再写回仓库。

## 22. 第九批迁移执行记录

### 2026-07-20：Neo4j 公共客户端与查询副本清理

已完成：

1. 新增 `vue_api/common/neo4j_client.py`，集中管理家谱、轨交和通用三个 Neo4j 配置映射、驱动创建、事务超时、结果收集和驱动关闭。
2. `query_new_neo4j` 的 `timeout` 参数现在会传入 Neo4j `Query`，不再是未生效的形式参数。
3. 旧 `query_neo4j` 继续兼容 APOC `runTimeboxed`，但 Cypher 文本改为参数传递，修复查询中包含单引号时拼接失效并降低注入风险。
4. 问答、家谱辅助、规则向量构建、图谱构建、规则构建和页面实体查询全部改用公共 Neo4j 客户端；项目内只有公共客户端可以直接调用 `GraphDatabase.driver`。
5. 删除规则模块中与图谱模块完全相同的 36 KB `dependencies/graph_rule_queries/cypher_tool.py` 及空包入口。图谱构建侧仍保留有业务所有权的图数据批量写入算法，但驱动与查询已公共化。
6. 新增 4 个公共客户端测试，覆盖三图谱路由、配置选择、参数转发、超时、APOC 参数化和驱动关闭。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 46 / 46 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 三个 Neo4j 实例直连探针 | 通用、轨交、家谱均成功 |
| 旧 APOC 查询探针 | 成功，返回参数化结果 |
| Neo4j 驱动直连调用 | 除公共客户端外为 0 |
| 四个页面 Neo4j 接口 | 均为 HTTP 200，分别返回 30 条路径和 30 组三元组 |
| OpenAPI 路径 | 60 条 |
| 在线服务 | `127.0.0.1:8998`，PID `20396` |

## 23. 第十批迁移执行记录

### 2026-07-20：旧问答 Cypher 工具模块删除

已完成：

1. 对 `kdzn_hciqa/engine_dependencies/graph_rule_queries/cypher_tool.py` 的跨模块引用和静态调用关系完成审计。旧文件约 79 KB，对外仍被使用的能力只有领域描述读取和通义千问消息调用，其余逻辑已由新图谱问答链路覆盖。
2. 将通义千问消息调用迁移到 `engine_dependencies/llm_clients.py::call_qwen_messages`，统一复用模型配置、请求参数、客户端创建和异常处理；原 `llm_config.qwen` 也改为调用同一入口。
3. 将领域描述读取迁移到 `engine_dependencies/prompt_builders.py::get_domain_desc`，并让提示词配置查询同时读取 `chitchat_domain_desc`。数据库不可用时返回空配置，不再因空结果解包而中断问答。
4. `kdzn_graph_qa_engine.py` 和 `qa_answer/graph_stream_answer.py` 已切换到上述新入口，随后完整删除旧问答 `graph_rule_queries/cypher_tool.py`。
5. 新增 4 个回归测试，覆盖千问模型选择、客户端复用、领域描述读取和数据库不可用降级。
6. 审计 `neo4j_hpt.py` 后确认其大部分函数仍可由现有问答入口到达，本批不做激进删除；后续应按实际业务子域拆分，或只在补齐针对性测试后删除已证明无调用方的辅助函数。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 50 / 50 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 旧问答 `cypher_tool.py` | 已删除，业务 Python 引用为 0 |
| OpenAPI 路径 | 60 条 |
| 图谱实体查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| `sql_polling` | HTTP 200，返回 157 条轨交规则 |
| 领域描述真实查询 | 非空，返回 4 字符描述 |
| 在线服务 | `127.0.0.1:8998`，PID `4180` |

## 24. 第十一批迁移执行记录

### 2026-07-20：轨交问答死代码定点清理

已完成：

1. 对 `engine_dependencies/graph_rule_queries/neo4j_hpt.py` 的模块导入、函数调用和动态访问方式完成复核，确认 7 个旧辅助函数没有生产调用方、测试调用方或动态导出。
2. 删除未使用的 `record_value`、`query_entity_properties`、`getBest_phrases`、`chinese_text_preprocess`、`search_similar_cn`、`is_sublist` 和 `find_topK_path`。
3. 删除整段已注释停用的 `find_topK_kdzn` 旧流程，以及只供该流程使用的 `TfidfVectorizer` 和 sklearn 余弦相似度导入。
4. 保留仍被生产链路使用的 `record_payload`、`getBest_phrase`、`ListCacheManager` 和 `cache_manager`，本批不改变任何现役函数的输入、输出或查询行为。
5. `neo4j_hpt.py` 从约 123 KB、2756 行收敛到约 113 KB、2542 行，共减少约 10 KB 和 214 行旧逻辑。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 50 / 50 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 已删除符号静态引用 | 0 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 家谱 Neo4j 直连探针 | 成功，`RETURN 1 AS ok` 返回 1 行 |
| 在线服务 | `127.0.0.1:8998`，PID `19548`，错误日志标记为 0 |

## 25. 第十二批迁移执行记录

### 2026-07-20：家谱关系查询独立模块拆分

已完成：

1. 新增 `engine_dependencies/graph_rule_queries/family_graph_queries.py`，集中承载家谱实体信息、普通亲属关系、字辈关系、同名人物描述消歧和规则分派。
2. 从 `neo4j_hpt.py` 迁移并删除 7 个家谱函数：`query_entity_info`、`query_relationship`、`query_relationship_zibei`、`extract_valid_zibei_strict`、`extract_person_desc_snippet`、`find_kograph_zibei` 和 `find_kograph`。
3. `kdzn_graph_qa_engine.py` 已直接从新家谱模块导入 `find_kograph` 和 `find_kograph_zibei`；旧文件中的家谱函数定义为 0，运行时确认函数模块归属为 `family_graph_queries`。
4. 家谱实体、人物描述和字辈查询改用 Neo4j 参数传递，不再把人物名或描述直接拼入 Cypher。动态规则模板保持原执行语义。
5. 家谱重排模型配置改为复用缓存的 `shared.load_config()`；旧大文件同步移除 `dashscope` 和字辈规则辅助的孤立导入。
6. `neo4j_hpt.py` 从约 113 KB、2542 行降到约 94 KB、2116 行；新家谱模块约 14 KB，领域边界已经独立。
7. 新增 4 个家谱查询测试，覆盖参数化实体查询、无结果提示、严格字辈过滤和人物描述提取。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 54 / 54 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 旧文件家谱函数定义 | 0 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 家谱真实实体信息查询 | “罗泽南”返回非空结果，长度 511 |
| `find_kograph` 真实入口 | 返回 5 项，实体信息非空 |
| 在线服务 | `127.0.0.1:8998`，PID `924`，错误日志标记为 0 |

## 26. 第十三批迁移执行记录

### 2026-07-20：家谱多轮状态按会话隔离

已完成：

1. 删除 `family_graph_queries.py` 中 6 个模块级可变状态：两组人物候选、两个人物名和两个字辈值，不再由所有请求共享同一份家谱上下文。
2. 新增 `FamilyRelationState` 和 `FamilyRelationStateStore`。每个会话独立保存人物候选、人物名和字辈，状态对象使用独立重入锁保护同一会话的并发更新。
3. 状态仓库以 `qid` 为键，并在访问时清理超过一小时未使用的状态，避免长期运行服务无限保留历史会话上下文。
4. `qid` 已作为 `session_id` 从 `/ko4csg_hci` 主编排依次传入 `csg_port_stream`、`kdzn_select`、场景检索、家谱检索和 `find_kograph_zibei`。
5. `deleteConversationById` 在数据库删除提交成功后同步清理对应家谱关系状态，避免删除后复用同一 `qid` 带回旧人物候选。
6. 保持家谱查询七元返回结构、字辈规则匹配、多轮描述消歧和普通亲属关系行为不变；未提供会话键的内部兼容调用使用独立默认桶。
7. 新增 4 个状态与生命周期测试，覆盖不同会话隔离、过期重建、引擎 `session_id` 透传和删除会话后的状态清理。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 58 / 58 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 家谱模块级人物/字辈状态 | 0 |
| 运行时会话隔离探针 | 成功，两个 `qid` 状态互不影响 |
| 运行时状态清理探针 | 成功，`clear(qid)` 后返回空状态 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 家谱真实实体信息查询 | “罗泽南”返回非空结果，长度 511 |
| 在线服务 | `127.0.0.1:8998`，PID `15808` |

## 27. 第十四批迁移执行记录

### 2026-07-21：向量匹配模块拆分与旧规则代码清理

已完成：

1. 新增 `engine_dependencies/graph_rule_queries/vector_matching.py`，集中管理 FAISS 完整性检查、规则实体向量库补建、单条检索、Top-K 检索、规则候选嵌入匹配和通用候选相似度。
2. `neo4j_hpt.py`、`web_search.py` 和 `kdzn_graph_qa_engine.py` 已直接导入新模块；旧文件不再定义或重导出向量匹配函数。
3. 将旧 `getBest_rules_vec` 统一替换为 `get_best_rule_match`，将 `get_top3_match` 统一替换为可配置的 `get_top_matches`。
4. 修复规则候选为空时旧实现误把查询文本本身当作匹配结果的问题；现在不发起嵌入请求并返回 `(None, None)`。
5. 规则候选嵌入继续按每批最多 10 条请求，并新增嵌入返回数量校验和零向量保护；FAISS 读取继续校验 `index.faiss` 与 `index.pkl`，读取异常安全降级为空结果。
6. 删除会被后定义静默覆盖的第一份 `get_best_match`、旧批量文本嵌入注释实现、旧 `query_path` 注释实现，以及家谱迁移后零引用的 128 行 `reasoning_rules` 静态规则表。
7. `neo4j_hpt.py` 从约 94 KB、2115 行降到约 66 KB、1507 行；新向量模块约 5 KB，轨交/通用查询编排与向量检索职责已经分离。
8. 新增 4 个向量匹配测试，覆盖空候选、10 条分批、最佳候选选择、缺失 FAISS 和空通用候选。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 62 / 62 通过 |
| Python 语法编译 | 通过 |
| Ruff `F401/F821/F822/F823` | 0 |
| 旧向量函数定义及旧名称 | 0 |
| 旧静态家谱规则及注释实现 | 0 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| RID 2401 真实 FAISS 检索 | 命中“变压器本体‘吱吱’或‘噼啪’声接触不良及引起的放电”，得分约 0.693 |
| 在线服务 | `127.0.0.1:8998`，PID `23728` |

## 28. 第十五批迁移执行记录

### 2026-07-21：轨交规则查询独立模块拆分

已完成：

1. 新增 `engine_dependencies/graph_rule_queries/rail_graph_queries.py`，集中承载轨交规则选择、规则入口实体查询、规则实体向量匹配、Cypher 模板渲染、图路径抽取和异常事件 BERT/Faiss 兜底查询。
2. 新增 `engine_dependencies/graph_rule_queries/graph_query_utils.py`，统一承载 Neo4j 记录解包、规则路径归一化、中文转拼音、子路径去重和中文节点属性提取；轨交、通用查询及向量生成入口共同复用该模块。
3. 从 `neo4j_hpt.py` 删除 `find_kdzn`、`getYiChang`、`getBest_phrase`、`get_text_embedding` 及已迁移的共享函数定义；旧模块不再定义或转发轨交入口。
4. `kdzn_graph_qa_engine.py` 已直接从新轨交模块导入 `find_kdzn` 和 `get_yichang`；`knowledge_base_chatbot.py` 的场景标签转换也已切换到共享工具模块。
5. 保持单段及多段路径字符串格式、四元返回结构、规则实体相似度阈值、轨交固定标签和动态规则模板行为不变。
6. 修复异常事件兜底在无可用索引时访问空键的问题；现在稳定返回四元空结果。多规则词频匹配现在返回对应规则对象，不再把规则名字符串误当规则字典。
7. Faiss 异常事件索引维度改为读取实际嵌入维度，不再硬编码 1024；查询模型更换后不会因维度假设直接失败。
8. `neo4j_hpt.py` 从约 66 KB、1507 行降到 1060 行；新轨交模块 362 行，共享工具模块 54 行，家谱、轨交、向量匹配和通用查询边界已经分开。
9. 新增 8 个测试，覆盖共享工具契约、空规则、空异常索引以及规则实体命中后 Cypher 渲染与执行链路。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 70 / 70 通过 |
| Python 语法编译 | 通过 |
| 新模块 Ruff `F/E9` | 0 |
| 旧文件轨交入口定义 | 0 |
| 运行时函数模块归属 | `find_kdzn`、`get_yichang` 均属于 `rail_graph_queries` |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 新增模块 TODO/FIXME | 0 |
| 在线服务 | `127.0.0.1:8998`，PID `19556`，最终日志错误标记为 0 |

## 29. 第十六批迁移执行记录

### 2026-07-21：通用图查询独立与旧聚合模块下线

已完成：

1. 将剩余通用规则匹配、TOG 图探索、多跳路径扩展、路径方向判断、权限主题标签解析和结果整理迁入 `engine_dependencies/graph_rule_queries/general_graph_queries.py`。
2. 将硬编码轨交图谱的 `all_paths_from_entity` 移入 `rail_graph_queries.py`，引擎分别从通用和轨交模块直接导入生产入口。
3. `all_paths_from_entity` 的实体名改为 Neo4j 参数传递，不再直接拼接到 Cypher，保留原固定诊断关系链及二元返回结构。
4. 完整删除 `engine_dependencies/graph_rule_queries/neo4j_hpt.py`；运行时 `find_spec` 验证旧模块不存在，仓库生产代码与测试引用均为 0。
5. 清理迁入通用模块的 6 个无效局部变量和 1 个无占位符 f-string，未改变查询分支、阈值、返回模型或多轮路径行为。
6. 更新 `kdzn_hciqa/CALL_CHAIN.md`，明确家谱、轨交、通用查询、共享工具和向量匹配五个独立职责边界。
7. 新增 6 个测试，覆盖出边/入边路径方向、无关路径拒绝、空查询短路、公开主题标签解析及轨交实体参数化查询。
8. 当前通用模块 1016 行，轨交模块 405 行；原本同时承载多领域逻辑的聚合文件已经退出新架构。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 76 / 76 通过 |
| Python 语法编译 | 通过 |
| 通用/轨交模块 Ruff `F/E9` | 0 |
| 旧 `neo4j_hpt.py` 文件及引用 | 0 |
| 运行时模块归属 | `find_general` 属于 `general_graph_queries`；`all_paths_from_entity` 属于 `rail_graph_queries` |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 在线服务 | `127.0.0.1:8998`，PID `17068`，日志错误标记为 0 |

## 30. 第十七批迁移执行记录

### 2026-07-24：通用问答多轮缓存按会话隔离

已完成：

1. 删除通用查询模块级单例 `cache_manager`，新增 `GeneralQueryCache` 和 `GeneralQueryStateStore`，缓存键采用 `qid + 文件场景`，不同用户、会话和文件不再共享路径状态。
2. 每个缓存状态使用独立重入锁，完整 `find_general` 调用在同一会话/文件范围内串行执行；不同会话仍可并发处理。
3. 状态仓库默认一小时未访问自动过期；未提供 `qid` 的兼容调用继续使用默认会话桶。
4. 将旧平行列表缓存改为保存完整 `SearchResult`，统一保留结果名称、路径、逐路径三元组、全局三元组和匹配实体，修复多轮按路径选回时数据类型及索引错位。
5. 移除 TOG 并发工作线程内只覆盖 `paths` 的不完整缓存写入；现在由 `find_general` 外层在所有候选完成后一次性写回完整结果，避免多线程相互覆盖。
6. `session_id` 已从 `/ko4csg_hci` 的 `qid` 继续透传到通用场景检索和 `find_general`，并按 `file_ontology` 建立独立作用域。
7. `deleteConversationById` 在数据库删除提交成功后，同时清理家谱关系状态与该 `qid` 下所有通用文件缓存。
8. 新增 6 个测试，覆盖会话/文件隔离、会话全量清理、过期重建、缓存字段对齐、入口写回及引擎 `session_id` 透传；原删除会话测试扩展为双状态清理验证。
9. `general_graph_queries.py` 当前 1144 行；新增代码用于明确状态所有权和生命周期，未恢复任何旧聚合模块或全局共享业务状态。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 82 / 82 通过 |
| Python 语法编译 | 通过 |
| 相关模块 Ruff `F/E9` | 0 |
| 模块级共享 `cache_manager` | 0 |
| `qid + 文件场景` 隔离探针 | 成功，`qid-a` 路径未出现在 `qid-b` |
| 会话清理探针 | 成功，`clear(qid-a)` 后对应路径为空 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 在线服务 | `127.0.0.1:8998`，PID `12500`，日志错误标记为 0 |

## 31. 第十八批迁移执行记录

### 2026-07-24：通用 TOG 模型调用归一与离线降级

已完成：

1. `general_graph_queries.py` 不再直接导入 `OpenAI`、读取 Qwen 供应商配置或调用 `chat.completions`；缓存判断和逐轮路径筛选统一复用 `llm_clients.call_qwen_messages`。
2. 删除 TOG 两处嵌套 `qwen` 函数及两套重复客户端创建、模型选择、temperature/top_p/max_tokens 和异常处理逻辑，模型配置所有权回归 `llm_clients.py`。
3. 删除每次进入 TOG 都执行、但结果从未参与实体匹配或路径推理的全实体 Neo4j 查询，减少一次无效数据库往返并消除场景值直接拼接 Cypher 的入口。
4. 新增统一 JSON 对象提取、缓存决策解析和路径候选解析函数，可处理解释文本、Markdown 包裹、空响应及非 JSON 响应。
5. 缓存判断模型不可用时默认返回 `TOG`，继续执行本地向量实体检索；路径筛选模型不可用时默认保留全部合法候选，不再触发 `None.split()` 或 `None[:100]` 异常。
6. 模型返回越界或不可解析的 `selected_ids` 时继续过滤并回退全部候选；合法选择及 `over/continue` 语义保持不变。
7. 新增 4 个测试，覆盖包裹 JSON 提取、缓存决策离线回退、路径候选离线/越界回退及集中模型调用参数。
8. `general_graph_queries.py` 从 1144 行降到 1100 行；直接模型调用、重复 Qwen 函数和无效全实体查询扫描均为 0。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 86 / 86 通过 |
| Python 语法编译 | 通过 |
| 通用查询模块 Ruff `F/E9` | 0 |
| 直接 `OpenAI/chat.completions/def qwen` | 0 |
| 无效 `query_all_entities/all_entities` | 0 |
| TOG 空响应解析测试 | 通过，缓存决策回退 `TOG`、路径选择保留全部候选 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 在线服务 | `127.0.0.1:8998`，PID `26004`，日志错误标记为 0 |

## 32. 第十九批迁移执行记录

### 2026-07-24：通用 TOG Cypher 参数化与审计进度校准

已完成：

1. 通用 TOG 初始一跳查询将匹配实体改为 `$match_entity` 参数，外向与内向查询复用同一参数，不再把向量命中的实体文本直接写入 Cypher。
2. 前向/后向路径扩展为每个节点生成 `$path_node_N` 参数；带引号、括号或 Cypher 片段的节点名只进入参数字典，不进入查询文本。
3. 新增动态图标签白名单，只允许字母、数字和下划线组成且以字母/下划线开头；非法数据库标签在查询前明确失败。
4. `query_path` 新增可选 `parameters` 并原样传递给公共 `query_new_neo4j`，家谱主题和普通主题保持原图数据库选择逻辑。
5. 通用规则路径不再直接执行 `cypher.replace("{entityname}", match_ent)`，改用共享 `render_cypher`，统一处理旧别名、转义和未知占位符拒绝。
6. 删除仅为字符串拼接服务的 `_esc`；运行时实体/节点直接插值扫描为 0。
7. 新增 3 个测试，覆盖初始查询参数与标签校验、恶意路径节点参数化，以及 Neo4j 参数透传；规则模板原有 3 个转义/占位符测试继续通过。
8. 将报告首页从整改前 60% 快照校准为当前代码侧约 92%，历史 AST/接口指标保留在第 2 节作为基线。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 89 / 89 通过 |
| Python 语法编译 | 通过 |
| 通用查询模块 Ruff `F/E9` | 0 |
| TOG 实体/路径节点直接插值 | 0 |
| 恶意实体运行探针 | 查询文本不含实体，参数值完整一致 |
| OpenAPI 路径 | 60 条 |
| 轨交实体子图查询 | HTTP 200，返回 30 条路径和 30 组三元组 |
| 轨交规则轮询 | HTTP 200，返回 157 条规则 |
| 家谱规则轮询 | HTTP 200，返回 522 条规则 |
| 当前代码侧进度 | 约 92%，进入发布收尾阶段 |
| 在线服务 | `127.0.0.1:8998`，PID `25760`，日志错误标记为 0 |

## 33. 第二十批迁移执行记录

### 2026-07-24：通用规则、查询状态与 TOG 路径探索解耦

已完成：

1. 新增 `general_query_state.py`，独立承载 `SearchResult`、会话缓存、状态仓库、过期清理和匹配实体规范化；删除会话逻辑改为直接依赖状态模块，不再为清理状态而导入规则执行模块。
2. 新增 `tog_path_explorer.py`，集中承载 TOG JSON 解析、模型调用、标签校验、初始一跳查询、路径方向判断、前后向扩展、路径结果整理和并发候选探索。
3. 将 TOG 运行参数收敛为不可变 `TogSearchContext`，显式传入会话缓存、嵌入客户端和事件队列，移除嵌套函数对通用规则函数局部变量的隐式捕获。
4. `general_graph_queries.py` 只保留数据库连接、主题权限解析、规则选择、入口实体匹配、规则 Cypher 渲染和结果整理，物理行数由约 1060 行降到 429 行。
5. TOG 多轮缓存命中、模型离线回退、候选并发、叶子节点终止、家谱图选择和 Neo4j 参数化行为保持；路径查询和状态类运行时归属已验证为新模块。
6. 修复拆分断点中的旧 `_normalize_matched_entities` 引用，并清理通用规则模块不再使用的并发、JSON、正则、向量入口和模型客户端导入。
7. 调整测试导入及 mock 边界，新增 TOG 缓存 `over` 短路测试，确认命中缓存时不会再次触发实体向量检索。
8. 更新 `CALL_CHAIN.md`，明确通用规则、查询状态和 TOG 路径探索三个独立职责边界。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 90 / 90 通过 |
| Python 语法编译 | 通过 |
| 本批相关模块 Ruff | 0 |
| `general_graph_queries.py` | 429 行，无嵌套 TOG 实现 |
| 运行时模块归属 | 规则、状态、TOG、路径查询分别属于对应新模块 |
| OpenAPI 路径 | 60 条 |
| 轨交/家谱规则轮询 | 157 / 522 条 |
| 三个 `neo4j_query` 入口 | 均为 HTTP 200，30 条路径和 30 组三元组 |
| 当前代码侧进度 | 约 94%，进入发布收尾阶段 |
| 在线服务 | `127.0.0.1:8998`，PID `29868`，日志错误标记为 0 |

## 34. 第二十一批迁移执行记录

### 2026-07-24：服务启动配置与代码仓库发布卫生

已完成：

1. 新增 `vue_api/common/server_settings.py`，集中解析服务监听地址、端口、FastAPI debug 和 Uvicorn reload，布尔值及端口均进行严格校验。
2. `ko_qa_server.py` 改为应用工厂；默认关闭 debug/reload，直接运行端口由旧 8988 统一为 8998，同时保留环境变量覆盖能力。
3. 新增 `.env.example`，记录服务、配置路径、向量路径和外部服务变量名，不包含任何可用凭据；应用不隐式读取 `.env`。
4. 扩展 `.gitignore`，覆盖 `config.local.*`、私有 `.env.*`、通用/规则名/规则实体向量库、BM25、LaTeX 中间文件和生成结果；`.env.example` 明确保持可提交。
5. 更新 `CONFIGURATION.md` 和 `REPOSITORY_MANIFEST.md`，补充生产启动默认值、运行资产边界和发布前提交范围。
6. 配置模板递归扫描确认密码、API key、secret 和 app id 的非空值为 0；真实 `config.local.yaml` 保持不变且继续被 Git 忽略。
7. 新增 4 个服务设置测试，覆盖安全默认值、环境变量覆盖、非法布尔值和非法端口拒绝。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 94 / 94 通过 |
| Python 语法编译 | 通过 |
| 全仓关键 Ruff `F/E9` | 0 |
| FastAPI 默认模式 | `debug=False`，OpenAPI 60 条 |
| 配置模板可用凭据 | 0 |
| 私有配置/运行资产忽略 | 全部命中，`.env.example` 未被忽略 |
| 轨交/家谱规则轮询 | 157 / 522 条 |
| 三个 `neo4j_query` 入口 | 均为 HTTP 200，30 条路径和 30 组三元组 |
| 当前代码侧进度 | 约 95%，仅剩发布操作收尾 |
| 在线服务 | `127.0.0.1:8998`，PID `24392`，日志错误标记为 0 |

## 35. 第二十二批迁移执行记录

### 2026-07-24：嵌入服务与规则实体向量构建独立

已完成：

1. 新增 `embedding_service.py`，统一承载 Qwen Embedding 客户端、10 条分批、限流/连接异常重试、欠费错误归一、维度探测、目录创建和 Windows FAISS 临时 ASCII 路径回退。
2. `user_store_rebuilder.py` 与 `kdzn_graph_qa_engine.py` 改为直接依赖嵌入模块，不再为了创建 Embedding 客户端而导入整个 `knowledge_base_chatbot.py`。
3. 新增 `rule_vector_builder.py`，规则表白名单、RID 范围读取、图谱入口实体采集、标签单字符纠错、去重、FAISS 构建和 CLI 均拥有唯一归属。
4. `rule_database.py` 改为直接调用规则向量构建模块；`knowledge_base_chatbot.py` 仅保留兼容导出，旧调用无需一次性修改。
5. 旧 `knowledge_base_chatbot.py --rid/--all` 命令继续可用，并委托新 CLI；新模块同时支持 `python -m ...rule_vector_builder`，两个 `--help` 均以退出码 0 完成。
6. 删除聚合模块中的嵌入类、FAISS 保存、规则实体采集、规则向量构建、重复 argparse 和文件尾调试注释；文件从 1040 行降到 883 行。
7. 清理本次暴露的无效变量、无占位符 f-string 和单行多模块导入；嵌入及规则向量核心定义静态扫描均只有 1 处。
8. 新增 6 个测试，覆盖欠费提示、异常封装、目录创建、FAISS 回退、兼容导出归属和非法表名查询前拒绝。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 100 / 100 通过 |
| Python 语法编译 | 通过 |
| 全仓关键 Ruff `F/E9` | 0 |
| 嵌入核心定义归属 | 仅 `embedding_service.py` |
| 规则向量核心定义归属 | 仅 `rule_vector_builder.py` |
| 新旧规则向量 CLI | `--help` 退出码均为 0 |
| OpenAPI 路径 | 60 条 |
| 轨交/家谱规则轮询 | 157 / 522 条 |
| 三个 `neo4j_query` 入口 | 均为 HTTP 200，30 条路径和 30 组三元组 |
| 当前代码侧进度 | 约 97%，仅剩最终仓库发布操作 |
| 在线服务 | `127.0.0.1:8998`，PID `17456`，日志错误标记为 0 |

## 36. 第二十三批迁移执行记录

### 2026-07-24：入口实体向量构建独立与旧规则向量方法删除

已完成：

1. 新增 `entity_vector_builder.py`，统一处理入口实体清洗去重、家谱/普通主题路径选择、FAISS 加载或空索引创建，以及增量文档索引。
2. 空实体列表现在直接返回 `empty`，不再为了建立无内容向量库调用远程 Embedding；`None`、空字符串和重复实体不会进入索引。
3. `graph_construct.graph_data` 改为直接调用入口实体构建模块，不再为了图谱入库后的实体向量化加载在线 RAG 聚合模块。
4. 问答后自动生成规则直接将新 RID、主题、标签和入口查询交给 `build_rule_entity_vector_store`；删除同一事务内对刚插入规则的重复 SELECT。
5. 完整删除 `Chatzxl.entity_vector` 及其中按三类图谱重复解析记录、先保存再加载空 FAISS、局部重复文档构建等旧逻辑。
6. 删除 `knowledge_base_chatbot.py` 顶层 `get_entity_vector`、`load_document_entity` 和 `_has_faiss_store` 重复实现；兼容导出指向新模块。
7. `knowledge_base_chatbot.py` 从 883 行继续降到 699 行，并移除不再使用的 Neo4j、实体向量路径、时间和系统导入。
8. 新增 4 个测试，覆盖实体清洗、空列表离线短路、去重文档增量索引，以及新增规则只执行一次 INSERT 并调用公共构建器。

验证结果：

| 验证项 | 结果 |
|---|---|
| 标准库单元测试 | 104 / 104 通过 |
| Python 语法编译 | 通过 |
| 全仓关键 Ruff `F/E9` | 0 |
| `Chatzxl.entity_vector` | 已删除，生产/测试引用为 0 |
| 入口实体构建定义 | 仅 `entity_vector_builder.py` |
| `knowledge_base_chatbot.py` | 699 行，仅保留 RAG/用户文档索引及兼容导出 |
| OpenAPI 路径 | 60 条 |
| 轨交/家谱规则轮询 | 157 / 522 条 |
| 三个 `neo4j_query` 入口 | 均为 HTTP 200，30 条路径和 30 组三元组 |
| 当前代码侧进度 | 约 98%，仅剩最终仓库发布操作 |
| 在线服务 | `127.0.0.1:8998`，PID `17600`，日志错误标记为 0 |

## 37. 第二十四批最终对齐复审

### 2026-07-24：发布门槛复核与结案判定

本次复审新发现并已修复：

1. `neo4j_def.py` 存在两个完全相同的 `KO_tupu`，后一个会静默覆盖前一个；现已删除重复定义以及无调用方的旧路径工具和 `__main__` 调试代码。
2. 有效 `KO_tupu` 链路原先把实体关键词直接拼进 Cypher；现改为 `$head` 参数，并将跳数限制为 1-5。
3. 公共旧式 `query_neo4j` 新增向后兼容的 `parameters`，通过 APOC `query_parameters` 传入业务参数，原 `query/timeout/kg` 调用方式不变。
4. 新增 3 个测试，覆盖恶意实体参数化、非法跳数查询前拒绝和多关键词结果分组；公共 Neo4j 客户端测试同步验证参数透传。

最终发布门槛：

| 门槛 | 结果 | 判定 |
|---|---:|---|
| Java 代理实际 Python 路径 | 51 / 51 存在 | 通过 |
| OpenAPI | 60 条 | 通过 |
| 自动化测试 | 107 / 107 | 通过 |
| Python 全量编译 | 通过 | 通过 |
| 关键 Ruff `F/E9` | 0 | 通过 |
| TODO / pass-only / NotImplemented | 0 | 通过 |
| 重复顶层 callable | 0 | 通过 |
| 旧模块生产引用 | 0 | 通过 |
| 高置信源码密钥 | 0 | 通过 |
| `config.yaml` 可用凭据 | 0 | 通过 |
| 非家谱规则向量资产 | 307 / 307 完整 | 通过 |
| 现有规则向量目录 | 313 / 313 成对完整 | 通过 |
| 轨交实体子图 | HTTP 200，30 路径 / 30 三元组 | 通过 |
| 家谱实体子图 | HTTP 200，6 路径 / 6 三元组 | 通过 |
| 服务日志错误标记 | 0 | 通过 |

结案判定：

1. **代码迁移可以结束。** 当前前端与生产调用范围内没有待迁移函数、接口缺口、重复实现或 TODO 阻断项。
2. **仓库发布尚不能直接结束。** 当前 Git 工作树共有 699 个条目：338 个已暂存删除、184 个未暂存删除、4 个未暂存修改和 173 个未跟踪文件，必须先按 `REPOSITORY_MANIFEST.md` 审查并形成一次一致提交。
3. 6 个规则向量目录对应的 RID 已不在数据库，是被 `.gitignore` 排除的孤儿部署资产，不影响运行，可在备份后单独清理。
4. 本次 MySQL 直连测得建连约 0.79-8.41 秒，规则轮询出现 12-24 秒波动，但查询结果始终正确；这是部署数据库连接性能风险，不是功能对齐阻断项。
5. 外部 LLM、语音识别、标准文档模型和 Pandoc/LaTeX 的真实供应商端到端结果依赖账号与部署环境，本次以接口加载、离线降级和自动化测试为准，正式发布环境仍应执行一次人工冒烟。

最终状态：**功能重构结案，进入 Git 纳管与部署发布阶段。**  
在线服务：`127.0.0.1:8998`，PID `2580`。

---

本报告是一次代码与当前运行环境快照审计。外部模型服务结果、数据库数据和图谱内容可能随环境变化；正式发布前应在目标部署环境重跑同一组回归用例。

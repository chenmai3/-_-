# KO-QA 重构版服务端

KO-QA 是一个基于 FastAPI 的知识图谱与知识库问答服务端，包含轨交诊断、
家谱问答、通用问答、图谱构建、规则构建、用户文档知识库和标准文档生成等功能。

本仓库是完成模块化重构后的服务端代码。旧版根目录脚本、重复实现、历史模型文件、
运行日志、用户上传文件、生成文档和向量库均未保留在 Git 仓库中。

## 一、重构说明

本次重构的主要目标如下：

- 使用 `ko_qa_server.py` 作为唯一 FastAPI 服务入口。
- 使用 `vue_api/router.py` 统一注册 `/api` 下的业务路由。
- 按业务领域拆分问答、图谱、规则、家谱和通用问答模块。
- 将路径、Neo4j 客户端、向量资产校验和服务启动参数下沉到 `vue_api/common/`。
- 将大模型调用、Embedding、规则向量生成、实体向量生成和用户向量库重建拆分为独立组件。
- 所有模块统一读取一份配置文件，不再在各模块中拼接不同的配置路径。
- 运行数据与源码分离，日志、向量库、上传文件、本地密钥等内容通过 `.gitignore` 排除。

## 二、项目结构

```text
KO_QA_RF/
├─ README.md                         # 本说明文档
├─ requirements.txt                 # 运行依赖
├─ requirements-dev.txt             # 测试与静态检查依赖
├─ LICENSE
└─ ko_qa_server/
   ├─ ko_qa_server.py               # FastAPI 唯一入口
   ├─ config.yaml                   # 无密钥的配置模板
   ├─ config.local.yaml             # 本地完整配置，不提交 Git
   ├─ .env.example                  # 环境变量示例
   ├─ CONFIGURATION.md              # 配置补充说明
   ├─ REFACTOR_AUDIT.md             # 重构对齐审计报告
   ├─ REPOSITORY_MANIFEST.md        # 源码与部署资产边界
   ├─ scripts/
   │  └─ manage_vector_assets.py    # 向量库检查、迁移和重建工具
   ├─ tests/                        # 自动化测试
   └─ vue_api/
      ├─ router.py                  # /api 总路由
      ├─ common/                    # 公共路径、Neo4j、向量资产和启动配置
      ├─ general_qa/                # 通用问答、URL 问答、用户知识库问答
      ├─ jiapu_qa/                  # 家谱问答
      ├─ graph_construct/           # 图谱构建与图谱数据管理
      ├─ rule_construct/            # 规则构建、匹配、持久化与轮询
      └─ kdzn_hciqa/
         ├─ api.py                  # 知识问答接口
         ├─ conversation_history/   # 会话历史
         ├─ document_upload/        # 用户文档上传与向量化
         ├─ engine_dependencies/    # 图谱问答、RAG、模型与向量组件
         ├─ permissions/            # 主题权限
         ├─ qa_answer/              # 图谱和 RAG 流式回答
         ├─ speech_recognition/     # 语音识别
         └─ standard_document/      # 标准文档生成与下载
```

## 三、核心模块

| 模块 | 接口前缀 | 主要职责 |
|---|---|---|
| `vue_api/kdzn_hciqa` | `/api/kdzn_qa` | 轨交及领域图谱问答、RAG、文件上传、语音识别、标准文档 |
| `vue_api/jiapu_qa` | `/api/jiapu_qa` | 家谱规则问答、人物关系、家谱会话状态、外部家谱数据源 |
| `vue_api/graph_construct` | `/api/graph` | 文件分析、图谱导入、实体浏览、图谱删除与权限 |
| `vue_api/rule_construct` | `/api/rule` | 规则生成、规则存储、图谱匹配、SQL 轮询与权限 |
| `vue_api/general_qa` | `/api/general_qa` | 普通对话、URL 内容问答、用户知识库问答 |
| `vue_api/common` | 无独立接口 | 配置路径、Neo4j 客户端、向量资产、关键词索引、启动参数 |

兼容接口 `/neo4j_query` 和 `/api/neo4j_query` 仍然保留。
完整接口以服务启动后的 `/docs` 为准。

## 四、运行环境

推荐环境：

- Python 3.9
- MySQL
- Neo4j，并安装业务查询依赖的 APOC 插件
- OpenAI 兼容的 Chat Completions 和 Embeddings 服务
- 可选：FFmpeg、Pandoc、LaTeX、本地 BGE 模型

安装运行依赖：

```powershell
cd D:\ko-qa-rf\KO_QA_RF
D:\anaconda\envs\KO\python.exe -m pip install -r requirements.txt
```

开发、测试环境安装：

```powershell
D:\anaconda\envs\KO\python.exe -m pip install -r requirements-dev.txt
```

## 五、配置文件

### 5.1 配置文件加载顺序

服务统一通过 `vue_api.common.paths.CONFIG_PATH` 获取配置，优先级从高到低为：

1. 环境变量 `KO_QA_CONFIG_PATH` 指定的文件。
2. `ko_qa_server/config.local.yaml`。
3. `ko_qa_server/config.yaml`。

首次部署时复制模板：

```powershell
cd D:\ko-qa-rf\KO_QA_RF\ko_qa_server
Copy-Item config.yaml config.local.yaml
```

然后只修改 `config.local.yaml`。该文件必须是一份完整配置，不是对
`config.yaml` 的局部覆盖；它已被 Git 忽略，不要将密码或 API Key 写入
`config.yaml`。

项目不会自动加载 `.env` 文件。环境变量需要由 PowerShell、IDE、Docker、
systemd 或其他进程管理器注入。

### 5.2 MySQL

规则、主题、权限、会话及部分业务数据使用 `KO_database`：

```yaml
KO_database:
  host: "127.0.0.1"
  user: "your_user"
  password: "your_password"
  database: "db_hp"
  charset: "utf8"
```

启动前需要确认数据库地址可访问，账号对目标表具有查询和业务所需的写入权限。

### 5.3 Neo4j

当前架构统一通过 `vue_api/common/neo4j_client.py` 创建驱动。配置映射如下：

| 配置项 | 代码中的图谱类型 | 用途 |
|---|---|---|
| `neo4j.default` | `jiapu` | 家谱图谱 |
| `neo4j.kdzn` | `kdzn` | 轨交诊断图谱 |
| `neo4j.new_kdzn` | 默认空类型 | 通用或其他主题图谱 |

配置示例：

```yaml
neo4j:
  default:
    uri: "bolt://127.0.0.1:7687"
    username: "neo4j"
    password: "your_password"
  kdzn:
    uri: "bolt://127.0.0.1:7688"
    username: "neo4j"
    password: "your_password"
  new_kdzn:
    uri: "bolt://127.0.0.1:7689"
    username: "neo4j"
    password: "your_password"
```

即使多个业务共用同一个 Neo4j 实例，也应保留三个完整配置项。

## 六、大模型配置

### 6.1 中间处理模型

`small_models` 用于问题分类、实体关系抽取、规则生成和部分提示词处理：

```yaml
small_models:
  gpt:
    model_name: "gpt-3.5-turbo"
    temperature: 0.0
    api_key: ""
    base_url: "https://example.com/v1"
  qwen:
    qwen2_model_name: "qwen-max"
    qwen2.5_model_name: "qwen2.5-72b-instruct"
    temperature: 0.0
    api_key: ""
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  kimi:
    model_name: "Moonshot-Kimi-K2-Instruct"
    temperature: 0.3
    api_key: ""
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

根配置项 `model` 决定部分中间流程优先使用的模型类型。

### 6.2 问答模型

`qa_models` 是最终回答模型配置：

- `qa_models.qwen`：Qwen、DeepSeekV3、DeepSeekR1、QwQ 等 OpenAI 兼容模型。
- `qa_models.spark`：讯飞星火。
- `qa_models.zhipuai`：智谱模型。
- `qa_models.kimi`：Kimi 模型。
- `local_model.url`：本地模型服务地址。

接口参数中的 `model_choose` 用于选择具体回答模型。修改模型时应同时确认
`model_name`、`base_url`、`api_key` 和目标服务的 OpenAI 兼容性。

### 6.3 Embedding 模型

当前真正生效的向量模型配置是 `embedding_models`：

```yaml
embedding_models:
  embedding_model_name: "text-embedding-v4"
  api_key: ""
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

`config.yaml` 中的 `Qwen` 和 `local` 是候选配置示例，不会自动切换。
需要更换向量服务时，应将目标配置写入 `embedding_models`。

当前 `QwenEmbeddings` 请求固定生成 **1024 维**向量。更换模型后必须确认其支持
1024 维输出，并重建所有相关 FAISS 向量库，不能混用不同模型或不同维度的旧索引。

Embedding 相关环境变量：

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `KO_QA_EMBEDDING_DIMENSION` | `1024` | 向量资产检查使用的目标维度 |
| `KO_QA_EMBEDDING_TIMEOUT` | `60` | 单次请求超时，单位秒 |
| `KO_QA_EMBEDDING_MAX_RETRIES` | `6` | 可重试错误的最大重试次数 |
| `KO_QA_EMBEDDING_RETRY_BASE` | `2` | 指数退避基础秒数 |
| `KO_QA_EMBEDDING_BATCH_DELAY` | `0.2` | Embedding 批次之间的等待秒数 |

## 七、路径统一管理

所有运行路径统一定义在 `vue_api/common/paths.py`。默认路径均以
`ko_qa_server/` 为根目录，也可以使用环境变量将运行数据放到仓库之外。

| 环境变量 | 默认位置 | 内容 |
|---|---|---|
| `KO_QA_SERVER_ROOT` | `ko_qa_server/` | 服务端根目录 |
| `KO_QA_CONFIG_PATH` | `config.local.yaml` 或 `config.yaml` | 完整配置文件 |
| `KO_QA_USER_VECTOR_STORES_ROOT` | `user_vector_stores/` | 用户文档向量库 |
| `KO_QA_ENTITY_VECTOR_ROOT` | `entity_vector/` | 图谱入口实体向量库 |
| `KO_QA_JIAPU_ENTITY_VECTOR_STORE` | `entity_vector/jiapu_entity_vector_store/` | 家谱主题实体向量库 |
| `KO_QA_RULE_ENTITY_VECTOR_KDZN_ROOT` | `rule_entity_vector_store_kdzn/` | 按 RID 保存的规则实体向量库 |
| `KO_QA_UPLOAD_FILE_ROOT` | `upload_file_user/` | 用户上传原文件 |
| `KO_QA_UPLOAD_JSON_ROOT` | `upload_files_json_all/` | 文件解析结果 |
| `KO_QA_TEMP_AUDIO_ROOT` | `temp_audio/` | 临时音频 |
| `KO_QA_EMBEDDING_MODEL_ROOT` | `model/embeddings/` | 本地 Embedding 模型 |
| `KO_QA_LOCAL_ANALYSIS_FILE_ROOT` | `graph_construct_files/` | 图谱构建本地分析文件 |

推荐在生产环境中把数据目录放到 Git 仓库之外：

```powershell
$env:KO_QA_SERVER_ROOT = "D:\ko-qa-rf\KO_QA_RF\ko_qa_server"
$env:KO_QA_USER_VECTOR_STORES_ROOT = "D:\KO_QA_DATA\user_vector_stores"
$env:KO_QA_ENTITY_VECTOR_ROOT = "D:\KO_QA_DATA\entity_vector"
$env:KO_QA_RULE_ENTITY_VECTOR_KDZN_ROOT = "D:\KO_QA_DATA\rule_entity_vector_store_kdzn"
$env:KO_QA_UPLOAD_FILE_ROOT = "D:\KO_QA_DATA\upload_file_user"
$env:KO_QA_UPLOAD_JSON_ROOT = "D:\KO_QA_DATA\upload_files_json_all"
$env:KO_QA_TEMP_AUDIO_ROOT = "D:\KO_QA_DATA\temp_audio"
```

不要在业务模块中重新使用 `Path.cwd()` 或硬编码绝对路径。新增路径应继续集中到
`vue_api/common/paths.py`。

## 八、向量库说明

向量库属于部署数据，不进入 Git。每个完整的 LangChain FAISS 向量库至少包含：

```text
index.faiss
index.pkl
```

只有其中一个文件时属于不完整向量库，不能用于检索。

### 8.1 用户知识库

默认路径：

```text
user_vector_stores/
└─ <user_id>/
   ├─ index.faiss
   ├─ index.pkl
   ├─ index/              # 关键词索引
   └─ doc_rangs.json      # 文档范围信息
```

用户上传原文件位于 `upload_file_user/<user_id>/`。向量库可以由上传接口创建，
也可以使用脚本重建。

检查用户向量库：

```powershell
cd D:\ko-qa-rf\KO_QA_RF\ko_qa_server
D:\anaconda\envs\KO\python.exe scripts\manage_vector_assets.py audit
```

从旧服务目录迁移维度兼容的用户向量库：

```powershell
D:\anaconda\envs\KO\python.exe scripts\manage_vector_assets.py migrate-users `
  --source-server "D:\旧项目\ko_qa_server" `
  --copy-uploads
```

从用户上传原文件重建：

```powershell
D:\anaconda\envs\KO\python.exe scripts\manage_vector_assets.py rebuild-users `
  --user-id 123456 `
  --replace
```

### 8.2 图谱入口实体向量库

普通主题的默认目录结构：

```text
entity_vector/
└─ <label>_entity_vector_store/
   └─ <scene拼音>_entity_vector_store/
      ├─ index.faiss
      └─ index.pkl
```

家谱主题实体向量库默认位于：

```text
entity_vector/jiapu_entity_vector_store/
```

这类向量库由图谱实体向量化流程调用
`engine_dependencies/entity_vector_builder.py` 创建。目录不存在时会自动创建。

### 8.3 规则实体向量库

轨交及非“家谱问答”规则按数据库 RID 保存：

```text
rule_entity_vector_store_kdzn/
└─ <rid>_entity_vector_store/
   ├─ index.faiss
   └─ index.pkl
```

生成指定规则：

```powershell
cd D:\ko-qa-rf\KO_QA_RF\ko_qa_server
D:\anaconda\envs\KO\python.exe -m `
  vue_api.kdzn_hciqa.engine_dependencies.rule_vector_builder `
  --rid 2401
```

一次生成多个 RID：

```powershell
D:\anaconda\envs\KO\python.exe -m `
  vue_api.kdzn_hciqa.engine_dependencies.rule_vector_builder `
  --rid 2401 --rid 2402 --rid 2403
```

生成规则表中的全部向量库：

```powershell
D:\anaconda\envs\KO\python.exe -m `
  vue_api.kdzn_hciqa.engine_dependencies.rule_vector_builder `
  --table ko_kdzn_rule_construct `
  --all
```

已存在的完整向量库默认跳过；需要覆盖时增加 `--force`。`--all` 会调用 Neo4j、
MySQL 和 Embedding 服务，执行前应确认数据库配置、API 额度和输出路径。

不要直接执行 `knowledge_base_chatbot.py` 的文件路径。包内模块包含相对导入，
命令行任务应从 `ko_qa_server/` 目录使用 `python -m` 运行。

## 九、其他外部服务

### 9.1 语音识别

| 环境变量 | 说明 |
|---|---|
| `XF_APP_ID` | 讯飞应用 ID |
| `XF_API_KEY` | 讯飞 API Key |
| `XF_API_SECRET` | 讯飞 API Secret |
| `FFMPEG_PATH` | FFmpeg 可执行文件路径；未配置时使用系统 `PATH` |

未设置讯飞环境变量时，代码会回退读取 `qa_models.spark` 中的对应配置。

### 9.2 联网搜索和文件解析

| 环境变量 | 说明 |
|---|---|
| `DASHSCOPE_APPLICATION_ID` | DashScope 搜索应用 ID |
| `DASHSCOPE_APPLICATION_API_KEY` | DashScope 搜索应用密钥 |
| `ZHIPUAI_API_KEY` | 智谱文件解析密钥 |
| `ZHIPUAI_BASE_URL` | 智谱兼容接口地址 |
| `ZHIPUAI_FILE_TIMEOUT` | 文件解析超时秒数 |
| `ZHIPUAI_FILE_MAX_RETRIES` | 文件解析重试次数 |

### 9.3 家谱外部服务

家谱辅助查询支持以下地址覆盖：

- `HPT_SUBMIT_URL`
- `HPT_RESULT_URL`
- `HPT_CANCEL_URL`

未配置时使用代码内的默认家谱服务地址。

### 9.4 标准文档生成

标准文档模块支持以下环境变量：

| 环境变量 | 说明 |
|---|---|
| `STANDARD_DOC_LLM_API_KEY` | 标准文档模型密钥 |
| `STANDARD_DOC_LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `STANDARD_DOC_LLM_MODEL` | 模型名称 |
| `STANDARD_DOC_LLM_TEMPERATURE` | 温度 |
| `STANDARD_DOC_LLM_TOP_P` | Top P |
| `STANDARD_DOC_LLM_MAX_TOKENS` | 最大输出 Token |
| `STANDARD_BGE_MODEL_PATH` | 本地 BGE 模型目录 |
| `STANDARD_TERMBASE_DB_URL` | SQLAlchemy 格式的术语数据库地址 |

未单独配置标准文档模型时，API Key 和 Base URL 会回退到
`small_models.qwen`。术语匹配还需要部署本地 BGE 模型，以及在
`generation_engine/cache/` 下生成术语 CSV 和 NPY 向量缓存。这些缓存不提交 Git。

生成 DOCX 需要 Pandoc；生成 PDF 还需要可用的 LaTeX 工具链。运行时生成的
`latex_cache/` 和 `result/` 目录同样不进入仓库。

## 十、服务启动

在 `ko_qa_server/` 目录启动：

```powershell
cd D:\ko-qa-rf\KO_QA_RF\ko_qa_server
D:\anaconda\envs\KO\python.exe -m uvicorn ko_qa_server:app `
  --host 0.0.0.0 `
  --port 8998
```

也可以直接运行入口：

```powershell
D:\anaconda\envs\KO\python.exe ko_qa_server.py
```

直接运行入口时使用以下环境变量：

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `KO_QA_HOST` | `0.0.0.0` | 监听地址 |
| `KO_QA_PORT` | `8998` | 监听端口 |
| `KO_QA_DEBUG` | `false` | FastAPI 调试模式 |
| `KO_QA_RELOAD` | `false` | Uvicorn 自动重载 |

启动后访问：

- OpenAPI：`http://127.0.0.1:8998/docs`
- OpenAPI JSON：`http://127.0.0.1:8998/openapi.json`

## 十一、测试与检查

```powershell
cd D:\ko-qa-rf\KO_QA_RF\ko_qa_server

# 自动化测试
D:\anaconda\envs\KO\python.exe -m pytest -q

# Python 编译检查
D:\anaconda\envs\KO\python.exe -m compileall -q vue_api tests scripts

# 高风险静态错误检查
D:\anaconda\envs\KO\python.exe -m ruff check vue_api tests scripts `
  --select F401,F821,F822,F823,E9
```

当前重构版本自动化测试基线为 **107 项测试全部通过**。

## 十二、禁止提交的内容

以下内容已通过 `.gitignore` 排除：

- `config.local.*`、`.env` 和任何包含真实密钥的配置。
- `*.log`、Python 缓存和测试缓存。
- `*.faiss`、`index.pkl`、`*.npy` 和各类向量库目录。
- 用户上传文件、文件解析结果和图谱分析临时文件。
- 音频临时文件、标准文档缓存和生成结果。
- 本地模型权重及其他部署数据。

向量库和上传文件应使用独立数据盘、备份系统或对象存储管理，不应通过 Git 分发。

## 十三、相关文档

- `ko_qa_server/CONFIGURATION.md`：配置和环境变量补充说明。
- `ko_qa_server/REFACTOR_AUDIT.md`：重构前后功能对齐审计。
- `ko_qa_server/REPOSITORY_MANIFEST.md`：源码、运行资产和禁止提交内容的边界。
- `ko_qa_server/vue_api/*/CALL_CHAIN.md`：主要业务调用链。

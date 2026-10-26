# KO-QA 服务配置

## 本地运行

1. 将 `config.yaml` 复制为 `config.local.yaml`。
2. 只在 `config.local.yaml` 中填写数据库、Neo4j、模型和第三方服务凭据。
3. 启动服务时会优先读取 `config.local.yaml`；该文件已被 `.gitignore` 排除。

也可以通过 `KO_QA_CONFIG_PATH` 指向部署环境提供的配置文件。路径类配置继续使用
`KO_QA_SERVER_ROOT`、`KO_QA_USER_VECTOR_STORES_ROOT`、
`KO_QA_RULE_ENTITY_VECTOR_KDZN_ROOT` 等环境变量覆盖。

## 服务启动配置

- `KO_QA_HOST`：监听地址，默认 `0.0.0.0`。
- `KO_QA_PORT`：监听端口，默认 `8998`。
- `KO_QA_DEBUG`：FastAPI 调试模式，默认 `false`。
- `KO_QA_RELOAD`：Uvicorn 自动重载，默认 `false`。

可复制 `.env.example` 作为部署环境变量清单。应用不会主动读取 `.env`；
由进程管理器、容器平台或 shell 注入环境变量。生产环境不应启用 debug 或 reload。

## 外部服务覆盖

- `HPT_SUBMIT_URL`、`HPT_RESULT_URL`、`HPT_CANCEL_URL`：华谱通提交、结果查询和取消地址；默认使用 `https://www.zhonghuapu.com/index.php/datamgr/` 下的原接口。
- `HPT_POLL_ATTEMPTS`、`HPT_POLL_INTERVAL`：华谱通轮询次数与间隔，默认 `36` 次、`5` 秒。每个任务单独保留提交和轮询的 Session Cookie，使用老站兼容的请求头和 TLS 配置。
- `XF_APP_ID`、`XF_API_KEY`、`XF_API_SECRET`：讯飞语音识别。
  可在私有配置中使用 `speech_recognition.app_id`、`api_key`、`api_secret`，与星火聊天模型凭据分开配置，沿用老项目开通录音文件转写的应用。环境变量优先。
- `DASHSCOPE_APPLICATION_ID`、`DASHSCOPE_APPLICATION_API_KEY`：DashScope 搜索应用。
- `ZHIPUAI_API_KEY`、`ZHIPUAI_BASE_URL`：文件文本提取。
- `ZHIPUAI_FILE_TIMEOUT`、`ZHIPUAI_FILE_MAX_RETRIES`：文件提取超时与重试。
- `KO_QA_EMBEDDING_TIMEOUT`、`KO_QA_EMBEDDING_MAX_RETRIES`、
  `KO_QA_EMBEDDING_RETRY_BASE`：嵌入请求超时与退避。
- `KO_QA_EMBEDDING_DIMENSION`：当前向量维度，默认 1024。
- `KO_QA_MAX_TEXT_SOURCE_BYTES`：用户纯文本重建上限，默认 2 MiB。
- `STANDARD_BGE_MODEL_PATH`：标准文档术语匹配使用的本地 BGE 模型目录。
- `FFMPEG_PATH`：语音文件转码使用的 ffmpeg 可执行文件；未设置时使用系统 `PATH`。
  也可设置私有配置中的 `speech_recognition.ffmpeg_path`；环境变量优先，其次为私有配置，最后使用系统 `PATH`。

## 仓库要求

- 不得提交 `config.local.*`、`.env*`（`.env.example` 除外）、向量库、上传源文件和解析缓存。
- `config.yaml` 只保留结构、模型名和非敏感默认值，不放置可用凭据。
- 所有 Python 领域模块统一通过 `vue_api.common.paths.CONFIG_PATH` 选择配置，不应自行拼接 `config.yaml` 路径。
- Neo4j 驱动创建和查询统一通过 `vue_api.common.neo4j_client`；领域模块不应直接读取 Neo4j 凭据或调用 `GraphDatabase.driver`。
- 服务启动参数统一由 `vue_api.common.server_settings` 解析，不在入口脚本中写死调试模式和端口。
- 提交范围和标准文档必要资产见 `REPOSITORY_MANIFEST.md`。
- 历史上进入过代码或聊天记录的密钥应在对应服务后台轮换，Git 脱敏不能撤销已泄露密钥。

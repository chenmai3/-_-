import sys
from pathlib import Path

if __package__ in (None, ""):
    server_root = Path(__file__).resolve().parents[3]
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))
    __package__ = "vue_api.kdzn_hciqa.engine_dependencies"

from .graph_rule_queries.graph_query_utils import han2pinyin_concat
from tqdm import tqdm
import pymysql
from langchain_openai import ChatOpenAI
import yaml
from langchain_community.vectorstores import FAISS
import faiss
from .vector_store_builder import load_documents, file2vector
from langchain_community.docstore.in_memory import InMemoryDocstore
from .file_text_extractor import extract_text_from_file, extract_text_from_TXT
from whoosh.index import open_dir
from whoosh.qparser import QueryParser, OrGroup
from langchain_core.documents import Document
from .embedding_service import (
    EmbeddingServiceUnavailable,
    QwenEmbeddings,
    ensure_vector_store_dir,
    probe_embedding_dimension,
    save_faiss_local_safe,
)
from .entity_vector_builder import get_entity_vector
from .rule_vector_builder import (
    build_rule_entity_vector_store,
    collect_rule_entity_texts,
    load_rule_vector_rows,
    normalize_rule_entry_query,
    rule_record_payload as _rule_record_payload,
    vector_generate,
)
from .llm_clients import llm_config
from ...common.keyword_index import rebuild_keyword_index
from ..shared import (
    CONFIG_PATH,
    USER_VECTOR_STORES_ROOT,
)

__all__ = [
    "Chatzxl",
    "EmbeddingServiceUnavailable",
    "QwenEmbeddings",
    "_rule_record_payload",
    "build_rule_entity_vector_store",
    "collect_rule_entity_texts",
    "ensure_vector_store_dir",
    "get_entity_vector",
    "load_rule_vector_rows",
    "normalize_rule_entry_query",
    "probe_embedding_dimension",
    "save_faiss_local_safe",
    "vector_generate",
]

llm = llm_config()
with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


def prompt_for_RAG_llm(context, question, history=None):
    history_str = ""
    if history and len(history) > 0:
        history_str = '\n\n'.join([f"{message['role']}: {message['content']}" for message in history if message])
    if history_str.strip():
        history_str += "**历史对话**  \n" + history_str
    prompt = f"""
- 目标 -
根据提供的知识库内容，准确回答用户的问题。如果知识库中没有相关信息，请明确告知。

- 角色 -
您扮演的角色是“变压器故障诊断小助手”，专门利用知识库中匹配到的内容为用户提供专业解答。

- 注意事项 -
1. 确保回答与问题完全对应，避免偏离主题。
2. 匹配到的知识存在与问题无关的内容，请注意筛选。充分利用对问题有用知识库内容
3. 如果知识库中没有相关信息，请明确告知用户“当前知识库无法准确回答您的问题，请等待知识库更新...”。
4. 回答应简洁明了，避免冗余信息。

- 知识库内容 -
{"-" * 30}
{context.strip()}
{"-" * 30}

- 问题 -
"{question}"
"""
    return prompt


class Chatzxl:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=cfg["small_models"]["gpt"]["api_key"],
            openai_api_base=cfg["small_models"]["gpt"]["base_url"],
            model=cfg["small_models"]["gpt"]["model_name"],
            temperature=cfg["small_models"]["gpt"].get("temperature", 0.3),
        )

    def init_database(self, bm25_index_dir='bm25_index_dir', vector_index_dir='vector_stores_bge_m3'):
        # self.bm25_retriever = DocumentRetrievalSystem(index_dir=bm25_index_dir)
        self.embeddings = QwenEmbeddings()

    def create_new_vector_stroes(self, user_vector_stores_path):
        user_vector_stores_path = ensure_vector_store_dir(user_vector_stores_path)
        embeddings = self.embeddings
        embedding_dim = probe_embedding_dimension(embeddings)
        index = faiss.IndexFlatL2(embedding_dim)
        vector_stores = FAISS(
            embedding_function=embeddings,
            index=index,
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
        )
        vector_stores.save_local(str(user_vector_stores_path))

    def update_vector_stores(self, file_path, file_name, userId, filetype):
        # 1. 提取文本，并返回可解析的文档
        # json_data, save_path = extract_text_from_file(file_path, file_name, file_type)
        # with lock:
        #     if userId not in user_vars:
        #         # user_vars[userId] = 0
        #         user_vector_storespath[userId] = ""
        #         # user_isuploadFile[userId] = False
        if filetype == 'TXT':
            json_data, save_path = extract_text_from_TXT(file_path, file_name)
        else:
            json_data, save_path = extract_text_from_file(file_path, file_name, filetype)
        if not save_path:
            raise RuntimeError(json_data.get("content") or "文件文本抽取失败")
        docs = load_documents(save_path)
        for doc in docs:
            # 打印文档的唯一标识和标题（假设标题存储在 metadata 中的 "名称" 字段）
            print("Document ID:", doc.metadata.get("id", "N/A"))
            print("Title:", doc.metadata.get("名称", ""))
            print("Content:")
            print(doc.page_content)
            print("=" * 80)
        print("成功加载到用户" + userId + "上传的文档")
        embeddings = self.embeddings

        user_vector_stores_path = USER_VECTOR_STORES_ROOT / userId
        print(11)
        try:
            vector_stores = FAISS.load_local(str(user_vector_stores_path), embeddings,
                                             allow_dangerous_deserialization=True)
        except Exception as e:
            print(str(e))
            self.create_new_vector_stroes(str(user_vector_stores_path))
            vector_stores = FAISS.load_local(str(user_vector_stores_path), embeddings,
                                             allow_dangerous_deserialization=True)
        print(11)
        user_json_path = USER_VECTOR_STORES_ROOT / userId / "doc_rangs.json"
        vector_stores = file2vector(docs, vector_stores, file_name, user_json_path)
        vector_stores.save_local(str(user_vector_stores_path))
        rebuild_keyword_index(user_vector_stores_path)

        print("该文档上传成功！")

    def koquery2kb(self, query, userid):

        rewritten_query = query

        user_vector_stores_path = USER_VECTOR_STORES_ROOT / userid
        user_keyword_index_path = USER_VECTOR_STORES_ROOT / userid / "index"
        vector_stores_user = FAISS.load_local(str(user_vector_stores_path), embeddings=self.embeddings,
                                              allow_dangerous_deserialization=True)
        print("用户知识库" + str(user_vector_stores_path) + "加载完成")

        ix = open_dir(str(user_keyword_index_path))
        print("用户关键词索引" + str(user_keyword_index_path) + "加载完成")
        # 向量库查询
        vector_docs = vector_stores_user.similarity_search(rewritten_query, k=5)
        # 关键词索引查询
        matched_segments = []  # 用来存储匹配到的文档段
        try:
            with ix.searcher() as searcher:
                parser = QueryParser("content", ix.schema, group=OrGroup.factory(0.9))
                query = parser.parse(query)
                results = searcher.search(query, limit=5)
                for hit in results:
                    matched_segments.append(hit.get("content"))
                del results
        finally:
            ix.close()

        docs = [d.metadata for d in vector_docs]
        for d in docs:
            # if "content" in d.keys():
            #     del d['content']
            if "id" in d.keys():
                del d['id']
        contexts = []
        for d in docs:
            # content = f"\n{d['名称']} \n"
            content = ""
            for k, v in d.items():
                if k == '名称':
                    continue
                content += f"\n{k}: {v} \n"
            contexts.append(content)
        # 将向量库中的上下文拼接起来
        final_context = "---------------".join(contexts)
        # 将关键词匹配的段落拼接起来
        matched_context = "\n---------------\n".join(matched_segments)
        # 将二者合并到一起
        final_context = final_context + "\n---------------\n" + matched_context
        # final_context = "\n---------------\n" + matched_context

        history = None
        prompt = prompt_for_RAG_llm(final_context, rewritten_query, history)
        print("prompt生成完成！")
        print(prompt)
        return prompt

    def connect_to_db(self):
        try:
            connection = pymysql.connect(
                host=cfg["KO_database"]["host"],  # 数据库主机
                user=cfg["KO_database"]["user"],  # 数据库用户名
                password=cfg["KO_database"]["password"],  # 数据库密码
                database=cfg["KO_database"]["database"],
                charset=cfg["KO_database"]["charset"]
            )
            return connection
        except pymysql.MySQLError as err:
            print(f"Error: {err}")
            return None

    def resolve_public_theme_vector_userid(self, userid, scene_choose=None):
        """
        判断当前主题是否 public。
        如果是 public，则把 userid 前缀替换成 create_id。

        例如：
            当前用户进来：
            6000917_file_vectorstoregs/gongyiliucheng_6000701

            如果该主题是 public，create_id=6000701

            最终改成：
            6000701_file_vectorstoregs/gongyiliucheng_6000701
        """
        try:
            raw_userid = str(userid)

            # 兼容你现在的主题向量库 userId 形式：
            # 6000917_file_vectorstoregs/gongyiliucheng_6000701
            sep = "_file_vectorstoregs/"

            if sep not in raw_userid:
                print("[RAG权限判断] 当前 userid 不是主题向量库格式，直接使用：", raw_userid)
                return raw_userid

            current_user_id, topic_label = raw_userid.split(sep, 1)

            print("[RAG权限判断] current_user_id:", current_user_id)
            print("[RAG权限判断] topic_label:", topic_label)
            print("[RAG权限判断] scene_choose:", scene_choose)

            connection = self.connect_to_db()

            try:
                with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                    sql = """
                        SELECT 
                            topic_permission,
                            create_id,
                            theme_label,
                            theme_name
                        FROM ko_theme_permission
                        WHERE 
                            theme_label = %s
                            OR theme_name = %s
                        ORDER BY id DESC
                        LIMIT 1
                    """
                    cursor.execute(sql, (topic_label, scene_choose))
                    row = cursor.fetchone()
            finally:
                connection.close()

            if not row:
                print("[RAG权限判断] 未查到主题权限记录，直接使用原 userid：", raw_userid)
                return raw_userid

            topic_permission = row.get("topic_permission")
            create_id = row.get("create_id")
            db_theme_label = row.get("theme_label") or topic_label

            print("[RAG权限判断] topic_permission:", topic_permission)
            print("[RAG权限判断] create_id:", create_id)
            print("[RAG权限判断] db_theme_label:", db_theme_label)

            # 关键逻辑：public 主题使用创建者 id
            if topic_permission == "public" and create_id:
                new_userid = f"{create_id}_file_vectorstoregs/{db_theme_label}"
                print("[RAG权限判断] public主题，切换向量库 userid：", new_userid)
                return new_userid

            print("[RAG权限判断] private主题，继续使用当前 userid：", raw_userid)
            return raw_userid

        except Exception as e:
            print("[RAG权限判断异常] 直接使用原 userid：", userid, e)
            return userid

    def koquery2kb_context_vector_only(self, query, userid, top_k=5, scene_choose=None):
        """
        只做 FAISS 向量检索，返回检索到的文本块。
        不做关键词检索，不生成完整 prompt。
        """
        try:
            if not hasattr(self, "embeddings"):
                self.init_database()

            # =========================
            # 新增：public 主题切换到创建者 id
            # =========================
            # 先走 public/private 权限判断
            userid = self.resolve_public_theme_vector_userid(userid, scene_choose)

            user_vector_stores_path = USER_VECTOR_STORES_ROOT / userid

            # =========================
            # 兼容旧向量库路径
            # 例如：
            # 新路径：6000701_file_vectorstoregs/gongyiliucheng_6000701
            # 旧路径：6000701_file_vectorstoregs/gongyiliucheng
            # =========================
            if not user_vector_stores_path.exists():
                print(f"[RAG向量检索] 标准路径不存在：{user_vector_stores_path}")

                try:
                    sep = "_file_vectorstoregs/"

                    # 权限判断后 userid 可能是：
                    # 6000701_file_vectorstoregs/gongyiliucheng_6000701
                    if sep in userid and scene_choose:
                        owner_id, _ = userid.split(sep, 1)

                        # 旧向量库创建时用的是 han2pinyin_concat(selectedMainScenario)
                        old_topic_label = han2pinyin_concat(scene_choose)

                        fallback_userid = f"{owner_id}_file_vectorstoregs/{old_topic_label}"
                        fallback_path = USER_VECTOR_STORES_ROOT / fallback_userid

                        print(f"[RAG向量检索] 尝试兼容旧路径：{fallback_path}")

                        if fallback_path.exists():
                            print(f"[RAG向量检索] 命中旧向量库路径：{fallback_path}")
                            userid = fallback_userid
                            user_vector_stores_path = fallback_path
                        else:
                            print(f"[RAG向量检索] 旧路径也不存在：{fallback_path}")

                except Exception as e:
                    print("[RAG向量检索] 兼容旧路径失败：", e)

            if not user_vector_stores_path.exists():
                print(f"[RAG向量检索跳过] 向量库不存在：{user_vector_stores_path}")
                return ""

            vector_stores_user = FAISS.load_local(
                str(user_vector_stores_path),
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True
            )

            print(f"[RAG向量检索] 向量库加载完成：{user_vector_stores_path}")

            vector_docs = vector_stores_user.similarity_search(query, k=top_k)

            contexts = []

            for idx, doc in enumerate(vector_docs, start=1):
                page_content = getattr(doc, "page_content", "") or ""
                metadata = getattr(doc, "metadata", {}) or {}

                source_name = (
                        metadata.get("名称")
                        or metadata.get("source_file")
                        or metadata.get("file_name")
                        or metadata.get("source")
                        or "未知来源"
                )

                if page_content.strip():
                    content = page_content.strip()
                else:
                    content_parts = []
                    for k, v in metadata.items():
                        if k in ["id", "名称"]:
                            continue
                        content_parts.append(f"{k}: {v}")
                    content = "\n".join(content_parts).strip()

                if content:
                    contexts.append(
                        f"【原始文档向量召回-{idx}】来源：{source_name}\n{content}"
                    )

            if not contexts:
                return ""

            return "\n\n---------------\n\n".join(contexts)

        except Exception as e:
            print("[RAG向量检索失败]", e)
            return ""


    def filename_vector(self, path, rulename):
        path = ensure_vector_store_dir(path)
        embeddings = QwenEmbeddings()
        vector_stores = FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)
        ntotal = vector_stores.index.ntotal  # 当前向量条数
        latest_chunk_id = ntotal - 1  # 最新已占用 id
        next_chunk_id = latest_chunk_id + 1  # 下一个可用 id
        documents = []
        doc = {'content': rulename, 'id': str(next_chunk_id)}
        documents.append(doc)
        docs = [Document(page_content=d['content'], metadata=d) for d in documents]
        for doc in tqdm(docs, desc="Indexing documents"):
            try:
                vector_stores.add_documents(documents=[doc], ids=[str(next_chunk_id)])
            except Exception as e:
                print(f"Error adding document ID {next_chunk_id}: {e}")
                continue
        vector_stores.save_local(str(path))
        print("文件名存入向量库成功！")

    def index_docs_qwen(
            self,
            vector_stores,
            docs,
            model_client,
            model_name,
            save_path,
            keep_tmp: bool = False,
    ):
        """
        将 docs 向量化并写入 FAISS（支持 LangChain FAISS 的 add_embeddings 或底层索引写入）。
        - 自动选择 JSON 或 TXT 模式（TXT：每页<=10行；JSON：每批<=10条）
        - 并发请求嵌入，指数退避重试；入库单线程（避免 FAISS 线程安全问题）
        - ID 从现有 index.ntotal 自增
        - keep_tmp=True 时保留 TXT 模式生成的临时文件（便于排查）
        """
        # ---------- 依赖 ----------
        import math
        import os
        import random
        import tempfile
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import numpy as np

        # ---------- 常量 ----------
        JSON_MAX_BATCH = 10
        TXT_MAX_LINES = 10
        TXT_SWITCH_BATCH_THRESHOLD = 999999  # 先别切 TXT 模式
        MAX_WORKERS = 4 # 先保守一点，避免接口限流
        TXT_MAX_TOKENS = 8192
        MAX_RETRIES = 8
        BACKOFF_BASE = 0.5

        # ---------- Document 兼容 ----------
        try:
            from langchain_core.documents import Document as _Doc
        except Exception:
            from langchain.docstore.document import Document as _Doc

        # ---------- 工具函数 ----------
        def _approx_tokens(s: str) -> int:
            if not s:
                return 0
            ascii_cnt = sum(1 for ch in s if ord(ch) < 128)
            non_ascii_cnt = len(s) - ascii_cnt
            return int(ascii_cnt / 4 + non_ascii_cnt)

        def _sleep_backoff(attempt: int):
            time.sleep((2 ** attempt) * (BACKOFF_BASE + random.random()))

        def _get_vec(item):
            if hasattr(item, "embedding"):
                return item.embedding
            if isinstance(item, dict) and "embedding" in item:
                return item["embedding"]
            raise TypeError("Unknown embedding item type")

        # ---------- 标准化输入 ----------
        contents, metadatas, doc_objs = [], [], []
        for d in docs:
            if hasattr(d, "page_content"):  # LangChain Document
                pc = str(getattr(d, "page_content", "") or "")
                md = getattr(d, "metadata", {}) or {}
            else:  # 纯字符串
                pc = str(d or "")
                md = {}
            contents.append(pc)
            metadatas.append(md)
            doc_objs.append(_Doc(page_content=pc, metadata=md))  # 始终用安全副本

        if not contents:
            return None

        # 过滤空白文本（避免下游报错）
        keep_idx = [i for i, t in enumerate(contents) if isinstance(t, str) and t.strip() != ""]
        if not keep_idx:
            print("[WARN] no non-empty docs to index")
            return None
        contents = [contents[i] for i in keep_idx]
        metadatas = [metadatas[i] for i in keep_idx]
        doc_objs = [doc_objs[i] for i in keep_idx]

        # ---------- 选择模式 ----------
        total_json_batches = math.ceil(len(contents) / JSON_MAX_BATCH)
        use_txt_mode = total_json_batches > TXT_SWITCH_BATCH_THRESHOLD
        if use_txt_mode and any(_approx_tokens(t) > TXT_MAX_TOKENS for t in contents):
            use_txt_mode = False  # 存在超长行，回退 JSON

        # ---------- 嵌入：TXT 模式 ----------
        def _embed_txt_concurrent(texts: list[str]) -> list[list[float]]:
            def _oneline(s: str) -> str:
                return (s or "").replace("\r\n", " ").replace("\n", " ")

            def _fetch_page(start_idx: int, lines: list[str]):
                tmp_path = None
                for attempt in range(MAX_RETRIES):
                    try:
                        # 写临时 txt（每页<=10行）
                        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as tf:
                            tmp_path = tf.name
                            for line in lines:
                                if _approx_tokens(line) > TXT_MAX_TOKENS:
                                    raise ValueError(f"One line exceeds {TXT_MAX_TOKENS} tokens; please chunk.")
                                tf.write(_oneline(line) + "\n")
                        # 请求 embeddings（部分 SDK 接受句柄，部分接受路径）
                        try:
                            with open(tmp_path, "r", encoding="utf-8") as f:
                                resp = model_client.embeddings.create(model=model_name, input=f)
                        except TypeError:
                            resp = model_client.embeddings.create(model=model_name, input=tmp_path)
                        vecs = [_get_vec(x) for x in resp.data]

                        if keep_tmp:
                            print("[KEEP TMP]", tmp_path)
                        else:
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                        return start_idx, vecs
                    except Exception:
                        if not keep_tmp and tmp_path:
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                        if attempt == MAX_RETRIES - 1:
                            raise
                        _sleep_backoff(attempt)

            pages = [(i, texts[i:i + TXT_MAX_LINES]) for i in range(0, len(texts), TXT_MAX_LINES)]
            results = [None] * len(texts)
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(pages)))) as ex:
                futs = [ex.submit(_fetch_page, start, lines) for start, lines in pages]
                for fut in as_completed(futs):
                    start, vecs = fut.result()
                    results[start:start + len(vecs)] = vecs
            return results

        # ---------- 嵌入：JSON 模式 ----------
        def _embed_json_concurrent(texts: list[str]) -> list[list[float]]:
            def _fetch_batch(start_idx: int, batch: list[str]):
                for attempt in range(MAX_RETRIES):
                    try:
                        import time
                        time.sleep(random.uniform(0.1, 0.4))

                        t0 = time.time()

                        print(
                            f"[Embedding Request] "
                            f"start={start_idx}, batch_size={len(batch)}, attempt={attempt + 1}"
                        )

                        resp = model_client.embeddings.create(
                            model=model_name,
                            input=batch
                        )

                        cost = time.time() - t0
                        print(
                            f"[Embedding Done] "
                            f"start={start_idx}, batch_size={len(batch)}, "
                            f"attempt={attempt + 1}, cost={cost:.2f}s"
                        )

                        vecs = [_get_vec(x) for x in resp.data]

                        if len(vecs) != len(batch):
                            raise ValueError(
                                f"Embedding result size mismatch: input={len(batch)}, output={len(vecs)}"
                            )

                        return start_idx, vecs

                    except Exception as e:
                        print(
                            f"[Embedding Retry] "
                            f"start={start_idx}, batch_size={len(batch)}, "
                            f"attempt={attempt + 1}, err={repr(e)}"
                        )

                        if attempt == MAX_RETRIES - 1:
                            raise

                        _sleep_backoff(attempt)

            batches = [
                (i, texts[i:i + JSON_MAX_BATCH])
                for i in range(0, len(texts), JSON_MAX_BATCH)
            ]

            worker_num = min(MAX_WORKERS, max(1, len(batches)))

            print(f"[Embedding] texts={len(texts)}")
            print(f"[Embedding] JSON_MAX_BATCH={JSON_MAX_BATCH}")
            print(f"[Embedding] batches={len(batches)}")
            print(f"[Embedding] batch_sizes={[len(batch) for _, batch in batches]}")
            print(f"[Embedding] workers={worker_num}")

            results = [None] * len(texts)

            with ThreadPoolExecutor(max_workers=worker_num) as ex:
                futs = [
                    ex.submit(_fetch_batch, start, batch)
                    for start, batch in batches
                ]

                for fut in as_completed(futs):
                    start, vecs = fut.result()
                    results[start:start + len(vecs)] = vecs

            return results

        # ---------- 1) 获取向量 ----------
        all_vecs = _embed_txt_concurrent(contents) if use_txt_mode else _embed_json_concurrent(contents)

        # ---------- 2) 写入 FAISS（ID 自增） ----------
        def _next_start_id(store, default=0) -> int:
            try:
                return int(store.index.ntotal)
            except Exception:
                return default

        start_id = _next_start_id(vector_stores, 0)
        ids = [str(i) for i in range(start_id, start_id + len(contents))]

        try:
            # LangChain FAISS：正确用法是传 (text, embedding) 对
            if hasattr(vector_stores, "add_embeddings"):
                text_emb_pairs = list(zip(contents, all_vecs))
                vector_stores.add_embeddings(text_embeddings=text_emb_pairs, metadatas=metadatas, ids=ids)
            else:
                raise AttributeError("no add_embeddings")
        except Exception:
            # 直接写底层索引 + 同步 docstore
            arr = np.asarray(all_vecs, dtype="float32")
            vector_stores.index.add(arr)
            for _id, d in zip(ids, doc_objs):
                vector_stores.docstore.add({_id: d})
            if hasattr(vector_stores, "index_to_docstore_id"):
                base = len(vector_stores.index_to_docstore_id)
                for k, _id in enumerate(ids):
                    vector_stores.index_to_docstore_id[base + k] = _id

        # ---------- 3) 保存 ----------
        if save_path:
            save_path = ensure_vector_store_dir(save_path)
            print(f"[Save] vector_store_path={save_path}, exists={save_path.is_dir()}")
            save_faiss_local_safe(vector_stores, save_path)

        end_id = int(ids[-1])
        mode = "TXT" if use_txt_mode else "JSON"
        print(f"[OK] Indexed {len(contents)} docs. Mode={mode} | ID range [{start_id}, {end_id}]")
        return end_id

if __name__ == "__main__":
    from .rule_vector_builder import main as rule_vector_main

    rule_vector_main()

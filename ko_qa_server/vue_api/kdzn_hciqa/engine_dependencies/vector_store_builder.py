import os
from uuid import uuid4

import json
from tqdm import tqdm
from langchain_core.documents import Document

from langchain_community.vectorstores import FAISS

from langchain.text_splitter import RecursiveCharacterTextSplitter

import requests
from typing import List
from langchain.embeddings.base import Embeddings

# 全局字典，存储向量库属性
doc_rangs = {}
user_counters = {}
doc_rangs_admin = {}
admin_counters = 0


class BGEApiEmbeddings(Embeddings):
    """
    通过 HTTP 调用本地部署的 bge-m3 Embedding API。
    接口返回 JSON，其中包含 'embedding' 字段。
    """

    def __init__(self):
        self.api_url = "http://10.2.60.75:11434/api/embed"

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量对文本进行向量化。
        这里示例是“一个文本一次请求”，如果 bge-m3 支持批量，可以自行优化。
        """
        embeddings = []
        for text in texts:
            payload = {
                "model": "bge-m3",  # 看你接口里需要什么参数
                "input": text
            }
            resp = requests.post(self.api_url, json=payload)
            resp_data = resp.json()
            # 假设接口返回 {"code":0, "msg":"", "embedding":[...]}，这里取 "embedding"
            embeddings.append(resp_data["embeddings"][0])
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """
        对单条查询进行向量化。
        """
        payload = {
            "model": "bge-m3",
            "input": text
        }
        resp = requests.post(self.api_url, json=payload)
        resp_data = resp.json()
        return resp_data["embeddings"][0]


class QuentinApiEmbeddings(Embeddings):
    """
    通过HTTP调用本地部署的 quentin2/bge-large-zh-v1.5 Embedding API。
    接口返回JSON，其中包含 'embedding' 字段。
    """

    def __init__(self):
        self.api_url = "http://10.2.60.75:11434/v1/embeddings"
        self.model_name = "jeffh/intfloat-multilingual-e5-large-instruct:f16"

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量对文本进行向量化。
        """
        payload = {
            "model": self.model_name,
            "input": texts
        }
        resp = requests.post(self.api_url, json=payload)
        resp.raise_for_status()
        resp_data = resp.json()

        embeddings = [item["embedding"] for item in resp_data["data"]]
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """
        对单条查询进行向量化。
        """
        payload = {
            "model": self.model_name,
            "input": [text]
        }
        resp = requests.post(self.api_url, json=payload)
        resp.raise_for_status()
        resp_data = resp.json()

        return resp_data["data"][0]["embedding"]


# embeddings = BGEApiEmbeddings()
# a=embeddings.embed_query("hello world")
# print(embeddings)
# embedding_dim = len(a)

# db = FAISS.load_local('vector_stores_gpt', embeddings, allow_dangerous_deserialization=True)

# Initialize FAISS index
# index = faiss.IndexFlatL2(embedding_dim)
# vector_store = FAISS(
#     embedding_function=embeddings,
#     index=index,
#     docstore=InMemoryDocstore(),
#     index_to_docstore_id={},
# )

# db = FAISS.load_local('vector_stores_gpt', embeddings, allow_dangerous_deserialization=True)
# file_path = "all_files_content.json"
def merge_incomplete_chunks(chunks, THRESHOLD, sentence_enders=("。", "！", "？")):
    """
    合并初步切分后的块，确保每个块尽可能以句子结束符结尾，同时防止块过长
    参数：
        chunks: 初步切分的文本块列表
        sentence_enders: 被认为是完整句子结束的标点
        max_merged_length: 合并后块允许的最大字符数
    """
    merged_chunks = []
    buffer = ""
    for i, chunk in enumerate(chunks):
        # 将当前块合并到 buffer 中，去除多余空白并添加空格
        buffer = (buffer + " " + chunk.strip()).strip() if buffer else chunk.strip()

        # 当 buffer 超过最大长度时，尝试在最近的句末位置拆分
        if len(buffer) >= THRESHOLD:
            # 在 buffer 的最后 max_merged_length 部分内寻找句子结束符
            split_pos = None
            search_start = max(0, len(buffer) - 100)  # 最多往前找 100 个字符
            for pos in range(len(buffer) - 1, search_start - 1, -1):
                if buffer[pos] in sentence_enders:
                    split_pos = pos + 1  # 包含结束符
                    break
            if split_pos is not None and split_pos < len(buffer):
                # 如果找到了合适的拆分位置，则将前面的部分作为一个块输出
                merged_chunks.append(buffer[:split_pos].strip())
                buffer = buffer[split_pos:].strip()  # 剩余部分保留到 buffer
            else:
                # 如果没找到合适的拆分位置，则直接输出整个 buffer
                merged_chunks.append(buffer)
                buffer = ""
        else:
            # 如果 buffer 长度不足且以句末结束，直接输出
            if buffer and buffer[-1] in sentence_enders:
                merged_chunks.append(buffer)
                buffer = ""
            # 如果不是最后一个块，也不急于输出
            elif i == len(chunks) - 1:
                # 如果到了最后一个块，无论是否以句末结束，都输出
                merged_chunks.append(buffer)
                buffer = ""
    if buffer:
        merged_chunks.append(buffer)
    return merged_chunks


# Load and process documents
def load_documents(file_path):
    # 设定内容切分的阈值，例如 1000 个字符
    THRESHOLD = 250

    # 优化后的分隔符列表（按优先级排序）
    custom_separators = [
        # 按匹配优先度排序
        # 匹配中文序号（一、 二、 等）
        r'\\n+[一二三四五六七八九十]+、',  # 匹配 "一、" 或 "二."
        # 匹配中文括号序号（如：一、二）包含换行
        r'\\n+[(（]+[一二三四五六七八九十]+[）)]',
        # 保留原有的Markdown标题
        "\n## ", "\n### ",
        # 匹配数字编号（如：1.  2.1）
        r'\\n+[\d]+[.]',
        r'\\n+[\d]+[.]+[\d]'
        # 其他通用分隔符
        "\n\n", "\n", "。", "！", "？"
    ]
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=THRESHOLD,
        chunk_overlap=30,
        separators=custom_separators,  # 使用正则表达式
        length_function=len,
        is_separator_regex=True  # 启用正则模式
    )

    # 初始化文本切分工具，设定每个分片最大 THRESHOLD 字符，允许一定重叠（可选）
    # text_splitter = RecursiveCharacterTextSplitter(chunk_size=THRESHOLD, chunk_overlap=30)
    print(f"Loading documents from {file_path}")
    with open(file_path, encoding='utf-8') as fp:
        data = json.load(fp)
    if isinstance(data, dict):
        data = [data]
    documents = []
    chunk_id = 0
    for i, doc in enumerate(data):
        # 假设 JSON 中有两个字段："名称" 作为标题，"内容" 存放 Markdown 格式的文本
        md_text = doc.get('content', '')
        # 将 Markdown 文本转换为 HTML（你也可以选择保留 Markdown）
        # html_content = markdown.markdown(md_text)
        # 将标题和转换后的内容拼接在一起
        content = f"{doc.get('名称', '')}\n{md_text}"
        # 如果内容长度超过阈值，则使用 langchain 的文本切分工具进行切分
        if len(content) > THRESHOLD:
            # 切分过长文档
            chunks = text_splitter.split_text(content)
            # 后处理：合并那些末尾不完整的块
            optimized_chunks = merge_incomplete_chunks(chunks,THRESHOLD)
            for chunk in optimized_chunks:
                new_doc = doc.copy()
                new_doc['content'] = chunk
                # 使用 chunk_id 作为文档 ID，从 0 开始依次递增
                new_doc['id'] = str(chunk_id)
                documents.append(new_doc)
                chunk_id += 1
        else:
            # 不需要切分的文档
            doc['content'] = content
            doc['id'] = str(chunk_id)
            documents.append(doc)
            chunk_id += 1
    return [Document(page_content=d['content'], metadata=d) for d in documents]


# documents.extend(docs)
# docs = load_documents(file_path)

def file2vector_admin(documents, vector_store, filename, json_path="upload_file_admin/doc_rangs_admin.json"):
    # 加载已有记录（如果存在）
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            doc_rangs_admin = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        doc_rangs_admin = {}

    # 获取当前最大ID作为起始ID
    existing_ids = [id_range[1] for id_range in doc_rangs_admin.values() if isinstance(id_range, list)]
    admin_counters = max(existing_ids, default=-1) + 1

    start_id = admin_counters

    for doc in tqdm(documents, desc="Indexing documents"):
        current_id = admin_counters
        try:
            vector_store.add_documents(documents=[doc], ids=[str(current_id)])
        except Exception as e:
            print(f"Error adding document ID {current_id}: {e}")
            continue
        admin_counters += 1

    ending_id = admin_counters - 1
    doc_rangs_admin[filename] = [start_id, ending_id]

    # 更新记录到json文件
    with open(json_path, 'w', encoding='utf-8') as file:
        json.dump(doc_rangs_admin, file, ensure_ascii=False, indent=4)

    return vector_store


def process_and_index_documents(file_path, vector_store, json_path="upload_file_admin/doc_rangs_admin.json"):
    global admin_counters

    THRESHOLD = 500
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=THRESHOLD, chunk_overlap=30)

    # 加载已有记录（如果存在）
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            doc_rangs_admin = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        doc_rangs_admin = {}

    print(f"Loading and processing documents from {file_path}")
    with open(file_path, encoding='utf-8') as fp:
        data = json.load(fp)
    if isinstance(data, dict):
        data = [data]

    documents = []
    chunk_id = 0

    for doc in data:
        doc_name = doc.get('名称', f"Unnamed_{chunk_id}")
        md_text = doc.get('content', '')
        # 拼接标题和内容
        content = f"{doc_name}\n{md_text}"

        # 记录当前文档切分的起始 chunk_id
        start_chunk_id = chunk_id

        # 如果内容超过阈值，则切分成多个片段
        if len(content) > THRESHOLD:
            chunks = text_splitter.split_text(content)
            for chunk in chunks:
                print(chunk)
                new_doc = doc.copy()  # 保留原文档其他信息
                new_doc['content'] = chunk  # 更新为当前切分后的片段
                new_doc['id'] = str(chunk_id)
                # 创建 Document 对象时，将完整文档字典作为 metadata 传入
                documents.append(Document(page_content=chunk, metadata=new_doc))
                chunk_id += 1
        else:
            # 文档内容不需要切分，直接更新内容与 id
            new_doc = doc.copy()
            new_doc['content'] = content
            new_doc['id'] = str(chunk_id)
            documents.append(Document(page_content=content, metadata=new_doc))
            chunk_id += 1

        # 更新该文档在 json 记录中的范围（起始和结束 chunk_id）
        doc_rangs_admin[doc_name] = [start_chunk_id, chunk_id - 1]

    start_id = admin_counters

    # 将处理后的文档添加到向量存储中
    for doc in tqdm(documents, desc="Indexing documents"):
        current_id = admin_counters
        try:
            vector_store.add_documents(documents=[doc], ids=[str(current_id)])
        except Exception as e:
            print(f"Error adding document ID {current_id}: {e}")
            continue
        admin_counters += 1

    ending_id = admin_counters - 1

    # 将更新后的记录写入 json 文件
    with open(json_path, 'w', encoding='utf-8') as file:
        json.dump(doc_rangs_admin, file, ensure_ascii=False, indent=4)

    print(f"Processed document ID range: ({start_id}, {ending_id})")
    print(f"Updated {json_path} content:", doc_rangs_admin)

    return vector_store


def file2vector(documents, vector_store, filename, json_path):
    # 加载或初始化json文件
    if os.path.exists(json_path):
        with open(json_path, "r", encoding='utf-8') as f:
            doc_rangs = json.load(f)
    else:
        doc_rangs = {}

    # 确定起始id
    if doc_rangs:
        # 取已有最大结束id后+1作为起始
        start_id = max(end for _, end in doc_rangs.values()) + 1
    else:
        start_id = 0

    current_id = start_id
    for doc in tqdm(documents, desc="Indexing documents"):
        try:
            vector_store.add_documents(documents=[doc], ids=[str(current_id)])
        except Exception as e:
            print(f"Error adding document ID {current_id}: {e}")
            continue
        current_id += 1

    ending_id = current_id - 1

    # 更新json文件信息
    doc_rangs[filename] = [start_id, ending_id]

    # 写回json文件
    with open(json_path, "w", encoding='utf-8') as f:
        json.dump(doc_rangs, f, ensure_ascii=False, indent=4)

    print("Updated doc_rangs:", doc_rangs)
    return vector_store


def file2vector_1(documents, vector_store):
    batch_size = 10

    for i in tqdm(range(0, len(documents), batch_size), desc="Indexing documents"):
        batch = documents[i:i + batch_size]
        # # for idx, doc in enumerate(batch):
        # #     print(f"Item {idx}")
        # #     print("Type:", type(doc))
        #
        ids = [str(uuid4()) for _ in batch]

        try:
            vector_store.add_documents(documents=batch, ids=ids)
        except Exception as e:
            print(f"Error adding documents: {e}")
    return vector_store


# vector_store = file2vector(docs, vector_store)
# # # Save vector store
# vector_store.save_local('vector_stores_bge_m3')

# Perform similarity search
# def search(query, k=2):
#     results = vector_store.similarity_search(query, k=k)
#     for res in results:
#         print(f"* {res.page_content} [{res.metadata}]")
#
# search("李医生")

# a_query = ""
# results = vector_store.similarity_search_with_score(query=a_query,k=3)
#
# for index, (doc, score) in enumerate(results):
#     print(f"[{index}][SIM={score:3f}]{doc.page_content} [{doc.metadata}]")


# query_vector = query_embedder.embed_query(a_query)
# results = db.similarity_search_by_vector(query_vector, k=3)
# for index, doc in enumerate(results):
#     print(f"[{index}]{doc.page_content} [{doc.metadata}]")

""" 带 score 版本
results = db.similarity_search_with_relevance_scores(query_vector, k=3)
for index, (doc, score) in enumerate(results):
    print(f"[{index}][SIM={score:3f}]{doc.page_content} [{doc.metadata}]")
"""


def check_same_doc(vector_store, vec_path):
    # 删除重复文档
    duplicate_ids = []
    seen_texts = set()
    for i, doc_id in vector_store.index_to_docstore_id.items():
        print(f"[{i}] {doc_id}")
        doc = vector_store.docstore.search(doc_id)
        # if not doc:
        #     continue

        content = doc.page_content.strip()
        #
        if content in seen_texts:
            # 这个文档内容已经出现过，视为重复
            duplicate_ids.append(doc_id)
        else:
            seen_texts.add(content)
    #
    print("需要删除的重复文档ID:", duplicate_ids)
    if len(duplicate_ids) > 0:
        vector_store.delete(ids=duplicate_ids)
        vector_store.save_local(vec_path)
        print("向量库保存到" + vec_path + "。重复文档已经删除！")
    else:
        print("没有重复文档！")


# embeddings = QuentinApiEmbeddings()
# # vector_stores = FAISS.load_local('vector_stores_multilingual-e5-large-instruct(200)', embeddings, allow_dangerous_deserialization=True)
# # #
# # check_same_doc(vector_stores, 'vector_stores_multilingual-e5-large-instruct(200)')
# a=embeddings.embed_query("hello world")
# # rewritten_query = "介绍一下熙泰公司"
# # vector_docs = vector_stores.similarity_search(rewritten_query, k=20)
# # #
# # for res in vector_docs:
# #     print(f"* {res.page_content} ")
# #     print("--------------------------------")
# # print(embeddings)
# embedding_dim = len(a)
# index = faiss.IndexFlatL2(embedding_dim)
# vector_stores = FAISS(
#     embedding_function=embeddings,
#     index=index,
#     docstore=InMemoryDocstore(),
#     index_to_docstore_id={},
# )
# vector_stores.save_local('vector_stores_multilingual-e5-large-instruct(500)')
# vector_stores = process_and_index_documents(file_path, vector_stores)
# vector_stores.save_local('vector_stores_multilingual-e5-large-instruct(500)')

def user_delete_file(userid, filename):
    embeddings = BGEApiEmbeddings()
    from ..shared import USER_VECTOR_STORES_ROOT

    user_vector_stores_path = str(USER_VECTOR_STORES_ROOT / userid)
    vector_stores = FAISS.load_local(user_vector_stores_path, embeddings,
                                     allow_dangerous_deserialization=True)
    if userid not in doc_rangs:
        print("User {userid} not found")
        return {"message:" f"User {userid} not found."}
    user_doc = doc_rangs[userid]
    if filename not in user_doc:
        print("File {filename} not found.")
        return {"message:" f"File {filename} not found."}
    start_id, end_id = user_doc[filename]
    duplicate_ids = [str(i) for i in range(start_id, end_id + 1)]
    try:
        vector_stores.delete(ids=duplicate_ids)
        vector_stores.save_local(user_vector_stores_path)
        print("成功删除" + userid + "的向量库中的" + filename)
    except Exception as e:
        print("删除出错！")
        return {"message:" f"Error delete vector store: {e}."}

    del user_doc[filename]

    return {"message:" f"用户{userid}向量库里面的{filename} 成功删除！"}


def admin_delete_file(filename):
    # 1. 从 doc_rangs_admin.json 中加载已有的记录
    try:
        with open("upload_file_admin/doc_rangs_admin.json", "r", encoding="utf-8") as file:
            doc_rangs_admin = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        doc_rangs_admin = {}

    embeddings = QuentinApiEmbeddings()
    admin_vector_stores_path = "vector_stores_multilingual-e5-large-instruct(500)"
    vector_stores = FAISS.load_local(
        admin_vector_stores_path,
        embeddings,
        allow_dangerous_deserialization=True
    )

    # 2. 检查该 filename 是否在记录中
    if filename not in doc_rangs_admin:
        print(f"File {filename} not found.")
        return {"message": f"File {filename} not found."}

    # 3. 获取对应 ID 范围并删除向量
    start_id, end_id = doc_rangs_admin[filename]
    duplicate_ids = [str(i) for i in range(start_id, end_id + 1)]
    try:
        vector_stores.delete(ids=duplicate_ids)
        vector_stores.save_local(admin_vector_stores_path)
        print(f"成功删除全局向量库里的 {filename}")
    except Exception as e:
        print("删除出错")
        return {"message": f"Error delete vector store: {e}."}

    # 4. 从内存和 JSON 文件中移除对该文件的记录
    del doc_rangs_admin[filename]
    with open("upload_file_admin/doc_rangs_admin.json", "w", encoding="utf-8") as file:
        json.dump(doc_rangs_admin, file, ensure_ascii=False, indent=4)

    return {"message": f"File {filename} 成功删除！"}

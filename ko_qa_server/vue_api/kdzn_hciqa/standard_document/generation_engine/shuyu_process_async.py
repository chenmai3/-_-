import os.path

import torch
from sqlalchemy import create_engine
import pandas as pd
from sentence_transformers import SentenceTransformer, util
import numpy as np
import re
from .qwen80b_chat import chat_async
from .extract_util import detect_sep_symbol
from pathlib import Path
from ...shared import load_config

BASE_DIR = Path(__file__).resolve().parent

TERM_NAME_CN = 'term_name'
TERM_NAME_EN = 'term_name_en'
TERM_EXPLAIN = 'term_explain'
TERM_SOURCE = 'term_source'

OUTPUT_PATTERN = re.compile(
    r"中文名称：(.+?)\s*"
    r"英文名称：(.+?)\s*"
    r"中文解释：(.+?)\s*"
    r"相似术语候选：(.+?)\s*"
    r"\*\*是否替换：(.+?)\*\*\s*"
    r"\*\*推荐替换术语：(.+?)\*\*\s*",
    re.S
)


# 去掉本地术语库中中文解释没必要的信息
def clean_local_term_explain(local_term_explain):
    pattern = r'\s*\[[^\]]*\]$'  # 匹配末尾的方括号内容
    return re.sub(pattern, '', local_term_explain)


# 将本地术语库转为更适合生成embeddings的句式
def format_local_term(local_term):
    # 更结构化的方式
    return f"术语：{local_term['term_name']} 解释：{clean_local_term_explain(local_term['term_explain'])}"


# 将LLM抽取术语库转为更适合生成embeddings的句式
def format_gen_term(gen_term) -> str:
    return f"术语：{gen_term[0]} 解释：{gen_term[2]}"


def process_df_source(df):
    df[TERM_SOURCE] = df[TERM_EXPLAIN].str.extract(r'')


# 生成csv文件保存数据库文件，生成数据库中'术语解释'的所有embeddings并保存到本地，便于后续直接本地调取
def gen_and_save_df_and_embeddings(
        sql_table_name='bz_terminology',
        csv_prefix='bz_terminology',
        model_name='bge-large-zh',
        save_path=None,
        device='cuda'):
    save_path = Path(save_path) if save_path is not None else BASE_DIR / "cache"
    cfg = load_config()
    ko_db = cfg["KO_database"]
    db_connection_str = os.getenv(
        "STANDARD_TERMBASE_DB_URL",
        (
            f"mysql+pymysql://{ko_db['user']}:{ko_db['password']}@"
            f"{ko_db['host']}/{ko_db['database']}?charset=utf8mb4"
        ),
    )

    # 创建引擎
    engine = create_engine(db_connection_str)
    model_path = Path(os.getenv("STANDARD_BGE_MODEL_PATH", BASE_DIR / model_name))
    model = SentenceTransformer(model_path).to(device)
    model.eval()
    try:
        if not save_path.exists():
            save_path.mkdir(parents=True, exist_ok=True)
            print(f"文件夹 '{save_path}' 已创建")
        else:
            print(f"文件夹 '{save_path}' 已存在")
        df_save_path = save_path / f'{csv_prefix}.csv'
        embeddings_save_path = save_path / f'{model_name}_local_termbase_embeddings.npy'

        # 读取整个表
        df = pd.read_sql_table(sql_table_name, engine)

        df = process_df_source(df)

        # 保存到CSV文件
        df.to_csv(df_save_path, index=False, encoding='utf-8-sig')
        print(f"数据已保存到 {save_path}/{csv_prefix}.csv")

        # 保存embeddings到本地
        df['combined_text'] = df.apply(format_local_term, axis=1)
        embeddings = model.encode(df['combined_text'].tolist(), convert_to_tensor=True)
        np.save(embeddings_save_path, embeddings.cpu().numpy())
        print(f"\'术语：xxx 解释：xxx\'格式的Embeddings已保存到 {embeddings_save_path}")

    except Exception as e:
        print(f"错误: {e}")


def load_df_and_embeddings(csv_prefix='bz_terminology', model_name='bge-large-zh',
                           save_path=None):
    save_path = Path(save_path) if save_path is not None else BASE_DIR / "cache"
    df_save_path = save_path / f'{csv_prefix}.csv'
    embeddings_save_path = save_path / f'{model_name}_local_termbase_embeddings.npy'
    df = pd.read_csv(df_save_path, encoding="utf-8-sig")
    embeddings = np.load(embeddings_save_path)
    return df, embeddings


def load_df(csv_prefix='bz_terminology', save_path=None):
    save_path = Path(save_path) if save_path is not None else BASE_DIR / "cache"
    df_save_path = save_path / f'{csv_prefix}.csv'
    return pd.read_csv(df_save_path, encoding="utf-8-sig")


def load_embeddings(model_name='bge-large-zh', save_path=None):
    save_path = Path(save_path) if save_path is not None else BASE_DIR / "cache"
    embeddings_save_path = save_path / f'{model_name}_local_termbase_embeddings.npy'
    return np.load(embeddings_save_path)


def get_terms(inputs):
    '''
    从大模型在正文中提取的术语中获取其中的术语信息，并用结构对象存储
    :param inputs: 满足shuyu_content定义的输出结构
    :return: 二维列表，[][3]，第一维对应不同术语，第二维对应术语：[中文名称，英文名称，中文解释]
    '''
    inputs = inputs.split('\n')
    terms = []
    for info in inputs:
        if info.strip() == '':
            continue
        sep = detect_sep_symbol(info)
        term = info.split(sep)
        if len(term) == 3:
            terms.append(term)
    return terms


# 找到术语库中与其匹配的topk个术语
def match(terms, model_name='bge-large-zh', topk=10, batch_size=32, threshold=0.8, device='cuda'):
    '''
    :param terms: 术语：List[List[中文名称，英文名称，中文解释]]
    :param model_name:
    :param topk: 选取相似度最高的topk个本地术语
    :param batch_size: 每轮处理的数量
    :return: 输入所有术语在本地术语库中相似度最高的topk个术语的索引
    '''

    if not terms:
        return []
    path = Path(os.getenv("STANDARD_BGE_MODEL_PATH", BASE_DIR / model_name))
    if not path.is_dir():
        raise FileNotFoundError("未找到标准术语匹配模型，请设置 STANDARD_BGE_MODEL_PATH 指向 bge-large-zh 模型目录。")
    if device == 'cuda' and not torch.cuda.is_available():
        device = 'cpu'
    path = str(path)
    model = SentenceTransformer(path).to(device)
    model.eval()
    local_termbase_embeddings = load_embeddings()
    all_topk_indices = []
    for i in range(0, len(terms), batch_size):
        batch_terms = terms[i:i + batch_size]
        batch_gen_embeddings = model.encode(
            [format_gen_term(term) for term in batch_terms],
            convert_to_tensor=True).cpu().numpy()
        # 计算相似度
        batch_similarities = util.cos_sim(batch_gen_embeddings, local_termbase_embeddings)
        # 取相似度最高的 topk 索引
        batch_topk = torch.topk(batch_similarities, k=min(topk, batch_similarities.shape[1]), dim=1)
        batch_topk_indices = batch_topk.indices
        batch_topk_values = batch_topk.values
        # 根据阈值过滤
        filtered_indices = []
        for row_indices, row_values in zip(batch_topk_indices, batch_topk_values):
            valid = row_indices[row_values > threshold]
            if len(valid) == 0:
                # 如果没有超过阈值的，添加占位符（如 -1）
                filtered_indices.append([-1])
            else:
                filtered_indices.append(valid.tolist())
        all_topk_indices.extend(filtered_indices)
    return all_topk_indices


def chat_prepare(terms, match_indices):
    '''
    :param terms: List[List[中文名称，英文名称，中文解释]]
    :param match_indices: List[List[idx,...]]
    :return:
    messages：前置系统信息prompt
    user_contents：每个术语对应的用户信息prompts
    前者和后者每项拼接即可一次对话
    '''
    df = load_df()
    user_contents = []
    for i, term in enumerate(terms):
        # 如果match_indices为-1，则跳过
        if match_indices[i] == [-1]:
            user_contents.append(None)
            continue
        # 生成输入信息
        user_content = (
            f'### 原始术语\n'
            f'中文名称：{term[0]}\n'
            f'英文名称：{term[1]}\n'
            f'中文解释：{term[2]}\n'
            f'### 候选相似术语\n')
        for idx, candidate_idx in enumerate(match_indices[i]):
            candidate_term = df.iloc[candidate_idx].to_dict()
            user_content += (
                f'{idx + 1}. 中文名称：{candidate_term[TERM_NAME_CN]}\n'
                f'   英文名称：{candidate_term[TERM_NAME_EN]}\n'
                f'   中文解释：{candidate_term[TERM_EXPLAIN]}\n')
        user_contents.append({"role": "assistant", "content": user_content})
    return user_contents


def shuyu_process_chat(user_contents):
    path = BASE_DIR / "prompt" / "3shuyu_select_prompt.md"
    with open(path, 'r', encoding='utf-8') as file:
        system_prompt = file.read()
    file.close()
    messages = {"role": "system", "content": system_prompt}
    ignore_idx, messages_list = [], []
    for i, msg in enumerate(user_contents):
        if msg is None:
            ignore_idx.append(i)
            continue
        messages_list.append([messages, user_contents[i]])
    results = chat_async(messages_list, "术语匹配")
    return results, ignore_idx


def process(terms, match_indices, chat_results, ignore_idx):
    df = load_df()
    res = []
    count = 0
    for i, term in enumerate(terms):
        if i in ignore_idx:
            res.append([term])
            continue
        for replace_output in OUTPUT_PATTERN.findall(chat_results[count]):
            # replace_output:列表[原始术语中文，原始术语英文，原始术语中文解释，候选替换术语，是否替换，替换术语，替换原因]
            if replace_output[4].strip() == '是':
                # replace_output[5]是替换术语，如果替换，则格式为"1. 替换术语中文名"。1指示其在所有候补替换术语的顺序序号（从1开始）
                idx_and_name = replace_output[5].strip().split('.')
                if not idx_and_name[0].isdigit():
                    print(f"[Warning] 非数字序号：{idx_and_name[0]}，跳过此项")
                    res.append([term])
                    continue
                idx = int(idx_and_name[0]) - 1
                replace_shuyu = df.iloc[match_indices[i][idx]].to_dict()
                # 判断中文名称是否一致，避免大模型输出错误
                if idx_and_name[1].strip() == replace_shuyu[TERM_NAME_CN].strip():
                    res.append([term, replace_shuyu])
            elif replace_output[4].strip() == '否':
                res.append([term])
        count += 1
    return res


def shuyu_process(inputs, model_name='bge-large-zh', topk=10):
    '''
    返回的original_and_replace结构：
    List[List[原始术语信息，替换术语信息]]，
    '''
    terms = get_terms(inputs)
    match_indices = match(terms, model_name=model_name, topk=topk)
    user_contents = chat_prepare(terms, match_indices)
    chat_results, ignore_idx = shuyu_process_chat(user_contents)
    for result in chat_results:
        print(result, '\n')
    replace_info = process(terms, match_indices, chat_results, ignore_idx)
    return replace_info

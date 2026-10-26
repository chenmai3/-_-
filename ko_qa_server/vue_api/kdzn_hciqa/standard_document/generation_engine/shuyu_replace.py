from .api import chat
from .shuyu_process_async import shuyu_process
from pathlib import Path
import re


BASE_DIR = Path(__file__).resolve().parent

TERM_NAME = 'term_name'
TERM_EXPLAIN = 'term_explain'
TERM_NAME_EN = 'term_name_en'
TERM_STANDARD_CODE = 'standard_code'
TERM_STANDARD_NAME = 'standard_name'
TERM_ENTRY_NUMBER = 'entry_number'
TITLE_PATTERN = re.compile(r'^#{1,6}\s*\d+(?:\.\d+)*\s*')


def shuyu_replace_llm(shuyu, zhengwen, topk=10):
    '''
    1.使用'术语：[术语名称] 解释：[术语解释]'的输入构建embedding，进行相似度匹配，在本地术语库中选取topk
    2.直接替换：将替换术语直接粘贴到正文
    3.以标准化文档markdown格式输出‘3 术语和定义’
    :param shuyu: 传入LLM生成的术语信息
    :param zhengwen: 传入LLM生成的正文信息
    :param topk: 术语相似度匹配时，在术语库中选择topk个匹配度最高的术语
    :return: 返回列表：每一项由原始术语和替换术语（如有）组成的子列表组成。
                其中，原始术语内部结构List[中文名称，英文名称，中文解释]
                    替换术语：Dict{}，内部索引和信息同sql库
    '''
    replace_info = shuyu_process(shuyu, topk=topk)

    with open(BASE_DIR / 'prompt' / '3shuyu_replace_prompt.md', 'r', encoding='utf-8') as f:
        system_content = f.read()
    f.close()

    messages = [{"role": "system", "content": system_content}]
    replace_content = '# 正文\n' + zhengwen + '\n\n' + '# 原始术语和替换术语\n'
    for term in replace_info:
        if len(term) == 2:
            replace_content += f'原始术语：{term[0][0]} 替换术语：{term[1][TERM_NAME]}\n'
    messages.append({"role": "user", "content": replace_content})
    chat(messages)

    format_shuyu_output(replace_info)
    return replace_info


def shuyu_appear_once_process(zhengwen, term_name, term_explain):
    # 替换术语仅出现一次，直接在术语后面加括号解释
    index = zhengwen.find(term_name)
    if index != -1:
        # 找出 index 所在的行范围
        line_start = zhengwen.rfind('\n', 0, index) + 1
        line_end = zhengwen.find('\n', index)
        if line_end == -1:
            line_end = len(zhengwen)
        current_line = zhengwen[line_start:line_end].strip()
        # 检查是否是标题行
        if not TITLE_PATTERN.match(current_line):
            ins_pos = index + len(term_name)
            zhengwen = (
                    zhengwen[:ins_pos]
                    + f'（{term_explain}）'
                    + zhengwen[ins_pos:]
            )
    return zhengwen


def shuyu_replace(shuyu, zhengwen, model_name='bge-large-zh', topk=10):
    '''
    1.使用'术语：[术语名称] 解释：[术语解释]'的输入构建embedding，进行相似度匹配，在本地术语库中选取topk
    2.直接替换：将替换术语直接粘贴到正文
    3.以标准化文档markdown格式输出‘3 术语和定义’
    :param shuyu: 传入LLM生成的术语信息
    :param zhengwen: 传入LLM生成的正文信息
    :param topk: 术语相似度匹配时，在术语库中选择topk个匹配度最高的术语
    :return:
    shuyu: 格式化术语和定义输出，可直接print
    zhengwen：已替换的格式化正文输出，可直接print
    replace_info: 返回列表：每一项由原始术语和替换术语（如有）组成的子列表组成。
                其中，原始术语内部结构List[中文名称，英文名称，中文解释]
                    替换术语：Dict{}，内部索引和信息同sql库
    '''
    replace_info = shuyu_process(shuyu, model_name=model_name, topk=topk)

    idx_shuyu_appear_zero_one_time = []
    for i, info in enumerate(replace_info):
        if len(info) == 2:
            count = zhengwen.count(info[1][TERM_NAME])
            if count > 0:
                zhengwen = zhengwen.replace(info[0][0], info[1][TERM_NAME])
                # 避免替换后该术语次数反而增多，再判断一次
                if zhengwen.count(info[1][TERM_NAME]) == 1:
                    idx_shuyu_appear_zero_one_time.append(i)
                    # 替换术语仅出现一次，直接在术语后面加括号解释
                    zhengwen = shuyu_appear_once_process(zhengwen, term_name=info[1][TERM_NAME],
                                                         term_explain=info[1][TERM_EXPLAIN])
            else:
                idx_shuyu_appear_zero_one_time.append(i)
        elif len(info) == 1:
            # 无替换术语，当术语仅出现一次时，直接在术语后面加括号解释
            count = zhengwen.count(info[0][0])
            if count == 1:
                idx_shuyu_appear_zero_one_time.append(i)
                zhengwen = shuyu_appear_once_process(zhengwen, term_name=info[0][0], term_explain=info[0][2])
            elif count == 0:
                idx_shuyu_appear_zero_one_time.append(i)

    shuyu = format_shuyu_output(replace_info, idx_shuyu_appear_zero_one_time)
    return shuyu, zhengwen, replace_info


# 去掉本地术语库中中文解释没必要的信息
def clean_local_term_explain(local_term_explain):
    pattern = r'\s*\[[^\]]*\]$'  # 匹配末尾的方括号内容
    return re.sub(pattern, '', local_term_explain)


def format_shuyu_output(terms, idx_shuyu_appear_zero_one_time) -> str:
    '''
    markdown格式标准化输出'3 术语和定义'章节
    :param terms: 列表List：每一项由原始术语和替换术语（如有）组成的子列表组成。
                其中，原始术语内部结构List[中文名称，英文名称，中文解释]
                    替换术语：Dict{}，内部索引和信息同sql库
    :return: 标准化文档markdown格式输出‘3 术语和定义’的字符串
    '''
    output = '# 3 术语和定义\n\n下列术语和定义适用于本文件。\n\n'
    j = 0
    for i, term in enumerate(terms):
        if i in idx_shuyu_appear_zero_one_time:
            continue
        output += f'## 3.{j + 1}\n'
        if len(term) == 2:
            output += f'**{term[1][TERM_NAME]}**    **{term[1][TERM_NAME_EN]}**\n\n{clean_local_term_explain(term[1][TERM_EXPLAIN])}\n\n'
            output += f'[来源：{term[1][TERM_STANDARD_CODE]}，{term[1][TERM_ENTRY_NUMBER]}]\n\n'
        else:
            output += f'**{term[0][0]}**    **{term[0][1]}**\n\n{term[0][2]}\n\n'
        j += 1

    output = output.strip()
    return output

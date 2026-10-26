from .yinyong_process import yinyong_process
from .zhengwen_process import process1
from .qwen80b_chat import chat
from .shuyu_replace import shuyu_replace
from .qwen80b_chat import run_stage_with_progress
from pathlib import Path
from .md2json import title2json


BASE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(__file__).resolve().parent


def gen_yinyan_fanwei_yinyong_stream(zhengwen, shuyu_replace_info):
    '''
    生成 引言 范围 规范性引用章节
    :param zhengwen: 完整的正文输入
    :return:
    '''
    # 引言
    path = BASE_DIR / "prompt" / "0yinyan_content.md"
    with open(path, 'r', encoding='utf-8') as file:
        yinyan_content = file.read()
    yinyan_messages = [
        {"role": "system", "content": yinyan_content},
        {"role": "user", "content": zhengwen}
    ]
    # 范围
    path = BASE_DIR / "prompt" / "1fanwei_content.md"
    with open(path, 'r', encoding='utf-8') as file:
        fanwei_content = file.read()
    fanwei_messages = [
        {"role": "system", "content": fanwei_content},
        {"role": "user", "content": zhengwen}
    ]
    # 规范性引用文件
    path = BASE_DIR / "prompt" / "2yinyong_content.md"
    with open(path, 'r', encoding='utf-8') as file:
        yinyong_system_content = file.read()
    yinyong_messages = [
        {"role": "system", "content": yinyong_system_content},
        {"role": "user", "content": zhengwen}
    ]

    results = yield from run_stage_with_progress(
        messages_list=[yinyan_messages, fanwei_messages, yinyong_messages],
        task_name="生成 引言、范围和规范性引用文件",
        status_section="yinyan-fanwei-yinyong_liucheng",
        model=None,
        max_concurrency=3,  # 3 个并发刚好
    )

    yinyan, fanwei, yinyong = results
    yinyong = yinyong_process(yinyong, shuyu_replace_info, zhengwen)

    if '# 引言' not in yinyan:
        yinyan = '# 引言\n' + yinyan
    if '# 1 范围' not in fanwei:
        fanwei = '# 1 范围\n' + fanwei

    return yinyan, fanwei, yinyong


def gen_qianyan(input_content, stream=True):
    with open(BASE_DIR / 'prompt' / '0qianyan_content.md', 'r', encoding='utf-8') as file:
        qianyan_content = file.read()
    qianyan_messages = [
        {"role": "system", "content": qianyan_content},
        {"role": "user", "content": input_content}
    ]
    qianyan = chat(qianyan_messages, stream=stream)
    if '# 前言' not in qianyan:
        qianyan = '# 前言\n' + qianyan
    return qianyan


def gen_dagang(input_content, stream=True):
    with open(BASE_DIR / 'prompt' / 'dagang_content.md', 'r', encoding='utf-8') as file:
        dagang_content = file.read()
    dagang_messages = [
        {"role": "system", "content": dagang_content},
        {"role": "user", "content": input_content}
    ]
    dagang = chat(dagang_messages, stream=stream)
    return dagang


def gen_zhengwen(dagang, input_content):
    '''
    此处生成的正文并不是最终结果，在经过术语抽取后，还要对正文中对应的内容进行修改
    :param dagang:
    :param input_content:
    :return:
    '''
    chapter_outputs = process1(dagang, input_content)
    return chapter_outputs


def gen_shuyu(zhengwen, stream=True, model_name='bge-large-zh'):
    with open(BASE_DIR / 'prompt' / '3shuyu_content.md', 'r', encoding='utf-8') as file:
        shuyu_system_content = file.read()
    shuyu_messages = [
        {"role": "system", "content": shuyu_system_content},
        {"role": "user", "content": zhengwen}
    ]
    # 此处是直接使用LLM抽取正文得到的术语
    shuyu = chat(shuyu_messages, stream=stream)
    shuyu, zhengwen, shuyu_replace_info = shuyu_replace(shuyu, zhengwen, model_name=model_name)
    return shuyu, zhengwen, shuyu_replace_info


def gen_title(input_content, zhengwen, stream=True, chat_model_name=None):
    title_markdown = title(input_content, zhengwen, stream, model_name=chat_model_name)
    title_json = title2json(title_markdown)
    return title_markdown, title_json


def title(input_content, zhengwen, stream=True, model_name=None):
    path = BASE_DIR / "prompt" / "title.md"
    with open(path, 'r', encoding='utf-8') as file:
        messages = [
            {"role": "system", "content": file.read()},
            {"role": "user", "content": f'## 说明内容\n{input_content}\n\n## 正文\n{zhengwen}'}
        ]
    title = chat(messages, stream=stream, model=model_name)
    return title

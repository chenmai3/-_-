import re
from pathlib import Path

from .qwen80b_chat import chat_async

# from extract_util import extract_content_without_error
from .zhengwen_polish import zhengwen_polish
BASE_DIR = Path(__file__).resolve().parent

FORMULA_SYMBOLS = [
    r'<formula>', r'</formula>', r'<\formula>', r'{formula}', r'{\formula}', r'{/formula}',
    r'<FORMULA>', r'</FORMULA>', r'<\FORMULA>', r'{FORMULA}', r'{\FORMULA}', r'{/FORMULA}', ]
TABLE_SYMBOLS = [
    r'<table>', r'</table>', r'<\table>', r'{table}', r'{\table}', r'{/table}',
    r'<TABLE>', r'</TABLE>', r'<\TABLE>', r'{TABLE}', r'{\TABLE}', r'{/TABLE}', ]
CONTENT_SYMBOLS = [
    r'<content>', r'</content>', r'<\content>', r'{content}', r'{\content}', r'{/content}',
    r'<CONTENT>', r'</CONTENT>', r'<\CONTENT>', r'{CONTENT}', r'{\CONTENT}', r'{/CONTENT}', ]
CAPTION_SYMBOLS = [
    r'<caption>', r'</caption>', r'<\caption>', r'{caption}', r'{\caption}', r'{/caption}',
    r'<CAPTION>', r'</CAPTION>', r'<\CAPTION>', r'{CAPTION}', r'{\CAPTION}', r'{/CAPTION}', ]
LABEL_SYMBOLS = [
    r'<label>', r'</label>', r'<\label>', r'{label}', r'{\label}', r'{/label}',
    r'<LABEL>', r'</LABEL>', r'<\LABEL>', r'{LABEL}', r'{\LABEL}', r'{/LABEL}', ]
PARAM_SYMBOLS = [
    r'<param>', r'</param>', r'<\param>', r'{param}', r'{\param}', r'{/param}',
    r'<PARAM>', r'</PARAM>', r'<\PARAM>', r'{PARAM}', r'{\PARAM}', r'{/PARAM}', ]


# 对大纲内容分段，获取每一章的标题
def get_chapter_dagang(input):
    # 提取所有章节标题（# 开头的行）
    # pattern = r'(^#\s*\d+[^\n]*)(?:(?=\n#\s*\d)|\Z)'  # 匹配每个章节块
    # matches = re.findall(pattern, input, flags=re.MULTILINE | re.DOTALL)

    # 提取完整章节的内容
    chapters = []
    pattern_blocks = r'(^#\s*\d+[^\n]*)(.*?)(?=\n#\s*\d|\Z)'
    blocks = re.findall(pattern_blocks, input, flags=re.MULTILINE | re.DOTALL)
    for title, content in blocks:
        block_text = title.strip() + content.rstrip()
        chapters.append(block_text)
    return chapters


def zhengwen_chat_prepare(dagang, input_content):
    chapters = get_chapter_dagang(dagang)
    chapter_contents = []
    for chapter in chapters:
        content = f'## 说明内容\n```{input_content}```\n\n## 章节大纲\n```\n{chapter}\n```'
        chapter_contents.append({"role": "user", "content": content})
    return chapter_contents


def gen_zhengwen(chapter_contents):
    path = BASE_DIR / "prompt" / "4zhengwen_content.md"
    with open(path, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    system_message = {"role": "system", "content": system_prompt}
    messages_list = [
        [system_message, content] for content in chapter_contents
    ]

    results = chat_async(messages_list, "正文生成")
    return results


def renumber_labels(blocks, counter: int):
    new_blocks = []
    for block in blocks:
        # 匹配 </label>[公式编号：X]</label> 或 </label>[表编号：X]</label>
        def replace_label(m):
            nonlocal counter
            new_text = f"</label>{counter}</label>"
            counter += 1
            return new_text

        block_new = re.sub(
            r'</label>\s*\d+\s*</label>',
            replace_label,
            block
        )
        new_blocks.append(block_new)
    return new_blocks, counter


def chapter_format(chapter: str, idx_formula_start: int = 1, idx_table_start: int = 1):
    symbol_replacements = {
        'FORMULA_SYMBOLS': r'</formula>',
        'TABLE_SYMBOLS': r'</table>',
        'CONTENT_SYMBOLS': r'</content>',
        'CAPTION_SYMBOLS': r'</caption>',
        'LABEL_SYMBOLS': r'</label>',
        'PARAM_SYMBOLS': r'</param>'
    }

    for symbol_type, replacement in symbol_replacements.items():
        for symbol in globals()[symbol_type]:
            chapter = chapter.replace(symbol, replacement)

    # 暂存当前的起始索引，用于替换正文中出现的“见表（x）所示”时使用
    tmp_formula, tmp_table = idx_formula_start, idx_table_start
    formula_blocks = re.findall(r'</formula>.*?</formula>', chapter, re.DOTALL)
    table_blocks = re.findall(r'</table>.*?</table>', chapter, re.DOTALL)
    # 对公式和表格分别编号
    formula_new, idx_formula_start = renumber_labels(formula_blocks, idx_formula_start)
    table_new, idx_table_start = renumber_labels(table_blocks, idx_table_start)
    # 替换回原文
    for old, new in zip(formula_blocks, formula_new):
        chapter = chapter.replace(old, new)
    for old, new in zip(table_blocks, table_new):
        chapter = chapter.replace(old, new)
    for idx in range(idx_formula_start - tmp_formula):
        chapter = chapter.replace(f'式（{idx + 1}）', f'式（{idx + tmp_formula}）')
        chapter = chapter.replace(f'式({idx + 1})', f'式（{idx + tmp_formula}）')
        chapter = chapter.replace(f'式{idx + 1}', f'式（{idx + tmp_formula}）')

    for idx in range(idx_table_start - tmp_table):
        chapter = chapter.replace(f'表（{idx + 1}）', f'表（{idx + tmp_table}）')
        chapter = chapter.replace(f'表({idx + 1})', f'表（{idx + tmp_table}）')
        chapter = chapter.replace(f'表{idx + 1}', f'表（{idx + tmp_table}）')
    return chapter, idx_formula_start, idx_table_start


# 只返回生成后的正文内容：分章节返回，列表形式
def process1(dagang, input_content, polish_math_express=True):
    chapter_contents = zhengwen_chat_prepare(dagang, input_content)
    chapter_outputs = gen_zhengwen(chapter_contents)
    chapter_outputs = zhengwen_polish(chapter_outputs, polish_math_express=polish_math_express)

    # 由于多线程生成导致正文中的表格和公式编号序列需要重新排序
    idx_formula_start, idx_table_start = 1, 1
    for i, chapter in enumerate(chapter_outputs):
        chapter, idx_formula_start, idx_table_start = chapter_format(chapter, idx_formula_start, idx_table_start)
        chapter_outputs[i] = chapter
    return chapter_outputs


def zhengwen_process(dagang, input_content):
    chapter_contents = zhengwen_chat_prepare(dagang, input_content)
    results = gen_zhengwen(chapter_contents)
    idx_formula_start, idx_table_start = 1, 1
    chapter_outputs_0 = []
    print("=====未润色正文=====")
    for i, result in enumerate(results):
        chapter_outputs_0.append(result)
        print(result, '\n\n')
    chapter_outputs = zhengwen_polish(chapter_outputs_0)
    print("=====润色后正文=====")
    for i, chapter in enumerate(chapter_outputs):
        chapter, idx_formula_start, idx_table_start = chapter_format(chapter, idx_formula_start, idx_table_start)
        chapter_outputs[i] = chapter
        print(chapter, '\n\n')
    return chapter_outputs_0, chapter_outputs

# if __name__ == '__main__':
# with open('cache/test_dagang.txt', 'r', encoding='utf-8') as f:
#     dagang = f.read()
# zhengwen_chat_prepare(dagang, 'a')
# with open('cache/test_zhengwen.txt', 'r', encoding='utf-8') as f:
#     zhengwen = f.read()
# print(zhengwen_format(zhengwen))

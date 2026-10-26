from .shuyu_replace import TERM_NAME, TERM_NAME_EN, TERM_EXPLAIN, clean_local_term_explain, TERM_STANDARD_CODE, \
    TERM_ENTRY_NUMBER
from .constants import CHAPTER_NAME, TITLE, SYMBOL, TYPE, SHUYU

IGNORE_QIANYAN = ['# 前言']
IGNORE_YINYAN = ['# 引言']
IGNORE_FANWEI = ['# 1 范围']
IGNORE_YINYONG = ['# 2 规范性引用文件']


def qianyan2json(text):
    data = [
        {SYMBOL.TEXT: CHAPTER_NAME.QIANYAN, SYMBOL.TYPE: TITLE.QIANYAN_YINYAN}
    ]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line in IGNORE_QIANYAN:
            continue
        data.append({SYMBOL.TEXT: line, SYMBOL.TYPE: TYPE.PARAGRAPH})
    return data


def yinyan2json(text):
    data = [
        {SYMBOL.TEXT: CHAPTER_NAME.YINYAN, SYMBOL.TYPE: TITLE.QIANYAN_YINYAN}
    ]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line in IGNORE_YINYAN:
            continue
        data.append({SYMBOL.TEXT: line, SYMBOL.TYPE: TYPE.PARAGRAPH})
    return data


def fanwei2json(text):
    data = [
        {SYMBOL.TEXT: CHAPTER_NAME.FANWEI, SYMBOL.TEXT_NUMBER: "1", SYMBOL.TYPE: TITLE.CHAPTER}
    ]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line in IGNORE_FANWEI:
            continue
        data.append({SYMBOL.TEXT: line, SYMBOL.TYPE: TYPE.PARAGRAPH})
    return data


def yinyong2json(text):
    data = [
        {SYMBOL.TEXT: CHAPTER_NAME.GUIFANXING_YINYONG_WENJIAN, SYMBOL.TEXT_NUMBER: "2", SYMBOL.TYPE: TITLE.CHAPTER}
    ]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line in IGNORE_YINYONG:
            continue
        data.append({SYMBOL.TEXT: line, SYMBOL.TYPE: TYPE.PARAGRAPH})
    return data


def shuyu2json(shuyu_replace_info):
    data = [
        {SYMBOL.TEXT: CHAPTER_NAME.SHUYU_DINGYI, SYMBOL.TEXT_NUMBER: "3", SYMBOL.TYPE: TITLE.CHAPTER}
    ]
    j = 0
    for i, term in enumerate(shuyu_replace_info):
        if len(term) == 2:
            data.append({
                SYMBOL.TEXT: {SHUYU.NAME: term[1][TERM_NAME], SHUYU.ENNAME: term[1][TERM_NAME_EN],
                              SHUYU.TEXT_NUMBER: f"3.{j + 1}"}, SYMBOL.TYPE: SHUYU.ITEM1})
            data.append({
                SYMBOL.TEXT: clean_local_term_explain(term[1][TERM_EXPLAIN]),
                SYMBOL.TYPE: TYPE.PARAGRAPH
            })
            data.append({
                SYMBOL.TEXT: f'[来源：{term[1][TERM_STANDARD_CODE]}，{term[1][TERM_ENTRY_NUMBER]}]',
                SYMBOL.TYPE: TYPE.PARAGRAPH
            })
        else:
            data.append({
                SYMBOL.TEXT: {SHUYU.NAME: term[0][0], SHUYU.ENNAME: term[0][1], SHUYU.TEXT_NUMBER: f"3.{j + 1}"},
                SYMBOL.TYPE: SHUYU.ITEM1
            })
            data.append({
                SYMBOL.TEXT: term[0][2], SYMBOL.TYPE: TYPE.PARAGRAPH
            })

        j += 1
    return data


def zhengwen2json(zhengwen):
    from .zhengwen_format_json import zhengwen_md2json
    data = zhengwen_md2json(zhengwen)
    return data


def title2json(file_title):
    from .constants import FILE_TITLE
    return [
        {SYMBOL.TEXT: file_title, SYMBOL.TYPE: FILE_TITLE}
    ]


# with open('./cache/test_qianyan.txt', 'r', encoding="utf-8") as f:
#     content = f.read()
# qianyan2json(content)

# with open('./cache/test_yinyan.txt', 'r', encoding="utf-8") as f:
#     content = f.read()
# yinyan2json(content)

# with open('./cache/test_fanwei.txt', 'r', encoding="utf-8") as f:
#     content = f.read()
# fanwei2json(content)

# with open('./cache/test_yinyong.txt', 'r', encoding="utf-8") as f:
#     content = f.read()
# yinyong2json(content)


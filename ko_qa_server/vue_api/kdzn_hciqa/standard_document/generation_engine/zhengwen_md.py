from .constants import SYMBOL, TITLE, TYPE, FORMULA, LIEXIANG
from .qwen80b_chat import chat_async
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

def to_markdown_table(table):
    if not table or not table[0]:
        return ""
    # 转为字符串，防止非 str 类型
    table = [[str(cell) for cell in row] for row in table]
    header = table[0]
    rows = table[1:]
    # 表头
    md = []
    md.append("| " + " | ".join(header) + " |")
    # 分隔行
    md.append("| " + " | ".join(["---"] * len(header)) + " |")
    # 数据行
    for row in rows:
        md.append("| " + " | ".join(row) + " |")

    return "\n".join(md)


def json2md(zhengwen_json):
    res = []
    polish_math_list = []
    change_idx = []
    for i, item in enumerate(zhengwen_json):
        if item[SYMBOL.TYPE] == TITLE.CHAPTER:
            res.append(f'# {item[SYMBOL.TEXT_NUMBER]} {item[SYMBOL.TEXT]}')
        elif item[SYMBOL.TYPE] == TITLE.LEVEL_ONE:
            res.append(f'## {item[SYMBOL.TEXT_NUMBER]} {item[SYMBOL.TEXT]}')
        elif item[SYMBOL.TYPE] == TITLE.LEVEL_TWO:
            res.append(f'## {item[SYMBOL.TEXT_NUMBER]} {item[SYMBOL.TEXT]}')
        elif item[SYMBOL.TYPE] ==TITLE.TABLE:
            res.append(f'{item[SYMBOL.TEXT_NUMBER]} {item[SYMBOL.TEXT]}')
        elif item[SYMBOL.TYPE] == TYPE.TABLE:
            res.append(to_markdown_table(item[SYMBOL.TEXT]))
        elif item[SYMBOL.TYPE] == TYPE.FORMULA:
            formula_content = item[SYMBOL.TEXT][FORMULA.LATEX]
            formula_label = item[SYMBOL.TEXT][FORMULA.LABEL]
            res.append(f'  ${formula_content}$      ({formula_label})\n')
            res.append(f'式中：')
            for i, param in enumerate(item[SYMBOL.TEXT][FORMULA.DEFINITION]):
                param_name = param[FORMULA.DEFINITION_TEXT].strip('$')
                param_desc = param[FORMULA.DEFINITION_DESC]
                if i == len(item[SYMBOL.TEXT][FORMULA.DEFINITION]) - 1:
                    res.append(f"${param_name}$--{param_desc}。")
                else:
                    res.append(f"${param_name}$--{param_desc}；")
        elif item[SYMBOL.TYPE] in [TYPE.PARAGRAPH, LIEXIANG.NUMBERED_LEVEL_ONE, LIEXIANG.NUMBERED_LEVEL_TWO,
                                   LIEXIANG.UNNUMBERED_LEVEL_ONE, LIEXIANG.UNNUMBERED_LEVEL_TWO]:
            res.append(None)
            change_idx.append(i)
            polish_math_list.append(item[SYMBOL.TEXT])

    return polish_math_list, res, change_idx



    # polish_math_res = polish_math_expressions(polish_math_list)
    # j = 0
    # for i, r in enumerate(res):
    #     if r is None:
    #         res[i] = polish_math_res[j]
    #         j += 1
    #
    # return '\n'.join(res)

def polish_math_expressions(texts):
    with open(BASE_DIR / 'prompt' / '4zhengwen_polish_math_express.md', 'r', encoding='utf-8') as f:
        prompt = f.read()
    system_message = {"role": "system", "content": prompt}
    messages_list = [
        [system_message, {"role": "user", "content": text}] for text in texts
    ]


    texts = chat_async(messages_list, "正文数学表达式润色")
    return texts

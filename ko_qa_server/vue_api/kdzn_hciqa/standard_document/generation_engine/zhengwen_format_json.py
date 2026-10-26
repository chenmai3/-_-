import re
from .constants import SYMBOL, TYPE, TITLE, FORMULA


def match_title(title):
    TITLE_PATTERN = r'^(\d+(\.\d+)*)\s+(.*)$'
    """从去掉 Markdown 井号后的标题文本中提取编号和正文。
       返回 (编号, 文本) 或 None。
    """
    match = re.match(TITLE_PATTERN, title)
    if match:
        return match.group(1), match.group(3)
    return None


def parse_markdown_structure(text):
    result = []
    # 去掉空行并保留每行原始缩进末尾空格处理
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    current_body = []

    def flush_body():
        """将累计的正文写入结果"""
        nonlocal current_body
        if current_body:
            content = "\n".join(current_body).strip()
            if content:
                result.append({
                    SYMBOL.TYPE: TYPE.PARAGRAPH,
                    SYMBOL.TEXT: content
                })
            current_body = []

    for line in lines:
        # 一级标题 "# "
        if re.match(r"^#\s", line):
            flush_body()
            payload = match_title(line[1:].strip())
            if payload:
                idx, content = payload
            else:
                idx, content = None, line[1:].strip()
            result.append({
                SYMBOL.TYPE: TITLE.CHAPTER,
                SYMBOL.TEXT_NUMBER: idx,
                SYMBOL.TEXT: content
            })

        # 二级标题 "## "
        elif re.match(r"^##\s", line):
            flush_body()
            payload = match_title(line[2:].strip())
            if payload:
                idx, content = payload
            else:
                idx, content = None, line[2:].strip()
            result.append({
                SYMBOL.TYPE: TITLE.LEVEL_ONE,
                SYMBOL.TEXT_NUMBER: idx,
                SYMBOL.TEXT: content
            })

        # 三级标题 "### "
        elif re.match(r"^###\s", line):
            flush_body()
            payload = match_title(line[3:].strip())
            if payload:
                idx, content = payload
            else:
                idx, content = None, line[3:].strip()
            result.append({
                SYMBOL.TYPE: TITLE.LEVEL_TWO,
                SYMBOL.TEXT_NUMBER: idx,
                SYMBOL.TEXT: content
            })

        # 普通内容
        else:
            if line.strip():
                current_body.append(line)

    flush_body()
    return result


def parse_text_with_formula_and_table(text):
    # 1. 定义正则表达式
    formula_pattern = re.compile(r'</formula>.*?</formula>', re.S)
    table_pattern = re.compile(r'</table>.*?</table>', re.S)

    # 2. 找到所有公式和表格
    matches = []
    for m in formula_pattern.finditer(text):
        matches.append({
            SYMBOL.TYPE: TYPE.FORMULA,
            "start": m.start(),
            "end": m.end(),
            "content": m.group()
        })

    for m in table_pattern.finditer(text):
        matches.append({
            SYMBOL.TYPE: TYPE.TABLE,
            "start": m.start(),
            "end": m.end(),
            "content": m.group()
        })

    # 3. 按出现顺序排序
    matches.sort(key=lambda x: x["start"])

    # 4. 按顺序拆分正文
    result = []
    last_pos = 0

    for m in matches:
        # 正文部分
        if m["start"] > last_pos:
            text_part = text[last_pos:m["start"]].strip()
            if text_part:
                result.append({
                    "type": "text",
                    "content": text_part
                })

        # 插入特殊结构
        result.append({
            "type": m["type"],
            "content": m["content"]
        })

        last_pos = m["end"]

    # 处理最后剩余正文
    if last_pos < len(text):
        rest_text = text[last_pos:].strip()
        if rest_text:
            result.append({
                "type": "text",
                "content": rest_text
            })
    return result


def parse_formula2json(text):
    # 提取content中的公式
    content_pattern = re.compile(r'</content>(.*?)</content>', re.DOTALL)
    contents = content_pattern.findall(text)

    # 提取</label>中的数字
    label_pattern = re.compile(r'</label>\s*(\d+)\s*</label>')
    labels = label_pattern.findall(text)

    # 提取变量名和说明
    var_pattern = re.compile(r'</name>(.*?)</name>\s*</desc>(.*?)</desc>', re.DOTALL)
    variables = var_pattern.findall(text)

    formula_json = {
        SYMBOL.TEXT: {
            FORMULA.LATEX: contents[0],
            FORMULA.LABEL: labels[0],
            FORMULA.DEFINITION: [
                {FORMULA.DEFINITION_TEXT: t, FORMULA.DEFINITION_DESC: d} for t, d in variables
            ]
        },
        SYMBOL.TYPE: TYPE.FORMULA
    }
    return formula_json


def parse_table2json(text):
    # 提取content中的公式
    content_pattern = re.compile(r'</content>(.*?)</content>', re.DOTALL)
    content = content_pattern.findall(text)[0]

    lines = content.strip().split('\n')
    table_list = []

    for line in lines:
        # 忽略分隔线
        if set(line.strip()) == {'-', '|'}:
            continue
        # 分割每行并去掉多余空格
        row = [cell.strip() for cell in line.strip('|').split('|')]
        table_list.append(row)

    # 提取</label>中的数字
    label_pattern = re.compile(r'</label>\s*(\d+)\s*</label>')
    labels = label_pattern.findall(text)

    # 提取变量名和说明
    desc_pattern = re.compile(r'</desc>(.*?)</desc>', re.DOTALL)
    desc = desc_pattern.findall(text)

    json0 = {
        SYMBOL.TEXT: desc[0],
        SYMBOL.TEXT_NUMBER: f'表{labels[0]}',
        SYMBOL.TYPE: TITLE.TABLE
    }
    json1 = {
        SYMBOL.TEXT: table_list,
        SYMBOL.TYPE: TYPE.TABLE
    }
    return json0, json1


def parse_liexiang2json(text):
    '''
    列项仅出现在正文的段落中，不考虑公式和表格
    识别方式：根据前面的符号判断
    :param text:
    :return:
    '''
    from .constants import LIEXIANG

    lines = text.split('\n')
    has_liexiang = False
    data = []

    # 先检查是否真的含有列项
    for line in lines:
        content = line.strip()
        if re.match(r"[a-zA-Z]\)", content) or re.match(r"\d+\)", content):
            has_liexiang = True
            break

    # 情况 1：整个 text 没有列项 → 作为一个段落返回
    if not has_liexiang:
        return [{
            SYMBOL.TEXT: text.strip(),
            SYMBOL.TYPE: TYPE.PARAGRAPH
        }]

    # 情况 2：存在列项 → 按行解析
    for line in lines:
        content = line.strip()
        if not content:
            continue

        if re.match(r"[a-zA-Z]\)", content):
            # a) xxx
            data.append({
                SYMBOL.TEXT: content[2:].strip(),
                SYMBOL.TYPE: LIEXIANG.NUMBERED_LEVEL_ONE,
                SYMBOL.TEXT_NUMBER: content[:2]
            })
        elif re.match(r"\d+\)", content):
            # 1) xxx
            idx = content.find(')') + 1
            data.append({
                SYMBOL.TEXT: content[idx:].strip(),
                SYMBOL.TYPE: LIEXIANG.NUMBERED_LEVEL_TWO,
                SYMBOL.TEXT_NUMBER: content[:idx]
            })
        else:
            # 普通行，也属于段落
            data.append({
                SYMBOL.TEXT: content,
                SYMBOL.TYPE: TYPE.PARAGRAPH
            })

    return data


def zhengwen_md2json(text):
    data = []
    # 第一次解析，只根据大纲标题解析，公式表格依然存放在段落中
    format_list = parse_markdown_structure(text)
    title_values = TITLE().__list__()
    for item in format_list:
        if item[SYMBOL.TYPE] in title_values:
            data.append(item)
            continue
        # 解析段落中的公式表格和正文
        parse_list = parse_text_with_formula_and_table(item[SYMBOL.TEXT])
        for p in parse_list:
            if p[SYMBOL.TYPE] is TYPE.TABLE:
                json0, json1 = parse_table2json(p["content"])
                data.append(json0)
                data.append(json1)
            elif p[SYMBOL.TYPE] is TYPE.FORMULA:
                data.append(parse_formula2json(p["content"]))
            else:
                data = data + parse_liexiang2json(p["content"])

    return data

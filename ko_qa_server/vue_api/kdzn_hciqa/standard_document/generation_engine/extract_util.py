import re

START_SYMBOLS = [
    r'</start>', r'</START>', r'<start>', r'<START>', r'<\start>', r'<\START>',
    r'[START]', r'[start]', r'{START}', r'{start}']
END_SYMBOLS = [
    r'</end>', r'</END>', r'<end>', r'<END>', r'<\end>', r'<\END>',
    r'[END]', r'[end]', r'{END}', r'{end}']
SEP_SYMBOLS = [
    r'</SEP>', r'</sep>', r'<SEP>', r'<sep>', r'<\SEP>', r'<\sep>',
    r'</SEP}', r'</sep}', r'{/SEP>', r'{/sep}', r'{SEP>', r'{sep>', ]


# 检测开始符是否存在
def detect_start_symbol(text):
    pattern = re.compile("|".join(map(re.escape, START_SYMBOLS)))
    match = pattern.search(text)
    if not match:
        raise ValueError("LLM生成时，开始符格式不规范，脚本无法提取！请将相关信息反馈给开发者！")
    return match.group(0)


# 检测结束符是否存在
def detect_end_symbol(text):
    pattern = re.compile("|".join(map(re.escape, END_SYMBOLS)))
    match = pattern.search(text)
    if not match:
        raise ValueError("LLM生成时，结束符格式不规范，脚本无法提取！请将相关信息反馈给开发者！")
    return match.group(0)


def detect_sep_symbol(line):
    pattern = re.compile("|".join(map(re.escape, SEP_SYMBOLS)))
    match = pattern.search(line)
    if not match:
        raise ValueError("LLM生成时，间隔符格式不规范，脚本无法提取！请将相关信息反馈给开发者！")
    return match.group(0)


# 提取开始符和结束符之间的内容
def extract_content(text):
    try:
        start_symbol = detect_start_symbol(text)
        end_symbol = detect_end_symbol(text)
    except ValueError as e:
        print(f'error: {e}')
        exit(1)
    # 使用正则表达式匹配两个标识符之间的内容
    # re.DOTALL 让 . 匹配包括换行符在内的所有字符
    pattern = re.escape(start_symbol) + r'(.*?)' + re.escape(end_symbol)
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[0].strip()


# 提取开始符和结束符之间的内容
def extract_content_without_error(text):
    try:
        start_symbol = detect_start_symbol(text)
    except ValueError as e:
        print(f'error: {e}')
        start_symbol = r'</start>'
        text = f'{start_symbol}\n' + text
    try:
        end_symbol = detect_end_symbol(text)
    except ValueError as e:
        print(f'error: {e}')
        end_symbol = r'</end>'
        text = text + f'\n{end_symbol}'

    # 使用正则表达式匹配两个标识符之间的内容
    # re.DOTALL 让 . 匹配包括换行符在内的所有字符
    pattern = re.escape(start_symbol) + r'(.*?)' + re.escape(end_symbol)
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[0].strip()

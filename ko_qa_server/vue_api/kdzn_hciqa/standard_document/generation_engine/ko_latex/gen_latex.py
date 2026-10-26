import os
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


class CHAPTER_NAME:
    QIANYAN = "前言"
    YINYAN = "引言"
    FANWEI = "范围"
    GUIFANXING_YINYONG_WENJIAN = "规范性引用文件"
    SHUYU_DINGYI = "术语和定义"


class SYMBOL:
    TEXT = "text"
    TYPE = "type"
    TEXT_NUMBER = "text_number"


class TYPE:
    PARAGRAPH = "标准文件_段"
    FORMULA = "标准文件_正文公式"
    TABLE = "标准文件_表格"


FILE_TITLE = '标准文件_正文标准名称'


class LIEXIANG:
    NUMBERED_LEVEL_ONE = '标准文件_字母编号列项（一级）'
    NUMBERED_LEVEL_TWO = '标准文件_数字编号列项（二级）'
    UNNUMBERED_LEVEL_ONE = '标准文件_无编号列项（一级）'
    UNNUMBERED_LEVEL_TWO = '标准文件_无编号列项（二级）'


class TITLE:
    QIANYAN_YINYAN = "标准文件_前言、引言标题"
    CHAPTER = "标准文件_章标题"
    LEVEL_ONE = "标准文件_一级条标题"
    LEVEL_TWO = "标准文件_二级条标题"
    TABLE = "标准文件_正文表标题"

    def __list__(self):
        return [
            self.QIANYAN_YINYAN,
            self.CHAPTER,
            self.LEVEL_ONE,
            self.LEVEL_TWO,
            self.TABLE
        ]


class FORMULA:
    LATEX = "latex"
    LABEL = "label"
    DEFINITION = "definition"
    DEFINITION_DESC = "desc"
    DEFINITION_TEXT = "text"


class TABLE:
    LABEL = "label"
    DESC = "desc"


class SHUYU:
    ENNAME = "enName"
    NAME = "name"
    EXPLAIN = "explain"
    TEXT_NUMBER = "text_number"
    ITEM1 = "标准文件_术语条一"


def gen_qianyan_tex(cache_path, qianyan_json):
    save_path = os.path.join(cache_path, 'qianyan.tex')
    with open(save_path, "w", encoding="utf-8") as f:
        f.write('\\begin{preamble}{前言}\n')
        for text in qianyan_json:
            if text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')
        f.write('\\end{preamble}')
    print(f"{save_path} 文件已创建并保存内容。")
    return


def gen_yinyan_tex(cache_path, yinyan_json):
    save_path = os.path.join(cache_path, 'yinyan.tex')
    with open(save_path, "w", encoding="utf-8") as f:
        f.write('\\begin{preamble}{引言}\n')
        for text in yinyan_json:
            if text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')
        f.write('\\end{preamble}')
    print(f"{save_path} 文件已创建并保存内容。")
    return


def tex_annotation_process(tex_path):
    # 读取文件内容
    with open(tex_path, "r", encoding="utf-8") as f:
        content = f.read()
    # 替换 % 为 \%
    content = re.sub(r'\\*%', r'\%', content)
    # 写回文件（覆盖原文件）
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(content)


def gen_main_matter(cached_path, json_data):
    save_path = os.path.join(cached_path, 'main_matter.tex')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\\chapter{范围}\n')
        for text in json_data['fanwei']:
            if text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')

        f.write('\\chapter{规范性引用文件}\n')
        for text in json_data['yinyong']:
            if text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')

        f.write('\\chapter{术语和定义}\n')
        for text in json_data['shuyu']:
            if text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')
            elif text[SYMBOL.TYPE] == SHUYU.ITEM1:
                f.write(f'\\noindent {{\\heiti {text[SYMBOL.TEXT][SHUYU.TEXT_NUMBER]}}}\n\n')
                f.write(f'{{\\heiti {text[SYMBOL.TEXT][SHUYU.NAME]}  {text[SYMBOL.TEXT][SHUYU.ENNAME]}}}\n\n')

        for text in json_data['zhengwen']:
            if text[SYMBOL.TYPE] == TITLE.CHAPTER:
                f.write(f'\\chapter{{{text[SYMBOL.TEXT]}}}\n\n')
            elif text[SYMBOL.TYPE] == TITLE.LEVEL_ONE:
                f.write(f'\\section{{{text[SYMBOL.TEXT]}}}\n\n')
            elif text[SYMBOL.TYPE] == TITLE.LEVEL_TWO:
                f.write(f'\\subsection{{{text[SYMBOL.TEXT]}}}\n\n')
            elif text[SYMBOL.TYPE] == TYPE.PARAGRAPH:
                f.write(f'{text[SYMBOL.TEXT]}\n\n')
            elif text[SYMBOL.TYPE] == TYPE.FORMULA:
                formula_content = text[SYMBOL.TEXT][FORMULA.LATEX]
                formula_content = formula_content.strip('$')
                formula_label = text[SYMBOL.TEXT][FORMULA.LABEL]
                definition = text[SYMBOL.TEXT][FORMULA.DEFINITION]
                f.write(f'\\begin{{equation}}{formula_content}\\end{{equation}}\n\n')
                f.write('式中：\n\n')
                for i, defi in enumerate(definition):
                    defi_text = defi[FORMULA.DEFINITION_TEXT].strip('$')
                    defi_text = f'${defi_text}$'
                    f.write(f'{defi_text}——{defi[FORMULA.DEFINITION_DESC]}')
                    if i != len(definition) - 1:
                        f.write('；\n\n')
                    else:
                        f.write('。\n\n')
            elif text[SYMBOL.TYPE] == TYPE.TABLE:
                table_content = text[SYMBOL.TEXT]
                f.write(f'{array_to_latex_table(table_content)}\n\n')
            elif text[SYMBOL.TYPE] == TITLE.TABLE:
                text_number = text[SYMBOL.TEXT_NUMBER]
                text_title = text[SYMBOL.TEXT]
                f.write(f'\\begin{{center}}\n\n{{\\heiti {text_number} {text_title}}}\n\n\\end{{center}}\n\n')
            elif text[SYMBOL.TYPE] == LIEXIANG.NUMBERED_LEVEL_ONE:
                f.write(f'{text[SYMBOL.TEXT_NUMBER]}{text[SYMBOL.TEXT]}\n\n')
            elif text[SYMBOL.TYPE] == LIEXIANG.NUMBERED_LEVEL_TWO:
                f.write(f'{text[SYMBOL.TEXT_NUMBER]}{text[SYMBOL.TEXT]}\n\n')

    tex_annotation_process(save_path)


def array_to_latex_table(arr, caption=None, label=None):
    def escape_latex(s):
        # 转义 LaTeX 特殊字符
        return str(s).replace('_', '\\_').replace('%', '\\%')

    cols = len(arr[0])
    col_format = "c" * cols  # 所有列居中

    lines = []
    if caption or label:
        lines.append("\\begin{table}[ht]")
        lines.append("\\centering")
    else:
        # 即使没有 table 环境，也可以用 \begin{center} 居中
        lines.append("\\begin{center}")

    lines.append(f"\\begin{{tabular}}{{{col_format}}}")
    lines.append("\\hline")

    # 表头加粗
    header_row = " & ".join(f"\\textbf{{{escape_latex(x)}}}" for x in arr[0]) + " \\\\"
    lines.append(header_row)
    lines.append("\\hline")

    # 内容行
    for row in arr[1:]:
        line = " & ".join(escape_latex(x) for x in row) + " \\\\"
        lines.append(line)

    lines.append("\\hline")
    lines.append("\\end{tabular}")

    lines.append("\\end{center}")

    # 添加 caption 和 label（如果有）
    if caption:
        lines.insert(-1, f"\\caption{{{caption}}}")  # 插入在 end{tabular} 后，end{center} 前
    if label:
        lines.insert(-1, f"\\label{{{label}}}")

    # 如果使用了 table 环境，需要包裹起来
    if caption or label:
        lines.insert(0, "\\begin{table}[ht]")
        lines.append("\\end{table}")

    return "\n".join(lines)


def gen_main_tex(cache_path):
    save_path = os.path.join(cache_path, 'main.tex')
    with open(os.path.join(cache_path, 'main.tex'), "w", encoding="utf-8") as f:
        f.write(r'''%!TEX program = xelatex
\documentclass{GB-template}
\usepackage{amsmath}
\usepackage{ctex}

% use parameters
\ICS{这里输入 ICS 号}
\fenlei{这里输入分类号}
\biaozhunhao{在这里输入标准号}
\daitibiaozhunhao{在这里输入代替标准号}
\name{标准名称}
\enname{标准名称的英文译名}
\conformity{（与国际标准一致性的标识）}
\department{国家标准发布部门}
\fabudate{XXXX-XX-XX}
\shishidate{XXXX-XX-XX}
    
\begin{document}
\input{qianyan.tex}
\input{yinyan.tex}
\mainmatter
\input{main_matter.tex}
\end{document}''')
    print(f"{save_path} 文件已创建并保存内容。")


def gen_latex(json_data, out_file_path):
    cache_dir_path = str(BASE_DIR / "latex_cache" / out_file_path)
    os.makedirs(cache_dir_path, exist_ok=True)
    gen_main_tex(cache_dir_path)
    gen_qianyan_tex(cache_dir_path, json_data['qianyan'])
    gen_yinyan_tex(cache_dir_path, json_data['yinyan'])
    gen_main_matter(cache_dir_path, json_data)

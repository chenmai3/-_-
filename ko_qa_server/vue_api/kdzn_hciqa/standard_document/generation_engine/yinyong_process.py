from .extract_util import extract_content_without_error, detect_sep_symbol
from .util import is_number

'''
有些需要注意的书写规则：
这里的GB/T，GB排序是一起排的，即国家标准内部排序不考虑前面的GB，只需要考虑后面的序号排序
索引号后接年份
索引号后接（所有部分）等词汇
'''
TERM_NAME_CN = 'term_name'
TERM_NAME_EN = 'term_name_en'
TERM_EXPLAIN = 'term_explain'
TERM_STANDARD_CODE = 'standard_code'
TERM_STANDARD_NAME = 'standard_name'
NATIONAL_STANDARD_TYPE_CODE = ['GB', 'GB/T', 'GB/Z', 'GJB', 'GBZ', 'GBZ/T', 'GBJ']
INDUSTRY_FIELD_CODE = [
    'AQ', 'BB', 'CB', 'CH', 'CJ', 'CY', 'DA', 'DB', 'DL', 'DY', 'DZ', 'EJ', 'FZ', 'GA', 'GC', 'GF', 'GH', 'GM', 'GY',
    'HB', 'HG', 'HJ', 'HS', 'HY', 'JB', 'JC', 'JG', 'JR', 'JS', 'JT', 'JY', 'KA', 'LB', 'LD', 'LS', 'LY', 'MH', 'MR',
    'MT', 'MZ', 'NB', 'NY', 'QB', 'QC', 'QJ', 'QX', 'RB', 'RF', 'SB', 'SC', 'SF', 'SH', 'SJ', 'SL', 'SN', 'SW', 'SY',
    'TB', 'TD', 'TY', 'WB', 'WH', 'WJ', 'WM', 'WS', 'WW', 'XB', 'XF', 'YB', 'YC', 'YD', 'YJ', 'YS', 'YY', 'YZ', 'ZY',
    'AQ/T', 'BB/T', 'CB/T', 'CH/T', 'CJ/T', 'CY/T', 'DA/T', 'DB/T', 'DL/T', 'DY/T', 'DZ/T', 'EJ/T', 'FZ/T', 'GA/T',
    'GC/T', 'GF/T', 'GH/T', 'GM/T', 'GY/T', 'HB/T', 'HG/T', 'HJ/T', 'HS/T', 'HY/T', 'JB/T', 'JC/T', 'JG/T', 'JR/T',
    'JS/T', 'JT/T', 'JY/T', 'KA/T', 'LB/T', 'LD/T', 'LS/T', 'LY/T', 'MH/T', 'MR/T', 'MT/T', 'MZ/T', 'NB/T', 'NY/T',
    'QB/T', 'QC/T', 'QJ/T', 'QX/T', 'RB/T', 'RF/T', 'SB/T', 'SC/T', 'SF/T', 'SH/T', 'SJ/T', 'SL/T', 'SN/T', 'SW/T',
    'SY/T', 'TB/T', 'TD/T', 'TY/T', 'WB/T', 'WH/T', 'WJ/T', 'WM/T', 'WS/T', 'WW/T', 'XB/T', 'XF/T', 'YB/T', 'YC/T',
    'YD/T', 'YJ/T', 'YS/T', 'YY/T', 'YZ/T', 'ZY/T'
]


def process(text, shuyu_replace_info, zhengwen, sep_symbol=r'</SEP>'):
    text = extract_content_without_error(text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    # 如果术语存在替换，则将该替换术语的来源也添加到规范性引用文件中
    # 这个计数器是方便在正文中查找规范性引用文件时，当不存在该引用文件时，仍能保存术语来源的引用文件
    shuyu_replace_count = 0
    for replace_info in shuyu_replace_info:
        if len(replace_info) == 2:
            lines.append(replace_info[1][TERM_STANDARD_CODE] + sep_symbol + replace_info[1][TERM_STANDARD_NAME])
            shuyu_replace_count += 1

    gb, ind, db, t, q, iec, iso, other = [], [], [], [], [], [], [], []
    '''
    各种标准类型排序规则
    gb：国家标准，只要是国家标准，就按编号排序，无视'GB', 'GB/T'等前缀
    ind：行业标准，排序规则为：行业（优先级最高）（无视/T） + 标准顺序号
    db：地方标准，排序规则为：地域编号（优先级最高） + 标准顺序号
    t：团体标准，排序规则为：团体编号（优先级最高）（全英文） + 标准顺序号
    q：企业标准，排序规则为：企业编号（优先级最高）（全英文） + 标准顺序号
    iec：国际iec标准：只考虑标准顺序号
    iso：国际iso标准：只考虑标准顺序号
    '''
    for i, line in enumerate(lines):
        # 未检测到分隔符，则跳过这行
        sep = detect_sep_symbol(line)
        if sep is None:
            print(f"LLM生成规范性引用文件时，分隔符格式不规范，脚本无法提取！跳过该规范性引用文件：{line}")
        idx, name = line.split(sep)
        idx, name = idx.strip(), name.strip()
        #当索引号和名称都不出现在正文中，就不输出LLM生成的该引用文件。（术语来源的引用文件保存）
        if idx not in zhengwen and name not in zhengwen and i < len(lines) - shuyu_replace_count:
            continue

        # idx是标准类型和标准编号的组合，默认为'type number'格式，但可能出现'IEC SRD 63302-2:2025'，出现2个空格符，需特殊出率
        if len(idx.split(' ')) == 2:
            standard_type, standard_number = idx.split(' ')
            # 只取特殊字符前的部分作为排序依据，特殊字符可能无法完全覆盖
            standard_number = standard_number.split('-')[0].split('—')[0].split('(')[0].split('（')[0].split(':')[0]
            # 格式规范问题：如果标准号中包含非数字和小数点的字符，则跳过该引用文件
            if not is_number(standard_number):
                other.append(line.replace(sep, ' '))
                continue
            if standard_type.upper() in NATIONAL_STANDARD_TYPE_CODE:
                gb.append((standard_number, line.replace(sep, ' ')))
            # 行业标准主要分为强制性行业标准和推荐性行业标准，主要区别为在行业领域代码后是否存在 /T
            elif standard_type.upper() in INDUSTRY_FIELD_CODE:
                # 行业标准排序：行业（优先级最高）（无视/T） + 标准顺序号
                ind.append((standard_type.upper()[:2], standard_number, line.replace(sep, ' ')))
            # 地方标准（行业标准中有DB，但地方标准DB开头）
            elif standard_type.upper()[:2] == 'DB':
                # 提取地域编号  格式为：DB + 地域代码 + /T + 标准顺序号 + 年份号。
                end_pos = standard_type.find(r'/')
                # 找不到或不是数字则pass
                if end_pos == -1 or is_number(standard_type[2:end_pos]) is False:
                    other.append(line.replace(sep, ' '))
                    continue
                region_idx = int(standard_type[2:end_pos])
                # 排序标准：地域编号（优先级最高） + 标准顺序号
                db.append((region_idx, standard_number, line.strip().replace(sep, ' ')))
            elif standard_type.upper()[:2] == r'T/':
                t_idx = standard_type.upper()[2:]
                # 团体编号都是英文。不是则格式错误，退出
                if t_idx.isalpha() is False:
                    other.append(line.replace(sep, ' '))
                    continue
                t.append((t_idx, standard_number, line.replace(sep, ' ')))
            elif standard_type.upper()[:2] == r'Q/':
                q_idx = standard_type.upper[2:]
                # 团体编号都是英文。不是则格式错误，退出
                if q_idx.isalpha() is False:
                    other.append(line.replace(sep, ' '))
                    continue
                q.append((q_idx, standard_number, line.replace(sep, ' ')))
            # 不适用于IEC SRD 63302-2:2025
            elif standard_type.upper()[:3] == 'IEC':
                iec.append((standard_number, line.replace(sep, ' ')))
            # 同上
            elif standard_type.upper()[:3] == 'ISO':
                iso.append((standard_number, line.replace(sep, ' ')))
            else:
                other.append(line.replace(sep, ' '))
        elif len(idx.split(' ')) == 3:
            _, _, standard_number = idx.split(' ')
            standard_number = standard_number.split('-')[0].split('—')[0].split('(')[0].split('（')[0].split(':')[0]
            if idx[:3].upper() == 'IEC':
                iec.append((standard_number, line.replace(sep, ' ')))
            elif idx[:3].upper() == 'ISO':
                iso.append((standard_number, line.replace(sep, ' ')))
            else:
                other.append(line.replace(sep, ' '))
        # 对于不符合规范的引用文件，直接放到other中，例如：IEEE1451.0。无法提取出类型和编号
        else:
            other.append(line.replace(sep, ' '))

    gb = sorted(gb, key=lambda x: float(x[0]))
    ind = sorted(ind, key=lambda x: (x[0], float(x[1])))
    db = sorted(db, key=lambda x: (x[0], float(x[1])))
    t = sorted(t, key=lambda x: (x[0], float(x[1])))
    q = sorted(q, key=lambda x: (x[0], float(x[1])))
    iec = sorted(iec, key=lambda x: float(x[0]))
    iso = sorted(iso, key=lambda x: float(x[0]))

    output = f'# 2 规范性引用文件\n\n下列文件中的内容通过文中的规范性引用而构成本文件必不可少的条款。其中，注日期的引用文件，仅该日期对应的版本适用于本文件；不注日期的引用文件，其最新版本（包括所有的修改单）适用于本文件。\n\n'
    for line in gb:
        output += f'{line[1]}\n\n'
    for line in ind:
        output += f'{line[2]}\n\n'
    for line in db:
        output += f'{line[2]}\n\n'
    for line in t:
        output += f'{line[2]}\n\n'
    for line in q:
        output += f'{line[2]}\n\n'
    for line in iec:
        output += f'{line[1]}\n\n'
    for line in iso:
        output += f'{line[1]}\n\n'
    if len(other) > 1:
        output += '**以下内容后台无法有效处理，请手动处理**\n\n'
        for line in other:
            output += f'{line}\n\n'
    print(output)
    return output


def yinyong_process(text, shuyu_replace_info, zhengwen):
    return process(text, shuyu_replace_info, zhengwen)

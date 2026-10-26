def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

    # -*- coding: utf-8 -*-

    # 表格数据
# -*- coding: utf-8 -*-

header = ["字辈序号"] + [str(i) for i in range(22)]
row2   = ["字辈", "相", "志", "景", "自", "汝", "绍", "国", "宏", "延",
          "祯", "昌", "克", "相", "盛", "时", "德", "显", "名", "彰",
          "忠", "正", "世"]

# 第一列宽度，其它列宽度（可以按需要微调）
FIRST_W = 6
COL_W   = 3

def sep_line():
    line = "+" + "-"*(FIRST_W+2)
    for _ in range(22):
        line += "+" + "-"*(COL_W+2)
    line += "+"
    print(line)

def print_row(row):
    # 第一列
    line = "| " + row[0].center(FIRST_W) + " "
    # 后面 22 列
    for text in row[1:]:
        line += "| " + text.center(COL_W) + " "
    line += "|"
    print(line)

sep_line()
print_row(header)
sep_line()
print_row(row2)
sep_line()


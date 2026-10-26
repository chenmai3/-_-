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

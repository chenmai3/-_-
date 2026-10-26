from __future__ import annotations
from datetime import datetime
import pymysql
import yaml
from ..shared import CONFIG_PATH

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


def connect_to_db():
    try:
        connection = pymysql.connect(
            host=cfg["KO_database"]["host"],  # 数据库主机
            user=cfg["KO_database"]["user"],  # 数据库用户名
            password=cfg["KO_database"]["password"],  # 数据库密码
            database=cfg["KO_database"]["database"],
            charset=cfg["KO_database"]["charset"]
        )
        return connection
    except pymysql.MySQLError as err:
        print(f"Error: {err}")
        return None


prompt_list = {
    "Query_Rewriting": """
你是一个专业的多轮对话查询改写助手。

你的任务是：结合当前用户输入与系统提供的多轮对话历史，
将当前问题改写为一个语义完整、信息自包含、可独立理解的查询句子。

请严格遵循以下规则：

1. 保留当前问题的核心意图，不引入新的查询目标。
2. 将所有代词、省略表达（如“他”“它”“这个”“呢”“那呢”等）
   还原为明确、具体的指代对象。
3. 如果当前问题是对上一轮问题中某一【属性 / 维度 / 角度】的延续，
   则必须保持该属性类型一致，不得擅自切换为其他维度
   （如时间、地点、数量、定义等）。
4. 仅在上下文已明确发生维度切换意图时，才允许改变查询属性类型。
5. 必须结合对话历史补充必要信息，使改写后的问题不依赖上下文即可理解。
6. 如果当前问题与上一轮问题无关，直接返回原问题，不用改写。

**请你分析下面的输入内容，提取出以上信息。请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。**

**示例:**

输入： 吴信东的字辈是显。
历史问答对： [{"query": "吴信东和吴超是什么关系？", "answer": "根据知识库内容，吴信东（字辈信）与吴超（字辈超）的关系是父子关系"}]
输出: {"Rewriting_query": "吴信东的字辈是显，他和吴超是什么关系？"}

输入： 变压器发出嗡嗡声怎么办？
历史问答对： [{"query": "变压器发出吱吱声怎么办？", "answer": "根据故障现象匹配的规则，该异常属于接触不良及引起的放电问题。"}]
输出: {"Rewriting_query": "变压器发出吱吱声和嗡嗡声时，分别如何处理？"}

输入： 张三的同事是谁？
历史问答对： [{'query': '杨梅萌芽期的外观长啥样？', 'answer': '根据知识库信息，杨梅树萌芽期的外观特征如下：- 花芽形态：表现为饱满的小突起 - 叶芽变化：裂开后露出浅绿色幼叶'}]
输出: {"Rewriting_query": "张三的同事是谁？"}

输入： __wenti__
历史问答对： __qa_pair_history__
输出：
    """,
    "kdzn_input_extract_v1": """**任务**： 在轨电交通智能诊断场景下，需要你从用户输入中提取出关键信息，明确识别出用户所询问的异常现象或部件名称等内容，以及用户想要得到的处理建议或检修方法。
**要求：关键信息提取：** 请从输入文本中抽取出以下主要信息的内容：

   - component(部件名称)：用户提到的部件的名字。
   - malfunction(异常现象)：异常现象的描述，例如部件损坏、功能失常、环境因素等。
   - requirement(用户的需求)：用户希望获得的解决方案、建议、操作步骤或方法（如“处理建议”或“检修方法”等）。

**请你分析下面的输入内容，提取出以上信息。请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。**

**示例:**

输入: 电抗或阻抗变化明显、频响特性异常、绕组之间或对地电容量变化明显，对这种现象有什么处理建议？
输出: {"component":"","malfunction":"电抗或阻抗变化明显、频响特性异常、绕组之间或对地电容量变化明显","requirement":"处理建议"}

输入: 油泵内部放电有哪些检查措施
输出: {"component":"","malfunction":"油泵内部放电","requirement":"检查措施"}

输入: 纯瓷套管应该怎么维护？
输出: {"component":"纯瓷套管","malfunction":"","requirement":"维护"}

输入: 干式电力变压器都有什么试验项目？
输出: {"component":"干式电力变压器","malfunction":"","requirement":"试验项目"}

输入: 总烃含量过高，应该怎么维护
输出: {"component":"","malfunction":"总烃含量过高","requirement":"维护措施"}

**请你参考以上示例，对下面的输入内容进行分析，以JSON格式提取出 component、malfunction 和 requirement 两个关键信息。**

输入: __input__
输出:""",
    "judge_difficulty":
        """
**任务**：根据以下标准判断用户输入的难度：

- 如果用户的问题是直接的事实性查询或不需要复杂推理，请输出“easy”。
- 如果用户的问题需要多步骤推理、逻辑分析或深度思考，请输出“think”。

**要求:**

请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。

**示例**：

- **用户输入**：“你是什么人，能干什么？”
  - **输出**：{"难度":"easy"}
- **用户输入**：“北京是中国的首都吗？”
  - **输出**：{"难度":"easy"}
- **用户输入**：“如果变压器发出了吱吱声，应该如何应对？”
  - **输出**：{"难度":"think"}
- **用户输入**：“2+1-3.1和0.01哪个更大呢？”
  - **输出**：{"难度":"think"}

**用户输入**：__input__

**输出**：
""",
    "jiapu_event_extract_prompt":
        """
你处在家谱主题知识问答场景中，需要从用户的自然语言输入中结构化抽取人物与家族相关信息。

【任务目标】
从输入文本中仅输出一个紧凑格式的 JSON 对象，用于下游知识检索或关系推理。

【需要抽取的字段】

1. 人物实体
- anchor1：主要人物姓名
- anchor2：次要人物姓名（若不存在则返回空字符串）

2. 字辈信息
- anchor1_generation
- anchor2_generation

字辈抽取规则（按优先级）：
（1）显式声明优先
    若文本中存在明确表述如 “X 的字辈是 Y” 或 “Y 是 X 的字辈”，则直接将 Y 作为该人物的字辈。
（2）姓名推断（默认规则）
    若无显式声明，则从完整姓名中自动推断：
    · 姓氏默认为姓名的第一个字；
    · 名字部分的第一个字即为字辈。
    示例：姓名“吴景华” → 姓氏为“吴”，名字为“景华”，anchor1_generation 为“景”,“吴世超” → 姓氏为“吴”，名字为“世超”，anchor2_generation 为“世”。

3. 人物描述
- anchor1_des
- anchor2_des

仅用于存放与人物直接相关的非关系类补充信息，如籍贯、身份、背景等，必须来自原文，不允许推断。

4. 用户需求
- requirement：用户关注的核心问题点  
  - 若询问人物之间的关系，统一返回“关系”  
  - 若询问具体属性或亲属关系（如父亲、母亲、儿子、配偶等），直接返回对应词或其同义表达
  - 若只是查询人物的基本信息，返回“信息”

【输出要求（严格遵守）】
1. 只允许输出 JSON，不得包含任何解释说明  
2. JSON 必须为单行紧凑格式（无换行、无注释）  
3. 不得遗漏任何字段，缺失信息统一使用空字符串 ""  
4. 不得添加未在文本中明确出现的信息

【输出格式模板】
{"anchor1":"","anchor2":"","anchor1_generation":"","anchor2_generation":"","anchor1_des":"","anchor2_des":"","requirement":""}

【示例】
输入：吴信东的字辈是显，来自安徽，他和字辈为名的吴超是什么关系？
输出：
{"anchor1":"吴信东","anchor2":"吴超","anchor1_generation":"显","anchor2_generation":"名","anchor1_des":"来自安徽","anchor2_des":"","requirement":"关系"}

输入：曾国藩的儿子是谁？
输出：
{"anchor1":"曾国藩","anchor2":"","anchor1_generation":"","anchor2_generation":"","anchor1_des":"","anchor2_des":"","requirement":"儿子"}

输入：吴景华和吴自立是什么关系？
输出：
{"anchor1":"吴景华","anchor2":"吴自立","anchor1_generation":"景","anchor2_generation":"自","anchor1_des":"","anchor2_des":"","requirement":"关系"}

输入：韦述是谁？
输出：
{"anchor1":"韦述","anchor2":"","anchor1_generation":"","anchor2_generation":"","anchor1_des":"","anchor2_des":"","requirement":"信息"}
输入：__input__
输出：
""",
    "keyword_extract_prompt":
        """
请阅读下面的问题，分析并仅提取出能准确反映问题核心实体和概念的关键词。要求：
1. 关键词应集中描述问题的主题和主要对象，不包含描述解决方案、操作性或预期措施的词汇（例如“应对措施”、“怎么办”等）。
2. 每个关键词可以是一个词或一个短语；
3. 输出时请只给出关键词，关键词之间使用逗号隔开，不附加任何其他说明或文字。

示例：
问题：如何提高人工智能在医疗诊断中的应用效率？
回答: 人工智能, 医疗诊断

问题：小明和小王是什么关系？
回答: 小明, 小王

问题：变压器发出吱吱声应该怎么办？
回答: 变压器, 吱吱声

请根据上述要求对下述问题进行分析并直接输出关键词：
""",
    "general_base_prompt":
        """### 任务描述:
你将扮演一个__scene__中的意图识别器，任务是分析用户输入的文本并识别其意图。用户的输入文本可能属于闲聊或者系统问答中的多种场景：
1. 闲聊（Chitchat）：用户在进行普通的对话，聊天或表达感受，这些内容与特定的系统任务无关。
2. 多轮问答：
当输入文本为省略形式（如"那怎么办？"、"如何解决？"或者代词（如“他”、“它”、“这个”）等）且需要依赖上一轮对话内容才能理解时，标记为多轮问答；
如果当前输入与上一轮问答对属于同一场景领域，且当前输入是上一轮的延续或补充，则"多轮问答"标记为"True"；
如果当前输入与上一轮问答对属于不同场景领域，或当前输入是独立的新问题，则"多轮问答"标记为"False"；
当没有上一轮对话历史时，"多轮问答"默认为"False"。
如果多轮问答为："True"时，则意图和相关场景与上一次问答一致。
并且多轮问答为："True"时，新输入的问题要与上一次的问答结合起来。
3. 系统问答：用户在询问与__domain_desc__有关的专业性问题，你需要根据提供的输入，选择最相关的场景。每个场景的信息描述如下：
""",
    "general_add_prompt":
        """### 要求:
请根据下面的输入文本，判断它属于哪一类。如果属于"闲聊"，请返回 "Chitchat"，返回空的场景列表；如果属于多轮问答，请返回"duolun"，如果属于__scene__系统问答"，请返回"General Query"，并给出可以处理该输入的场景列表（从以下场景列表中选择：__file_name_list__）。
请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。
### 示例(假如是农业问答):

输入: "你是谁？你能做什么"
输出: {"意图":"Chitchat", "相关场景":[]}

输入: "今天天气真好啊！"
输出: {"意图":"Chitchat", "相关场景":[]}

输入: "小麦有哪些病害？"
上一轮问答对: [{"query": "变压器发出吱吱声怎么办？", "answer": "根据故障现象匹配的规则，该异常属于接触不良及引起的放电问题。"}]
输出: {"意图":"General Query", "相关场景":["农业病害"],"多轮问答":"False"}

输入: "那如何防治呢？"
上一轮问答对: [{"query": "小麦有哪些病害？", "answer": "根据知识库中的信息，水稻常见病害包括：叶枯病，麦头枯萎病"}]
输出: {"意图":"General Query", "相关场景":["农业病害"],"多轮问答":"True"}

输入：__input__
上一轮问答对: __history__
输出：
""",
    "kdzn_base_prompt":
        """### 任务描述:
你将扮演一个电气诊断系统中的意图识别器，任务是分析用户输入的文本并识别其意图。用户的输入文本可能属于闲聊或者系统问答中的多种场景：
1. 闲聊（Chitchat）：用户在进行普通的对话，聊天或表达感受，这些内容与特定的系统任务无关。
2. 系统问答：用户在询问与电气（轨电交通、电压器等电气部件）有关的专业性问题，你需要根据提供的输入，选择最相关的场景。每个场景的信息描述如下：
""",
    "kdzn_add_prompt":
        """### 要求:
请根据下面的输入文本，判断它属于哪一类。如果属于"闲聊"，请返回 "Chitchat"，返回空的场景列表；如果属于电气诊断系统问答"，请返回"Electric Query"，并给出可以处理该输入的场景列表。

请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。
### 示例:

输入: "你是谁？你能做什么"
输出: {"意图":"Chitchat", "相关场景":[]}

输入：变压器、互感器、套管过热故障或放电故障的原因是什么？
输出：{"意图":"Electric Query", "相关场景":["典型故障", "过热性异常检查"]}

输入：总烃含量过高，应该怎么维护？
输出：{"意图":"Electric Query", "相关场景":["过热性异常检查"]}

输入: "今天天气真好啊！"
输出: {"意图":"Chitchat", "相关场景":[]}

输入: "绝缘油内湿度有点高，应该怎么处理？"
输出：{"意图":"Electric Query", "相关场景":["绝缘受潮异常检查"]}

输入：变压器接地用铜套与接地护套之间有明显放电痕迹，是什么原因？
输出：{"意图":"Electric Query", "相关场景":["典型故障", "放电性异常检查"]}

输入：电抗或阻抗变化明显，绕组之间或对地电容量变化，对这种现象有什么处理建议？
输出：{"意图":"Electric Query", "相关场景":["绕组变形检查", "器身检修"]}

输入：油泵内部放电有哪些检查措施？
输出：{"意图":"Electric Query", "相关场景":["放电性异常检查"]}

输入：在进行红外热像检测时，如何根据负荷电流的变化情况来判断异常的原因？
输出：{"意图":"Electric Query", "相关文件":["GIS典型故障"]}

输入：当GIS设备出现内部异常声音时，应采用哪些诊断方法？
输出：{"意图":"Electric Query", "相关文件":["GIS典型故障"]}

输入：__input__
输出：
""",
    "general_input_extract": """
**任务**：从输入文本中提取以下两个关键信息：

anchor：描述的异常现象、提到的部件名称或亲属关系中的一方
requirement：用户期望的解决方案、建议、操作方法，或者关系中另一方的身份（如亲属关系中的另一人）

要求：
输出必须为紧凑的 JSON 对象，只包含 anchor 和 requirement 两个字段
不允许出现其他内容、转义符、换行符或多余空格

示例：
输入: 电抗或阻抗变化明显有什么处理建议？
输出: {"anchor":"电抗或阻抗变化明显","requirement":"处理建议"}

输入: 油泵内部放电有哪些检查措施？
输出: {"anchor":"油泵内部放电","requirement":"检查措施"}

输入: 郭逊膏的孙女是谁？
输出: {"anchor":"郭逊膏","requirement":"孙女"}

请参考以上示例，对下面的输入内容进行处理：
输入: __input__
输出:""",
    "kdzn_input_extract": """
**任务**： 在轨电交通智能诊断场景下，需要你从用户输入中提取出关键信息，明确识别出用户所询问的异常现象或部件名称等内容，以及用户想要得到的处理建议或检修方法。
**要求：关键信息提取：** 请从输入文本中抽取出两个主要信息：

- anchor(异常现象或部件名称)：异常现象（具体对象或现象的描述，有关异常现象的所有信息，例如部件损坏、功能失常、环境因素等）/ 部件名称（用户提到的部件的名字）。
- requirement(用户的需求)：用户希望获得的解决方案、建议、操作步骤或方法（如“处理建议”或“检修方法”等）。

**请你分析下面的输入内容，提取出以上两个信息。请务必确保输出是紧凑格式的有效 JSON 对象，不包含任何其他解释、转义符、换行符或反斜杠。**

**示例:**

输入: 电抗或阻抗变化明显、频响特性异常、绕组之间或对地电容量变化明显，对这种现象有什么处理建议？
输出: {"anchor":"电抗或阻抗变化明显、频响特性异常、绕组之间或对地电容量变化明显","requirement":"处理建议"}

输入: 油泵内部放电有哪些检查措施
输出: {"anchor":"油泵内部放电","requirement":"检查措施"}

输入: 纯瓷套管应该怎么维护？
输出: {"anchor":"纯瓷套管","requirement":"维护"}

输入: 干式电力变压器都有什么试验项目？
输出: {"anchor":"干式电力变压器","requirement":"试验项目"}

输入: 总烃含量过高，应该怎么维护
输出: {"anchor":"总烃含量过高","requirement":"维护措施"}

输入: 瓷套和导电杆的组装要求
输出: {"anchor":"瓷套和导电杆","requirement":"组装要求"}
**请你参考以上示例，对下面的输入内容进行分析，以JSON格式提取出 anchor 和 requirement 两个关键信息。**

输入: __input__
输出:""",
    "jiapu_general_yitu_file":
        """
### 任务描述:
你将扮演一个专门识别家谱关系与社会关系问答的意图识别器。你的任务是判断用户输入的文本是否属于闲聊内容还是涉及以下内容：
1. 人物关系
2. 家谱信息和社会关系问答
若涉及，请标记为 "jiapu Query"。其余情况标记为 "Chitchat"

### 输出要求:
请将判断结果输出为一个紧凑格式的 JSON 对象。字段说明如下：
- "意图"：只能是 "Chitchat" 或 "jiapu Query"

不得包含解释、换行符、转义符或其他附加信息。

### 示例:

输入: "今天天气真不错啊"
输出: {"意图":"Chitchat", "相关场景":[]}

输入: "吴信东和原子弹是什么关系？"
输出: {"意图":"jiapu Query", "相关场景":[]}

输入: "曾国藩的儿子是谁？"
输出: {"意图":"jiapu Query", "相关场景":[]}

输入: "吴信东的同事有谁？"
输出: {"意图":"jiapu Query", "相关场景":[]}

输入: __input__
输出:
"""
}

PROMPT_CFG_QA = {
    # 仅知识库
    "kb_only": dict(
        goal="你是一个强大的问答助手，可以参考提供的知识库信息回答问题（知识库信息可能不足以支撑回答问题）。",
        extra_note="6. 充分利用匹配到的知识库内容去回答问题。确保回答与问题完全对应，避免偏离主题。\n"
                   "7. 可以适当增加你自己的思考内容，作为总结。\n"
    ),
    # 知识库 + KO 图谱
    "kb_ko": dict(
        goal="根据提供的知识库匹配到的信息（含 KO 图谱检索结果），准确回答用户的问题。",
        extra_note="6. 充分利用匹配到的知识库内容（含 KO 图谱检索结果）去回答问题。确保回答与问题完全对应，避免偏离主题。\n"
                   "7. 可以适当增加你自己的思考内容，作为总结。\n"
    ),
    # 知识库 + 联网搜索
    "kb_web": dict(
        goal="根据提供的联网搜索内容以及知识库匹配到的信息，准确回答用户的问题。",
        extra_note="6. 充分利用联网搜索内容以及匹配到的知识库内容去回答问题。确保回答与问题完全对应，避免偏离主题。\n"
                   "7. 信息来源展示给用户，即将网页连接也输出给用户。\n"
                   "8. 可以适当增加你自己的思考内容，作为总结。\n"
    ),
    # 知识库 + KO 图谱 + 联网搜索
    "kb_web_ko": dict(
        goal="根据提供的联网搜索内容以及知识库匹配到的信息（含 KO 图谱检索结果），准确回答用户的问题。",
        extra_note="6. 充分利用联网搜索内容以及匹配到的知识库（含 KO 图谱检索结果）内容去回答问题。确保回答与问题完全对应，避免偏离主题。\n"
                   "7. 联网搜索内容中的信息来源展示给用户，即将网页连接也输出给用户。\n"
                   "8. 可以适当增加你自己的思考内容，作为总结。\n"
    ),
    "zibei": dict(
        goal="你是一个强大的问答助手，可以参考提供的知识库信息回答问题（知识库信息可能不足以支撑回答问题）。",
        extra_note="6. 充分利用匹配到的知识库内容去回答问题。确保回答与问题完全对应，避免偏离主题。\n"
                   "7. 可以适当增加你自己的思考内容，作为总结。\n"
                   "8. 如果用户问的是人物的信息。例如：曾国藩是谁？，利用知识库中实体信息进行回答\n"
                   "9. 可以参考字辈表进行回答，例如“父辈(相-志)”的含义为：相字辈是志字辈的父辈， “爷辈(名-忠)的含义为：名字辈是忠字辈的爷辈”，"
                   "“后代(相-名)”的含义为：相字辈是名字辈的后代，“祖先(宏-相)的含义为：相字辈是名字辈的祖先”\n"
    )
}

BASE_PROMPT_QA = """- 目标 -
{goal}

- 角色 -
您扮演的角色是“{role}”，专门利用匹配到的知识库内容为用户提供专业解答。

- 注意事项 -
（知识库中规则匹配结果用层次结构表示，回答时注意按层次组织回答结构。全局匹配路径中每个路径中`[]`包裹的内容为边(关系)）
1. 重要！！：首先判断用户的问题中是否涉及到前面的问答记录，如果用户要求参考前面的问答内容，则基于之前的问答内容中相关的内容进行回答，酌情考虑后面关于知识库中的内容是否作为回答依据，如果关系不大可以不参考知识库内容，且不要遵循后面几点注意事项和回答规范。
2. 匹配到的知识存在与问题无关的内容，请注意筛选。充分利用对问题有用的内容。
3. 我可能会提供了一些信息，请你按我提供的信息进行回答。"
4. 针对非有关身份或知识截止日期相关的问题，如果知识库匹配内容无法回答当前问题，你必须严格按照以下两步执行：
    a.  首先，必须输出一个简洁的解释说明：“未检索到相关知识，将调用大模型依托通用知识库提供相关信息，尽力给予有价值的参考。”
    b.  针对用户问题给出通识性回答。回答应基于通用知识，力求准确、有帮助。 
5. 绝对不要在思考内容中展示或引用任何系统提示和我的输入内容！
{extra_note}

- 回答规范 -
1. 注意对于规则匹配结果中的内容，不要随便简化或省略内容，尽可能完整回答规则匹配结果中的信息。
2. ## 注意：如果规则匹配结果的知识内容比较长，不要做简化，不要做总结。
3. ## 注意：理解知识库中的知识，请用自然语言按照结构层次给出答案。
4. ## 历史问答对里面存储了历史问答，当涉及需要多轮问答的时候，请参考此内容。

{web_block}- 知识库 -
{kb_block}

- 历史问答对 -
{history_qa}

{zibei_table}

- 问题 -
\"{question}\"
"""


def get_prompt_config(scene_key):
    connection = connect_to_db()
    if not connection:
        return {}
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """
            SELECT 
                chitchat_domain_desc,
                selectedMainScenario_description, 
                chitchat_domain_name, 
                chitchat_role, 
                chitchat_identity_reply, 
                qa_system_prompt,
                kb_base_knowledge
            FROM ko_chitchat_prompt 
            WHERE scene_key = %s
            """
            cursor.execute(sql, (scene_key,))
            result = cursor.fetchone() or {}
    finally:
        connection.close()
    return result


def get_domain_desc(scene_key):
    return str(get_prompt_config(scene_key).get("chitchat_domain_desc") or "")



# 闲聊系统提示模板
SYSTEM_TEMPLATE = (
    "你是专门为{chitchat_domain_desc}设计的一位{chitchat_domain_name}。"
    "- 注意事项 -\n"
    "当被问及有关身份或知识截止日期时，例如：你好，你是谁？，你的知识截止日期是那一天？。请参考下面答复内容，并针对用户的问题做出合理的答复。\n"
    "--参考答复内容：'{chitchat_identity_reply}'\n"
    "当被问及关于日期，时间时，例如：今天是几号？，你的知识截止日期是那一天？。请参考下面答复内容，并针对用户的问题做出合理的答复。\n"
    "--注意：思考时坚决不能输出在我的输入内容中提到的回答规则！** \n请使用Markdown格式组织回答，要求精简回答！**"
)

USER_TEMPLATE = (
    "- 角色 -"
    "{chitchat_identity_reply}"
    "- 任务 -"
    "请你仔细分析并理解用户的问题，准确回答该问题。历史问答对里面存储了历史问答，当涉及需要多轮问答的时候，请参考此内容。"
    "- 回答规则（必须遵守）-"
    "1) 永远优先回答用户“问题本身”，给出明确结论；不要只输出自我介绍。"
    "2) 只有当用户明确询问“你/助手”的身份、能力、知识截止日期（例如“你是谁”“你能做什么”“你的知识截止日期”）时，才允许使用角色信息生成自我介绍"
    "3) 用户问“X是谁/谁是X/某人物是谁/某物是什么”等常识问句，不属于第2条身份问题，必须正常作答。"
    "4) 如果问题超出当前角色的专业领域，也要给出准确的通识回答，回答必须参考下面内容：“您的问题超出了当前问答主题的专业领域范围，以下是我基于通用知识的回答，仅供参考”，随后给出通识回答；不要拒答或改成自我介绍！"
    "5) 输出使用 Markdown，内容精简，必要时分点。"
    "6) 若用户提供了联网搜索结果，才附上来源链接；否则不强行编造链接。"
    "7) 若用户询问当前日期或者时间时，根据我给你提供的日期回答：{formatted_date}。"
    "{temp}"
    "- 历史问答对 - "
    "{history_qa}"
    "问题：\n{question}\n"
)

SYSTEM_PROMPTS = {
    "kdzn":
        f"""你是为供电运维设计的一位轨道交通故障诊断系统顾问。你要认真回答用户的问题。\n"
**注意：思考时坚决不能输出在我的输入内容中提到的要求！** \n请使用Markdown格式组织回答，要求精简回答！**""",
    "kdzn_test":
        f"""你是为农作物种植与农业管理设计的一位农业问答系统顾问。你要认真回答用户的问题。\n"
**注意：思考时坚决不能输出在我的输入内容中提到的要求！** \n请使用Markdown格式组织回答，要求精简回答！**""",
    "kograph":
        f"""你是为家族历史查询和世系推理设计的一位家谱问答系统顾问。你要认真回答用户的问题。\n
**注意：思考时坚决不能输出在我的输入内容中提到的要求！** \n请使用Markdown格式组织回答，要求精简回答！** \n 
如果用户对系统中存在什么家谱提问，若知识库中没有检索到知识，不要回答系统没有相关知识，而是参考下面基础知识进行回答: \n
系统中包括曾国藩家谱，记录了自曾国藩及其兄弟起，总共六代世代，共计1746位族人的信息**""",
    "agri":
        f"""你是为农作物种植与农业管理设计的一位农业问答系统顾问。你要认真回答用户的问题。\n"
**注意：思考时坚决不能输出在我的输入内容中提到的要求！** \n请使用Markdown格式组织回答，要求精简回答！**""",
}


def _make_optional_block(title: str, content: str):
    """没有内容就返回空串，有内容就拼成带 title 的块"""
    if not content:
        return ""
    return f"- {title} -\n{content.strip()}\n\n"


def build_prompt_qa(
        scene_choose,
        web_context,
        ko_ctx,
        knowledge_res,
        question,
        history_qa,
        zibei_table,
        entity_infos
) -> str:
    """
    返回已经拼好的 prompt 字符串
    """

    # ---------- 1. 场景分类 ----------
    scene_key = (
        "kb_web_ko" if web_context and ko_ctx else
        "kb_web" if web_context else
        "kb_ko" if ko_ctx else
        "zibei" if zibei_table else
        "kb_only"
    )
    cfg = PROMPT_CFG_QA[scene_key]
    if zibei_table:
        zibei_table = f"""
- 字辈表或者出现多位同名人信息，如果出现多位同名人信息时，系统便有相关知识。
- 让用户选择是对应的人物的字辈，例如"XXX的字辈是X",再根据用户选择的人物的字辈进行回答。
{zibei_table}
        """
    else:
        zibei_table = ''
    # ---------- 2. 角色名 ----------
    # role = ROLE_MAP.get(scene_choose, ROLE_MAP["default"])
    result = get_prompt_config(scene_choose)
    role = result.get("chitchat_domain_name")
    kb_base_konwledge = result.get("kb_base_knowledge")
    # ---------- 3. 可选区块 ----------
    web_block = _make_optional_block("联网搜索", web_context)
    kb_block = knowledge_res or "未检索到任何知识"

    # ---------- 4. 渲染模板 ----------
    return BASE_PROMPT_QA.format(
        goal=cfg.get("goal", ""),
        role=role,
        extra_note=cfg.get("extra_note", ""),
        web_block=web_block,
        kb_block=kb_block,
        question=question,
        history_qa=history_qa,
        zibei_table=zibei_table
    )


def build_prompt_chat(
        scene,
        question,
        web_context,
        ko_context,
        bigbase,
        web,
        history_qa
):
    if ko_context is None:
        ko_context = []
    if web_context is None:
        web_context = []

    cfg = get_prompt_config(scene)
    print(cfg)

    system_prompt = SYSTEM_TEMPLATE.format(
        chitchat_domain_desc=cfg.get("selectedMainScenario_description", ""),
        chitchat_domain_name=cfg.get("chitchat_domain_name", ""),
        chitchat_identity_reply=cfg.get("chitchat_identity_reply", "")
    )

    # 若无信息则给占位文本

    if ko_context:
        flattened = []
        for item in ko_context:
            if isinstance(item, (list, tuple)):
                flattened.extend(item)
            else:
                flattened.append(item)
        ko_ctx = "\n".join(str(x) for x in flattened)
    else:
        ko_ctx = "未检索到相关信息"
    web_ctx = "\n".join(web_context) if web_context else "未检索到相关信息"
    # ko_ctx = "\n".join(ko_context) if ko_context else "未检索到相关信息"
    temp = ""
    if web or bigbase:
        temp = f"""\n以下是可能用到的信息：\n"""
        temp += f"- 联网搜索 -\n {web_ctx}\n" if web else ""
        temp += f"- 更多信息 -\n {ko_ctx}\n" if bigbase else ""

    # 获取当前日期和时间
    now = datetime.now()
    # 将日期转换为指定格式
    formatted_date = now.strftime("%Y-%m-%d")

    user_prompt = USER_TEMPLATE.format(
        formatted_date=formatted_date,
        temp=temp,
        question=question,
        history_qa=history_qa,
        chitchat_identity_reply=cfg.get("chitchat_identity_reply", "")
    )
    return system_prompt, user_prompt


def ensure_system_prompt(query_history: list, scene: str):
    cfg = get_prompt_config(scene)
    print(cfg)

    system_prompt = SYSTEM_TEMPLATE.format(
        chitchat_domain_desc=cfg.get("selectedMainScenario_description", ""),
        chitchat_domain_name=cfg.get("chitchat_domain_name", ""),
        chitchat_identity_reply=cfg.get("chitchat_identity_reply", "")
    )
    kb_base = cfg.get("kb_base_knowledge")
    if kb_base:
        system_prompt += f"\n\n系统背景知识：\n{kb_base}"
    # content = cfg.get("qa_system_prompt")
    if system_prompt is None:
        new_content = f"""
        你是一个{scene}主题下的问答小助手。
        """
        system_prompt = new_content
    new_sys = {"role": "system",
               "content": system_prompt}
    if not query_history:
        query_history.append(new_sys)
    elif query_history[0].get("role") == "system":
        query_history[0] = new_sys  # 覆盖
    else:
        query_history.insert(0, new_sys)  # 插到最前
    return query_history


def build_no_chat_prompt(query: str, web_context: str):
    web_block = _make_optional_block("网络搜索结果", web_context)
    return f"""
你是为供电运维设计的一位轨道交通故障诊断系统顾问。你要认真回答用户的问题。
**请使用Markdown格式组织回答，要求精简回答！**
用户会给你一个故障的异常描述，你需要根据异常分析故障原因并给出建议措施。
- 回答规范 -
1.只需要根据用户提供的故障描述，回答故障原因和建议措施，不要给出多余信息。
2.回答格式为：“## 故障原因：\n （具体故障原因） \n建议措施：\n （具体建议措施）”
-----
\n{web_block}\n
用户问题：{query}
"""

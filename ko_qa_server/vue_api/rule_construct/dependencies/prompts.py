import json
from typing import Dict


def build_rule_name_prompt(batch) -> str:
    # rule_generation 内部函数：规则模板批量命名提示词。
    return f"""
# 角色
你是知识图谱/Neo4j 方向的业务规则架构师。

# 任务
下面给你一些“自动聚类后的规则模板”，每个模板都来自真实图谱路径的结构归纳。
你需要为每个模板生成一个清晰、可复用、业务化的规则名(rule_name)。

每个模板包含：
- entry_sig：入口节点角色（前驱关系、后继关系）
- rel_chain：关系链
- exit_sig：出口节点角色
- support：该模板在路径中出现的支持度
- entry_examples / exit_examples：入口和出口样例节点
- sample_paths：样例完整路径
- getIn4simi：入口实体召回查询
- rule_path：规则主体路径查询

# 命名要求
1. rule_name 要业务化，不要写 Cypher 语法。
2. rule_name 要尽量表达“从什么对象出发，查询什么内容 / 规则 / 结论”。
3. 不要使用某个具体实例名，尽量抽象成类别。
4. getIn4simi 和 rule_path 必须原样返回，不要改写。
5. 只输出 JSON 数组，不要 markdown，不要解释。
6. rule_name 只能描述 rule_path 实际返回的最终对象，禁止使用“及其”“和”“要求”等会把结果扩展到下一跳的表达。

# 输出格式
[
  {{
    "rule_name": "...",
    "getIn4simi": "...",
    "rule_path": "..."
  }}
]

# 输入
{json.dumps(batch, ensure_ascii=False, separators=(",", ":"))}
"""


def build_file_rule_parse_prompt(relation_list, rule_des) -> str:
    # uploadRule 内部函数：自然语言规则到关系链的解析提示词。
    return f"""
    # Role
    你是一名知识图谱逻辑解析专家。你的任务是将自然语言描述的规则转化为结构化的逻辑链条。

    # Context
    系统预定义了一组合法的【关系集合 (Relation Set)】。你在构建逻辑链时，必须严格遵守以下原则：
    1. **严格受限**：只能使用【关系集合】中存在的词汇作为连接关系。
    2. **语义映射**：如果输入文本中的动词/介词不在列表中，必须选择列表中**语义最接近**的标准术语进行替换。
    3. **禁止造词**：严禁创造任何列表中不存在的新关系词。
    4. **路径完整**：保留推理过程中的所有关键逻辑节点，但连接词必须标准化。

    # Input Data
    - **合法关系列表**: valid_relations_list
    - **规则描述文本**: user_input_text

    # Output Format
    请仅输出一个标准的 **JSON 对象**，不要包含 markdown 代码块标记（如 ```json）、解释性文字或前缀。
    JSON 结构定义如下：
    {{
      "rule_name": "从输入文本中提取或概括出的简短规则名称（字符串），**但不能具有任何实体名称，例如“苹果”，“手机”等**",
      "relation_chain": ["关系词1", "关系词2", "关系词3"] // 必须是来自合法关系列表的字符串数组，按逻辑顺序排列
      "rule_entry": "从输入文本中提取或概括出的实体名称（字符串），**但不能具有任何关系词，例如“是”，“是”等**"
    }}

    # Few-Shot Examples

    ## Example 1
    Input:
    - 合法关系列表: ["母亲", "父亲", "妹妹"]
    - 规则描述文本: 外祖父是母亲的父亲

    Output:
    {{"rule_name": "外祖父关系推导", "relation_chain": ["母亲", "父亲"], "rule_entry": "外祖父"}}

    ## Example 2
    Input:
    - 合法关系列表: ["处置建议", "异常现象", "故障类型"]
    - 规则描述文本: 故障处理建议，机器需要先从异常现象定位故障类型，再根据故障类型给出处置建议。

    Output:
    {{"rule_name": "故障处理建议", "relation_chain": ["异常现象", "故障类型", "处置建议"], "rule_entry": "机器"}}

    ## Example 3
    Input:
    - 合法关系列表: ["生长环境", "病害", "虫害"]
    - 规则描述文本: 土豆的病虫害，土豆可能生长在不同环境中，不同环境中的土豆会遭受不同的病害，不同的病害又会引发虫害。

    Output:
    {{"rule_name": "病虫害", "relation_chain": ["生长环境", "病害", "虫害"], "rule_entry": "土豆"}}

    # 注意
    Example 3中的“土豆”是具体实体，不能体现在"rule_name"中。

    # Task
    Example 1, Example 2, Example 3 中的"relation_chain"均是从合法关系列表中找的对应关系。
    请根据提供的【合法关系列表】和【规则描述文本】，执行语义映射并生成对应的 JSON 输出。

    ---
    **当前输入数据：**
    合法关系列表: {relation_list}
    规则描述文本: {rule_des}

    **输出：**
    """


def build_semantic_validate_prompt(rule_item: Dict[str, str], best_path: str) -> str:
    # uploadRule 内部函数：规则语义校验提示词。
    return f"""
你是知识图谱规则语义验证器。

【输入】

规则头(rule_name)

用户规则描述(rule_desc)

规则体(rule_path / getIn4simi)

图谱中检索得到的最佳子路径(best_path)

【待验证规则】
{json.dumps(rule_item, ensure_ascii=False, indent=2)}

【最佳子路径】
{best_path}

【任务】
请判断该规则是否语义成立：

规则头是否语义成立

是否准确表达了“从入口到出口想得到的结论关系和目标信息”

是否与用户意图一致

是否存在方向颠倒

路径的最后一个关系名称是否与规则头(rule_name)意思相近，当最后一个关系是方法，而规则头是关于类型或种类时也不满足要求

【输出要求】
只输出一个 JSON 对象，不要 markdown，不要解释文字。

【输出格式】
{{
"passed": true,
"reason": "......",
"problem_type": "none",
"suggestion": "",
"normalized_rule_name": "...",
"normalized_rule_desc": "..."
}}

【示例1】
输入
{{
    规则头(rule_name)：根据水果种类确定规则
    用户规则描述(rule_desc)：不同的水果种类
    规则体(rule_path)：(南方水果)-[种类]->(苹果)
    最佳子路径(best_path)：(南方水果)-[种类]->(苹果)
}}
输出
{{
  "passed": true,
  "reason": "规则头语义成立，路径最后一个关系'种类'与规则头'根据水果种类确定规则'意思相近，方向正确，与用户意图一致。",
  "problem_type": "none",
  "suggestion": "",
  "normalized_rule_name": "水果种类确定规则",
  "normalized_rule_desc": "不同的水果种类"
}}
【示例2】
输入
{{
    规则头(rule_name)：根据水果种类确定规则
    用户规则描述(rule_desc)：不同的水果种类
    规则体(rule_path)：(南方水果)-[种类]->(苹果)->[生长环境]->(应在温度、湿度适宜的环境中成长)
    最佳子路径(best_path)：(南方水果)-[种类]->(苹果)->[生长环境]->(应在温度、湿度适宜的环境中成长)
}}
输出
{{
  "passed": false,
  "reason": "最佳子路径的出口节点应为种类的描述，实际出口为生长环境。",
  "problem_type": "none",
  "suggestion": "",
  "normalized_rule_name": "水果的生长环境",
  "normalized_rule_desc": "水果生长的适宜环境"
}}

problem_type 只能是：

none

name_mismatch（包括规则头名称与路径最后一个关系名称意思不相近的情况）

desc_mismatch

entry_exit_mismatch

direction_mismatch

other
"""


def build_repair_rule_prompt(rule_item: Dict[str, str], best_path: str) -> str:
    # uploadRule 内部函数：规则语义修复提示词。
    return f"""
你是知识图谱规则修复器。

【原规则】
{json.dumps(rule_item, ensure_ascii=False, indent=2)}

【最佳子路径】
{best_path}

【任务】
该规则在图谱中已经存在真实可行路径，但语义验证未通过。
请基于最佳子路径对规则进行修复，目标是让规则头、规则描述、规则体三者语义一致。

【修复要求】
1. 尽量少改动
2. 优先修正规则头(rule_name)和规则描述(rule_desc)
3. 若必须修改 rule_path，只允许沿着 best_path 的语义方向做小幅修正
4. 必须保留 getIn4simi、rule_path
5. rule_path 必须保留 {{entityname}} 占位，并 RETURN p
6. 不要输出解释，不要 markdown，只输出一个 JSON 对象
7. 不允许更换图谱领域，不允许引入无关 label

【输出格式】
{{
  "rule_name": "...",
  "rule_desc": "...",
  "getIn4simi": "...",
  "rule_path": "..."
}}
"""

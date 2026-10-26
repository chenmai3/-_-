"""Adapt Chunfeng QA's existing intent recognition to standard generation."""

from ..qa_answer.graph_stream_answer import get_kdzn_engine


def classify_standard_request(query: str) -> str:
    engine = get_kdzn_engine()
    # Use the same general intent prompt and recognize_intent/is_chitchat_turn
    # methods as csg_port_stream_refactored, without loading graph assets.
    domain = (
        '根据主题、技术材料或修改要求，生成、编写、起草或完善标准、规范、规程等标准文档。'
        '只有要求产出或修改标准文档才属于本系统任务；打招呼、询问身份、'
        '普通知识问答以及解释已有标准的含义均属于 Chitchat。'
    )
    base = engine.prompt_list['general_base_prompt'].replace('__scene__', '标准生成').replace('__domain_desc__', domain)
    prompt = engine.prompt_list['general_add_prompt'].replace('__scene__', '标准生成')
    prompt = prompt.replace('__file_name_list__', "['标准文档编写']").replace('__history__', '暂无上一轮问答')
    prompt = prompt.replace('__input__', query)
    intent = engine.recognize_intent(query, base + '\n' + prompt)
    if not engine.is_chitchat_turn('标准生成', intent, ''):
        return 'standard'

    # Reuse the genealogy scene's classifier before routing to general chat.
    family_prompt = engine.prompt_list['jiapu_general_yitu_file'].replace('__input__', query)
    family_intent = engine.recognize_intent(query, family_prompt)
    return 'family' if family_intent.yitu == 'jiapu Query' else 'chat'

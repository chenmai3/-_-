import yaml
from openai import OpenAI

from ..common import CONFIG_PATH


with CONFIG_PATH.open(encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


class llm_config:
    # graph_construct 当前只在文件向量化和入口实体向量化中使用 embedding client。
    def __init__(self):
        self.embedd = OpenAI(
            api_key=cfg["embedding_models"]["api_key"],
            base_url=cfg["embedding_models"]["base_url"],
        )


def call_qwen_max(messages):
    # uploadRule 内部函数：调用 Qwen Max 解析上传文件里的规则描述。
    client = OpenAI(
        api_key=cfg["qa_models"]["qwen"]["api_key"],
        base_url=cfg["qa_models"]["qwen"]["base_url"],
    )
    model_name = cfg["qa_models"]["qwen"]["qwenMax"]
    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.0,
            stream=False,
        )
        return completion.choices[0].message.content
    except Exception as exc:
        print(f"[rule_construct] Qwen Max 调用失败: {repr(exc)}")
        if getattr(exc, "code", "") == "data_inspection_failed":
            return "我们换个话题聊聊吧。"
        return ""


def call_qwen_small(messages):
    # rule_generation 内部函数：规则命名、语义校验、规则修复共用的小模型调用。
    client = OpenAI(
        api_key=cfg["small_models"]["qwen"]["api_key"],
        base_url=cfg["small_models"]["qwen"]["base_url"],
    )
    model_name = cfg["small_models"]["qwen"]["qwen2.5_model_name"]
    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.0,
            stream=False,
        )
        return completion.choices[0].message.content
    except Exception as exc:
        print(f"[rule_construct] 小模型调用失败: {repr(exc)}")
        if getattr(exc, "code", "") == "data_inspection_failed":
            return "我们换个话题聊聊吧。"
        return ""

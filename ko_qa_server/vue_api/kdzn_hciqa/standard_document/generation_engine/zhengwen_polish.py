from .qwen80b_chat import chat_async
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent

def polish_chat(chapters):
    path = BASE_DIR / "prompt" / "4zhengwen_polish.md"
    with open(path, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    system_message = {"role": "system", "content": system_prompt}
    messages_list = [
        [system_message, {"role": "user", "content": chapters[i]}] for i in range(len(chapters))
    ]
    results = chat_async(messages_list, "正文润色")
    return results

def zhengwen_polish(chapters, polish_math_express=False):
    # if polish_math_express:
    #     chapters = polish_math_expressions(chapters)
    chapters = polish_chat(chapters)
    return chapters


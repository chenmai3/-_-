import json
import os
import shutil
from pathlib import Path
import subprocess
import re
# from shuyu_replace import shuyu_replace
from .fun import gen_yinyan_fanwei_yinyong_stream, gen_title
from .qwen80b_chat import get_standard_llm_client, get_standard_llm_config, run_stage_with_progress
from .zhengwen_process import zhengwen_chat_prepare, chapter_format
from .shuyu_replace import shuyu_replace
import time
import os
from pathlib import Path
from .md2json import qianyan2json, shuyu2json,yinyan2json,yinyong2json,fanwei2json, zhengwen2json
from .zhengwen_md import json2md
BASE_DIR = Path(__file__).resolve().parent

# 标准文档生成的大模型配置统一从环境变量/配置文件读取，避免在业务代码里散落密钥和服务地址。


def make_latex(name: str):
    src_dir = BASE_DIR / "latex_configure"
    dst_dir = BASE_DIR / "latex_cache" / name
    result_dir = BASE_DIR / "result"

    # 创建目录
    dst_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    print("✅ 目录已准备")

    # 复制模板
    for item in src_dir.iterdir():
        if item.is_dir():
            shutil.copytree(item, dst_dir / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst_dir / item.name)
    print("✅ 模板复制完成")

    original_cwd = Path.cwd()
    success = False

    try:
        os.chdir(dst_dir)

        # 编译三次
        for i in range(3):
            try:
                result = subprocess.run(
                    ["xelatex", "-interaction=nonstopmode", "main.tex"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    timeout=60  # 建议延长至60秒
                )

                print(f"🔄 第 {i+1} 次编译完成 (returncode={result.returncode})")
                if result.returncode != 0:
                    print(f"⚠️  xelatex 第 {i+1} 次失败")
            except subprocess.TimeoutExpired:
                print(f"⏰ 第 {i+1} 次编译超时")
                break

        # 检查 PDF 是否生成
        pdf_path = Path("main.pdf")
        if pdf_path.exists():
            final_name = f"{name}.pdf"
            pdf_path.rename(final_name)
            target_path = result_dir / final_name
            shutil.move(final_name, target_path)
            print(f"✅ PDF 已保存至 {target_path}")
            success = True
        else:
            print("❌ 未生成 main.pdf，编译可能失败")

    except Exception as e:
        print(f"💥 编译过程中发生异常: {e}")
    finally:
        os.chdir(original_cwd)
        # 清理临时目录
        if dst_dir.exists():
            try:
                shutil.rmtree(dst_dir)
                print("🧹 临时目录已清理")
            except Exception as e:
                print(f"⚠️ 无法删除临时目录 {dst_dir}: {e}")

    return success


def gen_zhengwen_stream_json2md(zhengwen_json):
    class SYMBOL:
        TEXT = "text"
        TYPE = "type"
        TEXT_NUMBER = "text_number"

    polish_math_list, res, change_idx = json2md(zhengwen_json)
    path = BASE_DIR / "prompt" / "4zhengwen_polish_math_express.md"
    with open(path, 'r', encoding='utf-8') as f:
        prompt = f.read()
    system_message = {"role": "system", "content": prompt}
    messages_list = [
        [system_message, {"role": "user", "content": text}] for text in polish_math_list
    ]

    polish_math_res = yield from run_stage_with_progress(
        messages_list=messages_list,
        task_name="正文数学表达式润色",
        status_section="dagang",
        model=get_standard_llm_config()["model"],
        max_concurrency=10,
    )
    j = 0
    for i, r in enumerate(res):
        if r is None:
            res[i] = polish_math_res[j]
            j += 1
    j = 0
    for i in change_idx:
        zhengwen_json[i][SYMBOL.TEXT] = polish_math_res[j]
        j += 1

    zhengwen_md = '\n'.join(res)
    return zhengwen_md, zhengwen_json



def zhengwen_polish_stream(chapters):
    """
    正文润色（带进度流式），返回每章润色后的文本 list
    """
    # polish_math_expressions
    # path = BASE_DIR / "prompt" / "4zhengwen_polish_math_express.md"
    # with open(path, 'r', encoding='utf-8') as f:
    #     prompt = f.read()
    # system_message = {"role": "system", "content": prompt}
    # messages_list = [
    #     [system_message, {"role": "user", "content": chapters[i]}] for i in range(len(chapters))
    # ]
    #
    # chapters = yield from run_stage_with_progress(
    #     messages_list=messages_list,
    #     task_name="正文数学表达式润色",
    #     status_section="dagang",
    #     model="qwen2.5-72b-instruct",
    #     max_concurrency=10,
    # )
    # polished = yield from run_stage_with_progress(
    #     messages_list=messages_list,
    #     task_name="正文润色",
    #     status_section="dagang",
    #     model="qwen2.5-72b-instruct",
    #     max_concurrency=10,
    # )


    # polish_chat
    path = BASE_DIR / "prompt" / "4zhengwen_polish.md"
    with open(path, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    system_message = {"role": "system", "content": system_prompt}

    messages_list = [
        [system_message, {"role": "user", "content": chapters[i]}]
        for i in range(len(chapters))
    ]

    # 也用 dagang(zhengwen)_status，把“正文生成 + 润色”的全流程日志打在同一个框里；
    # 你也可以改成 'zhengwen_polish_status'，前端单独显示。
    chapters = yield from run_stage_with_progress(
        messages_list=messages_list,
        task_name="正文润色",
        status_section="dagang",
        model=get_standard_llm_config()["model"],
        max_concurrency=10,
    )
    return chapters


def gen_zhengwen_stream(chapter_contents):
    """
    章节正文生成（带进度流式），返回每章生成后的文本 list
    """
    path = BASE_DIR / "prompt" / "4zhengwen_content.md"
    with open(path, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    system_message = {"role": "system", "content": system_prompt}
    messages_list = [
        [system_message, content] for content in chapter_contents
    ]

    # dagang(zhengwen)_status：放第二个竖框上方
    chapter_outputs = yield from run_stage_with_progress(
        messages_list=messages_list,
        task_name="正文生成",
        status_section="dagang",
        model=get_standard_llm_config()["model"],
        max_concurrency=10,
    )
    return chapter_outputs


def stream_section(section_name: str, text: str, chunk_size: int = 5):
    """
    将一段 text 按 chunk_size 字符切片，逐块通过 SSE 推送到前端。
    每块都是完整的 JSON：{"section": section_name, "content": "..."}。
    """
    # JSON already preserves whitespace and newlines; slice the original text.
    for idx in range(0, len(text), chunk_size):
        payload = {"section": section_name, "content": text[idx:idx + chunk_size]}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def generate_content(text, state):
    final_res = []
    input_content = text
    start_time = time.time()
    llm_config = get_standard_llm_config()
    client = get_standard_llm_client()

    # ---------- 1. 前言 ----------
    # 状态提示（可选）
    yield f"data: {json.dumps({'section': 'qianyan_status', 'content': '正在生成前言中'})}\n\n"
    # 标题（如果前端自己有标题，也可以去掉）
    # yield f"data: {json.dumps({'section': 'qianyan', 'content': '**前言**StReAmNeWlInEStReAmNeWlInE'})}\n\n"
    path_1 = BASE_DIR / "prompt" / "0qianyan_content.md"
    with open(path_1, 'r', encoding='utf-8') as file:
        qianyan_content = file.read()
    qianyan_messages = [
        {"role": "system", "content": qianyan_content},
        {"role": "user", "content": input_content}
    ]

    # try:
    response = client.chat.completions.create(
        model=llm_config["model"],
        messages=qianyan_messages,
        stream=True,
        temperature=llm_config["temperature"],
        top_p=llm_config["top_p"],
        max_tokens=llm_config["max_tokens"],
    )
    res_1 = []
    for msg in response:
        delta = msg.choices[0].delta
        if delta.content:
            delta_raw = delta.content
            text_delta = delta_raw.replace('\n', 'StReAmNeWlInE').replace(' ', 'StReAmSpAcE')
            # 这里 section 固定为 qianyan
            payload = {"section": "qianyan", "content": text_delta}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            time.sleep(0.02)
            res_1.append(delta_raw)
    qianyan_markdown = "".join(res_1).strip()
    # except Exception as e:
    #     print(f"\n[Error] {e}")
    #     return None

    qianyan_json = qianyan2json(qianyan_markdown)

    yield f"data: {json.dumps({'section': 'qianyan_status', 'content': '完成'})}\n\n"
    time.sleep(0.02)
    # ---------- 2. 大纲（内部使用，不展示） ----------
    yield f"data: {json.dumps({'section': 'dagang_status', 'content': '正在生成大纲中'})}\n\n"
    time.sleep(0.02)
    dagang = ''
    path_2 = BASE_DIR / "prompt" / "dagang_content.md"
    with open(path_2, 'r', encoding='utf-8') as file:
        dagang_content = file.read()
    dagang_messages = [
        {"role": "system", "content": dagang_content},
        {"role": "user", "content": input_content}
    ]
    # ★ 先打一块 H1 标题：# 大纲
    title_md = "# 大纲\n\n"
    title_encoded = (
        title_md
            .replace('\n', 'StReAmNeWlInE')
            .replace(' ', 'StReAmSpAcE')
    )
    title_payload = {
        "section": "dagang",  # 或者 "shuyu_title"，看你前端怎么分支
        "content": title_encoded
    }
    yield f"data: {json.dumps(title_payload, ensure_ascii=False)}\n\n"
    try:
        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=dagang_messages,
            stream=True,
            temperature=llm_config["temperature"],
            top_p=llm_config["top_p"],
            max_tokens=llm_config["max_tokens"],
        )
        res_2 = []
        for msg in response:
            delta = msg.choices[0].delta
            if delta.content:
                delta_raw = delta.content
                # 大纲一般不展示，但我们仍打上 section=dagang，前端可以忽略
                text_delta = delta_raw.replace('\n', 'StReAmNeWlInE').replace(' ', 'StReAmSpAcE')
                payload = {"section": "dagang", "content": text_delta}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                time.sleep(0.02)
                res_2.append(delta_raw)
        dagang = "".join(res_2).strip()
    except Exception as e:
        raise RuntimeError("标准生成阶段失败") from e
    # pattern_blocks = r'(^#\s*\d+[^\n]*)(.*?)(?=\n#\s*\d|\Z)'
    # blocks = re.findall(pattern_blocks, dagang, flags=re.MULTILINE | re.DOTALL)
    # print()

    yield f"data: {json.dumps({'section': 'dagang_status', 'content': '正在生成正文中'})}\n\n"
    # ---------- 2.1 由大纲拆成章节 ----------
    chapter_contents = zhengwen_chat_prepare(dagang, input_content)

    # ---------- 2.2 正文生成（带进度流式） ----------
    # 会不断 yield 出 "✅ 正文生成 [会话 i] 开始对话/回答完毕" 这类信息，
    # section = 'dagang(zhengwen)_status'
    chapter_outputs = yield from gen_zhengwen_stream(chapter_contents)

    yield f"data: {json.dumps({'section': 'dagang_status', 'content': '正文润色中'})}\n\n"

    # ---------- 2.3 正文润色（带进度流式） ----------
    # 同样所有过程（每章开始/结束/异常）都会以 dagang(zhengwen)_status 的形式流出
    chapter_outputs = yield from zhengwen_polish_stream(chapter_outputs)

    # ---------- 2.4 格式化 + 拼接 ----------
    idx_formula_start, idx_table_start = 1, 1
    for i, chapter in enumerate(chapter_outputs):
        chapter, idx_formula_start, idx_table_start = chapter_format(
            chapter, idx_formula_start, idx_table_start
        )
        chapter_outputs[i] = chapter

    zhengwen_outputs = "\n\n".join(chapter_outputs).strip()
    zhengwen_json = zhengwen2json(zhengwen_outputs)
    zhengwen_markdown, zhengwen_json = yield from gen_zhengwen_stream_json2md(zhengwen_json)
    yield from stream_section('dagang(zhengwen)', zhengwen_markdown, chunk_size=200)
    yield f"data: {json.dumps({'section': 'dagang_status', 'content': '完成'})}\n\n"
    time.sleep(0.02)
    # 由大纲生成正文
    # zhengwen = gen_zhengwen(dagang, input_content)

    # ---------- 3. 术语 ----------
    yield f"data: {json.dumps({'section': 'shuyu_status', 'content': '正在进行术语抽取'})}\n\n"
    time.sleep(0.02)
    path_3 = BASE_DIR / "prompt" / "3shuyu_content.md"
    with open(path_3, 'r', encoding='utf-8') as file:
        shuyu_system_content = file.read()
    shuyu_messages = [
        {"role": "system", "content": shuyu_system_content},
        {"role": "user", "content": zhengwen_markdown}
    ]
    # ★ 先打一块 H1 标题：# 3 术语和定义
    title_md = "# 3 术语和定义\n\n"
    title_encoded = (
        title_md
            .replace('\n', 'StReAmNeWlInE')
            .replace(' ', 'StReAmSpAcE')
    )
    title_payload = {
        "section": "shuyu",  # 或者 "shuyu_title"，看你前端怎么分支
        "content": title_encoded
    }
    yield f"data: {json.dumps(title_payload, ensure_ascii=False)}\n\n"
    try:
        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=shuyu_messages,
            stream=True,
            temperature=llm_config["temperature"],
            top_p=llm_config["top_p"],
            max_tokens=llm_config["max_tokens"],
        )
        res_3 = []
        for msg in response:
            delta = msg.choices[0].delta
            if delta.content:
                delta_raw = delta.content  # 原始分片
                # ★ 核心：在中文句号 "。" 后自动加换行（前面没有换行的情况才加）
                # 例如： "术语A。术语B。" -> "术语A。\n术语B。\n"
                delta_with_newline = re.sub(r'。(?!\n)', '。\n\n', delta_raw)
                # 然后再做占位符编码
                text_delta = (
                    delta_with_newline
                        .replace('\n', 'StReAmNeWlInE')
                        .replace(' ', 'StReAmSpAcE')
                )

                payload = {"section": "shuyu", "content": text_delta}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                time.sleep(0.02)

                # 后续要用的完整术语文本，也用“加过换行”的版本来累积
                res_3.append(delta_with_newline)
        shuyu_md = "".join(res_3).strip()
    except Exception as e:
        raise RuntimeError("标准生成阶段失败") from e

    # 术语替换正文
    shuyu_md, zhengwen_markdown, shuyu_replace_info = shuyu_replace(shuyu_md, zhengwen_markdown, model_name='bge-large-zh')
    shuyu_json = shuyu2json(shuyu_replace_info)
    # ---------- 4. 正文 ----------
    # 状态提示可以只打一块
    yield f"data: {json.dumps({'section': 'zhengwen_status', 'content': '正在对正文进行术语替换'}, ensure_ascii=False)}\n\n"
    # time.sleep(10)
    # yield f"data: {json.dumps({'section': 'zhengwen_status', 'content': '**正在生成正文中**'}, ensure_ascii=False)}\n\n"
    time.sleep(0.02)
    yield from stream_section('zhengwen', zhengwen_markdown, chunk_size=200)
    yield f"data: {json.dumps({'section': 'shuyu_status', 'content': '完成'})}\n\n"
    time.sleep(0.02)

    # ---------- 5. 引言 / 范围 / 引用 ----------
    yield f"data: {json.dumps({'section': 'yinyan-fanwei-yinyong_status', 'content': '引言、范围和规范性引用文件生成中'}, ensure_ascii=False)}\n\n"
    # yinyan, fanwei, yinyong = gen_yinyan_fanwei_yinyong(zhengwen, shuyu_replace_info)
    yinyan_markdown, fanwei_markdown, yinyong_markdown = yield from gen_yinyan_fanwei_yinyong_stream(zhengwen_markdown, shuyu_replace_info)
    yinyan_json = yinyan2json(yinyan_markdown)
    fanwei_json = fanwei2json(fanwei_markdown)
    yinyong_json = yinyong2json(yinyong_markdown)
    for sse_chunk in stream_section('yinyan', yinyan_markdown, chunk_size=20):
        yield sse_chunk

    for sse_chunk in stream_section('fanwei', fanwei_markdown, chunk_size=20):
        yield sse_chunk

    for sse_chunk in stream_section('yinyong', yinyong_markdown, chunk_size=20):
        yield sse_chunk

    yield f"data: {json.dumps({'section': 'yinyan-fanwei-yinyong_status', 'content': '完成'})}\n\n"
    time.sleep(0.02)


    title_md, title_json = gen_title(input_content, zhengwen_markdown)


    json_data = {
        'qianyan': qianyan_json,
        'yinyan': yinyan_json,
        'fanwei': fanwei_json,
        'yinyong': yinyong_json,
        'shuyu': shuyu_json,
        'title': title_json,
        'zhengwen': zhengwen_json,
    }

    final_res.append(str(yinyan_markdown))
    final_res.append(str(fanwei_markdown))
    final_res.append(str(yinyong_markdown))
    final_res.append(str(shuyu_md))
    final_res.append(str(zhengwen_markdown))
    full_standard_text = "\n\n".join(final_res)
    state.answer_content = full_standard_text
    # print(state.answer_content)
    chunk_size = max(50, len(full_standard_text) // 6)
    for sse_chunk in stream_section('final_res', full_standard_text, chunk_size=chunk_size):
        yield sse_chunk
    time.sleep(0.02)




    print('========== 最终整合 ==========')
    from .ko_latex import gen_latex
    now_time = str(int(time.time()))
    gen_latex(json_data, now_time)
    print(f'耗时{time.time() - start_time}s')

    make_latex(now_time)
    print("xelatex main.tex 成功")

    # 保存为doc文件
    try:
        import pypandoc

        # 检查是否已有 pandoc
        pypandoc.get_pandoc_version()
    except OSError:
        print("Pandoc 未找到，正在自动下载安装...")
        pypandoc.download_pandoc()  # 默认下载到用户目录，如 ~/.cache/pypandoc/

    # 转换为 PDF 文档
    out_file = now_time
    relative_dir = BASE_DIR / "result"
    output_path = os.path.join(relative_dir, f"{out_file}.pdf")
    # output = pypandoc.convert_text(full_standard_text, 'docx', format='md', outputfile=output_path)
    path = output_path
    print(path)
    # if not output:
    #     print(f"✅ 已成功保存为 f{out_file}.docx")
    # else:
    #     print("❌ 转换失败:", output)
    print(f'耗时{time.time() - start_time}s')
    yield f"data: {json.dumps({'section': 'doc_path', 'content': path}, ensure_ascii=False)}\n\n"


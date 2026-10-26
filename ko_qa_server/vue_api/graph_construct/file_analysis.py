import asyncio
import json
import re
import tempfile
import time
import traceback
from copy import deepcopy
from pathlib import Path

import httpx
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from fastapi import HTTPException, UploadFile

from .common import (
    ANALYSIS_TASKS,
    ANALYSIS_TASK_LOCK,
    LOCAL_ANALYSIS_FILE_ROOT,
    basename_any_path,
    create_analysis_task,
    frontend_error,
    frontend_success,
    get_analysis_task,
    safe_path_name,
    update_analysis_task,
)


UPLOAD_URL = "https://ko.zhonghuapu.com/api/extraction/saveFile2/"
WORD_ANALYZE_URL = "https://koapi.zhonghuapu.com/query_haograph/Word2kgPipeline"
FILE_ANALYZE_URL = "https://ko.zhonghuapu.com/koapi/query_haograph/FileAnalysis"
GRAPH_URL = "https://koapi.zhonghuapu.com/query_haograph/GraphConstruction"
SERVER_FILE_DIR = Path("file")
TRIPLE_RESULT_HEADER = ["根节点", "类型", "头实体", "关系", "尾实体"]

DOCX_CONCURRENCY = 2
HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=1800.0, write=120.0, pool=10.0)
HTTPX_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=0)


def split_docx_by_chapter(src_docx_path, output_dir, server_prefix=""):
    # save_analysis_and_enterData 接口内部函数：按“第 X 章”标题切割 docx。
    src_docx_path = Path(src_docx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not src_docx_path.exists():
        raise FileNotFoundError(f"源 Word 文件不存在: {src_docx_path}")

    chapter_re = re.compile(r"^\s*第\s*[一二三四五六七八九十百千万零〇两\d]+\s*章(?:[\s:：、.．-]*.*)?$")

    def safe_chapter_name(name):
        name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name.strip())
        return re.sub(r"\s+", " ", name)[:120] or "未命名章节"

    def is_chapter(element, doc):
        if element.tag != qn("w:p"):
            return False
        text = Paragraph(element, doc).text.strip()
        if not text or "..." in text or "……" in text or "…" in text:
            return False
        return bool(chapter_re.match(text))

    doc = Document(str(src_docx_path))
    chapters = []
    current_title = None
    current_elements = []

    for element in doc.element.body.iterchildren():
        if element.tag == qn("w:sectPr"):
            continue
        if is_chapter(element, doc):
            if current_title and current_elements:
                chapters.append((current_title, current_elements))
            current_title = Paragraph(element, doc).text.strip()
            current_elements = [deepcopy(element)]
        elif current_title:
            current_elements.append(deepcopy(element))

    if current_title and current_elements:
        chapters.append((current_title, current_elements))

    if not chapters:
        return [{
            "path": str(src_docx_path),
            "chapter_name": src_docx_path.name,
            "safe_chapter_name": src_docx_path.name,
            "filename": src_docx_path.name,
            "is_full_document": True,
        }]

    result = []
    used_names = {}
    for title, elements in chapters:
        base_name = safe_chapter_name(title)
        count = used_names.get(base_name, 0) + 1
        used_names[base_name] = count
        chapter_name = base_name if count == 1 else f"{base_name}_{count}"
        part_path = output_dir / f"{server_prefix}{chapter_name}.docx"
        if part_path.exists():
            part_path.unlink()

        new_doc = Document(str(src_docx_path))
        body = new_doc.element.body
        sect_pr = deepcopy(body.sectPr) if body.sectPr is not None else None
        for item in list(body):
            body.remove(item)
        for item in elements:
            body.append(deepcopy(item))
        if sect_pr is not None:
            body.append(sect_pr)
        new_doc.save(str(part_path))

        result.append({
            "path": str(part_path),
            "chapter_name": base_name,
            "safe_chapter_name": chapter_name,
            "filename": part_path.name,
        })
    return result


def safe_json_response(resp: httpx.Response, api_name: str):
    try:
        return resp.json()
    except Exception as exc:
        raise ValueError(f"{api_name} 返回不是合法 JSON: status={resp.status_code}, response={resp.text[:1000]}") from exc


def parse_uploaded_filename(upload_result):
    # save_analysis_and_enterData 接口内部函数：兼容外部上传接口的多种返回结构。
    if isinstance(upload_result, str) and upload_result.strip():
        return basename_any_path(upload_result)
    if isinstance(upload_result, dict):
        for key in ("filename", "fileName", "name", "path", "url"):
            value = upload_result.get(key)
            if isinstance(value, str) and value.strip():
                return basename_any_path(value)
        for key in ("data", "result"):
            value = upload_result.get(key)
            if value:
                return parse_uploaded_filename(value)
    raise ValueError(f"上传接口返回格式错误: {upload_result}")


def build_server_filename(user_id: str, uploaded_filename: str) -> str:
    uploaded_filename = basename_any_path(uploaded_filename)
    if uploaded_filename.startswith(f"{user_id}-"):
        return uploaded_filename
    return f"{user_id}-{uploaded_filename}"


def normalize_file_analysis_result(file_result) -> str:
    # save_analysis_and_enterData 接口内部函数：把 FileAnalysis 的返回整理成文本。
    if isinstance(file_result, str):
        content = file_result
    elif isinstance(file_result, dict):
        content = file_result.get("content") or file_result.get("text") or file_result.get("result")
        content = content or json.dumps(file_result, ensure_ascii=False)
    elif isinstance(file_result, list):
        content = "\n".join(
            item.get("content", str(item)) if isinstance(item, dict) else str(item)
            for item in file_result
        )
    else:
        content = str(file_result)

    if not content.strip():
        raise ValueError("FileAnalysis 返回内容为空")
    return content


def parse_graph_triples_response(graph_response, error_prefix: str):
    # save_analysis_and_enterData 接口内部函数：校验 GraphConstruction/Word2kgPipeline 三元组结构。
    if not isinstance(graph_response, list) or not graph_response:
        raise ValueError(f"{error_prefix}返回格式错误，期望非空 list，实际返回: {str(graph_response)[:1000]}")
    graph_data = graph_response[0]
    if not isinstance(graph_data, dict):
        raise ValueError(f"{error_prefix}数据格式错误: {str(graph_data)[:1000]}")
    triples = graph_data.get("triples", [])
    if not isinstance(triples, list):
        raise ValueError(f"{error_prefix} triples 不是 list: {str(graph_response)[:1000]}")
    return triples


def save_local_source_file(user_id: str, selected_main_topic: str, filename: str, file_bytes: bytes) -> Path:
    # save_analysis_and_enterData 接口内部函数：使用相对服务根目录保存原始文件。
    save_dir = LOCAL_ANALYSIS_FILE_ROOT / f"{safe_path_name(user_id)}_file_vectorstorges" / safe_path_name(selected_main_topic)
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / safe_path_name(filename)
    save_path.write_bytes(file_bytes)
    return save_path


async def handle_save_analysis_and_enter_data(user_id: str, file: UploadFile, selected_main_topic: str):
    original_filename = Path(file.filename or "未命名文件").name
    suffix = Path(original_filename).suffix.lower()
    file_content_type = file.content_type or "application/octet-stream"
    file_bytes = await file.read()

    if not file_bytes:
        return frontend_error("上传文件内容为空", status_code=400, data={"ok": False, "error": "上传文件内容为空"})

    save_local_source_file(user_id, selected_main_topic, original_filename, file_bytes)
    task_id = await create_analysis_task(user_id=user_id, original_filename=original_filename, suffix=suffix)
    asyncio_task = asyncio.create_task(
        run_analysis_task(
            task_id=task_id,
            user_id=user_id,
            original_filename=original_filename,
            suffix=suffix,
            file_bytes=file_bytes,
            file_content_type=file_content_type,
        )
    )

    async with ANALYSIS_TASK_LOCK:
        ANALYSIS_TASKS[task_id]["_asyncio_task"] = asyncio_task

    return frontend_success({
        "ok": True,
        "taskId": task_id,
        "status": "pending",
        "message": "文件已接收，后台解析已开始",
    })


async def handle_save_analysis_file(user_id: str, file: UploadFile):
    original_filename = Path(file.filename or "未命名文件").name
    file_bytes = await file.read()
    if not file_bytes:
        return {"ok": False, "error": "文件解析错误", "details": "上传文件内容为空"}

    try:
        async with httpx.AsyncClient(verify=False, timeout=HTTPX_TIMEOUT, limits=HTTPX_LIMITS) as client:
            server_filename, _ = await upload_original_file(
                client,
                user_id,
                original_filename,
                file_bytes,
                file.content_type or "application/octet-stream",
            )
            content, _ = await call_file_analysis(client, server_filename)
        return {"ok": True, "result": content}
    except Exception as exc:
        return {"ok": False, "error": "文件解析错误", "details": str(exc)}


async def handle_enter_data_with_file(payload: dict):
    content = str(payload.get("content") or "").strip()
    file_name = str(payload.get("file_name") or "").strip()
    if not content or not file_name:
        return {"ok": False, "error": "通过文件添加数据错误", "details": "content、file_name 不能为空"}

    try:
        async with httpx.AsyncClient(verify=False, timeout=HTTPX_TIMEOUT, limits=HTTPX_LIMITS) as client:
            triples, _ = await call_graph_construction(client, content)
        rows, _ = build_normal_file_result_rows(file_name, triples)
        return {"ok": True, "result": rows}
    except Exception as exc:
        return {"ok": False, "error": "通过文件添加数据错误", "details": str(exc)}


async def handle_analysis_progress(task_id: str):
    task = await get_analysis_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return frontend_success({
        "ok": True,
        "taskId": task.get("taskId"),
        "status": task.get("status"),
        "currentStep": task.get("currentStep"),
        "total": task.get("total"),
        "finished": task.get("finished"),
        "failed": task.get("failed"),
        "message": task.get("message"),
    })


async def handle_analysis_result(task_id: str):
    task = await get_analysis_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    status = task.get("status")
    if status == "success":
        result = task.get("result") or {}
        return frontend_success({
            "ok": True,
            "taskId": task_id,
            "status": "success",
            "message": task.get("message", "解析完成"),
            "extractionResult": result.get("extractionResult"),
            "debug": result.get("debug", task.get("debug", {})),
        })
    if status == "failed":
        return frontend_success({
            "ok": False,
            "taskId": task_id,
            "status": "failed",
            "message": task.get("message", "解析失败"),
            "error": task.get("error"),
            "debug": task.get("debug", {}),
            "extractionResult": None,
        })
    return frontend_success({
        "ok": False,
        "taskId": task_id,
        "status": status,
        "progress": task.get("progress", 0),
        "currentStep": task.get("currentStep"),
        "message": "任务尚未完成",
        "extractionResult": None,
    })


def build_task_failure_debug(exc: Exception, total_start: float):
    return {
        "exception_type": type(exc).__name__,
        "total_cost_seconds": round(time.time() - total_start, 2),
        "traceback": traceback.format_exc()[-3000:],
    }


async def run_analysis_task(*, task_id: str, user_id: str, original_filename: str, suffix: str, file_bytes: bytes, file_content_type: str):
    total_start = time.time()
    await update_analysis_task(task_id, status="running", currentStep="初始化解析任务", progress=1, message="后台解析任务已启动")
    try:
        result = await parse_uploaded_file_core(
            task_id=task_id,
            user_id=user_id,
            original_filename=original_filename,
            suffix=suffix,
            file_bytes=file_bytes,
            file_content_type=file_content_type,
        )
        debug = result.get("debug", {})
        debug["task_total_cost_seconds"] = round(time.time() - total_start, 2)
        await update_analysis_task(task_id, status="success", currentStep="解析完成", progress=100, message="解析完成", result=result, debug=debug)
    except Exception as exc:
        await update_analysis_task(
            task_id,
            status="failed",
            currentStep="解析失败",
            progress=100,
            error=str(exc),
            message="文件解析失败",
            debug=build_task_failure_debug(exc, total_start),
        )


async def parse_uploaded_file_core(*, task_id: str, user_id: str, original_filename: str, suffix: str, file_bytes: bytes, file_content_type: str):
    total_start = time.time()
    async with httpx.AsyncClient(verify=False, timeout=HTTPX_TIMEOUT, limits=HTTPX_LIMITS, trust_env=False) as client:
        if suffix == ".docx":
            return await parse_docx_file_core(task_id, user_id, original_filename, file_bytes, client, total_start)
        return await parse_normal_file_core(task_id, user_id, original_filename, suffix, file_bytes, file_content_type, client, total_start)


def write_docx_to_temp_parts_dir(original_filename: str, file_bytes: bytes, tmp_dir: Path):
    local_src_path = tmp_dir / original_filename
    local_parts_dir = tmp_dir / "parts"
    local_parts_dir.mkdir(parents=True, exist_ok=True)
    local_src_path.write_bytes(file_bytes)
    return local_src_path, local_parts_dir


async def upload_docx_part(client: httpx.AsyncClient, user_id: str, part_path: Path):
    upload_start = time.time()
    with part_path.open("rb") as f:
        resp = await client.post(
            UPLOAD_URL,
            data={"userId": user_id},
            files={"file": (part_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    upload_cost = round(time.time() - upload_start, 2)
    if resp.status_code != 200:
        raise RuntimeError(f"章节文件上传失败: file={part_path.name}, status={resp.status_code}, response={resp.text[:1000]}")
    uploaded_filename = parse_uploaded_filename(safe_json_response(resp, "章节上传接口"))
    return uploaded_filename, upload_cost


async def analyze_docx_part_on_server(client: httpx.AsyncClient, server_part_path: Path, server_part_filename: str):
    analyze_start = time.time()
    resp = await client.post(WORD_ANALYZE_URL, data={"word_path": str(server_part_path)})
    analyze_cost = round(time.time() - analyze_start, 2)
    if resp.status_code != 200:
        raise RuntimeError(f"章节docx解析失败: part={server_part_filename}, status={resp.status_code}, response={resp.text[:1000]}")
    triples = parse_graph_triples_response(safe_json_response(resp, "Word2kgPipeline"), f"章节图谱 part={server_part_filename} ")
    return triples, analyze_cost


def build_chapter_result_rows(root_filename: str, chapter_name: str, triples):
    chapter_rows = [TRIPLE_RESULT_HEADER.copy()]
    invalid_count = 0
    for triple in triples:
        if not isinstance(triple, (list, tuple)) or len(triple) < 3:
            invalid_count += 1
            continue
        head, relation, tail = triple[0], triple[1], triple[2]
        if isinstance(head, str) and head.startswith("Doc_doc_"):
            head = chapter_name
        if isinstance(tail, str) and tail.startswith("Doc_doc_"):
            tail = chapter_name
        chapter_rows.append([root_filename, "文件", head, relation, tail])
    return chapter_rows, invalid_count


async def analyze_one_docx_part(*, index: int, total_parts: int, part_info: dict, task_id: str, user_id: str, root_filename: str, client: httpx.AsyncClient):
    part_start = time.time()
    part_path = Path(part_info["path"])
    chapter_name = part_info["chapter_name"]
    if not part_path.exists():
        raise FileNotFoundError(f"待上传章节文件不存在: {part_path}")

    await update_analysis_task(task_id, currentStep=f"上传章节 {index}/{total_parts}", message=f"正在上传章节：{chapter_name}")
    uploaded_filename, upload_cost = await upload_docx_part(client, user_id, part_path)
    server_part_filename = build_server_filename(user_id, uploaded_filename)
    server_part_path = SERVER_FILE_DIR / server_part_filename

    await update_analysis_task(task_id, currentStep=f"解析章节 {index}/{total_parts}", message=f"正在解析章节：{chapter_name}")
    triples, analyze_cost = await analyze_docx_part_on_server(client, server_part_path, server_part_filename)
    chapter_rows, invalid_count = build_chapter_result_rows(root_filename, chapter_name, triples)

    return {
        "index": index,
        "chapter_name": chapter_name,
        "safe_chapter_name": part_info.get("safe_chapter_name", chapter_name),
        "local_part_filename": part_path.name,
        "uploaded_filename": uploaded_filename,
        "server_part_filename": server_part_filename,
        "server_part_path": str(server_part_path),
        "chapter_result_data": chapter_rows,
        "triples_count": len(triples),
        "rows_added": len(chapter_rows) - 1,
        "invalid_triples_count": invalid_count,
        "upload_cost_seconds": upload_cost,
        "analyze_cost_seconds": analyze_cost,
        "cost_seconds": round(time.time() - part_start, 2),
    }


async def analyze_docx_parts_with_progress(task_id: str, user_id: str, root_filename: str, part_infos, client: httpx.AsyncClient):
    total_parts = len(part_infos)
    sem = asyncio.Semaphore(DOCX_CONCURRENCY)
    counter_lock = asyncio.Lock()
    counters = {"finished": 0, "failed": 0}

    async def run_one(index, part_info):
        async with sem:
            try:
                part_result = await analyze_one_docx_part(
                    index=index,
                    total_parts=total_parts,
                    part_info=part_info,
                    task_id=task_id,
                    user_id=user_id,
                    root_filename=root_filename,
                    client=client,
                )
                async with counter_lock:
                    counters["finished"] += 1
                    progress = 15 + int(counters["finished"] / total_parts * 80)
                    await update_analysis_task(
                        task_id,
                        progress=min(progress, 95),
                        finished=counters["finished"],
                        failed=counters["failed"],
                        currentStep=f"章节解析进度 {counters['finished']}/{total_parts}",
                        message=f"已完成 {counters['finished']}/{total_parts} 个章节，当前完成：{part_result['chapter_name']}",
                    )
                return part_result
            except Exception:
                async with counter_lock:
                    counters["failed"] += 1
                    await update_analysis_task(
                        task_id,
                        finished=counters["finished"],
                        failed=counters["failed"],
                        currentStep=f"章节解析失败 {counters['failed']} 个",
                        message=f"已有 {counters['failed']} 个章节解析失败",
                    )
                raise

    raw_results = await asyncio.gather(
        *[run_one(index, part_info) for index, part_info in enumerate(part_infos, start=1)],
        return_exceptions=True,
    )
    errors = [item for item in raw_results if isinstance(item, Exception)]
    if errors:
        raise RuntimeError("; ".join(str(e) for e in errors[:3]))
    return sorted(raw_results, key=lambda x: x["index"])


def summarize_docx_part_results(root_filename: str, original_filename: str, all_results, total_start: float):
    result_data = [TRIPLE_RESULT_HEADER.copy()]
    debug_parts = []
    total_triples_count = total_rows_added = total_invalid_triples_count = 0
    for part_result in all_results:
        result_data.extend(part_result["chapter_result_data"][1:])
        total_triples_count += part_result["triples_count"]
        total_rows_added += part_result["rows_added"]
        total_invalid_triples_count += part_result["invalid_triples_count"]
        debug_parts.append({k: part_result[k] for k in (
            "index", "chapter_name", "safe_chapter_name", "local_part_filename",
            "uploaded_filename", "server_part_filename", "server_part_path",
            "triples_count", "rows_added", "invalid_triples_count",
            "upload_cost_seconds", "analyze_cost_seconds", "cost_seconds",
        )})

    return {
        "ok": True,
        "extractionResult": result_data,
        "debug": {
            "mode": "parse_only_docx_local_split_concurrency_2_async_task",
            "total_cost_seconds": round(time.time() - total_start, 2),
            "root_filename": root_filename,
            "original_filename": original_filename,
            "suffix": ".docx",
            "parts_count": len(debug_parts),
            "concurrency": DOCX_CONCURRENCY,
            "triples_count": total_triples_count,
            "rows_added": total_rows_added,
            "invalid_triples_count": total_invalid_triples_count,
            "result_count": len(result_data),
            "parts": debug_parts,
        },
    }


async def upload_original_file(client: httpx.AsyncClient, user_id: str, original_filename: str, file_bytes: bytes, file_content_type: str):
    upload_start = time.time()
    resp = await client.post(
        UPLOAD_URL,
        data={"userId": user_id},
        files={"file": (original_filename, file_bytes, file_content_type)},
    )
    upload_cost = round(time.time() - upload_start, 2)
    if resp.status_code != 200:
        raise RuntimeError(f"上传失败: status={resp.status_code}, response={resp.text[:1000]}")
    server_filename = build_server_filename(user_id, parse_uploaded_filename(safe_json_response(resp, "原始文件上传接口")))
    return server_filename, upload_cost


async def call_file_analysis(client: httpx.AsyncClient, server_filename: str):
    analyze_start = time.time()
    resp = await client.post(FILE_ANALYZE_URL, data={"file": server_filename})
    file_analyze_cost = round(time.time() - analyze_start, 2)
    if resp.status_code != 200:
        raise RuntimeError(f"文件解析失败: status={resp.status_code}, response={resp.text[:1000]}")
    content = normalize_file_analysis_result(safe_json_response(resp, "FileAnalysis"))
    return content, file_analyze_cost


async def call_graph_construction(client: httpx.AsyncClient, content: str):
    file_list_json = json.dumps([{"id": "0", "content": content, "prompt": ""}], ensure_ascii=False)
    graph_start = time.time()
    resp = await client.post(
        GRAPH_URL,
        data={
            "fileList": file_list_json,
            "toolkit": "lszh",
            "kgType": "general",
            "graphStructure": "",
        },
    )
    graph_cost = round(time.time() - graph_start, 2)
    if resp.status_code != 200:
        raise RuntimeError(f"三元组抽取失败: status={resp.status_code}, response={resp.text[:1000]}")
    triples = parse_graph_triples_response(safe_json_response(resp, "GraphConstruction"), "三元组 ")
    return triples, graph_cost


def build_normal_file_result_rows(original_filename: str, triples):
    result_data = [TRIPLE_RESULT_HEADER.copy()]
    invalid_count = 0
    for triple in triples:
        if not isinstance(triple, (list, tuple)) or len(triple) < 3:
            invalid_count += 1
            continue
        result_data.append([original_filename, "文件", triple[0], triple[1], triple[2]])
    return result_data, invalid_count


async def parse_docx_file_core(task_id, user_id, original_filename, file_bytes, client, total_start):
    # save_analysis_and_enterData 接口内部函数：docx 本地分章，并发上传解析后汇总三元组。
    await update_analysis_task(task_id, currentStep="本地保存上传docx", progress=5, message="正在保存上传的 Word 文件")
    root_filename = original_filename
    tmp_obj = tempfile.TemporaryDirectory()

    try:
        tmp_dir = Path(tmp_obj.name)
        local_src_path, local_parts_dir = write_docx_to_temp_parts_dir(original_filename, file_bytes, tmp_dir)

        await update_analysis_task(task_id, currentStep="本地切割docx", progress=10, message="正在按章节切割 Word 文件")
        part_infos = split_docx_by_chapter(local_src_path, local_parts_dir)
        if not part_infos:
            raise ValueError("Word 分割结果为空")

        total_parts = len(part_infos)
        await update_analysis_task(
            task_id,
            currentStep="并发上传并解析章节docx",
            progress=15,
            total=total_parts,
            finished=0,
            failed=0,
            message=f"共识别到 {total_parts} 个章节，开始解析",
        )

        all_results = await analyze_docx_parts_with_progress(
            task_id=task_id,
            user_id=user_id,
            root_filename=root_filename,
            part_infos=part_infos,
            client=client,
        )
        await update_analysis_task(task_id, currentStep="汇总章节解析结果", progress=96, message="正在汇总所有章节的 extractionResult")
        result = summarize_docx_part_results(root_filename, original_filename, all_results, total_start)
        await update_analysis_task(task_id, currentStep="章节结果汇总完成", progress=98, message="章节结果汇总完成")
        return result
    finally:
        tmp_obj.cleanup()


async def parse_normal_file_core(task_id, user_id, original_filename, suffix, file_bytes, file_content_type, client, total_start):
    # save_analysis_and_enterData 接口内部函数：非 docx 文件走上传、FileAnalysis、GraphConstruction。
    await update_analysis_task(task_id, currentStep="上传原始文件", progress=10, message="正在上传原始文件")
    server_filename, upload_cost = await upload_original_file(client, user_id, original_filename, file_bytes, file_content_type)

    await update_analysis_task(task_id, currentStep="文件解析", progress=35, message="正在调用 FileAnalysis 解析文件内容")
    content, file_analyze_cost = await call_file_analysis(client, server_filename)

    await update_analysis_task(task_id, currentStep="三元组抽取", progress=65, message="正在调用 GraphConstruction 抽取三元组")
    triples, graph_cost = await call_graph_construction(client, content)

    result_data, invalid_count = build_normal_file_result_rows(original_filename, triples)

    return {
        "ok": True,
        "extractionResult": result_data,
        "debug": {
            "mode": "parse_only_normal_file_async_task",
            "total_cost_seconds": round(time.time() - total_start, 2),
            "original_filename": original_filename,
            "suffix": suffix,
            "server_filename": server_filename,
            "upload_cost_seconds": upload_cost,
            "file_analyze_cost_seconds": file_analyze_cost,
            "graph_cost_seconds": graph_cost,
            "triples_count": len(triples),
            "invalid_triples_count": invalid_count,
            "result_count": len(result_data),
        },
    }

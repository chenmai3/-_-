import json
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from zhipuai import ZhipuAI

from ..shared import UPLOAD_JSON_ROOT, load_config


SUPPORTED_REMOTE_TYPES = {"PDF", "DOCX", "DOC", "XLS", "XLSX", "PPT", "PPTX", "PNG", "JPG", "JPEG", "CSV"}
MAX_FILE_SIZE = 50 * 1024 * 1024


def save_extracted_json(file_name, content):
    payload = {"名称": file_name, "content": content}
    UPLOAD_JSON_ROOT.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_JSON_ROOT / f"{file_name}.json"
    with save_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload, str(save_path)


def extract_text_locally(file_path, file_type, PyPDF2=None):
    file_type = file_type.upper()

    if file_type == "DOCX":
        with zipfile.ZipFile(file_path) as docx_zip:
            xml = docx_zip.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text for node in root.findall(".//w:t", namespace) if node.text)

    if file_type == "CSV":
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue

    if file_type == "PDF":
        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader
            except Exception:
                return ""
        reader = PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    return ""


def build_zhipu_client():
    cfg = load_config()
    zhipu_config = cfg.get("ZhipuAI", cfg.get("qa_models", {}).get("zhipuai", {}))
    return ZhipuAI(
        api_key=os.getenv("ZHIPUAI_API_KEY", zhipu_config.get("api_key") or zhipu_config.get("api_keys")),
        base_url=os.getenv("ZHIPUAI_BASE_URL", zhipu_config.get("base_url")),
        timeout=float(os.getenv("ZHIPUAI_FILE_TIMEOUT", "30")),
        max_retries=int(os.getenv("ZHIPUAI_FILE_MAX_RETRIES", "1")),
    )


def extract_text_from_file(file_path, file_name, file_type):
    file_type = str(file_type or "").upper()
    if file_type not in SUPPORTED_REMOTE_TYPES:
        return {"名称": file_name, "content": "不支持的文件类型"}, None

    if os.path.getsize(file_path) > MAX_FILE_SIZE:
        return {"名称": file_name, "content": "文件内容过大"}, None

    uploaded_file_id = None
    try:
        client = build_zhipu_client()
        file_object = client.files.create(file=Path(file_path), purpose="file-extract")
        uploaded_file_id = file_object.id
        file_content_json_str = client.files.content(file_id=uploaded_file_id).content.decode()
        file_content_json = json.loads(file_content_json_str)
        return save_extracted_json(file_name, file_content_json.get("content", ""))
    except Exception as exc:
        print(f"文件解析接口失败，尝试本地抽取: {exc}")
        local_content = extract_text_locally(file_path, file_type)
        if local_content.strip():
            return save_extracted_json(file_name, local_content)
        message = f"文件解析失败: {exc}"
        print(message)
        return {"名称": file_name, "content": message}, None
    finally:
        if uploaded_file_id:
            try:
                client.files.delete(file_id=uploaded_file_id)
            except Exception as exc:
                print(f"远程文件清理失败: {exc}")


def extract_text_from_TXT(file_path, file_name):
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return save_extracted_json(file_name, f.read())
        except UnicodeDecodeError:
            continue
    return {"名称": file_name, "content": "TXT 文件编码无法识别"}, None

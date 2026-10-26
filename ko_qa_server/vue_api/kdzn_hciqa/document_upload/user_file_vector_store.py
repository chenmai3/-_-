import json
import os
import traceback

from fastapi import UploadFile
from fastapi.responses import JSONResponse

from ..shared import UPLOAD_FILE_ROOT, USER_VECTOR_STORES_ROOT, get_kochatbot


def ensure_user_vector_store(kochatbot, user_id: str):
    """Create the user's vector store and range metadata when it does not exist."""
    vector_store_path = USER_VECTOR_STORES_ROOT / user_id
    vector_store_path.mkdir(parents=True, exist_ok=True)

    faiss_path = vector_store_path / "index.faiss"
    pkl_path = vector_store_path / "index.pkl"
    if not faiss_path.exists() or not pkl_path.exists():
        kochatbot.create_new_vector_stroes(str(vector_store_path))

    doc_ranges_path = vector_store_path / "doc_rangs.json"
    if not doc_ranges_path.exists():
        with open(doc_ranges_path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)

    return vector_store_path


async def save_uploaded_file(user_id: str, file: UploadFile):
    """Persist an uploaded file under the current user's upload directory."""
    safe_filename = os.path.basename(file.filename or "")
    if not safe_filename:
        raise ValueError("上传文件名不能为空")

    save_dir = UPLOAD_FILE_ROOT / user_id
    save_dir.mkdir(parents=True, exist_ok=True)

    save_path = save_dir / safe_filename
    with open(save_path, "wb") as f:
        f.write(await file.read())
    return save_path, safe_filename


async def handle_upload(scene_choose: str, userId: str, file: UploadFile):
    """接口 upload：保存用户文件并更新该用户的向量库。"""
    try:
        if not userId:
            return JSONResponse({"msg": "userId 不能为空"}, status_code=400)
        if not file:
            return JSONResponse({"msg": "缺少上传文件"}, status_code=400)

        kochatbot = get_kochatbot()
        ensure_user_vector_store(kochatbot, userId)
        save_path, safe_filename = await save_uploaded_file(userId, file)

        filetype = safe_filename.split(".")[-1].upper()
        kochatbot.update_vector_stores(str(save_path), safe_filename, userId, filetype)

        return JSONResponse({"msg": "文件接收成功"}, status_code=200)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"msg": str(exc)}, status_code=500)

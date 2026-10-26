import os
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse


async def handle_download_word(word_name: str):
    """接口 download_word：从标准生成结果目录下载文档，带路径穿越防护。"""
    if not word_name:
        return JSONResponse({"success": False, "message": "缺少参数 word_name"}, status_code=400)

    result_root = Path(__file__).resolve().parent / "generation_engine" / "result"
    safe_word_name = os.path.basename(word_name)
    if not safe_word_name:
        return JSONResponse({"success": False, "message": "无效的文件名"}, status_code=400)

    file_path = (result_root / safe_word_name).resolve()
    result_root_resolved = result_root.resolve()

    if result_root_resolved not in file_path.parents and file_path != result_root_resolved:
        return JSONResponse({"success": False, "message": "非法访问"}, status_code=403)

    if not file_path.is_file():
        return JSONResponse({"success": False, "message": f"文件不存在: {safe_word_name}"}, status_code=404)

    return FileResponse(path=file_path, filename=safe_word_name, media_type="application/octet-stream")

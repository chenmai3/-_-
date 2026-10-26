import os
import logging
import subprocess
import uuid

from fastapi import UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..shared import FFMPEG_EXECUTABLE, TEMP_AUDIO_ROOT, load_config
from .xfyun_asr_client import XfyunSpeedAsrClient


UPLOAD_DIR = TEMP_AUDIO_ROOT
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)

def get_asr_settings():
    config = load_config()
    asr = config.get("speech_recognition", {})
    spark = config.get("qa_models", {}).get("spark", {})
    return {
        "app_id": os.getenv("XF_APP_ID") or asr.get("app_id") or spark.get("appid", ""),
        "api_key": os.getenv("XF_API_KEY") or asr.get("api_key") or spark.get("api_keys", ""),
        "api_secret": os.getenv("XF_API_SECRET") or asr.get("api_secret") or spark.get("api_secret", ""),
        "ffmpeg_path": os.getenv("FFMPEG_PATH") or asr.get("ffmpeg_path") or FFMPEG_EXECUTABLE,
    }


def convert_to_wav(src_path, wav_path):
    """接口 speechToText 的内部函数：调用 ffmpeg 将上传音频转为 16k 单声道 wav。"""
    try:
        cmd = [
            get_asr_settings()["ffmpeg_path"],
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-y",
            "-i",
            str(src_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            str(wav_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError("未找到 FFmpeg，请配置 speech_recognition.ffmpeg_path 或 FFMPEG_PATH。")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b'').decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"音频转码失败：{detail[-500:] or str(exc)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("音频转码超时，请缩短录音后重试。") from exc


def my_asr_api_speed(wav_path: str) -> str:
    """接口 speechToText 的内部函数：调用讯飞极速版 ASR。"""
    settings = get_asr_settings()
    if not all(settings[key] for key in ('app_id', 'api_key', 'api_secret')):
        raise RuntimeError('未配置讯飞语音识别凭据，请检查 speech_recognition 或 XF_* 环境变量。')
    client = XfyunSpeedAsrClient(**{key: settings[key] for key in ('app_id', 'api_key', 'api_secret')})
    return client.transcribe(wav_path)


async def handle_speech_to_text(file: UploadFile):
    """接口 speechToText：接收音频文件，转码后调用 ASR，最后清理临时文件。"""
    raw_path = None
    wav_path = None
    stage = '接收录音'
    request_id = uuid.uuid4().hex[:12]

    if not file:
        return JSONResponse(status_code=400, content={"code": 400, "msg": "缺少文件"})

    try:
        content = await file.read()
        if not content:
            return JSONResponse(status_code=400, content={"code": 400, "msg": "录音文件为空，请重新录音。"})
        ext = os.path.splitext(file.filename or 'record.webm')[1].lower()
        raw_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
        with open(raw_path, "wb") as f:
            f.write(content)

        wav_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.wav"
        stage = '音频转码'
        await run_in_threadpool(convert_to_wav, raw_path, wav_path)
        stage = '讯飞语音识别'
        text = await run_in_threadpool(my_asr_api_speed, str(wav_path))

        return JSONResponse(status_code=200, content={"code": 200, "text": text})
    except Exception as exc:
        logger.exception('[Speech ASR] request=%s stage=%s failed: %s', request_id, stage, exc)
        return JSONResponse(status_code=500, content={
            "code": 500, "msg": str(exc), "stage": stage, "request_id": request_id,
        })
    finally:
        if raw_path and raw_path.exists():
            raw_path.unlink()
        if wav_path and wav_path.exists():
            wav_path.unlink()

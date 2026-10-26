# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from urllib3.filepost import encode_multipart_formdata

logger = logging.getLogger(__name__)


class XfyunSpeedAsrClient:
    """接口 speechToText 的内部依赖：讯飞极速版录音文件转写客户端。"""

    UPLOAD_URL = "https://upload-ost-api.xfyun.cn/file/upload"
    CREATE_URL = "https://ost-api.xfyun.cn/v2/ost/pro_create"
    QUERY_URL = "https://ost-api.xfyun.cn/v2/ost/query"

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

    @staticmethod
    def _response_json(response, action: str):
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise RuntimeError(f"讯飞{action}返回了无效数据，请稍后重试。")
        code = data.get('code')
        if str(code) != '0':
            logger.error('[Speech ASR] provider action=%s http_status=%s code=%s message=%s sid=%s',
                         action, response.status_code, code, data.get('message') or data.get('desc'), data.get('sid'))
        if str(code) == '11200' and 'licc failed' in str(data.get('message', '')).lower():
            raise RuntimeError(
                '讯飞暂时无法创建转写任务（11200：licc failed），请稍后重试。'
                '若持续失败，请检查“录音文件转写极速版”的服务状态及调用限制。'
            )
        if str(code) != '0':
            raise RuntimeError(f"讯飞{action}失败（{code}）：{data.get('message') or data.get('desc') or '服务异常'}")
        response.raise_for_status()
        return data

    @staticmethod
    def _http_date() -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    @staticmethod
    def _sha256_base64(data: bytes) -> str:
        return base64.b64encode(hashlib.sha256(data).digest()).decode("utf-8")

    def _build_headers(self, url: str, method: str, body: bytes, content_type: str) -> dict:
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path
        date = self._http_date()
        digest = "SHA-256=" + self._sha256_base64(body)
        request_line = f"{method} {path} HTTP/1.1"
        signature_origin = f"host: {host}\ndate: {date}\n{request_line}\ndigest: {digest}"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")
        authorization = (
            f'api_key="{self.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line digest", '
            f'signature="{signature}"'
        )
        return {
            "Host": host,
            "Date": date,
            "Digest": digest,
            "Authorization": authorization,
            "Content-Type": content_type,
            "Accept": "application/json",
        }

    @staticmethod
    def _guess_content_type(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".wav":
            return "audio/wav"
        if ext == ".mp3":
            return "audio/mpeg"
        if ext == ".pcm":
            return "application/octet-stream"
        return "application/octet-stream"

    @staticmethod
    def _guess_encoding(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        return "lame" if ext == ".mp3" else "raw"

    def _upload_small_file(self, file_path: str) -> str:
        if os.path.getsize(file_path) >= 30 * 1024 * 1024:
            raise Exception("当前示例只支持小于 30MB 的音频文件")

        request_id = uuid.uuid4().hex
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        fields = [
            ("app_id", self.app_id),
            ("request_id", request_id),
            ("data", (filename, file_bytes, self._guess_content_type(file_path))),
        ]
        body, content_type = encode_multipart_formdata(fields)
        headers = self._build_headers(self.UPLOAD_URL, "POST", body, content_type)

        resp = requests.post(self.UPLOAD_URL, data=body, headers=headers, timeout=60)
        data = self._response_json(resp, '音频上传')
        return data["data"]["url"]

    def _create_task(self, file_url: str, file_path: str) -> str:
        request_id = uuid.uuid4().hex
        body_dict = {
            "common": {"app_id": self.app_id},
            "business": {
                "request_id": request_id,
                "language": "zh_cn",
                "domain": "pro_ost_ed",
                "accent": "mandarin",
                "postproc_on": 1,
                "language_type": 1,
                "enable_subtitle": 0,
            },
            "data": {
                "audio_url": file_url,
                "audio_src": "http",
                "audio_size": os.path.getsize(file_path),
                "format": "audio/L16;rate=16000",
                "encoding": self._guess_encoding(file_path),
            },
        }
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        # The same application can succeed and then return HTTP 500/11200.
        # Retry only an explicit rejected creation, preserving its request_id.
        for attempt in range(3):
            headers = self._build_headers(self.CREATE_URL, "POST", body, "application/json")
            resp = requests.post(self.CREATE_URL, data=body, headers=headers, timeout=60)
            try:
                rejected = resp.status_code >= 500 and str(resp.json().get('code')) == '11200'
            except (ValueError, AttributeError):
                rejected = False
            if rejected and attempt < 2:
                print(f"[Speech ASR] task creation rejected (11200), retry={attempt + 1}/2")
                time.sleep(attempt + 1)
                continue
            data = self._response_json(resp, '创建转写任务')
            return data["data"]["task_id"]

    def _query_task(self, task_id: str) -> dict:
        body_dict = {"common": {"app_id": self.app_id}, "business": {"task_id": task_id}}
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        headers = self._build_headers(self.QUERY_URL, "POST", body, "application/json")

        resp = requests.post(self.QUERY_URL, data=body, headers=headers, timeout=30)
        data = self._response_json(resp, '查询转写任务')
        return data

    @staticmethod
    def _extract_text(result_json: dict) -> str:
        result = result_json.get("data", {}).get("result", {})
        lattice_list = result.get("lattice2") or result.get("lattice") or []
        parts = []

        def walk(obj):
            if isinstance(obj, str):
                try:
                    walk(json.loads(obj))
                except (ValueError, TypeError):
                    pass
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "w" and isinstance(value, str) and value != "":
                        parts.append(value)
                    else:
                        walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        for item in lattice_list:
            walk(item.get("json_1best", {}))
        return "".join(parts).strip()

    def transcribe(self, file_path: str, timeout_seconds: int = 120, poll_interval: int = 2) -> str:
        file_url = self._upload_small_file(file_path)
        task_id = self._create_task(file_url, file_path)
        start = time.time()

        while True:
            result = self._query_task(task_id)
            task_status = str(result.get("data", {}).get("task_status", ""))
            if task_status in ("3", "4"):
                return self._extract_text(result)
            if task_status not in ("1", "2"):
                raise Exception(f"任务状态异常: {result}")
            if time.time() - start > timeout_seconds:
                raise Exception("极速版转写超时，请稍后重试")
            time.sleep(poll_interval)

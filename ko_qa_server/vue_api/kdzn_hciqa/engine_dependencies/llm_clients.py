import datetime
import json
import queue
import ssl
import threading
from datetime import datetime
from time import mktime
from urllib.parse import urlencode
from urllib.parse import urlparse
from wsgiref.handlers import format_date_time
import time
import requests
import websocket
import yaml
from openai import OpenAI
import base64
import hmac
import hashlib
import _thread as thread

from ..shared import CONFIG_PATH
from ..qa_answer.prompt_security import prepare_qa_messages

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


def build_chat_params(provider_config, *, model, messages, stream=False, temperature=None):
    return {
        "model": model,
        "messages": messages,
        "temperature": provider_config.get("temperature", 0.0) if temperature is None else temperature,
        "top_p": provider_config.get("top_p", 0.8),
        "max_tokens": provider_config.get("max_tokens", 4096),
        "stream": stream,
    }


def call_qwen_messages(messages, model_name="qwen2", client=None):
    provider = cfg["small_models"]["qwen"]
    model_key = "qwen2.5_model_name" if model_name == "qwen2.5" else "qwen2_model_name"
    qwen_client = client or OpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"],
    )
    try:
        completion = qwen_client.chat.completions.create(
            **build_chat_params(
                provider,
                model=provider[model_key],
                messages=messages,
                temperature=0.0,
            )
        )
        return completion.choices[0].message.content
    except Exception as exc:
        if getattr(exc, "code", None) == "data_inspection_failed":
            return "我们换个话题聊聊吧。"
        print(f"[llm_clients] Qwen request failed: {exc}")
        return None


class llm_config:
    def __init__(self):

        self._gpt = OpenAI(api_key=cfg["small_models"]["gpt"]["api_key"],
                           base_url=cfg["small_models"]["gpt"]["base_url"])
        self._qwen2 = OpenAI(
            api_key=cfg["small_models"]["qwen"]["api_key"],  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
            base_url=cfg["small_models"]["qwen"]["base_url"],  # 填写DashScope SDK的base_url
        )
        self._kimi = OpenAI(
            api_key=cfg["small_models"]["kimi"]["api_key"],
            base_url=cfg["small_models"]["kimi"]["base_url"],
        )
        self.choose_model = "Mistral-7B-Instruct-v0.3/"
        self.embedd = OpenAI(
            api_key=cfg["embedding_models"]["api_key"],
            base_url=cfg["embedding_models"]["base_url"]
        )
        # 建立映射表
        self.func_map = {
            "qwen2": self.qwen2,
            "gpt_multiQA": self.gpt_multiQA,
            "gpt_predict": self.gpt_predict,
            "kimi": self.kimi,
        }
        self.model_name = cfg.get("model", "qwen2")  # 默认值是 qwen2

    def gpt_predict(self, head, prompt):
        """output:answer:str"""
        messages = [{'role': 'user', 'content': prompt}]
        if head:
            messages.insert(0, {'role': 'system', 'content': head})
        for _ in range(5):
            try:
                completion = self._gpt.chat.completions.create(
                    **build_chat_params(
                        cfg["small_models"]["gpt"],
                        model=cfg["small_models"]["gpt"]["model_name"],
                        messages=messages,
                        temperature=0.0,
                    )
                )
                return completion.choices[0].message.content
            except Exception:
                time.sleep(1)

    def gpt_multiQA(self, history):
        """output:messages:list"""
        history_0 = {"role": "system", "content": "你是一位专业的知识海洋(KO)系统问答助手，你要认真回答用户的问题"}
        messages = []
        if isinstance(history, str):
            messages = list(json.loads(history))
        elif isinstance(history, list):
            messages = list(history)
        if messages[0]["role"] != "system":
            messages.insert(0, history_0)
        completion = self._gpt.chat.completions.create(
            **build_chat_params(
                cfg["small_models"]["gpt"],
                model=cfg["small_models"]["gpt"]["model_name"],
                messages=messages,
                temperature=0.0,
            )
        )
        answer = completion.choices[0].message.content
        last_assistant_ans = {"role": "assistant", "content": answer}
        messages.append(last_assistant_ans)
        if messages and messages[0].get("role"):
            if messages[0]["role"] == "system":
                messages.pop(0)  # 去掉system角色
        return messages

    def qwen(self, mess, model_name="qwen2"):
        return call_qwen_messages(mess, model_name=model_name, client=self._qwen2)

    def get_ans_with_retry(self, message, model="qwen2", try_num=5):
        for _ in range(try_num):
            try:
                res_ans = self.qwen(message, model)
                if res_ans and res_ans != '{}':
                    return res_ans
            except Exception:
                time.sleep(1)
        return None

    def qwen2(self, head, prompt):
        """output:answer:str"""
        messages = [{'role': 'user', 'content': prompt}]
        if head:
            messages.insert(0, {'role': 'system', 'content': head})
        result_ans = self.get_ans_with_retry(messages)
        if not result_ans:
            result_ans = self.get_ans_with_retry(messages, "qwen2.5")
        return result_ans

    def qwen2_message(self, history, model_name=""):
        """output:answer:str"""
        history_0 = {"role": "system",
                     "content": "你叫小KO，你是在知识海洋(Knowledge Ocean, KO)系统中专业的大模型问答助手，你要认真回答用户的问题。"}
        messages = []
        if isinstance(history, str):
            messages = list(json.loads(history))
        elif isinstance(history, list):
            messages = list(history)
        if messages and messages[0].get("role"):
            if messages[0]["role"] != "system":
                messages.insert(0, history_0)
        if model_name in ["qwen-max", "qwen-turbo-latest"]:
            result_ans = self.get_ans_with_retry(messages, model_name)
        else:
            result_ans = self.get_ans_with_retry(messages)
        if not result_ans:
            result_ans = self.get_ans_with_retry(messages, "qwen2.5")
        return result_ans

    async def qwen2_stream(self, messages, model_name=None, try_num=5):
        head = [{"role": "system", "content": "你是一位专业的知识海洋(KO)系统问答助手，你要认真回答用户的问题"}]
        model_name = model_name or cfg["small_models"]["qwen"]["qwen2_model_name"]
        attempt = 0

        while attempt < try_num:
            try:
                completion = self._qwen2.chat.completions.create(
                    **build_chat_params(
                        cfg["small_models"]["qwen"],
                        model=model_name,
                        messages=head + messages,
                        stream=True,
                    )
                )
                for chunk in completion:
                    if chunk.choices:
                        content = chunk.choices[0].delta.content
                        yield content

                break  # 成功完成后退出循环

            except Exception as e:
                attempt += 1
                print(f"请求失败，尝试第 {attempt}/{try_num} 次，错误信息：{e}")
                if attempt == try_num:
                    print("达到最大重试次数，退出。")
                    yield "请求失败，请稍后再试。"

    def kimi(self, head, prompt):
        messages = [{'role': 'user', 'content': prompt}]
        if head:
            messages.insert(0, {'role': 'system', 'content': head})
        try:
            completion = self._kimi.chat.completions.create(
                **build_chat_params(
                    cfg["small_models"]["kimi"],
                    model=cfg["small_models"]["kimi"]["model_name"],
                    messages=messages,
                    temperature=cfg["small_models"]["kimi"].get("temperature", 0.3),
                )
            )
            result = completion.choices[0].message.content
            return result
        except Exception:
            print("KIMI错误")

    def spark(self, appid, api_key, api_secret, gpt_url, domain, query, timeout=30):
        if urlparse(gpt_url).scheme in {"http", "https"}:
            # Spark's HTTP API uses the combined APIPassword as a bearer token;
            # appid and api_secret are only used by the WebSocket API below.
            payload = gen_params(appid, query, domain)
            settings = payload["parameter"]["chat"]
            with OpenAI(api_key=api_key, base_url=gpt_url, timeout=timeout, max_retries=0) as client:
                with client.chat.completions.create(
                    model=domain,
                    messages=payload["payload"]["message"]["text"],
                    temperature=settings["temperature"],
                    max_tokens=settings["max_tokens"],
                    stream=True,
                ) as stream:
                    for chunk in stream:
                        if chunk.choices:
                            choice = chunk.choices[0]
                            if choice.delta.content:
                                yield choice.delta.content
                            if choice.finish_reason == "sensitive":
                                yield "抱歉，这个问题我不能回答"
                                return
            return

        q = queue.Queue()
        completed = threading.Event()

        # 改写回调，把 content 放入队列
        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data["header"]["code"] != 0:
                    q.put(RuntimeError(f"星火返回错误：{data['header']}"))
                    ws.close()
                    return
                choices = data["payload"]["choices"]
                for text in choices["text"]:
                    if text.get("content"):
                        q.put(text["content"])
                if choices["status"] == 2:  # 最后一条
                    completed.set()
                    q.put(None)
                    ws.close()
            except Exception as exc:
                q.put(exc)
                ws.close()

        # 其它回调保持不变
        def on_error(ws, error):
            q.put(Exception(error))
            ws.close()

        def on_close(ws, *args):
            if not completed.is_set():
                q.put(ConnectionError("星火连接在回答完成前关闭，请检查网络或服务状态。"))
            else:
                q.put(None)

        def on_open(ws):
            payload = gen_params(appid, query, domain)
            ws.send(json.dumps(payload))

        # 启动 WebSocket 在另一个线程
        wsParam = Ws_Param(appid, api_key, api_secret, gpt_url)
        wsUrl = wsParam.create_url()
        ws_app = websocket.WebSocketApp(wsUrl,
                                        on_message=on_message,
                                        on_error=on_error,
                                        on_close=on_close,
                                        on_open=on_open)
        def run_websocket():
            try:
                ws_app.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception as exc:
                # Startup errors may bypass websocket-client's on_error callback.
                q.put(exc)
            finally:
                if not completed.is_set():
                    q.put(ConnectionError("星火连接已结束，但未收到完整回答。"))

        t = threading.Thread(target=run_websocket, daemon=True)
        t.start()

        # 从队列里不断拿数据并 yield
        start = time.monotonic()
        try:
            while True:
                try:
                    chunk = q.get(timeout=0.1)
                except queue.Empty:
                    if time.monotonic() - start > timeout:
                        raise TimeoutError("星火流式超时")
                    continue

                if isinstance(chunk, Exception):
                    raise chunk
                if chunk is None:
                    break

                yield chunk
        finally:
            ws_app.close()
            t.join(timeout=1)

    def local_glm(self, prompt):
        url = f"http://114.213.232.140:26389"
        data = {
            "prompt": prompt,
            "history": [],
        }
        try:
            response = requests.post(url, data=json.dumps(data))
            return response.json()["response"]
        except Exception as e:
            print('error: ', e)


# 星火大模型
class Ws_Param(object):
    # 初始化
    def __init__(self, APPID, APIKey, APISecret, gpt_url):
        parsed_url = urlparse(gpt_url)
        if parsed_url.scheme not in {"ws", "wss"} or not parsed_url.netloc:
            raise ValueError(
                "星火 WebSocket 地址必须使用 ws:// 或 wss://；"
                "generalv3.5 请配置 wss://spark-api.xf-yun.com/v3.5/chat，不能使用 HTTP 接口地址。"
            )
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.host = parsed_url.netloc
        self.path = parsed_url.path
        self.gpt_url = gpt_url

    def create_url(self):
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))
        # 如果 format_date_time 返回 bytes，就 decode 一下
        if isinstance(date, bytes):
            date = date.decode('utf-8')

        # 构造签名原文
        signature_origin = (
            f"host: {self.host}\n"
            f"date: {date}\n"
            f"GET {self.path} HTTP/1.1"
        )

        # HMAC-SHA256 签名并 Base64
        signature_sha = hmac.new(
            self.APISecret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha_base64 = base64.b64encode(signature_sha).decode('utf-8')

        # 构造 authorization header 内容并 Base64
        authorization_origin = (
            f'api_key="{self.APIKey}", '
            'algorithm="hmac-sha256", '
            'headers="host date request-line", '
            f'signature="{signature_sha_base64}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode('utf-8')
        ).decode('utf-8')

        # 拼接为 URL 参数
        params = {
            "authorization": authorization,
            "date": date,
            "host": self.host
        }
        return self.gpt_url + "?" + urlencode(params)


# 收到websocket错误的处理
def on_error(ws, error):
    print("### error:", error)


# 收到websocket关闭的处理
def on_close(ws):
    print("### closed ###")


# 收到websocket连接建立的处理
def on_open(ws):
    thread.start_new_thread(run, (ws,))


def run(ws, *args):
    data = json.dumps(gen_params(appid=ws.appid, query=ws.query, domain=ws.domain))
    ws.send(data)


# 收到websocket消息的处理
def on_message(ws, message):
    # print(message)
    data = json.loads(message)
    code = data['header']['code']
    if code != 0:
        print(f'请求错误: {code}, {data}')
        ws.close()
    else:
        choices = data["payload"]["choices"]
        status = choices["status"]
        content = choices["text"][0]["content"]
        print(content, end='')
        if status == 2:
            print("#### 关闭会话")
            ws.close()


def gen_params(appid, query, domain):
    """
    通过appid和用户的提问来生成请参数
    """

    data = {
        "header": {
            "app_id": appid,
            "uid": "1234",
            # "patch_id": []    #接入微调模型，对应服务发布后的resourceid
        },
        "parameter": {
            "chat": {
                "domain": domain,
                "temperature": 0.5,
                "max_tokens": 4096,
                "auditing": "default",
            }
        },
        "payload": {
            "message": {
                "text": prepare_qa_messages([{"role": "user", "content": query}])
            }
        }
    }
    return data

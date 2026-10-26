import requests
import json
from joblib.externals.loky.backend.queues import Queue

url = "http://36.213.76.124:6380/v1/chat/completions"
api_token = ""
headers = {
    'Authorization': f'Bearer',
    'Content-Type': 'application/json'
}


def chat(messages):
    try:
        payload = {
            "model": "Qwen3-80B-vllm",
            "messages": messages,
            "stream": True
        }

        response = requests.post(url, headers=headers, json=payload, stream=True)
        response.raise_for_status()

        print("[正在接收流式响应...]")
        full_content = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data:"):
                    data_str = decoded_line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data_chunk = json.loads(data_str)
                        content = data_chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            print(content, end="", flush=True)
                            full_content += content
                    except json.JSONDecodeError:
                        print(f"\n[JSON 解析错误]: {data_str}")
                    except Exception as e:
                        print(f"\n[发⽣未知错误]: {e}")
        print("\n\n[ 流式响应接收完毕。]")
        return full_content
    except requests.exceptions.RequestException as e:
        print(f"\n[API 请求错误]: {e}")


def chatqo(messages, qo: Queue):
    try:
        payload = {
            "model": "Qwen3-32B-vllm",
            "messages": messages,
            "stream": True
        }

        response = requests.post(url, headers=headers, json=payload, stream=True)
        response.raise_for_status()

        print("[正在接收流式响应...]")
        full_content = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data:"):
                    data_str = decoded_line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data_chunk = json.loads(data_str)
                        content = data_chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            qo.put(content)
                            print(content, end="", flush=True)
                            full_content += content
                    except json.JSONDecodeError:
                        print(f"\n[JSON 解析错误]: {data_str}")
                    except Exception as e:
                        print(f"\n[发⽣未知错误]: {e}")
        print("\n\n[ 流式响应接收完毕。]")
        return full_content
    except requests.exceptions.RequestException as e:
        print(f"\n[API 请求错误]: {e}")
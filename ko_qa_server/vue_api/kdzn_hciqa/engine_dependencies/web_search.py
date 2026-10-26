import os
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import jieba
import pymysql
import requests
from ddgs import DDGS
import urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import json
from http import HTTPStatus
from dashscope import Application
from selenium.webdriver.support.ui import WebDriverWait  # 添加导入
from selenium.webdriver.support import expected_conditions as EC  # 添加导入
from selenium.webdriver.common.by import By
import re
from .graph_rule_queries.vector_matching import get_best_rule_match
from .llm_clients import llm_config
from ..shared import connect_to_db, load_config
llm = llm_config()
cfg = load_config()


def parse_search_results(formatted_str):
    """
    解析 format_search_results 格式化后的字符串，反向生成原始结果列表
    """
    items = []
    # 使用正则按标题分割块，标题是"标题: "开头的行
    # 先按换行分割，逐行处理
    lines = formatted_str.splitlines()
    current_item = {}
    for line in lines:
        line = line.strip()
        if line.startswith("标题: "):
            # 新条目开始，先保存前一个
            if current_item:
                items.append(current_item)
                current_item = {}
            current_item["title"] = line[len("标题: "):]
        elif line.startswith("链接: "):
            current_item["url"] = line[len("链接: "):]
        elif line.startswith("内容: "):
            current_item["description"] = line[len("内容: "):]
        elif line == "":
            # 空行代表条目分割，保存当前条目
            if current_item:
                items.append(current_item)
                current_item = {}
    # 最后一个条目添加
    if current_item:
        items.append(current_item)

    return items


def format_search_results(results, method):
    lines = []
    # 智能体联网搜索
    if method == 'dashscope':
        for idx, result in enumerate(results, start=1):
            title = result.get("title", "无标题")
            url = result.get("url", "无链接")
            description = result.get("description", "无描述")
            lines.append(f"标题: {title}\n链接: {url}\n内容: {description}\n")

    # duckduckgo联网搜索
    elif method == 'DDG':
        for idx, result in enumerate(results, start=1):
            title = result.get("title", "无标题")
            href = result.get("href", "无链接")
            body = result.get("body", "无描述")
            lines.append(f"标题: {title}\n链接: {href}\n内容: {body}\n")

    # 爬虫联网搜索
    elif method == 'pachong':
        for idx, result in enumerate(results, start=1):
            title = result.get("title", "无标题")
            href = result.get("url", "无链接")
            body = result.get("description", "无描述")
            lines.append(f"标题: {title}\n链接: {href}\n内容: {body}\n")

    # 百度百科
    elif method == 'baidubaike':
        for idx, result in enumerate(results, start=1):
            title = result.get("title", "无标题")
            href = result.get("url", "无链接")
            body = result.get("description", "无描述")
            lines.append(f"标题: {title}\n链接: {href}\n内容: {body}\n")
    sorted_lines = sorted(lines, key=lambda s: ("baike" not in s))
    return "\n".join(sorted_lines)


def get_prompt(context, query):
    # 遍历所有搜索结果，将其格式化后添加到 prompt 中
    prompt = f"""
- 目标 -
根据提供的联网搜索内容，准确回答用户的问题。如果搜索到的内容中没有相关信息，请明确告知。

- 角色 -
您扮演的角色是“变压器故障诊断小助手”，专门利用联网搜索中获取到的内容为用户提供专业解答。

- 注意事项 -
1. 确保回答与问题完全对应，避免偏离主题。
2. 匹配到的知识存在与问题无关的内容，请注意筛选。充分利用对问题有用的内容。
3. 如果搜索到的知识中没有相关信息，请明确告知用户“由于缺乏相关信息，当前无法准确回答您的问题”。
4. 信息来源展示给用户，即将网页连接也输出给用户。
5. 可以适当增加你自己的思考内容，作为总结。

- 知识库内容 -
{context.strip()}
    
- 问题 -
"{query}"
"""
    return prompt


# prompt = web_search_pachong("python")
# print(prompt)
def web_search_DDG(query):
    search_results = DDGS().text(query, max_results=5)
    context = format_search_results(search_results, 'DDG')
    # prompt = get_prompt(context, query)
    return context


def web_search_dashscope(query):
    try:
        app_config = cfg.get("dashscope_application", {})
        app_id = os.getenv("DASHSCOPE_APPLICATION_ID") or app_config.get("app_id", "")
        api_key = (
            os.getenv("DASHSCOPE_APPLICATION_API_KEY")
            or app_config.get("api_key")
            or cfg["qa_models"]["qwen"]["api_key"]
        )
        if not app_id or not api_key:
            return None
        response = Application.call(
            api_key=api_key,
            app_id=app_id,
            prompt=query)

        # 检查响应状态码
        if response.status_code != HTTPStatus.OK:
            print(f"[web_search] DashScope application failed: request_id={response.request_id}, "
                  f"status={response.status_code}, app_id={app_id}, message={response.message}")
            return None

        # 尝试解析返回的 JSON 数据
        try:
            # print(response.output.text)
            response_data = response.output.text
            print("ali 搜索：", response_data)
            # context = format_search_results(response_data, 'dashscope')
            # prompt = get_prompt(response_data, query)
            return response_data
        except json.JSONDecodeError as e:
            print(f"Failed to parse response as JSON: {e}")
            return None

    except requests.exceptions.RequestException as e:
        # 捕获请求异常
        print(f"Network error: {e}")
        return None
    except Exception as e:
        # 捕获其他可能的异常
        print(f"An unexpected error occurred: {e}")
        return None


def baidu_baike_scraper(query):
    # 对 query 进行 URL 编码
    query_encoded = urllib.parse.quote(query)
    search_url = f"https://baike.baidu.com/search?enc=utf8&word={query_encoded}"

    # 设置 Selenium 使用无头模式（即不弹出浏览器窗口）
    options = Options()
    options.add_argument("--headless")  # 启用无头模式
    options.add_argument("--disable-extensions")  # 禁用扩展
    options.add_argument("--disable-gpu")  # 禁用 GPU，加速渲染
    options.add_argument("--no-sandbox")  # 沙盒模式
    options.add_argument("--disable-dev-shm-usage")  # 解决 DevToolsActivePort 文件不存在的错误
    options.add_argument("start-maximized")  # 窗口最大化
    options.add_argument("disable-infobars")  # 禁止浏览器提示条
    options.add_argument('--disable-web-security')  # 禁用安全性
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')  # 禁用 CSP
    options.add_argument("--no-proxy-server")
    options.add_argument("--proxy-server='direct://'")
    # 启动 Selenium WebDriver（Chrome）
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"Error launching Chrome WebDriver: {e}")
        return None

    # 访问百度搜索结果页面
    driver.get(search_url)
    driver.get(search_url)
    # 等待页面加载完成，确保结果完全加载
    try:
        # 等待页面中显示以 'container_' 开头的元素加载完成
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.XPATH, "//*[starts-with(@class, 'container_UDOLw')]"))
        )

    except Exception as e:
        print(f"Error waiting for page to load: {e}")
        driver.quit()
        return None

    # 获取页面内容
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # 获取搜索结果项（根据新的 HTML 结构更新类名）
    # result_items = soup.find_all('div', class_='container_EB0wZ')  # 使用正确的类名
    result_items = soup.find_all('div', class_=re.compile('^container_UDOLw'))

    if not result_items:
        print("未找到搜索结果项，可能是页面结构改变了")
        driver.quit()  # 关闭浏览器
        return None

    results = []
    for item in result_items[:3]:  # 获取前五个结果
        # title = item.find('a', class_='title_Qq6En')  # 更新为正确的类名
        title = item.find('a', class_=re.compile('^title_'))
        title_text = title.text if title else "No title"
        url = title['href'] if title else "No URL"

        # 查找两个可能的类名
        # description = item.find('p', class_='abstract_rC2eN')
        description = item.find('p', class_=re.compile('^(abstract_|summary_)'))

        description_text = description.text if description else "No description"

        results.append({
            "title": title_text,
            "url": url,
            "description": description_text
        })
    context = format_search_results(results, 'baidubaike')

    driver.quit()  # 关闭浏览器
    return context


def pachong(query):
    # 对 query 进行 URL 编码
    query_encoded = urllib.parse.quote(query)
    search_url = f"https://www.baidu.com/s?wd={query_encoded}"

    # 设置 Selenium 使用无头模式（即不弹出浏览器窗口）
    options = Options()
    options.add_argument("--headless")  # 启用无头模式
    options.add_argument("--disable-extensions")  # 禁用扩展
    options.add_argument("--disable-gpu")  # 禁用 GPU，加速渲染
    options.add_argument("--no-sandbox")  # 沙盒模式
    options.add_argument("--disable-dev-shm-usage")  # 解决 DevToolsActivePort 文件不存在的错误
    options.add_argument("start-maximized")  # 窗口最大化
    options.add_argument("disable-infobars")  # 禁止浏览器提示条
    options.add_argument('--no-proxy-server')
    options.add_argument('--proxy-server=')

    # 启动 Selenium WebDriver（Chrome）
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"Error launching Chrome WebDriver: {e}")
        return None

    # 访问百度搜索结果页面
    driver.get(search_url)

    # 等待页面加载完成
    time.sleep(1)  # 可以根据网络情况调整等待时间

    # 获取页面内容
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # 获取搜索结果项
    result_items = soup.find_all('div', class_='result c-container xpath-log new-pmd')

    if not result_items:
        print("未找到搜索结果项，可能是页面结构改变了")
        driver.quit()  # 关闭浏览器
        return None

    results = []
    for item in result_items[:3]:  # 获取前五个结果
        title = item.find('h3').text if item.find('h3') else "No title"
        url = item.find('a')['href'] if item.find('a') else "No URL"

        # 查找两个可能的类名
        description = item.find('span', class_='summary-text_560AW') or item.find('span', class_='content-right_2s-H4')
        description_text = description.text if description else "No description"

        results.append({
            "title": title,
            "url": url,
            "description": description_text
        })

    driver.quit()  # 关闭浏览器
    context = format_search_results(results, 'pachong')
    # prompt = get_prompt(context, query)
    # return prompt
    return context


def web_search_pachong(keywords_list):
    keyword_results = []
    for keyword in keywords_list:
        print(f"正在爬取百度搜索关键词: {keyword}")
        results = pachong(keyword)
        keyword_results.append(results)
    return keyword_results


def web_search_baidubaike(keywords_list):
    keyword_results = []
    for keyword in keywords_list:
        print(f"正在爬取百度百科关键词: {keyword}")
        results = baidu_baike_scraper(keyword)
        keyword_results.append(results)
    return keyword_results


def match_top10_wname_by_wordfreq(connection, wenti, ksource, top_k: int = 10):
    """
    根据词频交集，从 tb_zhihaiqa_bdwebsearch 表中匹配与用户问题最相似的前 top_k 个 wname。

    :param connection: PyMySQL Connection 对象
    :param wenti:      用户问题文本
    :param ksource:    只匹配此 ksource 的记录
    :param top_k:      返回最相似的前 top_k 条
    :return:           List[Tuple[wname, score]]，按交集词频由高到低排序
    """
    try:
        # 1. 取出符合 ksource 的所有 wname
        with connection.cursor() as cursor:
            sql = "SELECT DISTINCT wname FROM tb_zhihaiqa_bdwebsearch WHERE ksource = %s"
            cursor.execute(sql, (ksource,))
            rows = cursor.fetchall()
            wnames = [row[0] for row in rows]  # 假设 cursor 默认返回 tuple

        if not wnames:
            return []

        # 2. 分词并统计用户问题词频
        tokens_wenti = list(jieba.cut(wenti))
        freq_wenti = Counter(tokens_wenti)

        # 3. 对每个 wname 分词、统计，并计算词频交集大小
        scored = []
        for w in wnames:
            tokens_w = list(jieba.cut(w))
            freq_w = Counter(tokens_w)
            # 交集 Counter & Counter 会保留每个词在两个 Counter 中的最小出现次数
            overlap = sum((freq_wenti & freq_w).values())
            if overlap > 0:
                scored.append((w, overlap))

        if not scored:
            return []

        # 4. 按得分降序排序，取前 top_k
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    except pymysql.MySQLError as err:
        print(f"数据库操作出错: {err}")
        return []


def get_kdescription_by_wname(connection, wname, ksource):
    try:
        with connection.cursor() as cursor:
            # 查询语句，查找所有符合 name 的记录
            query = """
                    SELECT ktitle, kurl, kdescription
                    FROM tb_zhihaiqa_bdwebsearch
                    WHERE wname = %s AND ksource = %s \
                    """
            cursor.execute(query, (wname, ksource,))
            result = cursor.fetchall()  # 获取所有匹配的结果

            if result:
                all_record = [{
                    "title": row[0],
                    "url": row[1],
                    "description": row[2]
                } for row in result]  # 获取每行的记录
                return all_record
            else:
                print(f"No records found for name '{wname}' in source {ksource}.")
                return []
    except pymysql.MySQLError as err:
        print(f"Error while querying data: {err}")
        return []


def insert_bdwebsearch(connection, data_list, keyword, ksource):
    try:
        with connection.cursor() as cursor:
            # 插入语句，不再涉及id
            insert_query = """
                           INSERT INTO tb_zhihaiqa_bdwebsearch (wname, ksource, ktitle, kurl, kdescription)
                           VALUES (%s, %s, %s, %s, %s) \
                           """
            for data in data_list:
                # 插入数据
                new_data = (keyword, ksource, data["title"], data["url"], data["description"])
                cursor.execute(insert_query, new_data)
            connection.commit()  # 提交所有插入操作
            print("All data inserted successfully.")
    except pymysql.MySQLError as err:
        print(f"Error while inserting data: {err}")
        connection.rollback()  # 如果出错，回滚事务


def __web_search_pachong(keywords_list, threshold=0.7):
    keyword_results = []
    connection = connect_to_db()
    for keyword in keywords_list:
        match = match_top10_wname_by_wordfreq(connection, keyword, "bdsearch")
        if match:
            match = [w for w, _ in match]
            print("关键词匹配列表:", match)
            max_similarity, match_best = get_best_rule_match(keyword, match, llm.embedd)
            # 如果低于阈值，就返回 None
            if max_similarity < threshold:
                return []
            print("向量匹配结果：", match_best)
            raw_data = get_kdescription_by_wname(connection, match_best, "bdsearch")
            results = format_search_results(raw_data, "pachong")
            print(results)
            keyword_results.append(results)
        else:
            print(f"正在爬取百度搜索关键词: {keyword}")
            results = pachong(keyword)
            if results:
                raw_data = parse_search_results(results)
                insert_bdwebsearch(connection, raw_data, keyword, "bdsearch")
                keyword_results.append(results)
    connection.close()
    return keyword_results



def web_search_pachong_with_memo(kl):
    with ThreadPoolExecutor() as executor:
        future_pachong = executor.submit(__web_search_pachong, kl)
        future_dashscope = executor.submit(web_search_dashscope, kl[-1])

        res_pc = list()

        result_pachong = future_pachong.result()
        if isinstance(result_pachong, list):  # 确保类型正确
            res_pc = [item for item in result_pachong if item]
        result_dashscope = future_dashscope.result()
        if not res_pc and result_dashscope:
            res_pc.append(result_dashscope)
        #
        # for future in as_completed([future_pachong, future_dashscope]):
        #     try:
        #         result = future.result()
        #         # 判断是哪个任务的结果
        #         if isinstance(result, list):  # 假设 __web_search_pachong 返回 list 类型
        #             res_pc = result
        #         else:  # 假设 web_search_dashscope 返回非 list 类型（如字符串或 dict）
        #             ali_app_search = result
        #     except Exception as e:
        #         print(f"任务执行出错: {e}")
        #
        # if ali_app_search:
        #     res_pc.append(ali_app_search)

        return res_pc


# def web_search_baidubaike_with_memo(keywords_list):
#     keyword_results = []
#     connection = connect_to_db()
#     for keyword in keywords_list:
#         if check_wname_exists(connection, keyword, "bdbaike"):
#             print(f"关键词 {keyword} 命中缓存")
#             raw_data = get_kdescription_by_wname(connection, keyword, "bdbaike")
#             results = format_search_results(raw_data, "baidubaike")
#             keyword_results.append(results)
#         else:
#             print(f"正在爬取百度百科关键词: {keyword}")
#             results = baidu_baike_scraper(keyword)
#             if results:
#                 raw_data = parse_search_results(results)
#                 insert_bdwebsearch(connection, raw_data, keyword, "bdbaike")
#                 keyword_results.append(results)
#     connection.close()
#     return keyword_results

# from baidusearch.baidusearch import search
# if __name__ == '__main__':
#     print(web_search_pachong_with_memo(["合肥有几条地铁？"]))
# 调用函数获取数据
# query = ['变压器']
# results = search('合肥地铁8号线有几个站点')  # returns 10 or less results
# query = ['吴信东和吴共庆有什么区别？']
# prompt = web_search_pachong(query)
# print(prompt)
# context = web_search_baidubaike(query)
# context = baidu_baike_scraper("合肥地铁8号线有几个站点")
# print(results)

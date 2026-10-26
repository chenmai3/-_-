import json
from typing import Any, Tuple, List

# ko4csg_hci 内部引擎文件：
# 本文件从 kdzn_qa.py 迁移而来，承接 csg_port_stream / kdzn_select 主链路。

from .embedding_service import QwenEmbeddings
from .knowledge_base_chatbot import Chatzxl
import yaml
from .llm_clients import llm_config
from .graph_rule_queries.neo4j_def import KO_tupu
from .graph_rule_queries.family_graph_queries import find_kograph, find_kograph_zibei
from .graph_rule_queries.graph_query_utils import han2pinyin_concat
from .graph_rule_queries.general_graph_queries import find_general
from .graph_rule_queries.rail_graph_queries import (
    all_paths_from_entity,
    find_kdzn,
    get_yichang,
)
from .graph_rule_queries.vector_matching import find_most_similar
import pymysql
from .web_search import web_search_pachong_with_memo
from .graph_rule_queries.path2json import transform_paths_to_hierarchy, transform_paths_to_hierarchy_jiapu
from .prompt_builders import (
    build_prompt_chat,
    build_prompt_qa,
    ensure_system_prompt,
    get_domain_desc,
    prompt_list,
)
from dataclasses import dataclass, field
from ..shared import CONFIG_PATH, EMBEDDING_MODEL_ROOT

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

Triplet = Tuple[str, str, str]


@dataclass
class SearchResult:
    is_over: bool
    result_names: List[str]
    paths: List[str]
    path2triplet: List[list]
    path_triplets: List[tuple]
    matched_entities: List[Tuple[float, str]]  # 新增：[(score, match_ent_span), ...]


EMPTY_RES = SearchResult(False, [], [], [], [], [])


@dataclass
class ScenePromptContext:
    event_extract_prompt: str
    yitu_prompt: str
    file_name_list: List[str]


@dataclass
class IntentResult:
    yitu: str = "Chitchat"
    file_ontology_list: List[str] = field(default_factory=list)
    is_duolun: bool = False


@dataclass
class EventExtractResult:
    event: str = ""
    relation: str = ""
    query_way: str = ""
    anchor1_generation: str = ""
    anchor2_generation: str = ""
    anchor1_des: str = ""
    anchor2_des: str = ""


@dataclass
class RetrievalState:
    result_entities: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    path2triplets: List[list] = field(default_factory=list)
    path_triplets: List[tuple] = field(default_factory=list)
    path_texts: List[str] = field(default_factory=list)
    people_list_1: List[str] = field(default_factory=list)
    people_list_2: List[str] = field(default_factory=list)
    zibei_table: str = ""
    entity_infos: str = ""
    general_ranked_by_fo: dict = field(default_factory=dict)
    general_over_by_fo: dict = field(default_factory=dict)

    def add_tuple_result(self, result_entities, paths, path2triplets, path_triplets):
        paths = paths or []
        if not paths:
            return
        result_entities = result_entities or []
        path2triplets = path2triplets or []
        path_triplets = path_triplets or []
        self._add_path_text(path_triplets)
        self.result_entities.extend(result_entities)
        self.paths.extend(paths)
        self.path2triplets.extend(path2triplets)
        self.path_triplets.extend(path_triplets)

    def add_search_results(self, file_ontology, results):
        normalized = normalize_search_results(results)
        self.general_ranked_by_fo[file_ontology] = normalized
        self.general_over_by_fo[file_ontology] = [item.is_over for item in normalized]

        for result in normalized:
            if not result.paths:
                continue
            for one_path_triplets in result.path2triplet or []:
                self._add_path_text(one_path_triplets)
            self.result_entities.extend(x for x in result.result_names if x not in self.result_entities)
            self.paths.extend(result.paths)
            self.path2triplets.extend(result.path2triplet)
            self.path_triplets.extend(result.path_triplets)

    def _add_path_text(self, triplets):
        text = "；".join([f"{h}的{r}有{t}" for h, r, t in (triplets or [])])
        if text and text not in self.path_texts:
            self.path_texts.append(text)


def safe_json_loads(raw: Any, default=None, log_label: str = "json"):
    if default is None:
        default = {}
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception as exc:
        print(f"[ko4csg_hci] {log_label} parse failed: {exc}; raw={str(raw)[:300]}")
        return default


def normalize_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_search_results(results, expected_count=3):
    normalized = []
    for item in results or []:
        if isinstance(item, SearchResult):
            normalized.append(item)
        elif all(hasattr(item, attr) for attr in ("is_over", "result_names", "paths", "path2triplet", "path_triplets")):
            normalized.append(
                SearchResult(
                    bool(getattr(item, "is_over", False)),
                    getattr(item, "result_names", []) or [],
                    getattr(item, "paths", []) or [],
                    getattr(item, "path2triplet", []) or [],
                    getattr(item, "path_triplets", []) or [],
                    getattr(item, "matched_entities", []) or [],
                )
            )
        elif isinstance(item, tuple) and len(item) >= 4:
            names, paths, path2triplet, path_triplets = item[:4]
            normalized.append(SearchResult(False, names or [], paths or [], path2triplet or [], path_triplets or [], []))

    while len(normalized) < expected_count:
        normalized.append(EMPTY_RES)
    return normalized[:expected_count]


class kdzn_qa(llm_config):

    def __init__(self):
        super().__init__()
        self.prompt_list = prompt_list
        self.history2 = []
        self.yitu_file_res = {}
        self._embedding_client = None

    def get_embedding_client(self):
        if self._embedding_client is None:
            self._embedding_client = QwenEmbeddings()
        return self._embedding_client

    def emit_status(self, q, message: str):
        q.put(f"data: <PrOSpLiT>{message}</PrOSpLiT>\n\n")

    def call_llm_json(self, prompt: str, default=None, log_label: str = "llm_json"):
        response = self.func_map[self.model_name](None, prompt)
        return safe_json_loads(response, default=default or {}, log_label=log_label)

    def build_scene_prompt_context(self, scene_choose, userid, history_qa, question) -> ScenePromptContext:
        if scene_choose == "轨交诊断":
            base_prompt = self.prompt_list["kdzn_base_prompt"]
            add_prompt = self.prompt_list["kdzn_add_prompt"]
            file_info, file_name_list = self.get_file_info(scene_choose, userid)
            return ScenePromptContext(
                event_extract_prompt=self.prompt_list["kdzn_input_extract"],
                yitu_prompt=base_prompt + "\n" + file_info + add_prompt.replace("__input__", question),
                file_name_list=file_name_list,
            )

        if scene_choose == "家谱问答":
            return ScenePromptContext(
                event_extract_prompt=self.prompt_list["jiapu_event_extract_prompt"],
                yitu_prompt=self.prompt_list["jiapu_general_yitu_file"].replace("__input__", question),
                file_name_list=[],
            )

        domain_desc = get_domain_desc(scene_choose)
        base_prompt = self.prompt_list["general_base_prompt"].replace("__scene__", scene_choose).replace(
            "__domain_desc__", domain_desc
        )
        add_prompt = self.prompt_list["general_add_prompt"].replace("__scene__", scene_choose)
        file_info, file_name_list = self.get_file_info(scene_choose, userid)
        history_text = str(history_qa) if history_qa else "暂无上一轮问答"
        history_prompt = (
            add_prompt.replace("__history__", history_text)
            .replace("__input__", question)
            .replace("__file_name_list__", str(file_name_list))
        )
        return ScenePromptContext(
            event_extract_prompt=self.prompt_list["general_input_extract"],
            yitu_prompt=base_prompt + "\n" + file_info + history_prompt,
            file_name_list=file_name_list,
        )

    def match_telemetry_intent(self, question):
        telemetry_rules = [
            ("yxyc_entity_list_huanjing", "设备房环境"),
            ("yxyc_entity_list_dianzu", "设备房电阻"),
            ("yxyc_entity_list_dianliu", "设备房电流"),
            ("yxyc_entity_list_dianya", "设备房电压"),
            ("yxyc_entity_list_wendu", "设备房温度"),
            ("yxyc_entity_list_gonglvdiandu", "设备房功率电度"),
        ]
        for config_key, scene_name in telemetry_rules:
            for entity in cfg.get(config_key, []):
                if entity and entity in question:
                    print(f"[ko4csg_hci] telemetry intent matched: {config_key} -> {scene_name}")
                    return {
                        "意图": "遥测设备诊断",
                        "相关场景": [scene_name],
                    }
        return None

    def normalize_intent_result(self, raw_intent) -> IntentResult:
        intent_data = safe_json_loads(raw_intent, default={}, log_label="intent")
        if not isinstance(intent_data, dict):
            intent_data = {}
        yitu = intent_data.get("意图") or intent_data.get("鎰忓浘") or "Chitchat"
        file_ontology_list = (
            intent_data.get("相关场景")
            or intent_data.get("鐩稿叧鍦烘櫙")
            or []
        )
        is_duolun = str(intent_data.get("多轮问答") or intent_data.get("澶氳疆闂瓟") or "False") == "True"
        return IntentResult(
            yitu=yitu,
            file_ontology_list=normalize_list(file_ontology_list),
            is_duolun=is_duolun,
        )

    def recognize_intent(self, question, yitu_prompt) -> IntentResult:
        telemetry_intent = self.match_telemetry_intent(question)
        if telemetry_intent is not None:
            self.yitu_file_res = telemetry_intent
            return self.normalize_intent_result(telemetry_intent)

        print("\033[94m 意图/场景识别 \033[0m")
        llm_intent = self.call_llm_json(yitu_prompt, default={"意图": "Chitchat", "相关场景": []}, log_label="intent")
        if str(llm_intent.get("多轮问答") or llm_intent.get("澶氳疆闂瓟")) == "True" and isinstance(self.yitu_file_res, dict):
            self.yitu_file_res["多轮问答"] = "True"
        else:
            self.yitu_file_res = llm_intent
        return self.normalize_intent_result(self.yitu_file_res)

    def rewrite_query_if_needed(self, yitu, question, qa_pair_history):
        if yitu == "Chitchat" or qa_pair_history is None:
            return question
        print("执行查询改写")
        query_rewriting_prompt = self.prompt_list["Query_Rewriting"].replace("__wenti__", question).replace(
            "__qa_pair_history__", str(qa_pair_history)
        )
        rewrite_result = self.call_llm_json(query_rewriting_prompt, default={}, log_label="query_rewrite")
        return rewrite_result.get("Rewriting_query", question)

    def extract_event_info(self, scene_choose, event_extract_prompt, rewritten_query) -> tuple[str, EventExtractResult]:
        prompt = event_extract_prompt.replace("__input__", rewritten_query)
        print("\033[94m 事件抽取 \033[0m")
        raw_result = self.func_map[self.model_name](None, prompt)
        event_data = safe_json_loads(raw_result, default={}, log_label="event_extract")
        info = EventExtractResult()
        try:
            if scene_choose == "家谱问答":
                values = list(event_data.values())
                while len(values) < 7:
                    values.append("")
                (
                    p1,
                    p2,
                    info.anchor1_generation,
                    info.anchor2_generation,
                    info.anchor1_des,
                    info.anchor2_des,
                    info.query_way,
                ) = values[:7]
                if info.query_way == "关系":
                    info.event, info.relation = p1, p2
                else:
                    info.event, info.relation = p1, info.query_way
            else:
                values = list(event_data.values())
                if len(values) >= 2:
                    info.event, info.relation = values[:2]
        except Exception as exc:
            print(f"[ko4csg_hci] event normalize failed: {exc}")
        return raw_result, info

    def load_optional_contexts(self, q, rewritten_query, web, bigbase):
        web_context = []
        ko_context = []

        if web:
            self.emit_status(q, "正在进行联网搜索")
            try:
                web_context = web_search_pachong_with_memo([rewritten_query]) or []
                self.emit_status(q, "搜索完成")
            except Exception as exc:
                print(f"[ko4csg_hci] web search failed: {exc}")
                self.emit_status(q, "联网搜索失败，继续使用已有知识回答")

        if bigbase:
            self.emit_status(q, "正在更大图谱中检索")
            try:
                keyword_extract_prompt = self.prompt_list["keyword_extract_prompt"] + f"\n{rewritten_query}"
                keywords = self.qwen2(None, keyword_extract_prompt) or ""
                keywords_list = [keyword.strip() for keyword in keywords.split(",") if keyword.strip()]
                ko_context = KO_tupu(keywords_list) if keywords_list else []
                self.emit_status(q, "检索完成")
            except Exception as exc:
                print(f"[ko4csg_hci] KO graph search failed: {exc}")
                self.emit_status(q, "大图谱检索失败，继续使用当前主题知识回答")

        return web_context, ko_context

    def is_chitchat_turn(self, scene_choose, intent: IntentResult, event_extract_llm_res):
        if scene_choose == "轨交诊断":
            return intent.yitu == "Chitchat" or not intent.file_ontology_list or not event_extract_llm_res
        return intent.yitu == "Chitchat"

    def build_chitchat_messages(self, scene_key, rewritten_query, web_context, ko_context, bigbase, web, history_qa,
                                query_history):
        sys_prompt, user_prompt = build_prompt_chat(
            scene=scene_key,
            question=rewritten_query,
            web_context=web_context,
            ko_context=ko_context,
            bigbase=bigbase,
            web=web,
            history_qa=history_qa,
        )
        if query_history and query_history[0].get("role") == "system":
            query_history[0]["content"] = sys_prompt
        else:
            query_history.insert(0, {"role": "system", "content": sys_prompt})
        query_history.append({"role": "user", "content": user_prompt})
        return query_history

    def csg_port_stream_refactored(self, qa_pair_history, koqatheme_label_with_ID, userid, history_qa, q, query,
                                   scene_choose, web, bigbase, query_history: list, need_judge_diff: True,
                                   session_id=None):
        people_list_1 = []
        people_list_2 = []
        general_ranked_by_fo = {}
        general_over_by_fo = {}
        difficulty = "think"

        scene_context = self.build_scene_prompt_context(scene_choose, userid, history_qa, query)
        self.emit_status(q, f"用户问的是“{query}”，开始在{scene_choose}主题下分析用户意图")

        if need_judge_diff:
            try:
                judge_difficulty_prompt = self.prompt_list["judge_difficulty"].replace("__input__", query)
                q_difficulty = self.call_llm_json(judge_difficulty_prompt, default={}, log_label="difficulty")
                difficulty = q_difficulty.get("难度") or q_difficulty.get("闅惧害") or difficulty
            except Exception as exc:
                print(f"[ko4csg_hci] difficulty judge failed: {exc}")

        intent = self.recognize_intent(query, scene_context.yitu_prompt)
        rewritten_query = self.rewrite_query_if_needed(intent.yitu, query, qa_pair_history)
        event_extract_llm_res, event_info = self.extract_event_info(
            scene_choose,
            scene_context.event_extract_prompt,
            rewritten_query,
        )

        print("csg_sys_port: intent=", self.yitu_file_res)
        print("csg_sys_port: event_extract=", event_extract_llm_res)

        web_context, ko_context = self.load_optional_contexts(q, rewritten_query, web, bigbase)
        streaming_flag = False
        scene_key = scene_choose

        if self.is_chitchat_turn(scene_choose, intent, event_extract_llm_res):
            if web and bigbase:
                text = "当前主题下闲聊，正在整理联网搜索和更大图谱检索出来的信息"
            elif web:
                text = "当前主题下闲聊，正在整理联网搜索检索出来的信息"
            elif bigbase:
                text = "当前主题下闲聊，正在整理更大图谱检索出来的信息"
            else:
                text = "当前主题下闲聊，进行大模型通识回答"

            self.emit_status(q, text)
            query_history = self.build_chitchat_messages(
                scene_key,
                rewritten_query,
                web_context,
                ko_context,
                bigbase,
                web,
                history_qa,
                query_history,
            )
            return (
                intent.file_ontology_list,
                query_history,
                "",
                [],
                [],
                difficulty,
                streaming_flag,
                q,
                people_list_1,
                people_list_2,
                general_ranked_by_fo,
                general_over_by_fo,
            )

        if event_info.query_way == "关系":
            self.emit_status(q, "正在检索字辈相关知识")
        else:
            self.emit_status(q, f"用户问题涉及{event_info.event}的{event_info.relation}，正在检索相关知识")

        query_history = ensure_system_prompt(query_history, scene_key)
        self.emit_status(q, "正在进行关键词抽取")
        (
            query_history,
            get_paths,
            path_tris,
            aa,
            streaming_flag,
            people_list_1,
            people_list_2,
            general_ranked_by_fo,
            general_over_by_fo,
        ) = self.kdzn_select(
            intent.is_duolun,
            rewritten_query,
            scene_context.file_name_list,
            userid,
            q,
            history_qa,
            scene_choose,
            bigbase,
            event_info.event,
            event_info.relation,
            event_info.query_way,
            event_info.anchor1_generation,
            event_info.anchor2_generation,
            event_info.anchor1_des,
            event_info.anchor2_des,
            query,
            intent.file_ontology_list,
            query_history,
            web_context,
            ko_context,
            session_id=session_id,
        )

        return (
            intent.file_ontology_list,
            query_history,
            get_paths,
            path_tris,
            aa,
            difficulty,
            streaming_flag,
            q,
            people_list_1,
            people_list_2,
            general_ranked_by_fo,
            general_over_by_fo,
        )

    def safe_find_kdzn(self, userid, scene_choose, file_ontology, head, rel):
        try:
            result = find_kdzn(userid, scene_choose, file_ontology, head, rel, self.get_embedding_client(), self.embedd)
            if not result or len(result) < 4:
                return [], [], [], []
            return tuple(item or [] for item in result[:4])
        except Exception as exc:
            print(f"[ko4csg_hci] find_kdzn failed: fo={file_ontology}, error={exc}")
            return [], [], [], []

    def safe_find_kograph_zibei(self, head, rel, anchor1_generation, anchor2_generation, anchor1_des, anchor2_des,
                                session_id=None):
        try:
            result = find_kograph_zibei(
                head,
                rel,
                anchor1_generation,
                anchor2_generation,
                anchor1_des,
                anchor2_des,
                self.embedd,
                session_id=session_id,
            )
            if not result or len(result) < 7:
                return [], [], [], [], "", [], []
            return result
        except Exception as exc:
            print(f"[ko4csg_hci] find_kograph_zibei failed: {exc}")
            return [], [], [], [], "", [], []

    def safe_find_kograph(self, head, rel):
        try:
            result = find_kograph(head, rel, self.embedd)
            if not result or len(result) < 5:
                return [], [], [], [], ""
            return result
        except Exception as exc:
            print(f"[ko4csg_hci] find_kograph failed: {exc}")
            return [], [], [], [], ""

    def safe_find_general(
        self,
        userid,
        q,
        rewritten_query,
        file_ontology,
        scene_choose,
        head,
        rel,
        is_duolun,
        session_id=None,
    ):
        try:
            return find_general(
                userid,
                q,
                rewritten_query,
                file_ontology,
                scene_choose,
                head,
                rel,
                is_duolun,
                self.get_embedding_client(),
                self.embedd,
                3,
                5,
                session_id=session_id,
            )
        except Exception as exc:
            print(f"[ko4csg_hci] find_general failed: fo={file_ontology}, error={exc}")
            return normalize_search_results([])

    def safe_get_yichang(self, head, rel):
        try:
            result = get_yichang(head, rel, model_name=str(EMBEDDING_MODEL_ROOT / "text2vec_large_chinese"))
            if not result or len(result) < 4:
                return [], [], [], []
            return tuple(item or [] for item in result[:4])
        except Exception as exc:
            print(f"[ko4csg_hci] get_yichang failed: {exc}")
            return [], [], [], []

    def run_kdzn_retrieval(self, state: RetrievalState, userid, scene_choose, file_list, file_match_list, head, rel,
                           method):
        print(file_list)
        for file_ontology in file_match_list or []:
            if file_ontology is None and method == "global_event":
                state.add_tuple_result(*self.safe_get_yichang(head, rel))
            elif file_ontology in file_list:
                state.add_tuple_result(*self.safe_find_kdzn(userid, scene_choose, file_ontology, head, rel))
            elif file_ontology is None:
                print("文件没有匹配到！")

    def run_jiapu_retrieval(self, state: RetrievalState, head, rel, query_way, anchor1_generation, anchor2_generation,
                             anchor1_des, anchor2_des, session_id=None):
        print("query_way", query_way)
        if query_way == "关系":
            print("字辈关系回答")
            (
                result_entities,
                paths,
                path2triplets,
                path_triplets,
                state.zibei_table,
                state.people_list_1,
                state.people_list_2,
            ) = self.safe_find_kograph_zibei(
                head,
                rel,
                anchor1_generation,
                anchor2_generation,
                anchor1_des,
                anchor2_des,
                session_id,
            )
        else:
            print("亲属关系回答")
            result_entities, paths, path2triplets, path_triplets, state.entity_infos = self.safe_find_kograph(head, rel)
        state.add_tuple_result(result_entities, paths, path2triplets, path_triplets)

    def run_general_retrieval(
        self,
        state: RetrievalState,
        userid,
        q,
        rewritten_query,
        file_list,
        file_match_list,
        scene_choose,
        head,
        rel,
        is_duolun,
        session_id=None,
    ):
        for file_ontology in file_match_list or []:
            if file_ontology in file_list:
                results = self.safe_find_general(
                    userid,
                    q,
                    rewritten_query,
                    file_ontology,
                    scene_choose,
                    head,
                    rel,
                    is_duolun,
                    session_id,
                )
                state.add_search_results(file_ontology, results)
            elif file_ontology is None:
                print("文件没有匹配到！")

    def run_scene_retrieval(self, state: RetrievalState, userid, q, rewritten_query, file_list, scene_choose, head, rel,
                             query_way, anchor1_generation, anchor2_generation, anchor1_des, anchor2_des,
                             file_match_list, is_duolun, method, session_id=None):
        if not head or not rel:
            return
        if scene_choose == "轨交诊断":
            self.run_kdzn_retrieval(state, userid, scene_choose, file_list, file_match_list, head, rel, method)
        elif scene_choose == "家谱问答":
            self.run_jiapu_retrieval(
                state,
                head,
                rel,
                query_way,
                anchor1_generation,
                anchor2_generation,
                anchor1_des,
                anchor2_des,
                session_id,
            )
        else:
            self.run_general_retrieval(
                state,
                userid,
                q,
                rewritten_query,
                file_list,
                file_match_list,
                scene_choose,
                head,
                rel,
                is_duolun,
                session_id,
            )

    def build_path_hierarchy(self, scene_choose, path2triplets):
        if not path2triplets:
            return ""
        if scene_choose == "家谱问答":
            return transform_paths_to_hierarchy_jiapu(path2triplets)
        return transform_paths_to_hierarchy(path2triplets)

    def append_topic_rag_context(self, q, knowledge_res, userid, scene_choose, rewritten_query):
        try:
            self.emit_status(q, "正在检索主题原始文档知识库")
            topic_label = han2pinyin_concat(scene_choose)
            rag_userid = f"{userid}_file_vectorstoregs/{topic_label}"
            rag_bot = Chatzxl()
            rag_bot.init_database()
            rag_context = rag_bot.koquery2kb_context_vector_only(
                query=rewritten_query,
                userid=rag_userid,
                top_k=5,
                scene_choose=scene_choose,
            )
            if rag_context:
                self.emit_status(q, "主题原始文档知识库检索完成")
                return knowledge_res + "\n\n### 原始文档向量检索结果：\n" + rag_context
            print("[RAG向量检索] 未检索到主题原始文档内容")
            self.emit_status(q, "主题原始文档知识库未检索到相关内容")
        except Exception as exc:
            print("[RAG向量检索异常，不影响图谱问答]", exc)
        return knowledge_res

    def csg_port_stream(self, qa_pair_history, koqatheme_label_with_ID, userid, history_qa, q, query, scene_choose, web,
                        bigbase, query_history: list, need_judge_diff: True, session_id=None):
        return self.csg_port_stream_refactored(
            qa_pair_history,
            koqatheme_label_with_ID,
            userid,
            history_qa,
            q,
            query,
            scene_choose,
            web,
            bigbase,
            query_history,
            need_judge_diff,
            session_id=session_id,
        )

    def kdzn_select(self, is_duolun, Query_Rewriting_res, file_list, userid, q, history_qa, scene_choose, bigbase, head,
                     rel, query_way, anchor1_generation, anchor2_generation, anchor1_des, anchor2_des, wt,
                     file_match_list, qa_mess, web_context, KO_context,
                     method='file_match', session_id=None):
        state = RetrievalState()
        file_list = file_list or []
        file_match_list = file_match_list or []
        web_context = web_context or []
        KO_context = KO_context or []
        print("检索KG...")

        self.run_scene_retrieval(
            state,
            userid,
            q,
            Query_Rewriting_res,
            file_list,
            scene_choose,
            head,
            rel,
            query_way,
            anchor1_generation,
            anchor2_generation,
            anchor1_des,
            anchor2_des,
            file_match_list,
            is_duolun,
            method,
            session_id,
        )

        print("\033[36m文件匹配检索路径：", "\n".join(state.paths), "\033[0m")
        print(state.path2triplets)
        pathss_json = self.build_path_hierarchy(scene_choose, state.path2triplets)

        self.emit_status(q, "正在进行知识检索")
        web_context = "\n\n".join(web_context)
        print("web_context:", web_context)
        print("KO_context:", KO_context)
        print("entity_infos", state.entity_infos)

        topK_paths = []
        topK2triplet = []
        topK_tris = []
        streaming_flag = not state.paths and not topK_paths and bigbase
        knowledge_res = f"### 规则匹配结果：{pathss_json}" if pathss_json else ""

        combined_list = topK_paths + KO_context
        if combined_list:
            knowledge_res += '\n### 全局匹配参考：' + "\n\n".join(
                "\n".join(item) if isinstance(item, list) else item
                for item in combined_list
            )

        if state.entity_infos:
            knowledge_res += state.entity_infos

        knowledge_res = self.append_topic_rag_context(q, knowledge_res, userid, scene_choose, Query_Rewriting_res)

        if scene_choose == '家谱问答':
            zibei_table = str(state.zibei_table) + str(state.result_entities)
            history_qa = history_qa + state.people_list_1 + state.people_list_2
        else:
            zibei_table = ''
        prompt = build_prompt_qa(
            scene_choose=scene_choose,  # "kdzn" / "kograph" / 其它
            web_context=web_context,
            ko_ctx=KO_context,
            knowledge_res=knowledge_res,
            question=Query_Rewriting_res,
            history_qa=history_qa,
            zibei_table=zibei_table,
            entity_infos=state.entity_infos
        )

        state.paths += topK_paths
        state.path2triplets += topK2triplet
        state.path_triplets += topK_tris
        res_paths = json.dumps(state.paths, ensure_ascii=False)
        qa_mess.append({"role": "user", "content": prompt})
        print(prompt)
        return (
            qa_mess,
            res_paths,
            state.path2triplets,
            state.path_triplets,
            streaming_flag,
            state.people_list_1,
            state.people_list_2,
            state.general_ranked_by_fo,
            state.general_over_by_fo,
        )

    def connect_to_db(self):
        try:
            connection = pymysql.connect(
                host=cfg["KO_database"]["host"],  # 数据库主机
                user=cfg["KO_database"]["user"],  # 数据库用户名
                password=cfg["KO_database"]["password"],  # 数据库密码
                database=cfg["KO_database"]["database"],
                charset=cfg["KO_database"]["charset"]
            )
            return connection
        except pymysql.MySQLError as err:
            print(f"Error: {err}")
            return None

    def get_file_info(self, scene_choose, userID):
        db_connection = self.connect_to_db()
        file_info = ""
        file_name_list = []

        if not db_connection:
            print("数据库连接错误")
            return "", []

        try:
            with db_connection.cursor() as cursor:
                sql = """
                    SELECT DISTINCT scene_name, COALESCE(description, '')
                    FROM ko_theme_permission
                    WHERE theme_name = %s
                      AND (create_id = %s OR scene_permission = 'public')
                      AND scene_name IS NOT NULL AND scene_name <> ''
                    ORDER BY scene_name
                """
                cursor.execute(sql, (scene_choose, userID))
                rows = cursor.fetchall()

                if not rows:
                    print("未查询到符合条件的场景")
                    return "", []

                for i, (scene_name, description) in enumerate(rows, 1):
                    file_name_list.append(scene_name)
                    file_info += f"（{i}）.{scene_name}：{description}\n"

                return file_info, file_name_list

        except pymysql.MySQLError as err:
            print(f"数据库错误: {err}")
            return "", []
        finally:
            db_connection.close()


    def ycyx_stream(self, data_source, status):
        yxyc_data_list = cfg.get(['yxyc_data_list'])
        # 匹配最相似的实体
        best_match, score = find_most_similar(data_source, yxyc_data_list,
                                              self._qwen2, cfg['embedding_model_name'])
        formatted_paths, paths_tris = all_paths_from_entity(best_match)
        print(formatted_paths)
        print(f"匹配到的数据：{best_match}。")
        # print(f"当前数值：{data}，阈值上限：{threshold_up}，阈值下限：{threshold_down}")
        print(f"分析结果：{status}")
        filtered_formatted_paths = [p for p in formatted_paths if status in p]
        print("匹配到的路径：", filtered_formatted_paths)
        entities = []
        for p in filtered_formatted_paths:
            # 方法一：用 split
            entity = p.split('可能原因->')[-1]
            entities.append(entity)
        print("可能的原因：", entities[-1])
        return filtered_formatted_paths

#
# llm_config = llm_config()
# prompt = "你好"
# messs = [{"role": "user", "content": prompt}]
# answer = llm_config.qwen2_message(messs)
# print(answer)

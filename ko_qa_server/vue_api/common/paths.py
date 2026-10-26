import os
from pathlib import Path


def _path_from_env(env_name: str, default: Path) -> Path:
    value = os.getenv(env_name)
    if value:
        return Path(value).expanduser().resolve()
    return default


VUE_API_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = _path_from_env("KO_QA_SERVER_ROOT", VUE_API_ROOT.parent)
LOCAL_CONFIG_PATH = SERVER_ROOT / "config.local.yaml"
DEFAULT_CONFIG_PATH = LOCAL_CONFIG_PATH if LOCAL_CONFIG_PATH.is_file() else SERVER_ROOT / "config.yaml"
CONFIG_PATH = _path_from_env("KO_QA_CONFIG_PATH", DEFAULT_CONFIG_PATH)

USER_VECTOR_STORES_ROOT = _path_from_env(
    "KO_QA_USER_VECTOR_STORES_ROOT",
    SERVER_ROOT / "user_vector_stores",
)
ENTITY_VECTOR_ROOT = _path_from_env(
    "KO_QA_ENTITY_VECTOR_ROOT",
    SERVER_ROOT / "entity_vector",
)
JIAPU_ENTITY_VECTOR_STORE = _path_from_env(
    "KO_QA_JIAPU_ENTITY_VECTOR_STORE",
    ENTITY_VECTOR_ROOT / "jiapu_entity_vector_store",
)
RULE_ENTITY_VECTOR_KDZN_ROOT = _path_from_env(
    "KO_QA_RULE_ENTITY_VECTOR_KDZN_ROOT",
    Path(r"E:\新建文件夹\vector\rule_entity_vector_store_kdzn"),
)

UPLOAD_FILE_ROOT = _path_from_env("KO_QA_UPLOAD_FILE_ROOT", SERVER_ROOT / "upload_file_user")
UPLOAD_JSON_ROOT = _path_from_env("KO_QA_UPLOAD_JSON_ROOT", SERVER_ROOT / "upload_files_json_all")
TEMP_AUDIO_ROOT = _path_from_env("KO_QA_TEMP_AUDIO_ROOT", SERVER_ROOT / "temp_audio")
EMBEDDING_MODEL_ROOT = _path_from_env("KO_QA_EMBEDDING_MODEL_ROOT", SERVER_ROOT / "model" / "embeddings")
LOCAL_ANALYSIS_FILE_ROOT = _path_from_env(
    "KO_QA_LOCAL_ANALYSIS_FILE_ROOT",
    SERVER_ROOT / "graph_construct_files",
)


def entity_vector_store_path(label: str, scene_label: str) -> Path:
    return ENTITY_VECTOR_ROOT / f"{label}_entity_vector_store" / f"{scene_label}_entity_vector_store"


def rule_entity_vector_store_path(rid) -> Path:
    return RULE_ENTITY_VECTOR_KDZN_ROOT / f"{rid}_entity_vector_store"

from functools import lru_cache

import yaml
from neo4j import GraphDatabase, Query

from .paths import CONFIG_PATH


@lru_cache(maxsize=1)
def load_neo4j_config():
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)["neo4j"]


def graph_config_key(graph_kind: str = "") -> str:
    if graph_kind == "kdzn":
        return "kdzn"
    if graph_kind == "jiapu":
        return "default"
    return "new_kdzn"


def create_neo4j_driver(graph_kind: str = ""):
    graph = load_neo4j_config()[graph_config_key(graph_kind)]
    return GraphDatabase.driver(
        graph["uri"],
        auth=(graph["username"], graph["password"]),
    )


def query_new_neo4j(query, parameters=None, timeout=30, kg=""):
    driver = create_neo4j_driver(kg)
    try:
        with driver.session() as session:
            result = session.run(
                Query(query, timeout=float(timeout)),
                parameters or {},
            )
            return list(result)
    finally:
        driver.close()


def query_neo4j(query, timeout=30, kg="", parameters=None):
    """Run a legacy APOC time-boxed query with parameterized Cypher text."""
    driver = create_neo4j_driver("kdzn" if kg == "kdzn" else "jiapu")
    apoc_query = (
        "CALL apoc.cypher.runTimeboxed($statement, $query_parameters, $timeout_ms)"
    )
    parameters = {
        "statement": query,
        "query_parameters": parameters or {},
        "timeout_ms": int(float(timeout) * 1000),
    }
    try:
        with driver.session() as session:
            result = session.run(
                Query(apoc_query, timeout=float(timeout) + 1),
                parameters,
            )
            return list(result)
    finally:
        driver.close()


__all__ = [
    "create_neo4j_driver",
    "graph_config_key",
    "load_neo4j_config",
    "query_neo4j",
    "query_new_neo4j",
]

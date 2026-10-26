from collections.abc import Mapping

from ....common.neo4j_client import query_neo4j


def _record_path(record):
    if isinstance(record, Mapping):
        return record.get("p")
    if hasattr(record, "data"):
        return record.data().get("p")
    if isinstance(record, (tuple, list)) and record:
        value = record[0]
        if isinstance(value, Mapping):
            return value.get("p")
    return None


def _node_name(node):
    try:
        return node.get("name", str(node))
    except AttributeError:
        return str(node)


def _relation_name(relationship):
    try:
        return relationship.get("name") or relationship.type
    except AttributeError:
        return str(relationship)


def n_hop_ent(head, n_hop):
    """Return random paths exactly ``n_hop`` edges away from an entity."""
    n_hop = int(n_hop)
    if not 1 <= n_hop <= 5:
        raise ValueError(f"n_hop must be between 1 and 5: {n_hop}")

    intermediate = "-[]-(:ownthink)" * (n_hop - 1)
    query = (
        f"MATCH p=(a:ownthink){intermediate}-[]-(:ownthink) "
        "WHERE a.name = $head "
        "RETURN p ORDER BY rand() LIMIT 100"
    )
    records = query_neo4j(query, parameters={"head": str(head)})
    formatted_paths = []
    path_triplets = []

    for record in records:
        path = _record_path(record)
        if path is None:
            continue
        nodes = list(path.nodes)
        relationships = list(path.relationships)
        if not nodes:
            continue

        path_text = _node_name(nodes[0])
        triplets = []
        for index, relationship in enumerate(relationships):
            current = nodes[index]
            following = nodes[index + 1]
            following_name = _node_name(following)
            relation_name = _relation_name(relationship)
            is_forward = relationship.start_node == current
            if is_forward:
                path_text += f"-{relation_name}->{following_name}"
            else:
                path_text += f"<-{relation_name}-{following_name}"
            triplets.append(
                [
                    _node_name(relationship.start_node),
                    relation_name,
                    _node_name(relationship.end_node),
                ]
            )
        formatted_paths.append(path_text)
        path_triplets.append(triplets)

    return formatted_paths, path_triplets


def KO_tupu(keywords_list):
    results = []
    for keyword in keywords_list or []:
        paths, _triplets = n_hop_ent(keyword, 1)
        results.append(paths)
    return results

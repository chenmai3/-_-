import re
from collections.abc import Mapping


_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class UnresolvedRulePlaceholderError(ValueError):
    pass


def build_match_info(payload: Mapping, match_span: str = "") -> dict[str, str]:
    r1name = str(payload.get("R1Name") or payload.get("r1name") or "")
    r2name = str(payload.get("R2Name") or payload.get("r2name") or "")
    riname = str(payload.get("RIName") or payload.get("riname") or "")
    return {
        "R1Name": r1name,
        "R2Name": r2name,
        "RIName": riname,
        "match_span": match_span or "".join(x for x in (r1name, r2name, riname) if x),
    }


def _escape_cypher_text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def render_cypher(cypher: str, match_info: Mapping, query_text: str = "") -> str:
    r1name = match_info.get("R1Name") or match_info.get("r1name") or ""
    r2name = match_info.get("R2Name") or match_info.get("r2name") or ""
    riname = match_info.get("RIName") or match_info.get("riname") or ""
    replacements = {
        "r1name": r1name,
        "r2name": r2name,
        "riname": riname,
        "partname": match_info.get("partname") or r1name,
        "cyclename": match_info.get("cyclename") or r2name,
        "itemname": match_info.get("itemname") or riname,
        "faultname": match_info.get("faultname") or r2name,
        "phenomenon": match_info.get("phenomenon") or riname,
        "entityname": match_info.get("entityname") or riname,
        "match_span": match_info.get("match_span") or " ".join(x for x in (r1name, r2name, riname) if x),
        "query": query_text,
    }

    unresolved = set()

    def replace(match):
        key = match.group(1).casefold()
        if key not in replacements:
            unresolved.add(match.group(1))
            return match.group(0)
        return _escape_cypher_text(replacements[key])

    rendered = _PLACEHOLDER_PATTERN.sub(replace, str(cypher))
    if unresolved:
        names = ", ".join(sorted(unresolved))
        raise UnresolvedRulePlaceholderError(f"规则路径包含未支持的占位符: {names}")
    return rendered

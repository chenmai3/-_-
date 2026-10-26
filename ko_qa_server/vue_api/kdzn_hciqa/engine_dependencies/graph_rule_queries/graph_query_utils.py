import re

from pypinyin import lazy_pinyin


def record_payload(record):
    """Return the payload for both Neo4j Record and test-friendly mappings."""
    try:
        return record[0]
    except Exception:
        return record


def normalize_rule_paths(rule_path):
    if not rule_path:
        return []
    if isinstance(rule_path, list):
        return rule_path
    return [rule_path]


def han2pinyin_concat(txt: str) -> str:
    """Convert Chinese to continuous lowercase pinyin and retain alphanumerics."""
    result = []
    for char in txt:
        if re.match(r"[\u4e00-\u9fff]", char):
            pinyins = lazy_pinyin(char, errors="ignore")
            if pinyins:
                result.append(pinyins[0])
        elif re.match(r"[A-Za-z0-9]", char):
            result.append(char.lower())
    return "".join(result)


def remove_substrings(str_list):
    """Remove strings that are substrings of another item in the list."""
    sorted_list = sorted(str_list, key=len, reverse=True)
    result = []
    for index, value in enumerate(sorted_list):
        if not any(value in longer_value for longer_value in sorted_list[:index]):
            result.append(value)
    return result


def get_chinese_properties(node):
    return {
        key: value
        for key, value in node._properties.items()
        if (
            isinstance(key, str)
            and any("\u4e00" <= char <= "\u9fff" for char in key)
        )
        or key == "requirement"
    }

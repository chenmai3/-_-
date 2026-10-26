import time
from dataclasses import dataclass, field
from threading import RLock
from typing import List, Tuple


@dataclass
class SearchResult:
    is_over: bool
    result_names: List[str]
    paths: List[str]
    path2triplet: List[list]
    path_triplets: List[tuple]
    matched_entities: List[Tuple[float, str]]


EMPTY_RES = SearchResult(False, [], [], [], [], [])


def normalize_matched_entities(value):
    if not value:
        return []
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[1], str)
    ):
        return [value]
    return list(value)


def clone_search_result(result, *, is_over=None):
    return SearchResult(
        result.is_over if is_over is None else is_over,
        list(result.result_names or []),
        list(result.paths or []),
        list(result.path2triplet or []),
        list(result.path_triplets or []),
        normalize_matched_entities(result.matched_entities),
    )


@dataclass
class GeneralQueryCache:
    results: list[SearchResult] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=RLock, repr=False)

    def clear(self):
        self.results = []
        self.updated_at = time.monotonic()

    def replace(self, results):
        self.results = [
            clone_search_result(result)
            for result in results or []
            if isinstance(result, SearchResult)
            and (result.paths or result.result_names or result.path_triplets)
        ]
        self.updated_at = time.monotonic()

    def get_results(self, *, is_over=None):
        return [
            clone_search_result(result, is_over=is_over)
            for result in self.results
        ]

    def get_paths(self):
        return [path for result in self.results for path in result.paths]

    def get_result_by_path(self, selected_path):
        for result in self.results:
            if selected_path not in result.paths:
                continue
            index = result.paths.index(selected_path)
            names = (
                [result.result_names[index]]
                if index < len(result.result_names)
                else []
            )
            path2triplet = (
                [result.path2triplet[index]]
                if index < len(result.path2triplet)
                else []
            )
            return SearchResult(
                result.is_over,
                names,
                [selected_path],
                path2triplet,
                list(result.path_triplets),
                normalize_matched_entities(result.matched_entities),
            )
        return None


class GeneralQueryStateStore:
    def __init__(self, ttl_seconds=3600):
        self._ttl_seconds = ttl_seconds
        self._states = {}
        self._lock = RLock()

    @staticmethod
    def _key(session_id, scope):
        return str(session_id or "__default__"), str(scope or "__default__")

    def _remove_expired(self, now):
        expired = [
            key
            for key, state in self._states.items()
            if now - state.updated_at > self._ttl_seconds
        ]
        for key in expired:
            self._states.pop(key, None)

    def get(self, session_id, scope=None):
        now = time.monotonic()
        key = self._key(session_id, scope)
        with self._lock:
            self._remove_expired(now)
            state = self._states.get(key)
            if state is None:
                state = GeneralQueryCache()
                self._states[key] = state
            state.updated_at = now
            return state

    def clear(self, session_id, scope=None):
        session_key = str(session_id or "__default__")
        with self._lock:
            if scope is not None:
                self._states.pop(self._key(session_id, scope), None)
                return
            for key in [key for key in self._states if key[0] == session_key]:
                self._states.pop(key, None)


general_query_states = GeneralQueryStateStore()

from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class SearchMode(str, Enum):
    STRICT = "strict"
    STANDARD = "standard"
    LOOSE = "loose"


DEFAULT_MODE = SearchMode.STANDARD
DEFAULT_PREFIX_MINLEN = 4


@dataclass
class SearchPlan:
    mode: SearchMode
    fts_query: Optional[str]
    tokens: list[str]
    empty_reason: Optional[str] = None
    is_wildcard: bool = False


def normalize_mode(value: Optional[str], default: SearchMode = DEFAULT_MODE) -> SearchMode:
    if value:
        normalized = value.strip().lower()
        for mode in SearchMode:
            if normalized == mode.value:
                return mode
    return default


def _sanitize_token(token: str) -> str:
    token = (token or "").replace('"', "").replace("*", "").strip().lower()
    token = re.sub(r"\s+", "", token)
    return token


def tokenize_query(raw: str) -> list[str]:
    tokens: list[str] = []
    for part in re.split(r"[\s,]+", raw or ""):
        clean = _sanitize_token(part)
        if clean:
            tokens.append(clean)
    return tokens


def _term_for_mode(token: str, mode: SearchMode, prefix_min_len: int) -> str:
    if mode == SearchMode.STRICT:
        return token
    if mode == SearchMode.STANDARD:
        return f"{token}*" if len(token) >= prefix_min_len else token
    # locker/loose: toleranter, Prefix auch für kurze Tokens ab 2 Zeichen
    if len(token) >= 2:
        return f"{token}*"
    return token


def build_search_plan(raw_query: str, mode: SearchMode, prefix_min_len: int, allow_wildcard: bool = False) -> SearchPlan:
    trimmed = (raw_query or "").strip()
    if not trimmed:
        return SearchPlan(mode=mode, fts_query=None, tokens=[], empty_reason="Bitte Suchbegriff eingeben.")

    if trimmed == "*":
        if allow_wildcard:
            return SearchPlan(mode=mode, fts_query="*", tokens=["*"], is_wildcard=True)
        return SearchPlan(mode=mode, fts_query=None, tokens=[], empty_reason="Wildcard nur mit aktivem Filter.")

    tokens = tokenize_query(trimmed)
    if not tokens:
        return SearchPlan(mode=mode, fts_query=None, tokens=[], empty_reason="Bitte Suchbegriff eingeben.")

    prefix_len = max(1, int(prefix_min_len or 1))
    terms = [_term_for_mode(tok, mode, prefix_len) for tok in tokens]
    operator = " OR " if mode == SearchMode.LOOSE else " AND "
    query = operator.join(terms)
    return SearchPlan(mode=mode, fts_query=query, tokens=tokens)

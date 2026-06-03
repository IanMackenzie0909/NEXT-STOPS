"""Text normalization and lightweight fuzzy matching utilities."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable


_BRACKET_RE = re.compile(r"[（(].*?[）)]")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\-_/|・‧,，。．、:：;；!！?？'\"“”‘’]+")


def normalize_text(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("台", "臺")
    text = _BRACKET_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text)
    return text.lower().strip()


def compact_name(value: object) -> str:
    return normalize_text(value).replace(" ", "")


def tokenize(value: object) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    tokens = [t for t in text.split(" ") if t]
    # Chinese names often do not contain whitespace; keep the whole normalized string as one token.
    if len(text) >= 2 and text not in tokens:
        tokens.append(text)
    return tokens


def fuzzy_ratio(a: object, b: object) -> float:
    aa = compact_name(a)
    bb = compact_name(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    if aa in bb or bb in aa:
        return 0.92
    return SequenceMatcher(None, aa, bb).ratio()


def any_token_match(query_tokens: Iterable[str], haystack: str) -> bool:
    normalized = normalize_text(haystack)
    return any(token and token in normalized for token in query_tokens)

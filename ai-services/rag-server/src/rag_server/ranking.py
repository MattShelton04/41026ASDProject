"""Hybrid ranking: dense similarity fused with BM25 keyword relevance.

Small embedding models compress similarity into a narrow band, so passages that share a topic
word ("research area") can outrank the passage that names the exact thing asked about
("Research available"). Reciprocal rank fusion adds a keyword signal without mixing score
scales: the reported score stays the cosine similarity, which relevance floors and confidence
thresholds are calibrated against.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

BM25_K1 = 1.2
BM25_B = 0.75
RRF_K = 60
MAX_CHUNKS_PER_DOCUMENT = 2

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORD_TEXT = """
a an and are as at be by can do does for from how i if in is it its me my of on or our
so than that the their them then there these this to was we what when where which who
why will with you your
"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokens(text: str) -> list[str]:
    """Lower-case word tokens without stopwords; a trailing plural 's' is removed."""
    words = _TOKEN.findall(text.lower())
    return [
        word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
        for word in words
        if word not in _STOPWORDS
    ]


def bm25_scores(query: str, documents: Sequence[str]) -> list[float]:
    """Okapi BM25 for each document against the query, using corpus-level statistics."""
    terms = set(tokens(query))
    if not terms or not documents:
        return [0.0] * len(documents)
    tokenized = [tokens(document) for document in documents]
    average = sum(len(words) for words in tokenized) / len(tokenized) or 1.0
    frequency = Counter(term for words in tokenized for term in set(words) if term in terms)
    count = len(tokenized)
    idf = {
        term: math.log(1 + (count - frequency[term] + 0.5) / (frequency[term] + 0.5))
        for term in terms
    }
    scores = []
    for words in tokenized:
        counts = Counter(words)
        norm = BM25_K1 * (1 - BM25_B + BM25_B * len(words) / average)
        scores.append(
            sum(
                idf[term] * counts[term] * (BM25_K1 + 1) / (counts[term] + norm)
                for term in terms
                if counts[term]
            )
        )
    return scores


def fused_order(dense: Sequence[float], keyword: Sequence[float]) -> list[int]:
    """Indices ordered by reciprocal rank fusion of both signals (ties by dense score)."""

    def ranks(values: Sequence[float]) -> dict[int, int]:
        order = sorted(
            (index for index, value in enumerate(values) if value > 0), key=lambda i: -values[i]
        )
        return {index: rank for rank, index in enumerate(order, start=1)}

    dense_rank, keyword_rank = ranks(dense), ranks(keyword)

    def fused(index: int) -> float:
        return sum(
            1 / (RRF_K + rank[index]) for rank in (dense_rank, keyword_rank) if index in rank
        )

    return sorted(range(len(dense)), key=lambda index: (-fused(index), -dense[index]))

"""纯文本改写引擎。

对外只需要三个名字::

    from meow.engine import CatifyEngine, CatifyParams, preload

    engine = CatifyEngine()
    engine.rewrite("你在做什么？", CatifyParams(strength=2))
"""

from __future__ import annotations

from .analyzer import preload, tokenize
from .catifier import CatifyEngine
from .params import (
    KAOMOJI_INTERVAL_RANGE,
    KAOMOJI_PROB_RANGE,
    KAOMOJI_STD_RANGE,
    STRENGTH_LABELS,
    STRENGTH_MAX,
    STRENGTH_MIN,
    CatifyParams,
)
from .sentence import Emotion, SentenceKind, split_sentences

__all__ = [
    "CatifyEngine",
    "CatifyParams",
    "Emotion",
    "KAOMOJI_INTERVAL_RANGE",
    "KAOMOJI_PROB_RANGE",
    "KAOMOJI_STD_RANGE",
    "STRENGTH_LABELS",
    "STRENGTH_MAX",
    "STRENGTH_MIN",
    "SentenceKind",
    "preload",
    "split_sentences",
    "tokenize",
]

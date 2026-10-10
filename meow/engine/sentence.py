"""句子切分与分类 —— 纯字符串处理，不依赖 jieba。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from . import lexicon

# ---------------- 正则 ----------------

TRAILING_PUNCT_RE = re.compile(r"[。！？!?…~～\s]+$")
QUESTION_END_RE = re.compile(r"[?？]$")
EXCLAIM_END_RE = re.compile(r"[!！]$")
# 按句末标点切句，标点归属前一句
SENTENCE_SPLIT_RE = re.compile(r"[^。！？!?…]+[。！？!?…]*")

NEWLINE = "newline"
SENTENCE = "sentence"


class SentenceKind(str, Enum):
    """句式。"""

    STATEMENT = "statement"
    QUESTION = "question"
    EXCLAIM = "exclaim"


class Emotion(str, Enum):
    """情绪（用于挑颜文字）。"""

    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Segment:
    """切句结果的一段：要么是一个句子，要么是一个换行占位。"""

    kind: str
    text: str = ""

    @property
    def is_sentence(self) -> bool:
        return self.kind == SENTENCE


def strip_end_punct(text: str) -> str:
    """去掉句末的标点/空白。"""
    return TRAILING_PUNCT_RE.sub("", text).strip()


def has_tone_particle(sentence: str) -> bool:
    """句末（忽略标点）是否已经有语气助词。"""
    body = strip_end_punct(sentence)
    return bool(body) and body[-1] in lexicon.TONE_PARTICLES


def classify_sentence(sentence: str) -> SentenceKind:
    """按句末标点/语气词判断句式。"""
    stripped = sentence.rstrip()
    if stripped.endswith(("吗", "呢", "吧")) or QUESTION_END_RE.search(stripped):
        return SentenceKind.QUESTION
    if EXCLAIM_END_RE.search(stripped):
        return SentenceKind.EXCLAIM
    return SentenceKind.STATEMENT


def classify_emotion(sentence: str) -> Emotion:
    """按关键词判断情绪，优先级：开心 > 难过 > 生气 > 中性。"""
    if any(char in lexicon.HAPPY_CHARS for char in sentence):
        return Emotion.HAPPY
    if any(char in lexicon.SAD_CHARS for char in sentence):
        return Emotion.SAD
    if any(char in lexicon.ANGRY_CHARS for char in sentence):
        return Emotion.ANGRY
    return Emotion.NEUTRAL


def split_sentences(text: str) -> list[Segment]:
    """把整段文本切成句子，换行原样保留成 ``newline`` 段。

    这里修掉了 v1 的一个数据丢失问题：v1 只在遇到**空行**时才补一个换行段，
    于是 ``"第一行\\n第二行"`` 里的换行会被整个吃掉，多行消息会被拼成一行，
    而 ``"a\\n\\nb"`` 又会被压成一个换行。现在的规则是「段与段之间必然有换行」，
    重建后与原文的行结构完全一致。
    """
    segments: list[Segment] = []
    for index, paragraph in enumerate(text.split("\n")):
        if index > 0:
            segments.append(Segment(NEWLINE))
        if not paragraph.strip():
            continue
        for piece in SENTENCE_SPLIT_RE.findall(paragraph):
            if piece.strip():
                segments.append(Segment(SENTENCE, piece))
    return segments

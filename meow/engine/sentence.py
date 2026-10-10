"""句子切分与分类。

标点分两类，处理方式完全不同：

* **句末标点**（``。！？!?…``，以及当句末用的半角 ``.``）——句子到此结束。
  标点先留在句尾交给改写器，由它决定换成「喵~」还是还原成「？」「！」。
* **句内分隔**（``，,、；;：:`` 和空白）——只把长句切成小句，标点本身
  **原样保留**在输出里。这样 ``"你好，今天天气真好"`` 会变成
  ``"你好喵~，今天天气真好喵~"``，而不是把逗号挤到「喵」后面。

半角标点比全角危险得多：``3.14``、``example.com``、``http://``、``12:30``
里的标点都不是句末，所以额外做了保护。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from . import lexicon

# ---------------- 标点分类 ----------------

# 句末标点：句子到此为止
HARD_ENDERS: frozenset[str] = frozenset("。！？!?…")

# 句内分隔：切小句，标点保留（逗号、顿号、分号、冒号）
SOFT_SEPARATORS: frozenset[str] = frozenset("，,、；;：:")

# 这些半角标点需要额外判断，避免把数字/网址切开
GUARDED_HALFWIDTH: frozenset[str] = frozenset({".", ",", ":"})

# ---------------- 正则 ----------------

TRAILING_PUNCT_RE = re.compile(r"[。！？!?…~～.\s]+$")
QUESTION_END_RE = re.compile(r"[?？]$")
EXCLAIM_END_RE = re.compile(r"[!！]$")

# ---------------- 段落类型 ----------------

NEWLINE = "newline"
SENTENCE = "sentence"
SEPARATOR = "separator"


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
    """切句结果的一段。

    ``literal`` 不为 ``None`` 表示这一段不需要猫化，原样输出即可。
    """

    kind: str
    text: str = ""

    @property
    def is_sentence(self) -> bool:
        return self.kind == SENTENCE

    @property
    def literal(self) -> str | None:
        """不需要改写的段落应该原样输出的文字。"""
        if self.kind == NEWLINE:
            return "\n"
        if self.kind == SEPARATOR:
            return self.text
        return None


# ---------------- 纯字符串工具 ----------------


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


# ---------------- 半角标点的保护判断 ----------------


def _halfwidth_splits(text: str, index: int) -> bool:
    """这个半角标点要不要在这里断句。

    返回 ``False`` 表示它属于词/数字/网址内部，不该断。
    """
    char = text[index]
    previous = text[index - 1] if index > 0 else ""
    following = text[index + 1] if index + 1 < len(text) else ""

    if char == ".":
        # 3.14、example.com、index.js：两边都是 ASCII 字母数字 → 不是句末
        if (
            previous.isascii()
            and previous.isalnum()
            and following.isascii()
            and following.isalnum()
        ):
            return False
    elif char == ":":
        if following in "/\\":  # http://  https://  C:\
            return False
        if previous.isdigit() and following.isdigit():  # 12:30
            return False
    elif char == ",":
        if previous.isdigit() and following.isdigit():  # 1,000
            return False
    return True


def _is_hard_ender_at(text: str, index: int, sentence_started: bool) -> bool:
    """``text[index]`` 是不是一个句末标点。"""
    char = text[index]
    if char in HARD_ENDERS:
        return True
    if char == ".":
        # 开头的 ".5" 不当作句末，否则前面的内容会被吞掉
        return sentence_started and _halfwidth_splits(text, index)
    return False


# ---------------- 切句 ----------------


def split_sentences(text: str, *, split_on_space: bool = True) -> list[Segment]:
    """把整段文本切成「小句 + 分隔符 + 换行」的序列。

    ``split_on_space=False`` 时空白不再断句（英文句子能保持完整）。
    """
    segments: list[Segment] = []
    sentence: list[str] = []
    separators: list[str] = []
    pending_flush = False  # 刚读到句末标点，等下一个字符决定要不要收句

    def flush_sentence() -> None:
        if sentence:
            segments.append(Segment(SENTENCE, "".join(sentence)))
            sentence.clear()

    def flush_separators() -> None:
        if separators:
            segments.append(Segment(SEPARATOR, "".join(separators)))
            separators.clear()

    for index, char in enumerate(text):
        # 连续的句末标点（「？？？」「...」）要留给同一句
        if pending_flush and not _is_hard_ender_at(text, index, bool(sentence)):
            flush_sentence()
            pending_flush = False

        if char == "\n":
            flush_sentence()
            flush_separators()
            segments.append(Segment(NEWLINE))
            continue

        if _is_hard_ender_at(text, index, bool(sentence)):
            sentence.append(char)
            pending_flush = True
            continue

        if char in SOFT_SEPARATORS:
            if char in GUARDED_HALFWIDTH and not _halfwidth_splits(text, index):
                sentence.append(char)  # 句子内部，比如 1,000
                continue
            flush_sentence()
            pending_flush = False
            separators.append(char)
            continue

        if char.isspace():
            if not split_on_space:
                # 不断句：句中空格留在句子内部，句首空格跟分隔符一起原样保留
                # （否则它会被 catify_sentence 的 strip() 吃掉）
                if sentence:
                    sentence.append(char)
                else:
                    separators.append(char)
                continue
            flush_sentence()
            pending_flush = False
            separators.append(char)
            continue

        flush_separators()
        sentence.append(char)

    flush_sentence()
    flush_separators()
    return segments

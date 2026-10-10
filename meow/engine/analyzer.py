"""基于 jieba 词性标注的语义分析：判断要不要补主语、替换人称代词。

jieba 首次分词要加载词典（约 1 秒），所以这里做**惰性导入 + 显式预热**：
程序启动时可以在后台线程里调用 :func:`preload`，避免第一次按回车时卡顿。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from . import lexicon
from .sentence import SentenceKind, classify_sentence, strip_end_punct

LOGGER = logging.getLogger(__name__)

_pseg = None  # jieba.posseg 模块句柄，第一次用到时才导入


@dataclass(frozen=True)
class Token:
    """一个带词性的词。"""

    word: str
    flag: str


@dataclass(frozen=True)
class Roles:
    """句子里的主语 / 谓语 / 宾语下标（-1 表示没找到）。"""

    subject: int = -1
    verb: int = -1
    object: int = -1


def _load_pseg():
    global _pseg
    if _pseg is None:
        import jieba.posseg as pseg  # 导入较慢，放到真正需要的时候

        _pseg = pseg
    return _pseg


def preload() -> bool:
    """预加载 jieba 词典；成功返回 True，失败只记日志（不影响主流程）。"""
    try:
        tokenize("预热")
        return True
    except Exception as exc:
        LOGGER.warning("jieba 预热失败，将退化为不补主语：%s", exc)
        return False


def tokenize(text: str) -> list[Token]:
    """分词 + 词性标注。jieba 不可用时退化成「整句当一个词」，功能降级但不崩。"""
    if not text:
        return []
    try:
        pseg = _load_pseg()
        return [Token(pair.word, pair.flag) for pair in pseg.cut(text)]
    except Exception as exc:
        LOGGER.warning("jieba 分词失败，跳过词性分析：%s", exc)
        return [Token(text, "x")]


def needs_subject(sentence: str) -> bool:
    """判断句子是不是「缺主语」——比如「吃饭了吗」「好棒」。
    """
    body = strip_end_punct(sentence)
    if not body:
        return False
    if body in lexicon.NO_SUBJECT_PHRASES:
        return False
    for key, value in lexicon.PHRASE_MAP.items():
        if body == key or body == value:
            return False
    tokens = tokenize(body)
    if not tokens:
        return False
    first_flag = tokens[0].flag
    if first_flag.startswith(lexicon.SUBJECT_FLAGS):
        return False
    return first_flag.startswith(lexicon.PREDICATE_FLAGS)


def add_subject(sentence: str) -> str:
    """按句式补上主语：疑问句用「主人」，陈述句用「本喵」。"""
    subject = "主人" if classify_sentence(sentence) == SentenceKind.QUESTION else "本喵"
    return subject + sentence


def classify_roles(tokens: Iterable[Token]) -> Roles:
    """找出主语 / 谓语 / 宾语的位置：谓语是第一个动词，主语在它前面，
    宾语在它后面；没有动词时，第一个代词当主语。"""
    token_list = list(tokens)

    verb = -1
    for index, token in enumerate(token_list):
        if token.flag.startswith("v"):
            verb = index
            break

    subject = -1
    obj = -1
    if verb >= 0:
        for index in range(verb):
            if token_list[index].flag.startswith("r"):
                subject = index
                break
        for index in range(verb + 1, len(token_list)):
            if token_list[index].flag.startswith("r"):
                obj = index
                break
    else:
        for index, token in enumerate(token_list):
            if token.flag.startswith("r"):
                subject = index
                break

    return Roles(subject=subject, verb=verb, object=obj)


def replace_pronouns(
    tokens: Iterable[Token],
    only_subject_object: bool = False,
) -> list[str]:
    """替换人称代词。

    ``only_subject_object=True`` 时只替换主语/宾语位置，避免把「我觉得」
    里的「我」也换掉这类误伤。
    """
    token_list = list(tokens)
    roles = classify_roles(token_list)

    result: list[str] = []
    for index, token in enumerate(token_list):
        mapped = lexicon.PRONOUN_MAP.get(token.word)
        if mapped is None or not token.flag.startswith("r"):
            result.append(token.word)
            continue
        if only_subject_object and index not in (roles.subject, roles.object):
            result.append(token.word)
            continue
        result.append(mapped)
    return result

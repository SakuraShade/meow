"""基于 jieba 词性标注的语义分析：判断要不要补主语、替换人称代词。

jieba 首次分词要加载词典（约 1 秒），所以这里做**惰性导入 + 显式预热**：
程序启动时可以在后台线程里调用 :func:`preload`，避免第一次按回车时卡顿。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from . import lexicon
from .sentence import Emotion, SentenceKind, classify_sentence, strip_end_punct

LOGGER = logging.getLogger(__name__)

_pseg = None  # jieba.posseg 模块句柄，第一次用到时才导入

# 情绪优先级：得分相同时按这个顺序挑（开心 > 难过 > 生气 > 中性）
EMOTION_ORDER = ("happy", "sad", "angry")


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


def needs_subject(sentence: str, tokens: Iterable[Token] | None = None) -> bool:
    """判断句子是不是「缺主语」——比如「吃饭了吗」「来陪我玩」。

    ``tokens`` 可由调用方传入（避免重复分词）；缺省时这里自己分。
    """
    body = strip_end_punct(sentence)
    if not body:
        return False
    if body in lexicon.NO_SUBJECT_PHRASES:
        return False
    for key, value in lexicon.PHRASE_MAP.items():
        if body == key or body == value:
            return False
    token_list = list(tokens) if tokens is not None else tokenize(body)
    if not token_list:
        return False
    first = token_list[0]
    # 祈使句开头（请/别/不要……）虽然没有显式主语，也要补——补的是「主人」
    if first.word in lexicon.IMPERATIVE_LEADERS:
        return True
    if first.flag.startswith(lexicon.SUBJECT_FLAGS):
        return False
    return first.flag.startswith(lexicon.PREDICATE_FLAGS)


def is_imperative(tokens: Iterable[Token]) -> bool:
    """是不是祈使句——主语默认是「你/主人」而不是「本喵」。

    两条可靠的线索：

    1. 句首是祈使引导词（请、别、不要、快点、拜托……）；
    2. 第一个词之后出现了第一人称「我/咱」——动作是冲着「本喵」来的，
       那动作的发出者只能是对方（来**陪**我玩、帮**我**、给**我**看）。
    """
    token_list = list(tokens)
    if not token_list:
        return False
    if token_list[0].word in lexicon.IMPERATIVE_LEADERS:
        return True
    for token in token_list[1:]:
        if any(pronoun in token.word for pronoun in lexicon.FIRST_PERSON_PRONOUNS):
            return True
    return False


def infer_subject(sentence: str, tokens: Iterable[Token]) -> str:
    """给缺主语的句子挑主语：「主人」还是「本喵」。

    * 疑问句 —— 问的是对方 → 「主人」；
    * 祈使句 —— 在对对方下指令 → 「主人」；
    * 其余（陈述自己的动作/状态）→ 「本喵」。
    """
    if classify_sentence(sentence) is SentenceKind.QUESTION:
        return "主人"
    if is_imperative(tokens):
        return "主人"
    return "本喵"


def add_subject(sentence: str, tokens: Iterable[Token] | None = None) -> str:
    """按句式补上主语（疑问/祈使用「主人」，其余用「本喵」）。"""
    token_list = list(tokens) if tokens is not None else tokenize(strip_end_punct(sentence))
    return infer_subject(sentence, token_list) + sentence


def detect_emotion(tokens: Iterable[Token], text: str) -> Emotion:
    """按词（而不是单字）判断情绪，返回挑颜文字要用的类别。

    分两层匹配（见 :data:`~meow.engine.lexicon.EMOTION_PHRASES` 的说明）：

    * 多字短语 —— 在原文里做子串匹配；
    * 单字 —— 只匹配独立的词。

    情绪词前面紧跟否定词时做一次翻转：不开心→难过、别生气→平静、不难过→平静。
    """
    token_list = list(tokens)
    scores = {"happy": 0, "sad": 0, "angry": 0}
    matched: list[tuple[str, str]] = []  # (emotion, word)

    for emotion, phrases in lexicon.EMOTION_PHRASES.items():
        for phrase in phrases:
            if phrase in text:
                scores[emotion] += 1
                matched.append((emotion, phrase))

    token_words = {token.word for token in token_list}
    for emotion, chars in lexicon.EMOTION_CHARS.items():
        for char in chars:
            if char in token_words:
                scores[emotion] += 1
                matched.append((emotion, char))

    for emotion, word in matched:
        for negation in lexicon.NEGATION_WORDS:
            needle = negation + word
            index = text.find(needle)
            if index < 0:
                continue
            # 正反问句有两种叠字法：「喜不喜欢」（不 前是词首字）、
            # 「高兴不高兴」（不 前是词尾字）。这都是在问「要不要」，
            # 不是否定，跳过翻转。
            if index > 0 and text[index - 1] in (word[0], word[-1]):
                continue
            _flip_negation(scores, emotion)
            break

    if scores["happy"] <= 0 and scores["sad"] <= 0 and scores["angry"] <= 0:
        return Emotion.NEUTRAL

    best_score = max(scores[emotion] for emotion in EMOTION_ORDER)
    for emotion in EMOTION_ORDER:
        if scores[emotion] == best_score:
            return Emotion(emotion)
    return Emotion.NEUTRAL


def _flip_negation(scores: dict[str, int], emotion: str) -> None:
    """被否定时翻转/取消一次情绪命中。"""
    if emotion == "happy":
        scores["happy"] -= 1
        scores["sad"] += 1  # 「不开心」≈ 难过
    elif emotion == "sad":
        scores["sad"] -= 1  # 「不难过」≈ 平静
    elif emotion == "angry":
        scores["angry"] -= 1  # 「别生气」≈ 平静


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

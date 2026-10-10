"""猫化引擎：把一段文本改写成猫娘语气。

这个模块**只做文本改写**，不碰剪贴板、不碰界面、不依赖任何全局状态，
所以可以单独跑、单独测。随机数用注入的 ``random.Random`` 实例，
既保证线程安全，也让测试可以完全复现。
"""

from __future__ import annotations

import random
import re
from dataclasses import replace

from . import analyzer, lexicon
from .params import CatifyParams
from .sentence import (
    Emotion,
    Segment,
    SentenceKind,
    classify_sentence,
    has_tone_particle,
    split_sentences,
)

# 句末标点（改写前先摘掉，改写后按句式重新贴回去）
TRAILING_PUNCT_RE = re.compile(r"([。！？!?…~～.]+)$")

# 疑问句改用疑问系颜文字的概率
QUESTION_KAOMOJI_PROB = 0.5


class CatifyEngine:
    """无状态的改写器（随机源除外）。"""

    def __init__(self, random_source: random.Random | None = None) -> None:
        self._random = random_source or random.Random()

    # ---------------- 对外接口 ----------------

    def rewrite(self, text: str, params: CatifyParams | None = None, **overrides) -> str:
        """便捷入口：``overrides`` 会覆盖 ``params`` 里的同名字段。"""
        base = (params or CatifyParams()).clamp()
        if overrides:
            base = replace(base, **overrides).clamp()
        return self.catify(text, base)

    def catify(self, text: str, params: CatifyParams | None = None) -> str:
        """把整段文本猫化，保留原有换行与标点结构。

        切句时逗号、顿号、分号、空格都会把小句切开（各给小句补一个「喵」），
        但这些分隔符本身会原样输出，不会被语气词挤掉。

        颜文字分布策略：

        * 只有一句 —— 以 ``kaomoji_prob`` 概率添加；
        * 多句 —— 间隔服从 ``N(kaomoji_interval, kaomoji_std)``，
          这样天然会有「一段密集、一段稀疏」的节奏，而不是机械地每句都加。
        """
        settings = (params or CatifyParams()).clamp()
        if text is None:
            return ""
        if settings.seed is not None:
            self._random.seed(settings.seed)

        segments = split_sentences(text, split_on_space=settings.split_on_space)
        kaomoji_positions = self._plan_kaomoji(segments, settings)

        pieces: list[str] = []
        for index, segment in enumerate(segments):
            literal = segment.literal
            if literal is not None:
                # 换行、逗号、空格等原样输出
                pieces.append(literal)
                continue
            pieces.append(
                self.catify_sentence(
                    segment.text,
                    settings,
                    allow_kaomoji=index in kaomoji_positions,
                )
            )
        return "".join(pieces)

    def catify_sentence(
        self,
        sentence: str,
        params: CatifyParams | None = None,
        *,
        allow_kaomoji: bool = True,
    ) -> str:
        """改写单个句子。步骤固定为：短语替换 → 剥标点 → 分词 →
        补主语（疑问/祈使用「主人」）→ 换人称 → 加语气词 → 加波浪号 →
        还原标点 → 颜文字。"""
        settings = (params or CatifyParams()).clamp()

        # 1. 固定短语替换
        for key, value in lexicon.PHRASE_MAP.items():
            sentence = sentence.replace(key, value)

        # 2. 摘掉句末标点，后面按句式贴回去
        match = TRAILING_PUNCT_RE.search(sentence)
        body = sentence[: -len(match.group(1))] if match else sentence
        body = body.strip()
        if not body:
            return ""

        # 3. 分词（原文先分一次，情绪和补主语都要用）
        tokens = analyzer.tokenize(body)
        emotion = analyzer.detect_emotion(tokens, body)

        # 4. 补主语：疑问/祈使句默认主语是「主人」，其余是「本喵」
        if analyzer.needs_subject(body, tokens):
            subject = analyzer.infer_subject(sentence, tokens)
            body = subject + body
            tokens = analyzer.tokenize(body)  # 补完主语，重新分词再换人称

        # 5. 人称代词替换
        body = "".join(
            analyzer.replace_pronouns(tokens, only_subject_object=settings.only_subject_object)
        )

        kind = classify_sentence(sentence)
        particle_present = has_tone_particle(body)

        # 6. 句末语气词
        if settings.strength >= 1:
            body += self._pick_particle(kind, particle_present)

        # 7. 波浪号（句末语气词可能已经带了 ~，别叠成「喵~~」）
        if settings.add_tilde and not body.endswith(("~", "～")):
            body += "~"

        # 8. 还原句末标点
        if kind is SentenceKind.QUESTION:
            body += "？"
        elif kind is SentenceKind.EXCLAIM:
            body += "！"

        # 9. 颜文字
        if settings.strength >= 2 and allow_kaomoji:
            body += self._pick_kaomoji(emotion, kind)

        return body

    # ---------------- 内部：随机挑选 ----------------

    def _pick_particle(self, kind: SentenceKind, particle_present: bool) -> str:
        if kind is SentenceKind.QUESTION:
            pool = lexicon.MEOW_WITH_PARTICLE if particle_present else lexicon.MEOW_Q_NO_PARTICLE
        elif kind is SentenceKind.EXCLAIM:
            pool = lexicon.MEOW_WITH_PARTICLE if particle_present else lexicon.MEOW_EX_NO_PARTICLE
        else:
            pool = lexicon.MEOW_WITH_PARTICLE if particle_present else lexicon.MEOW_STATEMENT
        return self._random.choice(pool)

    def _pick_kaomoji(self, emotion: Emotion, kind: SentenceKind) -> str:
        key = emotion.value if emotion.value in lexicon.KAOMOJI else lexicon.DEFAULT_EMOTION
        # 疑问句有一半概率换成疑问系颜文字，语气更贴
        if kind is SentenceKind.QUESTION and self._random.random() < QUESTION_KAOMOJI_PROB:
            key = "question"
        pool = lexicon.KAOMOJI.get(key) or lexicon.KAOMOJI[lexicon.DEFAULT_EMOTION]
        return self._random.choice(pool)

    def _plan_kaomoji(self, segments: list[Segment], params: CatifyParams) -> set[int]:
        """先决定「哪几句加颜文字」，再统一改写。"""
        positions: set[int] = set()
        if params.strength < 2:
            return positions

        sentence_indices = [i for i, seg in enumerate(segments) if seg.is_sentence]
        total = len(sentence_indices)
        if total == 0:
            return positions

        if total == 1:
            if self._random.random() < params.kaomoji_prob:
                positions.add(sentence_indices[0])
            return positions

        # 多句：随机起点 + 正态间隔，避免总是落在第一句、也避免过于规律
        cursor = self._random.randint(0, max(1, int(params.kaomoji_interval) - 1))
        while cursor < total:
            positions.add(sentence_indices[cursor])
            step = max(1, round(self._random.gauss(params.kaomoji_interval, params.kaomoji_std)))
            cursor += step
        return positions

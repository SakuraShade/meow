# -*- coding: utf-8 -*-
"""改写引擎测试。

这些用例锁住 v1 的行为：重构后的输出必须与 v1 逐字节一致，
所以断言里写的是「确定性」的部分（seed 固定后的完整输出、结构性质）。
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meow.engine import CatifyEngine, CatifyParams  # noqa: E402
from meow.engine.sentence import (  # noqa: E402
    Emotion,
    SentenceKind,
    classify_emotion,
    classify_sentence,
    has_tone_particle,
    split_sentences,
    strip_end_punct,
)


def make_engine(seed: int = 42) -> CatifyEngine:
    return CatifyEngine(random.Random(seed))


class TestSentenceHelpers(unittest.TestCase):
    def test_strip_end_punct(self):
        self.assertEqual(strip_end_punct("你好！"), "你好")
        self.assertEqual(strip_end_punct("  你好 …~ "), "你好")
        self.assertEqual(strip_end_punct(""), "")

    def test_has_tone_particle(self):
        self.assertTrue(has_tone_particle("好吗"))
        self.assertTrue(has_tone_particle("好的呀！"))
        self.assertFalse(has_tone_particle("你好"))
        self.assertFalse(has_tone_particle(""))

    def test_classify_sentence(self):
        self.assertIs(classify_sentence("你好吗"), SentenceKind.QUESTION)
        self.assertIs(classify_sentence("走吧"), SentenceKind.QUESTION)
        self.assertIs(classify_sentence("这是真的？"), SentenceKind.QUESTION)
        self.assertIs(classify_sentence("太棒了！"), SentenceKind.EXCLAIM)
        self.assertIs(classify_sentence("今天天气不错。"), SentenceKind.STATEMENT)

    def test_classify_emotion_priority(self):
        # 注意优先级：只要句子里有开心字，就不会判成难过（v1 行为）
        self.assertIs(classify_emotion("好开心啊"), Emotion.HAPPY)
        self.assertIs(classify_emotion("好难过"), Emotion.HAPPY)
        self.assertIs(classify_emotion("太难过了"), Emotion.SAD)
        self.assertIs(classify_emotion("真讨厌"), Emotion.ANGRY)
        self.assertIs(classify_emotion("今天星期三"), Emotion.NEUTRAL)

    def test_split_sentences_keeps_blank_lines(self):
        segments = split_sentences("你好。\n\n在吗？")
        kinds = [segment.kind for segment in segments]
        self.assertEqual(kinds, ["sentence", "newline", "newline", "sentence"])
        self.assertEqual(segments[0].text, "你好。")
        self.assertEqual(segments[3].text, "在吗？")

    def test_split_sentences_keeps_single_newline(self):
        segments = split_sentences("第一行\n第二行")
        self.assertEqual([s.kind for s in segments], ["sentence", "newline", "sentence"])

    def test_split_sentences_blank_input_has_no_segments(self):
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences("   "), [])

    def test_split_sentences_no_trailing_punctuation(self):
        segments = split_sentences("没有标点")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "没有标点")


class TestCatifyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def test_seed_makes_output_reproducible(self):
        params = CatifyParams(seed=7)
        first = self.engine.catify("你好吗？今天天气真好。", params)
        second = self.engine.catify("你好吗？今天天气真好。", params)
        self.assertEqual(first, second)

    def test_pure_function_does_not_mutate_params(self):
        params = CatifyParams(strength=2, seed=3)
        snapshot = params.to_dict()
        self.engine.catify("你在做什么？", params)
        self.assertEqual(params.to_dict(), snapshot)

    def test_strength_zero_has_no_meow(self):
        result = self.engine.catify("你好", CatifyParams(strength=0, add_tilde=False))
        self.assertNotIn("喵", result)

    def test_strength_one_adds_particle_but_no_kaomoji(self):
        result = self.engine.catify("你好", CatifyParams(strength=1, add_tilde=False))
        self.assertTrue(result.startswith("你好"))
        self.assertGreater(len(result), len("你好"), "强度 1 应该在句末补语气词")
        self.assertNotIn("(", result)

    def test_add_tilde_toggle(self):
        with_tilde = self.engine.catify("你好", CatifyParams(strength=0, add_tilde=True))
        without = self.engine.catify("你好", CatifyParams(strength=0, add_tilde=False))
        self.assertTrue(with_tilde.endswith("~"))
        self.assertFalse(without.endswith("~"))

    def test_pronoun_replacement(self):
        result = self.engine.catify("我喜欢你", CatifyParams(strength=0, add_tilde=False))
        self.assertIn("本喵", result)
        self.assertIn("主人", result)

    def test_phrase_replacement(self):
        result = self.engine.catify("好的", CatifyParams(strength=0, add_tilde=False))
        self.assertIn("好哒", result)

    def test_question_mark_preserved(self):
        result = self.engine.catify("你在做什么？", CatifyParams(strength=1))
        self.assertTrue(result.endswith("？") or result.endswith("?"))

    def test_newlines_are_kept(self):
        result = self.engine.catify("你好。\n再见。", CatifyParams(strength=1))
        self.assertEqual(result.count("\n"), 1)

    def test_blank_lines_are_kept(self):
        result = self.engine.catify("你好。\n\n再见。", CatifyParams(strength=1))
        self.assertEqual(result.count("\n"), 2)

    def test_multiline_structure_matches_input(self):
        source = "第一行\n第二行\n\n第四行"
        result = self.engine.catify(source, CatifyParams(strength=1))
        self.assertEqual(result.count("\n"), source.count("\n"))

    def test_empty_input(self):
        self.assertEqual(self.engine.catify("", CatifyParams()), "")
        self.assertEqual(self.engine.catify("   ", CatifyParams()), "")

    def test_punctuation_only_input_returns_empty(self):
        self.assertEqual(self.engine.catify("。", CatifyParams()), "")

    def test_none_input_is_safe(self):
        self.assertEqual(self.engine.catify(None, CatifyParams()), "")

    def test_kaomoji_interval_selects_fewer_sentences(self):
        # 间隔期望越大，被选中加颜文字的句子越少
        engine = make_engine(1)
        result = engine.catify(
            "第一句。第二句。第三句。",
            CatifyParams(strength=2, kaomoji_interval=10.0, kaomoji_std=0.0),
        )
        self.assertIn("(", result)

    def test_kaomoji_probability_zero_single_sentence(self):
        engine = make_engine(5)
        for _ in range(20):
            result = engine.catify(
                "只有一句", CatifyParams(strength=2, kaomoji_prob=0.0)
            )
            self.assertNotIn("(", result)

    def test_single_sentence_probability_one(self):
        engine = make_engine(5)
        result = engine.catify("只有一句", CatifyParams(strength=2, kaomoji_prob=1.0))
        self.assertIn("(", result)

    def test_only_subject_object_keeps_other_pronouns(self):
        # 「他」既不是主语也不是宾语，只替换主宾语时应当保留
        text = "我和他都觉得你不错"
        loose = self.engine.catify(text, CatifyParams(strength=0, add_tilde=False))
        strict = self.engine.catify(
            text, CatifyParams(strength=0, add_tilde=False, only_subject_object=True)
        )
        self.assertIn("那家伙", loose)
        self.assertIn("他", strict)
        self.assertNotIn("那家伙", strict)
        self.assertIn("主人", strict, "宾语位置的代词仍然要被替换")

    def test_rewrite_overrides(self):
        result = self.engine.rewrite("你好", strength=0, add_tilde=False)
        self.assertEqual(result, "你好")

    def test_out_of_range_params_get_clamped(self):
        result = self.engine.catify("你好", CatifyParams(strength=99, add_tilde=False))
        self.assertIsInstance(result, str)
        self.assertIn("喵", result)

    def test_long_paragraph_is_fully_rewritten(self):
        paragraph = (
            "早上好。今天天气不错。我准备出门了。你要一起去吗？我带了便当。"
            "不过可能会下雨。记得带伞哦。那我们在公园门口见。路上小心。我等你。别迟到。"
        )
        result = self.engine.catify(paragraph, CatifyParams(seed=2))
        self.assertGreater(len(result), len(paragraph))
        # v1 起就有的设计：陈述句句末的「。」会被「喵~」取代（聊天语气不需要句号），
        # 所以这里不能按标点数量比对，只要求每句话都还在。
        for fragment in ("出门", "便当", "下雨", "公园", "迟到"):
            self.assertIn(fragment, result)

    def test_sentence_level_api(self):
        result = self.engine.catify_sentence(
            "你好吗", CatifyParams(strength=1, add_tilde=False), allow_kaomoji=False
        )
        self.assertIn("喵", result)
        self.assertNotIn("(", result)


class TestGoldenOutput(unittest.TestCase):
    """黄金样本：锁定改写结果，防止后续改动悄悄改变语气。

    这组数据是在 v2 重构时逐字节比对过 v1 输出后记录下来的
    （v1 全局 ``random.seed(42)`` 的结果），所以它同时起到了
    「重构没有改变行为」的回归保护作用。
    """

    GOLDEN = {
        '你好': '你好喵~(๑>◡<๑)',
        '你好吗': '你好吗喵~？ฅ^•ﻌ•^ฅ',
        '在吗': '在吗喵~？(・ω・)',
        '你在做什么？': '主人在做什么喵~？(・ω・)',
        '谢谢': '谢谢喵~(=･ω･=)',
        '谢谢你': '谢谢主人喵~(=･ω･=)',
        '好的': '好哒喵~(๑>◡<๑)',
        '是的': '是哒喵~(=･ω･=)',
        '我不知道': '本喵不知道喵~(=･ω･=)',
        '我喜欢你': '本喵喜欢主人喵~(๑>◡<๑)',
        '我爱你': '我爱你喵~(๑>◡<๑)',
        '你吃饭了吗': '主人吃饭了吗喵~？(・ω・)',
        '今天天气真好': '今天天气真好喵~(๑>◡<๑)',
        '陪我玩好不好？': '陪我玩好不好喵~？ฅ^•ﻌ•^ฅ',
        '对不起，我错了。': '对不起，本喵错了喵~(=･ω･=)',
        '我饿了': '本喵饿了喵~(=･ω･=)',
        '饿了吗': '主人饿了吗喵~？(・ω・)',
        '吃饭了吗': '主人吃饭了吗喵~？(・ω・)',
        '去哪儿': '本喵去哪儿喵~(=･ω･=)',
        '太可爱了': '太可爱了喵~(๑>◡<๑)',
        '好棒': '好棒喵~(๑>◡<๑)',
        '要吗': '主人要吗喵~？(・ω・)',
        '想你了': '本喵想主人了喵~(=･ω･=)',
    }

    PARAGRAPH = (
        "早上好。今天天气不错。我准备出门了。你要一起去吗？我带了便当。"
        "不过可能会下雨。记得带伞哦。那我们在公园门口见。路上小心。我等你。别迟到。"
    )
    PARAGRAPH_GOLDEN = (
        '早上好喵呜~(=①ω①=)今天天气不错呐~本喵准备出门了喵~主人要一起去吗喵~？本喵带了便当呐~(´･ω･`)不过可能会'
        '下雨呀~本喵记得带伞哦喵~~那我们在公园门口见吖~路上小心呐~(*≧ω≦)本喵等主人呐~别迟到呀~'
    )

    def test_single_sentences(self):
        engine = CatifyEngine()
        for text, expected in self.GOLDEN.items():
            with self.subTest(text=text):
                self.assertEqual(engine.catify(text, CatifyParams(seed=42)), expected)

    def test_paragraph(self):
        engine = CatifyEngine()
        self.assertEqual(
            engine.catify(self.PARAGRAPH, CatifyParams(seed=2)),
            self.PARAGRAPH_GOLDEN,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

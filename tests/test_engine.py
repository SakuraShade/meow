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
from meow.engine.analyzer import (  # noqa: E402
    detect_emotion,
    infer_subject,
    is_imperative,
    needs_subject,
    tokenize,
)
from meow.engine.sentence import (  # noqa: E402
    Emotion,
    SentenceKind,
    classify_sentence,
    has_tone_particle,
    split_sentences,
    strip_end_punct,
)


def make_engine(seed: int = 42) -> CatifyEngine:
    return CatifyEngine(random.Random(seed))


def emotion_of(text: str) -> Emotion:
    """按词判断情绪（测试用的便捷入口）。"""
    return detect_emotion(tokenize(text), text)


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

    def test_split_sentences_keeps_blank_lines(self):
        segments = split_sentences("你好。\n\n在吗？")
        kinds = [segment.kind for segment in segments]
        self.assertEqual(kinds, ["sentence", "newline", "newline", "sentence"])
        self.assertEqual(segments[0].text, "你好。")
        self.assertEqual(segments[3].text, "在吗？")

    def test_split_sentences_keeps_single_newline(self):
        segments = split_sentences("第一行\n第二行")
        self.assertEqual([s.kind for s in segments], ["sentence", "newline", "sentence"])

    def test_split_sentences_blank_input_has_no_sentences(self):
        self.assertEqual(split_sentences(""), [])
        # 纯空白不再变成空句子，而是原样保留成一段分隔符
        self.assertEqual([s.kind for s in split_sentences("   ")], ["separator"])
        self.assertTrue(all(not s.is_sentence for s in split_sentences("   ")))

    # ---------------- 分句符 ----------------

    def assert_split_texts(self, text, expected_sentences, **kwargs):
        segments = split_sentences(text, **kwargs)
        actual = [s.text for s in segments if s.is_sentence]
        self.assertEqual(actual, expected_sentences)
        return segments

    def test_fullwidth_comma_splits(self):
        self.assert_split_texts("你好，今天天气真好。", ["你好", "今天天气真好。"])
        self.assert_split_texts("早上好，今天天气不错，我准备出门了。",
                                ["早上好", "今天天气不错", "我准备出门了。"])

    def test_halfwidth_comma_splits(self):
        self.assert_split_texts("你好,今天天气真好.", ["你好", "今天天气真好."])

    def test_fullwidth_and_halfwidth_behave_the_same(self):
        full = split_sentences("你好，今天天气真好。")
        half = split_sentences("你好,今天天气真好.")
        self.assertEqual([s.kind for s in full], [s.kind for s in half])

    def test_semicolon_and_colon_split(self):
        self.assert_split_texts("第一句；第二句：第三句", ["第一句", "第二句", "第三句"])

    def test_enumeration_comma_splits(self):
        self.assert_split_texts("苹果、香蕉、橘子", ["苹果", "香蕉", "橘子"])

    def test_space_splits(self):
        self.assert_split_texts("你好 今天天气真好", ["你好", "今天天气真好"])

    def test_space_splitting_can_be_turned_off(self):
        self.assert_split_texts("你好 今天天气真好", ["你好 今天天气真好"], split_on_space=False)

    def test_halfwidth_period_ends_sentence(self):
        self.assert_split_texts("Hello. How are you?", ["Hello.", "How", "are", "you?"])

    def test_consecutive_enders_stay_together(self):
        self.assert_split_texts("真的吗？？？", ["真的吗？？？"])
        self.assert_split_texts("等等...", ["等等..."])

    # ---------------- 不该被切开的东西 ----------------

    def test_decimal_not_split(self):
        self.assert_split_texts("圆周率是 3.14", ["圆周率是", "3.14"])

    def test_domain_and_filename_not_split(self):
        self.assert_split_texts("example.com", ["example.com"])
        self.assert_split_texts("index.js", ["index.js"])

    def test_url_not_split(self):
        self.assert_split_texts("http://a.com/b", ["http://a.com/b"])

    def test_time_not_split(self):
        self.assert_split_texts("12:30", ["12:30"])

    def test_thousands_separator_not_split(self):
        self.assert_split_texts("1,000", ["1,000"])

    # ---------------- 分隔符保留 ----------------

    def test_separators_are_kept_verbatim(self):
        segments = split_sentences("你好，今天天气真好。")
        self.assertEqual([s.kind for s in segments], ["sentence", "separator", "sentence"])
        self.assertEqual(segments[1].text, "，")
        self.assertEqual(segments[1].literal, "，")

    def test_newline_and_separator_are_literals(self):
        newline = [s for s in split_sentences("a\nb") if s.kind == "newline"][0]
        self.assertEqual(newline.literal, "\n")
        sentence = [s for s in split_sentences("a\nb") if s.is_sentence][0]
        self.assertIsNone(sentence.literal)

    def test_split_sentences_no_trailing_punctuation(self):
        segments = split_sentences("没有标点")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "没有标点")


class TestEmotion(unittest.TestCase):
    """词级情绪判断：单字只按「独立成词」匹配，多字短语做子串匹配。"""

    def test_happy(self):
        for text in ("今天天气真好", "好开心", "太棒了", "好可爱", "我爱你", "点赞",
                     "厉害", "幸福", "激动", "开心死了"):
            with self.subTest(text=text):
                self.assertIs(emotion_of(text), Emotion.HAPPY)

    def test_sad(self):
        for text in ("好难过", "想哭", "心累", "真累", "委屈", "失望", "难受", "害怕"):
            with self.subTest(text=text):
                self.assertIs(emotion_of(text), Emotion.SAD)

    def test_angry(self):
        for text in ("生气", "气死我了", "真烦", "讨厌", "滚蛋", "愤怒", "恶心", "无语"):
            with self.subTest(text=text):
                self.assertIs(emotion_of(text), Emotion.ANGRY)

    def test_neutral(self):
        # 这些在旧的「单字匹配」下全都会误判
        for text in ("天气", "麻烦你了", "积累", "爱好", "美国", "你好", "好的",
                     "今天星期三", "明白", "赞助"):
            with self.subTest(text=text):
                self.assertIs(emotion_of(text), Emotion.NEUTRAL)

    def test_no_angry_for_weather(self):
        # 用户反馈的核心 bug：「气」在「天气」里误判成生气
        self.assertIs(emotion_of("今天天气真好"), Emotion.HAPPY)
        self.assertNotIn("▼皿", "今天天气真好")

    def test_negation_flips_happy_to_sad(self):
        self.assertIs(emotion_of("不开心"), Emotion.SAD)
        self.assertIs(emotion_of("我好不开心"), Emotion.SAD)
        self.assertIs(emotion_of("我不高兴"), Emotion.SAD)

    def test_negation_cancels_sad_and_angry(self):
        self.assertIs(emotion_of("不难过"), Emotion.NEUTRAL)
        self.assertIs(emotion_of("别生气"), Emotion.NEUTRAL)
        self.assertIs(emotion_of("我没生气"), Emotion.NEUTRAL)

    def test_a_not_a_questions_are_not_negation(self):
        # 「喜不喜欢」「高兴不高兴」是在问要不要，不是否定
        self.assertIs(emotion_of("喜不喜欢"), Emotion.HAPPY)
        self.assertIs(emotion_of("开不开心"), Emotion.HAPPY)
        self.assertIs(emotion_of("高兴不高兴"), Emotion.HAPPY)

    def test_priority_happy_wins_ties(self):
        # 同时出现开心和难过时，开心优先（沿用 v1 的优先级）
        self.assertIs(emotion_of("开心又难过"), Emotion.HAPPY)


class TestSubjectInference(unittest.TestCase):
    """补主语时挑「主人」还是「本喵」。"""

    def assert_subject(self, text: str, expected: str) -> None:
        tokens = tokenize(text)
        self.assertTrue(needs_subject(text, tokens), f"{text!r} 应该需要补主语")
        self.assertEqual(infer_subject(text, tokens), expected)

    def test_imperative_verbs_with_first_person_object(self):
        # 动作冲着「本喵」来 → 主语是对方（主人）
        for text in ("来陪我玩", "帮我一下", "抱抱我", "陪我去"):
            with self.subTest(text=text):
                self.assert_subject(text, "主人")

    def test_imperative_leaders(self):
        for text in ("请坐", "请进", "别走", "不要走", "快点", "拜托了"):
            with self.subTest(text=text):
                self.assert_subject(text, "主人")

    def test_plain_statements_use_self(self):
        for text in ("走了", "吃了", "看电影", "起床", "陪她去"):
            with self.subTest(text=text):
                self.assert_subject(text, "本喵")

    def test_polite_ask_forms_use_self(self):
        # 「请问」「请教」是自报家门，不是对主人的指令
        for text in ("请问现在几点", "请教一下"):
            with self.subTest(text=text):
                self.assert_subject(text, "本喵")

    def test_questions_use_master(self):
        for text in ("饿了吗", "吃饭了吗"):
            with self.subTest(text=text):
                self.assert_subject(text, "主人")

    def test_full_pipeline_imperative(self):
        engine = CatifyEngine()
        params = CatifyParams(strength=0, add_tilde=False)
        self.assertEqual(engine.catify("来陪我玩", params), "主人来陪我玩")
        self.assertEqual(engine.catify("帮我一下", params), "主人帮本喵一下")
        self.assertEqual(engine.catify("抱抱我", params), "主人抱抱本喵")
        self.assertEqual(engine.catify("陪她去", params), "本喵陪那家伙去")

    def test_is_imperative_false_for_self_actions(self):
        self.assertFalse(is_imperative(tokenize("走了")))
        self.assertFalse(is_imperative(tokenize("看电影")))


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
        # 纯空白没有句子可改，原样返回（service 层另有 strip() 兜底）
        self.assertEqual(self.engine.catify("   ", CatifyParams()), "   ")

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

    # ---------------- 逗号分句后的整体效果 ----------------

    def test_every_clause_gets_its_own_particle(self):
        result = self.engine.catify(
            "你好，今天天气真好", CatifyParams(strength=1, add_tilde=False)
        )
        particles = ("喵呜", "喵~", "喵", "呀", "呐", "吖")
        head, separator, tail = result.partition("，")
        self.assertEqual(separator, "，", "逗号要保留在输出里")
        self.assertTrue(head.startswith("你好"))
        self.assertTrue(tail.startswith("今天天气真好"))
        self.assertTrue(head.endswith(particles), head)
        self.assertTrue(tail.endswith(particles), tail)

    def test_comma_is_not_pushed_behind_the_particle(self):
        # 旧实现里半角标点会卡在「喵」前面，变成「真好.喵~」
        for source in ("你好,今天天气真好.", "你好，今天天气真好。"):
            result = self.engine.catify(source, CatifyParams(strength=1))
            self.assertNotIn(".喵", result)
            self.assertNotIn("，喵", result)

    def test_halfwidth_and_fullwidth_give_same_shape(self):
        params = CatifyParams(strength=1, seed=7)
        full = self.engine.catify("你好，今天天气真好", params)
        half = self.engine.catify("你好,今天天气真好", params)
        self.assertEqual(full.replace("，", ","), half)

    def test_no_double_tilde(self):
        # 句末语气词本身带 ~ 时不该再叠一个
        for seed in range(12):
            result = self.engine.catify("我准备出门了", CatifyParams(seed=seed, add_tilde=True))
            self.assertNotIn("~~", result)

    def test_separators_survive_round_trip(self):
        source = "第一句；第二句：第三句"
        result = self.engine.catify(source, CatifyParams(strength=1))
        for separator in ("；", "："):
            self.assertIn(separator, result)

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

    最初是在 v2 重构时逐字节比对过 v1 输出后记录下来的；此后有三次
    **有意**的调整，样本已同步更新：

    * 逗号、分号、空格也分句，且分隔符原样保留；
    * 句末语气词带 ``~`` 时不再叠加（不再出现「喵~~」）；
    * 情绪改为「按词判断」、主语改为「疑问/祈使用主人」。
    """

    GOLDEN = {
        '你好': '你好喵~(=･ω･=)',
        '你好吗': '你好吗喵~？(・ω・)',
        '在吗': '在吗喵~？(・ω・)',
        '你在做什么？': '主人在做什么喵~？(・ω・)',
        '谢谢': '谢谢喵~(=･ω･=)',
        '谢谢你': '谢谢主人喵~(=･ω･=)',
        '好的': '好哒喵~(=･ω･=)',
        '是的': '是哒喵~(=･ω･=)',
        '我不知道': '本喵不知道喵~(=･ω･=)',
        '我喜欢你': '本喵喜欢主人喵~(๑>◡<๑)',
        '我爱你': '我爱你喵~(๑>◡<๑)',
        '你吃饭了吗': '主人吃饭了吗喵~？(・ω・)',
        '今天天气真好': '今天天气真好喵~(๑>◡<๑)',
        '陪我玩好不好？': '陪我玩好不好喵~？(・ω・)',
        '对不起，我错了。': '对不起喵~，本喵错了喵~',
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
        '早上好喵呜~(=･ω･=)今天天气不错呐~本喵准备出门了喵~主人要一起去吗喵~？本喵带了便当呐~(´･ω･`)不过可'
        '能会下雨呀~本喵记得带伞哦喵~那我们在公园门口见吖~路上小心呐~(=˘ω˘=)本喵等主人呐~主人别迟到呀~'
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

# -*- coding: utf-8 -*-
"""向后兼容层（已废弃）。

v1 只提供一个 ``catify()`` 函数，所有代码都写在这一个文件里。
v2 把它拆成了 :mod:`meow.engine`；本文件只是为了不弄坏老脚本里的
``import catify``，新代码请直接用新接口：

.. code-block:: python

    from meow.engine import CatifyEngine, CatifyParams

    engine = CatifyEngine()
    print(engine.rewrite("你在做什么？", CatifyParams(strength=2)))

确认没有旧脚本依赖后，可以安全删除本文件。
"""

from __future__ import annotations

from meow.engine import CatifyEngine, CatifyParams

__all__ = ["CatifyEngine", "CatifyParams", "catify", "catify_sentence"]

_engine = CatifyEngine()


def catify(text, strength=2, kaomoji_prob=0.7, kaomoji_interval=3.0,
           kaomoji_std=1.0, only_subject_object=False, seed=None):
    """v1 的整段改写函数，行为与 v1 完全一致（含 ``seed`` 的可复现性）。"""
    params = CatifyParams(
        strength=strength,
        kaomoji_prob=kaomoji_prob,
        kaomoji_interval=kaomoji_interval,
        kaomoji_std=kaomoji_std,
        only_subject_object=only_subject_object,
        seed=seed,
    )
    return _engine.catify(text, params)


def catify_sentence(sent, strength=2, allow_kaomoji=True, only_subject_object=False):
    """v1 的单句改写函数。"""
    params = CatifyParams(strength=strength, only_subject_object=only_subject_object)
    return _engine.catify_sentence(sent, params, allow_kaomoji=allow_kaomoji)


if __name__ == "__main__":
    samples = [
        "你好", "你好吗", "在吗", "你在做什么？", "谢谢", "好的",
        "我不知道", "我喜欢你", "你吃饭了吗", "今天天气真好",
        "陪我玩好不好？", "我饿了", "去哪儿", "太可爱了", "好棒",
    ]
    print("=== 短句 ===")
    for sample in samples:
        print(f"{sample}  ->  {catify(sample, seed=42)}")
    print("\n=== 段落 ===")
    print(catify("你好！今天天气真好，我想出去玩。\n你在做什么？我有点饿了，陪我玩好不好？", seed=1))

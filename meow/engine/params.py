"""猫化参数：引擎的输入契约。

放在 engine 里而不是 config 里，是为了让 ``meow.engine`` 完全独立
（config 依赖 engine，而不是反过来）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

# 语气强度
STRENGTH_MIN = 0
STRENGTH_MAX = 2
STRENGTH_DEFAULT = 2

STRENGTH_LABELS: dict[int, str] = {
    0: "仅替换用词（不加喵）",
    1: "轻度（句末加喵）",
    2: "标准（加喵 + 颜文字）",
}

# 参数取值范围，UI 与配置校验共用同一份定义
KAOMOJI_PROB_RANGE = (0.0, 1.0)
KAOMOJI_INTERVAL_RANGE = (1.0, 10.0)
KAOMOJI_STD_RANGE = (0.0, 3.0)


def clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    """尽力把任意输入转成 ``[lo, hi]`` 内的 float，失败则回退默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(hi, max(lo, number))


def clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, number))


def clamp_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "是", "开"}:
            return True
        if lowered in {"0", "false", "no", "off", "否", "关"}:
            return False
    return default


@dataclass
class CatifyParams:
    """一次猫化改写用到的全部参数。"""

    strength: int = STRENGTH_DEFAULT
    kaomoji_prob: float = 0.7        # 单句时加颜文字的概率
    kaomoji_interval: float = 3.0    # 多句时颜文字间隔的期望（正态分布均值）
    kaomoji_std: float = 1.0         # 间隔的标准差
    only_subject_object: bool = False  # 只替换主语/宾语位置的代词
    add_tilde: bool = True           # 句末追加 "~"
    split_on_space: bool = True      # 空格也当作分句符（关掉可保住英文句子）
    seed: int | None = None          # 固定随机种子（调试/复现用）

    def clamp(self) -> "CatifyParams":
        """把每个字段收进合法范围，返回新对象。"""
        return replace(
            self,
            strength=clamp_int(self.strength, STRENGTH_DEFAULT, STRENGTH_MIN, STRENGTH_MAX),
            kaomoji_prob=clamp_float(self.kaomoji_prob, 0.7, *KAOMOJI_PROB_RANGE),
            kaomoji_interval=clamp_float(self.kaomoji_interval, 3.0, *KAOMOJI_INTERVAL_RANGE),
            kaomoji_std=clamp_float(self.kaomoji_std, 1.0, *KAOMOJI_STD_RANGE),
            only_subject_object=clamp_bool(self.only_subject_object, False),
            add_tilde=clamp_bool(self.add_tilde, True),
            split_on_space=clamp_bool(self.split_on_space, True),
            seed=None if self.seed is None else clamp_int(self.seed, 0, 0, 2**31 - 1),
        )

    @classmethod
    def from_dict(cls, data: Any) -> "CatifyParams":
        """从（可能损坏的）字典构造，任何字段缺失/类型错误都会回退默认值。"""
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        return cls(
            strength=clamp_int(data.get("strength"), defaults.strength, STRENGTH_MIN, STRENGTH_MAX),
            kaomoji_prob=clamp_float(data.get("kaomoji_prob"), defaults.kaomoji_prob, *KAOMOJI_PROB_RANGE),
            kaomoji_interval=clamp_float(data.get("kaomoji_interval"), defaults.kaomoji_interval, *KAOMOJI_INTERVAL_RANGE),
            kaomoji_std=clamp_float(data.get("kaomoji_std"), defaults.kaomoji_std, *KAOMOJI_STD_RANGE),
            only_subject_object=clamp_bool(data.get("only_subject_object"), defaults.only_subject_object),
            add_tilde=clamp_bool(data.get("add_tilde"), defaults.add_tilde),
            split_on_space=clamp_bool(data.get("split_on_space"), defaults.split_on_space),
            seed=None if data.get("seed") is None else clamp_int(data.get("seed"), 0, 0, 2**31 - 1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strength": self.strength,
            "kaomoji_prob": self.kaomoji_prob,
            "kaomoji_interval": self.kaomoji_interval,
            "kaomoji_std": self.kaomoji_std,
            "only_subject_object": self.only_subject_object,
            "add_tilde": self.add_tilde,
            "split_on_space": self.split_on_space,
            "seed": self.seed,
        }

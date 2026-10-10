# catify.py
import re
import math
import random
import jieba.posseg as pseg


# ==================== 词典 ====================

PRONOUN_MAP = {
    "你": "主人", "您": "主人", "你们": "主人们",
    "我": "本喵", "我们": "我们",
    "咱": "我们", "咱们": "我们",
    "他": "那家伙", "她": "那家伙",
}

PHRASE_MAP = {
    "好的": "好哒",
    "是的": "是哒",
    "对的": "对哒",
    "不行": "不行啦",
    "没有": "没有啦",
    "知道了": "知道了啦",
    "没问题": "没问题哒",
}

NO_SUBJECT_PHRASES = {
    "好", "好的", "好哒", "好呀", "好吧", "好呢", "好嘞",
    "嗯", "嗯嗯", "哦", "噢", "喔", "诶", "哎", "啊",
    "是", "是的", "是哒", "对", "对的", "对哒", "行", "可以",
    "没问题", "没问题哒", "收到", "知道了", "知道了啦",
    "明白", "明白了", "懂了", "了解",
    "是啊", "是吧", "对吗", "对吧",
    "你好", "您好", "再见", "拜拜", "晚安", "早安", "午安",
    "早上好", "中午好", "下午好", "晚上好", "早早",
    "谢谢", "谢谢你", "感谢", "感谢你", "辛苦了",
    "不客气", "没关系", "对不起", "抱歉",
    "好棒", "好可爱", "太棒了", "太可爱了", "厉害", "真好", "妙啊",
    "哈哈", "呵呵", "嘿嘿", "嘻嘻",
}

TONE_PARTICLES = set("吗呢吧啊呀哦嘛啦哟喂哈唉呗咧咯喽哒了喔")

MEOW_STATEMENT      = ["喵", "喵~", "喵呜", "呀", "呐", "吖"]
MEOW_Q_NO_PARTICLE  = ["喵", "呀", "吖"]
MEOW_EX_NO_PARTICLE = ["喵", "喵~", "吖"]
MEOW_WITH_PARTICLE  = ["喵", "喵~"]

# 扩展颜文字库
KAOMOJI = {
    "happy": [
        "o( =∩ω∩= )m", "(=^･ω･^=)", "(*^ω^*)", "ฅ^•ﻌ•^ฅ", "(=①ω①=)",
        "(*≧ω≦)", "(๑˃ᴗ˂)ﻭ", "ᕦ(òωóˇ)ᕤ", "(◕‿◕✿)", "(★ω★)",
        "(≧◡≦)", "(๑>◡<๑)", "(๑´ㅂ`๑)", "(=^‥^=)", "(◍•ᴗ•◍)",
    ],
    "sad": [
        "(=；ω；=)", "(´；ω；`)", "(｡•́︿•̀｡)", "(இ﹏இ`｡)",
        "(｡╯︵╰｡)", "(ㄒoㄒ)", "(´-ω-`)", "(｡•́︿•̀｡)",
    ],
    "angry": [
        "(=｀ω´=)", "(#`Д´)", "(҂`_´)", "(▼皿▼#)", "(｀Д´)",
    ],
    "question": [
        "(=･ω･=)?", "ฅ(•ω•ฅ)", "(◔_◔)", "(・∀・)?", "(?・ω・)",
        "(°ω°)?", "ฅ(^•ω•^ฅ)?",
    ],
    "neutral": [
        "(=￣ω￣=)", "(=①ω①=)", "(´･ω･`)", "(・ω・)", "(=･ω･=)",
        "(=˘ω˘=)", "(*・ω・)", "(・∀・)",
    ],
}

HAPPY_CHARS = set("好棒喜欢爱开心高兴哈哈嘿美可爱")
SAD_CHARS   = set("难过伤心哭累痛悲苦")
ANGRY_CHARS = set("生气讨厌烦滚怒恨")


# ==================== 工具 ====================

def strip_end_punct(s):
    return re.sub(r'[。！？!?…~～\s]+$', '', s).strip()


def has_tone_particle(sent):
    body = strip_end_punct(sent)
    return bool(body) and body[-1] in TONE_PARTICLES


def classify_sentence(sent):
    s = sent.rstrip()
    if s.endswith(("吗", "呢", "吧")) or re.search(r'[?？]$', s):
        return "question"
    if re.search(r'[!！]$', s):
        return "exclaim"
    return "statement"


def classify_emotion(sent):
    if any(c in HAPPY_CHARS for c in sent):
        return "happy"
    if any(c in SAD_CHARS for c in sent):
        return "sad"
    if any(c in ANGRY_CHARS for c in sent):
        return "angry"
    return "neutral"


def needs_subject(sent):
    body = strip_end_punct(sent)
    if not body:
        return False
    if body in NO_SUBJECT_PHRASES:
        return False
    for k, v in PHRASE_MAP.items():
        if body == k or body == v:
            return False
    words = list(pseg.cut(body))
    if not words:
        return False
    first_flag = words[0].flag
    if first_flag.startswith(("r", "n", "nr", "ns", "nt", "nz", "nh")):
        return False
    return first_flag.startswith(("v", "a"))


def add_subject(sent):
    stype = classify_sentence(sent)
    subj = "主人" if stype == "question" else "本喵"
    return subj + sent


def classify_roles(words):
    verb_idx = None
    for i, pair in enumerate(words):
        if pair.flag.startswith("v"):
            verb_idx = i
            break
    subj_idx = None
    obj_idx = None
    if verb_idx is not None:
        for i in range(verb_idx):
            if words[i].flag.startswith("r"):
                subj_idx = i
                break
        for i in range(verb_idx + 1, len(words)):
            if words[i].flag.startswith("r"):
                obj_idx = i
                break
    else:
        for i, pair in enumerate(words):
            if pair.flag.startswith("r"):
                subj_idx = i
                break
    return subj_idx, verb_idx, obj_idx


def replace_pronouns(words, only_subject_object=False):
    subj_idx, _, obj_idx = classify_roles(words)
    out = []
    for i, pair in enumerate(words):
        w, flag = pair.word, pair.flag
        if flag.startswith("r") and w in PRONOUN_MAP:
            if only_subject_object:
                if i == subj_idx or i == obj_idx:
                    out.append(PRONOUN_MAP[w])
                else:
                    out.append(w)
            else:
                out.append(PRONOUN_MAP[w])
        else:
            out.append(w)
    return out


def split_sentences(text):
    result = []
    for para in text.split("\n"):
        if not para.strip():
            result.append(("newline", ""))
            continue
        parts = re.findall(r'[^。！？!?…]+[。！？!?…]*', para)
        for p in parts:
            if p.strip():
                result.append(("sentence", p))
    return result


# ==================== 单句改写 ====================

def catify_sentence(sent, strength=2, allow_kaomoji=True,
                    only_subject_object=False):
    # 1. 短语替换
    for k, v in PHRASE_MAP.items():
        sent = sent.replace(k, v)

    # 2. 补主语
    if needs_subject(sent):
        sent = add_subject(sent)

    # 3. 剥句末标点
    m = re.search(r'([。！？!?…~～]+)$', sent)
    body = sent[:-len(m.group(1))] if m else sent
    body = body.strip()
    if not body:
        return ""

    # 4. 分词 + 代词替换
    words = list(pseg.cut(body))
    words = replace_pronouns(words, only_subject_object=only_subject_object)
    body = "".join(words)

    stype = classify_sentence(sent)
    emo = classify_emotion(sent)
    has_particle = has_tone_particle(body)

    # 5. 句末语气词（已有语气助词 -> 只加喵）
    if strength >= 1:
        if stype == "question":
            body += random.choice(
                MEOW_WITH_PARTICLE if has_particle else MEOW_Q_NO_PARTICLE
            )
        elif stype == "exclaim":
            body += random.choice(
                MEOW_WITH_PARTICLE if has_particle else MEOW_EX_NO_PARTICLE
            )
        else:
            body += random.choice(
                MEOW_WITH_PARTICLE if has_particle else MEOW_STATEMENT
            )

    # 6. 波浪号 ~
    body += "~"

    # 7. 标点符号
    if stype == "question":
        body += "？"
    elif stype == "exclaim":
        body += "！"
    else:
        body += ""

    # 8. 颜文字（可选）
    if strength >= 2 and allow_kaomoji:
        key = emo if emo in KAOMOJI else "neutral"
        if stype == "question" and random.random() < 0.5:
            key = "question"
        body += random.choice(KAOMOJI[key])

    return body


# ==================== 整段改写 ====================

def catify(text, strength=2,
           kaomoji_prob=0.7,        # 单句时添加颜文字的概率
           kaomoji_interval=3.0,    # 多句时颜文字间隔的期望值（正态分布均值）
           kaomoji_std=1.0,         # 间隔的标准差
           only_subject_object=False, seed=None):
    """
    颜文字分布策略：
    - 单句：以 kaomoji_prob 概率添加
    - 多句：间隔服从 N(kaomoji_interval, kaomoji_std)，天然产生"某处密集、某处稀疏"的自然感
    """
    if seed is not None:
        random.seed(seed)

    sentences = split_sentences(text)
    sent_indices = [i for i, (kind, _) in enumerate(sentences) if kind == "sentence"]
    total = len(sent_indices)

    # 预先决定哪些句子加颜文字
    kaomoji_set = set()
    if strength >= 2 and total > 0:
        if total == 1:
            if random.random() < kaomoji_prob:
                kaomoji_set.add(sent_indices[0])
        else:
            # 从 [0, interval) 中随机起点，避免总是第一句
            idx = random.randint(0, max(1, int(kaomoji_interval) - 1))
            while idx < total:
                kaomoji_set.add(sent_indices[idx])
                # 采样下一个间隔，按正态分布
                step = max(1, round(random.gauss(kaomoji_interval, kaomoji_std)))
                idx += step

    out = []
    for i, (kind, s) in enumerate(sentences):
        if kind == "newline":
            out.append("")
            continue
        out.append(catify_sentence(
            s, strength=strength,
            allow_kaomoji=(i in kaomoji_set),
            only_subject_object=only_subject_object,
        ))

    result = ""
    for i, (kind, s) in enumerate(sentences):
        if kind == "newline":
            result += "\n"
        else:
            result += out[i]
    return result


# ==================== 测试 ====================

if __name__ == "__main__":
    print("=== 短句 ===")
    tests = [
        "你好", "你好吗", "在吗", "你在做什么？", "谢谢", "谢谢你",
        "好的", "是的", "我不知道", "我喜欢你", "我爱你",
        "你吃饭了吗", "今天天气真好", "陪我玩好不好？",
        "对不起，我错了。", "我饿了", "饿了吗", "吃饭了吗",
        "去哪儿", "太可爱了", "好棒", "要吗", "想你了",
    ]
    for t in tests:
        print(f"{t}  ->  {catify(t, seed=42)}")

    print("\n=== 长句 / 段落（观察颜文字正态分布）===")
    para = """你好！今天天气真好，我想出去玩。
你在做什么？我有点饿了，陪我玩好不好？"""
    print(catify(para, seed=1))

    print("\n=== 长段落，观察颜文字节奏 ===")
    long_para = (
        "早上好。今天天气不错。我准备出门了。"
        "你要一起去吗？我带了便当。"
        "不过可能会下雨。记得带伞哦。"
        "那我们在公园门口见。路上小心。"
        "我等你。别迟到。"
    )
    for s in range(3):
        print(f"--- seed={s} ---")
        print(catify(long_para, seed=s))
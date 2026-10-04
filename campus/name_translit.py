#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人名音译：中文姓名 → 俄语音译（西里尔转写）

设计取舍（README 里也写明了，避免被误认为"官方译法"）：

  汉字 → 拼音 这一步需要上万条字典，本项目坚持"离线、零依赖"，
  所以走三条路，准确性递减、但都可追溯：

    1) 已登记人名：直接查 names_zh_ru.csv，取人工确认的定译 —— 最准，优先使用；
    2) 姓名用字在内置迷你拼音表内：自动拼出拼音 → 按规则转写成西里尔；
    3) 其余情况：原样保留汉字并标记【待人工核对】，绝不用机器结果冒充定译。

  俄语教师姓名（本身已是西里尔字母）一律保留原文，不做任何转写。

用法：
    python name_translit.py --name 王明
    python name_translit.py --name 李娜 --pinyin "li na"
"""

import argparse
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES_PATH = os.path.join(HERE, "names_zh_ru.csv")

# 内置迷你拼音表：常见姓氏 + 常用名字用字（可继续往里加，也可改用外部词典）
MINI_PINYIN = {
    # 常见姓氏
    "王": "wang", "李": "li", "张": "zhang", "刘": "liu", "陈": "chen",
    "杨": "yang", "黄": "huang", "赵": "zhao", "吴": "wu", "周": "zhou",
    "徐": "xu", "孙": "sun", "马": "ma", "朱": "zhu", "胡": "hu",
    "郭": "guo", "何": "he", "高": "gao", "林": "lin", "罗": "luo",
    "郑": "zheng", "梁": "liang", "谢": "xie", "宋": "song", "唐": "tang",
    "许": "xu", "韩": "han", "冯": "feng", "邓": "deng", "曹": "cao",
    "彭": "peng", "曾": "zeng", "肖": "xiao", "田": "tian", "董": "dong",
    "袁": "yuan", "潘": "pan", "蒋": "jiang", "蔡": "cai", "余": "yu",
    "杜": "du", "叶": "ye", "程": "cheng", "苏": "su", "魏": "wei",
    "吕": "lü", "丁": "ding", "任": "ren", "沈": "shen", "姚": "yao",
    "卢": "lu", "姜": "jiang", "崔": "cui", "钟": "zhong", "谭": "tan",
    "陆": "lu", "汪": "wang", "范": "fan", "金": "jin", "石": "shi", "于": "yu",
    # 常用名字用字
    "明": "ming", "伟": "wei", "芳": "fang", "娜": "na", "秀": "xiu",
    "英": "ying", "华": "hua", "丽": "li", "强": "qiang", "军": "jun",
    "磊": "lei", "洋": "yang", "勇": "yong", "艳": "yan", "杰": "jie",
    "娟": "juan", "涛": "tao", "超": "chao", "秀兰": "xiu", "霞": "xia",
    "平": "ping", "刚": "gang", "桂": "gui", "文": "wen", "辉": "hui",
    "丹": "dan", "琳": "lin", "雪": "xue", "婷": "ting", "宇": "yu",
    "浩": "hao", "博": "bo", "硕": "shuo", "晨": "chen", "阳": "yang",
    "静": "jing", "敏": "min", "洁": "jie", "睿": "rui", "欣": "xin",
}

# 声母 → 西里尔（参考帕拉季/ГОСТ 体系的常见写法）
INITIAL_MAP = {
    "b": "б", "p": "п", "m": "м", "f": "ф", "d": "д", "t": "т",
    "n": "н", "l": "л", "g": "г", "k": "к", "h": "х",
    "j": "цз", "q": "ц", "x": "с",
    "zh": "чж", "ch": "ч", "sh": "ш", "r": "ж",
    "z": "цз", "c": "ц", "s": "с",
}

# 韵母 → 西里尔（按长度降序匹配，保证 iong 先于 ong 命中）
FINAL_MAP = [
    ("iang", "ян"), ("iong", "юн"), ("uang", "уан"), ("ueng", "ун"),
    ("ian", "янь"), ("iao", "яо"), ("ing", "ин"), ("uai", "уай"),
    ("uan", "уань"), ("ang", "ан"), ("eng", "эн"), ("ong", "ун"),
    ("ai", "ай"), ("ao", "ао"), ("ei", "эй"), ("er", "эр"),
    ("ia", "я"), ("ie", "е"), ("iu", "ю"), ("in", "инь"),
    ("ua", "уа"), ("uo", "о"), ("ui", "уй"), ("un", "унь"),
    ("ou", "оу"), ("an", "ань"), ("en", "энь"),
    ("üe", "юэ"), ("üan", "юань"), ("ün", "юнь"), ("ü", "юй"),
    ("a", "а"), ("o", "о"), ("e", "э"), ("i", "и"), ("u", "у"),
]

# 零声母 y- 还原成对应的 i/ü 韵母：yang → iang、yu → ü
Y_FINALS = {
    "a": "ia", "an": "ian", "ang": "iang", "ao": "iao", "e": "ie",
    "i": "i", "in": "in", "ing": "ing", "ong": "iong", "ou": "iu",
    "u": "ü", "uan": "üan", "ue": "üe", "un": "ün",
}

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]+")


def is_cyrillic(text):
    """判断姓名是否已经是西里尔字母（俄语教师姓名应保留原文）。"""
    return bool(CYRILLIC_RE.search(text))


def pinyin_to_cyrillic(syllable):
    """单个拼音音节 → 西里尔转写。zh/ch/sh 等双字母声母优先。"""
    s = syllable.strip().lower().replace("v", "ü")
    if not s:
        return ""
    for initial in ("zh", "ch", "sh"):
        if s.startswith(initial):
            return INITIAL_MAP[initial] + _final_to_cyrillic(s[len(initial):])
    if s[0] in INITIAL_MAP:
        return INITIAL_MAP[s[0]] + _final_to_cyrillic(s[1:])
    # 零声母 w-：王 wang → Ван、伟 wei → Вэй（wu 单独处理）
    if s[0] == "w":
        rest = s[1:] or s
        if rest == "u":
            return "у"
        return "в" + _final_to_cyrillic(rest)
    # 零声母 y-：先还原成对应的 i/ü 韵母（yang → iang → ян）
    if s[0] == "y":
        rest = s[1:] or s
        return _final_to_cyrillic(Y_FINALS.get(rest, rest))
    return _final_to_cyrillic(s)


def _final_to_cyrillic(final):
    for key, val in FINAL_MAP:
        if final == key:
            return val
    return final  # 兜底：原样返回，避免静默出错


def to_pinyin(chinese):
    """汉字 → 拼音（基于内置迷你表）。返回 (拼音串, 未识别的汉字列表)。"""
    syllables, unknown = [], []
    for ch in chinese:
        if ch in MINI_PINYIN:
            syllables.append(MINI_PINYIN[ch])
        else:
            unknown.append(ch)
    return " ".join(syllables), unknown


def load_names(path=NAMES_PATH):
    """读取人工登记的人名定译表，返回 {中文姓名: 俄语定译}。"""
    table = {}
    if not os.path.exists(path):
        return table
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            zh, ru = (row.get("zh") or "").strip(), (row.get("ru") or "").strip()
            if zh and ru:
                table[zh] = ru
    return table


def transliterate(name, registered=None, pinyin=None):
    """
    姓名 → 俄语音译。

    返回 (俄语写法, 来源说明)；来源可能是：
      原文保留 / 人工定译 / 规则转写 / 待人工核对
    """
    registered = registered or load_names()
    if is_cyrillic(name):
        return name, "俄文原文保留"
    if name in registered:
        return registered[name], "人工定译"
    pinyin = pinyin or to_pinyin(name)[0]
    unknown = to_pinyin(name)[1]
    if not pinyin:
        return name, "待人工核对（迷你拼音表未收录）"
    # 俄文姓名各部分首字母大写
    cyr = " ".join(
        (part[:1].upper() + part[1:]) if part else part
        for part in (pinyin_to_cyrillic(s) for s in pinyin.split())
    )
    if unknown:
        return cyr, "规则转写，含未收录用字 %s，建议人工核对" % "".join(unknown)
    return cyr, "规则转写"


def main():
    parser = argparse.ArgumentParser(description="中文姓名 → 俄语音译")
    parser.add_argument("--name", required=True, help="要转写的中文姓名")
    parser.add_argument("--pinyin", default=None, help="可选：直接给出拼音，如 'wang ming'")
    args = parser.parse_args()

    ru, source = transliterate(args.name, pinyin=args.pinyin)
    print(f"  中文：{args.name}\n  俄文：{ru}\n  来源：{source}")


if __name__ == "__main__":
    main()

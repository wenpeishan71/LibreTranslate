#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园术语预检演示脚本（LibreTranslate 校园版）

解决的问题：
  LibreTranslate 直接翻译校园通知时，课程术语、缩写、课程编号、人名经常翻错。
  本脚本在翻译前先查术语表，把这些"容易翻错的内容"保护起来，
  只让翻译引擎处理普通句子，翻译完成后再把术语回填成术语表里的标准译法。

流程：原文 → ①术语预检 → ②LibreTranslate 翻译 → ③术语回填 → ④中俄对照输出

用法（本机已部署 LibreTranslate 时）：
  python glossary_precheck.py --text "本学期《计量经济学》期末考试于 MT-101 教室举行，请携带学生证。"

不连接后端时可用 --dry-run 只查看术语命中与保护结果，不实际调用翻译。
"""

import argparse
import csv
import json
import os
import re
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GLOSSARY_PATH = os.path.join(HERE, "terminology_zh_ru.csv")

# 术语占位符：形如 ⟦0⟧ ⟦1⟧，翻译时应原样保留
PLACEHOLDER = "\u27e6{}\u27e7"
PLACEHOLDER_RE = re.compile(PLACEHOLDER.format(r"(\d+)"))


def load_glossary(path=GLOSSARY_PATH):
    """读取术语库，返回 [(zh, ru, category), ...]，按中文长度降序（最长优先匹配）。"""
    entries = []
    # utf-8-sig：兼容带 BOM 的 CSV（Windows 记事本/Excel 另存常见）
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            zh, ru, cat = (row.get("zh") or "").strip(), (row.get("ru") or "").strip(), (row.get("category") or "").strip()
            if zh and ru:
                entries.append((zh, ru, cat))
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def protect_terms(text, glossary):
    """①术语预检：把命中的术语替换成占位符，返回 (受保护文本, {占位符序号: (ru, category)})。"""
    spans = []
    for zh, ru, cat in glossary:
        for m in re.finditer(re.escape(zh), text):
            spans.append((m.start(), m.end(), ru, cat))
    # 重叠区间只保留最长（列表已按术语长度降序生成）
    spans.sort()
    chosen, last_end = [], -1
    for s, e, ru, cat in spans:
        if s >= last_end:
            chosen.append((s, e, ru, cat))
            last_end = e
    protected, mapping, cursor = [], {}, 0
    for idx, (s, e, ru, cat) in enumerate(chosen):
        protected.append(text[cursor:s])
        protected.append(PLACEHOLDER.format(idx))
        mapping[idx] = (ru, cat)
        cursor = e
    protected.append(text[cursor:])
    return "".join(protected), mapping


def restore_terms(text, mapping):
    """③术语回填：把占位符替换回标准译法（缩写/编号类保持原样）。"""
    def sub(m):
        ru, cat = mapping[int(m.group(1))]
        return ru
    return PLACEHOLDER_RE.sub(sub, text)


def libre_translate(text, source, target, url, api_key=None):
    """②调用 LibreTranslate 的 /translate 接口，返回纯译文文本。"""
    payload = {"q": text, "source": source, "target": target, "format": "text"}
    if api_key:
        payload["api_key"] = api_key
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/translate", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    # /translate 返回的是 JSON（形如 {"translated_text": "..."}），
    # 这里取出真正的译文；若响应不是 JSON（如代理返回纯文本），则原样返回。
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(parsed, dict):
        return parsed.get("translated_text") or raw
    return raw


def main():
    parser = argparse.ArgumentParser(description="LibreTranslate 校园术语预检演示")
    parser.add_argument("--text", required=True, help="要翻译的原文")
    parser.add_argument("--source", default="zh", help="源语言代码，默认 zh")
    parser.add_argument("--target", default="ru", help="目标语言代码，默认 ru")
    parser.add_argument("--url", default="http://localhost:5000", help="LibreTranslate 服务地址")
    parser.add_argument("--api-key", default=None, help="可选 API key")
    parser.add_argument("--dry-run", action="store_true", help="只显示术语命中情况，不实际调用翻译")
    args = parser.parse_args()

    glossary = load_glossary()
    protected, mapping = protect_terms(args.text, glossary)

    print("== ① 术语预检 ==")
    if not mapping:
        print("  未命中任何术语，整句交给翻译引擎。")
    for idx, (ru, cat) in sorted(mapping.items()):
        print(f"  {PLACEHOLDER.format(idx)} -> {ru}  [{cat}]")
    print(f"\n== 送入翻译引擎的文本 ==\n  {protected}\n")

    if args.dry_run:
        return

    print("== ②③ 翻译并回填术语 ==")
    try:
        result = libre_translate(protected, args.source, args.target, args.url, args.api_key)
        translated = result
        final = restore_terms(translated, mapping)
        print(f"\n== ④ 中俄对照 ==\n  中：{args.text}\n  俄：{final}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  调用 LibreTranslate 失败：{exc}\n  提示：请确认本机已运行 LibreTranslate，或改用 --dry-run 查看预检效果。")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知 / 邮件的中俄对照生成（LibreTranslate 校园版）

在 glossary_precheck.py 的"术语预检 + 回填"之上，补上两件事：

  1. 人名音译：接入 name_translit.py，中文姓名按定译表或规则转写，
     俄语教师姓名保留原文（详见 names_zh_ru.csv）；
  2. 一键对照排版：把通知拆成「标题 / 正文 / 落款」三段，
     逐段翻译后输出可直接粘贴到邮件或公告里的中俄对照版。

流程：通知原文 → ①术语 + 人名预检 → ②LibreTranslate 翻译 → ③回填 → ④按模板排版

用法：
    # 直接给文本
    python notice_template.py --title "关于期末考试安排的通知" \
        --body "本学期《计量经济学》期末考试于 MT-101 教室举行，请携带学生证。" \
        --sign "教务处"

    # 从文件读（第一行=标题，最后一行=落款，中间=正文）
    python notice_template.py --file notice.txt --dry-run

    # 不连翻译引擎时，用 --dry-run 只查看术语/人名命中与受保护文本
    python notice_template.py --file notice.txt --dry-run
"""

import argparse
import os

from glossary_precheck import (  # 复用术语预检的成熟逻辑，避免重复实现
    load_glossary,
    libre_translate,
    protect_terms,
    restore_terms,
)
from name_translit import CYRILLIC_RE, load_names, transliterate

SECTIONS = [("标题", "Заголовок"), ("正文", "Текст"), ("落款", "Подпись")]


def build_entries(text, extra_names):
    """汇总所有需要保护的内容：术语库 + 人名定译 + 临时人名 + 俄文原文。"""
    entries = list(load_glossary())
    table = load_names()

    for zh, ru in table.items():
        if zh in text:
            entries.append((zh, ru, "人名"))

    for name in extra_names:
        name = name.strip()
        if not name:
            continue
        ru, _source = transliterate(name, registered=table)
        entries.append((name, ru, "人名"))

    # 文本里已经出现的西里尔字母（俄语教师姓名、俄文机构名）原样保留
    for run in set(CYRILLIC_RE.findall(text)):
        entries.append((run, run, "俄文原文"))

    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def render_block(zh_label, ru_label, zh_lines, ru_lines):
    """把一个段落渲染成中俄逐行对照。"""
    out = [f"【{zh_label} / {ru_label}】"]
    for z, r in zip(zh_lines, ru_lines):
        out.append(f"  中：{z}")
        out.append(f"  俄：{r}")
    return "\n".join(out)


def translate_or_placeholder(protected, mapping, args):
    """翻译受保护文本；--dry-run 或未连引擎时给出占位，不假装是译文。"""
    if args.dry_run:
        return restore_terms(protected, mapping)  # 只回填术语，展示结构
    return restore_terms(libre_translate(protected, args.source, args.target, args.url, args.api_key), mapping)


def split_lines(text):
    return [line for line in (l.strip() for l in text.splitlines()) if line]


def main():
    parser = argparse.ArgumentParser(description="校园通知 / 邮件的中俄对照生成")
    parser.add_argument("--title", help="通知标题")
    parser.add_argument("--body", help="通知正文（可多行）")
    parser.add_argument("--sign", default="", help="落款，如 教务处")
    parser.add_argument("--file", help="从文件读取：第一行=标题，最后一行=落款，中间=正文")
    parser.add_argument("--names", default="", help="临时补充的人名，逗号分隔，如 '王明,李娜'")
    parser.add_argument("--source", default="zh")
    parser.add_argument("--target", default="ru")
    parser.add_argument("--url", default="http://localhost:5000")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--out", default=None, help="可选：把对照结果写入文件")
    parser.add_argument("--dry-run", action="store_true", help="不调用翻译引擎，只查看预检与排版")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            lines = split_lines(f.read())
        if not lines:
            print("  文件为空。")
            return
        title = lines[0]
        sign = lines[-1] if len(lines) > 2 else ""
        body = "\n".join(lines[1:-1]) if len(lines) > 2 else (lines[1] if len(lines) > 1 else "")
    else:
        if not args.title:
            parser.error("请提供 --title，或改用 --file 从文件读取")
        title, body, sign = args.title, args.body or "", args.sign

    full_text = "\n".join([title, body, sign])
    entries = build_entries(full_text, args.names.split(","))

    blocks, hit_report = [], []
    for zh_label, ru_label in SECTIONS:
        segment = {"标题": title, "正文": body, "落款": sign}[zh_label]
        if not segment.strip():
            continue
        protected, mapping = protect_terms(segment, entries)
        for idx, (ru, cat) in sorted(mapping.items()):
            hit_report.append(f"  [{cat}] {ru}")
        ru_text = translate_or_placeholder(protected, mapping, args)
        blocks.append(render_block(zh_label, ru_label, split_lines(segment), split_lines(ru_text)))

    header = "════════ 校园通知（中俄对照）════════"
    if args.dry_run:
        header += "\n※ dry-run 模式：未调用翻译引擎，俄语侧仅展示术语回填结果"
    body_out = "\n\n".join([header] + blocks)

    if hit_report:
        body_out += "\n\n── 术语 / 人名命中 ──\n" + "\n".join(sorted(set(hit_report)))
    else:
        body_out += "\n\n── 术语 / 人名命中 ──\n  未命中任何术语或人名"

    print(body_out)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body_out + "\n")
        print(f"\n已写入：{os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()

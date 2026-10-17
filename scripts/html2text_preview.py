#!/usr/bin/env python3
"""把 HTML 变成「标题 + 正文纯文本」，供 warp-fetch 的 page 模式使用。

单独放成文件而不是内联在 workflow 里：YAML 块标量要求内容缩进，
而 Python 顶层语句必须贴左，两者冲突会把 YAML 解析炸掉（踩过）。
"""
import html
import re
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: html2text_preview.py <in.html> <out.txt>", file=sys.stderr)
        return 2

    src, dst = sys.argv[1], sys.argv[2]
    raw = open(src, "rb").read().decode("utf-8", "replace")

    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(m.group(1).strip()) if m else "(无 title)"

    txt = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    txt = re.sub(r"<!--.*?-->", " ", txt, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(re.sub(r"[ \t\r\f\v]+", " ", txt))
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()

    with open(dst, "w", encoding="utf-8") as f:
        f.write(f"TITLE: {title}\n\n{txt[:40000]}\n")

    print(f"TITLE = {title}")
    print(f"正文字符数 = {len(txt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

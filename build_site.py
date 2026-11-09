# -*- coding: utf-8 -*-
"""把 reports/ 下的日报 HTML 构建成一个免登录的独立静态站点（site/）。

处理内容：
  1) 删掉依赖资料库 SDK 的「访问量」模块（公开站点上会显示"本地预览"）
  2) 追加移动端媒体查询（原报告无 @media）
  3) 头部插入日期切换下拉，可在历史日报之间切换
  4) index.html = 最新一期；其余按 起止日期.html 平铺

用法：python build_site.py [--reports DIR] [--out DIR]
"""
import argparse
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

MOBILE_CSS = """
    @media (max-width: 760px){
      header{padding:12px 12px 0}
      h1{font-size:17px}
      .hd{gap:8px}
      .date{font-size:12px}
      nav{gap:6px}
      .tab{font-size:13px;padding:8px 12px}
      main{padding:12px !important}
      .panel{grid-template-columns:1fr !important;gap:10px !important}
      .card{padding:12px !important}
      #ds{margin-left:auto}
    }
    #ds{font:inherit;font-size:12px;padding:4px 8px;border:1px solid #d1d5db;
        border-radius:8px;background:#fff;color:#374151;max-width:170px}
"""

SELECT_CSS = ""


def stamp(html):
    """注入移动端样式（放在 </style> 前）。"""
    if "<style>" in html and "</style>" in html:
        return html.replace("</style>", MOBILE_CSS + "</style>", 1)
    return html


def drop_pv(html):
    """删除访问量 IIFE（与选项卡切换共用同一个 <script>，只能切掉那一段）与 pv-badge 的 span。"""
    def repl(m):
        block = m.group(1)
        if "var DB_ID=" not in block:
            return m.group(0)
        i = block.find("var DB_ID=")
        j = block.rfind("(function(){", 0, i)
        head = block[:j] if j != -1 else block
        open_tag = m.group(0).split(">", 1)[0] + ">"
        return open_tag + head + "</script>"

    html = re.sub(r"<script\b[^>]*>(.*?)</script>", repl, html, flags=re.S)
    html = re.sub(r'<span[^>]*id="pv-badge"[^>]*>.*?</span>', "", html, flags=re.S)
    return html


def add_switcher(html, options, current):
    """在头部日期后插入下拉切换。options: [(label, filename), ...]"""
    opts = "".join(
        '<option value="%s"%s>%s</option>' % (fn, " selected" if fn == current else "", label)
        for label, fn in options
    )
    sel = ('<select id="ds" onchange="if(this.value)location.href=this.value" '
           'title="切换日期">%s</select>' % opts)
    m = re.search(r'<span class="date">.*?</span>', html, re.S)
    if m:
        return html[:m.end()] + sel + html[m.end():]
    return html.replace("</h1>", "</h1>" + sel, 1)


def collect(reports_dir):
    """返回 [(date, tag, path)]，tag ∈ {晨报, 晚间版}"""
    items = []
    for p in glob.glob(os.path.join(reports_dir, "*.html")):
        name = os.path.basename(p)
        m = re.match(r"新闻日报(?:_晚间版)?_(\d{4}-\d{2}-\d{2})\.html$", name) \
            or re.match(r"新闻日报_(\d{4}-\d{2}-\d{2})_晚间版\.html$", name)
        if not m:
            continue
        items.append((m.group(1), "晚间版" if "晚间版" in name else "晨报", p))
    items.sort(key=lambda x: (x[0], 0 if x[1] == "晨报" else 1))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", default=os.path.join(HERE, "reports"))
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    items = collect(a.reports)
    if not items:
        raise SystemExit("[FAIL] reports 下没有匹配的日报 html")

    # 文件名：2026-11-05.html / 2026-11-05-晚间.html
    files = []
    for date, tag, path in items:
        fn = "%s%s.html" % (date, "-晚间" if tag == "晚间版" else "")
        files.append((date, tag, path, fn))

    options = [("%s %s" % (d, "晚间版" if t == "晚间版" else "晨报"), fn) for d, t, _, fn in files]

    for date, tag, path, fn in files:
        html = open(path, encoding="utf-8").read()
        html = drop_pv(html)
        html = stamp(html)
        html = add_switcher(html, options, fn)
        with open(os.path.join(a.out, fn), "w", encoding="utf-8") as f:
            f.write(html)

    # index = 最新一期（同一天优先晚间版）
    latest = files[-1]
    index_html = open(os.path.join(a.out, latest[3]), encoding="utf-8").read()
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print("BUILD_OK 页面 %d 个，最新 %s %s" % (len(files), latest[0], latest[1]))
    for _, _, _, fn in files:
        print("  -", fn)
    print("  - index.html")


if __name__ == "__main__":
    main()

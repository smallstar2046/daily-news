# -*- coding: utf-8 -*-
"""
每日新闻自动抓取程序 v1.0
========================
输出五类内容，生成 Markdown + HTML 日报：
1. 国内房产政策新闻 5-10 条
2. 科技/AI 消息 10-20 条
3. GitHub 每日 Trending 前 10 开源项目
4. 金融要闻 15 条
5. 加密货币：链上消息 5 条 + 政策类 5 条 + 交易数据类 10 条

数据源（经实测可达性验证）：
- RSSHub 镜像 rsshub.rssforever.com：GitHub Trending / 金色财经 / 36氪快讯 / 华尔街见闻
- 直连 RSS：量子位、爱范儿、虎嗅(RSSHub)
- 直连 API：新浪 7x24、华尔街见闻、gate.io 行情、恐慌贪婪指数
运行：python fetch_news.py [输出目录]
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

import feedparser
import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

RSSHUB = "https://rsshub.rssforever.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
}
TIMEOUT = 25


class _TagStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    s = _TagStripper()
    try:
        s.feed(raw)
    except Exception:
        pass
    text = unescape("".join(s.parts))
    return re.sub(r"\s+", " ", text).strip()


def ts_to_str(ts) -> str:
    """时间戳 -> 'MM-DD HH:MM'；失败返回空串"""
    try:
        if ts is None:
            return ""
        ts = float(ts)
        if ts > 1e12:  # 毫秒
            ts /= 1000
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def fetch(url, **kw):
    for attempt in (1, 2, 3):  # 失败重试，RSSHub 镜像偶发超时
        try:
            return requests.get(url, headers=HEADERS, timeout=kw.pop("timeout", TIMEOUT), **kw)
        except Exception as e:
            if attempt == 3:
                print(f"  [NET-FAIL] {url[:60]}: {type(e).__name__}")
                return None


def fetch_post(url, json_body, timeout=TIMEOUT):
    for attempt in (1, 2):
        try:
            h = {**HEADERS, "Content-Type": "application/json"}
            return requests.post(url, headers=h, json=json_body, timeout=timeout)
        except Exception as e:
            if attempt == 2:
                print(f"  [NET-FAIL] POST {url[:60]}: {type(e).__name__}")
                return None


def fetch_rss(url, limit=40, timeout=TIMEOUT):
    """解析 RSS/Atom，返回 [{title, link, summary, ts}]"""
    r = fetch(url, timeout=timeout)
    if r is None or r.status_code != 200:
        print(f"  [SRC-FAIL] {url[:70]}")
        return []
    parsed = feedparser.parse(r.content)
    out = []
    for e in parsed.entries[:limit]:
        ts = None
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(e, attr, None)
            if t:
                ts = time.mktime(t)
                break
        out.append({
            "title": strip_html(getattr(e, "title", "")),
            "link": getattr(e, "link", ""),
            "summary": strip_html(getattr(e, "summary", getattr(e, "description", "")))[:600],
            "ts": ts,
        })
    print(f"  [OK] {url[:70]} -> {len(out)} 条")
    return out


# ---------------------------------------------------------------- 五类抓取器
RE_ESTATE_KW = re.compile(
    r"房地产|楼市|房贷|住房|住建|限购|限售|限价|公积金|契税|土地|保障房|城中村|"
    r"房价|楼盘|物业|首付|收储|老旧小区|房企|地产|安居|经适房|限购令|房票|降息.*房|存量房"
)
RE_AI_KW = re.compile(
    r"AI|人工智能|大模型|GPT|OpenAI|Claude|Gemini|DeepSeek|Qwen|通义|文心|豆包|Kimi|"
    r"算力|芯片|GPU|英伟达|半导体|机器人|智能体|Agent|智驾|自动驾驶|AIGC|"
    r"多模态|神经网络|推理模型|开源模型|Sora|Copilot|英伟达|具身智能|人形机器人"
)
RE_CHAIN_KW = re.compile(
    r"链上|巨鲸|转账|钱包|地址|质押|黑客|攻击|被盗|链上数据|链上异动|赎回|充值|提现|挖矿"
)
RE_CRYPTOPOLICY_KW = re.compile(
    r"政策|监管|SEC|法案|立法|央行|证监会|罚款|合规|禁令|诉讼|起诉|稳定币|储备|许可|牌照|"
    r"司法|法院|国会|参议院|众议院|白宫|财政部|打击|调查|冻结|制裁|CFTC"
)
# 加密货币上下文：东财搜索池中仅保留与加密相关的条目，避免债市/AI 新闻混入
RE_CRYPTO_CTX = re.compile(
    r"币|链|加密|比特币|以太坊|稳定币|BTC|ETH|USDT|Web3|挖矿|钱包|公链|Solana|"
    r"Memecoin|DeFi|NFT|交易所|Token|代币|CFTC|SEC|狗狗币|莱特币|加密货币"
)


def eastmoney_search(keyword, size=15):
    """东方财富新闻搜索（按时间倒序），返回 [{title, link, summary, ts, ts_str}]"""
    param = {
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                                       "pageIndex": 1, "pageSize": size,
                                       "preTag": "", "postTag": ""}},
    }
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    r = fetch(url, params={"cb": "cb", "param": json.dumps(param, ensure_ascii=False)})
    if r is None or r.status_code != 200:
        print(f"  [SRC-FAIL] 东财搜索:{keyword}")
        return []
    try:
        m = re.search(r"cb\((.*)\)\s*$", r.text, re.S)
        arts = json.loads(m.group(1))["result"]["cmsArticleWebOld"]
    except Exception:
        print(f"  [PARSE-FAIL] 东财搜索:{keyword}")
        return []
    out = []
    for a in arts:
        dt = a.get("date", "")
        try:
            ts = datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            ts = None
        out.append({
            "title": strip_html(a.get("title", "")),
            "link": f"https://finance.eastmoney.com/a/{a.get('code','')}.html",
            "summary": strip_html(a.get("content", ""))[:200],
            "ts": ts, "ts_str": dt[:16],
        })
    print(f"  [OK] 东财搜索:{keyword} -> {len(out)} 条")
    return out


def get_sina_7x24(limit=50):
    """新浪财经 7x24 快讯"""
    url = f"https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size={limit}&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    r = fetch(url)
    if r is None or r.status_code != 200:
        print("  [SRC-FAIL] 新浪7x24")
        return []
    try:
        items = r.json()["result"]["data"]["feed"]["list"]
    except Exception:
        print("  [PARSE-FAIL] 新浪7x24")
        return []
    out = [{
        "title": strip_html(i.get("rich_text", "")),
        "link": (i.get("ext") or [{}])[0].get("url", "") if isinstance(i.get("ext"), list) else "",
        "summary": "",
        "ts": i.get("create_time"),
    } for i in items]
    print(f"  [OK] 新浪7x24 -> {len(out)} 条")
    return out


def get_wallstreetcn(limit=50):
    """华尔街见闻快讯"""
    url = f"https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit={limit}"
    r = fetch(url)
    if r is None or r.status_code != 200:
        print("  [SRC-FAIL] 华尔街见闻")
        return []
    try:
        items = r.json()["data"]["items"]
    except Exception:
        print("  [PARSE-FAIL] 华尔街见闻")
        return []
    out = [{
        "title": strip_html(i.get("title") or i.get("content_text", "")),
        "link": i.get("uri", "") or "",
        "summary": strip_html(i.get("content_short", ""))[:200],
        "ts": i.get("display_time"),
    } for i in items]
    print(f"  [OK] 华尔街见闻 -> {len(out)} 条")
    return out


def get_eastmoney_finance(limit=20):
    """东方财富要闻（金融补充源）"""
    url = ("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_news_col"
           f"&column=345&order=1&needInteractData=0&page_index=1&page_size={limit}&req_trace={int(time.time())}")
    r = fetch(url)
    if r is None or r.status_code != 200:
        print("  [SRC-FAIL] 东方财富")
        return []
    try:
        lst = r.json()["data"]["list"]
    except Exception:
        print("  [PARSE-FAIL] 东方财富")
        return []
    out = [{
        "title": strip_html(i.get("title", "")),
        "link": i.get("url_unique", i.get("url", "")),
        "summary": strip_html(i.get("summary", ""))[:200],
        "ts": ts_to_str(i.get("show_time")) and None,  # show_time 是字符串，仅展示用
        "ts_str": i.get("show_time", ""),
    } for i in lst]
    print(f"  [OK] 东方财富 -> {len(out)} 条")
    return out


def dedupe(items, seen=None):
    seen = seen if seen is not None else set()
    out = []
    for it in items:
        t = re.sub(r"[\s\W_]+", "", it["title"])[:40]
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(it)
    return out


def sort_by_ts(items):
    def ts_val(x):
        v = x.get("ts")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return sorted(items, key=ts_val, reverse=True)


def fmt_item(i, idx):
    t = i.get("ts_str") or ts_to_str(i.get("ts"))
    tag = f"【{i['tag']}】" if i.get("tag") else ""
    head = f"{idx}. {tag}**{i['title']}**"
    tail = f"  \n   [{t}]({i['link']})" if (i.get("link") and t) else (f"  \n   [{t}]({i['link']})" if i.get("link") else "")
    summ = f"  \n   {i['summary']}" if i.get("summary") and len(i["summary"]) > 20 else ""
    return head + summ + tail


# 1) 房产政策 ----------------------------------------------------------------
RE_ESTATE_KW = re.compile(
    r"房地产|楼市|房贷|住房|住建|限购|限售|限价|公积金|契税|土地|保障房|城中村|"
    r"房价|楼盘|物业|首付|收储|老旧小区|房企|地产|安居|经适房|限购令|房票|降息.*房|存量房"
)
# 成都本地政策关键词：标题含"成都"且命中以下任一词
RE_CHENGDU_KW = re.compile(
    r"楼市|住房|公积金|房产|房地产|土地|土拍|房贷|限购|购房|房价|新政|政策|物业|保交楼|收储|人才安居"
)


def _thepaper_chengdu():
    """澎湃内容 API（直连）：财经+时事频道近期条目中筛成都房产"""
    out, seen = [], set()
    for ch in ("25952", "25950"):  # 财经 / 时事
        r = fetch_post("https://api.thepaper.cn/contentapi/nodeCont/getByChannelId",
                       {"channelId": ch, "pageNum": 1, "pageSize": 40})
        if r is None or r.status_code != 200:
            continue
        try:
            lst = r.json()["data"]["list"]
        except Exception:
            continue
        for a in lst:
            title = strip_html(a.get("name", ""))
            if "成都" not in title or not RE_CHENGDU_KW.search(title):
                continue
            key = re.sub(r"[\s\W_]+", "", title)[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title,
                        "link": f"https://www.thepaper.cn/newsDetail_forward_{a.get('contId','')}",
                        "summary": "", "ts": (a.get("pubTimeLong") or 0) / 1000 or None,
                        "ts_str": "", "tag": "成都"})
    print(f"  [OK] 澎湃频道 -> 成都条目 {len(out)} 条")
    return out


def _parse_sogou_date(s):
    """搜狗时间文本 -> epoch；解析失败返回 None"""
    if not s:
        return None
    now = datetime.now()
    try:
        if s.endswith(("小时前", "天前")):
            n = int(re.search(r"\d+", s).group())
            unit = 3600 if "小时" in s else 86400
            return now.timestamp() - n * unit
        if re.match(r"\d{1,2}月\d{1,2}日", s):
            m = re.search(r"(\d{1,2})月(\d{1,2})日", s)
            dt = datetime(now.year, int(m.group(1)), int(m.group(2)))
            if dt > now:  # 未来日期归到去年
                dt = datetime(now.year - 1, int(m.group(1)), int(m.group(2)))
            return dt.timestamp()
        if re.match(r"20\d{2}-", s):
            return datetime.strptime(s, "%Y-%m-%d").timestamp()
    except Exception:
        pass
    return None


RE_JUNK_TITLE = re.compile(r"楼盘网|门户|大全|招聘|下载|官网|_|专题|排行榜|小区大全")


def _wscn_article_search(query, limit=15):
    """华尔街见闻文章搜索（域名稳定可达）"""
    r = fetch("https://api-one-wscn.awtmt.com/apiv1/search/article",
              params={"query": query, "limit": limit})
    if r is None or r.status_code != 200:
        print(f"  [SRC-FAIL] 华见闻搜索:{query}")
        return []
    try:
        items = r.json()["data"]["items"] or []
    except Exception:
        return []
    out = []
    for a in items:
        title = strip_html(a.get("title", ""))
        if not title:
            continue
        out.append({"title": title, "link": a.get("uri", ""),
                    "summary": strip_html(a.get("content_short", ""))[:150],
                    "ts": a.get("display_time"), "ts_str": ""})
    print(f"  [OK] 华见闻搜索:{query} -> {len(out)} 条")
    return out


def collect_chengdu(pool, min_n=3):
    """成都本地房产政策：搜狗搜索 + 澎湃 + 全国池过滤，三层叠加；只保留近 60 天"""
    print("  [成都] 开始采集（搜狗/澎湃/全国池）...")
    out, seen = [], set()
    cutoff = datetime.now().timestamp() - 60 * 86400

    def add(items):
        for i in items:
            if RE_JUNK_TITLE.search(i["title"]):
                continue
            ts = _parse_sogou_date(i.get("ts_str")) if not i.get("ts") else i["ts"]
            if ts and ts < cutoff:  # 旧闻丢弃
                continue
            if ts and not i.get("ts_str"):
                i = {**i, "ts_str": datetime.fromtimestamp(ts).strftime("%m-%d")}
            key = re.sub(r"[\s\W_]+", "", i["title"])[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({**i, "ts": ts, "tag": "成都"})

    # ① 全国池过滤
    add([i for i in pool if "成都" in i["title"] and RE_CHENGDU_KW.search(i["title"])])
    # ② 澎湃频道
    add(_thepaper_chengdu())
    # ③ 华尔街见闻文章搜索（稳定源）
    for q in ["成都 楼市", "成都 公积金", "成都 住房", "成都 土拍", "成都 房价"]:
        if len(out) >= min_n + 2:
            break
        add([i for i in _wscn_article_search(q) if "成都" in i["title"]])
    # ④ 搜狗搜索（有反爬，间歇可用）
    sess = requests.Session()
    sess.headers.update({**HEADERS, "Referer": "https://news.sogou.com/"})
    try:
        sess.get("https://news.sogou.com/", timeout=10)
    except Exception:
        pass
    for q in ["成都 楼市政策", "成都 住房公积金", "成都 房地产", "成都 土拍"]:
        if len(out) >= min_n + 2:
            break
        got = False
        for attempt in (1, 2):
            try:
                r = sess.get("https://news.sogou.com/news", params={"query": q}, timeout=20)
                got = r.status_code == 200 and r.text.count("<h3") > 0
                if got:
                    break
            except Exception:
                pass
            time.sleep(1.5)
        if not got:
            print(f"  [SRC-FAIL] 搜狗:{q}（验证页/超时）")
            continue
        items = []
        for b in re.split(r"<h3", r.text)[1:]:
            m = re.search(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", b, re.S)
            if not m:
                continue
            link, title = m.group(1), strip_html(m.group(2))
            if link.startswith("/"):
                link = "https://news.sogou.com" + link
            if "成都" not in title or not RE_CHENGDU_KW.search(title):
                continue
            tm = (re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", b)
                  or re.search(r"(\d{1,2}月\d{1,2}日)", b)
                  or re.search(r"(\d+小时前|\d+天前)", b))
            items.append({"title": title, "link": link, "summary": "", "ts": None,
                          "ts_str": tm.group(1) if tm else ""})
        add(items)
        print(f"  [OK] 搜狗:{q} -> 累计 {len(out)} 条成都条目")
        time.sleep(1.2)
    out = sort_by_ts(out)
    return out


def collect_estate(max_n=10):
    print("[1/6] 房产政策新闻...")
    # 专用源：东财新闻搜索（按时间）＋ 通用快讯关键词过滤
    pool = (eastmoney_search("房地产政策", 15)
            + eastmoney_search("楼市政策", 15)
            + eastmoney_search("住房公积金", 10)
            + get_sina_7x24(80) + get_wallstreetcn(60))
    hits = [i for i in pool if RE_ESTATE_KW.search(i["title"])]
    print(f"  命中房产关键词 {len(hits)} 条")
    items = dedupe(sort_by_ts(hits))
    # 规则：成都本地政策至少保底 3 条
    cd_count = sum(1 for i in items if "成都" in i["title"])
    if cd_count < 3:
        cd = collect_chengdu(pool, 3)
        seen = {re.sub(r"[\s\W_]+", "", i["title"])[:40] for i in items}
        for i in cd:
            key = re.sub(r"[\s\W_]+", "", i["title"])[:40]
            if key not in seen:
                items.append(i)
                seen.add(key)
        print(f"  成都条目：全国池 {cd_count} 条 + 补充 {len(cd)} 条")
    # 成都条目置顶展示
    items = sort_by_ts([i for i in items if i.get("tag") == "成都"]) + \
            sort_by_ts([i for i in items if i.get("tag") != "成都"])
    return items[:max_n + 3]


# 2) 科技/AI -----------------------------------------------------------------
def collect_tech(max_n=20):
    print("[2/6] 科技/AI 消息...")
    qbit = fetch_rss("https://www.qbitai.com/feed", 25)
    ifanr = fetch_rss("https://www.ifanr.com/feed", 25)
    huxiu = fetch_rss(f"{RSSHUB}/huxiu/article", 20)
    kr36 = fetch_rss(f"{RSSHUB}/36kr/newsflashes", 40)
    # 量子位/爱范儿本身就是科技源，全部保留；虎嗅与36氪按 AI/科技关键词过滤
    kr36_ai = [i for i in kr36 if RE_AI_KW.search(i["title"]) or RE_AI_KW.search(i["summary"])]
    huxiu_ai = [i for i in huxiu if RE_AI_KW.search(i["title"]) or RE_AI_KW.search(i["summary"])]
    items = dedupe(sort_by_ts(qbit + ifanr + kr36_ai + huxiu_ai))
    return items[:max_n]


# 3) GitHub Trending ----------------------------------------------------------
def github_api_fallback(max_n=10):
    """RSSHub Trending 失败时兜底：GitHub Search API 近7天新晋高星仓库"""
    from datetime import timedelta
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = (f"https://api.github.com/search/repositories?q=created:%3E{since}"
           f"&sort=stars&order=desc&per_page={max_n}")
    r = fetch(url, timeout=30)
    if r is None or r.status_code != 200:
        print("  [SRC-FAIL] GitHub API 兜底")
        return []
    try:
        repos = r.json()["items"]
    except Exception:
        return []
    items = [{
        "title": i["full_name"],
        "link": i["html_url"],
        "summary": (i.get("description") or "")[:200],
        "stars": f"⭐ {i['stargazers_count']:,}（近7日新晋）",
        "lang": i.get("language") or "",
        "ts": None, "ts_str": "",
    } for i in repos]
    print(f"  [OK] GitHub API 兜底 -> {len(items)} 条")
    return items


def collect_github(max_n=10):
    print("[3/6] GitHub Trending...")
    entries = fetch_rss(f"{RSSHUB}/github/trending/daily/any", max_n, timeout=45)
    items = []
    for e in entries:
        repo = e["title"].split(":")[0].strip()
        desc = e["summary"]
        m = re.search(r"Stars?:?\s*([\d,]{3,})", desc, re.I)
        stars = f"⭐ {m.group(1)}" if m else ""
        # RSSHub 描述尾部附带 "Language: xxStars: nForks: n"，截掉
        summary = re.split(r"Language:", desc)[0].strip(" ,，-")
        items.append({
            "title": repo,
            "link": e["link"],
            "summary": summary[:200],
            "stars": stars,
            "ts": None, "ts_str": "",
        })
    if len(items) < max_n:
        print(f"  Trending RSS 不足 {max_n} 条，启用 GitHub API 兜底")
        items += github_api_fallback(max_n - len(items))
    # RSSHub 描述里的 Star 数时有时无，缺失时用 GitHub API 补全
    for it in items:
        if it.get("stars"):
            continue
        r = fetch(f"https://api.github.com/repos/{it['title']}", timeout=15)
        if r is None or r.status_code != 200:
            continue
        try:
            it["stars"] = f"⭐ {r.json()['stargazers_count']:,}"
        except Exception:
            pass
    return items[:max_n]


# 4) 金融要闻 -----------------------------------------------------------------
def collect_finance(max_n=15):
    print("[4/6] 金融要闻...")
    wsc = get_wallstreetcn(40)
    em = get_eastmoney_finance(20)
    sina = get_sina_7x24(50)
    items = dedupe(sort_by_ts(wsc) + sort_by_ts(em) + sort_by_ts(sina))
    return items[:max_n]


# 5) 加密货币 -----------------------------------------------------------------
def collect_crypto():
    print("[5/6] 加密货币...")
    jinse = fetch_rss(f"{RSSHUB}/jinse/lives", 60)
    em_pool = (eastmoney_search("加密货币", 20)
               + eastmoney_search("比特币", 20)
               + eastmoney_search("稳定币", 15))
    crypto_pool = dedupe(sort_by_ts(jinse + [i for i in em_pool if RE_CRYPTO_CTX.search(i["title"])]))
    chain = [i for i in crypto_pool if RE_CHAIN_KW.search(i["title"])][:5]
    policy = [i for i in crypto_pool if RE_CRYPTOPOLICY_KW.search(i["title"])][:5]
    # 数量不足时补位：优先金色财经快讯（纯加密源），再从东财加密池补
    used = {i["title"] for i in chain} | {i["title"] for i in policy}
    for src in (dedupe(sort_by_ts(jinse)), crypto_pool):
        for i in src:
            if len(chain) >= 5 and len(policy) >= 5:
                break
            if i["title"] in used:
                continue
            if len(chain) < 5:
                chain.append(i); used.add(i["title"])
            elif len(policy) < 5:
                policy.append(i); used.add(i["title"])
        if len(chain) >= 5 and len(policy) >= 5:
            break
    # 交易数据
    trade = []
    fng = fetch("https://api.alternative.me/fng/?limit=1")
    if fng is not None and fng.status_code == 200:
        try:
            d = fng.json()["data"][0]
            trade.append({"title": f"恐慌贪婪指数：{d['value']}（{d['value_classification']}）",
                          "link": "https://alternative.me/crypto/fear-and-greed-index/", "summary": "", "ts": None, "ts_str": ""})
        except Exception:
            pass
    r = fetch("https://api.gateio.ws/api/v4/spot/tickers")
    tickers = []
    if r is not None and r.status_code == 200:
        try:
            tickers = [t for t in r.json() if t["currency_pair"].endswith("_USDT")]
        except Exception:
            pass
    by_pair = {t["currency_pair"]: t for t in tickers}
    def line(pair, name):
        t = by_pair.get(pair)
        if not t:
            return None
        chg = float(t.get("change_percentage", 0) or 0)
        vol = float(t.get("quote_volume", 0) or 0) / 1e8
        price = float(t["last"])
        price_s = f"{price:,.2f}" if price >= 100 else f"{price:.4f}".rstrip("0").rstrip(".")
        arrow = "📈" if chg >= 0 else "📉"
        return {"title": f"{name}：{price_s} USDT，24h {chg:+.2f}% {arrow}，24h 成交额 {vol:.2f} 亿 USDT",
                "link": "https://www.gate.io/trade/" + pair.replace("_", "_"), "summary": "", "ts": None, "ts_str": ""}
    for pair, name in [("BTC_USDT", "BTC"), ("ETH_USDT", "ETH"), ("SOL_USDT", "SOL"),
                       ("BNB_USDT", "BNB"), ("XRP_USDT", "XRP"), ("DOGE_USDT", "DOGE"),
                       ("ADA_USDT", "ADA"), ("AVAX_USDT", "AVAX"), ("LINK_USDT", "LINK"), ("TON_USDT", "TON")]:
        it = line(pair, name)
        if it:
            trade.append(it)
    # 不足 10 条时按成交额补主流币
    if len(trade) < 10:
        top = sorted(tickers, key=lambda t: float(t.get("quote_volume", 0)), reverse=True)
        used = {x["title"].split("：")[0] for x in trade}
        for t in top:
            if len(trade) >= 10:
                break
            name = t["currency_pair"].replace("_USDT", "")
            if name in used or name in ("USDT", "USDC", "DAI", "FDUSD", "TUSD"):
                continue
            it = line(t["currency_pair"], name)
            if it:
                trade.append(it)
                used.add(name)
    trade = trade[:10]
    return chain, policy, trade


# 6) 美联储/宏观消息面日程 -----------------------------------------------------
# 内置经济数据发布日程（北京时间，来源：BLS/BEA 2026 年度安排，经 tradersweek/sync2cal 交叉核对；
# 程序每季度更新一次）
ECON_SCHEDULE = [
    ("2026-11-06", "21:30", "💼 非农就业报告（10月）", "高"),
    ("2026-11-10", "21:30", "📊 CPI 通胀数据（10月）", "高"),
    ("2026-11-13", "21:30", "📊 PPI 生产者价格指数（10月）", "中"),
    ("2026-11-17", "21:30", "📈 零售销售（10月）", "高"),
    ("2026-11-25", "21:30", "📈 GDP 修正值 + PCE 物价指数（Q3）", "高"),
    ("2026-12-04", "21:30", "💼 非农就业报告（11月）", "高"),
    ("2026-12-10", "21:30", "📊 CPI 通胀数据（11月）", "高"),
    ("2026-12-15", "21:30", "📊 PPI（11月）", "中"),
    ("2026-12-16", "21:30", "📈 零售销售（11月）", "高"),
    ("2026-12-23", "21:30", "📈 GDP 终值 + PCE（Q3）", "中"),
    ("2027-01-28", "21:30", "📈 GDP 初值（Q4）+ 非农周", "高"),
]
# FOMC 兜底（官网解析失败时使用，标注"预定"）
FOMC_FALLBACK = [("2026-12-09", "2026-12-08~09（决议北京时间 12-10 03:00）", "预定"),
                 ("2027-01-27", "2027-01-26~27（决议北京时间 01-28 03:00）", "预定"),
                 ("2027-03-17", "2027-03-16~17（决议北京时间 03-18 02:00）", "预定")]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def fetch_fomc_dates():
    """从美联储官网解析 FOMC 会议日期（含决议的北京时间）"""
    r = fetch("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", timeout=30)
    if r is None or r.status_code != 200:
        return []
    text = re.sub(r"<[^>]+>", " ", r.text)
    out = []
    year = None
    for m in re.finditer(r"(20\d{2})\s+FOMC Meetings|"
                         r"(January|February|March|April|May|June|July|August|September|"
                         r"October|November|December)\s+(\d{1,2})\s*[–—-]\s*(\d{1,2})", text):
        if m.group(1):
            year = int(m.group(1))
            continue
        if not year or year < datetime.now().year:
            continue
        mo, d1, d2 = MONTHS[m.group(2)], int(m.group(3)), int(m.group(4))
        try:
            start = datetime(year, mo, d1)
        except ValueError:
            continue
        if start < datetime.now():
            continue
        # 决议 = 第二天(d2) 14:00 美东；夏令(3-10月)北京次日 02:00，冬令 03:00
        bj_h = "02:00" if 3 <= mo <= 10 else "03:00"
        out.append({"date": start.strftime("%Y-%m-%d"),
                    "when": f"{start.strftime('%Y-%m-%d')}~{d2}（美东）",
                    "name": "🏦 美联储 FOMC 议息会议",
                    "imp": "高",
                    "note": f"利率决议：北京时间 {mo}月{d2}日 次日 {bj_h}（含鲍威尔新闻发布会）"})
    return out


def collect_fed_events(max_n=12):
    """美联储消息面大事提醒：FOMC 议息 + 重磅经济数据"""
    print("[6/6] 美联储/宏观消息面日程...")
    events = []
    fomc = fetch_fomc_dates()
    if not fomc:
        print("  FOMC 官网解析失败，使用内置日程")
        for d, w, tag in FOMC_FALLBACK:
            events.append({"date": d, "when": w, "name": "🏦 美联储 FOMC 议息会议",
                           "imp": "高", "note": f"{tag}（官网未列出，以美联储后续公告为准）"})
    else:
        events += fomc
    today = datetime.now().strftime("%Y-%m-%d")
    for d, t, name, imp in ECON_SCHEDULE:
        if d >= today:
            events.append({"date": d, "when": f"{d} {t}（北京时间）", "name": name,
                           "imp": imp, "note": "公布前市场波动加大，注意仓位"})
    events.sort(key=lambda e: e["date"])
    return events[:max_n]


# ---------------------------------------------------------------- 报告生成
# 7) 银行业：存贷款/利率数据 + 最新政策 ---------------------------------------
# 说明：LPR 官方接口（中国货币网 ags 路径）已实测 404、东财数据中心报表名不存在，
# 故采用「东财新闻多关键词搜索 + 标题解析」方案，全部带兜底展示。
RE_BANK_DATA_KW = re.compile(r"M2|社会融资|社融|人民币贷款|人民币存款|新增贷款|新增存款|存款准备金|LPR|贷款市场报价利率")
RE_BANK_NUM_CTX = re.compile(r"同比增长|同比多增|环比|余额|增加|减少|万亿|亿元|基点|BP|%|\d\.\d+")
RE_BANK_POLICY_KW = re.compile(r"银行|存款|贷款|利率|信贷|理财|资本充足|监管|房贷|降准|降息|货币政策|金融监管")
RE_BANK_POLICY_ACT = re.compile(r"政策|新规|发布|下调|上调|调整|出台|印发|通知|监管|降准|降息|改革|办法|征求意见|实施|规范|指引|管委会|公告")
RE_LPR_PAIR = re.compile(r"1\s*年期[^0-9%]{0,12}(\d\.\d+)\s*%.{0,50}?5\s*年期以上[^0-9%]{0,12}(\d\.\d+)\s*%", re.S)
RE_LPR_PAIR_REV = re.compile(r"5\s*年期以上[^0-9%]{0,12}(\d\.\d+)\s*%.{0,50}?1\s*年期[^0-9%]{0,12}(\d\.\d+)\s*%", re.S)
RE_M2_YOY = re.compile(r"M2[^0-9%]{0,15}?同比增长\s*([\d.]+)\s*%")
RE_TSF_YOY = re.compile(r"社会融资规模(?:存量)?[^0-9%]{0,20}?同比增长\s*([\d.]+)\s*%")


def collect_banking():
    """返回 (bank_stats 结构化指标, bank_data 数据快讯, bank_policy 政策资讯 5 条)"""
    print("[7/7] 银行业（存贷款数据 + 政策资讯）...")
    pool = []
    for kw, n in [("LPR", 10), ("存款利率", 10), ("金融统计", 10), ("社会融资", 10),
                  ("人民币贷款", 10), ("存款准备金", 8), ("货币政策", 10), ("金融监管总局", 10)]:
        pool += eastmoney_search(kw, n)
    pool = dedupe(sort_by_ts(pool))

    # 数据类快讯：标题含存贷款/利率关键词且带数值语境
    bank_data = [i for i in pool
                 if RE_BANK_DATA_KW.search(i["title"]) and RE_BANK_NUM_CTX.search(i["title"])][:6]

    # 政策类：银行语境 + 政策动作词，去重后取 5 条；不足时从池中含"银行"的条目补位
    used = {i["title"] for i in bank_data}
    bank_policy = [i for i in pool
                   if i["title"] not in used
                   and RE_BANK_POLICY_KW.search(i["title"]) and RE_BANK_POLICY_ACT.search(i["title"])]
    bank_policy = bank_policy[:5]
    for i in pool:
        if len(bank_policy) >= 5:
            break
        if i["title"] in used or any(i["title"] == x["title"] for x in bank_policy):
            continue
        if RE_BANK_POLICY_KW.search(i["title"]):
            bank_policy.append(i)
    bank_policy = bank_policy[:5]

    # 结构化指标：LPR（1年期/5年期以上）、M2 同比、社融存量同比
    stats = []
    for i in pool:
        text = i["title"] + " " + (i.get("summary") or "")
        m = RE_LPR_PAIR.search(text) or RE_LPR_PAIR_REV.search(text)
        if m:
            stats.append({"name": "LPR · 1年期", "value": m.group(1) + "%",
                          "note": "贷款市场报价利率", "link": i["link"]})
            stats.append({"name": "LPR · 5年期以上", "value": m.group(2) + "%",
                          "note": "房贷定价基准", "link": i["link"]})
            break
    for i in pool:
        m = RE_M2_YOY.search(i["title"])
        if m:
            stats.append({"name": "M2 同比增速", "value": m.group(1) + "%",
                          "note": "广义货币供应量", "link": i["link"]})
            break
    for i in pool:
        m = RE_TSF_YOY.search(i["title"])
        if m:
            stats.append({"name": "社融存量同比", "value": m.group(1) + "%",
                          "note": "社会融资规模存量", "link": i["link"]})
            break
    if not any(s["name"].startswith("LPR") for s in stats):
        stats.append({"name": "LPR 最新报价", "value": "—",
                      "note": "本次未能从快讯解析，点击查看中国货币网",
                      "link": "https://www.chinamoney.com.cn/chinese/bklpr/"})
    print(f"  [OK] 银行业：数据快讯 {len(bank_data)} 条 / 政策 {len(bank_policy)} 条 / 结构化指标 {len(stats)} 个")
    return stats, bank_data, bank_policy


def build_markdown(data, date_str):
    lines = [f"# 每日新闻日报 · {date_str}", ""]
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}｜数据源：新浪财经 / 华尔街见闻 / 东方财富 / 量子位 / 爱范儿 / 虎嗅 / 36氪 / GitHub Trending / 金色财经 / gate.io")
    lines.append("")

    def section(title, items, note=""):
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("_今日该来源暂无命中条目。_")
            lines.append("")
            return
        for n, i in enumerate(items, 1):
            lines.append(fmt_item(i, n))
            lines.append("")
        if note:
            lines.append(f"_{note}_")
            lines.append("")

    cd_n = sum(1 for i in data["estate"] if i.get("tag") == "成都")
    cd_hint = f"，其中成都本地 {cd_n} 条（保底 3 条{ '✅已满足' if cd_n>=3 else '⚠️未满足' }）"
    section(f"一、国内房产政策新闻（{len(data['estate'])} 条{cd_hint}）", data["estate"])
    section(f"二、科技 / AI 消息（{len(data['tech'])} 条）", data["tech"])
    gh = data["github"]
    lines.append(f"## 三、GitHub 每日 Trending 前 {len(gh)}")
    lines.append("")
    for n, i in enumerate(gh, 1):
        lines.append(f"{n}. **[{i['title']}]({i['link']})** {i.get('stars','')}")
        if i.get("summary"):
            lines.append(f"   {i['summary']}")
        lines.append("")
    section(f"四、金融要闻（{len(data['finance'])} 条）", data["finance"])
    lines.append("## 五、加密货币")
    lines.append("")
    lines.append("### 5.1 链上消息")
    lines.append("")
    for n, i in enumerate(data["chain"], 1):
        lines.append(fmt_item(i, n)); lines.append("")
    if not data["chain"]:
        lines.append("_今日暂无链上类消息命中。_"); lines.append("")
    lines.append("### 5.2 政策监管")
    lines.append("")
    for n, i in enumerate(data["crypto_policy"], 1):
        lines.append(fmt_item(i, n)); lines.append("")
    if not data["crypto_policy"]:
        lines.append("_今日暂无政策类消息命中。_"); lines.append("")
    lines.append("### 5.3 交易数据")
    lines.append("")
    for n, i in enumerate(data["trade"], 1):
        lines.append(f"{n}. {i['title']}")
        lines.append("")
    # 六、美联储/宏观消息面日程
    lines.append("## 六、美联储 / 宏观消息面日程提醒")
    lines.append("")
    lines.append("> FOMC 日期来自美联储官网（federalreserve.gov）；经济数据日程为内置表（北京时间，每季度更新）")
    lines.append("")
    for n, e in enumerate(data.get("fed", []), 1):
        dd = (datetime.strptime(e["date"], "%Y-%m-%d") - datetime.now()).days
        cd = "🚨 就是今天" if dd == 0 else ("明天" if dd == 1 else f"还有 {dd} 天")
        lines.append(f"{n}. **{e['name']}**（{e['imp']}影响）")
        lines.append(f"   时间：{e['when']}｜**{cd}**")
        if e.get("note"):
            lines.append(f"   {e['note']}")
        lines.append("")
    if not data.get("fed"):
        lines.append("_日程获取失败。_")
        lines.append("")
    # 七、银行业
    lines.append("## 七、银行业（存贷款数据 + 最新政策）")
    lines.append("")
    lines.append("> LPR 官方源为中国货币网（chinamoney.com.cn）；指标数值从最新财经快讯解析，如未解析到以原文为准")
    lines.append("")
    lines.append("### 7.1 存贷款 / 利率数据")
    lines.append("")
    for n, s in enumerate(data.get("bank_stats", []), 1):
        src = f"｜[查看]({s['link']})" if s.get("link") else ""
        lines.append(f"{n}. **{s['name']}：{s['value']}**（{s.get('note','')}）{src}")
        lines.append("")
    for n, i in enumerate(data.get("bank_data", []), 1):
        lines.append(fmt_item(i, n))
        lines.append("")
    if not data.get("bank_data"):
        lines.append("_今日暂无数据类快讯命中。_")
        lines.append("")
    lines.append("### 7.2 银行最新政策")
    lines.append("")
    for n, i in enumerate(data.get("bank_policy", []), 1):
        lines.append(fmt_item(i, n))
        lines.append("")
    if not data.get("bank_policy"):
        lines.append("_今日暂无政策类消息命中。_")
        lines.append("")
    return "\n".join(lines)


def _source_name(link: str) -> str:
    """从链接域名推断来源名"""
    m = {
        "eastmoney.com": "东方财富", "wallstreetcn.com": "华尔街见闻", "sina": "新浪财经",
        "qbitai.com": "量子位", "ifanr.com": "爱范儿", "huxiu.com": "虎嗅",
        "36kr.com": "36氪", "github.com": "GitHub", "jinse": "金色财经",
        "gate.io": "gate.io", "alternative.me": "恐慌贪婪指数",
    }
    host = (link or "").split("/")[2] if "//" in (link or "") else ""
    for k, v in m.items():
        if k in host:
            return v
    return host or "快讯"


def build_html(data, date_str, md_path_name, is_evening=False):
    def card(i, n, cls=""):
        ts = i.get("ts_str") or ts_to_str(i.get("ts"))
        title = i["title"]
        link = i.get("link") or ""
        t_html = f"<a href='{link}' target='_blank'>{title}</a>" if link else title
        summ = i.get("summary") or ""
        s_html = f"<div class='s'>{summ}</div>" if summ and len(summ) > 15 else ""
        src = _source_name(link)
        tag = f"<span class='tagcd'>{i['tag']}</span>" if i.get("tag") else ""
        meta = f"<span class='src'>{src}</span><span>{ts}</span>" if ts else f"<span class='src'>{src}</span>"
        return (f"<div class='card {cls}'><div class='ct'><span class='num'>{n}</span>"
                f"<div class='tt'>{tag}{t_html}</div></div>{s_html}<div class='cm'>{meta}</div></div>")

    def cards(items, empty_hint="今日该板块暂无命中条目", numbered=True):
        if not items:
            return f"<div class='empty'>{empty_hint}</div>"
        return "".join(card(i, n if numbered else "•") for n, i in enumerate(items, 1))

    gh = "".join(
        f"<div class='card'><div class='ct'><span class='num'>{n}</span>"
        f"<div class='tt'><a href='{i['link']}' target='_blank'>{i['title']}</a></div></div>"
        f"<div class='s'>{i.get('summary','')}</div>"
        f"<div class='cm'><span class='tag'>{i.get('stars','')}</span>"
        f"<span class='src'>GitHub Trending</span></div></div>"
        for n, i in enumerate(data["github"], 1))
    # 交易数据：拆成 价格/涨跌/成交额 三段展示的统计卡
    trade = ""
    for i in data["trade"]:
        title = i["title"]
        if "：" in title and "24h" in title:
            name, rest = title.split("：", 1)
            price, rest2 = rest.split("USDT，", 1)
            parts = rest2.split("，")
            chg, vol = parts[0].replace("24h ", ""), parts[1]
            up = "+" in chg
            trade += (f"<div class='stat'><div class='sn'>{name}</div>"
                      f"<div class='sp'>{price}</div>"
                      f"<div class='sc {'up' if up else 'down'}'>{chg}</div>"
                      f"<div class='sv'>{vol}</div></div>")
        else:
            trade += f"<div class='stat wide'><div class='sn'>{title}</div></div>"

    # 美联储日程时间线卡
    fed = ""
    for n, e in enumerate(data.get("fed", []), 1):
        try:
            dd = (datetime.strptime(e["date"], "%Y-%m-%d") - datetime.now()).days
        except Exception:
            dd = 99
        cd = "🚨 今天" if dd == 0 else ("明天" if dd == 1 else f"{dd}天后")
        imp_cls = "hi" if e.get("imp") == "高" else "mid"
        fed += (f"<div class='card fed'><div class='ct'><span class='num'>{n}</span>"
                f"<div class='tt'>{e['name']} <span class='tag {imp_cls}'>{e['imp']}影响</span></div></div>"
                f"<div class='s'>{e['when']}</div>"
                f"<div class='cm'><span class='tag d'>⏳ {cd}</span></div>"
                f"<div class='note'>{e.get('note','')}</div></div>")

    cd_n = sum(1 for i in data["estate"] if i.get("tag") == "成都")
    cd_banner = (f"<div class='banner'>📍 成都本地政策 {cd_n} 条（保底 3 条）"
                 f"{'✅' if cd_n >= 3 else '⚠️ 今日暂不足，已尽最大采集'}"
                 f"｜绿标【成都】卡片即本地条目</div>")

    # 银行业：指标 stat 卡
    bank_stats_html = "".join(
        f"<div class='stat'><div class='sn'>{s['name']}</div>"
        f"<div class='sp'>{s['value']}</div>"
        f"<div class='sv'>{s.get('note','')}</div></div>"
        for s in data.get("bank_stats", []))

    tabs = [
        ("estate", "🏠 房产政策", "#f59e0b", cd_banner + cards(data["estate"])),
        ("tech", "🤖 科技 / AI", "#3b82f6", cards(data["tech"])),
        ("github", "⭐ GitHub 榜", "#8b5cf6", gh),
        ("finance", "💰 金融要闻", "#10b981", cards(data["finance"])),
        ("banking", "🏦 银行业", "#14b8a6",
         f"""<div class='sub'><h3>存贷款 / 利率数据 <span class='cnt'>{len(data.get('bank_stats',[]))}项指标</span></h3><div class='stats'>{bank_stats_html}</div>{cards(data.get('bank_data',[]), '今日暂无数据类快讯命中')}</div>
             <div class='sub'><h3>银行最新政策 <span class='cnt'>{len(data.get('bank_policy',[]))}条</span></h3>{cards(data.get('bank_policy',[]), '今日暂无政策类消息命中')}</div>"""),
        ("fed", "📅 美联储日程", "#dc2626", fed or "<div class='empty'>日程获取失败</div>"),
        ("crypto", "🪙 加密货币", "#f97316",
         f"""<div class='sub'><h3>链上消息 <span class='cnt'>{len(data['chain'])}条</span></h3>{cards(data['chain'], '今日暂无链上类消息命中')}</div>
             <div class='sub'><h3>政策监管 <span class='cnt'>{len(data['crypto_policy'])}条</span></h3>{cards(data['crypto_policy'], '今日暂无政策类消息命中')}</div>
             <div class='sub'><h3>交易数据 <span class='cnt'>{len(data['trade'])}条</span></h3><div class='stats'>{trade}</div></div>"""),
    ]
    counts = [len(data["estate"]), len(data["tech"]), len(data["github"]),
              len(data["finance"]),
              len(data.get("bank_stats", [])) + len(data.get("bank_data", [])) + len(data.get("bank_policy", [])),
              len(data.get("fed", [])),
              len(data["chain"]) + len(data["crypto_policy"]) + len(data["trade"])]
    nav = "".join(
        f"<button class='tab {'active' if k=='estate' else ''}' data-t='{k}' "
        f"style='--ac:{c}'>{label}<span class='badge'>{count}</span></button>"
        for (k, label, c, _), count in zip(tabs, counts))
    panels = "".join(
        f"<div class='panel' id='p-{k}' style='display:{'grid' if k=='estate' else 'none'}'>{body}</div>"
        for k, _, _, body in tabs)

    css = """
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#eef1f5;color:#1f2937;line-height:1.7}
    header{position:sticky;top:0;z-index:10;background:#ffffffee;backdrop-filter:blur(8px);
           border-bottom:1px solid #e5e7eb;padding:14px 20px 0}
    .hd{max-width:1080px;margin:0 auto;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
    h1{font-size:20px;color:#111827}
    .date{color:#6b7280;font-size:13px}
    nav{max-width:1080px;margin:10px auto 0;display:flex;gap:8px;overflow-x:auto}
    .tab{--ac:#3b82f6;flex:0 0 auto;display:flex;align-items:center;gap:6px;border:none;cursor:pointer;
         background:#f3f4f6;color:#374151;font-size:14px;font-weight:600;padding:9px 16px;
         border-radius:10px 10px 0 0;border-bottom:3px solid transparent}
    .tab:hover{background:#e8ecf1}
    .tab.active{background:#fff;color:var(--ac);border-bottom-color:var(--ac)}
    .badge{background:var(--ac);color:#fff;border-radius:9px;font-size:11px;padding:0 7px;font-weight:700}
    main{max-width:1080px;margin:0 auto;padding:18px 20px 40px}
    .panel{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;align-items:start}
    .sub{grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px}
    .sub h3{font-size:15px;color:#374151;margin:10px 0 2px;
         border-left:4px solid #f97316;padding-left:10px}
    .cnt{font-size:12px;color:#9ca3af;font-weight:400}
    .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;
          box-shadow:0 1px 2px rgba(0,0,0,.05);transition:box-shadow .15s,transform .15s}
    .card:hover{box-shadow:0 6px 16px rgba(0,0,0,.09);transform:translateY(-1px)}
    .ct{display:flex;gap:10px;align-items:flex-start}
    .num{flex:0 0 auto;min-width:22px;height:22px;border-radius:6px;background:#f3f4f6;color:#6b7280;
         font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:2px}
    .tt{font-weight:600;font-size:14.5px}
    .tt a{color:#1f2937;text-decoration:none}
    .tt a:hover{color:#2563eb}
    .s{font-size:13px;color:#6b7280;margin-top:8px;display:-webkit-box;-webkit-line-clamp:3;
       -webkit-box-orient:vertical;overflow:hidden}
    .cm{margin-top:10px;font-size:12px;color:#9ca3af;display:flex;gap:10px;align-items:center}
    .src{background:#f3f4f6;border-radius:5px;padding:0 7px}
    .tag{background:#eff6ff;color:#7c3aed;border-radius:5px;padding:0 7px;font-weight:700}
    .tag.hi{background:#fef2f2;color:#dc2626}.tag.mid{background:#fffbeb;color:#b45309}
    .tag.d{background:#eff6ff;color:#2563eb}
    .tagcd{background:#ecfdf5;color:#059669;border-radius:5px;padding:0 7px;font-size:12px;
           font-weight:700;margin-right:6px}
    .card.fed .note{margin-top:8px;font-size:12px;color:#9ca3af;border-top:1px dashed #f3f4f6;padding-top:8px}
    .banner{grid-column:1/-1;background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;
            border-radius:10px;padding:10px 16px;font-size:13.5px}
    .empty{grid-column:1/-1;background:#fff;border:1px dashed #d1d5db;border-radius:12px;
           padding:24px;text-align:center;color:#9ca3af}
    .stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
    .stat{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:12px 14px;text-align:center}
    .stat.wide{grid-column:1/-1;text-align:left;font-size:14px;font-weight:600}
    .sn{font-size:13px;color:#6b7280;font-weight:700}
    .sp{font-size:18px;font-weight:800;margin:2px 0;color:#111827}
    .sc{font-size:13px;font-weight:700}
    .sc.up{color:#dc2626}.sc.down{color:#059669}
    .sv{font-size:11px;color:#9ca3af}
    .views{font-size:12px;color:#6b7280;background:#fff;border:1px solid #e5e7eb;
           border-radius:999px;padding:3px 12px;margin-left:10px;font-weight:600}
    footer{max-width:1080px;margin:0 auto;padding:0 20px 30px;color:#9ca3af;font-size:12px}
    """
    counter_js = build_counter_js(date_str, is_evening)
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日新闻日报 · {date_str}</title><style>{css}</style></head><body>
<header>
  <div class="hd"><h1>📰 每日新闻日报</h1><span class="date">{date_str} · 生成于 {datetime.now().strftime('%H:%M')}</span><span class="views" id="pv-badge">👁 访问量 …</span></div>
  <nav>{nav}</nav>
</header>
<main>
{panels}
</main>
<footer>数据源：新浪财经 · 华尔街见闻 · 东方财富 · 量子位 · 爱范儿 · 虎嗅 · 36氪 · GitHub Trending · 金色财经 · gate.io · 中国货币网｜点击各板块标签切换，卡片点击标题查看原文</footer>
<script>
document.querySelectorAll('.tab').forEach(b=>{{
  b.addEventListener('click',()=>{{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.style.display='none');
    b.classList.add('active');
    document.getElementById('p-'+b.dataset.t).style.display='grid';
    window.scrollTo({{top:0}});
  }});
}});
{counter_js}
</script>
</body></html>"""
    return html


# 资料库「日报访问统计」表 ID（页面每次打开自动 +1；本地文件无 SDK 时自动降级显示）
VIEW_DATABASE_ID = ""


def build_counter_js(date_str, is_evening):
    """生成访问量统计 JS：日期+版别定位记录，存在则 +1，不存在则建记录。"""
    ver = "晚间版" if is_evening else "晨报"
    base_date = date_str.replace("（晚间版）", "")
    if not VIEW_DATABASE_ID:
        return ""
    return f"""
(function(){{
  var DB_ID='{VIEW_DATABASE_ID}';
  var D='{base_date}';
  var VER='{ver}';
  var badge=document.getElementById('pv-badge');
  if(!badge) return;
  function set(t){{ badge.textContent=t; }}
  try {{
    var db=window.__SMART_PAGE__ && window.__SMART_PAGE__.database;
    if(!db || !db.query) {{ set('👁 本地预览'); return; }}
    var flt={{and:[
      {{property:{{property:'日期',text:{{equals:D}}}}}},
      {{property:{{property:'版别',text:{{equals:VER}}}}}}
    ]}};
    function now(){{
      return new Date().toISOString().slice(0,19).replace('T',' ');
    }}
    db.query({{databaseId:DB_ID,filter:flt,pageSize:1}}).then(function(r){{
      var rec=(r.results||[])[0];
      if(rec){{
        var n=(typeof rec['访问量']==='number'?rec['访问量']:0)+1;
        return db.updateRecord({{databaseId:DB_ID,recordId:rec._id,
          properties:{{'访问量':{{number:n}},'最近访问':{{text:now()}}}}}}).then(function(){{return n;}});
      }}
      return db.addRecord({{databaseId:DB_ID,
        properties:{{'日期':{{text:D}},'版别':{{text:VER}},'访问量':{{number:1}},'最近访问':{{text:now()}}}}}}).then(function(){{return 1;}});
    }}).then(function(n){{ if(n!=null) set('👁 访问量 '+n); }})
      .catch(function(){{ set('👁 访问量 ·'); }});
  }} catch(e) {{ set('👁 访问量 ·'); }}
}})();
"""


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now()
    # 版本自动判定：12:00 前 = 晨报（沿用原文件名），12:00 后 = 晚间版（独立文件名）
    is_evening = now.hour >= 12
    suffix = "_晚间版" if is_evening else ""
    date_str = now.strftime("%Y-%m-%d")
    title_str = date_str + ("（晚间版）" if is_evening else "")
    print(f"=== 每日新闻抓取 {title_str} ===")

    data = {
        "estate": collect_estate(10),
        "tech": collect_tech(20),
        "github": collect_github(10),
        "finance": collect_finance(15),
    }
    chain, crypto_policy, trade = collect_crypto()
    data.update({"chain": chain, "crypto_policy": crypto_policy, "trade": trade,
                 "fed": collect_fed_events(12)})
    b_stats, b_data, b_policy = collect_banking()
    data.update({"bank_stats": b_stats, "bank_data": b_data, "bank_policy": b_policy})

    counts = {k: len(v) for k, v in data.items()}
    print("\n=== 抓取结果 ===")
    print(json.dumps(counts, ensure_ascii=False))

    md = build_markdown(data, title_str)
    html = build_html(data, title_str, "", is_evening)
    md_path = os.path.join(out_dir, f"新闻日报{suffix}_{date_str}.md")
    html_path = os.path.join(out_dir, f"新闻日报{suffix}_{date_str}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n已生成：\n  {md_path}\n  {html_path}")
    return md_path, html_path


if __name__ == "__main__":
    main()

"""بوت أخبار الذكاء الاصطناعي — ملخص يومي وتنبيهات فورية بالإيميل.

الاستخدام:
    python digest.py daily     # الملخص اليومي
    python digest.py alert     # فحص الإطلاقات الكبيرة
متغيرات البيئة: GEMINI_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, TO_EMAIL (اختياري),
GEMINI_MODEL (اختياري), DRY_RUN=1 (يحفظ الإيميل في out/ بدل ما يرسله ولا يعدّل الحالة).
بدون اعتماديات خارجية — مكتبة بايثون القياسية فقط.
"""
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from pathlib import Path

import config

ROOT = Path(__file__).parent

# تحميل .env للتشغيل المحلي (في GitHub Actions تأتي من الأسرار)
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _k, _, _v = _line.partition("=")
        if _k.strip() and not _k.startswith("#") and _v.strip():
            os.environ.setdefault(_k.strip(), _v.strip())
STATE_FILE = ROOT / "state" / "seen.json"
UA = "Mozilla/5.0 (ai-news-digest; +https://github.com)"
DRY_RUN = os.environ.get("DRY_RUN") == "1"
NOW = datetime.now(timezone.utc)
LOCAL_TZ = timezone(timedelta(hours=config.TZ_OFFSET_HOURS))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- HTTP ----------

def http_get(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        log(f"  ✗ {url[:70]}: {e}")
        return None


def url_ok(url):
    if not url or not url.startswith("http"):
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code in (401, 403)  # الصفحة موجودة لكنها تحجب البوتات
    except Exception:
        return False


# ---------- المصادر ----------

def _tag(el):
    return el.tag.split("}")[-1]


def _child_text(el, *names):
    for c in el:
        if _tag(c) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def _parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(raw, source):
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        log(f"  ✗ {source}: XML غير صالح ({e})")
        return items
    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        link = _child_text(el, "link")
        if not link:
            for c in el:
                if _tag(c) == "link" and c.get("href"):
                    link = c.get("href")
                    break
        summary = re.sub(r"<[^>]+>", " ", _child_text(el, "description", "summary", "content"))
        items.append({
            "source": source,
            "title": html.unescape(_child_text(el, "title")),
            "url": link,
            "summary": html.unescape(re.sub(r"\s+", " ", summary)).strip()[:400],
            "published": _parse_date(_child_text(el, "pubDate", "published", "updated", "date")),
        })
    return items


def hn_items(since):
    q = urllib.parse.urlencode({
        "query": config.HN_QUERY, "optionalWords": config.HN_QUERY, "tags": "story",
        "numericFilters": f"points>{config.HN_MIN_POINTS},created_at_i>{int(since.timestamp())}",
    })
    raw = http_get(f"https://hn.algolia.com/api/v1/search?{q}")
    if not raw:
        return []
    out = []
    for h in json.loads(raw).get("hits", []):
        out.append({
            "source": "Hacker News",
            "title": h.get("title", ""),
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "summary": f"{h.get('points', 0)} نقطة على Hacker News",
            "published": datetime.fromtimestamp(h.get("created_at_i", 0), timezone.utc),
        })
    return out


def github_trending():
    """المستودعات الأكثر حصولًا على نجوم اليوم من github.com/trending."""
    repos = []
    for since in ("daily", "weekly"):
        raw = http_get(f"https://github.com/trending?since={since}")
        if not raw:
            continue
        for a in raw.decode("utf-8", "ignore").split('<article class="Box-row">')[1:]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', a)
            if not m or any(r["name"] == m.group(1) for r in repos):
                continue
            d = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', a, re.S)
            s = re.search(r'([\d,]+) stars (today|this week)', a)
            t = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', a, re.S)
            lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', a)
            repos.append({
                "name": m.group(1), "url": f"https://github.com/{m.group(1)}",
                "desc": html.unescape(re.sub(r"<[^>]+>", "", d.group(1))).strip() if d else "",
                "stars_new": s.group(1) if s else "", "period": "اليوم" if since == "daily" else "هالأسبوع",
                "stars": t.group(1) if t else "", "lang": lang.group(1) if lang else "",
            })
        if len(repos) >= 15:
            break
    log(f"  ✓ GitHub Trending: {len(repos)}")
    return repos


def readme_excerpt(name):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github.raw"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{name}/readme", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode("utf-8", "ignore")
    except Exception:
        return ""
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", text)  # بدون صور ووسوم
    return re.sub(r"\s+", " ", text)[:2500]


def collect_feeds(since, kinds=None):
    items = []
    for name, url, kind in config.FEEDS:
        if kinds and kind not in kinds:
            continue
        raw = http_get(url)
        if not raw:
            continue
        fresh = [i for i in parse_feed(raw, name) if i["published"] and i["published"] >= since]
        log(f"  ✓ {name}: {len(fresh)}")
        items += fresh[:15]
    if not kinds:
        hn = hn_items(since)
        log(f"  ✓ Hacker News: {len(hn)}")
        items += hn
    return items


# ---------- Gemini ----------

def gemini(prompt, search=False, json_out=False):
    key = os.environ["GEMINI_API_KEY"]
    # إذا كان موديل مزحوم (503) أو تجاوز الحد (429) نعيد المحاولة ثم ننتقل للي بعده
    models = [m for m in (os.environ.get("GEMINI_MODEL"), *config.GEMINI_MODELS) if m]
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    if search:
        body["tools"] = [{"google_search": {}}]
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last_err = None
    for model in dict.fromkeys(models):
        data = None
        for attempt in range(2):
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read())
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                code = getattr(e, "code", 0)
                last_err = f"{model}: {code or e}"
                log("  ✗ Gemini", last_err)
                if code not in (429, 500, 503, 0):
                    break
                time.sleep(15)
        if data is None:
            continue
        cand = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        chunks = [c.get("web", {}) for c in cand.get("groundingMetadata", {}).get("groundingChunks", [])]
        return text, chunks
    raise RuntimeError(f"Gemini فشل: {last_err}")


def extract_json(text):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    return None


def grounded_search(hours, focus):
    accounts = ", ".join("@" + a for a in config.X_ACCOUNTS)
    prompt = f"""الوقت الحالي (UTC): {NOW:%Y-%m-%d %H:%M}.
ابحث في جوجل عن أخبار الذكاء الاصطناعي المنشورة خلال آخر {hours} ساعة فقط، وركّز على منصة X (تويتر)
ومنشورات هذه الحسابات: {accounts}، وعلى ما يتداوله الناس في X من ترندات.
{focus}
تجاهل أي خبر أقدم من {hours} ساعة أو لا تستطيع التحقق من تاريخه.
أرجع JSON فقط بهذا الشكل (مصفوفة، حتى ١٥ عنصرًا):
[{{"title": "عنوان قصير بالإنجليزية", "summary": "جملة توضح الخبر", "url": "الرابط الأصلي (تغريدة أو مقال)", "source": "اسم المصدر أو @الحساب", "date": "YYYY-MM-DD"}}]"""
    try:
        text, chunks = gemini(prompt, search=True)
    except Exception as e:
        log("  ✗ بحث Gemini:", e)
        return []
    items = extract_json(text) or []
    if not isinstance(items, list):
        return []
    fallback = [c.get("uri") for c in chunks if c.get("uri")]
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not it.get("title"):
            continue
        url = it.get("url", "")
        if not url_ok(url):
            url = fallback[i] if i < len(fallback) else \
                "https://www.google.com/search?q=" + urllib.parse.quote(it["title"])
        out.append({"source": it.get("source", "بحث"), "title": it["title"], "url": url,
                    "summary": it.get("summary", ""), "published": None})
    log(f"  ✓ بحث Gemini/X: {len(out)}")
    return out


# ---------- الحالة ----------

def load_state():
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    s.setdefault("urls", {})
    s.setdefault("titles", {})
    s.setdefault("alerts", {})
    return s


def save_state(s):
    if DRY_RUN:
        return
    cutoff = (NOW - timedelta(days=14)).isoformat()
    s["urls"] = {k: v for k, v in s["urls"].items() if v >= cutoff}
    s["titles"] = {k: v for k, v in s["titles"].items() if v >= cutoff}
    s["alerts"] = {k: v for k, v in s["alerts"].items() if k >= cutoff[:10]}
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def norm_title(t):
    return re.sub(r"\W+", " ", (t or "").lower()).strip()[:80]


def is_seen(s, item):
    return item.get("url") in s["urls"] or norm_title(item.get("title")) in s["titles"]


def mark_seen(s, item):
    if item.get("url"):
        s["urls"][item["url"]] = NOW.isoformat()
    if item.get("title"):
        s["titles"][norm_title(item["title"])] = NOW.isoformat()


# ---------- الإيميل ----------

CSS = """body{margin:0;background:#f4f5f7;font-family:Tahoma,Arial,sans-serif;color:#1f2328}
.w{max-width:640px;margin:0 auto;padding:20px 14px}
.c{background:#fff;border-radius:12px;padding:20px 22px;margin-bottom:14px}
h1{font-size:20px;margin:0 0 4px}.d{color:#6b7280;font-size:13px}
h2{font-size:16px;margin:0 0 12px;border-bottom:1px solid #eee;padding-bottom:8px}
.i{margin:0 0 14px}.i a{color:#0b57d0;font-weight:bold;text-decoration:none;font-size:15px}
.i p{margin:4px 0 0;line-height:1.7;font-size:14px}.s{color:#6b7280;font-size:12px}
.b{background:#fff8e1;border-right:4px solid #f5a623}
.t{background:#eef6ff;border-right:4px solid #0b57d0}
.i a.try{display:inline-block;margin-top:8px;background:#16a34a;color:#fff;font-size:13px;
padding:6px 14px;border-radius:8px}.f{color:#9ca3af;font-size:12px;text-align:center}"""


def item_html(it):
    return (f'<div class="i"><a href="{html.escape(it.get("url", ""))}">{html.escape(it.get("title", ""))}</a>'
            f'<p>{html.escape(it.get("summary", ""))}</p>'
            + (f'<p style="background:#f0fdf4;padding:8px 10px;border-radius:8px">💡 <b>فايدته لك:</b> '
               f'{html.escape(it["benefit"])}</p>' if it.get("benefit") else "")
            + (f'<p style="font-size:13px">التثبيت: <code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;'
               f'direction:ltr;display:inline-block">{html.escape(it["install"])}</code></p>' if it.get("install") else "")
            + f'<span class="s">{html.escape(it.get("source", ""))}</span>'
            + (f'<br><a class="try" style="background:#16a34a;color:#fff;padding:6px 14px;border-radius:8px" '
               f'href="{html.escape(it["try_url"])}">🧪 جرّب {html.escape(it.get("product", ""))}</a>'
               if it.get("try_url") else "") + '</div>')


def page(title, sub, blocks):
    return (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body dir="rtl"><div class="w"><div class="c"><h1>{html.escape(title)}</h1>'
            f'<div class="d">{html.escape(sub)}</div></div>{"".join(blocks)}'
            f'<div class="f">بوت أخبار الذكاء الاصطناعي · GitHub Actions</div></div></body></html>')


PAGE_CSS = """:root{--bg:#f4f5f7;--card:#fff;--ink:#1f2328;--mute:#6b7280;--link:#0b57d0;--soft:#f0fdf4;--line:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#1a1d23;--ink:#e6e8eb;--mute:#9aa1ab;--link:#7fb0ff;
--soft:#14261b;--line:#2a2f37}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,Arial,sans-serif}
.w{max-width:720px;margin:0 auto;padding:16px}.c{background:var(--card);border-radius:14px;padding:18px 20px;margin-bottom:14px}
h1{font-size:20px;margin:0 0 4px}.d{color:var(--mute);font-size:13px}h2{font-size:16px;margin:0 0 12px}
.brief{line-height:1.8;margin:0}
.tabs{display:flex;gap:8px;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:1}
.tabs a{flex:1;text-align:center;padding:12px;border-radius:12px;background:var(--card);color:var(--ink);
text-decoration:none;font-weight:bold;border:2px solid transparent}
.tabs a.on{border-color:var(--link);color:var(--link)}
.tab{display:none}.tab.on{display:block}
.i{padding:0 0 14px;margin:0 0 14px;border-bottom:1px solid var(--line)}.i:last-child{border:0;margin:0;padding:0}
.i>a{color:var(--link);font-weight:bold;text-decoration:none;font-size:15px}
.i p{margin:6px 0 0;line-height:1.75;font-size:14px}.s{color:var(--mute);font-size:12px}
.ben{background:var(--soft);padding:8px 10px;border-radius:8px}
code{background:var(--bg);padding:2px 6px;border-radius:4px;direction:ltr;display:inline-block;word-break:break-all}
a.try{display:inline-block;margin-top:8px;background:#16a34a;color:#fff;padding:6px 14px;border-radius:8px;
text-decoration:none;font-size:13px}.f{color:var(--mute);font-size:12px;text-align:center}"""


def web_item(it):
    return (f'<div class="i"><a href="{html.escape(it.get("url", ""))}">{html.escape(it.get("title", ""))}</a>'
            f'<p>{html.escape(it.get("summary", ""))}</p>'
            + (f'<p class="ben">💡 <b>فايدته لك:</b> {html.escape(it["benefit"])}</p>' if it.get("benefit") else "")
            + (f'<p>التثبيت: <code>{html.escape(it["install"])}</code></p>' if it.get("install") else "")
            + f'<span class="s">{html.escape(it.get("source", ""))}</span>'
            + (f'<br><a class="try" href="{html.escape(it["try_url"])}">🧪 جرّب {html.escape(it.get("product", ""))}</a>'
               if it.get("try_url") else "") + '</div>')


def write_web_page(date, brief, sections, repos):
    """يكتب صفحة اليوم في docs/d/ وينسخها كـ docs/index.html، ويرجّع رابطها."""
    news = "".join(f'<div class="c"><h2>{html.escape(s["name"])}</h2>{"".join(web_item(i) for i in s["items"])}</div>'
                   for s in sections)
    gh = (f'<div class="c"><h2>🐙 الأعلى نجمة في GitHub</h2>{"".join(web_item(r) for r in repos)}</div>'
          if repos else '<div class="c"><p>ما فيه مستودعات جديدة اليوم.</p></div>')
    n_news = sum(len(s["items"]) for s in sections)
    doc = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>أخبار الذكاء الاصطناعي {date}</title>
<style>{PAGE_CSS}</style></head><body><div class="w">
<div class="c"><h1>أخبار الذكاء الاصطناعي</h1><div class="d">{date}</div></div>
<div class="c" style="background:#fff8e1;color:#1f2328"><h2>💡 وش يهمك اليوم</h2><p class="brief">{html.escape(brief)}</p></div>
<div class="tabs"><a href="#news" data-t="news">📰 الأخبار ({n_news})</a><a href="#github" data-t="github">🐙 GitHub ({len(repos)})</a></div>
<div class="tab" id="t-news">{news}</div><div class="tab" id="t-github">{gh}</div>
<div class="f">بوت أخبار الذكاء الاصطناعي</div></div>
<script>
function show(){{var t=location.hash==="#github"?"github":"news";
document.querySelectorAll(".tab").forEach(function(e){{e.classList.toggle("on",e.id==="t-"+t)}});
document.querySelectorAll(".tabs a").forEach(function(e){{e.classList.toggle("on",e.dataset.t===t)}});}}
addEventListener("hashchange",show);show();
</script></body></html>"""
    docs = (ROOT / "out" / "site") if DRY_RUN else (ROOT / "docs")
    (docs / "d").mkdir(parents=True, exist_ok=True)
    (docs / "d" / f"{date}.html").write_text(doc, encoding="utf-8")
    (docs / "index.html").write_text(doc, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    log(f"  ✓ صفحة الويب: {docs / 'd' / (date + '.html')}")
    base = os.environ.get("PAGE_URL") or config.PAGE_URL
    return f"{base.rstrip('/')}/d/{date}.html"


def short_email(date, brief, url, n_news, n_repos):
    btn = ('<td style="padding:6px"><a href="{href}" style="display:block;background:{bg};color:#fff;text-decoration:none;'
           'font-weight:bold;font-size:16px;padding:16px 10px;border-radius:12px;text-align:center">{label}</a></td>')
    return (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"></head>'
            f'<body dir="rtl" style="margin:0;background:#f4f5f7;font-family:Tahoma,Arial,sans-serif;color:#1f2328">'
            f'<div style="max-width:560px;margin:0 auto;padding:20px 14px">'
            f'<div style="background:#fff;border-radius:12px;padding:20px 22px">'
            f'<h1 style="font-size:19px;margin:0 0 4px">📰 أخبار الذكاء الاصطناعي</h1>'
            f'<div style="color:#6b7280;font-size:13px;margin-bottom:14px">{date}</div>'
            f'<p style="line-height:1.8;margin:0 0 16px">💡 {html.escape(brief)}</p>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>'
            + btn.format(href=html.escape(url + "#news"), bg="#0b57d0", label=f"📰 الأخبار ({n_news})")
            + btn.format(href=html.escape(url + "#github"), bg="#24292f", label=f"🐙 GitHub ({n_repos})")
            + '</tr></table></div></div></body></html>')


def send_email(subject, html_body, text_body):
    if os.environ.get("DEFER_EMAIL") == "1" and not DRY_RUN:
        # يُرسل لاحقًا بـ `python digest.py send` بعد ما تنشر الصفحة
        (ROOT / "out").mkdir(exist_ok=True)
        (ROOT / "out" / "pending.json").write_text(
            json.dumps({"subject": subject, "html": html_body, "text": text_body}, ensure_ascii=False), encoding="utf-8")
        log("  ✓ الإيميل محفوظ للإرسال بعد نشر الصفحة")
        return
    if DRY_RUN:
        out = ROOT / "out"
        out.mkdir(exist_ok=True)
        f = out / f"{NOW:%Y%m%d-%H%M}-{sys.argv[1] if len(sys.argv) > 1 else 'daily'}.html"
        f.write_text(html_body, encoding="utf-8")
        log(f"DRY_RUN — حُفظ الإيميل في {f}")
        return
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    to = os.environ.get("TO_EMAIL") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"أخبار الذكاء الاصطناعي <{user}>", to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    log(f"✓ أُرسل الإيميل إلى {to}")


def to_text(sections):
    lines = []
    for sec in sections:
        lines.append(f"\n{sec['name']}\n")
        for it in sec["items"]:
            lines.append(f"• {it['title']}\n  {it['summary']}\n  {it['url']}")
            if it.get("benefit"):
                lines.append(f"  💡 فايدته لك: {it['benefit']}")
            if it.get("install"):
                lines.append(f"  التثبيت: {it['install']}")
            if it.get("try_url"):
                lines.append(f"  🧪 جرّبه: {it['try_url']}")
    return "\n".join(lines)


# ---------- الأوضاع ----------

def add_try_links(entries):
    """لكل خبر عن شي ينجرّب (موديل، موقع، أداة)، يدور الرابط الرسمي اللي تجربه منه."""
    wanted = [e for e in entries if e.get("product")]
    if not wanted:
        return
    listing = "\n".join(f"{i}. {e['product']} — {e['title']}" for i, e in enumerate(wanted))
    prompt = f"""لكل منتج ذكاء اصطناعي في القائمة، ابحث في جوجل عن الرابط الرسمي اللي يقدر المستخدم يجرّبه منه الحين:
صفحة التطبيق أو الموقع، أو الـplayground، أو صفحة الموديل على Hugging Face أو OpenRouter أو AI Studio.
لا تعطي رابط خبر أو مقال. إذا ما هو متاح للتجربة للعامة، اكتب null.
{listing}
أرجع JSON فقط: [{{"n": 0, "try_url": "https://..."}}]"""
    try:
        text, _ = gemini(prompt, search=True)
    except Exception as e:
        log("  ✗ روابط التجربة:", e)
        return
    for r in extract_json(text) or []:
        if not isinstance(r, dict):
            continue
        n, u = r.get("n"), r.get("try_url")
        if isinstance(n, int) and 0 <= n < len(wanted) and u and "vertexaisearch" not in u and url_ok(u):
            wanted[n]["try_url"] = u
    log(f"  ✓ روابط التجربة: {sum(1 for e in wanted if e.get('try_url'))}/{len(wanted)}")


def compact(items):
    return [{"id": i, "title": it["title"], "summary": it["summary"][:300], "source": it["source"],
             "date": it["published"].strftime("%Y-%m-%d %H:%M") if it.get("published") else ""}
            for i, it in enumerate(items)]


def github_section(state):
    """أعلى المستودعات نجومًا اليوم، مع شرح وش فايدتها لك لو ثبّتها. ما يتكرر المستودع خلال أسبوعين."""
    repos = [r for r in github_trending() if r["url"] not in state["urls"]]
    if not repos:
        return []
    for r in repos:
        r["readme"] = readme_excerpt(r["name"])
    listing = [{"id": i, "name": r["name"], "desc": r["desc"], "lang": r["lang"],
                "stars_new": r["stars_new"], "readme": r["readme"]} for i, r in enumerate(repos)]
    prompt = f"""هذه المستودعات الأعلى حصولًا على نجوم في GitHub الحين (JSON):
{json.dumps(listing, ensure_ascii=False)}

القارئ: {config.READER_PROFILE}.
اختر حتى {config.GITHUB_MAX_REPOS} مستودعات تفيده فعلًا (قدّم أدوات الذكاء الاصطناعي والوكلاء والأتمتة وأدوات المطورين،
وتجاهل اللي ما له علاقة بشغله). لكل واحد اكتب بالعربي الواضح (لهجة سعودية خفيفة):
- "what": وش هو بجملة أو جملتين.
- "benefit": وش فايدته له هو بالذات لو ثبّته عنده — مثال عملي مربوط بشغله، مو كلام عام.
- "install": أمر التثبيت أو التشغيل من الـREADME لو واضح (سطر واحد)، وإلا "".
أرجع JSON: {{"repos": [{{"id": 0, "what": "...", "benefit": "...", "install": ""}}]}}"""
    try:
        text, _ = gemini(prompt, json_out=True)
    except Exception as e:
        log("  ✗ قسم GitHub:", e)
        return []
    out = []
    for x in (extract_json(text) or {}).get("repos", [])[:config.GITHUB_MAX_REPOS]:
        idx = x.get("id")
        if isinstance(idx, int) and 0 <= idx < len(repos):
            r = repos[idx]
            meta = " · ".join(p for p in (f"⭐ {r['stars_new']} نجمة {r['period']}" if r["stars_new"] else "",
                                          f"المجموع {r['stars']}" if r["stars"] else "", r["lang"]) if p)
            out.append({"title": r["name"], "url": r["url"], "summary": x.get("what", r["desc"]),
                        "benefit": x.get("benefit", ""), "install": (x.get("install") or "").strip(),
                        "source": meta})
    log(f"  ✓ قسم GitHub: {len(out)}")
    return out


def run_daily():
    state = load_state()
    since = NOW - timedelta(hours=26)
    log("جمع المصادر…")
    items = collect_feeds(since)
    items += grounded_search(24, "غطِّ: إطلاقات الموديلات، الأدوات العملية (وكلاء، أتمتة، توليد فيديو وصور)، "
                                 "أخبار الذكاء الاصطناعي في السعودية والخليج، التمويل والاستحواذات والأبحاث المهمة.")
    items = [it for it in items if not is_seen(state, it)]
    log(f"عناصر جديدة: {len(items)}")
    if not items:
        log("ما فيه أخبار جديدة — ما أرسلت شي.")
        return

    prompt = f"""أنت محرر نشرة يومية لأخبار الذكاء الاصطناعي لقارئ سعودي يبني مشاريع بالذكاء الاصطناعي.
هذه أخبار آخر ٢٤ ساعة من X والمدونات الرسمية والمواقع التقنية (JSON):
{json.dumps(compact(items), ensure_ascii=False)}

المطلوب:
- اختر أهم {config.DIGEST_MAX_ITEMS} خبرًا كحد أقصى، وادمج الأخبار المكررة عن نفس الحدث (خذ أفضل id).
- وزّعها على هذه الأقسام بالضبط (اترك القسم فارغًا إن لم يوجد له شيء): {json.dumps(config.SECTIONS, ensure_ascii=False)}
- لكل خبر: عنوان عربي قصير وملخص بسطرين بالعربي الواضح (لهجة سعودية خفيفة مقبولة)، مع إبقاء أسماء المنتجات بالإنجليزية.
- "product": إذا الخبر عن شي جديد يقدر القارئ يجربه الحين (موديل، موقع، تطبيق، أداة)، اكتب اسمه بالإنجليزية؛ وإلا "".
- "top": أهم ٣ إلى ٥ أخبار اليوم (ids من اللي اخترتها)، وقدّم الإطلاقات اللي تنجرّب.
- اكتب "brief": فقرة «وش يهمك اليوم» من ٢-٣ جمل عن أهم ما حدث ولماذا يهم.
أرجع JSON: {{"brief": "...", "top": [0], "sections": [{{"name": "...", "items": [{{"id": 0, "title": "...", "summary": "...", "product": ""}}]}}]}}"""
    text, _ = gemini(prompt, json_out=True)
    data = extract_json(text) or {}
    top_ids = [i for i in data.get("top", []) if isinstance(i, int)][:5]
    sections, top, entries = [], {}, []
    for sec in data.get("sections", []):
        out = []
        for x in sec.get("items", []):
            idx = x.get("id")
            if isinstance(idx, int) and 0 <= idx < len(items):
                src = items[idx]
                e = {"title": x.get("title") or src["title"], "summary": x.get("summary", ""),
                     "url": src["url"], "source": src["source"], "product": (x.get("product") or "").strip()}
                entries.append(e)
                if idx in top_ids:
                    top[idx] = e  # يطلع في «أهم الأخبار» بس، ما يتكرر في قسمه
                else:
                    out.append(e)
        if out:
            sections.append({"name": sec.get("name", ""), "items": out})
    if top:
        sections.insert(0, {"name": "⭐ أهم الأخبار", "items": [top[i] for i in top_ids if i in top]})
    if not sections:
        raise RuntimeError(f"Gemini ما رجّع أقسام صالحة: {text[:300]}")
    add_try_links(entries)
    repos = github_section(state)

    # التفاصيل في صفحة ويب بتبويبين، والإيميل قصير فيه زرّين يفتحونها
    date_ar = NOW.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    brief = data.get("brief", "")
    n_news = sum(len(s["items"]) for s in sections)
    page_url = write_web_page(date_ar, brief, sections, repos)
    send_email(f"📰 أخبار الذكاء الاصطناعي — {date_ar}",
               short_email(date_ar, brief, page_url, n_news, len(repos)),
               f"وش يهمك اليوم:\n{brief}\n\n📰 الأخبار ({n_news}): {page_url}#news\n"
               f"🐙 GitHub ({len(repos)}): {page_url}#github\n")
    for it in items + repos:  # كل ما عُرض يُعلَّم، حتى لا يتكرر غدًا
        mark_seen(state, it)
    save_state(state)


def run_alert():
    state = load_state()
    today = NOW.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    sent_today = state["alerts"].get(today, 0)
    if sent_today >= config.ALERTS_PER_DAY:
        log(f"وصلنا حد التنبيهات اليوم ({sent_today}).")
        return
    since = NOW - timedelta(hours=config.ALERT_WINDOW_HOURS)
    log("فحص الإطلاقات الكبيرة…")
    items = collect_feeds(since, kinds={"lab"})
    items += grounded_search(3, "ابحث فقط عن الإطلاقات الكبيرة: موديل أو منتج جديد رسمي من شركة كبيرة "
                                "(OpenAI, Anthropic, Google, xAI, Meta, Mistral, DeepSeek, Apple, Microsoft, Nvidia).")
    items = [it for it in items if not is_seen(state, it)]
    if not items:
        log("ما فيه جديد.")
        return

    prompt = f"""الوقت الحالي (UTC): {NOW:%Y-%m-%d %H:%M}. هذه أخبار آخر ٣ ساعات (JSON):
{json.dumps(compact(items), ensure_ascii=False)}
حدد فقط "الإطلاقات الكبيرة": إعلان رسمي عن موديل ذكاء اصطناعي جديد أو منتج كبير من شركة كبيرة، متاح أو معلن اليوم.
ليست إطلاقًا كبيرًا: الشائعات، التسريبات، الأبحاث، التحديثات الصغيرة، المقالات التحليلية، أي خبر قديم.
كن صارمًا: إن شككت فلا تختره. الحد الأقصى ٣.
"product": اسم المنتج بالإنجليزية إذا يقدر القارئ يجربه، وإلا "".
أرجع JSON: {{"major": [{{"id": 0, "title": "عنوان عربي قصير", "summary": "سطرين بالعربي: وش انطلق ولماذا يهم", "product": ""}}]}}"""
    text, _ = gemini(prompt, json_out=True)
    data = extract_json(text) or {}
    picks = []
    for x in data.get("major", []):
        idx = x.get("id")
        if isinstance(idx, int) and 0 <= idx < len(items):
            src = items[idx]
            picks.append({"title": x.get("title") or src["title"], "summary": x.get("summary", ""),
                          "url": src["url"], "source": src["source"], "_src": src,
                          "product": (x.get("product") or "").strip()})
    if not picks:
        log("ما فيه إطلاق كبير.")
        return
    add_try_links(picks)
    sec = [{"name": "🚨 إطلاق جديد", "items": picks}]
    send_email(f"🚨 {picks[0]['title']}",
               page("🚨 تنبيه: إطلاق كبير", NOW.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),
                    [f'<div class="c">{"".join(item_html(p) for p in picks)}</div>']),
               to_text(sec))
    for p in picks:
        mark_seen(state, p["_src"])
        mark_seen(state, p)
    state["alerts"][today] = sent_today + 1
    save_state(state)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode == "send":
        pending = ROOT / "out" / "pending.json"
        if pending.exists():
            m = json.loads(pending.read_text(encoding="utf-8"))
            send_email(m["subject"], m["html"], m["text"])
    else:
        {"daily": run_daily, "alert": run_alert}[mode]()

#!/usr/bin/env python3
"""Fetch tech news RSS/Atom feeds and write news.json for The Tech Times.

Runs in a GitHub Action every 30 minutes. Standard library only.
Keeps headlines, links, sources, times and a short excerpt; the page links out to the full stories.

Usage:
  python scripts/fetch_news.py               # fetch live feeds, write news.json
  python scripts/fetch_news.py --from DIR    # parse saved feed files in DIR (for testing)
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEEDS = [
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("Wired", "https://www.wired.com/feed/rss"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("9to5Mac", "https://9to5mac.com/feed/"),
    ("Engadget", "https://www.engadget.com/rss.xml"),
    ("The Register", "https://www.theregister.com/headlines.atom"),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
    ("InfoQ", "https://feed.infoq.com/"),
    ("GitHub Blog", "https://github.blog/feed/"),
    ("Tom's Hardware", "https://www.tomshardware.com/feeds/all"),
]

MAX_AGE = timedelta(days=4)
MAX_PER_FEED = 30
MAX_ITEMS = 260
EXCERPT = 200
UA = "TheTechTimes/1.0 (+https://github.com/Tech-A/Tech-Times; personal news reader)"

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text):
    if not text:
        return ""
    text = html.unescape(TAG_RE.sub(" ", html.unescape(text)))
    return WS_RE.sub(" ", text).strip()


def excerpt(text):
    text = clean(text)
    if len(text) <= EXCERPT:
        return text
    cut = text[:EXCERPT].rsplit(" ", 1)[0].rstrip(",;:-–—")
    return cut + "…"


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def text_of(node, *names):
    for name in names:
        child = node.find(name)
        if child is not None and (child.text or "").strip():
            return child.text
    return ""


def parse_feed(source, raw):
    root = ET.fromstring(raw)
    items = []
    if root.tag == ATOM + "feed":
        for entry in root.findall(ATOM + "entry")[:MAX_PER_FEED]:
            link = ""
            for l in entry.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
                    break
            items.append({
                "title": clean(text_of(entry, ATOM + "title")),
                "url": link,
                "published": parse_date(text_of(entry, ATOM + "published", ATOM + "updated")),
                "summary": excerpt(text_of(entry, ATOM + "summary", ATOM + "content")),
            })
    else:
        channel = root.find("channel") if root.find("channel") is not None else root
        for item in channel.findall("item")[:MAX_PER_FEED]:
            link = text_of(item, "link") or text_of(item, "guid")
            items.append({
                "title": clean(text_of(item, "title")),
                "url": link.strip(),
                "published": parse_date(text_of(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date")),
                "summary": excerpt(text_of(item, "description")),
            })
    out = []
    for it in items:
        if not it["title"] or not it["url"].startswith(("http://", "https://")) or not it["published"]:
            continue
        it["source"] = source
        out.append(it)
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def main():
    args = sys.argv[1:]
    from_dir = Path(args[args.index("--from") + 1]) if "--from" in args else None
    now = datetime.now(timezone.utc)
    collected, report = [], []
    for source, url in FEEDS:
        try:
            if from_dir:
                path = from_dir / (re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-") + ".xml")
                if not path.exists():
                    continue
                raw = path.read_bytes()
            else:
                raw = fetch(url)
            items = parse_feed(source, raw)
            collected.extend(items)
            report.append(f"{source}: {len(items)}")
        except Exception as e:  # one broken feed shouldn't stop the paper
            report.append(f"{source}: FAILED ({type(e).__name__}: {e})")

    seen, fresh = set(), []
    for it in sorted(collected, key=lambda x: x["published"], reverse=True):
        key = re.sub(r"^https?://(www\.)?", "", it["url"]).split("?")[0].rstrip("/").lower()
        if key in seen or now - it["published"] > MAX_AGE:
            continue
        seen.add(key)
        it["published"] = it["published"].isoformat().replace("+00:00", "Z")
        fresh.append(it)

    out = {"updated": now.isoformat().replace("+00:00", "Z"), "count": len(fresh[:MAX_ITEMS]), "items": fresh[:MAX_ITEMS]}
    Path("news.json").write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print("\n".join(report))
    print(f"Wrote {out['count']} items")


if __name__ == "__main__":
    main()

"""Bounded discovery of primary documentation; stores links and text, never media."""

import datetime as dt
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import requests
from .store import config, now

SEEDS = [
    "https://developer.mozilla.org/en-US/docs/Web/Security",
    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides",
    "https://developers.cloudflare.com/1.1.1.1/encryption/",
    "https://learn.microsoft.com/en-us/windows-server/networking/",
    "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/vlan/b_1712_vlan_9300_cg.html",
    "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/rtng/b_1712_rtng_9300_cg.html",
    "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/sec/b_1712_sec_9300_cg.html",
    "https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-12/config-guide/b_wl_17_12_cg.html",
    "https://developers.cloudflare.com/cloudflare-one/",
]


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = self.article = self.main = 0
        self.parts = {"article": [], "main": [], "all": []}
        self.links = []
        self.anchor = None
        self.content_blocks = []
        self.scopes = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        # Boolean HTML attributes are valid and HTMLParser represents them as None.
        tokens = set((attributes.get("class") or "").split())
        body = attributes.get("itemprop") == "articleBody" or bool(
            tokens
            & {"entry-content", "post-content", "article-content", "article-body"}
        )
        block = [] if body else None
        if body:
            self.content_blocks.append(block)
        if tag not in (
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ):
            self.scopes.append((tag, block))
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip += 1
        if tag == "article":
            self.article += 1
        if tag == "main":
            self.main += 1
        if tag == "a" and not self.skip:
            self.anchor = [attributes.get("href") or "", []]

    def handle_data(self, value):
        if self.skip:
            return
        self.parts["all"].append(value)
        for _, block in self.scopes:
            if block is not None:
                block.append(value)
        if self.article:
            self.parts["article"].append(value)
        if self.main:
            self.parts["main"].append(value)
        if self.anchor is not None:
            self.anchor[1].append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append(
                (self.anchor[0], " ".join(" ".join(self.anchor[1]).split()))
            )
            self.anchor = None
        if tag in ("p", "li", "h1", "h2", "h3", "pre", "div"):
            for parts in self.parts.values():
                parts.append("\n")
            for _, block in self.scopes:
                if block is not None:
                    block.append("\n")
        for index in range(len(self.scopes) - 1, -1, -1):
            if self.scopes[index][0] == tag:
                del self.scopes[index:]
                break
        if tag == "article":
            self.article = max(0, self.article - 1)
        if tag == "main":
            self.main = max(0, self.main - 1)
        if tag in ("script", "style", "nav", "header", "footer"):
            self.skip = max(0, self.skip - 1)

    def paragraphs(self):
        content = sorted(
            ("".join(block) for block in self.content_blocks), key=len, reverse=True
        )
        body = next(
            (
                value
                for value in [
                    *content,
                    *("".join(self.parts[k]) for k in ("main", "article", "all")),
                ]
                if len(value.strip()) > 300
            ),
            "",
        )
        return [
            line
            for value in body.split("\n")
            if len(line := " ".join(value.split())) > 40
        ]


def allowed_source(url):
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or not any(
        host == h or host.endswith("." + h)
        for h in (
            "cloudflare.com",
            "cisco.com",
            "cisa.gov",
            "developer.mozilla.org",
            "learn.microsoft.com",
        )
    ):
        raise ValueError("Source outside approved primary publishers")


def fetch(url):
    for _ in range(3):
        allowed_source(url)
        with requests.get(
            url, timeout=(5, 20), allow_redirects=False, stream=True
        ) as response:
            response.raise_for_status()
            if response.status_code in (301, 302, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise ValueError("Source did not return a document")
            raw = bytearray()
            for chunk in response.iter_content(16384):
                raw.extend(chunk)
                if len(raw) > 2_000_000:
                    raise ValueError("Source exceeds evidence limit")
            break
    else:
        raise ValueError("Too many source redirects")
    doc = Document()
    doc.url = url
    doc.feed(raw.decode("utf-8", "replace"))
    return doc, bytes(raw)


def tables(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_sources(url TEXT PRIMARY KEY,title TEXT,discovered TEXT,crawled TEXT)"
    )
    db.commit()


def refresh(db):
    tables(db)
    seeds = config().get("knowledge_indexes", SEEDS)
    for seed in seeds:
        db.execute(
            "INSERT OR IGNORE INTO knowledge_sources VALUES(?,?,?,NULL)",
            (seed, "Primary documentation index", now()),
        )
    db.commit()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    # Walk links over time instead of keeping a finite bank of question text.
    frontier = db.execute(
        "SELECT url FROM knowledge_sources WHERE crawled IS NULL OR crawled<? ORDER BY (title='Primary documentation index') DESC,crawled,url LIMIT 2",
        (cutoff,),
    ).fetchall()
    for row in frontier:
        url = row[0]
        try:
            doc, _ = fetch(url)
            for href, title in doc.links:
                link = urljoin(doc.url, href).split("#", 1)[0].split("?", 1)[0]
                p = urlparse(link)
                allowed = (
                    (
                        p.hostname == "developer.mozilla.org"
                        and p.path.startswith(
                            ("/en-US/docs/Web/Security", "/en-US/docs/Web/HTTP")
                        )
                    )
                    or (
                        p.hostname == "developers.cloudflare.com"
                        and p.path.startswith(("/1.1.1.1/", "/cloudflare-one/"))
                    )
                    or (
                        p.hostname == "learn.microsoft.com"
                        and p.path.startswith("/en-us/windows-server/networking/")
                    )
                    or (
                        p.hostname == "www.cisco.com"
                        and p.path.startswith(
                            (
                                "/c/en/us/td/docs/switches/lan/",
                                "/c/en/us/td/docs/wireless/",
                            )
                        )
                    )
                )
                if not allowed or not title:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO knowledge_sources VALUES(?,?,?,NULL)",
                    (link, title[:180], now()),
                )
            db.execute(
                "UPDATE knowledge_sources SET crawled=? WHERE url=?", (now(), url)
            )
            db.commit()
        except (requests.RequestException, ValueError):
            db.execute(
                "UPDATE knowledge_sources SET crawled=? WHERE url=?", (now(), url)
            )
            db.commit()
            continue


def records(db):
    refresh(db)
    used = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT json_extract(plan,'$.source_url') FROM jobs WHERE plan IS NOT NULL"
        )
    }
    items = [
        dict(r)
        for r in db.execute(
            "SELECT url,title FROM knowledge_sources WHERE title!='Primary documentation index'"
        )
    ]
    items = [
        r for r in items if len(urlparse(r["url"]).path.strip("/").split("/")) >= 3
    ]
    # Deterministic daily rotation, spread across categories, with unused sources first.
    import hashlib

    day = now()[:10]
    items.sort(
        key=lambda r: (
            r["url"] in used,
            hashlib.sha256((day + r["url"]).encode()).hexdigest(),
        )
    )
    selected = []
    categories = {}
    for item in items:
        parsed = urlparse(item["url"])
        bits = parsed.path.strip("/").split("/")
        category = (
            parsed.hostname
            + "/"
            + (bits[3] if parsed.hostname == "developer.mozilla.org" else bits[0])
        )
        categories.setdefault(category, []).append(item)
    # Round robin, so a large web-docs index cannot crowd networking publishers out.
    while len(selected) < 24 and any(categories.values()):
        for group in categories.values():
            if group:
                selected.append(group.pop(0))
                if len(selected) == 24:
                    break
    return [
        {
            **r,
            "source": {
                "developer.mozilla.org": "MDN",
                "developers.cloudflare.com": "Cloudflare Docs",
                "www.cisco.com": "Cisco",
                "learn.microsoft.com": "Microsoft Learn",
            }.get(urlparse(r["url"]).hostname, "Primary documentation"),
            "published": None,
            "summary": "Primary educational documentation; evergreen, not a recent incident.",
            "evidence_type": "primary_documentation",
        }
        for r in selected
    ]

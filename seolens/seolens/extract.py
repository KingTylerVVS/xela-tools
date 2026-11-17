"""HTML → title / H1 / meta description / body text (stdlib html.parser)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template", "iframe", "button", "select"}
BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "section",
         "article", "blockquote", "pre", "table", "dd", "dt", "figcaption", "hr", "main"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skip = 0
        self.title: list[str] = []
        self.h1: list[str] = []
        self.in_title = False
        self.in_h1 = False
        self.h1_done = False
        self.body: list[str] = []
        self.post: list[str] = []
        self.post_depth: int | None = None   # stack depth of the Blogger .post-body div while open
        self.post_closed = False
        self.meta_desc = ""
        self.og_desc = ""
        self.canonical = ""
        self.og_url = ""

    def _nl(self):
        self.body.append("\n")
        if self.post_depth is not None:
            self.post.append("\n")

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "description" and not self.meta_desc:
                self.meta_desc = a.get("content", "").strip()
            elif name == "og:description" and not self.og_desc:
                self.og_desc = a.get("content", "").strip()
            elif name == "og:url" and not self.og_url:
                self.og_url = a.get("content", "").strip()
            return
        if tag == "link":
            if "canonical" in a.get("rel", "").lower().split() and not self.canonical:
                self.canonical = a.get("href", "").strip()
            return
        if tag in VOID:
            if tag in BLOCK:
                self._nl()
            return
        self.stack.append(tag)
        if tag in SKIP:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "h1" and not self.h1_done and not self.skip:
            self.in_h1 = True
        if (self.post_depth is None and not self.post_closed
                and "post-body" in a.get("class", "").split()):
            self.post_depth = len(self.stack)
        if tag in BLOCK:
            self._nl()

    def handle_endtag(self, tag):
        if tag in VOID or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            if t in SKIP:
                self.skip -= 1
            if t == "title":
                self.in_title = False
            if t == "h1" and self.in_h1:
                self.in_h1 = False
                self.h1_done = True
            if self.post_depth is not None and len(self.stack) < self.post_depth:
                self.post_depth = None
                self.post_closed = True
            if t == tag:
                break
        if tag in BLOCK:
            self._nl()

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
            return
        if self.skip:
            return
        self.body.append(data)
        if self.post_depth is not None:
            self.post.append(data)
        if self.in_h1:
            self.h1.append(data)


def _clean(text: str) -> str:
    lines = [re.sub(r"[ \t\xa0​]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_html(html: str) -> dict:
    p = _Parser()
    p.feed(html or "")
    p.close()
    text = "".join(p.post) if "".join(p.post).strip() else "".join(p.body)
    return {
        "title": _clean("".join(p.title)).replace("\n", " "),
        "h1": _clean("".join(p.h1)).replace("\n", " "),
        "description": p.meta_desc or p.og_desc,
        "text": _clean(text),
        "canonical": p.canonical or p.og_url,
    }

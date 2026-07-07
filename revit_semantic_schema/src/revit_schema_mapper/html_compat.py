"""Dependency-free HTML tree + CSS-selector shim, used when ``beautifulsoup4``
is not installed.

This is *not* a general CSS engine -- it supports exactly the selector shapes
``parse.py`` and ``crawl.py`` actually use: an optional tag name, an optional
``#id``, zero or more ``.class`` selectors, an optional ``:first-of-type``
pseudo-class, chained with descendant (space) or child (``>``) combinators
(e.g. ``"div.summary"``, ``"table#memberList"``, ``"#mainSection > p:first-of-type"``,
``"div.syntax pre"``). Anything more exotic (attribute selectors, ``:nth-child``,
sibling combinators, etc.) is out of scope; if a future selector needs one of
those, extend ``_parse_compound``/``_matches_compound`` rather than reaching
for a different design.

The public surface deliberately mirrors the slice of BeautifulSoup's API that
this codebase uses: ``find``, ``find_all``, ``select``, ``select_one``,
``get_text``, ``tag["attr"]``, and ``soup.title`` -- so ``parse.py``/
``crawl.py`` can import ``MiniSoup``/``MiniTag`` as drop-in replacements for
``BeautifulSoup``/``Tag`` without branching their own logic.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class MiniTag:
    def __init__(self, name: str, attrs: dict[str, object]):
        self.name = name
        self.attrs = attrs
        self.children: list["MiniTag | str"] = []
        self.parent: "MiniTag | None" = None

    # -- text ---------------------------------------------------------

    def get_text(self, separator: str = "", strip: bool = False) -> str:
        pieces = list(self._iter_text())
        if strip:
            pieces = [p.strip() for p in pieces]
            pieces = [p for p in pieces if p]
        text = separator.join(pieces)
        return text.strip() if strip else text

    def _iter_text(self):
        for child in self.children:
            if isinstance(child, str):
                yield child
            else:
                yield from child._iter_text()

    # -- attribute access ----------------------------------------------

    def __getitem__(self, key: str):
        if key == "class":
            return self.attrs.get("class", [])
        return self.attrs[key]

    def get(self, key: str, default=None):
        if key == "class":
            return self.attrs.get("class", default if default is not None else [])
        return self.attrs.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.attrs

    # -- find / find_all -------------------------------------------------

    def _iter_tags(self):
        for child in self.children:
            if isinstance(child, MiniTag):
                yield child
                yield from child._iter_tags()

    @staticmethod
    def _matches_find(node: "MiniTag", name: str | None, attrs: dict) -> bool:
        if name is not None and node.name != name:
            return False
        for key, want in attrs.items():
            if key == "class":
                classes = node.attrs.get("class", [])
                if want is True:
                    if not classes:
                        return False
                elif isinstance(want, (list, tuple, set)):
                    if not any(w in classes for w in want):
                        return False
                elif want not in classes:
                    return False
            else:
                if want is True:
                    if key not in node.attrs:
                        return False
                elif node.attrs.get(key) != want:
                    return False
        return True

    def find(self, name: str | None = None, **attrs) -> "MiniTag | None":
        for node in self._iter_tags():
            if self._matches_find(node, name, attrs):
                return node
        return None

    def find_all(self, name: str | None = None, **attrs) -> list["MiniTag"]:
        return [node for node in self._iter_tags() if self._matches_find(node, name, attrs)]

    @property
    def descendants(self):
        """All descendant nodes (tags and text), document order -- mirrors bs4's ``.descendants``."""
        for child in self.children:
            yield child
            if isinstance(child, MiniTag):
                yield from child.descendants

    # -- select / select_one ----------------------------------------------

    def select(self, css: str) -> list["MiniTag"]:
        return _select(self, css)

    def select_one(self, css: str) -> "MiniTag | None":
        results = self.select(css)
        return results[0] if results else None

    # -- misc ---------------------------------------------------------

    @property
    def title(self) -> "MiniTag | None":
        return self.find("title")


Tag = MiniTag


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = MiniTag("[document]", {})
        self._stack: list[MiniTag] = [self.root]

    def _make_attrs(self, attrs_list) -> dict[str, object]:
        attrs: dict[str, object] = {}
        for key, value in attrs_list:
            if key == "class":
                attrs["class"] = (value or "").split()
            else:
                attrs[key] = value if value is not None else ""
        return attrs

    def handle_starttag(self, tag, attrs_list):
        node = MiniTag(tag, self._make_attrs(attrs_list))
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        if tag not in _VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs_list):
        node = MiniTag(tag, self._make_attrs(attrs_list))
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].name == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if data:
            self._stack[-1].children.append(data)


def MiniSoup(html: str, features: str | None = None) -> MiniTag:
    """Drop-in replacement for ``BeautifulSoup(html, "html.parser")``."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# -- minimal CSS selector engine (see module docstring for scope) -------------


def _parse_compound(token: str) -> dict:
    tag = None
    id_ = None
    classes: list[str] = []
    pseudo = None
    i = 0
    match = re.match(r"[A-Za-z][\w-]*", token)
    if match:
        tag = match.group(0)
        i = match.end()
    while i < len(token):
        char = token[i]
        if char == "#":
            match = re.match(r"#([\w-]+)", token[i:])
            id_ = match.group(1)
            i += match.end()
        elif char == ".":
            match = re.match(r"\.([\w-]+)", token[i:])
            classes.append(match.group(1))
            i += match.end()
        elif char == ":":
            match = re.match(r":([\w-]+)", token[i:])
            pseudo = match.group(1)
            i += match.end()
        else:
            i += 1
    return {"tag": tag, "id": id_, "classes": classes, "pseudo": pseudo}


def _tokenize_selector(selector: str) -> list[tuple[dict, str]]:
    tokens: list[tuple[dict, str]] = []
    pending_combinator = "descendant"
    for raw in selector.split():
        if raw == ">":
            pending_combinator = "child"
            continue
        tokens.append((_parse_compound(raw), pending_combinator))
        pending_combinator = "descendant"
    return tokens


def _matches_compound(node: MiniTag, compound: dict) -> bool:
    if compound["tag"] and node.name != compound["tag"]:
        return False
    if compound["id"] and node.attrs.get("id") != compound["id"]:
        return False
    if compound["classes"]:
        node_classes = node.attrs.get("class", [])
        if not all(c in node_classes for c in compound["classes"]):
            return False
    if compound["pseudo"] == "first-of-type":
        if node.parent is None:
            return False
        same_tag_siblings = [c for c in node.parent.children if isinstance(c, MiniTag) and c.name == node.name]
        if not same_tag_siblings or same_tag_siblings[0] is not node:
            return False
    return True


def _iter_descendants(node: MiniTag):
    for child in node.children:
        if isinstance(child, MiniTag):
            yield child
            yield from _iter_descendants(child)


def _select(root: MiniTag, selector: str) -> list[MiniTag]:
    tokens = _tokenize_selector(selector)
    if not tokens:
        return []

    first_compound, _ = tokens[0]
    matches = [n for n in _iter_descendants(root) if _matches_compound(n, first_compound)]

    for compound, combinator in tokens[1:]:
        next_matches: list[MiniTag] = []
        seen: set[int] = set()
        for m in matches:
            pool = [c for c in m.children if isinstance(c, MiniTag)] if combinator == "child" else _iter_descendants(m)
            for n in pool:
                if _matches_compound(n, compound) and id(n) not in seen:
                    seen.add(id(n))
                    next_matches.append(n)
        matches = next_matches

    return matches

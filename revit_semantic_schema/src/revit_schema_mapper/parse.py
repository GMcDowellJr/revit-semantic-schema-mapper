"""HTML parsing for RevitApiDocs pages.

Sandcastle-generated API doc sites (which is what revitapidocs.com is) are
consistent in *content* but the exact markup (class names, div ids) varies
across presentation themes and has changed over the years. This module was
written without live access to the site (see docs/crawl_notes.md), so every
extraction helper below tries several plausible selectors/patterns in
priority order and falls back to a recorded parser_note rather than
raising, so a page that doesn't match our assumptions produces a visibly
incomplete ApiPage instead of a silent wrong answer or a crash that kills
the whole crawl.

Anyone validating this against the live site should grep for
``parser_notes`` in the output to find every page where a selector
assumption didn't hold.

DEPENDENCY FALLBACK: uses ``beautifulsoup4`` when installed, otherwise
falls back to the dependency-free ``html_compat`` shim (a small CSS-selector
engine scoped to exactly the selectors this module uses -- see
``html_compat.py`` for what it does and does not support).
"""

from __future__ import annotations

import re

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    from .html_compat import MiniSoup as BeautifulSoup, MiniTag as Tag

from .models import ApiPage, EnumMemberInfo, Kind, MemberInfo, MemberKind, ParameterInfo

_TITLE_KIND_SUFFIXES = {
    "Class": Kind.CLASS,
    "Structure": Kind.STRUCT,
    "Struct": Kind.STRUCT,
    "Enumeration": Kind.ENUM,
    "Enum": Kind.ENUM,
    "Interface": Kind.INTERFACE,
    "Property": Kind.PROPERTY,
    "Method": Kind.METHOD,
    "Constructor": Kind.CONSTRUCTOR,
}

# Selector candidates, most-specific-and-likely first. These are hypotheses,
# not verified facts -- see module docstring.
_SUMMARY_SELECTORS = ["div.summary", "#mainSection > p:first-of-type", "div#mainBody > p:first-of-type"]
_REMARKS_SELECTORS = ["div.remarks", "#remarksSection", "div#remarks"]
_SYNTAX_SELECTORS = ["div.syntax pre", "pre.typeSignature", "div#syntaxSection pre", "pre.code"]
_EXAMPLES_SELECTORS = ["div.codeExamples pre", "div#examplesSection pre", "div.example pre"]
_SEE_ALSO_SELECTORS = ["div.seeAlsoStyle", "div#seeAlsoSection", "div.seealso"]
_MEMBERS_TABLE_SELECTORS = ["table.members", "table#memberList", "table.memberTable"]
_ENUM_TABLE_SELECTORS = ["table.enumeration", "table#enumMembers", "table.members"]
_NAMESPACE_SELECTORS = ["div#TopicPathClassic a", "div.topicPath a", "nav.breadcrumb a"]


def _first_match(soup: BeautifulSoup, selectors: list[str]) -> Tag | None:
    for selector in selectors:
        found = soup.select_one(selector)
        if found is not None:
            return found
    return None


def _text_or_empty(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag is not None else ""


def _parse_title(soup: BeautifulSoup) -> tuple[str, Kind, list[str]]:
    """Returns (raw_title, kind, parser_notes)."""
    notes: list[str] = []
    h1 = soup.find("h1") or soup.find(id="PageHeader") or soup.title
    raw_title = _text_or_empty(h1) if h1 else ""
    if not raw_title:
        notes.append("could not locate a page title element (tried h1, #PageHeader, <title>)")
        return "", Kind.UNKNOWN, notes

    kind = Kind.UNKNOWN
    for suffix, candidate_kind in _TITLE_KIND_SUFFIXES.items():
        if raw_title.strip().endswith(suffix):
            kind = candidate_kind
            break
    if kind is Kind.UNKNOWN:
        notes.append(f"title {raw_title!r} did not match any known kind suffix")
    return raw_title, kind, notes


def _strip_kind_suffix(raw_title: str) -> str:
    for suffix in _TITLE_KIND_SUFFIXES:
        if raw_title.strip().endswith(suffix):
            return raw_title.strip()[: -len(suffix)].strip()
    return raw_title.strip()


def _parse_namespace(soup: BeautifulSoup) -> tuple[str, list[str]]:
    notes: list[str] = []
    crumbs = None
    for selector in _NAMESPACE_SELECTORS:
        found = soup.select(selector)
        if found:
            crumbs = found
            break
    if crumbs:
        for a in crumbs:
            text = a.get_text(strip=True)
            if text.startswith("Autodesk.Revit"):
                return text, notes

    match = re.search(r"Namespace:\s*(Autodesk\.Revit\.[\w.]+)", soup.get_text(" ", strip=True))
    if match:
        return match.group(1), notes

    notes.append("could not locate namespace via breadcrumb or 'Namespace:' text")
    return "", notes


_TYPE_DECL_RE = re.compile(
    r"(?:public|protected|internal|private)?\s*"
    r"(?:sealed\s+|abstract\s+|static\s+)*"
    r"(?:class|struct|interface|enum)\s+"
    r"(?P<name>[\w]+)"
    r"(?:\s*:\s*(?P<bases>[\w<>,.\s\[\]]+))?"
)

_MEMBER_SIG_RE = re.compile(
    r"(?:public|protected|internal|private)?\s*"
    r"(?:virtual\s+|override\s+|abstract\s+|static\s+|sealed\s+|new\s+)*"
    r"(?P<return_type>[\w<>,.\[\]?]+(?:\s*<[^()]+>)?)\s+"
    r"(?P<name>[\w]+)\s*"
    r"(?:\((?P<params>[^)]*)\)|\{)"
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_type_declaration(syntax_text: str) -> tuple[str | None, list[str], list[str]]:
    """Returns (base_type, interfaces, parser_notes) from a class/struct/interface syntax block."""
    notes: list[str] = []
    normalized = _normalize_whitespace(syntax_text)
    match = _TYPE_DECL_RE.search(normalized)
    if not match:
        notes.append(f"type declaration regex did not match syntax block: {normalized[:200]!r}")
        return None, [], notes

    bases_str = match.group("bases")
    if not bases_str:
        return None, [], notes

    parts = [p.strip() for p in bases_str.split(",") if p.strip()]
    if not parts:
        return None, [], notes
    # Convention (matches C#): first listed base is the base class *only*
    # when it doesn't look like a marker interface (starts with "I" + capital).
    # This is a heuristic, not a CLR-verified fact - flagged for review.
    base_type, interfaces = None, parts
    if parts and not re.match(r"^I[A-Z]", parts[0]):
        base_type, interfaces = parts[0], parts[1:]
    else:
        notes.append("first base-list entry looked like an interface; base_type left unset")
    return base_type, interfaces, notes


def _parse_member_signature(
    syntax_text: str,
) -> tuple[str | None, list[ParameterInfo], list[str]]:
    """Returns (return_type, parameters, parser_notes) from a property/method syntax block."""
    notes: list[str] = []
    normalized = _normalize_whitespace(syntax_text)
    match = _MEMBER_SIG_RE.search(normalized)
    if not match:
        notes.append(f"member signature regex did not match syntax block: {normalized[:200]!r}")
        return None, [], notes

    return_type = match.group("return_type").strip()
    params_str = match.group("params")
    parameters: list[ParameterInfo] = []
    if params_str:
        for chunk in _split_top_level_commas(params_str):
            chunk = chunk.strip()
            if not chunk:
                continue
            tokens = chunk.rsplit(" ", 1)
            if len(tokens) == 2:
                parameters.append(ParameterInfo(name=tokens[1].strip(), type=tokens[0].strip()))
            else:
                notes.append(f"could not split parameter into type/name: {chunk!r}")
    return return_type, parameters, notes


def _split_top_level_commas(text: str) -> list[str]:
    """Split on commas that are not inside <>/[] (for generic parameter types)."""
    parts: list[str] = []
    depth = 0
    current = []
    for char in text:
        if char in "<[":
            depth += 1
        elif char in ">]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def _parse_see_also(soup: BeautifulSoup) -> list[str]:
    container = _first_match(soup, _SEE_ALSO_SELECTORS)
    if container is None:
        return []
    return [a.get_text(strip=True) for a in container.find_all("a") if a.get_text(strip=True)]


def _parse_examples(soup: BeautifulSoup) -> list[str]:
    blocks = []
    for selector in _EXAMPLES_SELECTORS:
        blocks = soup.select(selector)
        if blocks:
            break
    return [b.get_text("\n", strip=True) for b in blocks]


def parse_type_page(html: str, url: str, version: str) -> ApiPage:
    """Parse a class/struct/interface page into an ApiPage.

    The member table on a type page typically only has short descriptions;
    full per-member detail (parameters, remarks, examples) comes from
    ``parse_member_page`` for the member's own page. Members found here are
    included as lightweight stubs so a type is still useful even if its
    member sub-pages were not crawled.
    """
    soup = BeautifulSoup(html, "html.parser")
    notes: list[str] = []

    raw_title, kind, title_notes = _parse_title(soup)
    notes.extend(title_notes)
    type_name = _strip_kind_suffix(raw_title)

    namespace, ns_notes = _parse_namespace(soup)
    notes.extend(ns_notes)

    full_type_name = f"{namespace}.{type_name}" if namespace else type_name

    syntax_tag = _first_match(soup, _SYNTAX_SELECTORS)
    base_type, interfaces = None, []
    if syntax_tag is not None:
        base_type, interfaces, decl_notes = _parse_type_declaration(syntax_tag.get_text(" ", strip=True))
        notes.extend(decl_notes)
    else:
        notes.append("no syntax block found; base_type/interfaces unavailable")

    members: list[MemberInfo] = []
    members_table = _first_match(soup, _MEMBERS_TABLE_SELECTORS)
    if members_table is not None:
        for row in members_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            member_name = cells[0].get_text(strip=True)
            description = cells[-1].get_text(" ", strip=True)
            if not member_name:
                continue
            member_kind = MemberKind.METHOD if "(" in cells[0].get_text() else MemberKind.PROPERTY
            members.append(
                MemberInfo(
                    name=member_name,
                    kind=member_kind,
                    declaring_type=full_type_name,
                    raw_signature=member_name,
                    summary=description,
                    source_url=url,
                )
            )
    else:
        notes.append("no members table found")

    return ApiPage(
        revit_version=version,
        namespace=namespace,
        type_name=type_name,
        full_type_name=full_type_name,
        kind=kind,
        base_type=base_type,
        inheritance_chain=[base_type] if base_type else [],
        implemented_interfaces=interfaces,
        members=members,
        summary=_text_or_empty(_first_match(soup, _SUMMARY_SELECTORS)),
        remarks=_text_or_empty(_first_match(soup, _REMARKS_SELECTORS)),
        examples=_parse_examples(soup),
        see_also=_parse_see_also(soup),
        source_url=url,
        parser_notes=notes,
    )


def parse_member_page(html: str, url: str, version: str, declaring_type: str) -> ApiPage:
    """Parse a property/method/constructor page into an ApiPage carrying one MemberInfo.

    ``declaring_type`` (e.g. "Autodesk.Revit.DB.View") must be supplied by
    the caller since it usually is only reliably known from the crawl
    context (which type page linked to this member), not always recoverable
    from the member page's own title.
    """
    soup = BeautifulSoup(html, "html.parser")
    notes: list[str] = []

    raw_title, kind, title_notes = _parse_title(soup)
    notes.extend(title_notes)
    member_name = _strip_kind_suffix(raw_title)
    if "." in member_name:
        # Sandcastle sometimes titles member pages "Type.Member Property"
        member_name = member_name.rsplit(".", 1)[-1]

    namespace, ns_notes = _parse_namespace(soup)
    notes.extend(ns_notes)

    syntax_tag = _first_match(soup, _SYNTAX_SELECTORS)
    return_type, parameters, sig_notes = (None, [], [])
    raw_signature = ""
    if syntax_tag is not None:
        raw_signature = syntax_tag.get_text(" ", strip=True)
        return_type, parameters, sig_notes = _parse_member_signature(raw_signature)
        notes.extend(sig_notes)
    else:
        notes.append("no syntax block found; return_type/parameters unavailable")

    member_kind = MemberKind.METHOD if kind is Kind.METHOD or "(" in raw_signature else MemberKind.PROPERTY

    member = MemberInfo(
        name=member_name,
        kind=member_kind,
        declaring_type=declaring_type,
        raw_signature=raw_signature,
        return_type=return_type,
        parameters=parameters,
        summary=_text_or_empty(_first_match(soup, _SUMMARY_SELECTORS)),
        remarks=_text_or_empty(_first_match(soup, _REMARKS_SELECTORS)),
        examples=_parse_examples(soup),
        see_also=_parse_see_also(soup),
        source_url=url,
    )

    full_type_name = f"{declaring_type}.{member_name}"
    return ApiPage(
        revit_version=version,
        namespace=namespace,
        type_name=member_name,
        full_type_name=full_type_name,
        kind=kind if kind is not Kind.UNKNOWN else (Kind.METHOD if member_kind is MemberKind.METHOD else Kind.PROPERTY),
        declaring_type=declaring_type,
        members=[member],
        summary=member.summary,
        remarks=member.remarks,
        examples=member.examples,
        see_also=member.see_also,
        source_url=url,
        parser_notes=notes,
    )


def parse_enum_page(html: str, url: str, version: str) -> ApiPage:
    soup = BeautifulSoup(html, "html.parser")
    notes: list[str] = []

    raw_title, kind, title_notes = _parse_title(soup)
    notes.extend(title_notes)
    type_name = _strip_kind_suffix(raw_title)

    namespace, ns_notes = _parse_namespace(soup)
    notes.extend(ns_notes)
    full_type_name = f"{namespace}.{type_name}" if namespace else type_name

    enum_members: list[EnumMemberInfo] = []
    table = _first_match(soup, _ENUM_TABLE_SELECTORS)
    if table is not None:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            member_name = cells[0].get_text(strip=True)
            if not member_name or member_name.lower() == "member name":
                continue
            numeric_value = None
            description = cells[-1].get_text(" ", strip=True)
            if len(cells) >= 3:
                candidate_value = cells[1].get_text(strip=True)
                if re.fullmatch(r"-?\d+", candidate_value):
                    numeric_value = candidate_value
            enum_members.append(
                EnumMemberInfo(
                    enum_name=type_name,
                    member_name=member_name,
                    numeric_value=numeric_value,
                    description=description,
                    source_url=url,
                )
            )
    else:
        notes.append("no enum members table found")

    return ApiPage(
        revit_version=version,
        namespace=namespace,
        type_name=type_name,
        full_type_name=full_type_name,
        kind=Kind.ENUM,
        enum_members=enum_members,
        summary=_text_or_empty(_first_match(soup, _SUMMARY_SELECTORS)),
        remarks=_text_or_empty(_first_match(soup, _REMARKS_SELECTORS)),
        source_url=url,
        parser_notes=notes,
    )


def extract_member_links(html: str, base_url: str) -> list[dict]:
    """Pull (name, url) pairs for each member listed in a type page's members table.

    Used by the pipeline to discover property/method sub-pages that may not
    be reachable from the version index/TOC directly.
    """
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    table = _first_match(soup, _MEMBERS_TABLE_SELECTORS)
    if table is None:
        return []
    links: list[dict] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        anchor = cells[0].find("a", href=True)
        if anchor is None:
            continue
        links.append({"name": anchor.get_text(strip=True), "url": urljoin(base_url, anchor["href"])})
    return links


def sniff_kind(html: str) -> Kind:
    """Best-effort kind detection used by the pipeline to dispatch to the right parser."""
    soup = BeautifulSoup(html, "html.parser")
    _, kind, _ = _parse_title(soup)
    return kind

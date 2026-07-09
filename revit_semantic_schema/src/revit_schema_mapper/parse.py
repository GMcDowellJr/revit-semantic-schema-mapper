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

CONFIRMED AGAINST LIVE MARKUP (2024, see docs/crawl_notes.md): a class page
does *not* embed its members table inline -- it links out to a separate
"<Type> Members" page (``find_members_page_link``/``parse_members_index_page``
below), which itself holds two ``table.members``/``table#memberList`` tables
(Methods, then Properties) under ``h1.heading`` section headers. The page
title lives in ``h4#api-title``, not ``h1``/``#PageHeader`` (those are kept
as fallbacks in case older cached years use classic Sandcastle markup). See
``pipeline.py`` for how the class-page -> members-page link is followed.

CONFIRMED AGAINST LIVE MARKUP (2025, see docs/crawl_notes.md): the
``h1.heading`` section marker is gone. Sections are now collapsible regions:
a ``<span class=collapsibleRegionTitle>`` (an icon plus the section name,
e.g. "Properties") followed by a ``<div class=collapsibleSection>`` wrapping
that section's table. ``parse_members_index_page`` recognizes both forms.
Separately, the syntax block (type declarations and member signatures alike)
moved into a per-language "code snippet" widget -- one
``div.codeSnippetContainerCode.{cs,vb,cpp,fs}`` per .NET language, each with
its own ``<pre><code>``; only the C# (``.cs``) one matters here. This was a
real, high-impact break: with no ``_SYNTAX_SELECTORS`` match, every member
page's ``return_type`` came back ``None``, which silently zeroed out *every*
candidate edge crawl-wide (``classify.classify_member`` requires a non-empty
``return_type`` before it will consider any edge rule at all) -- confirmed
via a live 2025 run producing 0 edges from 23k+ successfully "parsed" pages.
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
    "Members": Kind.MEMBERS_INDEX,
    # Standalone "<Type> Methods"/"<Type> Properties" pages exist alongside
    # the combined "<Type> Members" page (same data, pre-filtered); route
    # them through the same parser -- parse_members_index_page's section-
    # heading tracking degrades gracefully (member_kind stays None) if such a
    # page has no "Methods"/"Properties" h1.heading of its own.
    "Methods": Kind.MEMBERS_INDEX,
    "Properties": Kind.MEMBERS_INDEX,
}

# Selector candidates, most-specific-and-likely first. Confirmed against
# live markup: div.summary, div#mainBody, div.seeAlsoStyle, table.members,
# table#memberList all appear as-is on the real site (see module docstring).
_SUMMARY_SELECTORS = ["div.summary", "#mainSection > p:first-of-type", "div#mainBody > p:first-of-type"]
_REMARKS_SELECTORS = ["div.remarks", "#remarksSection", "div#remarks"]
_SYNTAX_SELECTORS = [
    # 2025 (see docs/crawl_notes.md): the syntax block moved into a
    # per-language "code snippet" widget -- one div.codeSnippetContainerCode
    # per .NET language (cs/vb/cpp/fs), each holding its own <pre><code>.
    # Only the C# one is relevant (the regexes below are C#-specific); it's
    # marked style="display: block" (the others "display: none") but that's
    # a CSS runtime detail, not something a static parse can rely on -- the
    # ".cs" class is what actually identifies it regardless of display.
    "div.codeSnippetContainerCode.cs pre",
    "div.syntax pre",
    "pre.typeSignature",
    "div#syntaxSection pre",
    "pre.code",
]
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


def _strip_trailing_overload_signature(title: str) -> str:
    """Strip a trailing, possibly-nested "(...)" overload-disambiguation
    group from a member page title, e.g. "ChangeTypeId Method (ElementId)"
    or "ChangeTypeId Method (Document, ICollection(ElementId), ElementId)"
    -> "ChangeTypeId Method" in both cases.

    Confirmed live layout: Sandcastle gives each overload of an overloaded
    method its own page, titled "<Name> Method (<param types>)" -- the
    param-type list is appended *after* the kind suffix, so a naive
    ``.endswith("Method")`` check never matches it, and both kind detection
    and name extraction need this stripped first. A regex can't do this
    correctly since the parameter list itself can contain parens (e.g.
    ``ICollection(ElementId)``); this walks back from the end tracking
    paren depth instead. Returns the title unchanged if it doesn't end in
    ``)`` or the parens are unbalanced (rather than guessing).
    """
    stripped = title.rstrip()
    if not stripped.endswith(")"):
        return title
    depth = 0
    for i in range(len(stripped) - 1, -1, -1):
        char = stripped[i]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                return stripped[:i].rstrip()
    return title  # unbalanced parens -- don't guess


def _parse_title(soup: BeautifulSoup) -> tuple[str, Kind, list[str]]:
    """Returns (raw_title, kind, parser_notes). ``raw_title`` is the full,
    unmodified title (including any overload signature); only the internal
    kind-suffix match strips it first -- see
    ``_strip_trailing_overload_signature``.
    """
    notes: list[str] = []
    # id="api-title" is what the live site actually uses (an <h4>, not <h1>);
    # h1/#PageHeader/<title> are kept as fallbacks for older cached years.
    h1 = soup.find(id="api-title") or soup.find("h1") or soup.find(id="PageHeader") or soup.title
    raw_title = _text_or_empty(h1) if h1 else ""
    if not raw_title:
        notes.append("could not locate a page title element (tried #api-title, h1, #PageHeader, <title>)")
        return "", Kind.UNKNOWN, notes

    kind_match_title = _strip_trailing_overload_signature(raw_title.strip())
    kind = Kind.UNKNOWN
    for suffix, candidate_kind in _TITLE_KIND_SUFFIXES.items():
        if kind_match_title.endswith(suffix):
            kind = candidate_kind
            break
    if kind is Kind.UNKNOWN:
        notes.append(f"title {raw_title!r} did not match any known kind suffix")
    return raw_title, kind, notes


def _strip_kind_suffix(raw_title: str) -> str:
    working = _strip_trailing_overload_signature(raw_title.strip())
    for suffix in _TITLE_KIND_SUFFIXES:
        if working.endswith(suffix):
            return working[: -len(suffix)].strip()
    return raw_title.strip()


_NAMESPACE_JSON_RE = re.compile(r'"namespace"\s*:\s*"([^"]+)"')


def _parse_namespace(soup: BeautifulSoup, html: str = "") -> tuple[str, list[str]]:
    """Returns (namespace, parser_notes).

    Confirmed live layout: the breadcrumb (``<ul class="breadcrumb">``) is
    populated by client-side JS at runtime, not present as static text in
    the server-rendered HTML -- ``_NAMESPACE_SELECTORS`` and the
    "Namespace:" text search below will not match it. The namespace *is*
    reliably present in a ``<script>``-embedded ``templateData`` JS object
    literal (``"namespace": "Autodesk.Revit.DB"``), which this tries first.
    The breadcrumb/text strategies are kept as fallbacks for older cached
    years that may render it statically.
    """
    notes: list[str] = []

    if html:
        match = _NAMESPACE_JSON_RE.search(html)
        if match:
            return match.group(1), notes

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

    notes.append("could not locate namespace via embedded JSON, breadcrumb, or 'Namespace:' text")
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


def _member_name_cell(cells: list) -> "Tag | None":
    """Return the cell holding the member's name/link.

    Confirmed live layout is [icon, name, description] (3 cells) -- cell 0 is
    an <img> icon with no text, not the name. Falls back to cell 0 for a
    2-cell row in case some page/year omits the icon column.
    """
    if len(cells) >= 3:
        return cells[1]
    if cells:
        return cells[0]
    return None


_INHERITED_FROM_RE = re.compile(r"Inherited from\s+([A-Za-z_]\w*)")


def _row_is_inherited(row: Tag) -> bool:
    """Confirmed live layout: a member row's ``data`` attribute is a
    semicolon-separated flag list, e.g. ``public;inherited;notNetfw;`` for a
    member declared on a base type vs. ``public;declared;notNetfw;`` for one
    declared directly on this type.
    """
    data_attr = row.get("data", "") or ""
    return "inherited" in [part.strip() for part in data_attr.split(";")]


def _row_inherited_from(cells: list) -> str | None:
    """Best-effort short name of the type an inherited row's member is
    actually declared on, from the description cell's trailing "(Inherited
    from <a>Element</a>.)" (or ``<span class=nolink>Object</span>`` for
    universal .NET Object members). Returns None if that text isn't found,
    so the caller can decide not to guess.
    """
    if not cells:
        return None
    match = _INHERITED_FROM_RE.search(cells[-1].get_text(" ", strip=True))
    return match.group(1) if match else None


_TOP_LEVEL_DB_NAMESPACE = "Autodesk.Revit.DB"


def _resolve_inherited_owner_namespace(current_page_namespace: str) -> str:
    """Best-effort namespace for an inherited row's owner type, given the
    *current* page's own namespace.

    Confirmed live layout: a type in a sub-namespace (e.g.
    ``Autodesk.Revit.DB.Architecture.Room``) commonly inherits from a base
    type declared in the top-level ``Autodesk.Revit.DB`` namespace (e.g.
    ``Element``, ``SpatialElement``), not in that sub-namespace itself.
    Blindly reusing the current page's own namespace would fabricate a
    nonexistent owner (``Autodesk.Revit.DB.Architecture.Element`` instead of
    the real ``Autodesk.Revit.DB.Element``). This is a heuristic, not a
    verified fact for every case: it assumes the common pattern (a
    sub-namespace type's bases live one level up, in the shared top-level
    namespace) and returns the current namespace unchanged when it isn't
    already under ``Autodesk.Revit.DB`` -- there's nothing more specific to
    fall back to in that case.
    """
    if current_page_namespace == _TOP_LEVEL_DB_NAMESPACE or not current_page_namespace.startswith(f"{_TOP_LEVEL_DB_NAMESPACE}."):
        return current_page_namespace
    return _TOP_LEVEL_DB_NAMESPACE


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

    namespace, ns_notes = _parse_namespace(soup, html)
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
            name_cell = _member_name_cell(cells)
            cell_text = name_cell.get_text(strip=True) if name_cell is not None else ""
            description = cells[-1].get_text(" ", strip=True)
            if not cell_text:
                continue
            member_kind = MemberKind.METHOD if "(" in cell_text else MemberKind.PROPERTY
            # An overloaded method's Name cell on a class/struct page's own inline member
            # table (as opposed to parse_member_page's per-member sub-page, which already
            # goes through the same helper via its title) shows the real Sandcastle
            # disambiguation text verbatim, e.g. "SpliceRebar(Document, ElementId,
            # RebarSpliceOptions, Line, ElementId)" -- confirmed real leak on a Revit 2025
            # crawl: left unstripped, this becomes both MemberInfo.name and (downstream)
            # EdgeCandidate.member_name, which then can never match a manifest member by
            # name in ground_truth.cross_validate_dll (Stage B correctly reported these as
            # MEMBER_NOT_FOUND, but the real bug was here, upstream of Stage B entirely).
            # _strip_trailing_overload_signature already handles exactly this shape (and
            # a non-overloaded method's plain "Foo()" reduces to "Foo" the same way) --
            # applied to member_kind detection's *input* text above, not its output, since
            # a property's cell text never has parens to strip in the first place.
            member_name = _strip_trailing_overload_signature(cell_text)
            members.append(
                MemberInfo(
                    name=member_name,
                    kind=member_kind,
                    declaring_type=full_type_name,
                    raw_signature=cell_text,
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

    namespace, ns_notes = _parse_namespace(soup, html)
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

    if kind is Kind.CONSTRUCTOR:
        # A constructor has no return type in C# at all -- "public AreaTagFilter ()" has
        # nothing between the access modifier and the constructor's own name for
        # _MEMBER_SIG_RE's <return_type> group to correctly leave empty, since that group is
        # required (one-or-more) and the leading access-modifier group is optional. Confirmed
        # against a real Revit 2025 crawl: this makes _MEMBER_SIG_RE backtrack into treating
        # the access modifier itself ("public"/"protected"/...) as return_type for every
        # constructor page, which then flows into classify.classify_member and produces a
        # bogus name_only_candidate EdgeCandidate (source_type == member_name, "public" is
        # obviously not a real Autodesk.Revit.DB type) -- 98 such edges in that crawl, all
        # later reporting Stage B's MEMBER_NOT_FOUND for the same reason. Discarding
        # return_type here (not upstream in _parse_member_signature, which has no idea what
        # kind of page it's parsing) is a fact about the C# language, not a heuristic, and
        # relies on classify_member's own existing rule that a falsy return_type never
        # produces an edge.
        if return_type is not None:
            notes.append(f"discarding constructor's parsed return_type {return_type!r}: constructors have no return type")
        return_type = None

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

    namespace, ns_notes = _parse_namespace(soup, html)
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
    be reachable from the version index/TOC directly. On the live site the
    members table usually isn't on the type page itself (see
    ``find_members_page_link``/``parse_members_index_page``); this is kept as
    a defensive fallback for pages/years that do inline it.

    A row inherited from a base type (e.g. ``ArePhasesModifiable`` inherited
    from ``Element`` on a ``Wall`` page) is *not* declared on this type --
    including it here with this page's own type as declaring type would
    mis-attribute it (e.g. a false ``Wall.ArePhasesModifiable``). Such rows
    get a ``declaring_type_hint`` resolved from the row's own "(Inherited
    from X.)" text instead of the caller's default, or are skipped entirely
    if that text can't be parsed (better to lose the row than mis-attribute
    it).
    """
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    namespace, _ = _parse_namespace(soup, html)
    table = _first_match(soup, _MEMBERS_TABLE_SELECTORS)
    if table is None:
        return []
    links: list[dict] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        name_cell = _member_name_cell(cells)
        if name_cell is None:
            continue
        anchor = name_cell.find("a", href=True)
        if anchor is None:
            continue
        link = {"name": anchor.get_text(strip=True), "url": urljoin(base_url, anchor["href"])}
        if _row_is_inherited(row):
            inherited_from = _row_inherited_from(cells)
            if inherited_from is None:
                continue  # inherited but from an unknown type -- don't guess
            owner_namespace = _resolve_inherited_owner_namespace(namespace) if namespace else ""
            link["declaring_type_hint"] = f"{owner_namespace}.{inherited_from}" if owner_namespace else inherited_from
        links.append(link)
    return links


def find_members_page_link(html: str, base_url: str) -> str | None:
    """Find the "Members" sub-nav link on a class/struct/interface page.

    Confirmed live layout: a shared sub-nav (``table#bottomTable``) lists
    links to sibling pages (e.g. a class page links to "Members | Example |
    See Also"; a Members page links back to "<Type> Class | Methods |
    Properties | See Also"). Returns the absolute URL of the link whose text
    is exactly "Members", or None if not found.
    """
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    nav = soup.find(id="bottomTable")
    if nav is None:
        return None
    for anchor in nav.find_all("a", href=True):
        if anchor.get_text(strip=True) == "Members":
            return urljoin(base_url, anchor["href"])
    return None


def _is_members_table(tag) -> bool:
    if tag.name != "table":
        return False
    classes = tag.attrs.get("class", [])
    return "members" in classes or "memberTable" in classes or tag.attrs.get("id") == "memberList"


def parse_members_index_page(html: str, base_url: str) -> tuple[list[dict], list[str]]:
    """Parse a "<Type> Members" page into member link dicts.

    Confirmed live layout (2024): an ``h1.heading`` reading "Methods" or
    "Properties" precedes a ``table.members``/``table#memberList`` for that
    section, in document order (the live markup has an unclosed ``<div>``
    upstream of these, so they end up nested rather than siblings -- a full
    descendant walk in document order is used rather than direct children,
    to be robust to that).

    Confirmed live layout (2025, see docs/crawl_notes.md): the ``h1.heading``
    marker is gone. Each section is instead a collapsible region: a
    ``<span class=collapsibleRegionTitle>`` (icon ``<img>`` plus the section
    name as trailing text, e.g. "Properties") followed by a sibling
    ``<div class=collapsibleSection>`` wrapping that section's table. Both
    markers are recognized here -- 2025's structural change didn't remove the
    2024 form from every cached year, so both are checked in document order.
    Returns (links, parser_notes); each link dict has
    ``name``, ``url``, and ``member_kind`` (a ``MemberKind`` or None if the
    section heading wasn't recognized). Entries with no link (e.g. inherited
    `Object` members like ``Equals``/``GetHashCode``, which have no page of
    their own) are omitted.

    A row inherited from a base type (e.g. ``ArePhasesModifiable`` inherited
    from ``Element`` on the real ``Wall`` page -- ``data="...;inherited;..."``)
    is *not* declared on this type; including it with this page's own type
    as declaring type would mis-attribute it (e.g. a false
    ``Wall.ArePhasesModifiable``). Such rows carry a ``declaring_type_hint``
    resolved from the row's own "(Inherited from X.)" text instead, or are
    skipped entirely if that text can't be parsed (better to lose the row
    than mis-attribute it).
    """
    from urllib.parse import urljoin

    notes: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    namespace, _ = _parse_namespace(soup, html)
    container = soup.find(id="mainBody") or soup.find(id="mainSection") or soup

    links: list[dict] = []
    current_section: str | None = None
    seen_tables: set[int] = set()
    for node in container.descendants:
        if isinstance(node, str):
            continue
        if node.name == "h1" and "heading" in node.attrs.get("class", []):
            current_section = node.get_text(strip=True)
            continue
        if node.name == "span" and "collapsibleRegionTitle" in node.attrs.get("class", []):
            current_section = node.get_text(strip=True)
            continue
        if not _is_members_table(node) or id(node) in seen_tables:
            continue
        seen_tables.add(id(node))

        member_kind = {
            "Methods": MemberKind.METHOD,
            "Properties": MemberKind.PROPERTY,
        }.get(current_section)
        if member_kind is None:
            notes.append(f"members table found under unrecognized section heading {current_section!r}")
        for row in node.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            name_cell = _member_name_cell(cells)
            if name_cell is None:
                continue
            anchor = name_cell.find("a", href=True)
            if anchor is None:
                continue  # no page of its own (e.g. inherited Object.Equals)
            link = {
                "name": anchor.get_text(strip=True),
                "url": urljoin(base_url, anchor["href"]),
                "member_kind": member_kind,
            }
            if _row_is_inherited(row):
                inherited_from = _row_inherited_from(cells)
                if inherited_from is None:
                    continue  # inherited but from an unknown type -- don't guess
                owner_namespace = _resolve_inherited_owner_namespace(namespace) if namespace else ""
                link["declaring_type_hint"] = f"{owner_namespace}.{inherited_from}" if owner_namespace else inherited_from
            links.append(link)
    if not links:
        notes.append("no member rows with links found on members index page")
    return links, notes


def resolve_type_name_from_members_index(html: str) -> str:
    """Best-effort fully-qualified owning type name from a "<Type> Members" page.

    Used when such a page is reached without already knowing its owner (e.g.
    discovered independently via generic link discovery, rather than by
    following the link from its class page -- the common path, see
    ``find_members_page_link``).
    """
    soup = BeautifulSoup(html, "html.parser")
    raw_title, _, _ = _parse_title(soup)
    short_name = _strip_kind_suffix(raw_title)
    namespace, _ = _parse_namespace(soup, html)
    return f"{namespace}.{short_name}" if namespace else short_name


def sniff_kind(html: str) -> Kind:
    """Best-effort kind detection used by the pipeline to dispatch to the right parser."""
    soup = BeautifulSoup(html, "html.parser")
    _, kind, _ = _parse_title(soup)
    return kind

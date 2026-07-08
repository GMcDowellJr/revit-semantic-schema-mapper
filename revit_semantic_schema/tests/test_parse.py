from revit_schema_mapper.models import Kind, MemberKind
from revit_schema_mapper.parse import (
    _strip_kind_suffix,
    _strip_trailing_overload_signature,
    extract_member_links,
    find_members_page_link,
    parse_enum_page,
    parse_member_page,
    parse_members_index_page,
    parse_type_page,
    resolve_type_name_from_members_index,
    sniff_kind,
)


def test_parse_class_page(load_fixture):
    html = load_fixture("class_familyinstance.htm")
    page = parse_type_page(html, "https://www.revitapidocs.com/2027/class_familyinstance.htm", "2027")

    assert page.kind is Kind.CLASS
    assert page.type_name == "FamilyInstance"
    assert page.namespace == "Autodesk.Revit.DB"
    assert page.full_type_name == "Autodesk.Revit.DB.FamilyInstance"
    assert page.base_type == "Element"
    assert "IDisposable" in page.implemented_interfaces
    assert "instance of a family" in page.summary.lower()
    member_names = {m.name for m in page.members}
    assert {"Symbol", "Host"} <= member_names


def test_extract_member_links(load_fixture):
    html = load_fixture("class_familyinstance.htm")
    links = extract_member_links(html, "https://www.revitapidocs.com/2027/class_familyinstance.htm")
    names = {link["name"] for link in links}
    assert "Symbol" in names
    symbol_link = next(link for link in links if link["name"] == "Symbol")
    assert symbol_link["url"].endswith("property_familyinstance_symbol.htm")


_INLINE_TABLE_CLASS_PAGE_WITH_INHERITED_ROWS = """
<html><body>
<h1 id="PageHeader">Wall Class</h1>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<div class="syntax"><pre class="typeSignature">public class Wall : HostObject</pre></div>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="arephasesmodifiable.htm">ArePhasesModifiable</a></td><td>Returns true if... (Inherited from <a href="element.htm">Element</a>.)</td></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="flip.htm">Flip</a></td><td>Flips the wall.</td></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="mystery.htm">MysteryInherited</a></td><td>No parseable owner text here.</td></tr>
</table>
</body></html>
"""


_INLINE_TABLE_CLASS_PAGE_WITH_OVERLOADED_METHOD_ROW = """
<html><body>
<h1 id="PageHeader">RebarSpliceUtils Class</h1>
<div id="TopicPathClassic"><a href="/2025/ns_db.htm">Autodesk.Revit.DB.Structure</a> Namespace</div>
<div class="syntax"><pre class="typeSignature">public class RebarSpliceUtils</pre></div>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="splicerebar1.htm">SpliceRebar(Document, ElementId, RebarSpliceOptions, Line, ElementId)</a></td><td>Splices two rebars.</td></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="width.htm">Width</a></td><td>A plain, non-overloaded property.</td></tr>
</table>
</body></html>
"""


def test_parse_type_page_strips_overload_signature_from_inline_member_table():
    """Regression test for a real Revit 2025 finding: a class page's own
    inline member table (the lightweight-stub path used when a member's own
    sub-page wasn't separately crawled) shows an overloaded method's Name
    cell as Sandcastle's real disambiguation text verbatim, e.g.
    "SpliceRebar(Document, ElementId, RebarSpliceOptions, Line, ElementId)".
    Left unstripped, that whole string became MemberInfo.name (and
    downstream, EdgeCandidate.member_name), which can never match a real
    manifest member by name -- confirmed as part of Stage B's
    MEMBER_NOT_FOUND results on that crawl, but the real bug was here,
    upstream of Stage B. parse_member_page's per-member-sub-page path
    already strips this via the page's own title; this inline-table path
    needs the same treatment applied to the cell text instead.
    """
    page = parse_type_page(
        _INLINE_TABLE_CLASS_PAGE_WITH_OVERLOADED_METHOD_ROW,
        "https://www.revitapidocs.com/2025/class_rebarspliceutils.htm",
        "2025",
    )
    by_name = {m.name: m for m in page.members}
    assert "SpliceRebar" in by_name
    assert by_name["SpliceRebar"].kind is MemberKind.METHOD
    assert "SpliceRebar(" not in by_name
    assert by_name["Width"].kind is MemberKind.PROPERTY


def test_extract_member_links_preserves_inherited_ownership():
    links = extract_member_links(
        _INLINE_TABLE_CLASS_PAGE_WITH_INHERITED_ROWS,
        "https://www.revitapidocs.com/2024/wall-class.htm",
    )
    by_name = {link["name"]: link for link in links}

    assert by_name["ArePhasesModifiable"]["declaring_type_hint"] == "Autodesk.Revit.DB.Element"
    assert "declaring_type_hint" not in by_name["Flip"]
    # Inherited but with no parseable owner: don't guess Wall, drop the row.
    assert "MysteryInherited" not in by_name


def test_parse_property_page_direct_return_type(load_fixture):
    html = load_fixture("property_familyinstance_symbol.htm")
    page = parse_member_page(
        html,
        "https://www.revitapidocs.com/2027/property_familyinstance_symbol.htm",
        "2027",
        declaring_type="Autodesk.Revit.DB.FamilyInstance",
    )
    assert page.kind is Kind.PROPERTY
    member = page.members[0]
    assert member.name == "Symbol"
    assert member.kind is MemberKind.PROPERTY
    assert member.return_type == "FamilySymbol"
    assert member.declaring_type == "Autodesk.Revit.DB.FamilyInstance"


def test_parse_property_page_elementid_return_type(load_fixture):
    html = load_fixture("property_view_viewtemplateid.htm")
    page = parse_member_page(
        html,
        "https://www.revitapidocs.com/2027/property_view_viewtemplateid.htm",
        "2027",
        declaring_type="Autodesk.Revit.DB.View",
    )
    member = page.members[0]
    assert member.name == "ViewTemplateId"
    assert member.return_type == "ElementId"
    assert "view template" in member.summary.lower()


def test_parse_enum_page(load_fixture):
    html = load_fixture("enum_builtinparameter.htm")
    page = parse_enum_page(html, "https://www.revitapidocs.com/2027/enum_builtinparameter.htm", "2027")

    assert page.kind is Kind.ENUM
    assert page.type_name == "BuiltInParameter"
    member_names = {m.member_name for m in page.enum_members}
    assert {"ROOM_NAME", "ROOM_NUMBER", "ROOM_AREA", "VIEW_NAME"} <= member_names
    room_number = next(m for m in page.enum_members if m.member_name == "ROOM_NUMBER")
    assert "number of the room" in room_number.description.lower()
    assert room_number.source_url == "https://www.revitapidocs.com/2027/enum_builtinparameter.htm"


def test_parse_room_class_and_number_property(load_fixture):
    class_html = load_fixture("class_room.htm")
    room_page = parse_type_page(class_html, "https://www.revitapidocs.com/2027/class_room.htm", "2027")
    assert room_page.full_type_name == "Autodesk.Revit.DB.Architecture.Room"
    member_names = {m.name for m in room_page.members}
    assert "Number" in member_names
    assert "Name" not in member_names

    number_html = load_fixture("property_room_number.htm")
    number_page = parse_member_page(
        number_html,
        "https://www.revitapidocs.com/2027/property_room_number.htm",
        "2027",
        declaring_type="Autodesk.Revit.DB.Architecture.Room",
    )
    number_member = number_page.members[0]
    assert number_member.return_type == "string"
    assert "room_number" in number_member.summary.lower().replace(" ", "_") or "room number" in number_member.summary.lower()


def test_real_members_index_page_sniffed_as_members_index(load_fixture):
    # tests/fixtures/real_wall_members.htm is the actual HTML (Wall Members,
    # Revit 2024) from the live site, confirming the class page does not
    # embed its members table inline -- see parse.py's module docstring.
    html = load_fixture("real_wall_members.htm")
    assert sniff_kind(html) is Kind.MEMBERS_INDEX


def test_parse_members_index_page_splits_methods_and_properties(load_fixture):
    html = load_fixture("real_wall_members.htm")
    url = "https://www.revitapidocs.com/2024/d0678575-843b-42ea-c91d-c94b13d7dd4f.htm"

    links, notes = parse_members_index_page(html, url)

    assert notes == []
    by_name = {link["name"]: link for link in links}
    assert by_name["ArePhasesModifiable"]["member_kind"] is MemberKind.METHOD
    assert by_name["ArePhasesModifiable"]["url"] == "https://www.revitapidocs.com/2024/329b02eb-5ee4-1715-2fbf-2cbbc0d3ff2a.htm"
    assert by_name["CrossSection"]["member_kind"] is MemberKind.PROPERTY
    assert by_name["Width"]["member_kind"] is MemberKind.PROPERTY
    # Inherited Object members with no page of their own (e.g. Equals) must
    # be omitted, not crawled as if they had a URL.
    assert "Equals" not in by_name

    # ArePhasesModifiable is real markup inherited from Element (data=
    # "public;inherited;notNetfw;"), not declared on Wall -- it must carry
    # Element as its declaring type, not Wall, so pipeline.py doesn't
    # attribute it to the wrong type. This fixture has no embedded namespace
    # JSON, so only the short name resolves here (see
    # test_parse_members_index_page_resolves_full_namespace_for_inherited_row
    # for the fully-qualified case).
    assert by_name["ArePhasesModifiable"]["declaring_type_hint"] == "Element"
    # Declared-on-Wall members must NOT get a declaring_type_hint override --
    # the caller's default (the current type) is correct for them.
    assert "declaring_type_hint" not in by_name["CrossSection"]
    assert "declaring_type_hint" not in by_name["Width"]


_MEMBERS_PAGE_WITH_NAMESPACE_AND_INHERITED_ROWS = """
<html><body>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<h4 id="api-title" class="truncate"> Wall Members </h4>
<div id="mainBody">
<h1 class="heading">Methods</h1>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="arephasesmodifiable.htm">ArePhasesModifiable</a></td><td>Returns true if... (Inherited from <a href="element.htm">Element</a>.)</td></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="flip.htm">Flip</a></td><td>Flips the wall.</td></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="mystery.htm">MysteryInherited</a></td><td>No parseable owner text here.</td></tr>
</table>
</div>
</body></html>
"""


def test_parse_members_index_page_resolves_full_namespace_for_inherited_row():
    links, notes = parse_members_index_page(
        _MEMBERS_PAGE_WITH_NAMESPACE_AND_INHERITED_ROWS,
        "https://www.revitapidocs.com/2024/wall-members.htm",
    )
    by_name = {link["name"]: link for link in links}

    assert by_name["ArePhasesModifiable"]["declaring_type_hint"] == "Autodesk.Revit.DB.Element"
    assert "declaring_type_hint" not in by_name["Flip"]

    # Inherited but with no parseable "(Inherited from X.)" text: better to
    # drop the row than mis-attribute it to Wall.
    assert "MysteryInherited" not in by_name
    assert notes == []


_ROOM_MEMBERS_PAGE_SUB_NAMESPACE_WITH_INHERITED_ROWS = """
<html><body>
<div id="TopicPathClassic"><a href="/2024/ns_db_architecture.htm">Autodesk.Revit.DB.Architecture</a> Namespace</div>
<h4 id="api-title" class="truncate"> Room Members </h4>
<div id="mainBody">
<h1 class="heading">Properties</h1>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="number.htm">Number</a></td><td>The room number. (Inherited from <a href="spatialelement.htm">SpatialElement</a>.)</td></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="volume.htm">Volume</a></td><td>The room volume.</td></tr>
</table>
</div>
</body></html>
"""


def test_parse_members_index_page_does_not_qualify_inherited_owner_with_sub_namespace():
    """Regression test: Room lives in Autodesk.Revit.DB.Architecture, but its
    real base types (SpatialElement, Element) live in the top-level
    Autodesk.Revit.DB namespace, not in .Architecture. Blindly prefixing the
    inherited owner with the *current page's* namespace would fabricate a
    nonexistent Autodesk.Revit.DB.Architecture.SpatialElement instead of the
    real Autodesk.Revit.DB.SpatialElement.
    """
    links, notes = parse_members_index_page(
        _ROOM_MEMBERS_PAGE_SUB_NAMESPACE_WITH_INHERITED_ROWS,
        "https://www.revitapidocs.com/2024/room-members.htm",
    )
    by_name = {link["name"]: link for link in links}

    assert by_name["Number"]["declaring_type_hint"] == "Autodesk.Revit.DB.SpatialElement"
    assert "declaring_type_hint" not in by_name["Volume"]
    assert notes == []


# Real markup shape from a live Revit 2025 run (Raspberry Pi, 2026-07, see
# docs/crawl_notes.md): the h1.heading section marker used in 2024 is gone,
# replaced by a collapsible region -- a <span class=collapsibleRegionTitle>
# (icon + section name as trailing text) followed by a sibling
# <div class=collapsibleSection> wrapping that section's table. Modeled on
# the real ACADExportOptions Properties page snippet the user pasted, with a
# Methods section added so both section kinds are exercised in one page.
_MEMBERS_PAGE_2025_COLLAPSIBLE_REGIONS = """
<html><body>
<h4 id="api-title" class="truncate"> Wall Members </h4>
<div id="mainBody">
<div class=collapsibleAreaRegion>
<span class=collapsibleRegionTitle tabindex=0><img class=collapseToggle src='sectionexpanded.png'> Methods</span>
</div>
<div class=collapsibleSection id=IDMethodsSection>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="flip.htm">Flip</a></td><td>Flips the wall.</td></tr>
</table>
</div>
<div class=collapsibleAreaRegion>
<span class=collapsibleRegionTitle tabindex=0><img class=collapseToggle src='sectionexpanded.png'> Properties</span>
</div>
<div class=collapsibleSection id=IDPropertiesSection>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;declared;notNetfw;"><td><img></td><td><a href="width.htm">Width</a></td><td>The wall width.</td></tr>
</table>
</div>
</div>
</body></html>
"""


def test_parse_members_index_page_recognizes_2025_collapsible_region_headings():
    links, notes = parse_members_index_page(
        _MEMBERS_PAGE_2025_COLLAPSIBLE_REGIONS,
        "https://www.revitapidocs.com/2025/wall-members.htm",
    )
    by_name = {link["name"]: link for link in links}

    assert notes == []
    assert by_name["Flip"]["member_kind"] is MemberKind.METHOD
    assert by_name["Width"]["member_kind"] is MemberKind.PROPERTY


# Real markup shape from a live Revit 2025 run (Raspberry Pi, 2026-07, see
# docs/crawl_notes.md): the syntax block moved into a per-language "code
# snippet" widget -- one div.codeSnippetContainerCode per .NET language
# (cs/vb/cpp/fs), each with its own <pre><code>, individual tokens wrapped in
# <span class=keyword>/<span class=identifier> etc. Modeled on the real
# ACAPreference property page snippet the user pasted (a simple property:
# "public ACAObjectPreference ACAPreference { get; set; }"). The vb block is
# deliberately placed *before* the cs one here (the reverse of the real
# page's order) to prove the fix selects by the ".cs" class specifically,
# not merely "whichever <pre> comes first in the document".
_PROPERTY_PAGE_2025_CODE_SNIPPET_WIDGET = """
<html><body>
<h4 id="api-title" class="truncate"> ACAPreference Property </h4>
<div id="mainBody">
<div class=codeSnippetContainerCodeContainer>
<div class="codeSnippetContainerCode vb" id=IDAB_code_Div2 style="display: none">
<pre><code><span class=keyword>Public</span> <span class=keyword>Property</span> <span class=identifier>ACAPreference</span> <span class=keyword>As</span> <span class=identifier>ACAObjectPreference</span></code></pre>
</div>
<div class="codeSnippetContainerCode cs" id=IDAB_code_Div1 style="display: block">
<pre><code><span class=keyword>public</span> <span class=identifier>ACAObjectPreference</span> <span class=identifier>ACAPreference</span> { <span class=keyword>get</span>; <span class=keyword>set</span>; }</code></pre>
</div>
</div>
</div>
</body></html>
"""


def test_parse_member_page_recognizes_2025_code_snippet_widget_syntax_block():
    """Regression test for the 2025 finding that zeroed out every candidate
    edge crawl-wide: with no _SYNTAX_SELECTORS match, every member page's
    return_type came back None, and classify.classify_member refuses to
    consider any edge rule at all without one.
    """
    page = parse_member_page(
        _PROPERTY_PAGE_2025_CODE_SNIPPET_WIDGET,
        "https://www.revitapidocs.com/2025/1a97e079-901e-56e0-252d-2b030d04e595.htm",
        "2025",
        declaring_type="Autodesk.Revit.DB.ACADExportOptions",
    )
    assert page.kind is Kind.PROPERTY
    member = page.members[0]
    assert member.name == "ACAPreference"
    assert member.return_type == "ACAObjectPreference"
    assert member.kind is MemberKind.PROPERTY
    # This minimal fixture has no embedded templateData JSON/breadcrumb (see
    # test_resolve_type_name_from_members_index_without_namespace_json for
    # the same documented limitation), so a namespace-lookup note is
    # expected here -- what matters is the *syntax-block* note is gone.
    assert not any("syntax block" in note for note in page.parser_notes)


def test_find_members_page_link(load_fixture):
    html = load_fixture("real_wall_members.htm")
    url = "https://www.revitapidocs.com/2024/d0678575-843b-42ea-c91d-c94b13d7dd4f.htm"

    # This fixture *is* the Members page, so its own nav points back to the
    # class page under the "Wall Class" label, not a "Members" label.
    assert find_members_page_link(html, url) is None


def test_resolve_type_name_from_members_index_without_namespace_json(load_fixture):
    # This fixture is trimmed and doesn't include the <script> block with the
    # embedded templateData.namespace JSON, so this only recovers the short
    # name -- documents the current fallback behavior rather than asserting
    # a namespace that isn't in the fixture.
    html = load_fixture("real_wall_members.htm")
    assert resolve_type_name_from_members_index(html) == "Wall"


# Real titles from a live overloaded-method page (Element.ChangeTypeId),
# confirmed via a Raspberry Pi run -- Sandcastle appends the overload's
# parameter-type list *after* the kind suffix, so a bare `.endswith("Method")`
# check never matches and these were falling through to "unrecognized page
# kind ...; skipping" instead of being parsed as Kind.METHOD.
def test_strip_trailing_overload_signature_single_param():
    assert _strip_trailing_overload_signature("ChangeTypeId Method (ElementId)") == "ChangeTypeId Method"


def test_strip_trailing_overload_signature_nested_parens():
    # The parameter list itself contains parens (ICollection(ElementId)) --
    # a naive non-greedy regex would stop at the first ')' and mis-strip.
    title = "ChangeTypeId Method (Document, ICollection(ElementId), ElementId)"
    assert _strip_trailing_overload_signature(title) == "ChangeTypeId Method"


def test_strip_trailing_overload_signature_no_op_when_no_trailing_parens():
    assert _strip_trailing_overload_signature("Wall Class") == "Wall Class"


def test_strip_kind_suffix_handles_overload_signature():
    assert _strip_kind_suffix("ChangeTypeId Method (ElementId)") == "ChangeTypeId"
    assert _strip_kind_suffix("ChangeTypeId Method (Document, ICollection(ElementId), ElementId)") == "ChangeTypeId"


def test_sniff_kind_recognizes_overloaded_method_page():
    html = '<html><body><h4 id="api-title" class="truncate"> ChangeTypeId Method (ElementId) </h4></body></html>'
    assert sniff_kind(html) is Kind.METHOD


def test_parse_member_page_overloaded_method_title():
    html = """
    <html><body>
    <h4 id="api-title" class="truncate"> ChangeTypeId Method (ElementId) </h4>
    <div id="mainBody">
    <div class="syntax"><pre class="typeSignature">public void ChangeTypeId(ElementId typeId)</pre></div>
    </div>
    </body></html>
    """
    page = parse_member_page(
        html,
        "https://www.revitapidocs.com/2024/changetypeid-elementid.htm",
        "2024",
        declaring_type="Autodesk.Revit.DB.Element",
    )
    assert page.kind is Kind.METHOD
    assert page.type_name == "ChangeTypeId"
    assert page.members[0].name == "ChangeTypeId"


def test_parse_member_page_constructor_has_no_return_type():
    """Regression test for a real Revit 2025 finding: a constructor's syntax
    block ("public AreaTagFilter ()") has nothing between the access
    modifier and the constructor's own name for _MEMBER_SIG_RE's required
    <return_type> group to leave empty, so it backtracks into capturing
    "public" itself as return_type. That garbage return_type then flowed
    into classify.classify_member and produced a bogus name_only_candidate
    edge for every constructor in the crawl (98 of them) -- all correctly
    caught by Stage B as MEMBER_NOT_FOUND, but the real bug was upstream
    here. A constructor has no return type in C# at all, so return_type
    must always come out None (which classify_member already treats as
    "never build an edge").
    """
    html = """
    <html><body>
    <h4 id="api-title" class="truncate"> AreaTagFilter Constructor </h4>
    <div id="mainBody">
    <div class="syntax"><pre class="typeSignature">public AreaTagFilter ()</pre></div>
    </div>
    </body></html>
    """
    page = parse_member_page(
        html,
        "https://www.revitapidocs.com/2025/areatagfilter-constructor.htm",
        "2025",
        declaring_type="Autodesk.Revit.DB.AreaTagFilter",
    )
    assert page.kind is Kind.CONSTRUCTOR
    member = page.members[0]
    assert member.name == "AreaTagFilter"
    assert member.return_type is None
    assert any("discarding constructor" in note for note in page.parser_notes)

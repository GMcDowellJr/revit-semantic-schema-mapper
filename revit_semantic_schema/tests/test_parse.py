from revit_schema_mapper.models import Kind, MemberKind
from revit_schema_mapper.parse import (
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

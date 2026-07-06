from revit_schema_mapper.models import Kind, MemberKind
from revit_schema_mapper.parse import extract_member_links, parse_enum_page, parse_member_page, parse_type_page


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

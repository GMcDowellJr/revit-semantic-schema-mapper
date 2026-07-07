import json

from revit_schema_mapper import export
from revit_schema_mapper.models import ApiPage, Kind, MemberInfo, MemberKind


def _page_with_doc_text() -> ApiPage:
    member = MemberInfo(
        name="Symbol",
        kind=MemberKind.PROPERTY,
        declaring_type="Autodesk.Revit.DB.FamilyInstance",
        raw_signature="public FamilySymbol Symbol { get; }",
        summary="Gets the FamilySymbol object.",
        remarks="Some copied remarks text from the docs site.",
        examples=["var symbol = instance.Symbol;"],
    )
    return ApiPage(
        revit_version="2024",
        namespace="Autodesk.Revit.DB",
        type_name="FamilyInstance",
        full_type_name="Autodesk.Revit.DB.FamilyInstance",
        kind=Kind.CLASS,
        members=[member],
        summary="A copied summary block from the docs site.",
        remarks="A copied remarks block from the docs site.",
        examples=["var x = new FamilyInstance();"],
        source_url="https://www.revitapidocs.com/2024/familyinstance-class.htm",
    )


def test_write_api_pages_redacts_doc_text_by_default(tmp_path):
    export.write_api_pages(tmp_path, [_page_with_doc_text()])

    written = json.loads((tmp_path / "api_pages.json").read_text())
    assert len(written) == 1
    page = written[0]
    assert page["summary"] == ""
    assert page["remarks"] == ""
    assert page["examples"] == []
    assert page["members"][0]["summary"] == ""
    assert page["members"][0]["remarks"] == ""
    assert page["members"][0]["examples"] == []
    # Facts, not prose, must survive redaction.
    assert page["full_type_name"] == "Autodesk.Revit.DB.FamilyInstance"
    assert page["source_url"] == "https://www.revitapidocs.com/2024/familyinstance-class.htm"
    assert page["members"][0]["name"] == "Symbol"
    assert page["members"][0]["raw_signature"] == "public FamilySymbol Symbol { get; }"


def test_write_api_pages_include_doc_text_opt_in(tmp_path):
    export.write_api_pages(tmp_path, [_page_with_doc_text()], include_doc_text=True)

    written = json.loads((tmp_path / "api_pages.json").read_text())
    page = written[0]
    assert page["summary"] == "A copied summary block from the docs site."
    assert page["members"][0]["remarks"] == "Some copied remarks text from the docs site."


def test_write_api_pages_redaction_does_not_mutate_input_pages(tmp_path):
    page = _page_with_doc_text()
    export.write_api_pages(tmp_path, [page])

    assert page.summary == "A copied summary block from the docs site."
    assert page.members[0].remarks == "Some copied remarks text from the docs site."

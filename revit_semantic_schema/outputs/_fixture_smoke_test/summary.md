# Revit Semantic Schema Mapper - Run Summary

## 1. Crawl scope
- Revit version: 2027 (FIXTURE SMOKE TEST - not a live crawl)
- Namespace: Autodesk.Revit.DB

## 2. Pages discovered
- 8

## 3. Pages parsed
- 8

## 4. Node candidates
- 4

## 5. Property relationship candidates
- 3

## 6. Method relationship candidates
- 0

## 7. Enum members extracted
- 7

## 8. Top 25 highest-confidence candidate edges
- `Autodesk.Revit.DB.FamilyInstance.Symbol` -> **INSTANCE_OF** -> `Autodesk.Revit.DB.FamilySymbol` (`direct_return_type`; return type `FamilySymbol`)
- `Autodesk.Revit.DB.View.ViewTemplateId` -> **CONTROLLED_BY_TEMPLATE** -> `Autodesk.Revit.DB.View` (`elementid_with_strong_name`; return type `ElementId`)
- `Autodesk.Revit.DB.Element.Id` -> **UNKNOWN_ELEMENTID_REFERENCE** -> `?` (`unknown_reference`; return type `ElementId`)

## 9. Top 25 uncertain candidates needing review
- `Autodesk.Revit.DB.Element.Id` -> **UNKNOWN_ELEMENTID_REFERENCE** -> `?` (`unknown_reference`; return type `ElementId`)
- `Autodesk.Revit.DB.View.ViewTemplateId` -> **CONTROLLED_BY_TEMPLATE** -> `Autodesk.Revit.DB.View` (`elementid_with_strong_name`; return type `ElementId`)
- `Autodesk.Revit.DB.FamilyInstance.Symbol` -> **INSTANCE_OF** -> `Autodesk.Revit.DB.FamilySymbol` (`direct_return_type`; return type `FamilySymbol`)

## 10. Room / Room Number / Room Name findings
## Room / Room Number / Room Name investigation

Source: https://www.revitapidocs.com/2027/class_room.htm
Members seen on Room page: ['Number']
- `Number` found as a distinct member on Room (supports keeping Number separate from Name).
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).

## 11. Limitations
- This is a smoke test run against static fixtures, not a live crawl.

## 12. Recommended next steps
- Run the real crawler once network access to revitapidocs.com is available.

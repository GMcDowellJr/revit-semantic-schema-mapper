# Revit Semantic Schema Mapper - Run Summary

## 1. Crawl scope
- Revit version: 2024
- Namespace: Autodesk.Revit.DB

## 2. Pages discovered
- 28459

## 3. Pages parsed
- 23241

## 4. Node candidates
- 2421

## 5. Property relationship candidates
- 8003

## 6. Method relationship candidates
- 2694

## 7. Enum members extracted
- 8415

## 8. Top 25 highest-confidence candidate edges
- `Autodesk.Revit.DB.ACADExportOptions.HatchBackgroundColor` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Color` (`direct_return_type`; return type `Color`)
- `Autodesk.Revit.DB.AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.FamilyInstance` (`direct_return_type`; return type `FamilyInstance`)
- `Autodesk.Revit.DB.AngularDimension.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AngularDimension` (`direct_return_type`; return type `AngularDimension`)
- `Autodesk.Revit.DB.AnnotationSymbol.duplicate` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AnnotationSymbol` (`direct_return_type`; return type `AnnotationSymbol`)
- `Autodesk.Revit.DB.AnnotationSymbol.AnnotationSymbolType` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AnnotationSymbolType` (`direct_return_type`; return type `AnnotationSymbolType`)
- `Autodesk.Revit.DB.AppearanceAssetElement.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AppearanceAssetElement` (`direct_return_type`; return type `AppearanceAssetElement`)
- `Autodesk.Revit.DB.AppearanceAssetElement.Duplicate` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AppearanceAssetElement` (`direct_return_type`; return type `AppearanceAssetElement`)
- `Autodesk.Revit.DB.AppearanceAssetElement.GetAppearanceAssetElementByName` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AppearanceAssetElement` (`direct_return_type`; return type `AppearanceAssetElement`)
- `Autodesk.Revit.DB.AppearanceAssetElement.GetRenderingAsset` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Asset` (`direct_return_type`; return type `Asset`)
- `Autodesk.Revit.DB.Arc.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Arc` (`direct_return_type`; return type `Arc`)
- `Autodesk.Revit.DB.Arc.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Arc` (`direct_return_type`; return type `Arc`)
- `Autodesk.Revit.DB.Arc.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Arc` (`direct_return_type`; return type `Arc`)
- `Autodesk.Revit.DB.Area.AreaScheme` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AreaScheme` (`direct_return_type`; return type `AreaScheme`)
- `Autodesk.Revit.DB.AreaTag.Area` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Area` (`direct_return_type`; return type `Area`)
- `Autodesk.Revit.DB.AreaTag.AreaTagType` -> **TAGS_ELEMENT** -> `Autodesk.Revit.DB.AreaTagType` (`direct_return_type`; return type `AreaTagType`)
- `Autodesk.Revit.DB.AreaVolumeSettings.GetAreaVolumeSettings` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AreaVolumeSettings` (`direct_return_type`; return type `AreaVolumeSettings`)
- `Autodesk.Revit.DB.AssemblyCodeTable.GetAssemblyCodeTable` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.AssemblyCodeTable` (`direct_return_type`; return type `AssemblyCodeTable`)
- `Autodesk.Revit.DB.AssemblyDifferenceMemberDifference.MemberDifference` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AssemblyMemberDifference` (`direct_return_type`; return type `AssemblyMemberDifference`)
- `Autodesk.Revit.DB.AssemblyInstance.CompareAssemblyInstances` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.AssemblyDifference` (`direct_return_type`; return type `AssemblyDifference`)
- `Autodesk.Revit.DB.AssemblyInstance.Create` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AssemblyInstance` (`direct_return_type`; return type `AssemblyInstance`)
- `Autodesk.Revit.DB.AssemblyInstance.GetTransform` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Transform` (`direct_return_type`; return type `Transform`)
- `Autodesk.Revit.DB.AssemblyInstance.PlaceInstance` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.AssemblyInstance` (`direct_return_type`; return type `AssemblyInstance`)
- `Autodesk.Revit.DB.AssemblyInstance.Location` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Location` (`direct_return_type`; return type `Location`)
- `Autodesk.Revit.DB.AssemblyViewUtils.Create3DOrthographic` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.View3D` (`direct_return_type`; return type `View3D`)
- `Autodesk.Revit.DB.AssemblyViewUtils.Create3DOrthographic` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.View3D` (`direct_return_type`; return type `View3D`)

## 9. Top 25 uncertain candidates needing review
- `Autodesk.Revit.DB.AlphanumericRevisionSettings.GetSequence` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.string` (`needs_runtime_validation`; return type `IList < string >`)
- `Autodesk.Revit.DB.AnnotationSymbol.GetLeaders` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Leader` (`needs_runtime_validation`; return type `IList < Leader >`)
- `Autodesk.Revit.DB.BaseExportOptions.GetPredefinedSetupNames` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.string` (`needs_runtime_validation`; return type `IList < string >`)
- `Autodesk.Revit.DB.BaseImportOptions.GetLayerSelection` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.string` (`needs_runtime_validation`; return type `ICollection < string >`)
- `Autodesk.Revit.DB.BrowserOrganization.GetFolderItems` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.FolderItemInfo` (`needs_runtime_validation`; return type `IList < FolderItemInfo >`)
- `Autodesk.Revit.DB.ColorFillLegend.GetColumnWidths` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.double` (`needs_runtime_validation`; return type `IList < double >`)
- `Autodesk.Revit.DB.ColorFillScheme.GetEntries` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.ColorFillSchemeEntry` (`needs_runtime_validation`; return type `IList < ColorFillSchemeEntry >`)
- `Autodesk.Revit.DB.ComponentRepeater.RepeatElements` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.ComponentRepeater` (`needs_runtime_validation`; return type `IList < ComponentRepeater >`)
- `Autodesk.Revit.DB.CompoundStructure.GetAdjacentRegions` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetExtendableRegionIds` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetLayers` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.CompoundStructureLayer` (`needs_runtime_validation`; return type `IList < CompoundStructureLayer >`)
- `Autodesk.Revit.DB.CompoundStructure.GetRegionIds` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetRegionsAlongLevel` -> **ASSIGNED_TO_LEVEL** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetRegionsAssociatedToLayer` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetSegmentIds` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.int` (`needs_runtime_validation`; return type `IList < int >`)
- `Autodesk.Revit.DB.CompoundStructure.GetWallSweepsInfo` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.WallSweepInfo` (`needs_runtime_validation`; return type `IList < WallSweepInfo >`)
- `Autodesk.Revit.DB.ContourSetting.GetContourSettingItems` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.ContourSettingItem` (`needs_runtime_validation`; return type `IList < ContourSettingItem >`)
- `Autodesk.Revit.DB.CurtainGrid.GetCurtainCells` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.CurtainCell` (`needs_runtime_validation`; return type `ICollection < CurtainCell >`)
- `Autodesk.Revit.DB.Curve.Tessellate` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.XYZ` (`needs_runtime_validation`; return type `IList < XYZ >`)
- `Autodesk.Revit.DB.CurveByPointsUtils.GetFaceRegions` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Reference` (`needs_runtime_validation`; return type `IList < Reference >`)
- `Autodesk.Revit.DB.CurveElement.CreateAreaBasedLoadBoundaryLines` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.CurveElement` (`needs_runtime_validation`; return type `IList < CurveElement >`)
- `Autodesk.Revit.DB.CurveUV.ComputeDerivatives` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.UV` (`needs_runtime_validation`; return type `IList < UV >`)
- `Autodesk.Revit.DB.DatumPlane.GetCurvesInView` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.Curve` (`needs_runtime_validation`; return type `IList < Curve >`)
- `Autodesk.Revit.DB.DGNExportOptions.GetPredefinedSetupNames` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.string` (`needs_runtime_validation`; return type `IList < string >`)
- `Autodesk.Revit.DB.DimensionType.GetEqualityFormula` -> **UNKNOWN_DB_OBJECT_REFERENCE** -> `Autodesk.Revit.DB.DimensionEqualityLabelFormatting` (`needs_runtime_validation`; return type `IList < DimensionEqualityLabelFormatting >`)

## 10. Room / Room Number / Room Name findings
## Room / Room Number / Room Name investigation

Source: https://www.revitapidocs.com/2024/80cd8f7f-bb92-6442-ac78-0ed17376844f.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/6044a7f3-bf19-498b-2724-c1458429423c.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/37944e7a-f298-9c25-20bb-9c0c1da46f41.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/5c1ed572-e744-3ab6-9b10-bb258a66f23a.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/026acd60-1c8b-984f-4b9b-a0c36bef998f.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/226a0235-822e-02a3-e0e3-34b39b54ef3a.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/75c9d2c7-a402-ea8b-9e7c-f8bc3510bbd5.htm
Members seen on Room page: none parsed
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/d6156ddf-27d5-5311-0887-5d8a326e9e99.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).
Source: https://www.revitapidocs.com/2024/e6b482cd-2466-0bc0-77ca-c40d2adaa3c7.htm
Members seen on Room page: ['Room']
- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).

## 11. Limitations
- Edge classification is a static, docs-only heuristic; no candidate edge has been validated against a live Revit document (see confidence label needs_runtime_validation).
- Member pages reachable only via a type's members table are discovered incrementally during parsing; a partial/interrupted crawl can under-count members for the last few types processed.
- Name-keyword-to-edge-type mapping (classify.py) is heuristic and English-name-based; it will misclassify or under-classify members whose names don't match the documented keyword list.
- 138 page(s) failed to fetch or parse: ['https://www.revitapidocs.com/2024/93d26466-11de-842c-f089-6b15b839e6af.htm', 'https://www.revitapidocs.com/2024/8f200255-a515-0c02-656b-b241e0011228.htm', 'https://www.revitapidocs.com/2024/8d74cf02-9271-3c6c-00f5-bc7b48d52c56.htm', 'https://www.revitapidocs.com/2024/77aa9939-8f41-1725-80dc-864ca1f7a49c.htm', 'https://www.revitapidocs.com/2024/2f482b62-410e-2db9-b6b9-c64abedcbc4c.htm', 'https://www.revitapidocs.com/2024/7ace570d-870f-be20-e493-e80ffa27f454.htm', 'https://www.revitapidocs.com/2024/26a118b5-c583-a9b2-c935-c11b270e140e.htm', 'https://www.revitapidocs.com/2024/e46e0d8f-5bcb-46bf-5def-03af68327b9e.htm', 'https://www.revitapidocs.com/2024/ace39293-a976-d22b-4798-42bb8e82b307.htm', 'https://www.revitapidocs.com/2024/941de0b6-a0f9-eb5a-5f25-9aa4d9da699a.htm'] ...

## 12. Recommended next steps
- Run against a live revitapidocs.com session and diff parser_notes across all pages to find and fix selector assumptions that didn't hold (see docs/crawl_notes.md).
- Expand the name-keyword edge taxonomy with additional evidence gathered from real docs text (docs_semantic_hint) rather than name matching alone.
- Cross-check high-confidence candidate edges (direct_return_type, elementid_with_strong_name) against a small number of real Revit documents to promote them out of 'candidate' status.
- Extend to Autodesk.Revit.DB.Architecture and Autodesk.Revit.DB.Structure for Room/Space and structural element coverage once the core DB namespace is validated.

## 14. Knowledge graph materialization

`graph.json`/`graph_core.json` resolve each edge's `candidate_target_type` string against the crawled node set (see graph.py) instead of leaving it as a loose type name.
- 2426 total nodes (5 external -- referenced by an edge but never crawled/classified)
- 10697 total edges
- Target resolution: exact=9017, external=69, none=965, short_name_fallback=646
- Confidence tier breakdown: core=1241, likely=623, needs_validation=368, unverified_reference=8465
- `graph_core.json` (confidence_tier=core only): 330 nodes, 1241 edges


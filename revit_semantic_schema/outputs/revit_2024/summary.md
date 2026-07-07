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
- `Autodesk.Revit.DB.AreaTag.AreaTagType` -> **TAGS_ELEMENT** -> `Autodesk.Revit.DB.AreaTagType` (`direct_return_type`; return type `AreaTagType`)
- `Autodesk.Revit.DB.AssemblyCodeTable.GetAssemblyCodeTable` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.AssemblyCodeTable` (`direct_return_type`; return type `AssemblyCodeTable`)
- `Autodesk.Revit.DB.AssemblyInstance.CompareAssemblyInstances` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.AssemblyDifference` (`direct_return_type`; return type `AssemblyDifference`)
- `Autodesk.Revit.DB.AssemblyViewUtils.CreateMaterialTakeoff` -> **USES_MATERIAL** -> `Autodesk.Revit.DB.ViewSchedule` (`direct_return_type`; return type `ViewSchedule`)
- `Autodesk.Revit.DB.AssemblyViewUtils.CreateMaterialTakeoff` -> **USES_MATERIAL** -> `Autodesk.Revit.DB.ViewSchedule` (`direct_return_type`; return type `ViewSchedule`)
- `Autodesk.Revit.DB.AssemblyViewUtils.CreateSheet` -> **PLACED_ON_SHEET** -> `Autodesk.Revit.DB.ViewSheet` (`direct_return_type`; return type `ViewSheet`)
- `Autodesk.Revit.DB.AssemblyViewUtils.CreateSingleCategorySchedule` -> **HAS_CATEGORY** -> `Autodesk.Revit.DB.ViewSchedule` (`direct_return_type`; return type `ViewSchedule`)
- `Autodesk.Revit.DB.AssemblyViewUtils.CreateSingleCategorySchedule` -> **HAS_CATEGORY** -> `Autodesk.Revit.DB.ViewSchedule` (`direct_return_type`; return type `ViewSchedule`)
- `Autodesk.Revit.DB.BeamSystem.Level` -> **ASSIGNED_TO_LEVEL** -> `Autodesk.Revit.DB.Level` (`direct_return_type`; return type `Level`)
- `Autodesk.Revit.DB.BrowserOrganization.GetCurrentBrowserOrganizationForSheets` -> **PLACED_ON_SHEET** -> `Autodesk.Revit.DB.BrowserOrganization` (`direct_return_type`; return type `BrowserOrganization`)
- `Autodesk.Revit.DB.BuiltInFailures.AnalyticalModelFailures.HighestAssociatedLevelBelowLowestAssociatedLevel` -> **ASSIGNED_TO_LEVEL** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AnalyticalModelFailures.LowestAssociatedLevelAboveHighestAssociatedLevel` -> **ASSIGNED_TO_LEVEL** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.ArrayFailures.CannotCreateArraySelectionIsGrouped` -> **MEMBER_OF_GROUP** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.ArrayFailures.CouldntFindNewHostsForElements` -> **HOSTED_BY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AddedElementsNotSamePhaseAsAssembly` -> **ASSIGNED_TO_PHASE** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyDeleteTypeWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyDidNotMatchRequestedTypeWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyDisassembleInstanceWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyInheritTypeWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyInvalidMember` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyNewTypeWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.AssemblyRenameTypeWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.CouldNotAcquireAssemblyViews` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.CouldNotChangeTypeOfAssembly` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)
- `Autodesk.Revit.DB.BuiltInFailures.AssemblyFailures.DeleteAssemblyInstWithViewsWarn` -> **MEMBER_OF_ASSEMBLY** -> `Autodesk.Revit.DB.FailureDefinitionId` (`direct_return_type`; return type `FailureDefinitionId`)

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

## 10. Unknown-reference target type breakdown
Both UNKNOWN_* edge types mean 'definitely a reference, but no keyword/docs evidence identifies which specific relationship' -- per docs/edge_taxonomy_v0.md, that's the conservative, honest label, not a bug to fix by guessing a specific type. This breakdown exists so a concentration in a few target types (e.g. a generic identifier type referenced from all over the API) is visible here instead of only discoverable by querying candidate_edges.json directly.
- 8578 total UNKNOWN_* edges, 781 distinct target type(s)
  - `Autodesk.Revit.DB.ForgeTypeId`: 4031 (47%)
  - `Autodesk.Revit.DB.FailureDefinitionId`: 2067 (24%)
  - `(none)`: 366 (4%)
  - `Autodesk.Revit.DB.Curve`: 65 (1%)
  - `Autodesk.Revit.DB.Color`: 52 (1%)
  - `Autodesk.Revit.DB.Transform`: 49 (1%)
  - `Autodesk.Revit.DB.Reference`: 46 (1%)
  - `Autodesk.Revit.DB.ExternalServiceId`: 46 (1%)
  - `Autodesk.Revit.DB.CurveLoop`: 35 (0%)
  - `Autodesk.Revit.DB.XYZ`: 32 (0%)
  - `Autodesk.Revit.DB.FilterRule`: 32 (0%)
  - `Autodesk.Revit.DB.IFCAnyHandle`: 27 (0%)
  - `Autodesk.Revit.DB.string`: 22 (0%)
  - `Autodesk.Revit.DB.Solid`: 22 (0%)
  - `Autodesk.Revit.DB.Element`: 22 (0%)
  - ...and 766 more target type(s)

## 11. Room / Room Number / Room Name findings
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

## 12. Limitations
- Edge classification is a static, docs-only heuristic; no candidate edge has been validated against a live Revit document (see confidence label needs_runtime_validation).
- Member pages reachable only via a type's members table are discovered incrementally during parsing; a partial/interrupted crawl can under-count members for the last few types processed.
- Name-keyword-to-edge-type mapping (classify.py) is heuristic and English-name-based; it will misclassify or under-classify members whose names don't match the documented keyword list.
- 138 page(s) failed to fetch or parse during the original crawl (not re-derived here -- failed_urls isn't persisted to disk by the pipeline; see the original crawl's console output).

## 13. Recommended next steps
- Run against a live revitapidocs.com session and diff parser_notes across all pages to find and fix selector assumptions that didn't hold (see docs/crawl_notes.md).
- Expand the name-keyword edge taxonomy with additional evidence gathered from real docs text (docs_semantic_hint) rather than name matching alone.
- Cross-check high-confidence candidate edges (direct_return_type, elementid_with_strong_name) against a small number of real Revit documents to promote them out of 'candidate' status.
- Extend to Autodesk.Revit.DB.Architecture and Autodesk.Revit.DB.Structure for Room/Space and structural element coverage once the core DB namespace is validated.

## 14. Knowledge graph materialization

`graph.json`/`graph_core.json` resolve each edge's `candidate_target_type` string against the crawled node set (see graph.py) instead of leaving it as a loose type name.
- 2441 total nodes (20 external -- referenced by an edge but never crawled/classified)
- 10697 total edges
- Target resolution: exact=9017, external=69, none=965, short_name_fallback=646
- Confidence tier breakdown: core=1241, likely=623, needs_validation=368, unverified_reference=8465
- `graph_core.json` (confidence_tier=core only): 289 nodes, 1148 edges
- 53 communities detected over the core subgraph (heuristic=53 labels)
- Largest communities:
  - `FailureDefinitionId · BuiltInFailures.GroupFailures · BuiltInFailures.FamilyFailures` (72 nodes)
  - `Category · ConceptualSurfaceType · ConceptualConstructionType` (26 nodes)
  - `Material · MassSurfaceData · EnergyAnalysisConstruction` (19 nodes)
  - `Level · MultistoryStairs · Railing` (17 nodes)
  - `ViewSheet · FabricArea · FabricSheetType` (8 nodes)
  - `ForgeTypeId · ParameterTypeId · InternalDefinition` (8 nodes)
  - `Reference · RebarConstraint · DividedSurface` (7 nodes)
  - `Element · Parameter · ChangeType` (6 nodes)
  - `Phase · EnergyDataSettings · PlanTopology` (5 nodes)
  - `FillPatternElement · MEPSystemType · ColorFillSchemeEntry` (4 nodes)


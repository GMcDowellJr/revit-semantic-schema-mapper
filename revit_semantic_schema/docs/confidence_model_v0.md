# Confidence model v0

Every candidate edge carries exactly one of these labels in `edge_confidence`. They are not a
strict linear ranking (see the note on `needs_runtime_validation` and `docs_semantic_hint`
below) but for the purpose of "top 25 highest-confidence" / "top 25 uncertain" lists in
`summary.md`, they are ranked in the order listed here, most to least trustworthy.

1. **`direct_return_type`**
   The return type directly names another Revit DB object type, such as `FamilySymbol` or
   `Material`. This is the strongest static signal available from docs alone: the compiler
   itself guarantees the relationship's target type.

2. **`elementid_with_strong_name`**
   The return type is `ElementId` and the member name strongly indicates the target, such as
   `ViewTemplateId` or `MaterialId`. `ElementId` erases the target type, so this relies on
   naming convention rather than the type system.

3. **`elementid_collection_with_strong_name`**
   The return type is a collection of `ElementId` and the member name strongly indicates
   relationship semantics (e.g. `GetDependentElements`). Same caveat as above, plus
   cardinality is many-valued.

4. **`docs_semantic_hint`**
   The docs summary or remarks explicitly describe the relationship in prose, independent of
   (or compensating for) weak type/name evidence. Applied as an upgrade from
   `name_only_candidate` / `unknown_reference` when a relationship phrase is found in the
   member's summary or remarks text.

5. **`name_only_candidate`**
   The member name suggests a relationship, but the return type is a primitive
   (`bool`/`int`/`string`/etc.) or otherwise gives no independent confirmation.

6. **`unknown_reference`**
   The member appears reference-like (returns `ElementId` or a DB object type) but neither
   the name nor the docs text gives a confident target or semantics. This is the deliberately
   honest fallback — see the taxonomy doc's precedence note about preferring this over a
   guessed specific type.

7. **`needs_runtime_validation`**
   The edge cannot be trusted from static docs alone and requires testing against an actual
   Revit document to confirm — for example, a method returning a generic collection whose
   element type isn't independently confirmed to be reference-bearing, or any edge where the
   direction/cardinality is ambiguous from documentation alone. This label is a flag for
   "don't trust this without running it," not a statement that the edge is more or less
   likely to be real than `unknown_reference`; it's a distinct axis (verifiability) rather
   than a point further down the same confidence ranking.

None of these labels should ever be read as "this edge is a fact." The project's whole
premise is that everything produced here is a *candidate* schema mined from documentation
text and static typing, not a verified data model — see the Non-goals section of the top
level README.

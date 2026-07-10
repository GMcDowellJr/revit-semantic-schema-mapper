# DLL reflection v0 (design)

**Status: all three stages implemented.** Stage A (`reflect_revit_api.ps1`), Stage B
(`ground_truth.cross_validate_dll`, wired into `__main__.py` as `--cross-validate-dll`), and
Stage C (`revitlookup.py`'s mining, plus `ground_truth.cross_validate_revitlookup`, wired into
`__main__.py` as `--cross-validate-revitlookup`) all exist and are tested. This document
remains the design record and the source of truth for *why* each stage works the way it does —
see "Workflow once built" below for the actual commands. This documents the project's
cross-validation of the docs-derived *candidate* schema (`node_type_candidates.json` /
`candidate_edges.json`) against **ground truth** read directly from the compiled
`Autodesk.Revit.DB` assemblies via .NET reflection (Stage A/B) and from RevitLookup's own
public descriptor source (Stage C), instead of trusting revitapidocs.com's HTML alone.

## Why this matters

Everything the pipeline has produced so far (`crawl.py` → `parse.py` → `classify.py`) is
mined from documentation text. `docs/crawl_notes.md` already has two concrete examples of
docs and reality disagreeing:

- `Material.SurfacePatternId`/`CutPatternId` don't exist in the real Revit 2024 API at all —
  only found by cross-checking a live crawl's actual member list against
  `DEFAULT_KNOWN_EDGE_CHECKS`, a fixed hand-written list of nine checks.
- `Room.Number` is inherited from an intermediate base class not obvious from `Room`'s own
  docs page, and the crawler's guess at that base type's fully-qualified name was itself
  wrong on the first live run (namespace mis-qualification bug, since fixed).

Both were caught by manual, one-off spot checks. DLL reflection generalizes this: instead of
nine hand-picked known-edge checks, every single type/member/signature the docs crawl claims
to exist can be checked against what the real compiled assembly says exists, automatically,
on every run.

## Reconciling with the existing non-goal

The top-level README's Non-goals section says live Revit access must never become the
*primary or required* source of truth — the **base pipeline**
(`crawl.py`/`parse.py`/`classify.py`) must keep working for anyone without Revit installed,
from docs alone. That's a statement about priority/dependency, not a blanket ban on ever
touching Revit-related tooling. DLL reflection is a separate, **optional, opt-in** stage
layered on top, for whoever has a local Revit installation and wants to validate a crawl's
output against it — this stage specifically stays limited to static reflection over
already-compiled assemblies sitting on disk (no `Application`/`Document`/UIless-mode launch),
which is the narrowest possible reading of "opt-in secondary evidence." A later,
explicitly-scoped stage that actually *runs* anything against a live document (RevitLookup
in a live Revit session, or a bespoke probe script) would go further and is a separate
decision, not something this document commits to. Reading RevitLookup's own **source code**
(Stage C below) is not that stage — it is static text analysis of a third public project, no
different in kind from parsing revitapidocs.com's HTML or reflecting over a compiled DLL, and
stays inside this same boundary.

## Architecture

```
Stage A (Windows, wherever Revit 2024 is installed)
  reflect_revit_api.ps1  --install-dir "C:\Program Files\Autodesk\Revit 2024"
                         --namespace-prefix Autodesk.Revit.DB
                         --out ground_truth_manifest_2024.json

Stage B (this repo, any machine, no Revit required)
  python -m revit_schema_mapper --version 2024 --cross-validate-dll ground_truth_manifest_2024.json
    -> ground_truth_report.json + a new summary.md section

Stage C (optional, this repo, any machine, no Revit required)
  python -m revit_schema_mapper.revitlookup --source-dir <checkout> --tag 2024.0.13
                                             --out revitlookup_reference_2024.json
    -> mines lookup-foundation/RevitLookup's own C# source (public, MIT-licensed) for
       descriptor coverage and guard-condition patterns

  python -m revit_schema_mapper --version 2024 --cross-validate-revitlookup revitlookup_reference_2024.json
    -> revitlookup_cross_validation_report.json + a new summary.md section, feeding two more
       EdgeCandidate fields (revitlookup_referenced/revitlookup_requires_document_context)
       alongside the dll_* ones from Stage B (see "Stage C" below)
```

Stage A produces a portable JSON file; Stage B never touches a Windows machine or a real DLL
directly. This mirrors the project's existing "bulk output lives outside git, small summaries
live in git" convention (README → "Where the crawl output lives") — the manifest and the
report are both candidates for the same treatment.

## Stage A: the reflection tool

**Language: PowerShell script** (`reflect_revit_api.ps1`, not yet written), for the same
reason the base pipeline falls back to stdlib-only Python when `requests`/`bs4` aren't
installed: zero extra install on any Windows box. Windows PowerShell 5.1 (`powershell.exe`,
distinct from PowerShell 7's `pwsh.exe`) hosts .NET Framework, which has
`[System.Reflection.Assembly]::ReflectionOnlyLoadFrom` built in — loads an assembly's
metadata only, without running any static initializer or requiring its native/unmanaged
dependencies to resolve, which matters since RevitAPI.dll is a managed wrapper over
unmanaged Revit internals that generally aren't loadable outside a running Revit process.
(If the session ends up on PowerShell 7 instead, the .NET Core equivalent is
`System.Reflection.MetadataLoadContext`, which is a separate NuGet package rather than
built-in — worth confirming which host is actually available before committing to one path.)

### 1. Finding the relevant assemblies out of 3151 DLLs

Most of the 3151 DLLs under `C:\Program Files\Autodesk\Revit 2024` are irrelevant (native
interop, third-party libraries, unrelated Autodesk components). Rather than hard-coding
`RevitAPI.dll`/`RevitAPIUI.dll` as *the* answer (those are the well-known ones, but guessing
is exactly the failure mode this whole project exists to avoid — see `crawl_notes.md`'s
repeated "confirmed empirically" pattern), the script should:

1. Enumerate every `*.dll` recursively under the install dir.
2. Reflection-only-load each one, in a try/catch (many will fail to load as metadata-only —
   that's expected and not an error worth surfacing loudly).
3. Keep only assemblies exposing at least one type whose namespace starts with
   `--namespace-prefix` (default `Autodesk.Revit.DB`, same flag name/default as the existing
   crawler for consistency).
4. Record which assemblies matched in the manifest's `assemblies_scanned` list (path, name,
   matched: true/false) — an explicit, checkable fact instead of an assumption baked into the
   script.

### 2. Cross-assembly type references and `ReflectionOnlyAssemblyResolve`

A type in one assembly can reference a type declared in another (e.g. a base type or a
parameter type living in a sibling DLL). Reflection-only loading does **not** auto-resolve
these the way normal loading does — the script needs a
`AppDomain.CurrentDomain.add_ReflectionOnlyAssemblyResolve` handler that redirects any
unresolved reference to the matching DLL already found under the install dir (by simple
name), falling back to a stub/unresolved marker rather than throwing if truly not found on
disk. This is the same category of problem `graph.py`'s external-stub-node handling already
solves on the docs side (`docs/edge_taxonomy_v0.md`, `TargetResolution.EXTERNAL`) — anything
unresolved should become an explicit "external, not further inspected" entry, not a crash and
not a silently dropped type.

### 3. Manifest schema (`ground_truth_manifest_<version>.json`)

Deliberately close to `models.NodeCandidate`/`MemberInfo` shape so Stage B's diffing logic
doesn't need a large remapping layer — but this is asserted fact from the compiler's own
metadata, not a confidence-scored candidate, so no `evidence`/`confidence` fields:

```json
{
  "revit_version": "2024",
  "generated_at": "2026-07-07T00:00:00Z",
  "namespace_prefix": "Autodesk.Revit.DB",
  "assemblies_scanned": [
    {"path": "C:\\Program Files\\Autodesk\\Revit 2024\\RevitAPI.dll",
     "name": "RevitAPI", "matched": true}
  ],
  "types": [
    {
      "full_type_name": "Autodesk.Revit.DB.Wall",
      "assembly": "RevitAPI",
      "kind": "class",
      "is_abstract": false,
      "base_type": "Autodesk.Revit.DB.HostObject",
      "inheritance_chain": ["Autodesk.Revit.DB.HostObject", "Autodesk.Revit.DB.Element", "..."],
      "implemented_interfaces": ["..."],
      "members": [
        {
          "name": "Symbol",
          "kind": "property",
          "declaring_type": "Autodesk.Revit.DB.FamilyInstance",
          "return_type": "Autodesk.Revit.DB.FamilySymbol",
          "parameters": [],
          "is_static": false
        }
      ],
      "enum_members": []
    }
  ]
}
```

`declaring_type` on each member (not assumed to equal the containing type — reflection's
`MemberInfo.DeclaringType` gives this directly and correctly for inherited members, which is
exactly the thing `parse_members_index_page`'s `declaring_type_hint` heuristic has to work
hard to reconstruct from HTML on the docs side per `crawl_notes.md`). This is one of the
concrete advantages of reflection over docs-scraping: no inheritance-attribution guessing.

## Stage B: the Python cross-validator

New module, `ground_truth.py`, following the existing module boundary convention (one
concern per file, wired together in `pipeline.py`):

- Loads a `ground_truth_manifest_<version>.json`.
- For every `NodeCandidate.full_type_name`: exact match, then short-name fallback (same
  two-pass resolution `graph.build_graph` already uses for `candidate_target_type` — reuse
  that logic rather than re-implementing it) against `manifest.types`. Result:
  `CONFIRMED` / `DOC_ONLY` (docs claim a type that isn't in the compiled API — stale docs
  or a deprecated/renamed type) / (separately) `DLL_ONLY` for manifest types with no
  matching `NodeCandidate` at all (an undocumented type, or a crawl coverage gap).
- For every `EdgeCandidate` (keyed by `(source_type, member_name)`): look up that member on
  the resolved type **or any type in its `inheritance_chain`** (same cross-declaring-type
  fallback `_build_known_edge_report` already does for the nine hand-picked known-edge
  checks — this generalizes that exact mechanism to every edge). Result:
  `SIGNATURE_CONFIRMED` (return type + parameter types match) / `SIGNATURE_MISMATCH`
  (member exists, signature differs) / `MEMBER_NOT_FOUND`.
- Writes `ground_truth_report.json` + a new `summary.md` section, in the same
  found/missing/reason style as the existing `target_report.json`/section 5 and
  `known_edge_report.json`/section 6 from the targeted-validation crawl — this is the same
  reporting pattern, just applied to the whole crawl instead of a fixed target list.

### A new, distinct confidence axis — not a replacement for the existing one

`docs/confidence_model_v0.md`'s seven `ConfidenceLabel` values describe how confidently
*docs alone* imply a relationship exists (return type, naming convention, prose). DLL
verification is orthogonal to that, the same way `needs_runtime_validation` is already
documented as "a distinct axis (verifiability) rather than a point further down the same
confidence ranking."

A single `dll_verified: Optional[bool]` collapses two genuinely different facts into one flag:
"does this member exist with a matching signature" and "is this the right relationship" (e.g.
an edge can be signature-verified yet still only exist because it's inherited from a base type
everything else also inherits it from — the exact `Wall`/`Floor`/`Door`-all-`HAS_PARAMETER`
fan-out problem). Revised proposal, keeping those visible separately:

- On `NodeCandidate`: `dll_type_verified: Optional[bool] = None` — `True` once the manifest
  confirms `full_type_name` exists (via the same exact/short-name resolution
  `graph.build_graph` already uses), `False` if it's `DOC_ONLY`, `None` until a
  cross-validation pass runs.
- On `EdgeCandidate`, three orthogonal fields instead of one:
  - `dll_signature_verified: Optional[bool]` — the member exists (on the resolved type or an
    ancestor in its `inheritance_chain`) with a normalized signature match (return type +
    parameter types). `ground_truth_report.json` also records *which* kind of `False` it was
    (`SIGNATURE_MISMATCH` vs `MEMBER_NOT_FOUND`) per edge — collapsing those two into one bool
    would hide a real distinction.
  - `dll_relationship_scope: Optional[str]` — `"declared"` if the manifest's `declaring_type`
    for that member equals the edge's own `source_type`, `"inherited"` if it only matched via a
    different entry in `source_type`'s `inheritance_chain`. An edge with `relationship_scope:
    inherited` is the machine-checkable signal for "this relationship probably belongs on the
    base type, not repeated on every subclass" — the same ontology cleanup called out in the
    other review, now a field instead of a manual observation.
  - `dll_semantic_verified: Optional[bool]` — reserved, **not set by anything in this design**.
    `signature_verified=True` only proves the member exists and returns the claimed
    type/shape (e.g. `ICollection<ElementId>`); it does not prove those ids resolve to the
    claimed target type in a real document — that needs a later runtime-verification stage,
    which crosses this project's Non-goal on ever requiring a running Revit process (see
    below) and is deliberately out of scope here. The field exists now so that axis is visible
    in the data model even before anything populates it, rather than silently folding
    "signature-true" and "semantically-true" into the same flag once that stage does exist.
- `dll_verified_status: Optional[str]` on both — a convenience rollup `ground_truth.py`
  computes from the fields above for `summary.md`/spot-checking, e.g. `not_found`,
  `signature_mismatch`, `signature_verified_declared`, `signature_verified_inherited` — always
  derived, never hand-set.
- `revitlookup_referenced: Optional[bool]` and `revitlookup_requires_document_context:
  Optional[bool]` on `EdgeCandidate` — populated by Stage C, not Stage B; see below.

**Does this require changes to `crawl.py`?** No. None of the fields above are ever touched by
`crawl.py`/`parse.py`/`classify.py` — they are purely additive, defaulted (`None`) fields on
`NodeCandidate`/`EdgeCandidate` in `models.py`, appended after the existing fields. Every
existing `classify.py` construction call site already builds these objects by keyword, so
adding trailing defaulted fields doesn't require touching a single one of those call sites —
they simply never pass the new kwargs, and the dataclass default (`None`) applies. The only
code that ever *writes* to them is the new `ground_truth.py`, run as an explicit separate pass
(`--cross-validate-dll`) after a crawl already exists — cross-validation is layered on top of
the crawl, same as the Stage A/Stage B split above, not mixed into it.

### Normalization is the hard part, not the lookup

The lookup logic above is straightforward; matching signature *strings* is not. Two sources
of false mismatches to expect, both because docs-scraped and reflection-derived signature
text will never be byte-identical even when they describe the same real member:

1. **Generic syntax.** Sandcastle docs render generics as `ICollection(ElementId)`;
   .NET reflection's `Type.ToString()`/`MemberInfo` gives `ICollection\`1[ElementId]` or
   similar CLR-native form. `crawl_notes.md` already hit an adjacent problem — an overloaded
   method's *title* has parenthesized parameter lists that needed careful paren-depth
   parsing (`_strip_trailing_overload_signature`) rather than a naive regex. Signature
   comparison here needs its own normalization function on both sides (docs-form and
   reflection-form) into one canonical shape before comparing — not a string equality check.
2. **Namespace qualification.** `graph.py`'s docstring already documents a real, confirmed
   case of edges/nodes disagreeing on how fully-qualified a type name is
   (`Autodesk.Revit.DB.Room` vs `Autodesk.Revit.DB.Architecture.Room`). Reflection gives the
   one unambiguous fully-qualified name; the existing short-name fallback resolution is the
   right tool to bridge to it, reused rather than re-derived for this new comparison.

Get the normalization function reviewed/tested against a handful of real signatures *before*
building the full diff report on top of it — a wrong normalizer would silently manufacture
`SIGNATURE_MISMATCH` noise across the whole report, the exact opposite of what this stage is
for.

## Stage C: mining RevitLookup's descriptor *source* as a third static evidence layer

The earlier review of this design filed RevitLookup under "runtime tooling," on the same side
of the non-goal boundary as actually opening Revit. That conflates two different things:

- **Running RevitLookup inside Revit against a live document** — a genuine runtime source, out
  of scope here, same as any other runtime-verification stage.
- **Reading RevitLookup's own C# source from its public repo** — a static text-parsing
  exercise, no different in kind from parsing revitapidocs.com's HTML (Stage 1) or reflecting
  over a compiled DLL (Stage A). This is confirmed reachable
  ([`lookup-foundation/RevitLookup`](https://github.com/lookup-foundation/RevitLookup), fetched
  directly, MIT-licensed) and sits entirely inside the docs-first, no-live-Revit boundary —
  it never runs Revit, RevitLookup, or `RevitAPI.dll`.

**Version pinning is not optional here, and the first real check caught a live mistake.**
RevitLookup tags releases per Revit year (`<year>.<major>.<minor>`, e.g. `2024.0.13`), and its
`develop` branch tracks whatever the *next* Revit version is (2027, as of this writing) —
mining `develop` describes a later Revit version's API surface, not 2024's, the version this
project's `ground_truth_manifest_2024.json` was actually reflected from. Confirmed directly:
fetching `develop`'s current `ViewDescriptor.cs`/`CompoundStructureDescriptor.cs` (the earlier
review's own two named examples) showed a `Configure(IMemberConfigurator configuration)` /
`.Member()`/`.Extension()` fluent API — but **neither file exists at all** at the actual
`2024.0.13` tag, which instead has the `Resolve(Document, string, ParameterInfo[])`/
`RegisterExtensions(IExtensionManager)` shape described below. Mining `develop` would have
silently produced a reference file describing RevitLookup's *current* Revit-version support,
not Revit 2024's — always mine the tag matching the target Revit version, record it
(`revitlookup_tag` below) verbatim, and re-sync deliberately, never silently re-point at
`develop` or "whatever's newest." See `crawl_notes.md` for the full real-version-mismatch
finding.

**Update (2026-07-10): the parser now also handles real drift confirmed at 2025.x/2026.x
tags**, layered on top of the `2024.0.13` shape described below, never replacing it --
`revitlookup.py`'s own module docstring has the specifics (renamed/relocated
`DescriptorsMap.cs`, `Resolve()` dropping its `Document` parameter, bare method-group switch
arms, the `RevitApi.*` → `Context.*` rename, the `.AppendVariant(...)` → `Variants.Values<T>`/
`new Variants<T>` builder rename, and the `manager.Register(nameof(X), ...)` extension-naming
shape) and `crawl_notes.md`'s "Stage C coverage audit" entry has the full confirmed-against-
real-source analysis. `2024.0.13` remains solid and unaffected.

At `2024.0.13`, `DescriptorMap.cs`'s (singular "Descriptor", confirmed real file name at this
tag — `source/RevitLookup/Core/ComponentModel/DescriptorMap.cs`) `FindDescriptor` switch is a
curated list of 60 real cases in total (confirmed by direct count), 45 of them under the
`Root`/`APIObjects`/`IDisposables`/`Enumerator` section headers that correspond to real
`Autodesk.Revit.DB` API objects — the rest are plain BCL/UI-framework types (`System`/`Internal`/
`Media`/`ComponentManager` sections) also worth a hand-written descriptor but not part of the
Revit DB object model itself — mapping a type to a hand-written descriptor class, each
implementing `IDescriptorResolver`/`IDescriptorExtension` (confirmed directly from real
descriptor files: `ElementDescriptor.cs`, `HostObjectDescriptor.cs`,
`FamilyManagerDescriptor.cs`, all under
`source/RevitLookup/Core/ComponentModel/Descriptors/`). Within a descriptor, static parsing
extracts three signals, none requiring Revit to run — implemented in
`src/revit_schema_mapper/revitlookup.py`, tested against these exact real files in
`tests/fixtures/revitlookup/`:

1. **Positive corroboration.** Every `nameof(Type.Member) => ...` (or bare string-literal, e.g.
   `"BoundingBox" =>`, likely a human-readable label rather than the exact real member name —
   tracked separately via a `name_source` field, `"nameof"` vs. `"string_literal"`) case inside a
   `Resolve(Document context, string target, ParameterInfo[] parameters)` method names a member
   RevitLookup's authors specifically wrote custom resolution logic for, as opposed to letting
   it fall through to generic reflection display. Absence proves nothing (RevitLookup doesn't
   special-case everything) — this is a positive-only signal, never used to argue an edge is
   wrong.
2. **Guard-condition / cardinality mining, for free.** Real resolver bodies (`ElementDescriptor`'s
   `GetMaterialArea`/`GetMaterialVolume`, `FamilyManagerDescriptor`'s
   `GetAssociatedFamilyParameter`) build multiple results via `.AppendVariant(...)` — cardinality
   is per-item, not a single value, confirmed directly rather than via the design's original
   `CompoundStructureDescriptor`/`VariantsResolver.ResolveIndex` example (which doesn't exist at
   this tag). Detecting `.AppendVariant(` textually is the cheap proxy. **Real subtlety found
   while confirming this**: a case's *inline* expression is often just a bare call to a
   separately-defined local function (e.g. `nameof(Element.GetMaterialArea) =>
   ResolveGetMaterialArea(),`), with the actual `.AppendVariant`/document-context logic living in
   that named local function later in the same method body, not inline in the case itself — the
   parser follows that indirection (`_find_local_function_body`) rather than only inspecting the
   inline case text, which would otherwise silently miss the real signal.
3. **Document-context detection.** The confirmed real accessors in this version's code are
   `RevitApi.ActiveView`/`RevitApi.Document` (static/global accessors — the `Resolve()` method's
   own `context` parameter is declared but often unused in favor of these), plus `.Document`/
   `FilteredWorksetCollector`/`Schema.ListSchemas` — a cheap textual proxy for "this edge is real,
   but incomplete without a live document," the same signal `needs_runtime_validation` describes.
4. **Synthetic-member exclusion.** `RegisterExtensions(IExtensionManager manager)` registers names
   (via `extension.Name = nameof(...)` or a literal string) that don't exist on the real type at
   all — confirmed real example: `HostObjectDescriptor`'s extensions (`GetBottomFaces`/
   `GetTopFaces`/`GetSideFaces`) are all named via `nameof(HostExtensions.X)`, where
   `HostExtensions` is a *separate* extension-method holder class, not `HostObject` itself. These
   must stay excluded from anything compared against a DLL manifest — Stage B would otherwise see
   one as a "member," fail to find it (never in the compiled assembly), and misreport
   `MEMBER_NOT_FOUND` for what's actually just a UI convenience, not a crawl gap.

`revitlookup_reference.json` shape (`dataclasses.asdict` of `RevitLookupReference` —
`src/revit_schema_mapper/revitlookup.py`), entirely derived by parsing RevitLookup's C# source
text, no Revit or `RevitAPI.dll` involved in producing it:

```json
{
  "revitlookup_tag": "2024.0.13",
  "descriptor_map": [
    {"target_type_short_name": "Element", "descriptor_class": "ElementDescriptor", "section": "IDisposables"}
  ],
  "descriptors": [
    {
      "descriptor_class": "ElementDescriptor",
      "resolved_members": [
        {"member_name": "CanBeHidden", "name_source": "nameof", "requires_document_context": true, "has_multiple_variants": false},
        {"member_name": "GetMaterialArea", "name_source": "nameof", "requires_document_context": false, "has_multiple_variants": true}
      ],
      "synthetic_extensions": ["CanBeMirrored", "GetJoinedElements"],
      "parser_notes": []
    }
  ]
}
```

`descriptor_map`'s `section` field is the file's own `//SectionName` comment header
(`System`/`Root`/`Enumerator`/`APIObjects`/`IDisposables`/`Internal`/`Media`/`ComponentManager`,
confirmed real section names at this tag) — every switch case is recorded, not just the ones
that look like real `Autodesk.Revit.DB` types; filtering to "real API types only" (e.g.
excluding `System`/`Internal`/`Media`/`ComponentManager`) is left to whoever consumes this file,
since that judgment call could shift release to release and shouldn't be silently baked into
the parser itself. `parser_notes` is populated (rather than silently leaving `resolved_members`
empty) when a file references `IDescriptorResolver`/`IDescriptorExtension` but this parser
couldn't find/parse the expected method shape — the same "explicit, checkable fact instead of a
silent assumption" this design's earlier open question called for.

Mining itself is still only reachable via the standalone
`python -m revit_schema_mapper.revitlookup --source-dir <checkout> --tag <tag> --out <path>`
entry point (mirrors `reflect_revit_api.ps1`'s own "operate on a local directory" shape) — not
wired into `python -m revit_schema_mapper`'s own argument parser, since it needs a local
RevitLookup checkout at a pinned tag, the same reason Stage A's own reflection script stays a
separate step rather than something the main pipeline invokes itself.

**Now built**: combining `revitlookup_reference.json` with `candidate_edges.json` into the
`revitlookup_referenced`/`revitlookup_requires_document_context` `EdgeCandidate` fields this
section originally only proposed — `ground_truth.cross_validate_revitlookup` (mutates those two
fields in place, the same pattern Stage B's `cross_validate_dll` already uses for its own
`dll_*` fields), wired into `__main__.py` as `--cross-validate-revitlookup REFERENCE_PATH`,
writing `revitlookup_cross_validation_report.json` plus a refreshed summary section. Matching is
by **short type name only** — `DescriptorMap.cs`'s own `target_type_short_name` is never
namespace-qualified in RevitLookup's own source, unlike Stage B's manifest (which carries a real
`full_type_name` and only falls back to short-name matching when it's unambiguous) — a known,
documented limitation of the source data itself, not something the cross-validation pass can
resolve on its own. `revitlookup_referenced` is deliberately never set to `False`: a member with
no corroborating case in RevitLookup's source is exactly as unproven as one that was never
checked, and setting `False` would risk a downstream consumer misreading absence as evidence
against the edge. Can run before, after, or without `--cross-validate-dll` — the two never touch
each other's fields, and neither mutates any node-level field (Stage C only ever adds edge-level
corroboration, since RevitLookup's descriptor coverage says nothing new about a *type*'s own
existence that `DescriptorMap.cs`'s own type list wouldn't already say via `descriptor_map`).

## Workflow once built

1. On a Windows machine with Revit 2024 installed: run
   `reflect_revit_api.ps1 -InstallDir "C:\Program Files\Autodesk\Revit 2024" -Out ground_truth_manifest_2024.json`.
2. Move/publish that JSON alongside that version's other bulk crawl output (same Release-asset
   convention as `outputs/revit_<version>/*.json`, per README → "Where the crawl output
   lives").
3. Run `python -m revit_schema_mapper --version 2024 --cross-validate-dll ground_truth_manifest_2024.json`
   against an existing crawl's output dir (`pipeline.run_cross_validate_dll`, wired into
   `__main__.py`) — this reads that dir's `node_type_candidates.json`/`candidate_edges.json`,
   writes `ground_truth_report.json`, updates both candidate files in place with each
   candidate's `dll_*` fields, and refreshes a `summary.md`/`validation_summary.md` section.
4. Read the new `summary.md` section — same "distinct sections, a low number in one doesn't
   imply a problem in the others" principle the targeted-validation crawl summary already
   follows for crawler/parser/classifier.
5. (Optional, Stage C, independent of steps 1-4): on any machine, clone
   `lookup-foundation/RevitLookup` and check out the tag matching the target Revit version
   (e.g. `git checkout 2024.0.13`), then run
   `python -m revit_schema_mapper.revitlookup --source-dir <checkout> --tag 2024.0.13 --out revitlookup_reference_2024.json`.
6. Run `python -m revit_schema_mapper --version 2024 --cross-validate-revitlookup revitlookup_reference_2024.json`
   against the same crawl's output dir (`pipeline.run_cross_validate_revitlookup`, wired into
   `__main__.py`) — reads `candidate_edges.json`, writes
   `revitlookup_cross_validation_report.json`, updates the candidate file in place with each
   edge's `revitlookup_*` fields, and refreshes a `summary.md`/`validation_summary.md` section.
   Can run before, after, or without steps 1-4.

## Open questions / risks to resolve before implementing

- **Windows PowerShell 5.1 vs PowerShell 7 availability** on whatever machine actually runs
  Stage A — determines whether `ReflectionOnlyLoadFrom` (built in) or `MetadataLoadContext`
  (separate package) is the real starting point. Don't assume; check on the actual machine
  first, the same way every other real-run finding in `crawl_notes.md` was confirmed
  empirically rather than guessed. **Partially resolved, from the wrong side**: the dev
  sandbox that wrote `reflect_revit_api.ps1` turned out to have no Windows/Revit access at
  all (see `crawl_notes.md` → "Stage A ... first real run"), so both branches are implemented
  and the PS7/`MetadataLoadContext` branch is confirmed working end-to-end against real (non-
  Revit) DLLs, but the PS 5.1/`ReflectionOnlyLoadFrom` branch — the one an actual Windows+Revit
  box will most likely use — has never been executed at all. That remains the real open item.
- **Assembly count/time budget.** Reflection-only-loading and filtering 3151 DLLs to find the
  handful that matter could be slow; may want a `-KnownAssemblyHints RevitAPI.dll,RevitAPIUI.dll`
  fast-path that's checked first, with the full recursive scan as a fallback/completeness
  check rather than the only path — but only after confirming the fast path is actually
  correct and complete, not assumed. A 536-DLL non-Revit scan (`crawl_notes.md`) completed in
  well under a second, suggesting the full ~3151-DLL Revit scan is unlikely to need this, but
  that's still an inference from a smaller, non-Revit substitute, not a confirmed timing.
- **Signature normalization correctness** (see above) is the single biggest risk to the
  report being trustworthy at all. Confirmed correct against real reflection strings (both
  `Type.ToString()` and `Type.FullName` forms) for the single-type-argument generic case;
  confirmed to still mishandle multi-type-argument generics exactly as its own docstring
  already disclosed — see `crawl_notes.md` for both confirmations. No Revit signature has ever
  been found that needs the multi-arg case fixed, so it hasn't been touched.
- **MetadataLoadContext's cross-framework requirement, newly confirmed.** Revit's DLLs target
  .NET Framework; a PowerShell 7 host runs .NET/.NET Core. `MetadataLoadContext` needs
  reference assemblies matching the *target* framework (`mscorlib` etc.), not just the host
  runtime's own — `reflect_revit_api.ps1`'s `-NetFrameworkReferenceAssembliesDir` parameter
  exists for this, but the combination is implemented/reasoned-through, not yet run against a
  real net48 assembly. See `crawl_notes.md`.
- **Multiple Revit versions.** This design is per-version (`ground_truth_manifest_2024.json`,
  `..._2025.json`, etc.), matching the existing per-version `outputs/revit_<version>/`
  layout — no cross-version logic is in scope here.
- **Stage C's C#-parsing surface.** `Resolve()` methods use plain pattern-matching `switch`
  expressions in the confirmed files, but Stage C's parser needs to be honest about what it
  can't confidently extract (e.g. a differently-shaped descriptor, or a future RevitLookup
  refactor) rather than silently under-reporting `resolved_members` — same "explicit, checkable
  fact instead of a silent assumption" principle as the rest of this design. A `descriptors`
  entry with zero `resolved_members` should be distinguishable in the output from "genuinely no
  special-cased members" vs. "the parser didn't recognize this file's shape."

**Now that Stages B and C both exist independently**, a further, still entirely open question is
how to actually *combine* their two sets of fields (plus the base `edge_confidence`) into a
single richer signal, rather than leaving them as parallel, uncorrelated annotations forever —
see `docs/multi_source_corroboration_v0.md` for that design record (source asymmetry, version/
provenance granularity, pipeline-ordering staleness risk, downstream-consumer shape, and whether
docs-first is structural or just where the pipeline happened to start).

## Related project: Fingerprint, and a longer-horizon vision

A prior review pass surfaced claims about a separate `Fingerprint` project (not in this
workspace) that keeps a cached, pinned snapshot of RevitLookup's descriptor files as
write-extractor reference material (`REVIT_LOOKUP_DOMAIN_MAP.md`, a `sync_revitlookup_reference.py`
script, per-type `*Descriptor.cs` copies). Three of those files were shared directly and
confirmed genuine, unmodified RevitLookup source (not fabricated by the earlier conversation)
— they informed Stage C above. That snapshot is otherwise unrelated to this repo and three
months stale as of this writing; nothing here depends on `Fingerprint` existing or being
reachable, since Stage C mines RevitLookup's own public repo directly rather than through it.

**Longer-horizon vision, not committed scope**: once this project has a DLL-reflection-verified
ground-truth graph (Stages A/B) and the RevitLookup-source corroboration signals (Stage C),
that combined output could become an upstream input for `Fingerprint`'s own extractor-writing
process — replacing ad hoc consultation of a manually-pinned RevitLookup snapshot with a
systematically verified schema, and potentially reducing how much `Fingerprint` (or other
tools) need to consult RevitLookup directly at all. That's a real direction worth keeping in
mind while designing the fields above, but it's explicitly **not** scoped into this
document — it would need its own design pass once `Fingerprint` is actually reachable from
this workspace.

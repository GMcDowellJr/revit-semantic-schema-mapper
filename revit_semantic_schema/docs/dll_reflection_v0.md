# DLL reflection v0 (design)

**Status: design only, nothing implemented yet.** This documents the next major step for
the project: cross-validating the docs-derived *candidate* schema (`node_type_candidates.json`
/ `candidate_edges.json`) against **ground truth** read directly from the compiled
`Autodesk.Revit.DB` assemblies via .NET reflection, instead of trusting revitapidocs.com's
HTML alone.

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
explicitly-scoped runtime-verification stage (see "Related project" below) would go further
and is a separate decision, not something this document commits to.

## Two-stage architecture

```
Stage A (Windows, wherever Revit 2024 is installed)
  reflect_revit_api.ps1  --install-dir "C:\Program Files\Autodesk\Revit 2024"
                         --namespace-prefix Autodesk.Revit.DB
                         --out ground_truth_manifest_2024.json

Stage B (this repo, any machine, no Revit required)
  python -m revit_schema_mapper --version 2024 --cross-validate-dll ground_truth_manifest_2024.json
    -> ground_truth_report.json + a new summary.md section
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

## Workflow once built

1. On a Windows machine with Revit 2024 installed: run
   `reflect_revit_api.ps1 -InstallDir "C:\Program Files\Autodesk\Revit 2024" -Out ground_truth_manifest_2024.json`.
2. Move/publish that JSON alongside that version's other bulk crawl output (same Release-asset
   convention as `outputs/revit_<version>/*.json`, per README → "Where the crawl output
   lives").
3. Run `python -m revit_schema_mapper --version 2024 --cross-validate-dll ground_truth_manifest_2024.json`
   (new CLI flag, not yet added to `__main__.py`) against an existing crawl's output dir.
4. Read the new `summary.md` section — same "distinct sections, a low number in one doesn't
   imply a problem in the others" principle the targeted-validation crawl summary already
   follows for crawler/parser/classifier.

## Open questions / risks to resolve before implementing

- **Windows PowerShell 5.1 vs PowerShell 7 availability** on whatever machine actually runs
  Stage A — determines whether `ReflectionOnlyLoadFrom` (built in) or `MetadataLoadContext`
  (separate package) is the real starting point. Don't assume; check on the actual machine
  first, the same way every other real-run finding in `crawl_notes.md` was confirmed
  empirically rather than guessed.
- **Assembly count/time budget.** Reflection-only-loading and filtering 3151 DLLs to find the
  handful that matter could be slow; may want a `-KnownAssemblyHints RevitAPI.dll,RevitAPIUI.dll`
  fast-path that's checked first, with the full recursive scan as a fallback/completeness
  check rather than the only path — but only after confirming the fast path is actually
  correct and complete, not assumed.
- **Signature normalization correctness** (see above) is the single biggest risk to the
  report being trustworthy at all.
- **Multiple Revit versions.** This design is per-version (`ground_truth_manifest_2024.json`,
  `..._2025.json`, etc.), matching the existing per-version `outputs/revit_<version>/`
  layout — no cross-version logic is in scope here.

## Related project: RevitLookup, and a longer-horizon vision

[`lookup-foundation/RevitLookup`](https://github.com/lookup-foundation/RevitLookup) is a real,
separate open-source Revit add-in for interactively inspecting live API objects inside a
running Revit session — confirmed reachable and genuine (fetched directly: C#, MIT-licensed,
`source/RevitLookup/Core/Decomposition/Descriptors/...`). A prior review pass surfaced claims
about a separate `Fingerprint` project (not in this workspace) that keeps a cached, pinned
snapshot of RevitLookup's descriptor files as write-extractor reference material
(`REVIT_LOOKUP_DOMAIN_MAP.md`, `DescriptorsMap.cs`, per-type `*Descriptor.cs` files like
`ViewDescriptor`/`CompoundStructureDescriptor`). Three of those files have since been shared
directly and are genuine, unmodified RevitLookup source (not fabricated by the earlier
conversation) — but they're a three-month-old copy in a repo this one has no connection to, so
treat any specific claim about current RevitLookup internals as unverified *here* until that
repo is actually in scope. What they do confirm, concretely:

- `DescriptorsMap.cs` is exactly the runtime-type dispatch table described earlier — a single
  `switch` from a live CLR object's type to a `*Descriptor` class, covering the great majority
  of `Autodesk.Revit.DB`'s concrete types (`Wall`, `View`, `CompoundStructure`,
  `FamilyInstance`, `Workset`, ~80 more).
- `ViewDescriptor`/`CompoundStructureDescriptor` show the "guard conditions" claim was real
  and specific: `CompoundStructureDescriptor.Resolve` doesn't call `GetMaterialId`/
  `GetLayerFunction`/etc. blindly, it resolves them per-layer-index via
  `VariantsResolver.ResolveIndex(compoundStructure.LayerCount, ...)`; `ViewDescriptor` needs
  live `Document` context to resolve filters/worksets/categories (`view.Document.Settings...`,
  `new FilteredWorksetCollector(view.Document)...`) — i.e. exactly the "project state affects
  results" problem from the confidence-model discussion, encoded as working code rather than
  prose.

**Longer-horizon vision, not committed scope**: once this project has a DLL-reflection-verified
ground-truth graph (this design) and, eventually, a scoped runtime-verification layer, that
verified graph could become an upstream input for `Fingerprint`'s own extractor-writing
process — replacing ad hoc consultation of a pinned RevitLookup snapshot with a systematically
verified schema, and potentially reducing how much `Fingerprint` (or other tools) need
RevitLookup at all. That's a real direction worth keeping in mind while designing the
`dll_semantic_verified`/`dll_verified_status` fields above, but it's explicitly **not** scoped
into this document — it would need its own design pass once `Fingerprint` is actually
reachable from this workspace.

# Multi-source evidence corroboration v0 (design)

**Status: design only, nothing implemented yet.** Stages B (`ground_truth.cross_validate_dll`)
and C (`ground_truth.cross_validate_revitlookup`) both exist and both mutate `EdgeCandidate` in
place, independently (`docs/dll_reflection_v0.md`) — but nothing yet *combines* their two sets
of fields, or the base docs-derived `edge_confidence`, into a single richer signal. This
document records the open design questions raised while thinking through how that combination
should work, before any of it is built — same posture `dll_reflection_v0.md` had before Stages
A/B/C existed.

## Current state, confirmed against the actual code

- `--cross-validate-dll` and `--cross-validate-revitlookup` are two separate, opt-in CLI passes.
  Both read/write `candidate_edges.json`; both mutate the same `EdgeCandidate` objects, on
  disjoint field prefixes (`dll_*` vs. `revitlookup_*`); neither depends on or overwrites the
  other's fields. They can run in either order, or either alone, or neither, with an identical
  end state either way (`pipeline.run_cross_validate_dll` / `run_cross_validate_revitlookup`).
- Neither Stage B nor Stage C ever generates a *new* candidate. Only the base pipeline
  (`crawl.py` → `parse.py` → `classify.py`) produces `EdgeCandidate`/`NodeCandidate` objects at
  all — Stage B/C only annotate a candidate that already exists. See "Is docs-first structural
  or incidental?" below for why that's true today but isn't an inherent property of the sources
  themselves.
- `graph.confidence_tier` (the four-bucket collapse `graph.json`/`graph_core.json` expose) is
  computed purely from the docs-only `edge_confidence` label. Nothing about `dll_*`/
  `revitlookup_*` feeds into it.

## Open design questions

### 1. Source asymmetry: positive-only vs. positive-or-negative evidence

The three sources are not symmetric, and a combined signal can't treat them as if they were:

- **DLL (Stage B)** can actively *contradict* a docs claim — `MEMBER_NOT_FOUND` /
  `SIGNATURE_MISMATCH` are real negative evidence that the docs-derived edge is wrong.
- **RevitLookup (Stage C)** is deliberately positive-only — `EdgeCandidate.revitlookup_referenced`
  is never set to `False` (see that field's docstring in `models.py`), because RevitLookup not
  special-casing a member proves nothing about it.
- **Docs** is the source of the claim itself, not something that "corroborates" its own claim.

A naive "count how many of 3 sources agree" scalar would conflate a DLL contradiction with a
RevitLookup non-mention, which are very different things. Any combined axis needs per-source
status (`confirmed` / `contradicted` / `no_data`), not a single number — see also #4/#5 below,
which both assume this shape rather than a scalar.

### 2. Ceiling: none of the three sources verify semantic correctness

`dll_semantic_verified` is reserved and never set for a reason: a DLL signature match proves a
member *exists* with the claimed shape, not that `classify.py`'s guess at *which relationship it
represents* (`candidate_edge_type`) is correct. RevitLookup corroboration has the same ceiling —
it proves a human found the member worth resolution logic, not that this project's specific
edge-type label for it is right. Even a triple-corroborated edge could have the wrong
`candidate_edge_type`. Keep this explicit wherever a combined signal is surfaced, so "3/3
corroborated" doesn't read as "verified true relationship" when it only means "verified this
member exists."

Also worth flagging for anyone picking this up later: "semantic" already means two unrelated
things in this codebase — `semantic_roles.py`'s domain-role classification (View/Family/Room)
and whatever "semantic web / ontology" turns out to mean if that work ever gets scoped (see #7).
Disambiguate explicitly before writing anything that uses the word.

### 3. Version/provenance granularity beyond the Revit-year label

Confirmed by reading the actual schemas, not assumed:

- `GroundTruthManifest.assemblies_scanned` (Stage A/B) only records `path`/`name`/`matched` —
  no assembly file version or build number
  (`tests/fixtures/ground_truth_manifest_2024.json`). So a manifest labeled `"revit_version":
  "2024"` can't currently distinguish "reflected against Revit 2024's initial release" from
  "reflected against Revit 2024 Update 3."
- `RevitLookupReference` (Stage C) has `revitlookup_tag` but **no mining timestamp at all** —
  unlike `GroundTruthManifest`, which has `generated_at`.
- `crawl.py` captures a per-page `fetched_at` timestamp in the HTML cache's `.meta.json`
  sidecar, but it's discarded before export — `ApiPage`/`EdgeCandidate`/`NodeCandidate` carry
  `source_url` but no fetch timestamp.

Three independent, currently-unreconciled version identifiers exist: the docs site's year-folder
(coarsest — revitapidocs.com doesn't appear to expose anything finer), whatever exact
`RevitAPI.dll` build a manifest was reflected from (unrecorded today, though
`reflect_revit_api.ps1` could capture `FileVersionInfo` if this becomes worth doing), and
RevitLookup's own `<year>.<major>.<minor>` tag scheme (tracks their tool's own compatibility
updates, not necessarily 1:1 with a Revit build number). Reconciling these — or at least
recording all three per candidate — is a prerequisite for any provenance claim stronger than
"as of some point in this Revit year."

### 4. Pipeline ordering / staleness risk

`graph.json`/`graph_core.json` are only rebuilt by a full run or `--graph-only`. Both
cross-validation passes mutate `candidate_edges.json` in place but never trigger a graph
rebuild. So today: crawl → build graph → run `--cross-validate-dll` → run
`--cross-validate-revitlookup` leaves `graph.json` silently stale relative to
`candidate_edges.json`, with nothing that warns about it. This is already slightly misleading
(the `dll_*`/`revitlookup_*` fields exist on the candidate file but not on the exported graph
edges at all yet), and becomes a real correctness bug once a corroboration axis is meant to live
on `GraphEdge` — at that point "did you re-run `--graph-only` after both cross-validation passes"
becomes load-bearing, not just cosmetic.

### 5. `confidence_tier` / core-subgraph interaction with corroboration

`graph_core.json`'s definition (`confidence_tier == core`) is purely a docs-confidence collapse
today. Open question: should an edge with weak docs confidence but DLL+RevitLookup agreement get
promoted into the core subgraph? If so, `community.py`'s community detection (which only runs
over the core subgraph) and the semantic-role Sankey/heatmap map would both shift based on
corroboration, not just docs confidence — a real behavior change that should be decided
deliberately. This is the same underlying decision as #7's axiom-promotion gate, just applied to
"core subgraph membership" instead of "asserted ontology axiom" — worth solving once, generically,
rather than twice.

### 6. Downstream consumer shape: RDF needs reification, Neo4j/networkx don't

`README.md` names Neo4j, RDF, and `networkx` as illustrative downstream consumers of
`GraphNode.id`/`GraphEdge.source`/`target` as a plain join key — none are implemented in this
repo today. For two of the three, a new corroboration axis costs nothing: Neo4j and `networkx`
are property-graph models where arbitrary node/edge attributes are native.

RDF is different and worth designing for deliberately if it's ever built: RDF's native unit is a
triple, with no room for annotations. A `GraphEdge` here isn't "X hasParameter Y is true," it's
"X hasParameter Y is a *candidate*, evidenced by these sources at these confidence levels" —
that needs either classic reification (mint a resource per edge, assert the real triple, hang
`confidence_tier`/`dll_*`/`revitlookup_*`/corroboration fields off that resource as annotation
triples) or RDF-star (`<<X hasParameter Y>> confidenceTier "core"`). `GraphEdge` is already
structurally close to "the reified statement" — an exporter would mint one resource per edge and
attach each evidence field as its own annotation triple, not try to cram multiple sources' worth
of metadata into one plain triple.

### 7. Relationship to a possible future ontology/semantic layer

Not yet scoped, and may not be needed — this document deliberately doesn't commit to it. Worth
recording two things while the rest of this design is fresh:

- `class_role`, `EdgeType` (`docs/edge_taxonomy_v0.md`), and `semantic_roles.classify_api_role`
  already function as three independent, informal, un-formalized ontology-like vocabularies (a
  node class taxonomy, a predicate list, and a coarser domain-role scheme) layered over the same
  graph — the same "keep axes separate, don't collapse" principle this whole document argues for
  elsewhere, already present in the code without ever being named that way.
- If ontology/semantic-web work is ever pursued, the natural role of multi-source corroboration
  is as an axiom-promotion gate: a candidate with enough independent agreement is confident
  enough to commit as an asserted axiom (OWL/RDFS); one with only docs support stays a
  lower-trust, provisional annotation. Ontology *alignment* (mapping this project's ad hoc
  vocabulary onto an external ontology, if one exists for this domain) would use the same
  reification/annotation pattern as #6 — an alignment confidence score belongs on the mapping
  resource, not stapled onto the base fact.

The actionable takeaway today is cheap and doesn't require committing to any of the above: keep
every evidence axis separate and inspectable, never lossy-collapsed. That's useful regardless of
whether ontology work ever happens, and costs nothing if it doesn't.

### 8. Is docs-first structural, or just where the pipeline happened to start?

Checked directly against `classify.py` rather than assumed:

- `classify_member`'s `candidate_edge_type` and most of `edge_confidence` are derived entirely
  from `member.name` (matched against a keyword regex), `member.return_type`, and
  `member.parameters` — all fields `ManifestMember` (Stage A's reflection output) already
  carries in full. `member.summary`/`member.remarks` (actual docs prose) are consulted in
  exactly one place, and only ever *upgrade* confidence to `DOCS_SEMANTIC_HINT` when the
  structural signal alone was weak (`classify.py:283, 332-335`) — prose never determines
  `edge_type` itself.
- `classify_class_role` never touches docs prose at all — purely `kind`/name-suffix/inheritance
  chain/member-kind-mix based.

So a reflection manifest is structurally rich enough that an equivalent classifier could run
directly against `ManifestType`/`ManifestMember` and reproduce nearly the same candidate graph.
The one thing it structurally cannot ever produce is `DOCS_SEMANTIC_HINT`-style evidence, since
compiled IL carries no human-authored explanation text. Docs also contributes `source_url` — a
link a human can actually go read — which reflection has no equivalent of, independent of
classification accuracy.

**Why docs is first in the implemented pipeline anyway, recorded accurately rather than
rationalized after the fact**: the dev environment that originally built this had no
Windows/Revit access at all (`docs/crawl_notes.md` — Stage A's own first real run), so the base
pipeline was necessarily built docs-first as a practical convenience given that constraint, not
because of a considered judgment that docs is more authoritative or "more correct" than DLL
reflection or RevitLookup. The README's non-goal (a Windows+Revit install must never become the
*required* entry point) is a real, worth-keeping constraint on its own accessibility merits —
anyone without a Revit license can still run something useful — but it should not be read as an
epistemic ranking of the three sources. DLL reflection is annotation-only today because of build
order plus a deliberate choice to keep Revit access optional, not because it has less to say.

**Real, not-yet-run validation exercise this suggests**: run an equivalent classifier directly
against an existing `ground_truth_manifest_<version>.json`, bypassing docs entirely, and diff
the resulting candidate set against the docs-derived one. Any divergence beyond
`DOCS_SEMANTIC_HINT`-tagged edges would be a genuine signal about docs coverage gaps — something
`cross_validate_dll` never checks today, since it only verifies existence/signature of candidates
docs already produced, and never independently re-derives `candidate_edge_type` from the
manifest itself.

## Not in scope for this document

Actually implementing any of the above. This is a design record of open questions, same posture
`dll_reflection_v0.md` had before any of Stages A/B/C existed — revisit and update in place as
questions get resolved, rather than treating this as a historical artifact once work starts.

<!-- SPDX-License-Identifier: MIT -->
# Myron discovery planning contract (Phase 2.19)

Status (2026-10-25): **offline, synthetic, structural only**. This phase adds a
planning contract and a pure validator for **Stage 1** of the staged discovery
process in [DISCOVERY-GATE.md](DISCOVERY-GATE.md). It creates no real request, no
approval, no transport, no capture, no provenance or ledger artifact, no hardware
parser adapter and no hardware authority. Stages 2 to 4 stay unsupported and
documentation-only. **Stage 0 prerequisites stay unresolved**: this phase does not
waive the real kit, snapshot and preflight request or any other prerequisite. All nine
authority flags stay `false` and all seven deployment blockers stay unchanged.

## Files

- `device/myron/discovery-contract.json`: the canonical public contract (version
  0.1.0, schema `myron-discovery-contract/1`, a namespace distinct from the capture,
  session, bootchain and fixture contracts).
- `tools/myron-discovery`: a small trusted loader (same pattern as
  `tools/myron-kernel-source`: one no-follow capture of the implementation bytes,
  compiled and executed from those bytes).
- `tools/lib/myron-discovery-impl.py`: the implementation. A validator, not a generator:
  there is no command that builds, signs or converts a plan.
- `tests/myron-discovery`: synthetic tests, registered in `tests/all`.

## Commands

| Command | Behaviour |
| --- | --- |
| `show` | Emits the exact committed contract. The file must equal the canonical rendering of the in-code contract, or the tool refuses. |
| `check-plan --stdin` | Reads at most 16 KiB of JSON from stdin only, validates it, then prints one **fixed** success document. |
| `--version` | `0.1.0`. |

Exit 0 is success, 1 a refusal (stdout empty, stderr exactly `myron-discovery:
E_REFUSED`), 2 misuse (stderr exactly `myron-discovery: E_USAGE`). Nothing from the
input is echoed: no plan, digest, reference, count, path or exception text. The
success document is a constant (`status` `synthetic-plan-structurally-valid`,
`meaning` `structure-only`, and `hardware_read_authorized`, `execution_supported`,
`approval_issued`, `evidence_collected`, `blockers_cleared` and
`stage0_prerequisites_satisfied` all `false`).

## Plan schema (closed, exact key sets)

```
schema "myron-discovery-plan/1", kind "myron-discovery-plan",
domain "synthetic-discovery-plan", stage 1,
bindings { contract_sha256, implementation_sha256, synthetic_review_context_sha256 },
target_ref, trust_ref, output_ref, recovery_ref,
sources    [ { source_ref, metadata_profile_id } ],
operations [ { sequence, source_ref, command_id, max_returned_bytes, timeout_ms } ],
limits { max_calls, max_returned_bytes, max_elapsed_ms },
stop_policy_id
```

Key order is not significant; the key sets are. Operation order is significant.

Invariants the validator enforces:

- Exact types. Budgets are positive integers; booleans are not integers.
- **References resolve only inside the pinned review context**: a finite list of dummy
  names (`synthetic-target-ref-1`, `synthetic-source-ref-1`, ...). No real host key,
  endpoint, source name, path, output location, identifier or private hash exists in
  the contract.
- Command IDs are inert identifiers that must be listed for the source's metadata
  profile. There is no field for shell text, glob, URL, path, block range, offset,
  partition payload operation, retry, wildcard or observed-value interpolation.
  Such keys are refused by name (`forbidden-field`) and every other unknown key is
  refused by the closed schema.
- Sources are unique, in review-context order, and are exactly all three review-context
  sources (one identity source, two distinct topology sources). A subset is refused.
- Operations are serial: `sequence` is exactly 1..n in list order; each
  `(source_ref, command_id)` pair appears once.
- **Required Stage 1 coverage.** The review context carries
  `stage1_required_operations`, an explicit ordered list in the contract (not derived
  from any observed value): the independent identity/trust check first, then, for each
  topology source in order, its topology and then its geometry command. `operations`
  must equal that list exactly. Omitting, adding or reordering a source or command is
  refused (`required-sources`, `required-coverage`, `required-order`), so identity-only,
  topology-only, geometry-only, identity-last and single-topology-source plans fail.
  At least `min_distinct_topology_sources` (2) distinct sources carry the topology
  command, preserving the Stage 1 disagreement-check model. This is a statement about
  the synthetic model only; it defines no real acquisition semantics. A plan may still
  choose lower positive per-operation bytes and timeouts.
- `max_calls` equals the operation count (5 with the current review context). Each operation's bytes and timeout are at
  most its command's ceiling. The sum of operation bytes is at most
  `limits.max_returned_bytes`; the sum of timeouts (serial) is at most
  `limits.max_elapsed_ms`.
- Limits are at most the contract's synthetic Stage 1 ceilings (6 calls, 16384
  bytes, 30000 ms). These are **hypothetical planning numbers, not reviewed Stage 0
  limits**, and are separate from the **parser ceilings** (16 KiB input, depth 4,
  256 nodes, 64-character strings, 16 items), which bound this program's own parsing.
- Strict JSON: duplicate keys, invalid UTF-8, a BOM, `NaN`/`Infinity`, floats,
  non-ASCII or control characters, excess depth, size or node count are refused.
- Domain isolation: `fixture`, `hardware`, `live` and any other domain, stages 2 to 4,
  and approval, evidence, ledger, provenance, transport or execution fields are
  refused. A fixture artifact or contract is never a valid plan, and the existing
  fixture collector (`tools/myron-collect`, unchanged) refuses discovery-shaped input at
  the content level (the tests build a valid preflight request and a separately placed,
  structurally closed capture tree whose files carry a discovery plan). There
  is no converter between the two.

## Reads of the repository's own files

The loader (for the implementation) and the validator (for the contract) read each
file once through a no-follow descriptor chain. A file is accepted only if it is a
regular file, owned by the caller, not group/other-writable, has one link and is within
its byte bound; exactly `st_size` bytes are read; and a second `fstat` of the same
descriptor shows an unchanged identity (`st_dev`, `st_ino`, `st_mode`, `st_uid`,
`st_nlink`, `st_size`, `st_mtime_ns`, `st_ctime_ns`). Truncation, growth, a same-size
rewrite, a mode change or any metadata change during the read refuses with the fixed
public line. Descriptors are closed on every path.

## Bindings and the hash graph

The graph is directed. The plan binds three digests; the contract carries none of
itself or of the implementation, so nothing hashes itself.

| Binding | Computed from |
| --- | --- |
| `contract_sha256` | the exact bytes of `device/myron/discovery-contract.json` as read |
| `implementation_sha256` | the exact captured bytes of `tools/lib/myron-discovery-impl.py` |
| `synthetic_review_context_sha256` | canonical JSON (sorted keys, no spaces, ASCII) of the contract's `review_context` |

The loader is excluded from the implementation digest and is reviewed in git. No
digest claims to cover Python, the standard library or any other runtime dependency.
Because `implementation_sha256` changes with every edit to the implementation, a
plan cannot be a static document; tests derive it from the running module.

## What a pass means

A pass shows only that the plan is structurally consistent with the synthetic
contract. It does **not** authorize a hardware read, issue an approval, execute
anything, collect evidence, clear any blocker or satisfy any Stage 0 prerequisite. It
is not a request, and nothing downstream may treat it as one.

## Future producer requirements (documentation only, nothing implemented)

A later, separately reviewed producer would need, at least:

- A **private provenance** record binding the session, target, trust root, source
  mapping, code, contract, request and approval.
- A **ledger** recording every attempt: requested and actual returned bytes, elapsed
  time and outcome, rereads and overreads, failed calls and incomplete accounting.
- Crash-safe, no-overwrite publication of both, with private modes.

No schema for these is defined or implied here.

## Non-goals

A real request, an acquisition schema, a producer, a transport, a capture, hardware
bytes, a parser adapter, approval issuance, deployment readiness, and a converter from
discovery documents to capture fixtures. Stages 2 to 4 are described in
[DISCOVERY-GATE.md](DISCOVERY-GATE.md) only.

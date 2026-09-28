# SCRUM-91 — Tron (Nile testnet) TRC-20 fee-estimation module

Design documents under adversarial review by Codex. **No implementation
until a literal `APPROVE`.**

- `DESIGN.md` — full design draft (v12, 2026-09-28). Spanish.
- `gen_binding_vectors.py` — runnable binding-vector generator. Verifies
  itself: asserts preimage lengths, SHA-256 digests and literal preimage hex
  for three vectors, plus semantic derivation checks (authoritative
  maintenance boundary invariant, pricing-horizon gate, strict proposal
  validation), 10 real mutation tests and 10 negative cases.
- `binding_vectors.json` — regenerated vectors (V1 539 bytes, V2 489 bytes,
  V3 539 bytes).
- `codex_v12_submission.txt` — the review brief for v12 (v11 file kept for
  history).

Scope: Tron Nile testnet only. Additive, isolated, behind `TRON_ENABLED`
(default off). v12: estimation-only module — no reserve, no signing, no
broadcast (those moved to a future phase, §18 of DESIGN.md). No mainnet,
no real funds.

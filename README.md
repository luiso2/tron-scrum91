# SCRUM-91 — Tron (Nile testnet) TRC-20 fee-estimation module

Design documents under adversarial review by Codex. **No implementation
until a literal `APPROVE`.**

- `DESIGN.md` — full design draft (v11, 2026-09-28). Spanish.
- `gen_binding_vectors.py` — runnable binding-vector generator. Verifies
  itself: asserts preimage lengths, SHA-256 digests and literal preimage hex
  for both vectors, plus semantic derivation checks (maintenance-boundary
  formula, pricing-horizon gate, proposal activation rule).
- `binding_vectors.json` — regenerated vectors (V1 486 bytes, V2 436 bytes).
- `codex_v11_submission.txt` — the exact review request sent to Codex for v11.

Scope: Tron Nile testnet only. Additive, isolated, behind `TRON_ENABLED`
(default off). No signing, no broadcasting, no mainnet, no real funds.

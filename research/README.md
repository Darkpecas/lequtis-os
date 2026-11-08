# Liquid Neurology research arrays — isolated candidate

**Status:** RESEARCH_PACKET_GENERATOR_READY; NO live Hermes/VPS execution claimed.
**Owner:** LeQutis; all research arrays and external tools are subordinate.

This is a bounded, standard-library-only staging mechanism, not a redesign of the sovereign runtime.

## Usage
```sh
python3 research/liquid_neurology_arrays.py --goal "Evaluate MCP 2026-07-28 interoperability" > /tmp/lequtis_research_packets.jsonl
python3 -m unittest discover -s tests -p 'test_liquid_neurology_arrays.py'
```

The first command generates seven diverse JSON task packets. It does not dispatch them.
Hermes must be inspected and an authorized task API verified before any live dispatch.
Do not run agents from untrusted research responses; keep execution behind LeQutis gates.
The receipt parser checks structural completeness only, **not** cryptographic authenticity or external execution.

## Research protocol
For every array preserve original hypothesis, primary source, contradiction, negative evidence, baseline, test, result and recommendation. Blindly cross-check before synthesis. Never equate a source claim, a packet, a local test, and a live Hostinger result.

Decisions: HARVEST / ISOLATED_EXPERIMENT / BOUNDED_USE / WATCH / REJECT / ORIGINAL_INVENTION.

## Seven independent arrays
1. Protocol frontier — MCP specification, implementations, conformance
2. Memory evolution — learning versus retrieval, interference tests
3. Diversity — blind hypotheses and falsification
4. Engineering — feature tests and independent re-execution
5. Security — authorization, hostile responses, evidence integrity
6. Continuity — Hermes resumption, idempotency, disconnected iPhone
7. Invention — curiosity allocation versus equal-budget baseline

## Deployment gates
- G0: file read-back and local unit tests
- G1: isolated branch PR; Doc/TBQ/Verifier review
- G2: **read-only** inventory of the existing Hostinger Hermes instance
- G3: approved isolated dispatch adapter and independent execution receipts
- G4: live end-to-end retest and rollback evidence
All beyond G1 are **NOT VERIFIED**. Never automatically install a new server or change LeQutis Core.

## Source manifest
MCP: https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro
Conformance: https://github.com/modelcontextprotocol/conformance
Tasks: https://github.com/modelcontextprotocol/ext-tasks
SDK implementation: https://github.com/modelcontextprotocol/python-sdk

# AI Research Boundaries

The AI layer can explain one audited `development` or `validation` trial. It
cannot read the sealed holdout, change research inputs, run code, fetch files by
path, or contact an exchange. The campaign-root `facts.json` currently points
to the consumed holdout, so the AI loader deliberately skips that file and all
`holdout-*.json` artifacts. It builds an in-memory fact view from a selected
`trial-*.json`, its ledger and margin audit, then checks the snapshot hashes
against the audited manifest.

## Read-only tools

The only tool names are `get_summary`, `get_attribution`, `get_risks`, and
`get_evidence`. Calls must name a registered `trial_id`; evidence lookup also
requires a registered `evidence_id`. Arbitrary file paths, shell commands,
code execution, network access, fee changes, and holdout requests are rejected.
This is application-level allowlisting, not an operating-system sandbox.

Tool diagnostics stay in memory and contain only the allowlisted tool name,
valid trial ID, and allow/deny status. Raw arguments and credential-like values
are never included in diagnostics or returned error messages.

## Reports and optional model client

`render_analysis` prints numeric facts from the core trial artifact. Optional
model text appears in a separate section and cannot add fields, cite unknown
evidence IDs, include numeric claims, or contain fee/holdout/execution
instructions. Invalid output, a timeout, or an unconfigured client returns the
same facts-only report. The returned metadata records provider/model labels,
prompt version, an input SHA-256, and the safe tool-call log.

`UnconfiguredClient` is intentionally offline. No provider, API key, network
call, or API-key environment lookup is included in this iteration. A future
provider must be configured separately and must preserve the same response
schema and data boundary.

## Example

```python
from crypto.ai.client import UnconfiguredClient
from crypto.ai.facts import load_facts
from crypto.ai.report import generate_narrative

facts = load_facts("results/crypto/btc-carry-v3-20261010", "trial-005")
result = generate_narrative(facts, UnconfiguredClient())
print(result["status"])  # fallback until a provider is explicitly configured
print(result["report"])
```

The selected negative `funding_filter` development trial is useful for a
deterministic demonstration: its figures remain sourced from the audited trial
and margin audit, while any future model explanation would be marked as prose.

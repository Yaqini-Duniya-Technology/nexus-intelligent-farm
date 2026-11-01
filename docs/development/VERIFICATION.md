# First reliability batch — verification record

Baseline: `e5eccd442eeada29769f304f4d025946c1fafe20`. Working branch: `upgrade/audit-roadmap-batch-1`.

## Local checks completed

- Python 3.12.14, standard-library workspace suite: **454 tests passed** (425 prior + 29 added).
- `node nexus/farm_app/test_form_safety.cjs`: passed valid-choice preservation, missing-choice clearing, idempotent lock restoration and response-generation ordering assertions.
- `node --check` passed for modified resource/form/Help scripts.
- `python -m nexus.farm_app.smoke_workspace`: **65 combined routes passed** against a new temporary database; response lengths and trace headers checked.
- Help index now measures approximately **34 KB**, listing summaries rather than all full guides. Full articles, search and offline downloads remain available. There are now **90** guides.
- Resource list paging defaults to 100 and caps at 200; a 105-entry fixture showed 100 + 5 nonoverlapping entries and all 105 in the filtered export.
- Persisted-domain tests rejected an invalid enum even after its content hash was made consistent. A prior payload without the later optional `captures` property stayed readable and unchanged.
- Strict request tests cover duplicate/nested keys, nonfinite/overflowing numbers, bounded JSON depth, charset/media, duplicated framing, Transfer-Encoding, compression, partial reads and timeout recovery. A valid legacy farm write still roundtrips; invalid requests save nothing.
- The combined write origin boundary now applies before all delegated routes. Server-generated trace IDs do not use client-supplied identifiers; request logs omit query strings, headers and bodies.
- Tracker tests validate 150 unique IDs, workstream totals, dependency acyclicity, required evidence and read-only operation.

## Remote and browser gates

The baseline GitHub run passed 749 repository tests with 123 subtests. That is baseline evidence, not a claim that this new branch has passed remotely.

A new CI workflow defines Ubuntu/Windows × Python 3.13/3.14 workspace jobs, helper/syntax checks and isolated route smoke checks. NEXUS-UPG-101 remains In Progress until all four remote jobs pass. The existing simulation/repository workflow remains separate and unchanged.

The environment did not have a browser runtime. A Chromium headless-shell download was attempted and failed because the downloaded archive was incomplete/invalid. No browser test pass is claimed. NEXUS-UPG-073 and NEXUS-UPG-074 therefore remain In Progress, even though implementation, pure-helper tests and syntax checks are present.

## Required manual browser acceptance for the two UI items

Use isolated Test records and no actual farm facts:

1. Open a resource/market form, select valid references and enter unsaved text. Refresh the record list; verify valid choices/text stay intact. A removed/ineligible choice must become blank with a visible warning.
2. Change field or Actual/Test source, clear the form or open another saved record. Verify the discard prompt; cancel it and confirm the original context/text remains. When changing only field and clearing values deliberately, the chosen Actual/Test source must remain explicit.
3. Save with a delayed response. Verify form and context controls lock, only one request is sent and previous disabled states are restored on failure. A successful save clears the form only after the result is received.
4. Trigger two delayed refresh responses in reverse order. Verify only the newest selection is shown. Check loading/error text as well as the record list.
5. Verify leave-page warning behaviour in the supported browser, noting browser restrictions on `beforeunload` prompts. No auto-save should occur.
6. Use keyboard and narrow viewport to check controls, labels and focus. These observations are not substituted by the pure JavaScript helper tests.

Actual user data, full device/mobile coverage, authenticated roles, production hosting and agricultural accuracy were not evaluated in this batch.

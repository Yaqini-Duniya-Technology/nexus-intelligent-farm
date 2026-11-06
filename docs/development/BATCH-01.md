# Baseline and protected inspections — batch 1

Release: nexus-baseline-inspections-v1. Parent source: 02070b9ed82de16f11996c9cc157007840c86440.

## Verified baseline and boundaries

This audit concerns repository source, isolated fixtures and the user's previous owner/viewer display check. The actual Windows database and running process are not accessible from this build environment. Do not equate a selected diagnostic file with the live process database.

`baseline/source-inventory.json` maps static candidate route literals, command modules, SQL table references and source hashes. It is not a reachability scanner: dynamic SQL and route assembly require review. `master-upgrades.json` tracks all 150 requirements; unassessed existing features are not labelled complete or absent.

Authenticated core routes: account session/login/logout/recovery/admin via the existing pilot allowlist; `/workspace`, `/api/workspace`; now `/field-inspections` and `/api/field-inspections`. Static scripts contain no farm records. All other legacy operational routes remain unavailable on this server. Legacy Operations without `--authenticated` remains single-user and must stay local.

Existing architecture: farms → fields → observations → tasks → task_actions/followups; observations → field_inspections with supersedes_id linking corrections. Session account → farm membership → role governs farm access. Inspection payloads retain frozen observations and content hashes. Security events link the acting account and farm. Other existing season, resource, evidence, market and voice modules appear in the inventory but are not thereby authenticated or validated by this batch.

## Requirement evidence and status

| IDs | Delivered evidence | Remaining acceptance |
|---|---|---|
| 001–003 | Reproducible static inventory, SQL dependency candidates, explicit authenticated/legacy boundary | Manual reachability/dependency review across all dynamic workflows |
| 004 | Release ID in audit and authenticated startup; source hashes | Operator confirms installed release and active process |
| 005–006 | 150-item status register and common acceptance gates | Detailed per-module acceptance criteria and prior roadmap reconciliation |
| 007 | New-directory-only DEMO generator with two farms and three scoped accounts | Operator usability check; fixtures pass locally |
| 008 | Existing Windows/Python 3.13/3.14 CI matrix retained; commands below | New commit's Windows CI results must be checked separately |
| 009–010 | Known limits, test evidence, explicit unverified status and progress rules | Remaining modules' detailed defect audit and real-user acceptance |
| 011–012 | Protected inspection service, page, API, audit transaction and contextual Help | Local browser sign-in/save/correction/refresh acceptance |

No item is marked Completed merely because code exists. Tests and manual checks are separate fields. No item is Field-Validated by this build.

## Security and record preservation

Inspection reads select only observations joined to the authorised farm. Optional observation IDs are checked against that farm. Owner/editor writes check membership again under BEGIN IMMEDIATE, then reuse the existing inspection validator and correction service on that same connection. Viewers cannot write even with forged frontend roles. Origin and CSRF checks apply to POST. Unknown routes continue to be denied. Auditing failures roll back inspection inserts. Stale histories and changed observations reject saves; identical payloads reuse existing entries.

Read-only requests do not initialise the inspection table. First authorised save creates it if absent, using the existing schema in the same transaction. No released migration text was changed. No actual database was opened or modified during development. Existing tasks, action records, bundles and original evidence are not rewritten.

## Operator installation and Help

Stop both running servers with Ctrl+C before updating code. Use the checked source installer from this release. It backs up the existing database and changed source before installing. `RELEASE.json` is a packaging-format manifest; the application release is the identifier above.

From the existing project directory:

```powershell
python -m unittest discover -s nexus/farm_app -t .
python -m nexus.farm_app.baseline_audit --database nexus-farm.sqlite3 > baseline-local.json
python -u -m nexus.farm_app.operations --authenticated --database nexus-farm.sqlite3 --port 8080
```

Keep baseline-local.json private: it includes the selected absolute database path, schema and counts, but no farm notes or authentication secrets. Compare its path with the launch command. It cannot inspect an unrelated running process. Read-only diagnostics refuse a nonexistent database rather than creating one.

Create an isolated demonstration workspace in a NEW directory, with a private password typed twice (not in command arguments):

```powershell
python -m nexus.farm_app.demo_workspace --directory "$HOME\NEXUS-demo-inspections"
python -u -m nexus.farm_app.operations --authenticated --database "$HOME\NEXUS-demo-inspections\nexus-farm.sqlite3" --port 8082
```

Accounts: demo-owner and demo-viewer have farm 1; demo-other has farm 2. All use the demo password you chose. No actual observations are copied. Do not use this demo database for actual farm records. Existing directory causes refusal, never overwrite. If creation is interrupted, use another new directory after inspecting the partial demo directory.

Open `/workspace`, select the DEMO farm, add an explicitly DEMO observation. Open Field inspections, select the same farm and observation. Record DEMO inspection with actual test time after observation, required descriptions and counts. Blank means unknown; zero means counted none. Correct one entry with a reason; confirm the earlier entry remains after refresh. A new visit uses New inspection. Inspect the page Help for field meanings, examples, limitations and error recovery. Saving inspections does not complete tasks or create decision actions.

In a private browser sign in demo-viewer: read history, no save form. demo-other must not see farm 1. Automated tests additionally exercise direct API tampering, CSRF/Origin rejection, expired/disabled accounts, revocation and atomic rollback. Browser testing does not replace these checks.

## Known limits and follow-up

No browser/mobile acceptance has yet been recorded for the new inspection page. Large inspection histories are not paginated; measure performance before large-scale use. Unsaved entries remain in page memory after errors, not persistent browser storage. Reauthentication in another tab preserves the current draft until refresh; closing/reloading loses it. Refresh updates stale history tokens but the user must deliberately assess newer evidence before resubmitting. Existing account/session controls remain unchanged.

No new livestock module, chatbot, diagnosis, task assignment system, shared hosting or automatic financial posting is introduced. Adviser identities remain user-reported. Legacy schemas outside this permission rollout need a separate ownership review before enabling their routes.

## Progress measurement

Technical denominator: 150 upgrade records. Verified completion numerator requires item-specific technical, documentation and manual acceptance evidence. Until those gates are assessed, report status counts, not an invented product percentage. Local-pilot denominator: the 11 acceptance statements in the supplied master prompt; each needs an evidence record before calculating a satisfied/11 percentage. Long-term six-area vision has no agreed requirement denominator, so percentage is not measurable yet. Prior approximate 30% was a planning estimate, not a verified measurement; this release does not repeat it as fact.

## Rollback

Stop the server. Restore changed code from the installer's backup-authenticated-core-code directory, then use the matching previous launcher. No destructive migration is required. Keep database backups private; restore a database only as a separate, deliberate recovery operation, because doing so would discard later records. Do not overwrite the database merely to undo this source update.

## Local verification record — 6 November 2026

502 standard-library workspace tests passed (72.722 seconds). Existing combined workspace smoke passed all 65 routes on an isolated temporary database. New JavaScript passed Node syntax checking. Git whitespace validation passed. Full-repository pytest and new Windows/browser checks are not claimed by these local results; see CI separately. Six new protected-inspection tests plus three baseline tests were added. No actual farmer database was used.

A subsequent focused run passed 23 tests after the final startup/help changes. The whole-repository pytest attempt was blocked during collection by missing `kaggle_environments` in this local runtime (four import errors); no full-repository pass is claimed locally. GitHub CI uses the repository dependency installation and is reported separately.

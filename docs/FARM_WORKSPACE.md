# NEXUS local farm workspace

A single-user, loopback-only Python/SQLite pilot alongside the simulation MVP. Field entries, sources, identities and outcomes are user-reported. This workspace does not execute the simulator's autonomous policy against a real farm.

## Start

From the repository root, with Python 3.13 or newer:

```bash
python -m nexus.farm_app.operations --port 8080 --database nexus-farm.sqlite3
```

The local workspace uses Python's standard library and loads no AI model just to open these pages. Simulation dependencies in the repository requirements files are a separate concern. For imported ASR/model workflows, follow the existing explicit model setup separately; speech expansion remains deferred.

| Page | Purpose |
| --- | --- |
| `/workbench` | Find records, plan work and check consistency |
| `/evidence-studio` | Measurements, case questions and evidence links |
| `/resources` | Supplies, equipment, labour, budgets and traceability |
| `/market` | Produce lots, buyer enquiries, orders and receipt reports |
| `/help-centre` | 89 workflow guides, meanings and fictional examples |
| `/overview` | Existing farm dashboard |

Keep the server terminal open. Open `http://127.0.0.1:8080/workbench` in your browser. Stop with Ctrl+C. This is not an authenticated multi-user or public deployment.

## Data and history

- Start from an empty database or supply the path to your existing pilot database. Never commit actual farm records, contact details, credentials, audio or exports.
- Use Test material for practice. Leave optional actual harvest links blank for test lots. Test recordings do not become farm observations.
- New resource and market entries use append-only corrections, source separation, reference checks and request reuse. Existing legacy records have their own documented correction rules.
- Market quantities and payment reports are a separate ledger. They do not post core stock movements or Finance transactions. Offer sheets are local drafts; order statements are not authenticated or tax invoices.
- Confirmed orders reserve recorded quantities. Actual losses/returns may reveal commitment shortfalls; they are shown rather than hidden by invented stock.
- Saved evidence bundles preserve their captured scope. New links or later corrections do not rewrite earlier captures. Hashes establish consistency, not independent accuracy or identity.
- Names and sources are user-reported; Help never fills or submits forms. No outreach, payment, diagnosis or equipment action is executed.

## Tests

```bash
python -m unittest discover -s nexus/farm_app -t .
```

425 farm-workspace tests passed in the release environment. This count is separate from the simulation regression baseline. The packaged Windows installer had 6 additional tests; it is distributed with the downloadable release, not required for a fresh Git clone. 65 local-launcher route checks also passed. Browser visual/keyboard and Windows-specific execution still need local checks.

The existing GitHub Actions workflow runs repository-wide pytest, including these unittest classes. Its remote result may differ from the local standard-library run because it also installs and tests the simulation environment.

## Backup

Before updating an existing installation, stop the server and back up the actual database:

```bash
python -m nexus.farm_app.backup --database nexus-farm.sqlite3
```

SQLite backups include market/resource entries. External files remain outside a database backup. Do not push databases or backup/export directories to GitHub. For recovery controls, use the existing Operations system-checks page and documented recovery commands; never overwrite your only original copy.

## Next phase

Pilot the workflow with labelled test records, then prioritise explicit core-stock/Finance reconciliation previews, complete order evidence captures and controlled access before shared-network deployment. Speech/chatbot expansion remains last.

Built by [Yaqini & Duniya Technology](https://yd.ydtech.workers.dev).

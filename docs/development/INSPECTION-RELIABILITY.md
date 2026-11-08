# NEXUS inspection reliability

Release: `nexus-inspection-reliability-v1`. Scope: NEXUS-INS-001 and NEXUS-INS-002.

## Using a draft

- Select the correct farm and observation. Choose **New inspection** for an actual separate visit or select the specific entry to correct. A correction appends an entry, keeping the original.
- **Refresh records** keeps the current tab's draft. If the observation, history or correction target changed, saving is blocked. Read the refreshed history. Choose a valid correction target and confirm it, or use **Use reviewed history** when the original target is still available. Changing a correction to a separate visit requires confirmation.
- If a save result is unclear, select **Retry same save**. This resends the exact request. It either saves it once or returns the existing inspection number. If your session expired, sign in in another tab as the original account and use **Refresh records** before retrying. A revoked or read-only account cannot submit or replay a save.
- Drafts and pending retries are held in tab memory. Full page reloads, closing the tab, and browser crashes can lose unsaved text and the retry ID. If that happens after an uncertain save, check the saved history before entering it again. No private draft text is written to browser storage.

## Data and access

The server checks session, CSRF, farm membership, write role and observation ownership before processing a save or returning a prior result. Correction requests include the original target ID and its content hash, plus the observation hash and history version. An invalid or stale correction returns a conflict. The role and farm checks remain inside the same write transaction as the inspection.

The first keyed save adds the SQLite table `nexus_inspection_receipts` inside the write transaction. It stores account and farm scope, request UUID, request hash and inspection ID. The inspection, receipt and security audit event commit or roll back together. No migration command is needed; existing inspections and old clients are preserved. Keyed requests only deduplicate an exact retry using the same key. Separate visits can have identical contents. Older clients without a key retain the previous content-based retry behavior. No legacy routes were opened.

## Install and verify on Windows

Download and extract `nexus-inspection-reliability.zip`. Stop the running NEXUS servers with Ctrl+C before installing. From your existing NEXUS directory:

```powershell
Expand-Archive "$HOME\Downloads\nexus-inspection-reliability.zip" "$HOME\Downloads\nexus-inspection-reliability" -Force
python "$HOME\Downloads\nexus-inspection-reliability\install_workspace.py" --project . --database nexus-farm.sqlite3
python -m unittest discover -s nexus/farm_app -t .
python -u -m nexus.farm_app.operations --authenticated --database nexus-farm.sqlite3 --port 8080
```

Use the existing database only to check sign-in and read history. For save and correction trials, create a new demo directory. The command asks for a demo password; use it for the demo accounts only.

```powershell
$demo = Join-Path $HOME ("NEXUS-inspection-demo-" + (Get-Date -Format yyyyMMdd-HHmmss))
python -m nexus.farm_app.demo_workspace --directory "$demo"
python -u -m nexus.farm_app.operations --authenticated --database "$demo\nexus-farm.sqlite3" --port 8082
```

Open [the demo sign-in](http://127.0.0.1:8082/) as `demo-owner`. Create a clearly labelled demo observation in the workspace, then open [Field inspections](http://127.0.0.1:8082/field-inspections). Save one visit, correct it and reload the page. For a two-tab check, select the same correction target in both tabs, save in one, and use **Refresh records** in the other. The stale draft must stay blocked. In a private window, sign in as `demo-viewer`: history should be visible without a save form. `demo-other` is assigned to the other farm only.

## Automated browser acceptance

Run `python -m nexus.farm_app.smoke_inspection_browser` with Node and the Playwright package available and Chromium installed. It creates its own temporary two-farm database and only changes test accounts. With Playwright installed in a separate tools directory, set `NODE_PATH` to that directory's `node_modules`. The optional `NEXUS_CHROMIUM_PATH` setting selects an already installed Chromium binary.

## Rollback and remaining scope

If a source rollback is necessary, stop the server and restore the installer's source backup. The additive receipt table can remain; do not drop it or restore over a live database just to undo source changes. Keep the database backup private.

Batch 1 does not include the redesigned inspection history, isolated backup restore/startup verification, or authenticated crop seasons. The next batch is NEXUS-INS-003 and NEXUS-REC-004. No field validation or production recovery is claimed.

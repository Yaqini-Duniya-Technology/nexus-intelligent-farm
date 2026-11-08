# NEXUS inspection history and isolated recovery

Release: `nexus-inspection-history-recovery-v1`. Scope: NEXUS-INS-003 and NEXUS-REC-004.

The protected inspection page lists entries newest first. Each card shows its local inspection time, sample counts and correction links. Expand **Details and correction history** for the field, observation at capture, sampling method, reported findings, limits and changed values. Original entries remain visible. Counts describe the recorded sample; no percentages, diagnoses or field-wide estimates are inferred. Zero, unknown, not recorded and not applicable have distinct labels. The displayed timezone is the browser’s; saved timestamps stay unchanged.

## Install on Windows

Download and extract the release ZIP. Stop the running workspace with Ctrl+C. From your existing project directory:

```powershell
Expand-Archive "$HOME\Downloads\nexus-inspection-history-recovery.zip" "$HOME\Downloads\nexus-inspection-history-recovery" -Force
python "$HOME\Downloads\nexus-inspection-history-recovery\install_workspace.py" --project . --database nexus-farm.sqlite3
if ($LASTEXITCODE -ne 0) { throw "NEXUS installation failed." }
python -m unittest discover -s nexus/farm_app -t .
if ($LASTEXITCODE -ne 0) { throw "NEXUS tests failed." }
python -u -m nexus.farm_app.operations --authenticated --database nexus-farm.sqlite3 --port 8080
```

Confirm the release, database path and **authenticated core workspace** in the terminal. Open [Field inspections](http://127.0.0.1:8080/field-inspections), choose a farm and observation, then open a history card. A port conflict stops startup and suggests `Get-NetTCPConnection -LocalPort 8080 -State Listen`. A missing or incompatible database stops startup. The launcher does not select another database or fall back to a legacy server.

## Reproduce the isolated recovery drill

The automated drill creates a disposable two-farm database, saves an original inspection and correction, backs it up, restores the backup into a new directory, and starts the actual authenticated launcher against the restored copy.

```powershell
python -m unittest nexus.farm_app.test_restore_isolated -v
```

It verifies fresh owner/viewer sign-ins, farm membership, field and observation access, exact inspection history equality including hashes and timestamps, cross-farm denial, original retry receipt reuse, missing/incompatible databases and occupied-port diagnostics. It checks that both input database files remain byte-for-byte unchanged. For the real Chromium check, install the browser tools described in [Inspection Reliability](INSPECTION-RELIABILITY.md) and set `$env:NEXUS_RESTORE_BROWSER = '1'` before running the command. Remove that variable afterwards with `Remove-Item Env:NEXUS_RESTORE_BROWSER`.

To rehearse manually with a **demo** backup, stop the other workspace before opening the restore in the same browser profile: loopback cookies can be shared across ports. Alternatively, use a separate browser profile. Use the exact path printed by the backup command.

```powershell
python -m nexus.farm_app.backup --database "$demo\nexus-farm.sqlite3" --output-directory "$demo\backups"
$restore = Join-Path $HOME ("NEXUS-restore-drill-" + (Get-Date -Format yyyyMMdd-HHmmss))
python -m nexus.farm_app.restore_isolated --backup "REPLACE_WITH_PRINTED_DEMO_BACKUP_PATH" --directory "$restore"
if ($LASTEXITCODE -ne 0) { throw "Isolated restore failed." }
python -u -m nexus.farm_app.operations --authenticated --database "$restore\nexus-farm.sqlite3" --port 8082
```

Sign in with the existing demo account on the restored workspace and compare the same observation’s original and correction. The restore command refuses an existing destination directory, checks integrity, foreign keys and access migration checksums, and clears sessions and password reset tokens in the new copy. It keeps account credentials, memberships, inspections and receipts. No schema migration is required by this batch.

This is **database-only recovery**. External attachments, exports and audio are not restored. Keep backups and restore directories private; they contain workspace records and account hashes. This drill does not certify recovery of your live farm database. For a source rollback, stop the server and restore the installer's source backup. Crop season access remains a separate batch.

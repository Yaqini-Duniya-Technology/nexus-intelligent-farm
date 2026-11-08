# NEXUS protected crop seasons

Release: `nexus-protected-crop-seasons-v1`. Includes inspection reliability, mobile inspection history and the isolated recovery drill from the first two batches.

Open **Crop seasons** from the authenticated workspace. Select a farm, then add or edit a season. Owners and editors can write; viewers can read. An existing season cannot move to a different field. A season edit preserves prior and new details in the change history. Earlier legacy edits that were not recorded cannot be reconstructed. Saved harvest date, weight and area are read-only here.

Use **Observation season context** to link an observation to a season for the same field. An inspection follows its parent observation. Select **Unknown season** when the evidence is insufficient. This is different from no entry and from an unavailable legacy link. The recorded growth stage is user-reported; planting and expected harvest dates do not establish it. Earlier context retains the season details captured at the time.

The server checks session, CSRF, origin, farm membership and field relationships on protected requests. Legacy routes, season deletion/closure, exports and harvest editing remain outside this release. Protected season edits require the current record version. If a create response is lost, refresh and check the list before trying again.

## Windows installation

Download the source-only upgrade ZIP into Downloads. Stop the running NEXUS server with Ctrl+C. Run these commands from your existing NEXUS folder:

```powershell
$upgrade = "$HOME\Downloads\nexus-protected-crop-seasons"
Expand-Archive -LiteralPath "$upgrade.zip" -DestinationPath $upgrade -Force -ErrorAction Stop
python "$upgrade\install_workspace.py" --project . --database nexus-farm.sqlite3
if ($LASTEXITCODE -ne 0) { throw "NEXUS installation failed." }
python -m unittest discover -s nexus/farm_app -t .
if ($LASTEXITCODE -ne 0) { throw "NEXUS tests failed." }
python -u -m nexus.farm_app.operations --authenticated --database nexus-farm.sqlite3 --port 8080
```

Open [Protected crop seasons](http://127.0.0.1:8080/protected-seasons). The installer backs up the existing database and source. No separate migration command is required; the season tables and change history are initialised when first written. To trial writes, use a disposable workspace as described in the [inspection reliability guide](INSPECTION-RELIABILITY.md).

The [recovery guide](INSPECTION-HISTORY-RECOVERY.md) describes the isolated database drill and rollback. External files are outside the database restore. Stopping and restoring source files does not require deleting the additive change history table.

# Data directories, migrations and account foundations

Keep NEXUS local. The separate account pilot enforces its narrow farm scope; account records and farm grants are **not enforced across the full Operations web workspace**. Existing pages still expose the local workspace to its operator. Do not publish it or bind a proxy to it. Speech/chatbot expansion remains deferred.

## Select persistent storage

Stop NEXUS first. Existing commands using `--database nexus-farm.sqlite3` keep their meaning. The launcher prints the resolved database through its selected configuration.

For a dedicated directory, copy the existing `nexus-farm.sqlite3` and all its attachment/record directories while the app is stopped. Keep the original copy. This release does not move files for you. Launch with:

```powershell
python -u -m nexus.farm_app.operations --port 8080 --data-directory "C:\NEXUS-data"
```

That selects `C:\NEXUS-data\nexus-farm.sqlite3` and makes that directory the launcher's working directory, so relative attachment/export paths remain together. Assets are loaded from the installed source. Other standalone commands must still receive explicit database/output paths or run from this data directory. Do not combine `--database` with `--data-directory`.

A missing database is refused rather than silently creating an empty farm. Only for an intentionally new empty workspace:

```powershell
python -u -m nexus.farm_app.operations --data-directory "C:\NEXUS-new" --initialize-data-directory
```

Do not use that flag to fix a missing old database. Find the original database instead. Examples are illustrative paths, not existing locations on your computer.

## Preview and apply additive migrations

The new migration ledger governs new access-control tables. Existing legacy schema initializers remain in place; this is not yet a conversion of all historical schema changes to numbered migrations.

Read-only preview (the database must already exist):

```powershell
python -m nexus.farm_app.deployment_controls --database "C:\NEXUS-data\nexus-farm.sqlite3" --backup-directory "C:\NEXUS-data\backups"
```

Apply while the server is stopped:

```powershell
python -m nexus.farm_app.deployment_controls --database "C:\NEXUS-data\nexus-farm.sqlite3" --backup-directory "C:\NEXUS-data\backups" --apply
```

Alternatively add `--apply-migrations` to the launcher. Existing databases are migrated before legacy initialization; a newly initialized workspace is migrated after its core tables exist. Every pending migration batch requires a SQLite API backup whose integrity and relationships pass. A write lock protects the pre-migration copy. SQL and ledger entries commit together; failure rolls back them together, leaving the backup. Identical reruns do nothing. A changed checksum, unknown version or history gap stops startup. Never edit migration rows to bypass an error: restore the matching application release and investigate.

Backup files are local copies, not off-device disaster recovery. They contain personal farm data. To recover, stop NEXUS and restore the verified pre-migration database using the existing recovery procedure and matching source release. There is no automatic downgrade or destructive migration in this batch.

## Administer local account foundations

Apply migration 1 first. From a private terminal:

```powershell
python -m nexus.farm_app.local_accounts --database "C:\NEXUS-data\nexus-farm.sqlite3" create --username example-owner
python -m nexus.farm_app.local_accounts --database "C:\NEXUS-data\nexus-farm.sqlite3" grant --account-id 1 --farm-id 1 --role owner
```

The username is 3–64 lowercase ASCII letters, digits, dots, dashes or underscores. Password entry is hidden, repeated for confirmation, and accepts 12–1024 characters. Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes with 600,000 iterations; no plaintext password or command-line password argument is stored. Example IDs must be replaced with actual IDs.

A grant associates one enabled account with one existing farm. `owner` and `editor` can pass the write-permission primitive; `viewer` can pass the read primitive only. Other farms are denied. The last enabled owner cannot be demoted through the grant command. These are technical scope roles, not assertions that someone is a qualified adviser or administrator. Account disabled flags deny the primitive. Operating-system access to the database/CLI remains privileged; no account enrollment or identity verification is provided.

## Authenticated local pilot

After applying both migrations and creating an account/grant, start the separate pilot:

```powershell
python -u -m nexus.farm_app.account_pilot --database "C:\NEXUS-data\nexus-farm.sqlite3" --port 8081
```

Open http://127.0.0.1:8081. Sign in with the account created above. Only permitted farms, their fields, up to 100 recent observations and up to 100 separate pilot notes are exposed. Editor/owner may add notes; viewer may only read. Notes never create farm observations/tasks. All other routes, including legacy exports and attachments, are unavailable in this pilot. The full Operations launcher remains single-user and does not enforce these grants.

Sessions use random tokens stored only as hashes, an eight-hour absolute lifetime and 30-minute idle timeout. Cookies are HttpOnly and SameSite Strict. Note saves and logout require matching local Origin and a session CSRF token. Five failed logins per username within 15 minutes temporarily limit retries; failed passwords and unknown accounts share a generic response. Grants and disabled-account state are rechecked on requests. This loopback HTTP pilot does not use Secure cookies; hosted TLS/cookie configuration is still required. Use a private computer and sign out when finished. No password reset, public enrollment or hosted identity verification is provided.

The page includes contextual help, illustrative examples and unsaved-note warnings. HTTP and service tests verify isolation; real-browser acceptance remains pending.

## What remains before shared hosting

Password reset and account lifecycle; integration of authenticated identity at every full-workspace route; farm-scoped queries, exports, attachments and mutations; CSRF/session-cookie controls; account lifecycle/audit; role-matrix review; cross-farm HTTP tests; hosting/TLS/recovery acceptance. These are not replaced by creating account records. The local Host and Origin checks remain useful but are not authentication.

## Validation

Tests cover backup-before-schema, no-op reruns, failed backup, transactional schema rollback, checksum/future-version refusal, missing-directory refusal, explicit path conflict, password checks, viewer/write separation, disabled accounts, cross-farm denial and last-owner protection. Test fixtures contain no real farm evidence. Existing local workspace tests and route smoke remain required.

## 5 November continuation

Migration 3 adds platform administration, account activity and operator-assisted password recovery. See [Account administration and recovery](security/ACCOUNT_GUIDE.md) for current supported commands. The earlier account-foundation limitations above describe the initial pilot; password recovery is now implemented, while full Operations authentication and shared hosting remain incomplete.

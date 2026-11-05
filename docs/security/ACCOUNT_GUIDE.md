# Account administration and recovery

Stop both local servers before installing or applying migrations. Keep your existing database and attachments. Use the updater's checked backup; migration 3 also requires its own checked pre-change backup. Do not edit schema history or reset a populated database.

## Upgrade and bootstrap

From your NEXUS project folder:

```powershell
python -m nexus.farm_app.deployment_controls --database nexus-farm.sqlite3 --backup-directory backups
python -m nexus.farm_app.deployment_controls --database nexus-farm.sqlite3 --backup-directory backups --apply
```

Find the existing account IDs without SQL, then use the intended owner's actual ID (example 1):

```powershell
python -m nexus.farm_app.account_admin --database nexus-farm.sqlite3 list-local
```

```powershell
python -m nexus.farm_app.account_admin --database nexus-farm.sqlite3 bootstrap-admin --account-id 1
python -u -m nexus.farm_app.account_pilot --database nexus-farm.sqlite3 --port 8081
```

Bootstrap is a privileged local filesystem-operator action. It works only once and never assigns farm membership. If the ID is unknown, use the existing account creation output; do not guess. No existing owner automatically becomes a platform administrator. A second bootstrap is rejected.

Sign in at http://127.0.0.1:8081. Platform administrators see Account administration; it opens `/admin`. Other accounts cannot read this page/API. No farm assigned means the operator must explicitly assign an existing farm. Creating an account alone does not grant one.

## Dashboard fields and steps

1. Search: enter part of the lowercase username, e.g. fictional `example-viewer`. Choose All/Enabled/Disabled and Refresh. Lists show at most 100 accounts per page. Last sign-in means the latest successful sign-in recorded by this release; older activity may be unavailable.
2. Create: enter a unique 3–64 character lowercase ASCII username (letters, digits, dot, dash, underscore), a 12–1024 character password and exactly the same repeat. Passwords are hidden and never shown in the account list. Deliver initial credentials privately.
3. Assign: enter the account ID displayed in the list, choose an existing farm and one of the implemented roles, then Assign role. Viewer reads permitted records; editor/owner can add separate pilot notes. Owner adds ownership status and last-owner protection. These roles are not professional qualifications.
4. Remove assignment: choose the correct account and farm, then confirm removal. That farm becomes inaccessible on subsequent protected requests. It does not delete farm records.
5. Disable/enable: enter the account ID, then confirm. Disable rejects subsequent requests and destroys prior sessions/reset credentials. Enable allows a fresh sign-in, not reuse of an old session. Another enabled owner must exist for every owned farm before disabling an owner. The last platform administrator is protected.
6. Activity: read the newest 100 security events, including actor, affected account, farm, category, time, result and safe summary. There is no edit/delete interface. Events do not verify a user's real identity. Local CLI actions are labelled as privileged local-operator actions.

Owner does not imply platform administrator. Creating another account does not grant platform-administrator status. Additional administrator delegation is not included in this batch.

## Recover a forgotten password

An authorised operator must confirm identity independently, for example through an already established in-person contact. Do not accept an unverified username alone as proof. No email/SMS service is configured.

From a private terminal, replace the example IDs and private output path with real values. `--operator-id` must be an enabled platform administrator. The local CLI is privileged by filesystem access; do not give shell/database access to ordinary app users.

```powershell
python -m nexus.farm_app.account_admin --database nexus-farm.sqlite3 issue-reset --operator-id 1 --account-id 2 --identity-basis "Identity checked in person through an established contact" --output "$HOME\nexus-private-reset.txt"
```

The file must not already exist. It receives a single-use credential valid for 15 minutes. On Windows, use a private folder with access restricted to the operator; Python file-mode bits do not substitute for Windows ACLs. Read and deliver the credential privately to the verified user. Do not paste it into chat, farm records, screenshots, shared folders or URLs. Delete the file after use; never commit it to Git.

The user opens the recovery section on the pilot sign-in page, enters the credential and repeats a new password. Successful recovery signs out all previous sessions, consumes every outstanding reset for that account and requires a new sign-in. Disabled accounts cannot reset. Issuing another credential invalidates the old one. If expired/used, request a new independently verified recovery.

## Troubleshooting and boundaries

- Passwords differ: repeat exactly, check Caps Lock and keyboard layout; no reset is saved on mismatch.
- No farm assigned: ask the operator for an explicit farm grant, then Refresh. Signing in does not create a farm.
- Session expired/unavailable: sign in again; disabled accounts and revoked sessions are refused. Contact your operator if access changed.
- Insufficient permission: a viewer cannot save notes or administer accounts. Farm ownership alone does not grant platform administration.
- Last owner/administrator error: establish a legitimate replacement before removing access. Do not bypass the guard with SQL.
- Migration checksum/history error: stop and investigate the installed source/database version. Do not change recorded checksums.
- Failed save: read the message, refresh saved records and check whether it was saved before retrying. Audit persistence is in the same transaction as successful admin changes.

The pilot is local HTTP only. Shared hosting, secure hosted cookies/TLS and all full-workspace permissions remain unfinished. Keep Operations (8080) single-user and private. The pilot's notes are separate from observations/tasks. Advanced speech/chatbot expansion remains deferred.

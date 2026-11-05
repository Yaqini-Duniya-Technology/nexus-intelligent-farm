# First administration batch — verification

Scope: NEXUS-SEC-001, SEC-002, SEC-007 and SEC-008. Other phase items remain planned. The account pilot is preserved; full-workspace integration is not included in this release.

## Automated checks

- 479 workspace tests pass, including 10 dedicated administration tests plus existing account-pilot and deployment tests.
- 65 existing combined-workspace routes pass against an isolated temporary database.
- Node syntax checks pass for account_admin.js and account_pilot.js.
- Dedicated tests exercise owner/viewer continuity, password/session hash redaction, separate platform authority, account search/creation, role changes, revocation, disabling/re-enabling, last-owner/administrator protection, CSRF, denied admin HTTP calls, single-use/expired reset credentials, reset session invalidation, append-only audit enforcement, rollback if audit insertion fails, checked migration backup and v2→v3 account/session preservation.
- A restored pre-migration fixture is migrated again without losing its original farm record. No recovery exercise ran against actual user data.

## Browser checks

User-reported baseline: owner sign-in, farm retrieval, note persistence, sign-out/re-login and viewer read-only interface. New administration/recovery pages have service and real-HTTP tests and JavaScript syntax checks, but no real-browser acceptance pass is claimed. SEC-010 remains planned. Install locally and verify the administration Help, account creation, farm grants, viewer restrictions and recovery before wider use.

## Security findings resolved

No platform-administrator distinction or management dashboard at baseline: now explicit and denied to ordinary owners/viewers. No recovery: now operator-mediated, expiring, hash-only and single-use; successful reset revokes sessions. No account audit: now transactional append-only events, no credential values. No last-owner disable/remove guards: now protected with last-platform-administrator protection. No last-sign-in information: recorded on future successful logins. Empty farm list: now explains that an operator must assign a farm.

## Remaining limitations

Full Operations routes, exports and attachments are not yet account protected. Role coverage stays owner/editor/viewer; no manager/worker/adviser matrix yet. Recovery identity verification is performed by a privileged operator outside the software. The CLI and database require privileged local filesystem access. Private credential-file access on Windows requires appropriate folder ACLs. Email/SMS recovery, additional administrator delegation, hosted TLS/Secure cookies, full legacy schema conversion, audit retention/export and real-browser acceptance remain future work. Audit records do not establish a person's real identity and cannot prevent an operating-system database administrator replacing a file.

## Next batch

Progressively integrate authenticated account scope into the main workspace: farm/field records, observations and tasks first. Keep unsupported legacy routes unavailable in any authenticated shared entry point. Add direct API cross-farm and role-denial tests before enabling each section. Protect exports/attachments before shared hosting. No deployment or speech/chatbot expansion is included here.

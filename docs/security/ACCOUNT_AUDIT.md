# Account-pilot audit — 5 November 2026

Baseline: d353ab1af9d1556397877827843583cedd87c839 (review branch). No actual user database was provided. The user reported successful owner sign-in, note persistence, sign-out/re-login and a viewer interface with no note-entry form. These are user-reported browser checks, not an automated end-to-end browser run.

## Existing protections

The separate account_pilot loopback server uses salted PBKDF2 password verification, random hashed session tokens, eight-hour absolute and 30-minute idle expiry, username login-attempt limits, exact local Host/Origin checks and CSRF for note/logout writes. Farm memberships are rechecked by its scoped services. Viewer has no note writes; owner/editor have scoped note writes. All unrecognised legacy routes, exports and attachments are denied in that pilot. Existing automated service/HTTP tests cover those boundaries.

## Missing protections at baseline

- No platform administrator identity, account-management page, status workflow or account search.
- No password recovery or session invalidation through recovery.
- No account/security activity history or recorded last sign-in.
- No clear no-farm-assignment guidance.
- The full Operations workspace (normally 8080) is local single-user: Host/Origin checks there are not user authentication. Farm, field, observation, task, inspection, decision, resource, inventory, market, finance, attachment and export handlers are not covered by the pilot's account enforcement.
- Roles are owner/editor/viewer. Manager, worker and adviser permissions are not implemented. No qualifications are inferred from a role.
- The app has no configured recovery email/SMS delivery, production TLS/session configuration or shared-hosting acceptance.

## First-batch design

Migration 3 adds a separate platform-administrator association, last-sign-in column, hashed single-use reset records and append-only security history. Released migrations 1 and 2 stay unchanged. Existing accounts receive no automatic platform authority. A privileged local operator bootstraps the first administrator; farm owner status alone cannot manage accounts.

Administration is authenticated and CSRF protected. The last enabled owner of any assigned farm cannot be removed/demoted/disabled; the last enabled platform administrator cannot be disabled. Status disabling invalidates sessions and reset credentials. Role removal takes effect on the next protected request. Admin authority grants account administration, not automatic membership or farm-record access in the pilot.

Recovery is operator-mediated: an independently performed identity check is required by the CLI workflow; software does not verify identity automatically. A 256-bit random credential is written once to a private local file, stored only as a hash, expires in 15 minutes and cannot be reused. Successful redemption replaces the password and invalidates all previous account sessions. No reset credential is returned by general admin APIs, stored in audit summaries or placed in a URL. The local CLI/database file remains a privileged operating-system boundary, not a remote account API.

## Deferred boundaries

This batch does not secure the full legacy workspace. It preserves the separate pilot and denies unsupported routes there. Main-workspace integration must proceed section by section with positive and cross-farm negative tests before exposing it to shared users. Browser automation and full legacy migration conversion remain separate tracker items. No public/shared deployment or speech/chatbot work is included.

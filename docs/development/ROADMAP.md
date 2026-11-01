# NEXUS development roadmap: 150 upgrades

150 future upgrades from baseline e5eccd442eeada29769f304f4d025946c1fafe20; earlier delivered capabilities are not counted again.

Requested A–I quotas total 140. J adds 10 explicit cross-cutting validation/release items to reach 150.

First batch: 18 implemented IDs. Tested means recorded acceptance evidence; In Progress does not claim all browser/platform checks passed. Planned/Blocked entries are not implemented features. Full purpose, benefit, requirements, criteria and tests are in [roadmap.json](roadmap.json).

| ID | Feature | Priority | Phase | Status | Dependencies | Verification / guide | Git reference |
|---|---|---|---|---|---|---|---|
| NEXUS-UPG-001 | Strict JSON object parsing | Critical | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-002 | Bounded request framing | Critical | 1 — Audit and reliability | Tested | NEXUS-UPG-001 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-003 | UTF-8 JSON media contracts | Critical | 1 — Audit and reliability | Tested | NEXUS-UPG-001 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-004 | Request-body timeouts | Critical | 1 — Audit and reliability | Tested | NEXUS-UPG-001 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-005 | Validated resource pagination | High | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-006 | Saved resource domain checks | Critical | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-007 | Composable route registry | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-008 | Schema migration registry | High | 2 — Access and platform foundations | In Progress | None | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-009 | Transaction service boundaries | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-010 | Typed API error catalogue | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-011 | Resource payload migration policy | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-012 | Bounded SQLite contention recovery | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-013 | Query-plan and index review | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-014 | Explicit data-directory configuration | High | 2 — Access and platform foundations | In Progress | None | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-015 | Separate dependency profiles | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-016 | Verified knowledge source register | Medium | 3 — Evidence and operational integration | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-017 | Claim-level source references | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-018 | Knowledge provenance and usage gate | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-019 | Versioned knowledge captures | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-020 | Rule version manifest | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-021 | Applicability-gated knowledge cards | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-022 | Water context review | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-023 | Cross-record symptom assertion review | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-024 | Reviewed pest-scouting protocol library | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-025 | Soil sampling depth and spatial alignment | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-026 | Weather relevance checks | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-027 | Rainfall window and units checks | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-028 | Explicit abstention outputs | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-029 | Source-only retrieval baseline | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-030 | Knowledge-card evidence explanations | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-031 | Agricultural rule evaluation fixtures | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-032 | Dataset card registry | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-016 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-033 | Leakage and field-split checks | Medium | 3 — Evidence and operational integration | Blocked | NEXUS-UPG-032 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-034 | Disabled-by-default model adapter | Future | 3 — Evidence and operational integration | Blocked | NEXUS-UPG-032 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-035 | Offline model monitoring harness | Future | 3 — Evidence and operational integration | Blocked | NEXUS-UPG-032 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-036 | Season-scoped cultivation plans | High | 3 — Evidence and operational integration | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-037 | Actual planting event records | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-038 | Input application reports | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-039 | Irrigation activity evidence | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-040 | Worker capacity planning | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-041 | Equipment usage-hour logs | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-042 | Field-area measurement reconciliation | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-043 | Inspection route planning | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-044 | Adviser consultation tracking | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-045 | Evidence attachment registry | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-046 | Attachment integrity checks | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-047 | Recurring follow-up templates | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-048 | Authenticated work assignments | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-094 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-049 | Explicit task/work-order/decision links | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-050 | Field context age visibility | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-051 | Append-only harvest weighing corrections | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-052 | Reusable sampling-protocol templates | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-053 | Multi-location inventory count sessions | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-054 | Cross-module chronology review | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-055 | Farm handover report | High | 3 — Evidence and operational integration | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-056 | Market-to-core quantity preview | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-057 | Market-to-Finance reconciliation preview | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-058 | Complete order evidence captures | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-059 | Versioned offer-sheet captures | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-060 | Order terms amendment workflow | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-061 | Packaging quantity records | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-062 | Evidence-supported unit conversions | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-063 | Produce storage condition history | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-064 | Buyer acknowledgement evidence | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-065 | Buyer fulfilment summaries | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-066 | Market price reference notes | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-067 | Produce cost allocation scope | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-068 | Export redaction preview | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-069 | Cooperative lot provenance | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-094 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-070 | Market end-to-end acceptance fixture | Medium | 3 — Evidence and operational integration | Planned | NEXUS-UPG-009 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-071 | Compact Help Centre index | High | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-072 | Preserve valid form references | High | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-073 | Unsaved form change protection | High | 1 — Audit and reliability | In Progress | NEXUS-UPG-072 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-074 | Ignore stale refresh responses | High | 1 — Audit and reliability | In Progress | NEXUS-UPG-072 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-075 | Resource and market page controls | High | 1 — Audit and reliability | Tested | NEXUS-UPG-005 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-076 | Role-aware workspace start | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-093 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-077 | Accessible labels audit | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-078 | Mobile workflow acceptance | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-079 | Consistent navigation landmarks | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-080 | Print readability checks | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-081 | Keyboard acceptance suite | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-082 | Deferred Help payload loading | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-083 | Active filter chips and reset | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-084 | First-record onboarding | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-085 | Date and number display consistency | Medium | 4 — Usability, guidance and adoption | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-086 | Same-origin writes across combined routes | Critical | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-087 | Reject ambiguous body encodings | Critical | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-088 | Safe request diagnostics | High | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-089 | Local account password storage | Critical | 2 — Access and platform foundations | In Progress | NEXUS-UPG-014 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-090 | First-owner bootstrap | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-089 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-091 | Secure account sessions | Critical | 2 — Access and platform foundations | In Progress | NEXUS-UPG-089 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-092 | Session-bound CSRF protection | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-089 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-093 | Role permission matrix | Critical | 2 — Access and platform foundations | In Progress | NEXUS-UPG-089 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-094 | Farm membership scoping | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-091, NEXUS-UPG-093 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-095 | Object-level authorization | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-091, NEXUS-UPG-093 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-096 | Session revocation and logout | High | 2 — Access and platform foundations | Planned | NEXUS-UPG-089 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-097 | Authentication abuse limits | High | 2 — Access and platform foundations | Planned | NEXUS-UPG-089 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-098 | Authenticated actor audit trail | High | 2 — Access and platform foundations | Planned | NEXUS-UPG-091, NEXUS-UPG-093 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-099 | Scoped export permissions | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-091, NEXUS-UPG-093 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-100 | Public-deployment security gate | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-089 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-101 | Cross-platform workspace CI | High | 1 — Audit and reliability | Tested | None | GitHub Actions 41297994634: all four platform jobs passed; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-102 | Data-minimising readiness endpoint | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-103 | Pre-migration backup gate | Critical | 2 — Access and platform foundations | In Progress | NEXUS-UPG-008, NEXUS-UPG-104 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-104 | Operator recovery rehearsal reports | Critical | 2 — Access and platform foundations | Planned | NEXUS-UPG-008 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-105 | Container data-volume recipe | Future | 2 — Access and platform foundations | Planned | NEXUS-UPG-100, NEXUS-UPG-104 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-106 | GitHub Actions runtime maintenance | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-107 | Privacy-aware operational metrics | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-108 | Startup diagnostics | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-109 | Dependency inventory and SBOM | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-110 | Release manifest CI verification | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-111 | Required release quality gates | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-112 | Migration recovery rehearsal | High | 2 — Access and platform foundations | In Progress | NEXUS-UPG-008, NEXUS-UPG-103 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-113 | Infrastructure cost worksheet | High | 2 — Access and platform foundations | Planned | None | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-114 | TLS and private access deployment recipe | Future | 2 — Access and platform foundations | Planned | NEXUS-UPG-100, NEXUS-UPG-104 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-115 | Production readiness assessment | High | 2 — Access and platform foundations | Planned | NEXUS-UPG-100, NEXUS-UPG-104 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-116 | Reliability troubleshooting guide | High | 1 — Audit and reliability | Tested | NEXUS-UPG-001, NEXUS-UPG-071, NEXUS-UPG-075 | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-117 | Account administration guide | Medium | 4 — Usability, guidance and adoption | In Progress | NEXUS-UPG-091, NEXUS-UPG-093 | Foundation/pilot tests; docs/DEPLOYMENT_CONTROLS.md; full acceptance pending | Continuation review branch |
| NEXUS-UPG-118 | API contracts reference | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-119 | Cross-module save-effects matrix | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-120 | Season relevance FAQ | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-121 | Market money examples | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-122 | Nonprivate visual walkthroughs | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-123 | Plain-language content review | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-124 | Human-reviewed Hausa glossary | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-125 | Selector-to-form Help binding validation | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-126 | Documented example-to-fixture links | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-127 | Guide revision history | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-128 | Offline help package | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-129 | Backup and recovery walkthrough | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-130 | Developer setup profiles | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-015, NEXUS-UPG-116 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-131 | Pilot intake records | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-132 | Early-user feedback triage | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-133 | Observed usability study checklist | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-134 | Deterministic demonstration workspace | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-135 | Publishable capability catalogue | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-136 | YD Tech brand usage guide | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-137 | Cooperative discovery records | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-138 | Pricing validation experiments | Future | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-139 | Partnership request templates | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-140 | Investor evidence pack | Medium | 4 — Usability, guidance and adoption | Planned | NEXUS-UPG-142 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-141 | Permanent 150-upgrade tracker | High | 1 — Audit and reliability | Tested | None | docs/development/VERIFICATION.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-142 | Reproducible technical audit baseline | High | 1 — Audit and reliability | Tested | None | docs/development/AUDIT-2026-11-01.md; docs/development/VERIFICATION.md, docs/RELIABILITY_GUIDE.md | 1cd8563515fa0a1b0888866a8178eaf78e93938b |
| NEXUS-UPG-143 | Acceptance-evidence links | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-144 | Phase release checklist | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-145 | Historical compatibility fixtures | High | Continuous release governance | Planned | NEXUS-UPG-011 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-146 | Risk-to-negative-test coverage map | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-147 | Privacy scope review | High | Continuous release governance | Planned | NEXUS-UPG-068 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-148 | Versioned release provenance index | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-149 | Pilot outcome evidence gate | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |
| NEXUS-UPG-150 | Future opportunity register | High | Continuous release governance | Planned | NEXUS-UPG-141 | Acceptance pending; docs/development/ROADMAP.md | Not implemented |

## Validate and inspect

```bash
python -m nexus.farm_app.development_tracker
python -m nexus.farm_app.development_tracker --status Tested --details
python -m nexus.farm_app.development_tracker --workstream F --details
python -m nexus.farm_app.smoke_workspace
```

Tracker commands do not open a farm database. The route smoke command starts an isolated temporary database/server and removes it. Summary counts always cover all 150 entries; filters affect detailed listings only. See [audit](AUDIT-2026-11-01.md), [verification](VERIFICATION.md) and [review branch PR](https://github.com/Yaqini-Duniya-Technology/nexus-intelligent-farm/pull/1).

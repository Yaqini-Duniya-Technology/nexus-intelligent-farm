# NEXUS — MVP PRODUCT BRIEF

## Local farm workspace — November 2026

The repository now also includes a **single-user local pilot workspace** for field records, human reviews, resource planning and Produce & Market records. This track is separate from the simulation's autonomous action loop: it does not diagnose crops, control equipment, transfer money or contact buyers.

```bash
python -m nexus.farm_app.operations --port 8080 --database nexus-farm.sqlite3
```

Open [Operations](http://127.0.0.1:8080/workbench), [Produce & Market](http://127.0.0.1:8080/market), or [Help Centre](http://127.0.0.1:8080/help-centre). The local workspace uses Python's standard library; the simulation has separate dependencies.

- [150-upgrade roadmap and current audit](docs/development/ROADMAP.md)
- [Safe saving and troubleshooting](docs/RELIABILITY_GUIDE.md)
- [Local workspace setup, data boundaries and testing](docs/FARM_WORKSPACE.md)
- [Produce & Market release: 50 capabilities](docs/releases/produce-market-2026-11-01.md)
- 90 workflow guides with field explanations and fictional examples.
- 454 farm-workspace tests passed in the first reliability batch; simulation results below are a separate historical baseline.
- No databases, audio, exports or model weights are included. Speech/chatbot expansion remains deferred.

Built by [Yaqini & Duniya Technology](https://yd.ydtech.workers.dev).

---


[![NEXUS Python tests](https://github.com/Yaqini-Duniya-Technology/nexus-intelligent-farm/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/Yaqini-Duniya-Technology/nexus-intelligent-farm/actions/workflows/ci.yml)


## Architecture and engineering evidence

- **[System architecture and validation boundaries](docs/ARCHITECTURE.md)** — decision flow, execution verification, experience memory and reproducibility.
- **[Reproducible MVP demonstration](#mvp-demonstration)** — documented 720-step simulation using seed 101.
- **[Reported MVP results](#validated-mvp-results)** — simulation metrics, not field outcomes.


## Product

**NEXUS — Intelligent Farm Decision & Autonomous Management System**

NEXUS is an AI-driven farm intelligence and autonomous management platform designed to help farms move from fragmented observations and manual decisions toward a continuous decision-and-execution loop.

## Core Product Loop

```text
Sense
  ↓
Understand
  ↓
Predict
  ↓
Reason
  ↓
Decide
  ↓
Recommend
  ↓
Act
  ↓
Observe
  ↓
Learn
```

## Core Problem

Farm operations require repeated decisions across planting, watering, harvesting, resource allocation, risk management, timing, and operational execution.

These decisions are often disconnected:

- farm state is observed separately from planning;
- predictions do not always become operational decisions;
- decisions are not always connected to execution;
- execution outcomes are rarely converted into structured historical evidence;
- historical experience is difficult to reuse systematically.

NEXUS is designed to close this loop.

## What Makes NEXUS Different

NEXUS is not positioned as only a crop-prediction model.

Its architecture connects:

```text
Farm State
    +
Risk / Prediction Intelligence
    ↓
Decision Engine
    ↓
Execution Intent
    ↓
Spatial Planning
    ↓
Environment Action
    ↓
Outcome Evaluation
    ↓
Experience Memory
    ↓
Historical Evidence
```

This creates a pathway toward an adaptive farm operating system rather than an isolated prediction tool.

## Current MVP

The current MVP is validated inside the Kaggriculture simulation environment.

The system can:

- construct farm state;
- evaluate structured crop risks;
- generate and score candidate decisions;
- select strategic actions;
- create persistent spatial execution intents;
- select execution targets;
- navigate toward targets;
- execute actions;
- evaluate outcomes;
- construct and store historical experiences;
- retrieve contextually similar experiences;
- summarize historical evidence;
- interpret historical outcome patterns.

Historical evidence currently remains descriptive and does not modify the live decision score.

## Validated MVP Results

A reproducible 720-step episode using seed 101 produced:

| Metric | Result |
|---|---:|
| Steps requested | 720 |
| Decisions recorded | 719 |
| Experiences recorded | 719 |
| MATCHED | 374 |
| PARTIAL | 318 |
| NOT_MATCHED | 10 |
| UNKNOWN | 0 |
| Harvest decisions | 249 |
| Successful harvests | 82 |
| Verified target crops | 82 |
| Matched harvests | 82 |
| Harvested units | 82 |
| Records interpreted | 409 |
| Records with historical retrieval | 403 |

Automated regression baseline:

**324 tests passed**

## Decision Safety / Architectural Boundary

A runtime invariance probe was performed with an intentionally extreme historical experience carrying a decision score of 999999.0.

The current decision remained unchanged:

```text
Decision: PLANT_WHEAT
Action:   ['PLANT', 'WHEAT']
Score:    8.0
```

Result:

```text
Decision unchanged: PASS
Action unchanged:   PASS
History retrieved:  PASS
OVERALL:             PASS
```

This confirms that the current historical-intelligence layer is descriptive rather than a hidden policy modifier.

## Autonomous Harvest Validation

NEXUS supports persistent spatial execution intents for operations such as harvesting.

During the validated 720-step episode:

```text
Harvest decisions:      249
Successful harvests:     82
Verified target crops:   82
Matched harvests:        82
Harvested units:         82
```

A successful harvest requires actual target-level evidence:

- the intended target crop existed;
- the target crop was removed;
- harvested product was recorded;
- harvested units increased.

Movement toward a target is not incorrectly classified as a successful harvest.

## Target Users

Initial target users include:

1. Small and medium-scale farmers.
2. Commercial farms.
3. Agricultural extension and farm-management organisations.
4. Agri-tech operators managing multiple farms.
5. Agricultural research and innovation programmes.

## Initial Nigerian Use Case

NEXUS is intended for Nigerian farming environments where fragmented information, limited technical support, operational uncertainty, and resource constraints make timely farm decisions difficult.

The long-term opportunity is to combine:

- local farm observations;
- weather intelligence;
- crop risk;
- market intelligence;
- farm resources;
- historical farm experiences;
- operational planning.

## Long-Term Product

The MVP is the foundation for a broader farm intelligence platform:

```text
Farm Data
   +
External Intelligence
   +
Historical Experience
        ↓
Decision Intelligence
        ↓
Farm Recommendations
        ↓
Operational Automation
```

Future interfaces may include dashboards, mobile workflows, SMS/USSD integrations, WhatsApp workflows, and integrations with field sensors and farm-management systems.

## Commercialisation Direction

Potential future business models include:

- subscription software for farms;
- farm-management SaaS;
- enterprise deployment for agricultural organisations;
- agricultural intelligence services;
- API and integration services;
- institutional deployments.

The exact commercial model will be validated during real-farm pilots rather than assumed from the simulation MVP.

## Current Product Stage

NEXUS should be described accurately as:

**A simulation-validated technical MVP with a working autonomous decision-and-execution loop and structured historical intelligence.**

The MVP does not yet claim:

- commercial-scale deployment;
- large-scale user traction;
- production agronomic recommendations;
- autonomous physical robotics;
- revenue validation;
- a learned reinforcement-learning policy.

## Roadmap

### Phase 1 — MVP

Validated simulation-based autonomous decision and execution loop.

### Phase 2 — Real-Farm Validation

Connect NEXUS to structured observations from real farms and validate:

- state representation;
- recommendations;
- operational feasibility;
- farmer feedback;
- outcome tracking.

### Phase 3 — Evidence-Informed Decisions

Develop stronger recommendations from historical evidence while maintaining explicit policy boundaries and auditability.

### Phase 4 — Adaptive Farm Intelligence

Investigate adaptive policies using validated historical outcomes and farm-specific context.

### Phase 5 — Autonomous Farm Operations

Extend toward external farm integrations, field systems, sensors, and operational automation.

## September 30 MVP Definition of Done

- [x] Autonomous decision loop
- [x] Spatial execution intents
- [x] Target-level harvest validation
- [x] Experience memory
- [x] Contextual retrieval
- [x] Historical evidence interpretation
- [x] Decision invariance validation
- [x] 720-step reproducible demonstration
- [x] 324-test regression baseline
- [ ] Repository packaging finalized
- [ ] Application materials finalized
- [ ] Real-farm validation documented where available

## MVP Demonstration

Run:

```bash
python demo.py
```

The demonstration executes a reproducible 720-step episode using seed 101 and reports:

- decision count;
- experience count;
- experience quality;
- autonomous harvest evidence;
- historical retrieval;
- evidence interpretation;
- MVP validation checks.

## Product Vision

NEXUS aims to become an intelligent operating layer for agriculture:

**not merely predicting what may happen, but helping farms decide what to do next, execute the decision, observe the result, and systematically learn from experience.**

---

## Engineering case study | Recruiter overview

### NEXUS: Autonomous Agricultural Intelligence

**Project status:** Simulation-validated technical MVP; real-farm validation pending

**Why I built / am building it:** Farm operators need a connected process for observing conditions, selecting actions, executing them and learning from results.

**Who it is for:** Farmers, farm managers, agricultural extension teams and agri-tech partners.

**Development and engineering process:** Problem framing → autonomous decision-loop design → spatial action intents → simulated execution → outcome verification → experience storage and retrieval → reproducible regression testing.

**Demonstrated progress and evidence:** A documented 720-step simulation recorded 719 decisions and 719 experiences, with 82 successful harvests; the repository reports a 324-test regression baseline. These are simulation results, not field performance.

**What I plan to achieve:** Real-farm pilots, expert review, integration with farm observations and gradual evidence-informed operational automation.

**What this work demonstrates to a hiring team:** The ability to connect a real user problem to a technical plan, implement and evaluate a solution, document limitations honestly, and prioritize the next engineering milestones.

**[Source repository](https://github.com/Yaqini-Duniya-Technology/nexus-intelligent-farm)** · No public MVP URL confirmed for this repository.


**Developer:** Inda Obanyi · AI/ML Engineer & Software Developer · Founder, Yaqini & Duniya Technology  
**[Portfolio](https://indaobanyi.vercel.app)** · **[LinkedIn](https://www.linkedin.com/in/inda-obanyi-8886553a6/)** · **[GitHub](https://github.com/Inda-Obanyi)**


Storage and account foundations: [deployment controls guide](docs/DEPLOYMENT_CONTROLS.md). The separate narrow account pilot enforces its own farm scope; grants do not yet protect the full Operations workspace; shared hosting remains deferred.

Account administration and recovery: [operator guide](docs/security/ACCOUNT_GUIDE.md), [account audit](docs/security/ACCOUNT_AUDIT.md), and [15-item phase tracker](docs/security/phase-tracker.json). Farm ownership does not automatically grant platform administration.

Protected core workspace integration: [authenticated launcher and permission guide](docs/security/AUTHENTICATED_CORE.md). Start with `python -m nexus.farm_app.operations --authenticated --database nexus-farm.sqlite3 --port 8080`. Unsupported legacy sections remain unavailable in that mode; default Operations remains local single-user. No shared hosting readiness is claimed.

### Baseline and protected inspections

See [batch 1 evidence and local acceptance guide](docs/development/BATCH-01.md) and [150-item status register](docs/development/master-upgrades.json). New authenticated inspection routes reuse existing append-only validation. Keep local. See [inspection reliability and demo verification](docs/development/INSPECTION-RELIABILITY.md) for the newer draft and retry workflow.

[Mobile inspection history and isolated recovery drill](docs/development/INSPECTION-HISTORY-RECOVERY.md)

[Protected crop seasons and observation context](docs/development/PROTECTED-CROP-SEASONS.md)

# Job Agent — System Architecture

## 1. High-Level Architecture Overview

Job Agent is a hybrid deterministic-agentic system designed for continuous, resilient job discovery, evaluation, resume tailoring, automated browser application, and application tracking.

There are two ways a job enters the system. The scheduled discovery engine sweeps
job boards on its own, and the human-in-the-loop loop described in
[ROLE_DISCOVERY.md](ROLE_DISCOVERY.md) lets the user import jobs they picked out
themselves from searches the RoleDiscoveryAgent recommended. Both converge on the
same normalizer, deduplicator and match engine.

```mermaid
flowchart TD
    subgraph RoleDiscovery ["0. Role Discovery (what to search for)"]
        CV[Master CV in Reactive Resume] --> CG[CandidateCapabilityGraph]
        PROFILE[Candidate profile] --> CG
        CG --> RM[RoleMap: primary / secondary / stretch / avoid]
        RM --> SQ[(Search queries per provider)]
        SQ --> EXT[Browser extension: Search Inbox]
        EXT --> HUMAN[Human browses and clicks Import]
        HUMAN --> IMPORT[BrowserImportService]
        IMPORT --> NORM
        SQ --> JD
    end

    subgraph Discovery ["1. Job Discovery Engine"]
        GH[Greenhouse API] --> JD[JobDiscoveryWorker]
        LEV[Lever API] --> JD
        ASH[Ashby API] --> JD
        CC[Company Feeds] --> JD
        WEB[Generic Web / JSON-LD] --> JD
        JD --> NORM[JobNormalizer & Deduplicator]
    end

    subgraph Evaluation ["2. Evaluation & Decision"]
        NORM --> CANON[(CanonicalJob DB)]
        CANON --> ME[MatchEngine / JobAnalysisAgent]
        PROF[(CandidateProfile & Vault)] --> ME
        ME --> SCORE{Score >= Threshold?}
    end

    subgraph Preparation ["3. Resume & Document Prep"]
        SCORE -- No --> IGNORE[Mark IGNORED]
        SCORE -- Yes --> RR_APP[Reactive Resume: Create Application]
        RR_APP --> TAILOR[ResumeAgent: Tailor Resume]
        PROF --> TAILOR
        TAILOR --> QA[Hallucination Guard & ATS Check]
        QA --> PDF[Reactive Resume: Export PDF]
        PDF --> ATTACH[Attach PDF to Application]
        ATTACH --> CL[Generate Cover Letter & Answers]
    end

    subgraph Execution ["4. Browser Execution & Submission"]
        CL --> PREFLIGHT[ApplicationPreflight]
        PREFLIGHT --> BROWSER[BrowserApplicationAgent / Playwright]
        BROWSER --> ADAPTERS{ATS Adapter}
        ADAPTERS --> GHA[GreenhouseAdapter]
        ADAPTERS --> LEVA[LeverAdapter]
        ADAPTERS --> ASHA[AshbyAdapter]
        ADAPTERS --> GENA[GenericApplicationAdapter]
        ADAPTERS --> CAPTCHA{CAPTCHA / 2FA?}
        CAPTCHA -- Yes --> BLOCKED[Mark BLOCKED & Alert]
        CAPTCHA -- No --> FILL[Fill Form & Upload PDF]
        FILL --> SUBMIT[Submit Form]
        SUBMIT --> VERIFY[Verify Confirmation Evidence]
    end

    subgraph Tracking ["5. Tracking & Observability"]
        VERIFY --> RR_UPDATE[Reactive Resume: Update Status APPLIED]
        RR_UPDATE --> TG[TelegramNotifier: Send Submission Card]
        VERIFY --> EV[(Audit Evidence & DB State)]
        RR_UPDATE --> MON[ApplicationMonitor: Scheduled Follow-up]
    end

    subgraph Learning ["6. Market Feedback"]
        CANON --> FB[Search performance per query]
        FB --> RM
        CANON --> NEWROLE[Roles discovered from imported jobs]
        NEWROLE --> RM
    end
```

---

## 2. Core Philosophy: LLM Reasoning vs Deterministic Engineering

A fundamental principle of Job Agent is strict separation of concerns:

| Domain | Responsibility | Handled By |
|---|---|---|
| **Semantic Understanding** | Parsing complex job requirements, assessing nuances of candidate experience, contextual bullet point prioritization, drafting natural responses, reasoning through unknown form fields. | **LLM (JobAnalysisAgent, ResumeAgent, BrowserAgent)** |
| **Integrity & Guardrails** | Preventing hallucination of non-existent employers, skills, dates, degrees, metrics, or credentials. | **Deterministic Code (HallucinationGuard, Profile Validator)** |
| **Form Interaction** | Locating form inputs via accessibility trees, selecting dropdowns, uploading files, waiting for DOM transitions. | **Deterministic Code (Playwright Locators & Adapters)** |
| **System Operations** | API calls, database transactions, idempotency locks, retries, rate limits, file I/O, Telegram transport, Celery queues. | **Deterministic Code (FastAPI, SQLAlchemy, Celery, httpx)** |

---

## 3. Directory Layout & Monorepo Structure

```text
JobAgent/
├── apps/
│   ├── api/                     # FastAPI backend (REST endpoints, webhooks)
│   │   ├── main.py
│   │   ├── routes/
│   │   │   ├── jobs.py
│   │   │   ├── applications.py
│   │   │   ├── answers.py
│   │   │   ├── system.py
│   │   │   └── webhooks.py
│   │   └── dependencies.py
│   ├── worker/                  # Celery application & task declarations
│   │   ├── celery_app.py
│   │   ├── tasks/
│   │   │   ├── discovery.py
│   │   │   ├── analysis.py
│   │   │   ├── tailoring.py
│   │   │   ├── browser.py
│   │   │   ├── monitor.py
│   │   │   └── telegram.py
│   │   └── beat_schedule.py
│   └── web/                     # React + TypeScript Vite frontend
│       ├── src/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── services/
│       │   └── types/
│       ├── package.json
│       └── vite.config.ts
├── packages/
│   ├── domain/                  # Core domain models, enums, interfaces
│   │   ├── models.py
│   │   ├── enums.py
│   │   └── state_machine.py
│   ├── reactive_resume/         # Typed client for Reactive Resume v5 REST & MCP
│   │   ├── client.py
│   │   ├── models.py
│   │   └── patch_builder.py
│   ├── candidate_profile/       # Profile loader, AnswerVault & anti-hallucination guard
│   │   ├── profile.py
│   │   ├── answer_vault.py
│   │   └── guard.py
│   ├── job_sources/             # Extensible job discovery adapters
│   │   ├── base.py
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── company_careers.py
│   │   └── feeds.py
│   ├── llm/                     # Multi-provider LLM abstraction
│   │   ├── base.py
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   ├── gemini_provider.py
│   │   └── gateway.py
│   ├── browser/                 # Playwright automation engine
│   │   ├── session.py
│   │   ├── locators.py
│   │   └── forms.py
│   ├── application_adapters/    # ATS-specific form handlers
│   │   ├── base.py
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── workday.py
│   │   └── generic.py
│   ├── preflight/               # 12-point pre-submit verification
│   │   ├── checker.py
│   │   └── rules.py
│   ├── telegram/                # Telegram bot & interactive handlers
│   │   ├── bot.py
│   │   ├── notifications.py
│   │   └── handlers.py
│   └── persistence/             # PostgreSQL database layer
│       ├── database.py
│       ├── models.py
│       └── repositories.py
├── config/
│   ├── candidate-profile.yaml   # Master candidate configuration
│   └── settings.py              # Pydantic base settings
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   ├── Dockerfile.web
│   └── docker-compose.yml
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── ARCHITECTURE.md
├── IMPLEMENTATION_PLAN.md
├── REACTIVE_RESUME_INTEGRATION.md
├── APPLICATION_STATE_MACHINE.md
└── SECURITY.md
```

---

## 4. Key Subsystem Interactions

### A. CandidateAnswerVault
- Form questions repeatedly ask for sponsorship, work authorization, notice periods, salary expectations, and technology tenure.
- The `CandidateAnswerVault` acts as an auditable, persistent memory store for normalized canonical questions.
- If a question cannot be resolved with high confidence (>= 0.95) from existing verified answers or deterministic profile attributes, the application enters `NEEDS_USER_INPUT` and alerts the user via Telegram with inline quick-reply buttons.

### B. Preflight & Idempotency Protection
- Before invoking the final `submit` action in Playwright, `ApplicationPreflight` runs synchronously.
- It computes a cryptographic fingerprint of `(company, role, applyUrl, candidate_email, date)`.
- If an active lock or completed application exists with this fingerprint, submission halts immediately to prevent double-applying.
- Full pre-submit DOM snapshots and screenshots are stored in `JobSnapshot` for complete post-incident auditability.

### C. Multi-Level Observability
- Every execution run receives a unique UUID `run_id`.
- Celery tasks propagate `correlation_id`, `job_id`, and `application_id` through structured JSON logs.
- Failures capture:
  - Error category (`NETWORK_ERROR`, `CAPTCHA`, `VALIDATION_ERROR`, etc.)
  - Full Playwright screenshot and DOM HTML
  - Request/response payloads
  - LLM input prompts and structured outputs

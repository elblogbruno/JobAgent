# Job Agent — Implementation Plan

This implementation plan defines the complete, phased roadmap for building **Job Agent**: a production-grade, maintainable autonomous job search and application platform.

---

## 1. Project Objectives & Definition of Done

### Objective
Provide an autonomous, continuous agent capable of:
1. Discovering job openings across multiple ATS and job boards (Greenhouse, Lever, Ashby, company career sites, web feeds).
2. Normalizing and semantically deduplicating jobs into canonical listings.
3. Evaluating jobs against the candidate's master profile using structured LLM reasoning (producing a 0–100 match score and rich fit metrics).
4. Managing job applications and tailored CVs in **Reactive Resume**.
5. Generating tailored, strictly non-hallucinated resumes and cover letters.
6. Executing browser automation via **Playwright** with specialized ATS adapters to fill and submit job applications.
7. Verifying application confirmation through multi-factor evidence.
8. Updating application tracking pipelines and notifying the candidate via an interactive **Telegram Bot**.
9. Monitoring post-submission status and follow-ups.

### Definition of Done (End-to-End MVP Milestone)
The system is considered done when the following live scenario executes without manual intervention:
1. An open job is discovered from an active ATS feed (e.g. Greenhouse / Lever / Ashby).
2. The agent scores it >= auto-apply threshold (or prepare threshold) against `CandidateProfile`.
3. The deduplication check confirms no prior application exists.
4. An `Application` record is created in Reactive Resume.
5. A tailored resume derived from the Master CV is created, validated against profile constraints, exported as PDF, and attached to the Reactive Resume application.
6. A custom, personalized cover letter is drafted.
7. Playwright opens the job application URL in a persistent browser context.
8. The appropriate ATS adapter fills all fields, resolves standard questions from `CandidateAnswerVault`, uploads the tailored PDF, and completes the form.
9. `ApplicationPreflight` validates all inputs and conditions immediately before submission.
10. The application is submitted, and confirmation is verified via DOM inspection.
11. Reactive Resume status is updated to `applied` with timeline entries and documents attached.
12. A formatted Telegram alert is sent to the candidate with full match details, gaps, and links.

---

## 2. Technical Stack Decisions

| Layer | Technology | Rationale |
|---|---|---|
| **Language & Runtime** | Python 3.11+ | Native async support, rich LLM ecosystem, mature Playwright & Celery support |
| **API Framework** | FastAPI | High-performance async REST framework, OpenAPI standard, typed Pydantic models |
| **Task Queue & Scheduler** | Celery + RabbitMQ + Celery Beat | Distributed async job execution, persistent queues, reliable retry mechanisms |
| **Database & ORM** | PostgreSQL 16 + SQLAlchemy 2.0 (asyncpg) + Alembic | Transactional integrity, JSONB support for rich snapshots and audit logs |
| **Browser Automation** | Playwright Python (Chromium) | Robust locator engine (accessibility tree, role, text), persistent contexts |
| **CV & Pipeline Tracker** | Reactive Resume v5 (REST API + MCP) | Open-source master CV repository, versioning, PDF rendering engine |
| **LLM Provider Abstraction** | Custom Multi-Provider Gateway | Agnostic support for OpenAI, Anthropic, Gemini, OpenRouter, and local Ollama |
| **Messaging & Interaction** | Telegram Bot API (python-telegram-bot) | Real-time push notifications and inline approval buttons for review mode |
| **Frontend Dashboard** | React 18 + TypeScript + Vite + Tailwind CSS | Clean operational dashboard for tracking runs, manual reviews, and metrics |

---

## 3. Phased Roadmap

### Phase 1 — Foundation & Core Infrastructure
- Repository layout (`apps/`, `packages/`, `docker/`).
- Docker Compose setup (PostgreSQL, RabbitMQ, API, Celery worker, Celery beat, Frontend).
- Database migrations with Alembic; domain models: `Job`, `JobSource`, `JobSnapshot`, `ApplicationRun`, `BrowserRun`, `AgentDecision`, `CandidateAnswer`.
- Configuration and secrets management via Pydantic Settings (`.env`).
- Structured logging with correlation IDs (`run_id`, `job_id`, `application_id`).

### Phase 2 — Reactive Resume Client & Contracts
- Fully typed client for Reactive Resume v5 API (`x-api-key` auth).
- Endpoints covered:
  - Resumes: list, get, duplicate, patch (RFC 6902), lock, versions, restore, PDF export.
  - Applications: list, create, update, delete, attach document (`resume`, `cover-letter`), timeline notes, stats.
  - Application AI: autofill, match score, draft message, tailor resume.
- Unit and integration tests with mocked Reactive Resume server responses.

### Phase 3 — Candidate Profile & Answer Vault
- `CandidateProfile` YAML parser and validator: identity, job preferences, locations, remote policies, salary floors, visa rules, forbidden fabrications.
- `CandidateAnswerVault`: canonical question resolver with fuzzy matching, confidence scores, user-confirmed memory, and unknown question flagging (`NEEDS_USER_INPUT`).
- Master resume synchronization between local profile and Reactive Resume master CV.

### Phase 4 — Job Discovery Engine
- Generic `JobSource` interface and query models.
- Specialized source implementations:
  - `AshbySource` (public API / board JSON)
  - `GreenhouseSource` (public boards API)
  - `LeverSource` (postings API)
  - `CompanyCareersSource` (structured feed / JSON-LD)
  - `GenericWebSource` (discovery fallback)
- Periodic scheduler integration via Celery Beat.

### Phase 5 — Normalization, Deduplication & Match Engine
- Canonical job normalizer: title normalization, location categorization (Remote EU, Hybrid BCN, etc.), salary parsing.
- Multi-factor deduplication: company name, normalized title, ATS job ID, canonical URL, text similarity hashing.
- Cross-check against Reactive Resume applications and local database.
- `JobAnalysisAgent`: LLM-based evaluation producing structured 0–100 match scorecard, recommendation (`APPLY`, `PREPARE`, `IGNORE`), strengths, gaps, and risks.

### Phase 6 — Resume Tailoring & Document Generation Pipeline
- `ResumeAgent`: derive job-specific resume from Master CV.
- Tailoring operations: summary adjustment, experience bullet reordering/emphasis, skill highlighting.
- Strict Hallucination Guard: verifies every tailored bullet, title, metric, and skill exists in the master CV or candidate profile.
- ATS layout check: section ordering, keyword optimization without keyword stuffing.
- Trigger Reactive Resume PDF generation and download.
- Generate personalized cover letter matching company tone and role requirements.
- Attach generated PDF documents to Reactive Resume application record.

### Phase 7 — Browser Automation Core
- `BrowserSessionManager`: persistent Chromium context, session storage, viewport, anti-fingerprinting defaults without deceptive bypasses.
- `BrowserApplicationAgent`: semantic locators (accessible role, label, placeholder, aria attributes), multi-step wizard handler.
- Defensive safety: CAPTCHA / 2FA / Login detection triggering immediate abort (`BLOCKED_CAPTCHA`), session preservation, and alerting.

### Phase 8 — ATS Adapters
- `ApplicationAdapter` interface: `can_handle`, `analyze_form`, `fill`, `validate`, `submit`.
- Implementations:
  - `GreenhouseAdapter`
  - `LeverAdapter`
  - `AshbyAdapter`
  - `WorkdayAdapter` (foundation)
  - `WorkableAdapter`
  - `SmartRecruitersAdapter`
  - `GenericApplicationAdapter` (LLM-guided semantic DOM fallback)
- File upload handling for PDF resumes and cover letters.

### Phase 9 — Submission Engine, Preflight & Verification
- `ApplicationPreflight`: 12-point pre-submit verification checklist.
- Pre-submit DOM snapshot and full form field audit.
- State machine transitions: `PREPARING` → `READY` → `APPLYING` → `SUBMITTED_UNVERIFIED` → `APPLIED`.
- Post-submit evidence collector: confirmation text, confirmation IDs, URL redirects, response status codes.
- Idempotency guards and duplicate submission locks.

### Phase 10 — Telegram Interactive Bot & Notifications
- Real-time formatted notification cards on application events.
- Telegram inline approval buttons for `REVIEW_BEFORE_SUBMIT` mode (`[APLICAR]`, `[VER CV]`, `[IGNORAR]`).
- Interactive slash commands: `/status`, `/today`, `/pending`, `/applied`, `/errors`.
- Webhook / polling handler with authorization checks (restricted to `TELEGRAM_CHAT_ID`).

### Phase 11 — Application Monitor & Follow-ups
- Background monitor checking application state changes and follow-up deadlines (`followUpAt`).
- Recruiter outreach drafter (polite follow-up email / LinkedIn message).
- Extensible interfaces for email inbox monitoring (Gmail API hooks).

### Phase 12 — Operational Dashboard & UI
- React frontend:
  - Metrics overview (Discovered, Scored, Prepared, Applied, Interviews, Blocked).
  - Job explorer with search, filters, and match breakdown modals.
  - Applications pipeline view synchronized with Reactive Resume.
  - Audit trail viewer: run logs, preflight checks, screenshots on failure.
  - Manual action center: answer pending questions, approve pending applications.
  - System configuration panel.

---

## 4. Verification & Testing Strategy

- **Unit Tests**: Domain logic, normalization regexes, answer vault fuzzy matching, preflight checklist, LLM response parsers.
- **Integration Tests**: Reactive Resume mock server testing all REST endpoints, Telegram mock client, PostgreSQL transaction tests.
- **Browser Automation Fixtures**: Local HTML fixtures simulating Greenhouse, Lever, Ashby, and multi-step forms with error states and file uploads.
- **End-to-End Test Suite**: Complete headless run against mock ATS endpoints ensuring zero live applications are triggered during test runs.

# Job Agent 🤖🚀

> An autonomous, maintainable paired agent for continuous job discovery, semantic match analysis, Reactive Resume integration, browser automation, and post-submission monitoring.

## Highlights

- **Deterministic & Agentic Synergy**: Deterministic resilience for APIs, persistence, browser locators, and security; LLMs for semantic reasoning, job parsing, tailoring, and question handling.
- **Reactive Resume Native**: Integrates with Reactive Resume v5 REST API and MCP. Uses the Master CV as an immutable source of truth and derives tailored job-specific CVs.
- **Multi-Source Job Discovery**: Seamless ingestion from Greenhouse, Lever, Ashby, company career feeds, and generic web postings.
- **Role Discovery**: Infers which roles the candidate should search for from their capabilities rather than their keywords, turns them into one-click searches, and learns from the jobs actually imported.
- **Zero Hallucination Guarantee**: Strict verification preventing the invention of employers, degrees, skills, metrics, dates, or personal data.
- **Defensive Browser Automation**: Uses Playwright with semantic accessibility locators, multi-step navigation, and automatic safe abort on CAPTCHA/2FA.
- **Candidate Answer Vault**: Auditable memory resolving repetitive application questions with confidence thresholds and user fallback.
- **Telegram Bot Control**: Push notifications with job match summaries and interactive inline approval buttons for `REVIEW_BEFORE_SUBMIT` mode.
- **Full-Stack Observability**: Structured JSON logging, preflight checks, submission fingerprints, and an operational React dashboard.

---

## Quickstart

### 1. Requirements
- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (for PostgreSQL and RabbitMQ)

### 2. Configuration
Copy the template environment file:
```bash
cp .env.example .env
```
Update `.env` with your API keys:
- `REACTIVE_RESUME_API_KEY`: API key generated from Reactive Resume. The master CV
  itself is chosen in the dashboard, under **Tus CVs**, and stored in
  `config/candidate-profile.yaml`.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`: Telegram bot credentials.
- `OPENAI_API_KEY` (or Anthropic/Gemini).

Customize your career preferences in `config/candidate-profile.yaml`.

### 3. Docker Services
Start the supporting services (PostgreSQL & RabbitMQ):
```bash
docker-compose -f docker/docker-compose.yml up -d db rabbitmq
```

To run the whole stack in containers instead, `up -d` without arguments also
builds the API, the worker and the dashboard. The dashboard image proxies `/api`
to the API service, so port 3000 is all you need to open.

### 4. Running the System Locally

Install dependencies:
```bash
pip install -e ".[dev]"
playwright install chromium
```

The commands below use `python -m` so they always run against the interpreter you
installed those dependencies into. On a machine with several Python installations,
a bare `uvicorn` or `celery` may resolve to a different one and fail with
`ModuleNotFoundError`.

Start the FastAPI backend:
```bash
python -m uvicorn apps.api.main:app --reload --port 8000
```

Database tables are created on startup, and additive column upgrades are applied
at the same time, so there is no separate migration step.

Start the Celery worker, in its own terminal:
```bash
# Linux and macOS
python -m celery -A apps.worker.celery_app worker -l info

# Windows: the prefork pool needs fork(), which does not exist there
python -m celery -A apps.worker.celery_app worker -l info --pool=solo
```

Start the beat scheduler, in another terminal. It drives the periodic discovery,
monitoring and role map refresh tasks:
```bash
python -m celery -A apps.worker.celery_app beat -l info
```

On Windows, `celery worker -B` is rejected: beat must run as its own process.

The worker is optional for browser imports. When the broker is unreachable, the API
analyses an imported job in an in-process background task instead.

Start the web dashboard on http://localhost:3000:
```bash
cd apps/web && npm install && npm run dev
```

### 5. Browser Extension

Build it once, then load it unpacked from `chrome://extensions` (Developer mode ->
Load unpacked -> `apps/browser-extension/dist`):
```bash
cd apps/browser-extension && npm install && npm run build
```

Pair it with the backend from the dashboard's **Role Discovery** page: create a
pairing token and paste it into the extension's options page. See
[apps/browser-extension/README.md](apps/browser-extension/README.md).

---

## Architecture Documentation

- [System Architecture](ARCHITECTURE.md)
- [Role Discovery & Browser Extension](ROLE_DISCOVERY.md)
- [Implementation Roadmap](IMPLEMENTATION_PLAN.md)
- [Reactive Resume Integration](REACTIVE_RESUME_INTEGRATION.md)
- [Application State Machine](APPLICATION_STATE_MACHINE.md)
- [Security & Privacy](SECURITY.md)

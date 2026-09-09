# Job Agent 🤖🚀

> An autonomous, maintainable paired agent for continuous job discovery, semantic match analysis, Reactive Resume integration, browser automation, and post-submission monitoring.

## Highlights

- **Deterministic & Agentic Synergy**: Deterministic resilience for APIs, persistence, browser locators, and security; LLMs for semantic reasoning, job parsing, tailoring, and question handling.
- **Reactive Resume Native**: Integrates with Reactive Resume v5 REST API and MCP. Uses the Master CV as an immutable source of truth and derives tailored job-specific CVs.
- **Multi-Source Job Discovery**: Seamless ingestion from Greenhouse, Lever, Ashby, company career feeds, and generic web postings.
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
- `REACTIVE_RESUME_API_KEY`: API key generated from Reactive Resume.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`: Telegram bot credentials.
- `OPENAI_API_KEY` (or Anthropic/Gemini).

Customize your career preferences in `config/candidate-profile.yaml`.

### 3. Docker Services
Start the supporting services (PostgreSQL & RabbitMQ):
```bash
docker-compose -f docker/docker-compose.yml up -d db rabbitmq
```

### 4. Running the System Locally

Install dependencies:
```bash
pip install -e ".[dev]"
playwright install chromium
```

Run database migrations:
```bash
alembic upgrade head
```

Start the FastAPI backend:
```bash
uvicorn apps.api.main:app --reload --port 8000
```

Start the Celery worker and beat scheduler:
```bash
celery -A apps.worker.celery_app worker -l info -B
```

Start the web dashboard:
```bash
cd apps/web && npm install && npm run dev
```

---

## Architecture Documentation

- [System Architecture](ARCHITECTURE.md)
- [Implementation Roadmap](IMPLEMENTATION_PLAN.md)
- [Reactive Resume Integration](REACTIVE_RESUME_INTEGRATION.md)
- [Application State Machine](APPLICATION_STATE_MACHINE.md)
- [Security & Privacy](SECURITY.md)

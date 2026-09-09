# Security, Privacy & Integrity Specification

## 1. Absolute Agent Rules

The following ten rules are non-negotiable architectural constraints enforced at every layer of Job Agent:

1. **Zero Professional Hallucination**:
   Never invent or fabricate past companies, dates of employment, job titles, educational degrees, certifications, technologies, years of experience, metrics, languages, project outcomes, previous salaries, or work authorization statuses. All claims must be derived directly from the Master CV and `CandidateProfile`.

2. **Zero Personal Data Guessing**:
   Never guess unknown personal identity questions (e.g. legal name spellings, passport numbers, tax IDs, precise disability disclosures, veteran statuses). If a question is not answerable from `CandidateProfile` or verified in `CandidateAnswerVault`, mark the run as `NEEDS_USER_INPUT` and alert the candidate.

3. **Strict Single Submission Guarantee**:
   Never submit multiple applications to the same job opening. All submissions require an idempotency lock computed from the canonical company, normalized job title, ATS job ID, and application URL.

4. **Document Isolation**:
   Never submit a resume tailored for a different company or job. Each application must strictly bind to a freshly derived and validated resume specific to that canonical job ID.

5. **Validation Integrity**:
   Never ignore or force past browser form validation errors. If an input field indicates an error or required field violation, halt submission and attempt semantic correction or user escalation.

6. **Evidence-Based Application Verification**:
   Never consider an application sent simply because a submit button was clicked in Playwright. Transition to `APPLIED` requires deterministic post-submit evidence (confirmation text, redirect URL, confirmation ID).

7. **No Anti-Bot Evasion / CAPTCHA Bypasses**:
   Never attempt to solve or circumvent CAPTCHAs, Cloudflare turnstiles, 2FA prompts, login firewalls, or rate limit headers. When detected, immediately transition to `BLOCKED_CAPTCHA` or `BLOCKED_2FA`, preserve the browser session, alert the user via Telegram, and gracefully continue other tasks.

8. **Master CV Immutability**:
   The Master CV in Reactive Resume is immutable for the automated agent. The agent may only read the Master CV and create isolated duplicate copies for tailoring.

9. **Atomic Consistency with Reactive Resume**:
   Never execute a browser submission without an active, synchronized `Application` entity in Reactive Resume. Document attachments and timeline events must reflect exact reality.

10. **Full Auditability**:
    Every automated decision, LLM evaluation, form field assignment, preflight check, and submission event must be persisted with timestamped audit evidence and run correlation IDs.

---

## 2. Secrets Management & Environment Security

All sensitive credentials must be provided exclusively via environment variables or a secure `.env` file that is strictly ignored by version control.

### Required Environment Variables
| Variable | Description | Protection Level |
|---|---|---|
| `REACTIVE_RESUME_API_KEY` | API key for Reactive Resume REST API & MCP | High (Redacted in logs) |
| `REACTIVE_RESUME_BASE_URL` | Base URL for Reactive Resume API | Standard |
| `TELEGRAM_BOT_TOKEN` | Bot API token for push notifications & commands | Critical (Redacted in logs) |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for notifications & authorization | Standard |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | LLM provider API credentials | Critical (Redacted in logs) |
| `DATABASE_URL` | PostgreSQL connection string | Critical |
| `RABBITMQ_URL` | RabbitMQ connection string | Standard |
| `SECRET_KEY` | App encryption key for sensitive local data | Critical |

### Log Sanitization
Structured logging middleware automatically filters and redacts known secret patterns:
- Regex redaction for `x-api-key`, `Authorization: Bearer`, `bot<token>`, and connection passwords.
- No sensitive personal contact information is output in plaintext debug logs.
- Preflight screenshots taken by Playwright are stored locally in a secure, non-public artifacts directory.

---

## 3. Safe Browser Automation Standards

- **Browser Context**: Chromium running with persistent user data directories to preserve legitimate login cookies where explicitly configured.
- **Natural Interaction Speeds**: Human-like typing delays (30–90ms per keystroke) and viewport scrolling to prevent accidental denial-of-service on ATS career portals.
- **Defensive Termination**:
  - Maximum timeout of 30 seconds per form action.
  - Abort on detection of reCAPTCHA / hCaptcha / Cloudflare Challenge:
    ```python
    if await page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], #challenge-running").count() > 0:
        raise CaptchaBlockedException("Anti-bot verification encountered.")
    ```

---

## 4. Telegram Authorization & Access Control

- The Telegram bot endpoint inspects incoming message `message.chat.id` against `TELEGRAM_CHAT_ID`.
- Any commands or callback button presses received from unauthorized chat IDs are immediately discarded and logged as security warnings.

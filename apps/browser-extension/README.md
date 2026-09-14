# Job Agent browser extension

A Manifest V3 extension that puts your role map in the browser: the searches the
agent recommends are one click away, and any job worth applying to is one click
from being imported, parsed, scored and prepared.

The extension is deliberately **human-triggered**. It does not crawl, scroll,
bulk-extract or open pages on its own. The AI decides what is worth searching
for, you decide which result is interesting, and the extension makes importing
it almost frictionless.

## Build

```bash
cd apps/browser-extension
npm install
npm run build      # or: npm run watch
npm test           # pattern tests, via Node's own runner
```

The bundle lands in `dist/`. In Chrome, open `chrome://extensions`, enable
Developer mode, choose **Load unpacked** and select `apps/browser-extension/dist`.

## Pair it with your backend

The extension ships no credentials. Pair it once:

1. Start the API and the dashboard.
2. In the dashboard, open **Role Discovery** and click **Create pairing token**.
3. Copy the token (it is shown once), open the extension's options page, paste it
   next to your Job Agent URL, and click **Save and test**.

The token is stored in `chrome.storage.local` and sent as a bearer token. Only its
SHA-256 hash is stored server-side, and you can revoke it from the dashboard at any
time. The extension never asks for a LinkedIn, InfoJobs or Indeed password: those
sessions stay in your browser where they belong.

Pointing the extension at a host other than `localhost:8000` triggers a Chrome
permission prompt for that origin, which is why the manifest keeps
`optional_host_permissions` rather than requesting everything up front.

`host_permissions` covers exactly the job sites the content scripts already run
on. That is not extra reach: those sites are declared either way. It is what lets
the extension re-inject its script into a tab that was open when the extension
was updated, and what makes importing work from the side panel, which is not one
of the gestures Chrome grants `activeTab` for. Any other site is still covered by
`activeTab` alone, granted only when you invoke the extension yourself.

## What you get

- **Popup and side panel** — the Search Inbox, grouped by role family, with
  exploratory searches in their own section. Each row has one button per provider.
  The side panel stays open while you browse a job board.
- **Import Job / Import + Prepare** — on the page, in the popup, in the side panel,
  in the right-click menu, or with `Ctrl+Shift+J` / `Ctrl+Shift+K` (rebindable at
  `chrome://extensions/shortcuts`).
- **In-page button** — a small isolated control on supported job pages, which turns
  into `✓ Job Agent · Match 91` once the analysis lands. It lives in a shadow root
  and changes nothing about the page it sits on. Turn it off in the options.
- **Form assistant** — the side panel scans the page for the questions an
  application form is asking and lists them. Draft an answer for one, check it,
  then fill it into the field or copy it. Answers are drafted from your CV, your
  profile and the job on screen, never from thin air, and anything claiming a
  technology your CV does not have is flagged. Questions the answer vault already
  knows, such as work authorisation or salary, are answered without a model call.
  You can also highlight a question on the page and right-click to send it over.
- **Automatic submission detection** — when a page says your application went
  through ("Se ha enviado tu solicitud a…", "Thank you for applying"), the job is
  marked as sent on its own, with the confirming sentence kept as the audit note.
  The panel says it did so and offers Deshacer, because a wrong status is worse
  than a missed one. The patterns are anchored phrases with negation handling, so
  "Todavía no has enviado tu solicitud" does not fire.
- **Duplicate awareness** — before you import, the extension asks the backend
  whether the page is already known, matching on canonical URL, source URL, board
  job id, description fingerprint and company plus title.

Importing a job never submits an application. Submission follows the application
policy configured in your candidate profile.

The form assistant follows the same boundary. Detecting the questions happens
entirely in the page, so nothing leaves it by scanning. A question is only sent to
the backend when you ask for that specific answer, a field is only filled when you
click Fill in, and the form is never submitted.

## Layout

```
src/
  background/service-worker.ts   coordination, context menus, commands, polling
  content/content-script.ts      page capture and the in-page button
  content/dashboard-bridge.ts    lets the dashboard hand searches to the extension
  popup/  sidepanel/  options/   the three UI surfaces
  providers/                     linkedin, infojobs, indeed, google, generic
  extractors/                    linkedin, infojobs, indeed, greenhouse, lever,
                                 ashby, workday, generic
  api/job-agent-client.ts        the only code that talks to the backend
  shared/                        types, storage, DOM capture, shared rendering
```

The extension holds as little logic as possible. The backend remains the source of
truth for the candidate profile, the role map, the search strategy, jobs, scores,
applications and Reactive Resume.

## What is captured on import

In priority order: JSON-LD `JobPosting`, the site-specific extractor, semantic
HTML, then the visible job text. Scripts, styles, tracking attributes, navigation,
footers, hidden elements and "similar jobs" blocks are stripped before anything
leaves the page, and the backend repeats that cleaning on arrival.

Adding a site means adding one extractor in `src/extractors/` and registering it.
Adding a search engine means adding one provider in `src/providers/` and the
matching backend provider in `packages/search_providers/`.

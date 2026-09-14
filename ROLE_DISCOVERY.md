# Role Discovery

The candidate should not have to answer "what should I search for?". That is the
system's job.

```
Candidate profile + master CV
        ↓
CandidateCapabilityGraph        what the person can actually do
        ↓
RoleMap                         which roles that combination is worth
        ↓
Search queries                  concrete, per-provider, prioritised
        ↓
Browser extension               one click opens the results
        ↓
Human browses, imports what looks good
        ↓
Parse → deduplicate → score → Reactive Resume → application
        ↓
Market feedback                 which searches produced good jobs
        ↓
Better role map, better queries
```

## 1. CandidateCapabilityGraph

`packages/role_discovery/capability_graph.py` turns the profile plus the master CV
(pulled from Reactive Resume and flattened by `resume_digest.py`) into a graph that
keeps nine facets apart: technologies, capabilities, domains, responsibilities,
seniority, leadership, product ownership, technical depth and transferable skills.

Two things matter more than the node list:

- **Clusters.** A cluster is a combination of capabilities the candidate applied
  *together* in one role or project. Unity on its own says little; Unity with XR,
  computer vision, hardware integration and shipped product ownership points
  somewhere completely different.
- **Evidence weighting.** The CV is evidence. Stated interests are weaker. The job
  titles the candidate wrote down are wishes, and a desired title of "CTO" never
  becomes proof of leadership experience.

With a model configured, the graph is built by the model and validated on the way
in. Without one, a lexicon-driven fallback produces a usable graph so the feature
never goes dark.

## 2. RoleMap

`packages/role_discovery/agent.py` reasons over the graph, not over keywords. It
produces roles in four categories (primary, secondary, stretch, avoid) with a fit
score, confidence, reasoning, strengths, gaps, equivalent titles, search aliases,
industries, company types and seed queries, plus role families and capability gaps.

It is explicitly asked to name roles the candidate is unlikely to know exist, and
told not to assume their most frequent keyword is their best primary title.

The deterministic fallback scores role signatures over capability *combinations*: a
signature only fires when several independent signals are present, so a single
strong keyword can never on its own become a recommended role.

## 3. Search strategy

`packages/role_discovery/search_strategy.py` expands each role into query variants
that differ along real axes — exact title, title plus a differentiating technology,
alternative titles employers use, seniority wording, industry framing, and an
ATS-scoped web search — then targets them at providers.

The slate is split by an exploration budget, 70% primary, 20% secondary and 10%
exploratory by default, so the system keeps testing roles it is not yet sure about.

Providers live in `packages/search_providers/` behind one method,
`build_search_url(query)`. LinkedIn, InfoJobs, Google Jobs, Indeed and a generic web
search ship today; adding another is one class and one registry entry.

## 4. Search queries are first-class

Each query is a stored entity with a role, provider, location, remote flag,
priority, status, an exploratory flag and its own performance record: searches
opened, jobs imported, scored imports, high-match imports, applications generated
and interviews produced.

The agent may create, retune, demote, disable and replace them. Regenerating the
slate never loses history, and never silently revives a query the agent disabled.

## 5. Learning from the market

`packages/role_discovery/feedback.py` judges queries by the jobs they produced, not
by how many. Twenty imports averaging 58 is a query pointed at the wrong market and
gets demoted; eight imports with six above the high-match threshold gets promoted;
a query opened repeatedly with nothing worth importing loses priority.

Imported jobs are also read for vocabulary the map does not have. A title that
recurs, or one posting that scores very well, becomes a proposed role with its own
searches once accepted. Auto-acceptance is off by default and governed by
`role_discovery.auto_accept_*` in the candidate profile.

## 6. Reporting what actually happened

The agent cannot see an application you sent yourself on a company site, and it can
never see an interview. Those are reported from the dashboard, on the job card and
on each application: **La envié yo**, **Entrevista**, **Oferta**, **Rechazada**,
**Retirada**.

Reporting is not submitting. It records what you already did, and it is what closes
the loop: an application or an interview is credited to the search query that
produced the job, and `POST /api/roles/learn` then promotes the queries that lead to
interviews over the ones that only produce volume.

The extension also reports on its own. When a page confirms that an application
went through, the job is marked as sent without being asked, with the confirming
sentence stored as the note. Every reported outcome can be undone, which is what
makes automatic detection acceptable: the last entry is dropped from the history
and the status returns to what it was.

A job imported from the extension has no application run until documents are
prepared, so reporting against it creates one. The state machine keeps the
automated path strict and gives the candidate their own set of transitions: the
pipeline may not jump from `READY` to `APPLIED`, but a person saying "I sent this
myself" may. Terminal outcomes cannot be walked back, and an interview cannot be
reported before an application.

## 7. The CV library

**Tus CVs** lists every resume in Reactive Resume, in a grid with real PDF
previews, and marks the master. The master CV
is what the capability graph is built from, so switching it makes the role map stale.
The screen says so and offers to rebuild it there and then. Each row expands to show
the section counts and the exact digest the agent reads, which is the quickest way to
see why a role was or was not inferred.

CVs can be deleted from there, one confirmation click each, except the master.
Filtering by the `derived` tag finds the per-job copies the pipeline creates, which
is the pile that actually grows. On the Aplicaciones page, **Regenerar CV** rebuilds
a tailored CV with the current tailoring and deletes the one it replaces, so a
rebuild does not leave a near-duplicate behind. Use it after changing the master CV.

## Configuration

`config/candidate-profile.yaml`, under `role_discovery` and `extension`. The
defaults are sensible; the ones worth knowing:

| Setting | Meaning |
|---|---|
| `total_active_queries` | how many searches the slate holds |
| `primary_share` / `secondary_share` / `exploratory_share` | the exploration budget |
| `high_match_threshold` | what counts as a high-match import |
| `min_samples_before_demoting` | how much evidence before retiring a query |
| `auto_accept_proposed_roles` | adopt discovered roles without asking |

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/roles/discover` | rebuild graph, role map and searches |
| `GET /api/roles/map` | the role map, grouped for the UI |
| `GET /api/roles/capability-graph` | the graph behind it |
| `GET /api/roles/{role}` | one role and its searches |
| `POST /api/roles/{role}/accept` / `reject` | act on a proposed role |
| `POST /api/roles/learn` | retune queries, propose roles from imports |
| `GET /api/searches/inbox` | the Search Inbox, grouped and ranked |
| `POST /api/searches/{id}/opened` | attribution when a search is opened |
| `GET /api/searches/{id}/performance` | what a query actually produced |
| `POST /api/jobs/import-browser` | import the page the user is looking at |
| `GET /api/jobs/{id}/import-status` | poll while the analysis runs |
| `POST /api/extension/tokens` | create a pairing token for the extension |
| `GET /api/applications/outcomes` | the outcomes a person can report |
| `POST /api/applications/{run}/outcome` | report applied, interview, offer, rejected, withdrawn |
| `POST /api/applications/by-job/{job}/outcome` | the same, creating the run if needed |
| `GET /api/resumes` | every CV, with the master flagged |
| `GET /api/resumes/{id}` | one CV, with the digest role discovery reads |
| `PUT /api/resumes/master` | choose the master CV |
| `GET /api/resumes/{id}/pdf` | the rendered PDF, cached per version |
| `DELETE /api/resumes/{id}` | delete a CV, refused for the master |
| `POST /api/applications/{run}/resume` | download the tailored CV |
| `POST /api/applications/{run}/resume/regenerate` | rebuild it, deleting the old one |
| `POST /api/assistant/chat` | draft an answer for one form field |
| `POST /api/assistant/answers` | remember a confirmed answer for next time |
| `POST /api/extension/jobs/{job}/outcome` | report an outcome from the browser |
| `POST /api/extension/jobs/{job}/outcome/undo` | revert the last one |

Scheduled work runs on Celery: `learn_from_market` daily and `refresh_role_map`
weekly.

## Where the automation boundary sits

The AI decides **what** is worth searching. The human decides **which** result is
interesting. The extension makes importing it frictionless. The agent does the
expensive work afterwards.

Importing a job never submits an application. Submission continues to follow the
execution mode in the candidate profile.

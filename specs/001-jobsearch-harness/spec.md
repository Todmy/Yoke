# Feature Specification: Yoke — job-search harness

**Feature Branch**: `001-jobsearch-harness`  
**Created**: 2026-06-02  
**Status**: Draft  
**Input**: User description: "Yoke — a local-first job-search harness that scores roles against your CV with a deterministic core and a thin LLM surface, wraps an eval harness and a self-improving tuner around the scoring, keeps a self-pruning board and a first-class application tracker with a dedup guarantee, offers skill-gap and learning-path analysis with truthfulness-guarded resume tuning, and (later) an email outcome loop. CLI-first; the web panel is a thin client."

## Clarifications

### Session 2026-06-02

- Q: What triggers a role leaving the board (board pruning, FR-005)? → A: Posting-URL liveness — a role is pruned when a liveness check of its source URL returns gone/not-found (e.g. HTTP 404/410); a still-live URL keeps it, and transient network errors do not prune.
- Q: What concrete gate decides the tuner has "enough" decisions (FR-017)? → A: At least 5 applied AND at least 5 rejected AND at least 20 total, exposed as configurable thresholds with those defaults; below any threshold the tuner declines and explains what is missing.
- Q: What backs the local state, given the concurrency guarantee (FR-020, Edge Cases)? → A: SQLite in WAL mode — a single local file with a relational schema; WAL gives safe concurrent reads with serialized writes.
- Q: What is the eval's "stronger reference" (FR-015/016)? → A: A frozen golden set of roles carrying curated expected labels (geo truth, expected tier band, known-unsafe traps), bootstrapped once by a stronger reference model and human-reviewed, then frozen; at eval time the candidate is graded against these fixed labels with zero reference-model calls.
- Q: How does the comp-floor gate behave when a posting states no compensation (FR-002)? → A: The model supplies an estimated comp band as a flagged feature, informed by company and target-market context (not title/JD alone, since the same role can vary 2-3x by company and market); the deterministic floor gate applies to stated compensation and treats the estimate as an estimate.
- Q: How are matched/missing skills extracted without a required model call (FR-011)? → A: Hybrid — a deterministic curated skill taxonomy with aliases (always, no LLM) augmented by semantic similarity to maximize recall; the skill model spans tools, knowledge domains (e.g. high-load systems), and meta-qualities (e.g. fast learner), not only named technologies.
- Q: What is the "hosted subscription" LLM backend (FR-019)? → A: One of several pluggable provider adapters — vendor API keys (Anthropic, OpenAI, …), vendor subscriptions (Claude Code via `claude -p` — code-confirmed as the only subscription backend), and fully local models; v1 ships the subset actually used and new providers are added as plugins without pipeline changes. (Refined in the zoom-out session below: backends are two families — Claude-subscription + OpenAI-compatible.)
- Q: Is a surviving role re-scored, and what governs model cost (FR-005/FR-019)? → A: A user-set per-role model-spend budget trades cost against quality (default favors quality); model features are cached so the formula recomputes with zero model calls on weight changes, and the model is re-called only when the budget allows and the role is new, changed, or stale. The eval guards cheap/weak models.
- Q: How are A/B/C tier cutlines set, and does the tuner move them (FR-004/FR-017)? → A: Sensible defaults ship and work with no configuration; cutlines are fixed score thresholds the user MAY override at their own responsibility. The tuner refits only the scoring weights (the personalization knob) and does NOT move cutlines, so tiers stay comparable across runs. Weights and cutlines are distinct knobs — weights govern how features combine, cutlines govern where A/B/C fall on the resulting score.
- Q: How are the board fit indicator (FR-005) and the gap match indicator (FR-011/014) shown? → A: A qualitative band (e.g. Strong / Moderate / Weak) shown prominently with the underlying numeric score available on expand — the same scale for both, so a number is never the headline (avoids the false-precision / ATS-beating claim FR-014 guards against).
- Q: What is stored as "the CV version sent" (FR-007), and what is the CV model? → A: An immutable snapshot of the exact CV text sent at apply time. *(Phasing superseded below — variants pulled into v1.)* All CV edits stay human-confirmed accept/reject, never auto-applied (FR-013), never fabricating, framed as relevance not ATS-beating (FR-014).
- Q: Code has a third decision class `interested` — is it a training label (FR-008/FR-017)? → A: No. `interested` is kept as a board-side bookmark only; the tuner's positive class is `applied` alone, versus `rejected`. (Implementation delta: tune.py currently pools applied+interested as positive — must change to applied-only.)
- Q: Tuner gate — spec ≥5/≥5/≥20 vs code's ≥1 of each (FR-017)? → A: The spec's ≥5 applied / ≥5 rejected / ≥20 total holds; the code (tune.py, currently gating on ≥1 of each) MUST be hardened to it — ≥1 each overfits the weight grid and makes the before/after meaningless.
- Q: Tier cutlines — user-overridable or fixed (FR-004/FR-017)? → A: Fixed in v1, not user-overridable. The 55/70 thresholds (currently duplicated in analyze.py `tier_of` and tune.py `THRESHOLD`) MUST be defined in one shared source so scorer and tuner cannot drift. User-overridability is roadmap.
- Q: Does Yoke tailor CVs for ATS / per vacancy, and how does that differ from auto-rewrite tools (FR-012/014)? → A: Yes — per-vacancy ATS/relevance tailoring IS a supported goal. The line vs auto-rewrite tools is ASSISTED (human accept/reject, never silent auto-apply) and TRUTHFUL (surfaces only CV-supported skills, never fabricates to game keywords). Per-vacancy tailoring is v1; the named-variant library and live editor are v2 (see the variant-scope bullet below); the goal is in scope.
- Q: From the Scarlett AI scan, what do we adopt (FR-001/026)? → A: v1 sources = Djinni, DOU, Hiring Cafe (aggregator, one high-yield source), LinkedIn (read-only). Adopt: a guarded per-vacancy cover-letter draft (FR-026), an opinionated ICP-default profile preset (UA IT remote) for one-session setup (SC-001), and build-in-public as the go-to-market motion (fits launch-as-portfolio). NOT adopted: silent auto-rewrite, ATS keyword-stuffing, broad-feed competition.
- Q: CV variant scope — what is v1 vs v2 (FR-012)? → A: **Split.** v1 = single base CV + accept/reject tailoring + a per-application tailored copy at apply time (snapshotted), all reachable from a usable CLI (FR-018). v2 = named, reusable variant library + live in-tool editor + variant↔role reuse. Rationale: v1's tailor-at-apply serves the primary (passive) persona; the library/editor is an efficiency layer for the secondary (high-volume) persona. The immutable snapshot holds throughout. (Refines the earlier "full variant model in v1" call into a v1/v2 split.)
- Q: Cover-letter command shape (FR-026)? → A: A standalone `cover` command (CLI + thin web client), v1, output in the profile's language; draft + accept/reject/edit, grounded only in CV+JD, never auto-sent, never fabricating. Not wired into the apply flow.
- Q: How are the v1 sources accessed (FR-001)? → A: As pluggable scraper adapters (the existing `collect.py` scraper pattern) — Djinni, DOU, Hiring Cafe, LinkedIn (read-only, no logged-in actions) added as scraper plugins; manual paste/CSV import is the always-available fallback. No reliance on official APIs for the UA boards that lack them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get a trustworthy scored shortlist (Priority: P1)

A job seeker sets up their profile once (CV text, target lane, location, comp floor, an LLM provider), then runs the pipeline. Roles are pulled from many sources, the ones decided by plain rules are filtered without a model, the rest are scored against the profile, and only the strongest (Tier A/B) reach a small board. The seeker reviews the board and trusts the ranking because the score is a transparent formula, not a model's opinion.

**Why this priority**: This is the core value and the minimum viable product. Without a trustworthy shortlist there is nothing to triage, track, or improve.

**Independent Test**: Provide a profile and a set of roles, run the pipeline, and confirm a board appears with roles tiered A/B/C and a visible per-role fit reason. Can be exercised end to end with no LLM provider configured (deterministic path + mock).

**Acceptance Scenarios**:

1. **Given** a configured profile and available roles, **When** the pipeline runs, **Then** each role receives a fit score, a tier, and a one-line reason, and only Tier A/B roles appear on the board.
2. **Given** a role whose location rules it out (geo blocked) or whose lane is clearly off-target, **When** the pipeline runs, **Then** that role is decided by rules alone (Tier C) and never consumes a model call.
3. **Given** no LLM provider is configured, **When** the user tries to run scoring, **Then** the deterministic stages still run and the user is told a provider is required before the model-scored roles can be produced.

---

### User Story 2 - Track applications without double-applying (Priority: P2)

Over weeks the seeker applies to some roles and rejects others (recording a reason). Applying is a deliberate, logged step — never a single click that makes a role vanish. Each applied role enters a status pipeline; rejected roles drop off. A role the seeker has already acted on never reappears on the board, even if it is reposted under a new URL. The seeker can see a funnel (how many applied, advanced, interviewed).

**Why this priority**: The second-most painful problem after noise is wasted, duplicated effort and losing track of what is in flight. The decision log is also the ground-truth signal that later powers self-improvement.

**Independent Test**: Mark a role applied through the apply step, run a fresh collect that includes the same role reposted under a different URL, and confirm it does not return to the board; confirm the application appears in the tracker with a status and the funnel counts update.

**Acceptance Scenarios**:

1. **Given** a role on the board, **When** the user chooses to apply, **Then** they reach a step to record what they sent (CV version, notes) before the application is logged, and only after confirming does it enter the tracker.
2. **Given** a role already marked applied or rejected, **When** a later collect re-ingests the same role (same URL or same normalized company+title), **Then** it does not reappear on the board.
3. **Given** several logged applications with statuses, **When** the user views the tracker, **Then** response, interview, and offer rates are shown.

---

### User Story 3 - Close the skill and CV gap for a role (Priority: P2)

Looking at a role they want, the seeker asks what their CV is missing. They get the skills the role calls for that their CV does not show, ranked by how central they are to the role; for genuinely missing skills, suggestions of what to learn and how; and for skills they already have but did not surface, accept/reject bullet-level edit suggestions that never invent anything. The seeker decides what to act on and edits their own CV; they can also choose to upskill toward roles they want.

**Why this priority**: This is the one feature with validated user demand and the felt benefit at the moment of deciding to apply. It is gap analysis and a learning path, not an automatic rewrite.

**Independent Test**: Run gap analysis on a role with a known JD and a known CV; confirm it returns matched and ranked-missing skills and a match indicator, that learning suggestions appear for missing skills, and that no suggestion asserts a skill, metric, or seniority the CV does not contain.

**Acceptance Scenarios**:

1. **Given** a role with a job description and the user's CV, **When** the user requests a gap analysis, **Then** they see matched skills, missing skills ranked by relevance, and a match indicator framed honestly (a relevance signal, not a guarantee of passing screening).
2. **Given** missing skills, **When** suggestions are produced, **Then** each missing skill has a suggested way to learn it, and tuning suggestions are offered only for skills the CV already supports.
3. **Given** any suggestion, **When** it is shown, **Then** it is accept/reject and never auto-applied, and it never fabricates a skill, tool, certification, metric, or seniority level.

---

### User Story 4 - Trust and improve the scoring over time (Priority: P2)

A skeptical user (or a reviewer assessing the tool) wants evidence that the scoring is sound. They run an evaluation that scores the model against a stronger reference on a frozen set of roles, where unsafe calls (claiming a blocked role is remote, over-promoting a weak role, producing unparseable output) dominate the verdict. Separately, once enough real decisions exist, the scoring weights refit themselves to the user's own apply/reject behavior, so the ranking converges on that user's taste.

**Why this priority**: This is what makes Yoke a harness rather than a wrapper, and it is the differentiator for the hiring/reviewer audience. It depends on the scoring (US1) and the decision log (US2) existing first.

**Independent Test**: Build a golden set and run the eval to produce a saved scorecard with a pass/fail verdict driven by safety gates; seed both applied and rejected decisions and run the tuner to show a before/after change in agreement with those decisions, with zero model calls.

**Acceptance Scenarios**:

1. **Given** a frozen golden set, **When** the eval runs against a candidate model, **Then** a saved scorecard reports safety-gate results and a pass/fail verdict in which a single safety violation outweighs small fit differences.
2. **Given** enough applied and rejected decisions, **When** the tuner runs, **Then** it reports a before/after agreement metric and proposes adjusted weights without calling any model.
3. **Given** too few decisions of either class, **When** the tuner runs, **Then** it declines and explains what is missing rather than producing misleading weights.

---

### User Story 5 - Keep application status current from email (Priority: P3)

The seeker connects their mailbox read-only. Replies from employers are matched to tracked applications and update their status automatically, with a note recording the source. The seeker never has to remember to mark a role as screening or rejected. Anything they set by hand is never overwritten.

**Why this priority**: A real convenience that closes the outcome loop, but it depends on the tracker (US2) and carries the most setup and privacy weight, so it ships after the launch-ready core.

**Independent Test**: With a read-only test mailbox containing a reply from a tracked company, run the sync and confirm the matching application's status advances with a source note, and that a manually-set status is left untouched.

**Acceptance Scenarios**:

1. **Given** a connected read-only mailbox and a tracked application, **When** a matching employer reply arrives and the sync runs, **Then** the application's status updates with a note citing the message.
2. **Given** an application whose status the user set by hand, **When** the sync runs, **Then** that status is not overwritten.
3. **Given** the email connection, **When** any sync runs, **Then** Yoke only reads mail and never sends, deletes, or modifies it.

### Edge Cases

- A role has no job-description text available: gap analysis and content-based scoring degrade gracefully (work from title/metadata or ask the user to paste the JD) rather than failing.
- The model returns malformed or no output: it is counted as a parse failure by the eval and the role is skipped in scoring rather than crashing the run.
- Deterministic geo is uncertain (a bare city, ambiguous remote): the role is flagged for the model to judge rather than guessed.
- A posting omits salary: the model estimates a comp band from company and target-market context (flagged as an estimate) rather than dropping the role or assuming zero.
- A genuinely different role at the same company shares the same title as one already actioned: the dedup key may suppress it — an accepted trade-off in favor of never double-applying.
- Two processes (a scheduled run and the UI) touch the store at once: concurrent access must not corrupt state (met by SQLite WAL — concurrent reads, serialized writes).
- The user switches LLM providers or models between runs: scoring must remain comparable enough to trust, which is what the eval guards.

## Requirements *(mandatory)*

### Functional Requirements

**Sourcing and scoring (US1)**
- **FR-001**: System MUST pull roles from multiple pluggable sources and normalize and de-duplicate them into a single index; adding or removing a source MUST NOT change the rest of the pipeline. Each source is a pluggable scraper adapter (the existing `collect.py` pattern); the v1 set — Djinni, DOU, Hiring Cafe (itself a remote-jobs aggregator, used as one high-yield source), and LinkedIn (read-only, no logged-in actions) — is added as scraper plugins, with manual paste/CSV import as an always-available fallback. Feed breadth beyond this is deliberately not a competitive priority.
- **FR-002**: System MUST decide every rule-able attribute (location/geo eligibility, target-lane fit, compensation floor, hard rejects) deterministically and without a model call wherever the underlying data is present. The compensation-floor gate is deterministic when a posting states compensation; when compensation is absent, the model supplies an estimated comp band (informed by company and target-market context, not title/JD alone) as a flagged feature, and the gate treats it as an estimate rather than dropping the role or assuming zero.
- **FR-003**: System MUST limit the model to filling a fixed, narrow feature schema for a single role at a time; the model MUST NOT emit the fit score directly.
- **FR-004**: System MUST compute the fit score from the model-supplied features via a transparent, inspectable weighted formula, and assign a tier from the score plus deterministic gates (geo, comp floor — using stated compensation when present, else the model's flagged comp-band estimate); tier boundaries are fixed score cutlines defined in a single shared source (so the scorer and tuner cannot drift), not user-overridable in v1, and the tuner does not modify them.
- **FR-005**: System MUST present only the strongest roles (Tier A/B) on the board, with a per-role tier, fit indicator (a qualitative band — e.g. Strong/Moderate/Weak — shown with the underlying score available on expand), and one-line reason, and MUST prune the board by posting-URL liveness: on a later collect, a role whose source URL returns a gone/not-found response (e.g. HTTP 404/410) is removed from the board, while a still-live URL keeps it; transient fetch failures (network errors, timeouts, 5xx) MUST NOT prune.
- **FR-006**: System MUST run the full deterministic path with no LLM provider configured, and MUST clearly require an explicit provider before producing model-scored roles.

**Tracking and dedup (US2)**
- **FR-007**: System MUST treat applying as a logged, multi-step action (review role → record CV version and notes → confirm), never a single irreversible click; rejecting MAY be immediate and MUST capture a reason. The recorded CV version MUST be an immutable snapshot of the exact CV text sent (the base CV plus any accepted tailoring edits — possibly just the base), not a mutable reference that later edits could change.
- **FR-008**: System MUST record every decision (applied / interested / rejected + reason) together with the role's raw scoring features. The applied and rejected decisions are the ground-truth training signal for self-improvement; `interested` is a board-side bookmark and MUST NOT be used as a training label.
- **FR-009**: System MUST guarantee that a role the user has applied to or rejected never reappears on the board, keyed on the role URL plus a normalized company+title so reposts under new URLs are caught.
- **FR-010**: System MUST move applied roles through a status pipeline (applied → screening → interview → offer → accepted/rejected/ghosted) and MUST report response, interview, and offer rates.

**Gap and learning (US3)**
- **FR-011**: System MUST compute which skills a role calls for that the CV does and does not show, ranking missing skills by relevance, plus an honestly-framed match indicator (the same qualitative band as the board's fit indicator, with the underlying number available on expand). Extraction MUST run a deterministic baseline (a curated skill taxonomy with aliases, no required model call) and MAY augment it with semantic similarity to maximize recall; the skill model spans tools, knowledge domains (e.g. high-load systems), and meta-qualities (e.g. fast learner), not only named technologies.
- **FR-012**: System MUST, when a model is available, suggest what to learn and how for missing skills, and offer accept/reject bullet-level CV edits only for skills the CV already supports; all suggestions stay human-confirmed and never auto-applied (FR-013), aimed at surfacing genuine relevance rather than gaming screening (FR-014). In v1, accepted edits produce a per-application tailored copy of the base CV at apply time (snapshotted per FR-007), reachable from the CLI; a named, reusable CV-variant library and a live in-tool editor are v2.
- **FR-013**: System MUST never auto-apply a CV edit and MUST never fabricate a skill, tool, certification, metric, or seniority the CV does not contain.
- **FR-014**: System MUST frame any match/ATS indicator as a relevance signal for a human reader, not as a claim about beating automated screening. Tailoring a CV per vacancy to improve its ATS/relevance match IS a supported goal — done by surfacing skills the CV genuinely supports and rephrasing to the role's language, never by fabricating to game keyword screening.
- **FR-026**: System MUST provide a standalone cover-letter command (CLI + thin web client) that, when a model is available, generates a per-vacancy cover-letter draft in the profile's output language, grounded only in the CV and the role's job description; the draft MUST be accept/reject/editable by the user, never sent automatically, and MUST NOT fabricate any skill, experience, or claim absent from the CV.

**Trust and self-improvement (US4)**
- **FR-015**: System MUST be able to score a candidate model against a frozen golden set whose curated expected labels (geo truth, expected tier band, known-unsafe traps) were bootstrapped by a stronger reference model and human-reviewed, then frozen, and MUST save a scorecard; the eval MUST make zero reference-model calls at run time, grading the candidate only against the frozen labels.
- **FR-016**: System MUST make safety gates (claiming a blocked location is remote, over-promoting a role's tier, unparseable output) dominate the eval verdict over small fit-score differences; safety-gate detection MUST be a deterministic comparison against the golden set's expected labels, not a model judgment.
- **FR-017**: System MUST refit the scoring weights (weights only, never the tier cutlines) to the user's own applied vs rejected decisions (excluding `interested`, which is not a training label) to maximize agreement at the "worth pursuing" threshold, making zero model calls, and MUST decline with an explanation when the decision log falls below the configurable minimums (default: at least 5 applied, at least 5 rejected, and at least 20 total).

**Architecture and platform (cross-cutting)**
- **FR-018**: Every capability MUST be available as a command-line command runnable by a person and drivable by an agent; the web panel MUST be a thin client over the same logic with no business logic of its own.
- **FR-019**: System MUST support multiple interchangeable LLM providers selected by configuration, without pipeline changes, via two pluggable backend families: a Claude-subscription backend (`claude -p`, the only subscription path) and an OpenAI-compatible backend covering hosted API providers (OpenAI, Groq, Together, OpenRouter) and fully local models (Ollama, LM Studio); v1 ships the subset actually used and new providers are added as plugins.
- **FR-020**: System MUST keep all user data (CV, decisions, tokens, board) local to the user's machine and MUST NOT place personal data in the public project; local state is persisted in a single SQLite database in WAL mode, which MUST tolerate concurrent access (e.g. a scheduled run and the UI) without corruption.
- **FR-021**: System MUST NOT apply to any role on the user's behalf and MUST NOT rewrite a CV automatically; the human always decides and applies.

**Email outcome loop (US5, later phase)**
- **FR-022**: System MUST connect to email read-only, using credentials the user supplies themselves (app password or OAuth token) stored only locally; it MUST NOT request or enter the user's primary password.
- **FR-023**: System MUST match incoming employer replies to tracked applications and update their status with a source note, and MUST NOT overwrite a status the user set by hand.
- **FR-024**: System MUST only read mail — never send, delete, or modify it.

**Cost/quality budget (cross-cutting)**
- **FR-025**: System MUST let the user set a per-role model-spend budget that trades cost against quality (default favoring quality), and MUST govern re-scoring and model/provider escalation by that budget: model-supplied features are cached so the fit formula recomputes with zero model calls when weights change, and the model is re-called only when the budget allows and the role is new, changed, or stale.

### Key Entities *(include if feature involves data)*

- **Profile**: the user's CV (a single base CV in v1; a named variant library is v2), target lane, allowed location(s), compensation floor, output language, a per-role model-spend budget (cost/quality preference), and one or more configured LLM providers (API key, subscription, or local). Drives every scoring decision.
- **CV / tailored copy**: v1 has a single base CV; at apply time, accepted tailoring edits produce a per-application tailored copy that is snapshotted, never auto-rewritten. A named, reusable variant library and a live in-tool editor are v2.
- **Role**: a job posting pulled from a source — title, company, location, URL, source, cached job-description text, and known compensation.
- **Feature card**: the deterministic per-role assessment (geo verdict, lane verdict, comp, and what still needs the model).
- **Score / Tier**: the model-supplied features (including a flagged estimated comp band when the posting omits compensation), cached for reuse across runs; the formula-derived fit number; and the resulting tier (A/B/C).
- **Decision (label)**: an applied, interested, or rejected verdict on a role, with reason and the role's raw features. Applied and rejected are the self-improvement training signal; `interested` is a non-training bookmark.
- **Application**: an applied role progressing through the status pipeline, with an immutable snapshot of the CV variant sent, notes, current status, and source of the latest status change.
- **Weights**: the tunable coefficients of the scoring formula, refittable from decisions; distinct from the tier cutlines, which are fixed thresholds defined in one shared source (not user-overridable in v1) that the tuner does not move.
- **Golden set / scorecard**: a frozen set of roles with curated expected labels (geo truth, expected tier band, known-unsafe traps), and the eval result (safety-gate outcomes, agreement metrics, verdict).
- **Gap result**: matched and ranked-missing skills (spanning tools, knowledge domains, and meta-qualities) for a role, a match indicator, and learning/tuning suggestions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from an empty setup to a scored board in one session without hand-editing any configuration file.
- **SC-002**: The deterministic stages run end to end with no LLM provider configured, and roughly a quarter of roles are decided by rules without any model call.
- **SC-003**: An evaluation run always produces a saved scorecard with a pass/fail verdict, and any single safety-gate violation forces a fail regardless of fit-score closeness.
- **SC-004**: Once the decision log meets the minimums (default at least 5 applied, 5 rejected, and 20 total), the tuner improves agreement with the user's apply/reject choices over the default weights, demonstrably (a before/after number), with zero model calls; below the minimums it declines with an explanation.
- **SC-005**: A role the user has applied to or rejected never reappears on the board across subsequent runs, including reposts under a new URL.
- **SC-006**: A gap analysis returns matched and ranked-missing skills plus learning suggestions, and in review no suggestion asserts a skill, metric, or seniority absent from the CV.
- **SC-007**: A reviewer reading the project can state, in one sentence, why the scoring is trustworthy (the eval harness plus the auditable, tunable formula).
- **SC-008**: Every capability is reachable from the command line, and the web panel exposes nothing the CLI cannot do.

## Assumptions

- Target user is technically comfortable: able to run a command-line tool, supply an LLM key or run a local model, and tolerate local setup. Non-technical seekers are out of scope for v1.
- Yoke ships an opinionated default profile preset for the primary ICP (Ukrainian IT, remote) so a new user reaches a scored board in one session (SC-001) without hand-editing configuration.
- Single-user, single-machine, local-first. No multi-tenant or hosted service in scope.
- The CV is provided as text (pasted or a parsed document); rich resume rendering is out of scope.
- Bring-your-own model: a hosted subscription, a hosted API key, or a local model — the user chooses; the tool ships no bundled paid inference.
- Email sync is a later phase and is read-only with user-supplied credentials; it is not required for the launch-ready core (US1–US4).
- LinkedIn, where used as a source, is read-only and optional; no automated logged-in actions.
- No auto-apply and no automatic CV rewrite are deliberate product boundaries, not missing features.
- The dedup key (URL + normalized company|title) favors never double-applying over the rare case of two genuinely distinct same-title roles at one company.

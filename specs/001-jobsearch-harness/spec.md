# Feature Specification: Yoke — job-search harness

**Feature Branch**: `001-jobsearch-harness`  
**Created**: 2026-06-02  
**Status**: Draft  
**Input**: User description: "Yoke — a local-first job-search harness that scores roles against your CV with a deterministic core and a thin LLM surface, wraps an eval harness and a self-improving tuner around the scoring, keeps a self-pruning board and a first-class application tracker with a dedup guarantee, offers skill-gap and learning-path analysis with truthfulness-guarded resume tuning, and (later) an email outcome loop. CLI-first; the web panel is a thin client."

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
- A genuinely different role at the same company shares the same title as one already actioned: the dedup key may suppress it — an accepted trade-off in favor of never double-applying.
- Two processes (a scheduled run and the UI) touch the store at once: concurrent access must not corrupt state.
- The user switches LLM providers or models between runs: scoring must remain comparable enough to trust, which is what the eval guards.

## Requirements *(mandatory)*

### Functional Requirements

**Sourcing and scoring (US1)**
- **FR-001**: System MUST pull roles from multiple pluggable sources and normalize and de-duplicate them into a single index; adding or removing a source MUST NOT change the rest of the pipeline.
- **FR-002**: System MUST decide every rule-able attribute (location/geo eligibility, target-lane fit, compensation floor, hard rejects) deterministically, without a model call.
- **FR-003**: System MUST limit the model to filling a fixed, narrow feature schema for a single role at a time; the model MUST NOT emit the fit score directly.
- **FR-004**: System MUST compute the fit score from the model-supplied features via a transparent, inspectable weighted formula, and assign a tier from the score plus deterministic gates (geo, comp floor).
- **FR-005**: System MUST present only the strongest roles (Tier A/B) on the board, with a per-role tier, fit indicator, and one-line reason, and MUST prune the board over time.
- **FR-006**: System MUST run the full deterministic path with no LLM provider configured, and MUST clearly require an explicit provider before producing model-scored roles.

**Tracking and dedup (US2)**
- **FR-007**: System MUST treat applying as a logged, multi-step action (review role → record CV version and notes → confirm), never a single irreversible click; rejecting MAY be immediate and MUST capture a reason.
- **FR-008**: System MUST record every decision (applied / rejected + reason) together with the role's raw scoring features, as the ground-truth signal for self-improvement.
- **FR-009**: System MUST guarantee that a role the user has applied to or rejected never reappears on the board, keyed on the role URL plus a normalized company+title so reposts under new URLs are caught.
- **FR-010**: System MUST move applied roles through a status pipeline (applied → screening → interview → offer → accepted/rejected/ghosted) and MUST report response, interview, and offer rates.

**Gap and learning (US3)**
- **FR-011**: System MUST compute, deterministically and without a required model call, which skills a role calls for that the CV does and does not show, ranking missing skills by relevance, plus an honestly-framed match indicator.
- **FR-012**: System MUST, when a model is available, suggest what to learn and how for missing skills, and offer accept/reject bullet-level CV edits only for skills the CV already supports.
- **FR-013**: System MUST never auto-apply a CV edit and MUST never fabricate a skill, tool, certification, metric, or seniority the CV does not contain.
- **FR-014**: System MUST frame any match/ATS indicator as a relevance signal for a human reader, not as a claim about beating automated screening.

**Trust and self-improvement (US4)**
- **FR-015**: System MUST be able to score a candidate model against a stronger reference on a frozen golden set and save a scorecard.
- **FR-016**: System MUST make safety gates (claiming a blocked location is remote, over-promoting a role's tier, unparseable output) dominate the eval verdict over small fit-score differences.
- **FR-017**: System MUST refit the scoring weights to the user's own applied/rejected decisions to maximize agreement at the "worth pursuing" threshold, making zero model calls, and MUST decline with an explanation when there are too few decisions of either class.

**Architecture and platform (cross-cutting)**
- **FR-018**: Every capability MUST be available as a command-line command runnable by a person and drivable by an agent; the web panel MUST be a thin client over the same logic with no business logic of its own.
- **FR-019**: System MUST support multiple interchangeable LLM backends (a hosted subscription, hosted API providers, and fully local models) selected by configuration, without pipeline changes.
- **FR-020**: System MUST keep all user data (CV, decisions, tokens, board) local to the user's machine and MUST NOT place personal data in the public project.
- **FR-021**: System MUST NOT apply to any role on the user's behalf and MUST NOT rewrite a CV automatically; the human always decides and applies.

**Email outcome loop (US5, later phase)**
- **FR-022**: System MUST connect to email read-only, using credentials the user supplies themselves (app password or OAuth token) stored only locally; it MUST NOT request or enter the user's primary password.
- **FR-023**: System MUST match incoming employer replies to tracked applications and update their status with a source note, and MUST NOT overwrite a status the user set by hand.
- **FR-024**: System MUST only read mail — never send, delete, or modify it.

### Key Entities *(include if feature involves data)*

- **Profile**: the user's CV text, target lane, allowed location(s), compensation floor, output language, and provider choice. Drives every scoring decision.
- **Role**: a job posting pulled from a source — title, company, location, URL, source, cached job-description text, and known compensation.
- **Feature card**: the deterministic per-role assessment (geo verdict, lane verdict, comp, and what still needs the model).
- **Score / Tier**: the model-supplied features, the formula-derived fit number, and the resulting tier (A/B/C).
- **Decision (label)**: an applied or rejected verdict on a role, with reason and the role's raw features — the self-improvement signal.
- **Application**: an applied role progressing through the status pipeline, with the CV version sent, notes, current status, and source of the latest status change.
- **Weights**: the tunable coefficients of the scoring formula, refittable from decisions.
- **Golden set / scorecard**: a frozen reference set and the eval result (safety-gate outcomes, agreement metrics, verdict).
- **Gap result**: matched and ranked-missing skills for a role, a match indicator, and learning/tuning suggestions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from an empty setup to a scored board in one session without hand-editing any configuration file.
- **SC-002**: The deterministic stages run end to end with no LLM provider configured, and roughly a quarter of roles are decided by rules without any model call.
- **SC-003**: An evaluation run always produces a saved scorecard with a pass/fail verdict, and any single safety-gate violation forces a fail regardless of fit-score closeness.
- **SC-004**: After enough real decisions, the tuner improves agreement with the user's apply/reject choices over the default weights, demonstrably (a before/after number), with zero model calls.
- **SC-005**: A role the user has applied to or rejected never reappears on the board across subsequent runs, including reposts under a new URL.
- **SC-006**: A gap analysis returns matched and ranked-missing skills plus learning suggestions, and in review no suggestion asserts a skill, metric, or seniority absent from the CV.
- **SC-007**: A reviewer reading the project can state, in one sentence, why the scoring is trustworthy (the eval harness plus the auditable, tunable formula).
- **SC-008**: Every capability is reachable from the command line, and the web panel exposes nothing the CLI cannot do.

## Assumptions

- Target user is technically comfortable: able to run a command-line tool, supply an LLM key or run a local model, and tolerate local setup. Non-technical seekers are out of scope for v1.
- Single-user, single-machine, local-first. No multi-tenant or hosted service in scope.
- The CV is provided as text (pasted or a parsed document); rich resume rendering is out of scope.
- Bring-your-own model: a hosted subscription, a hosted API key, or a local model — the user chooses; the tool ships no bundled paid inference.
- Email sync is a later phase and is read-only with user-supplied credentials; it is not required for the launch-ready core (US1–US4).
- LinkedIn, where used as a source, is read-only and optional; no automated logged-in actions.
- No auto-apply and no automatic CV rewrite are deliberate product boundaries, not missing features.
- The dedup key (URL + normalized company|title) favors never double-applying over the rare case of two genuinely distinct same-title roles at one company.

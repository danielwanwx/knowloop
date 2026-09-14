# Private interview evidence storage

The coach owns classification and written assessment. `scripts/coach_state.py` only validates evidence boundaries and durably stores received batches. It does not grade answers, infer proficiency, invent a total score, or equate finishing a batch with finishing a session.

## Choose one private root

Reuse the learner's existing private directory when one is configured; otherwise the coach uses the conventional `$HOME/.local/share/interview-coach` root and resolves it to an absolute path. Carry that same path across tasks. Keep it outside the skill installation, plugin cache, and all Git repositories. The learner does not create SQLite data, dashboard fields, JSON payloads, or CLI commands; the coach creates and uses the private root as part of the accepted coaching workflow. The CLI always requires `--root`. Do not put records or input JSON in this repository, skill examples, fixtures, commits, or public artifacts.

The script rejects symbolic links in the root path and database files, rejects database hard links, requires current-user ownership, and uses directory/file permissions 0700/0600 where supported. Use a physically resolved path on platforms where `/tmp` or `/var` is a symlink. SQLite transactions make a received event, its linked evaluation, and repairs commit together; concurrent writers wait up to 30 seconds. An error does not acknowledge a save. A private root needs a filesystem with reliable SQLite locking; these permissions are not encryption or protection from another process running as the same user.

Before persistence, remove secrets and unnecessary personal data from the received content. Preserve the actual received/redacted wording; never reconstruct unseen answers or fabricate transcript completeness. `transcript` contains only the received learner-facing batch that is appropriate to persist. Do not copy private Mock examiner banks, hidden future questions, answer keys, or unrevealed rubrics into any field. Save a capability target for the next retest, then generate a fresh question when the retest starts.

## Commands

From the skill installation directory:

```sh
python3 scripts/coach_state.py save --root "$HOME/.local/share/interview-coach" --input -
python3 scripts/coach_state.py section --root "$HOME/.local/share/interview-coach" --input -
python3 scripts/coach_state.py debrief --root "$HOME/.local/share/interview-coach" --input -
python3 scripts/coach_state.py resume --root "$HOME/.local/share/interview-coach"
```

These commands are a coach implementation reference, not a learner workflow. The coach supplies one JSON object through `--input -` on standard input; it never asks the learner to run a command, paste storage data, or create a payload file. Learner payloads are not written to JSON, HTML, or another non-SQLite artifact. On success the CLI prints JSON with `status: saved` or `already_saved`. Exit status 2 reports a generic validation/storage error without echoing the payload or a sensitive path. Resolve the contract/path problem and replay the same event; do not claim it was stored until the command succeeds. `resume` prints private evidence to the local tool output; do not publish that output.

## Coach checkpoint lifecycle

This skill registers no end-of-turn callback or background listener and does not use a host scheduler as a persistence trigger. The coach therefore performs a synchronous semantic checkpoint before its next learner-facing prompt, section/stage advance, topic or mode transition, or wrap-up response:

1. For each newly received assessable answer, retry, or actual Live transcript handoff, redact it and run `save`. A question, reading passage, or coach-authored example alone is not an attempt record.
2. Before a named Learn component, article section, or design stage advances, run `section` with `status: complete`. If it is paused, stopped, or left by a topic/mode change, run `section` with `status: in_progress` first, using only established material.
3. When a bounded Mock stops, save every actual received Mock attempt first. Then run one `debrief` whose `source_event_ids` reference those saved events, including only strengths and gap rows supported by the received scope. With no actual answer, create neither invented source evidence nor a debrief.
4. Treat `saved` and `already_saved` as the only successful checkpoint results. Inspect the result and resume state before choosing the next action or saying it was saved. A transient failure is retried with the same stable ID before that affected transition; if local persistence remains unavailable, say so and do not claim recovery or a dashboard artifact.

Each CLI operation is independently transactional: `save` commits its event, evaluation, and repairs together; `section` commits one study record; `debrief` commits its debrief and gap rows together. Ordered checkpoints preserve the required source-evidence relationship, while deterministic IDs make an interrupted operation safe to replay without duplicate records. Automatic checkpoints never invoke a private report renderer or write learner data to HTML, JSON, or another non-SQLite artifact.

## Event contract

This synthetic example documents the schema; it is not learner evidence:

```json
{
  "event_id": "session-source-42:turn-3:binary-search-boundary",
  "occurred_at": "2026-09-07T19:00:00-07:00",
  "mode": "Practice",
  "track": "Algorithms",
  "competency": "binary search boundary invariant",
  "received": {
    "transcript": "Learner: For lower bound, [lo, hi) contains the unresolved positions. If a[mid] is below the target, set lo to mid + 1; otherwise set hi to mid. Each step shrinks the interval; when lo equals hi, return lo.",
    "original_answer": "For lower bound, [lo, hi) contains the unresolved positions. If a[mid] is below the target, set lo to mid + 1; otherwise set hi to mid. Each step shrinks the interval; when lo equals hi, return lo.",
    "hints": "",
    "retry": ""
  },
  "evaluation": {
    "evidence_type": "independent",
    "scope": "complete",
    "dimensions": {
      "correctness": "The stated interval invariant fits the received solution.",
      "communication": "Explains why the interval shrinks."
    },
    "state": "independent_today"
  },
  "repairs": [
    {
      "target": "Apply the boundary invariant under changed constraints",
      "due_at": "2026-09-10T19:00:00-07:00"
    }
  ],
  "context": {
    "material_url": "",
    "position": "binary search invariant discussion",
    "next_action": "Retest the boundary invariant with a fresh problem",
    "language": "Chinese explanations, English interview response"
  }
}
```

Required top-level fields are those above except `context`. Unexpected fields are rejected so private metadata is not silently added. `event_id`, `track`, and `competency` must be nonempty strings; timestamps must include a timezone. Modes are exactly `Learn`, `Practice`, `Mock`, and `Review`. Recommended stable track names are `Python`, `Algorithms`, `SystemDesign`, `Fundamentals`, `Behavioral`, `Introduction`, `Resume`, and `Data`; other nonempty names support migration. Keep competency labels stable across retests.

Use a stable source event identifier plus turn/competency suffix when splitting a mixed batch. Reuse that identifier for a retry of the storage operation, not for a new learner attempt. The canonical JSON SHA-256 is recorded: exact semantic replay (including reordered keys) creates no duplicate; the same ID with different content is rejected. To record a new answer or corrected assessment, append a new event ID and explain the correction in a textual dimension. Existing evidence is never overwritten.

`received.transcript` is a required nonempty string. Optional `original_answer`, `hints`, and `retry` are strings containing actual evidence; omit unavailable material. Never substitute the coach's rewrite for the learner's original answer. `context` supports only optional string fields `material_url`, `position`, `next_action`, `language`, `course_id`, and `task_id`; avoid personal identifiers and hidden examiner content. Each save is one competency-focused received batch, and `scope` describes that batch's assessability, not the complete session.

`evaluation` requires:

- `evidence_type`: `question`, `self_report`, `coach_example`, `prompted`, or `independent`.
- `scope`: `complete` or `incomplete`.
- `dimensions`: a nonempty map of dimension names to textual, evidence-based assessments. Use as many relevant dimensions as supported; no generated aggregate score.
- `state`: `needs_check`, `needs_hint`, `independent_today`, or `delayed_transfer`.

Only complete `independent` evidence with an original answer and no hints can use either independent state. Asking a question, reporting confidence, viewing a coach example, receiving hints, and incomplete evidence cannot establish independent performance. A correct retry after hints remains `prompted`/`needs_hint`; save a later fresh attempt separately. The script cannot determine whether a claim of independence is true: the coach must ground it in the actual interaction.

`delayed_transfer` additionally requires:

```json
"transfer": {
  "prior_event_id": "session-source-42:turn-3:binary-search-boundary",
  "kind": "retention",
  "evidence": "On a later day, reconstructed the invariant independently without reopening prior notes."
}
```

The earlier event must already exist, be earlier in time, and carry complete independent evidence for the same track and competency. `kind` is `retention` or `transfer`; both kinds require a later UTC calendar date. This conservative boundary prevents a same-day answer from claiming delayed performance; it is not a scientifically validated retention interval. For transfer, the coach must describe the actual changed constraints and independent response in `evidence`; a good repeat answer alone does not qualify. No `transfer` object is allowed for the other states.

`repairs` is a required list (possibly empty). Each entry has a nonempty capability `target`, timezone-bearing `due_at`, and optional `status` of `open` (default) or `resolved`. Duplicate targets within one event are rejected. The latest entry for the same track/competency/target controls its pending status. Successful `delayed_transfer` resolves the repairs belonging to its explicit `prior_event_id`; it does not clear unrelated targets. Record new remaining gaps in that retest's `repairs`. Only explicitly resolve a target when the evidence supports it.

## Resume and legacy notes

`resume` returns the total event count, latest saved batch as `latest_context` (including actual received text and context), latest actual attempt assessment per competency with its occurrence date and context (falling back to initial unmeasured evidence), all pending repairs, and currently due capability targets. Ordering follows successful append order; this is the latest saved context, not a claim that imported historical timestamps are newest. Read the returned evidence before selecting the next action. An empty database returns `latest_context: null`.

Existing `learner-state.md` or other private legacy notes remain untouched. Read them separately when the learner identifies them. If migrating, preserve provenance and save historical claims as `self_report`/`needs_check` until actual received independent evidence is available. Do not silently treat a legacy checklist or confidence label as mastery.

A later `question`, `self_report`, or `coach_example` stays in event history and latest context but does not replace an existing competency assessment. A later actual `prompted` or `independent` attempt can update or lower that assessment when the received evidence warrants it.

Optional numeric `rubric_scores`, explicit `attempt_outcome`, and failed/successful `retest_of` are defined in [assessment](assessment.md). Course selection and task status use the same SQLite database; see [course](course.md). Numeric fields do not change existing text-only event meaning. A learner-requested dashboard is an in-memory, local loopback view served directly from SQLite; it is never regenerated by a save, and the CLI does not create a data-bearing file.

## Reusable section library

`section` stores coach-prepared study material separately from attempt evidence. Completed sections require confirmed points, core ideas, and a read-aloud interview script. `learner_shortages` must be empty or grounded in received evidence; generated prose is never promoted to independent evidence. `source_event_ids` may be empty for pure reading material, but include every relevant saved attempt when a shortage or learner-specific conclusion is recorded.

```json
{
  "section_id": "news-feed:nfr:v1",
  "occurred_at": "2026-09-09T20:00:00-07:00",
  "track": "SystemDesign",
  "topic": "News Feed",
  "stage": "Non-functional Requirements",
  "breakdown": "latency, freshness, durability and workload",
  "status": "complete",
  "confirmed_points": ["Feed-read p95 is below 500 ms."],
  "core_ideas": ["A success response requires durable storage first."],
  "learner_shortages": ["Initially selected storage from the read/write ratio alone."],
  "interview_script": "For the non-functional requirements, I would prioritize...",
  "source_event_ids": ["news-feed:nfr-attempt"],
  "context": {"language": "English", "course_id": "system-design", "task_id": "sd-w2"}
}
```

`status` is `in_progress` or `complete`. In-progress records may have empty points or script; completed records may not. Arrays contain at most 30 short items and scripts are capped at 20,000 characters. Each new revision uses a new `section_id`; `resume` returns the latest revision for each track/topic/stage/breakdown plus `latest_section`.

## Debrief and personal gap ledger

`debrief` is one atomic analysis of saved evidence. It requires at least one existing `source_event_id`. Each gap is written to the normalized `gap_items` table with a stable `gap_key` and unique `gap_event_id`. Append a later row with the same key and `status: resolved` when new evidence supports closure; never edit or delete the old row.

```json
{
  "debrief_id": "news-feed:mock-1:debrief",
  "occurred_at": "2026-09-12T20:00:00-07:00",
  "mode": "Mock",
  "track": "SystemDesign",
  "topic": "News Feed",
  "summary_points": ["Completed requirements through one feed-fanout deep dive."],
  "strengths": ["Kept post durability separate from feed freshness."],
  "source_event_ids": ["news-feed:mock-1:attempt"],
  "gaps": [
    {
      "gap_event_id": "news-feed:mock-1:gap-cursor",
      "gap_key": "cursor-composite-boundary",
      "stage": "API / System Interface",
      "breakdown": "feed pagination",
      "observed_shortage": "Used offset under concurrent inserts.",
      "core_idea": "A cursor carries the last row's complete ordering key.",
      "standard_points": ["Sort by created_at and post_id", "Request rows strictly after the boundary"],
      "interview_script": "I would use cursor pagination because...",
      "repair_target": "Explain a stable composite cursor under concurrent inserts",
      "status": "open",
      "due_at": "2026-09-14T20:00:00-07:00"
    }
  ],
  "context": {"language": "English"}
}
```

`resume` returns `study_sections`, `latest_section`, the latest `debriefs` per track/topic, `latest_debrief`, and the current `open_gaps`. A learner-requested transient dashboard view reads the latest study library, debrief summaries, and open-gap ledger directly from SQLite. These are private coaching artifacts; they do not alter evidence counts, scores, task completion, or independent-performance states.

# Progressive learning, with observable limits

The four modes control how the coach interacts; the progression below controls what evidence to seek. Do not add six new user-facing modes or require the learner to configure a curriculum. Read this once on accepted entry and revisit for a new scope or review decision.

## Pick a finite target

Use the supplied material, goal and time. Replace “master databases” with a small working scope such as “explain a transaction isolation anomaly and choose a suitable prevention mechanism.” Sketch 3–5 observable outcomes and only the prerequisites needed for them. Outcomes must fit the topic: recognize a distinction, explain a cause, solve or demonstrate, choose under changed conditions, and retain later. For personal experience, test truthful specificity, reasoning and audience adaptation rather than a single canonical story. For a factual topic, do not invent implementation or system-scale requirements.

A map is a coverage checklist, not measured proficiency. Infer a useful initial scope; ask one focused question only if the intended application changes it materially. State what this session can establish and what remains untested. No whole-subject mastery percentages, permanent “mastered” flags, or offer guarantees.

## Move by evidence, not by a fixed quiz count

| Depth | Coach action | Advance when | If blocked |
|---|---|---|---|
| Orientation | In Learn, give a tiny explanation/example or locate the passage; for an experienced learner, sample a prerequisite first | The task and relevant terms are understood | Explain the minimum missing prerequisite; do not repeatedly quiz unknown terms |
| Retrieve | Invite a short closed-notes answer, reconstruction or prediction, one at a time | The relevant idea can be produced without supplied wording | Separate unfamiliarity from retrieval failure; provide one hint or explanation |
| Explain | Ask why a step works, what causes the result, or contrast a near-miss | Causal reasoning and the important boundary are correct | Demonstrate the broken link, then ask for self-explanation |
| Apply | Ask for an unseen small problem, code, calculation, diagram or real-story response | An actual artifact/answer meets the stated target without hints | Use a worked example, then a partly completed example, then a fresh independent attempt |
| Transfer | Change a meaningful condition or mix with a confusable approach without naming which method to use | The learner chooses and justifies a suitable approach; assumptions and failure cases survive probing | Return to the exact missing mechanism, not a harder random question |
| Retain | On a later day, ask an unseen equivalent or changed-context question before reviewing notes | Independent later evidence supports the same narrow capability | Relearn briefly, shorten the next interval, keep stronger claims pending |

Skip depths already supported by adequate evidence; revisit them when an error warrants it. Quick questions are a small diagnostic sample, not a speed contest or proof of mastery. Do not fire a list of questions before waiting for an answer. A novice may need teaching before any useful attempt. A strong learner should reach application/transfer quickly. At most two unsuccessful attempts on the same missing mechanism before changing the explanation or example; this is a usability guardrail, not a research-derived constant.

Feedback names the first incorrect step, explains why, supplies the smallest helpful correction, and asks for a retry. Immediate retry shows repair with help. Save it as prompted; only a fresh, adequately independent attempt can establish H0. In Mock, preserve interview flow and move teaching to debrief. Never turn “let me finish reading” into an interruption schedule.

## Adapt spacing; do not claim a personal forgetting curve

Start from existing due targets, desired retention horizon and actual availability. When no schedule exists, use these adjustable defaults:

- Incorrect or hinted: repair now; propose a fresh check next available day, usually within 1–2 days. If no prior independent evidence exists, that check can establish `independent_today`, not `delayed_transfer`.
- First independent success: propose about 2 days, then about 7 days after a successful independent review.
- Repeated successful delayed performance: extend the *previous actual interval* approximately twofold, usually up to 2–4 weeks for active interview preparation. Match longer horizons to the actual goal; do not pretend this is optimal for every subject.
- Failure on review: identify whether recall, mechanism, execution or language failed. Relearn the relevant part and shorten the interval. A quick typo does not erase unrelated knowledge.
- Review overdue: do one fresh check now and reschedule from actual performance; no catch-up pile of duplicate overdue quizzes.

These are product heuristics inspired by spacing research, not “the Ebbinghaus formula.” A small answer history cannot estimate a calibrated forgetting curve. The dates only enter the local queue; no background reminder is created. Default a short session to one due target plus one new target, reducing scope when time is tight. User priorities override the queue.

Use interleaving only after basic execution is available and the purpose is to distinguish plausible methods (e.g. heap vs sorting, isolation levels, statistical tests). Random subject switching and overload are not desirable difficulty. Couple factual retrieval with application; remembering vocabulary does not prove transfer.

## Save scope and progression using the existing contract

No second scorebook or database schema is needed. Keep a stable track and narrow competency across sessions. In `evaluation.dimensions`, use concise textual fields when relevant:

- `scope`: the bounded 3–5 outcomes and prerequisites; retain which outcomes remain untested.
- `progression`: deepest demonstrated depth, supporting event/answer, hint status and the next missing depth. Depth is separate from evidence state.
- `review_plan`: after a real review, note the previous assessment date, this assessment date, actual elapsed interval, proposed next interval and reason. Resume exposes the per-competency assessment date even when another topic was practiced more recently. If an older record lacks interval evidence, use a conservative default and label the missing history rather than inventing it.
- Domain dimensions: correctness/mechanism, execution, transfer, expression, or ownership as actually observed.

Keep a brief scope/depth note in every later actual assessment for that competency so resume does not discard its coverage context. Initial maps may accompany actual questions or self-reports as `needs_check`; do not create invented learner answers to initialize a map. Save reading position and one next action in `context`; put only capability targets and next due dates in `repairs`.

Use one stable review target per capability and refresh its due date on a real event, instead of precreating a stack of identical future reviews. On a successful delayed review, the store resolves the linked prior targets; include the same capability target with its next due date when retention maintenance is still useful. On a failed review, append actual evidence and re-open/reschedule that target. Do not discard independent strengths in other dimensions because English expression is weak. Carry forward relevant prior dimensional evidence with its original date and event ID, explicitly labelled historical rather than newly observed; the overall state is not a replacement for these distinct findings.

Existing storage states remain `needs_check`, `needs_hint`, `independent_today`, `delayed_transfer`. The last name includes later retention (`transfer.kind=retention`) as well as later transfer; tell the learner which was actually tested. The CLI enforces a later UTC date and prior independent evidence for either delayed kind. A later retention pass is not automatically a transfer pass. Never use a state label alone to claim the entire scope passed.

## What “learned” may mean

Say “you independently explained X and solved Y today; Z and delayed retention are still untested.” A stronger bounded claim needs evidence for the agreed outcomes, fresh application and later retention; include changed-context transfer when the goal requires it. Keep dates and context visible in the evidence and stay open to contrary results. No finite sample establishes complete, permanent knowledge of an unrestricted subject.

End with three short items: the first answer's evidence, the one useful correction, and the next action/date. Reference notes can contain a small correction card and one primary resource, but never hidden next-test questions/answers.

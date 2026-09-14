# Track guidance

Use only the relevant row, then probe the learner's actual claim. These are assessment targets, not a script to recite. A session may move across tracks; retain the topic and competency on each event.

For SystemDesign, read [system design delivery](system-design-delivery.md) before teaching or testing. Its stages organize the conversation; the row below describes the evidence to seek within those stages, not permission to jump straight to implementation.

| Track | First observable attempt | Useful probes | Completion evidence |
|---|---|---|---|
| Python / Algorithms | Explain constraints and an approach; write a small implementation when appropriate | Invariant, time/space, empty/duplicate/adversarial inputs; debug a failing example; explain the Python construct used | Own explanation plus observed code/tests where implementation is claimed. Oral fluency alone cannot pass coding |
| SystemDesign | Clarify requirements and walk one request/event through an end-to-end design | State ownership, API/schema, bottleneck, consistency, retry/failure, alternative and operational cost | Trace a concrete event, justify one choice and handle a new requirement without only naming products |
| Fundamentals | Explain the mechanism behind a claimed technology | Concurrency/locks, processes/threads, memory, network protocols, indexes/transactions, queues/cache, language/runtime behavior; ask for one small execution trace | Can predict behavior or diagnose a counterexample, distinguish guarantees from implementation assumptions |
| Behavioral | Tell one real situation, personal decision, action and result | Conflict, failure, ambiguity, influence, priorities, learning; “what did you actually do/say?” | Specific role and causal account, honest uncertainty, reflection and a credible alternative; no invented metrics |
| Introduction | Give a short introduction suitable for the stated role/audience | Why this experience matters, one substantiated strength, why the move, a concise follow-up | Clear relevant account within requested length; verify claims through examples, not a list of buzzwords |
| Resume | Pick one actual bullet or project and explain it | Personal vs team ownership, baseline/result measurement, design alternatives, hardest failure, evidence; shift engineer/manager audience | Can defend scope, mechanism and impact; unknown numbers stay unknown, hypothetical redesign is labelled |
| Data | Clarify data/SQL/quality problem, schema and correctness expectations | Joins/cardinality/nulls, aggregation/window functions, metric definition, duplicates, event time, lineage/backfill, quality checks and performance | Query or reconciliation reasoning handles real edge cases; distinguish a guessed business metric from an agreed definition |

Use track labels consistently when saving: Python, Algorithms, SystemDesign, Fundamentals, Behavioral, Introduction, Resume, Data. A competency is narrow, e.g. “explain ownership of a project decision” or “reason about retry deduplication,” not simply “all system design.” There is no universal checklist that every role must pass. Adapt depth to the job, relevant experience and actual evidence.

## Scale and scope are cross-cutting

Ask scale questions only after understanding the original case. Change one dimension at a time: users/QPS, cardinality, data size, skew/hot keys, concurrency, burst load, latency, geographic distribution, team size, budget or operational burden. Require the learner to identify what fails first, estimate an order of magnitude, explain a change and its cost. Bigger is not automatically distributed; a single-machine solution can be correct.

For algorithms, scale means input bounds, streaming vs batch, memory limits or an adversarial distribution. For a project/BQ, team or business scope does not justify inventing their experience: distinguish what happened from what they would do at a larger scale. For introductions, a changed audience means changing emphasis, not fabricating leadership scope.

## Language practice

First isolate whether the content is correct. Then give one shorter phrasing and have the learner speak it in their own words. Keep the learner's meaning and facts. A generated 60-second polished script is a demonstration, not proof they can reproduce it under follow-up. Do not force English during conceptual reading unless requested.

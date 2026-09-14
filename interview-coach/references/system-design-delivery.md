# System design delivery across coaching modes

Use this for SystemDesign Learn, Practice, Mock and Review, including a course assignment with no supplied article. It adds a conversation structure to the shared learning loop, not another mode or score store.

## Source and teaching order

Reference: [Hello Interview — Delivery Framework](https://www.hellointerview.com/learn/system-design/in-a-hurry/delivery), checked 2026-09-09. The published order is Requirements (functional then non-functional), Core Entities, API / System Interface, optional Data Flow, High Level Design, Deep Dives. Its purpose is to reach a working design before adding complexity; estimates should inform decisions.

KnowLoop's default teaching adaptation places a brief Data Flow before API to connect user actions to contracts. Do not attribute this reordered, explicit checkpoint to the original article. Follow a supplied article's order when accompanying that reading; identify any missing stage and cover it at a useful boundary. Do not pretend to have read an inaccessible article or its paid sections. Without source content, label explanations and examples coach-authored.

## Stage progression

Show a short location such as “News Feed · Functional Requirements” at entry and when changing stages. Show the roadmap once, not on every turn. This table is a coach guide; reveal only the current prompt, not a future question bank.

| Stage | Teaching focus / learner output | Coach-authored interviewer-style probe |
|---|---|---|
| Functional Requirements | Identify the actors, prioritize a few user actions, and make scope boundaries explicit. | Which user journey must work in the first version? |
| Non-functional Requirements | Turn relevant scale, latency, freshness, durability or availability needs into explicit assumptions/targets. Separate workload facts from assumptions. | Which quality matters most on this journey, and how would you measure it? |
| Core Entities | Name the domain objects, identifiers and important relationships. Defer detailed columns and indexes. | What relationship must the system remember to support that action? |
| Data Flow | Trace the main input → actions/state changes → output without choosing infrastructure yet. In a simple system, a short trace suffices. | What must happen between that user action and its visible result? |
| API / System Interface | Map the agreed actions to contracts: inputs, outputs, identity, and relevant pagination or errors. Use event/job contracts when HTTP is not the interface. | What does the caller send and receive to perform this action? |
| High Level Design | Connect the contracts to components and owned state. Trace the core requests end to end; add necessary schema details as they arise. | Walk one request through your drawing and explain each state change. |
| Deep Dives | Select the most consequential requirement gap or failure in this design; compare alternatives, revise the design and name the cost. | Under this changed condition, what fails first and why? |

Carry forward the learner's decisions: later APIs must implement agreed functionality, and deep dives must relate to the workload and quality targets. Do not inject a queue/cache/sharding recipe before a need is established. A necessary mechanism can appear in HLD; speculative optimizations go into a short pending list. Compute quantities when they affect a choice, not as a ritual. Return to an earlier stage if a new constraint invalidates it and explain the dependency.

## Same stages, different interaction

- **Learn / 陪读:** explain the current stage's purpose and one small example or the current paragraph. Then invite one short reconstruction or design choice. A new learner asking to study News Feed should first learn how to scope its user actions, not be asked to design tables. After a sufficient response, briefly summarize the decision and connect it to the next stage. Respect uninterrupted reading and requests for direct explanations; do not convert reading into a surprise mock.
- **Practice / 测试:** name the stage being assessed and give one contextual prompt before hints or demonstrations. A full-design practice starts at requirements; a targeted API test starts at API with the necessary scenario constraints supplied. Adapt the next probe to the answer. Prompted repair stays prompted under the shared evidence rules.
- **Mock:** give the design problem and agreed time/language, then let the candidate lead clarification and stage transitions. Answer scope questions as the interviewer. Keep the framework as an internal coverage guide; do not coach every transition or reveal model answers. Probe the candidate's actual design one question at a time. Summarize stage coverage and teaching points in the debrief. Stage headings alone are not answer hints; supplied mechanisms or choices are help and must be recorded as such.
- **Review / 复测:** resume the saved capability and stage, give enough neutral scenario context, and ask a fresh equivalent or changed-condition question before showing old notes. Do not force a complete seven-stage interview to retest one capability. Missing history means unassessed, not failed.

For a full 40-minute session, a coach allocation is 7 minutes for requirements, 3 for entities, 3 for flow, 4 for APIs, 13 for HLD, 8 for one deep dive and 2 for recap. These are adjustable teaching budgets, not official interview timings. A short reading session may stop at requirements; remaining stages stay pending. Explicit learner stage/time choices override the default order. Do not require confirmation at each transition or rush through an unexplained mechanism to meet a timer.

## Save and resume a stage

Use the evidence contract for actual attempts. At an actual attempt or natural reading boundary, keep `track: SystemDesign` and a narrow stable `competency`. In `context.position`, record the problem, source section, current stage, assumptions/decisions actually established, and what remains pending. Put one concrete continuation in `context.next_action`; retain course/task links when applicable. Example position format: `News Feed | stage: Functional Requirements | reading section: ... | established: ... | pending: ...`.

In evaluation dimensions, distinguish section coverage from demonstrated correctness, record hints, and leave untested stages untested. The appearance of all headings or a coach-provided design is not completion or independent performance. Resume this position across modes; if the learner explicitly restarts or jumps to a stage, preserve history and follow that choice.

When a stage is completed, the session may not advance until a `section` record has been saved and read back. Use the topic as `topic`, the delivery stage as `stage`, and a narrower mechanism such as `scope and chronological pagination` as `breakdown`. Save only decisions actually established in `confirmed_points`; put reusable principles in `core_ideas`; put evidence-backed personal gaps in `learner_shortages`; and produce one concise, natural English answer in `interview_script`. If the learner pauses, stops, switches mode, or changes topic before completion, save that stage as `in_progress` before acknowledging the pause or sending the next transition. This is the skill's synchronous checkpoint, not a background end-of-session callback.

After a full SystemDesign Mock, persist a `debrief` whose gap rows retain the exact stage and breakdown where each weakness appeared. A later review should use the standardized points and core idea for preparation, then hide the repair script before the learner's fresh attempt. Resolve a gap only through a later debrief row with the same stable `gap_key`; do not delete history or silently mark it fixed.

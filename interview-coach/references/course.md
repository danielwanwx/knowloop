# Courses and private planning

Use this reference for course selection, “what should I learn today?”, task
tracking, and a requested dashboard. The installed skill bundles
`assets/courses.json`; no repository, browser login, or public endpoint is
required.

Read `resume` before choosing work. A returning learner's explicit topic or
Week overrides the backlog. If no course is selected, offer the bundled public
catalog:

- `system-design`: a public resource sequence for system-design practice.
- `coding`: a public resource sequence for coding practice.

Never reuse an unavailable saved course or task identifier. Ask the learner to
select an available course and Week instead. Existing local records remain in
the private SQLite database, but unavailable catalog entries do not become an
active enrollment.

The catalog is bundled. A requested refresh has no configured public endpoint,
so it remains offline and makes no network request. Do not promise a remote
update or manufacture a replacement assignment.

Use the storage CLI internally. For example, a learner-selected system-design
Week can be enrolled with a short local payload:

```json
{"course_id":"system-design","week_id":"w2","minutes":30,"timezone":"America/Los_Angeles"}
```

Tasks are separate from evidence: completing a task records a learner-confirmed
state, while an evidence-backed task state must point to a saved matching
attempt. Course tasks are pending until that state is saved. A requested
dashboard is transient and local; public pages contain only the catalog and an
explicitly synthetic demonstration.

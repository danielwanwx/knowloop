# Evidence-based scores (optional)

Numeric scores are AI judgments about a specific observed attempt, not objective mastery percentages or hiring probabilities. Existing text-only events remain valid and unscored. A question, self-report or demonstration cannot earn an ability score. Keep the actual first answer, hints and retry separate. Score only dimensions you observed; absent means unassessed, not zero. For an inapplicable dimension, omit it and explain N/A in the textual dimensions.

Optional fields inside `evaluation`:

```json
{
  "attempt_outcome":"met",
  "rubric_scores":{
    "rubric_version":"knowloop-1",
    "dimensions":{
      "concepts":{"score":2,"reason":"Independently defined the invariant and checked it on the actual example."}
    }
  }
}
```

`attempt_outcome`: `met` or `not_met`, only on complete attempted scope, judged against the stated target. Do not infer this from fluent speech. Scored events require an actual `original_answer`. Score against the stated scope; exclude unfinished scope from pass-rate denominators.

Eight keys: `concepts` (concept understanding), `causality` (why it works), `application` (independent application; for BQ actual ownership/evidence), `edges` (boundaries/testing), `tradeoffs` (alternatives/transfer), `structure` (answer organization), `expression` (clarity in selected language), `retention` (later recall). Every value includes a concrete reason tied to that answer. The record supplies evidence ID/time/track/competency/hints/scope; don't put a second score archive elsewhere.

0 = observed material error; 1 = partial performance requiring support; 2 = independently meets the target; 3 = accurate independent performance under harder, new conditions with reasons. A 3 requires describing the changed constraint in the rationale. Scores ≥2 require complete independent unhinted evidence. A successful retry after seeing the answer still belongs to helped evidence; use a genuinely independent later attempt for an independent score.

For a later retest, add `retest_of` with the prior complete independent-success event ID. This supports both pass and fail, so the retention denominator includes failures. It must be the same track/competency on a later UTC date. Do not use retention scores on same-session repetition. Existing successful `delayed_transfer` remains supported; a failed retest uses `needs_hint` or `needs_check` plus `attempt_outcome: not_met` and `retest_of`. Do not set conflicting prior IDs. Hinted retest success is not unhinted retention.

## What the charts count

- Course completion: completed available tasks / all available tasks; skip/defer/unpublished separately visible. This is not mastery.
- Task assessment coverage: tasks linked to actual attempted evidence / available course tasks. This measures task coverage, not all possible knowledge.
- Independent success: complete unhinted attempts explicitly marked met / complete unhinted attempts with explicit outcomes. Legacy unscored attempts are separately counted.
- Hint dependence: complete helped attempts / complete actual attempts. Incomplete attempts are disclosed separately.
- Retention: linked, complete retests with explicit outcomes; numerator excludes hinted successes. Actual elapsed days and sample count shown; no fitted personal forgetting curve.
- Radar/trends require one selected track + competency; use one rubric version. Radar uses latest observation per axis with date/n, leaving unobserved axes blank. Trend adds no missing days and marks helped attempts. Do not average unrelated tasks into a total ability score.

The deterministic dashboard renderer owns statistics; never manually insert made-up chart numbers. Gap targets come from real saved repairs and are checked against evidence, not every ordinary question.

# Optional visual tools

For renderer contributors and explicit visual requests. Start ordinary interview practice with `$interview-coach`; these tools produce learning aids, not learner assessments. All outputs are local unless sharing is explicitly requested. Paths in command examples are relative to the repository root; installed skills resolve scripts relative to their SKILL.md.

## Recommended Architecture

The best compatibility model is:

1. **Plugin manifests per host**: Codex, Cursor, and Claude Code each get their own marketplace/plugin manifest.
2. **Short primary skill**: all hosts load `skills/card/SKILL.md` as the easiest diagram-first entrypoint.
3. **SDE preset skill**: `skills/senior-sde-interview-script/SKILL.md` remains available for users who want the explicit SDE interview workflow.
4. **Bundled renderer scripts**: the agent writes a small content JSON, then runs `scripts/render_interview_card.py` to generate the preview SVG, `.excalidraw` file, and optional Excalidraw share link.
5. **Optional MCP**: Excalidraw MCP is declared for hosts that support it, but it is not required for the main flow.

Renderer invariants:

- Text must fit inside its parent block; blocks grow vertically when needed.
- Connectors leave from block edges and route around unrelated blocks.
- Connectors should leave and enter block edges perpendicularly using short port stubs; avoid long segments that run parallel against a block border.
- Connector labels should read as line annotations: keep them close to the line, slightly offset from the stroke, and only move them farther when needed to avoid blocks.
- Whiteboard previews keep bottom padding beyond the lowest block so screenshots and SVG previews do not crop the final row.
- Block backgrounds use a semantic palette, not random cycling: the same `kind` gets the same fill, and colors communicate role such as client, API, database, cache, queue, storage, warning, note, or answer.
- Decorative icons are opt-in, because they reduce text width and increase overlap risk.

Content invariants:

- Start with a mental model, not a definition list.
- Use one obvious left-to-right or top-to-bottom path through the board.
- Show why the naive approach fails before showing the stronger design.
- End with the correctness check or decision rule.
- For Chinese output, preserve the source meaning but use natural Chinese. Keep English technical terms when they are clearer, and explain them briefly rather than forcing awkward translations.

This is deliberately not a `rules` or `CLAUDE.md` package. Rules are too host-specific and passive; plugin + skill packaging gives installable discovery, namespaced invocation, bundled scripts, and optional MCP wiring.

## Repository Layout

```text
.agents/plugins/marketplace.json                     # Codex marketplace
.cursor-plugin/marketplace.json                      # Cursor marketplace
.claude-plugin/marketplace.json                      # Claude Code marketplace
plugins/crack-system-interview-skill/
  .codex-plugin/plugin.json
  .cursor-plugin/plugin.json
  .claude-plugin/plugin.json
  .mcp.json                                          # Claude/Codex MCP config
  mcp.json                                           # Cursor MCP config
  commands/card.md                                   # Claude Code short command: /card
  skills/card/
    SKILL.md
    scripts/render_interview_card.py
    scripts/share_excalidraw.mjs
  skills/senior-sde-interview-script/
    SKILL.md
    scripts/render_interview_card.py
    scripts/share_excalidraw.mjs
  skills/system-design-study-coach/
    SKILL.md
    scripts/plan_lookup.py
card/                                                # standalone short skill copy
senior-sde-interview-script/                         # standalone skill copy
system-design-study-coach/                           # standalone daily study coach
docs/                                                # GitHub Pages 12-week study plan
scripts/                                             # repo-level renderer test copy
```

## End-To-End Flow

After the plugin or skill is installed in a host:

1. User pastes a Hello Interview/API/system-design paragraph.
2. Or the user provides a public article URL; the skill first runs `scripts/fetch_url_text.py` and uses the extracted `title`, `outline`, `sections`, and `text` as source material.
3. User optionally specifies language, for example `in Chinese`, `用中文`, `in Spanish`, or `bilingual English and Chinese`. If no language is specified, the skill uses English.
4. The agent invokes `card` for visual source digestion, or `senior-sde-interview-script` when the user asks for candidate-style interview wording.
5. For long URL sources, the agent creates a short page plan first and renders one compact card JSON per page. Each page preview/link is returned in source order.
6. The skill tells the agent to create a diagram JSON object:

```json
{
  "title": "CAP in Interviews",
  "language": "English",
  "style": "excalidraw-plus",
  "layout": "comparison",
  "planning": {
    "complexity": "medium",
    "diagram_strategy": "comparison",
    "reason": "The source is a CP versus AP tradeoff."
  },
  "summary": "CAP is a partition-time product decision.",
  "task": "Ask which failure hurts more during a partition: stale data or failed requests.",
  "constraints": [
    "Partition tolerance is mandatory",
    "The choice affects storage, cache, replication, and fallback strategy"
  ],
  "blocks": [
    {
      "id": "cp",
      "lane": "left",
      "kind": "component",
      "title": "CP for expensive wrong state",
      "body": "Inventory, payment, and seat holds cannot confirm stale state. Use conditional writes, transactions, or strong reads; degrade instead of accepting double booking."
    },
    {
      "id": "ap",
      "lane": "right",
      "kind": "component",
      "title": "AP for freshness-as-UX",
      "body": "Browsing, feeds, and recommendations can tolerate short-lived stale data. Serve from replicas or cache, then converge asynchronously."
    }
  ],
  "connectors": [
    {"from": "cp", "to": "ap", "label": "same partition, different product priority"}
  ],
  "callouts": [
    {"title": "Partition-time choice", "body": "Once a network partition exists, the practical tradeoff is stale reads versus failed requests."}
  ],
  "talk_track": "I would first ask which failure mode the product can tolerate: stale data or temporary unavailability."
}
```

6. The agent runs the bundled renderer:

```bash
python3 scripts/render_interview_card.py \
  --content /tmp/interview-card.json \
  --out /tmp/interview-card \
  --slug interview-card
```

7. The renderer writes:

```json
{
  "preview": "/tmp/interview-card/interview-card-preview.svg",
  "excalidraw": "/tmp/interview-card/interview-card.excalidraw",
  "link": null
}
```

8. Codex/Cursor reply with the preview image, link/path, and copyable talk track. Claude Code terminal replies with local paths and the talk track. It includes a share link only after an explicit sharing request.

## Language Selection

Default output language is English:

```text
Use $card: <paste text here>
```

Chinese output:

```text
Use $card in Chinese: <paste text here>
```

Other languages:

```text
Use $card in Spanish: <paste text here>
```

Bilingual:

```text
Use $card bilingual English and Chinese: <paste text here>
```


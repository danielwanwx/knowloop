---
description: Turn hard text into a visual study card and talk track
argument-hint: [text]
---

Use the bundled `card` skill in this plugin to help the user digest the following material. Produce a source-aligned Excalidraw study card, editable link or path, and concise talk track. Prefer decision trees, comparison maps, pipelines, architecture-style blocks, callouts, and small talk-track notes over long article-like script blocks.

Default to English unless the user explicitly requests Chinese or another language. If no text was provided in `$ARGUMENTS`, ask the user to paste the text. Return the preview/link output plus the copyable talk track when the source is system design, API design, or technical study material.

Keep output local by default. Share or synthesize the current content only when the user explicitly requests that external action.

Text:

$ARGUMENTS

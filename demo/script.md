# Demo script and shot list (the human records the video)

Target **2:50-3:00**, 1080p MP4, unlisted YouTube, subtitles on, no music (voice-over normalised).
Numbers on screen must equal `docs/NUMBERS.md`. Setup: fresh tenant `demo` seeded with
`make demo`, the workspace open in one window and a terminal in the other, 1440x900, font >= 16px.

| # | Time | Visual | Say (own words) | Notes |
|---|---|---|---|---|
| 1 | 0:00-0:10 | Title card: "Pedigree — git blame and git revert for what an AI agent believes" + your name | one-line hook | hold 4s |
| 2 | 0:10-0:35 | A coding agent works in the terminal; the workspace shows lineage appearing as it goes | "Agents remember things and act on them. When one source turns out to be bad, nobody can say what it already affected." | if live capture is flaky, replay the seeded tenant |
| 3 | 0:35-1:05 | The graph grows: Source -> Memory -> Action -> commit; hover a node to show `via` (hook vs agent-reported) | "Captured out-of-band by hooks and the API into FalkorDB, one graph per tenant — the model never writes its own lineage" | zoom the legend once |
| 4 | 1:05-1:45 | Click the poisoned web Source -> **Revoke (dry run)** -> drag the depth slider 1 then 6 -> the taint wave reaches a commit and a push | "A join sees two things. The graph sees the commit six hops away — and can say why, along which path" | the numbers on screen come from the dry-run output |
| 5 | 1:45-2:10 | Two memories turn `preserved` with their supporting source; the bar chart from `evals/REPORT.md` (B4 vs Pedigree) | "A naive cascade deletes these. Pedigree keeps what has independent support — over-invalidation 0.2777 for the cascade in the deepest cell, 0.0 here" | use the generated chart, not a redrawn one |
| 6 | 2:10-2:35 | The agent attempts `git push`; the hook prints the deny JSON with the path; then ask `impact` for an id we never recorded | "The gate answers with evidence. Unknown is unknown, not safe." | show the JSON, do not paraphrase it |
| 7 | 2:35-3:00 | Terminal: `make eval-quick` summary; tests green; isolation test; end card with repo URL, tracks, "remove FalkorDB and nothing works" | "Measured by committed scripts; tenant isolation tested against the failure class in Graphiti issues #1331/#1676" | pre-generate the output if the run is slow |

Rehearse three times, record two takes, keep a pre-recorded fallback clip per scene. Upload
unlisted, then paste the URL into `README.md` and `docs/submission/SUBMISSION.md`.

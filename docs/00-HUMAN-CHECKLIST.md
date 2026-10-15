# 00 - HUMAN CHECKLIST (only things the agent cannot do for you)
All times IST. Event: Oct 15 12:01 AM -> **Oct 18 11:59 PM**. Feature freeze Sun 3 PM. Aim to submit **Sun 9 PM**. Tags: **[V]** verified page exists/behaves as stated; **[U]** unverified - confirm yourself.
Total human time over the weekend: ~4-5 hours, mostly Sunday.

## Step 1 - Register on WeMakeDevs (5 min) - DO FIRST, tonight
- Open https://www.wemakedevs.org/hackathons/falkordb -> Sign in / create a free account -> **Register now** (solo is fine). The team and the submission are managed from the same panel [V per FAQ]. You cannot submit without registering.
- While there, open https://www.wemakedevs.org/hackathons/falkordb/submit (signed in) and screenshot the fields: the public fetch only shows a loading screen, so the exact fields are **[U]**. Save the screenshot into `docs/submission/form-fields.png` (do not commit anything private).

## Step 2 - Ask organizers on Discord (10 min) - tonight
Join the FalkorDB Discord (https://discord.com/invite/Y2mMT9VdMy [V link responds]; the event page says it is open all event) and, if you like, the WeMakeDevs Discord (https://discord.gg/wemakedevs). Post this in the hackathon / help channel (exact text):
```
Hi organizers! Solo participant here, a few quick clarifications for Graph Hacks:

1) Tracks: the launch blog says "You enter one track, and one submission is judged in it", but Rules #5 and the FAQ say we may enter one, two or all three tracks and must name each. Which is correct? If multiple tracks are allowed, is the same repo judged separately in each?

2) Blog side prize (AirPods 5): where should the post be published (dev.to, the WeMakeDevs blog, anywhere public?) and how do we submit the link (a field on the submit form, or in Discord)? Any deadline other than Oct 18, 11:59 PM IST?

3) Is there a maximum demo video length or preferred hosting (YouTube unlisted OK)?

Thanks!
```
Record the answers in `docs/DECISIONS.md` (ADR-000 / ADR-001). Until answered, the default is: enter **Track 2 (primary) + Track 1 (secondary)**, skip Track 3.

## Step 3 - GitHub repo (10 min) - tonight
- Create an **empty public repo** under your account (https://github.com/new, no README/license: the agent creates them). GitHub names only collide per owner, so `pedigree` is available on your account. Name check (GitHub search 2026-10-15): `pedigree-agent` (SHAI-gautam-upadhyay, 2025, no description), `agentic-ai-pedigree`, `PedigreeAI` (rmkanderson) exist elsewhere but are unrelated; PyPI `pedigree` is taken (we do not publish to PyPI); `pedigree-ledger`, `pedigree-memory`, `beliefblame` were free on PyPI/npm and had no GitHub hits. Nearby but different project: `mesa-dot-dev/agentblame` (AI-line attribution for git; 102 stars) - mention it in the README as related, not as a competitor.
- **Recommended name:** `pedigree`. **Alternates:** `pedigree-ledger`, `beliefblame`.
- Make it public from the first push (the first-commit timestamp is your evidence for the "new work" rule). 
- Give the agent push rights **without pasting tokens into chat**: run `gh auth login` once on the machine (https://cli.github.com) or set up an SSH key; then tell the agent the remote URL. If you prefer, tell the agent not to push and push yourself at checkpoints.

## Step 4 - API keys (optional; 10 min) - the Pedigree core needs NO LLM
Only needed for a live LLM-driven demo agent. No card required [D]:
- Gemini: https://aistudio.google.com/apikey [V page responds]. Free tier; limits visible in AI Studio; **free-tier data may be used to improve Google products** - never send private data.
- Groq: https://console.groq.com/keys [V]. Free: gpt-oss-120b/20b, qwen: 30 RPM, 1K RPD, 8K TPM, 200K TPD (https://console.groq.com/docs/rate-limits).
Put them **only** in `.env` (Step 7). Do not paste keys in chat.

## Step 5 - FalkorDB Cloud Free (fallback only; 10 min, Saturday)
Only if the single-container Render deploy fails. https://app.falkordb.cloud/signup [V]: free tier, no card, 100 MB, AWS/GCP, **no TLS, no persistence**, stops after 1 day inactive, deleted after 7 [D https://docs.falkordb.com/cloud/tiers/free]. Create an instance, copy host/port/password into Render env vars (not into the repo).

## Step 6 - Render account (5 min, Friday)
https://dashboard.render.com [V responds]: sign up with GitHub. Free web service, no card [D https://render.com/docs/free]: 512 MB, sleeps after 15 min idle (~1 min cold start). When the agent says the Dockerfile is ready: New -> Web Service -> connect the repo -> Runtime **Docker** -> instance type **Free** -> add env vars from `.env.example` (values only in Render's dashboard) -> Deploy. Open `/readyz`.

## Step 7 - Keep secrets safe (5 min)
`cp .env.example .env && chmod 600 .env`; put keys there only; confirm `.env` is in `.gitignore`; run `bash scripts/check_secrets.sh`; never screenshot or screen-record `.env`/terminals with tokens; Render keys live in its dashboard. If a key leaks (even in a commit), **revoke it immediately** at the provider and rotate; then ask the agent to purge it from history before submission. Rotate all keys after the hackathon.

## Step 8 - Decide before Friday (5 min)
Tracks (default T2 + T1) | repo name | blog platform (default dev.to) | video host (YouTube unlisted) | whether you personally record voice-over (recommended: yes, your own words) | which runtime you dogfood (OpenCode, and Claude Code if installed).

## Step 9 - Understand your own project (Sat/Sun, 90 min total) - this is rule #12
Rules #12-13: you must be able to explain the graph model, queries, architecture and decisions; fully AI-generated work without human understanding may be rejected. Read `docs/WALKTHROUGH.md` (the agent writes it), run each query once yourself, and rehearse the Q&A in `03-EVAL-AND-DEMO.md` section 10. Write 3-5 sentences in your own words in `AI_DISCLOSURE.md` about what you decided and verified.

## Step 10 - Submission form (Sun, 20 min)
Rules #10 require: public repo, README (setup + data model + queries/algorithms), demo video, live deployment or complete local instructions, the track(s). Likely fields **[U]**: project name, tagline/description, repo URL, demo video URL, deployment URL, tracks, team, maybe blog link. Use `docs/submission/SUBMISSION.md` (agent-written text). Open the form early (Sat) to see the real fields; submit by **Sun 9 PM**; re-open after submitting to confirm it saved; screenshot the confirmation.

## Step 11 - Blog post (Sun, 60 min)
Rules do not say where or how to submit the blog **[U - answered by Discord question 2]**; the main page only says "Write a blog post about your project. The best post wins a pair of AirPods 5." Default: publish on **dev.to** (https://dev.to, free, no card) with the draft from `docs/blog/`, add the repo + video links, tag `#hackathon #ai #graphdb #security`; post the link in Discord and in the form if a field exists; mention it in the README. Publish **before 5:30 PM Sunday**. (The organizers' own blog lives at https://www.wemakedevs.org/blogs - submitting there is **[U]**.)

## Step 12 - Demo video (Sun 3:00-4:30 PM, 90 min)
Use OBS Studio (https://obsproject.com, free) or QuickTime/Game Bar. 1080p, <= 3:00, your own voice-over (clear > polished), follow `demo/script.md` + `demo/shotlist.md` (agent-written from the real UI). Tips: dark theme, browser zoom 125%, close notifications/tabs/`.env`, test mic first, record in 2 segments, read numbers only from the NUMBERS screen, show the live URL **and** the local run, end with repo URL. Upload to YouTube (unlisted OK), open the link logged-out to confirm it plays, keep the mp4 as a backup.

## Step 13 - AI-use disclosure (paste into `AI_DISCLOSURE.md` and the form)
```
AI assistance disclosure: I built Pedigree with AI coding assistants - OpenCode (run through T3 Code) using [MODEL NAME(S) YOU ACTUALLY USED] - organised as a multi-agent workflow (orchestrator, builder, QA, security red-team, domain researcher, architect, eval statistician, technical writer). The assistants wrote most of the code, tests and first drafts of the docs under specifications and acceptance tests that [EDIT: describe what you personally designed]. I reviewed and verified [EDIT: what you personally verified - e.g. ran the test suite, ran the benchmarks, reviewed every Cypher query, ran the demo end-to-end]. Every benchmark number in the README and blog is produced by committed scripts (make eval) and listed in docs/NUMBERS.md. I can explain the graph model, the queries and the architecture; docs/WALKTHROUGH.md and docs/DECISIONS.md record them in plain language.
```
Edit the bracketed parts so every statement is true.

## Step 14 - T-minus schedule to the deadline
| When (IST) | T-minus to Oct 18 11:59 PM | You do |
|---|---|---|
| Thu Oct 15 7:00 PM | T-76h | Steps 1-3; start the agent with `06-MASTER-PROMPT.md`; answer its first batched message (<= 20 min) |
| Thu ~11:30 PM | T-72h | Checkpoint 0: confirm repo is receiving pushes; go to sleep |
| Fri 9:00 AM | T-63h | Read PROGRESS; unblock anything in the batch; Step 8 decisions |
| Fri ~9 PM | T-51h | Checkpoint 1: look at the UI; go/no-go on scope; Step 6 (Render) |
| Sat 9:00 AM | T-39h | Read Discord answers; Step 10 dry look at the form |
| Sat ~9 PM | T-27h | Checkpoint 2: open the deploy URL; confirm tracks |
| Sun 11:00 AM | T-13h | Read README and the draft blog; Step 9 rehearsal |
| Sun 1:00 PM | T-11h | Checkpoint 4: sanity-check every claim you cannot explain |
| **Sun 3:00 PM** | **T-9h** | **FEATURE FREEZE** (agent: bug-fixes + docs only) |
| 3:00-4:30 PM | T-9h..T-7.5h | Record the video (Step 12) |
| 4:30-5:30 PM | | Publish blog (Step 11) |
| 5:30-6:30 PM | | Fill the form (Step 10) |
| **9:00 PM** | **T-3h** | **Be submitted.** Screenshot confirmation |
| 9:00-11:59 PM | | Buffer: link checks only; do not merge features |
**Final checklist (tick all):** repo public + README renders | LICENSE | AI_DISCLOSURE.md | demo video public/unlisted link plays logged-out | live URL `/readyz` OK (or local setup verified from a clean clone) | tracks named | blog published and linked | NUMBERS.md matches README/blog (`python scripts/check_numbers.py`) | secret scan clean on history | form submitted + confirmation screenshot | Discord post with links.

## Step 15 - What to do if the agent gets stuck
| Symptom | Do this |
|---|---|
| Repeats the same failing step / apologises in loops | Paste: `STOP. Write the exact error, what you tried (commands + outputs) to docs/consults/NNN/question.md, launch the three consultants per docs/04 section 4, then follow decision.md. If still failing after that, log in KNOWN_ISSUES and apply the cut order.` |
| Context huge / forgets the plan | Paste: `Compact. Then follow the resume protocol in docs/04 section 10: read docs/PROGRESS.md CURRENT STATE, docs/05-PHASES.md, git log -20, run make test-quick, check TZ=Asia/Calcutta date, continue.` |
| Subagents unavailable / `@orchestrator` missing in T3 Code | Use docs/04 section 12: either role-switch ritual in one session, or open one chat per role with the role prompt from `.opencode/agents/<role>.md` |
| FalkorDB will not start | `redis-cli -p PORT PING`; `redis-cli -p PORT MODULE LIST` (expect `graph ... ver 42201`); check `ls -l bin/*.so` (needs `chmod +x`); port busy (`lsof -i :PORT`); glibc >= 2.39 required by the wheel (Ubuntu 24.04+); two servers must not share `DATA_DIR`. Fallback: the wheel's bundled 4.18.3 `.so` or Docker image `falkordb/falkordb:v4.22.1` |
| Scope creep (new features, LLM dependence) | Paste: `Out of scope. Re-read docs/05-PHASES.md; do only the next unfinished item on the ladder. Core must work with no LLM.` |
| Suspected fabricated numbers/claims | Paste: `Run python scripts/check_numbers.py and show the output. Remove every number not in docs/NUMBERS.md. Re-run make eval-quick and show the CSV paths.` |
| Free LLM rate limits (429) | Switch provider in `.env` (`LLM_PROVIDER=groq` <-> `gemini`); demo works without an LLM using recorded scenarios |
| Agent asks you questions mid-run | Answer once; remind it: `Batch all human questions into one message per docs/04 section 8.` |
| Behind schedule at Sun 11 AM | **Minimum Viable Submission:** freeze whatever P0+gate works; README honest about what is missing (Status table from FEATURES.md); record the video of what works; local setup instructions verified from a clean clone; submit by 9 PM. A working small thing beats a broken big thing (the organizers' own "one feature that runs beats five that almost do" philosophy appears in their AWS event criteria: https://www.wemakedevs.org/aws/first-commit). |

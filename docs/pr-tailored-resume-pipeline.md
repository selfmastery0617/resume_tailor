# Tailored resume pipeline

Builds on `dev` after the `fix-download-directory` merge. Six feature commits
plus one merge commit that resolves three conflicts.

## What this adds

**User-created templates with a visual builder.** Built-in templates stay
source-controlled; user templates live in `template_definitions` and are edited
by dragging elements. The `layout-v1` renderer drives both the preview and the
PDF, so a user template no longer previews one way and prints the default
structure. `generated_resumes` snapshots the layout as well as the template
id/version, because a user template is mutable and could otherwise retroactively
change what a past PDF was rendered from.

**A persistent DeepSeek browser profile.** Storage-state snapshots froze cookies
at one instant and went stale. A persistent Chromium profile behaves like a real
browser profile, so a sign-in lasts as long as it naturally would. Sign-in
happens in an embedded panel on Settings, because cookies set in the user's own
Chrome are httpOnly and origin-scoped and cannot be read from this process.

**Experience extraction with a live progress console.** Ranks the challenges in
`database.json` against a job description and writes bullets for two roles —
Job 1 from the company chosen in Settings, Job 2 picked automatically from the
FAANG entries. Semantic ranking via sentence-transformers with a deterministic
lexical fallback, so it degrades rather than fails. The console streams every
decision, so a surprising result can be explained rather than just observed.

**Tailored resume PDFs written to the output folder**, at
`<outputFolder>/<mm-dd-yy>_<Company>_<Job Title>/<Profile>_resume.pdf`. The
extraction's two roles replace the profile's experience section; name, contact
details, education, skills, template and styling still come from the profile.

**One DeepSeek chat per job, plus a summary step.** Previously each prompt
opened its own browser and its own conversation. Now all four prompts share one
chat, so each still has the earlier answers in context. A fourth step writes the
resume summary from the bullets just generated, using an editable prompt in
Settings.

**A simpler Jobs table.** Skills and Experience were intermediate results, so
they are reported in the console and the table keeps one Resume action that
extracts when needed and then renders the PDF.

## Notable bug found

Telling a new DeepSeek reply from the one still on screen cannot be done by
counting message bubbles: DeepSeek virtualises the message list and unmounts
older messages as a chat grows, so the count *drops* mid-conversation (observed
going 11 -> 2) and "wait for bubble N+1" never completes. That silently timed
out turns 3 and 4 of every job. It now compares against the previous reply's
text, which is immune because the newest message is always mounted.

Measured on one job: 4 of 4 turns land instead of 2, and 45s instead of 163s.

## Conflict resolutions

| File | Resolution |
| --- | --- |
| `frontend/src/App.tsx` | `describeExtractError` was refined on `dev` and deleted here with the Skills column it served. Kept the deletion — its intent (prefer the backend's own message) already lives in `describeError`. |
| `frontend/src/components/ProviderConnect.tsx` | Same expression, extracted here into a `detail` const with an added "Verifying the saved session…" state. Kept this side as the superset. |
| `backend/app/services/deepseek/login.py` | **Both branches independently fixed the same bug** — login reported success before the user had authenticated. Combined rather than picked: this side's persistent profile, two-confirmation loop and cancel detection, with `dev`'s `has_usable_user_token` inside `_is_signed_in`. That closes a false positive this side still had — DeepSeek writes `{"value": null, "__version": 0}` pre-auth, a truthy string that passed a bare `bool(token)` check. |

The output folder keeps `dev`'s native picker rather than the text input this
branch built on: a dialog that validates on selection is better, and the resume
profile picker and filename preview sit around it unchanged.

## Verification

- `npx tsc -b` clean; backend imports clean
- Merged app exercised in a browser: their read-only input + `Select folder…`
  picker, this branch's resume-profile dropdown, three numbered prompt editors,
  and the reduced column set all render with no console errors
- `has_usable_user_token` rejects the pre-auth wrapper and accepts a real token;
  `REQUIRED_CONFIRMATIONS` still 2
- Full pipeline run end to end: 6 + 8 bullets, summary, PDF saved to the
  configured folder, text verified inside the PDF

## Not included

- Batch "Generate Resumes" across many jobs at once
- `ExperienceCellRenderer.tsx`, `ExperienceModal.tsx` and `SkillsCellRenderer.tsx`
  are now unused; left in place rather than deleted

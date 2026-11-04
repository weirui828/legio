# Camp Legio — a cozy legion-camp webapp for legio's centuriae

## Style reference (read these first if you can see images)

Two mockups live in `docs/ui/reference/`:

- `camp-home.jpg` — the camp: an illustrated, softly painted Roman camp where
  every tent is a project, with cream/parchment chrome, pill navigation, a
  denarii counter and a STATUS meter.
- `tabula-operum.jpg` — a tent interior: a wooden **TABULA OPERUM** board with
  three columns of pinned notes, and a chibi role working at a desk, warm-glow,
  floating hearts and sparkles.

They are **style references only**. Read them with an image-capable tool if you
have one; the written tokens below are authoritative, and if an image and the
text disagree, the text wins. Do not ship these JPEGs, do not copy their
baked-in gibberish labels, and do not trace them as assets.

## The point (do not rescope this away)

A local, read-only webapp that shows legio's centuriae as one cozy Roman camp.
The camp is one illustrated scene, one tent per project. Click a tent and you
are inside that centuria's command tent: a board of its jobs, its cast of
roles, and the role that is working right now glowing at the desk.

It is started explicitly (`legio web`), binds `127.0.0.1` only, and stops with
Ctrl-C. No auth, no database, no external services, no network assets, no
build step.

## What to build

- `legio web [--port 8766] [--root DIR]` serves the app and
  `GET /api/camp` -> `{"projects":[{"name":..., "jobs":[...], "cast":[...]}]}`.
- `web/` at the repo root holds the HTML/CSS/JS/SVG assets (no bundler).
- The UI is strictly read-only: it never writes job.json, never runs an agent,
  never transitions a job, never closes a PR.

## Pages

### 1. CASTRA — the camp (`/`)

One illustrated scene, not a plain card grid: a warm ground plane, a winding
path, trees and props, and a cluster of round canvas tents with red pennants
and name banners. Each tent is one discovered centuria:

- banner text: `LEGIO <roman ordinal> · <real project name>`
- small status ribbon: counts from `job view` (`active` / `waiting` / `done`)
- hover: pennant wiggles, tent tilts ~2°, banner lifts; click: opens the tent
- tiny chibi legionaries stroll between tents (CSS animation; may be cut)
- empty camp: one unbuilt tent plot and "No legions yet. Plant the first
  standard."
- a project that fails to read is a visibly warped/muddy tent with a small red
  pennant and a safe one-line reason; it must never look like a healthy tent.

Chrome, from the reference:

- top-center pill nav with tiny icons: **CASTRA** (this page), **MILITES** (the
  cast), **LEGIONES** (projects list), **NUNTII** (what waits on you).
- top-right: an avatar medallion, a **denarii** counter (sum of `cost_usd`,
  formatted as denarii; may be cut), and a **STATUS** meter (how many projects
  read cleanly).
- bottom-left: **NOTIFICATIONS** panel folding out of a bell (the waiting jobs).
- bottom-right: **HELP**, an overlay that explains the metaphor and the keys.

### 2. The tent (`#/legion/<name>`)

A tent interior: cream canvas ceiling, dusty-blue drapes, wooden floor, a rug,
plants, and a heart-on-shield on the wall.

- **TABULA OPERUM** — the big wooden board, three columns:
  **AD FACIENDUM** (waiting), **IN CURSU** (active), **FACTUM** (terminal).
  Lane assignment uses only the flags in `job view`; the UI must not know
  stage semantics.
  Each job is a pinned parchment note: title, id, issue/PR, round,
  gate mark, review marks, cost. Notes are pinned with a red wax seal and
  carry a small glyph for their state.
- **The working role** — a chibi of the role named in `live` sits at the desk,
  writing on a scroll, with a warm glow, floating hearts and sparkles and a
  speech bubble naming the job. When `live` is null the desk is empty: a
  soldier dozes, "z z z", and a line like "The tent is quiet. Nobody is
  sweating yet."
- A small cast strip (see MILITES) may sit on the left of the board.

### 3. MILITES — the cast (`#/legion/<name>/cast`, or a fold-out panel)

The eight roles as character cards: name (Tesserarius, Signifer, Fabri,
Probator, Medicus, Mensor, Librator, Primus Pilus), the role's `function` and
one-line `duty`, and a state: on duty / resting / off-stage. The on-duty card
matches the chibi at the desk.

## Data and boundaries

- `centuria cast --json` -> `[{"role","function","duty","tier"}]`. The source is
  each role file's frontmatter (`.centuria/roles/*.md`); add a `duty:` line to
  each role file if it is missing. Old centuria copies may not have this: the
  UI must degrade gracefully.
- `job view` gains `"live": {"role","round","started"} | null`.
- `bin/run` writes `.centuria/jobs/<id>/live.json` immediately before spawning
  an agent and removes it after the agent exits. A crashed run leaves a stale
  file; the next spawn overwrites it, and the UI treats a `live.json` older
  than 10 minutes as "last seen Nm ago" (not glowing).
- Poll `/api/camp` every 2s; no fake activity and no stage-based guessing.
- **legio must stay pipeline-blind**: no role names, no stage semantics, no
  `build.md`/`VERDICT:` knowledge in `legio`; role names, duties and live state
  arrive from centuria. The self-check
  `grep -cE 'tesserarius|build\.md|VERDICT:' legio` must stay 0.
- Reuse the read-only HTTP layer already written at commit `a57dbd5` on
  `origin/centuria/002-add-api-to-legio` (closed PR #5) instead of rewriting it.
- `/api/camp` exposes only documented fields: no worktree paths, prompts, logs,
  config, secrets or artifact bodies.

## Visual language (from the reference; the reviewer cannot see pixels)

Palette (CSS custom properties on `:root`; these are sampled from the
reference and curated):

- warm outline `#5D3A2E`
- parchment `#FCEED9`, paper `#FBE1C7`, cream `#F7E7CC`
- peach `#EFC896`, tan `#E7B686`, shadow-tan `#D4A076`
- terracotta `#C15850`, brick `#9C5641`
- olive `#81905B`, sage `#B9BB67`
- dusty blue `#98AFC1`
- blush `#F2B8B5`
- brass/gold `#E8B84B`
- wood `#B17B68`, beam `#8D5049`
- glow `#FFE9B8`

Line and shape: 2–3px **warm brown** outlines (never black), no pure white,
no neon, no harsh flat drop shadows; soft two-tone shading only; rounded
corners 12–20px; sticker-ish composition on cream paper. Texture: a subtle
paper grain made of CSS gradients; no image textures.

Type: display — `"Iowan Old Style", "Palatino Linotype", Georgia, serif`, with
wide letter-spacing for the Latin caps; UI — `"Avenir Next", Nunito,
system-ui, sans-serif`. No downloaded fonts.

Composition: desktop-first at ~1440x900 like the reference; the camp is one
scene; the tent is board + desk. Mobile stacks the board under the desk.
Motion: calm 2–4s loops; respect `prefers-reduced-motion`.

Tone: warm, flirty, campy, affectionate. This is intentionally queer-camp
Roman comic style — **do not tone it down**. PG-13: no gore, no fetish gear, no
slurs. The floating hearts and sparkles are part of the working-role treatment.

Copy deck (use these exactly; Latin chrome with tiny icons):

- nav: CASTRA · MILITES · LEGIONES · NUNTII
- board: TABULA OPERUM · AD FACIENDUM · IN CURSU · FACTUM
- working bubble: "Fabri is hammering — do not disturb." (role-aware)
- quiet tent: "The tent is quiet. Nobody is sweating yet."
- empty camp: "No legions yet. Plant the first standard."
- read error: "The messenger lost the way." + safe one-line reason
- status meter label: STATUS; wallet: denarii

## Art fidelity (be honest about what code can paint)

The reference is soft gouache; this job produces code, so it will produce
inline SVG/CSS in the same palette and shape language — cozy-flat, not
painterly. That is acceptable for this PR.

Generated sprites may be provided in `web/assets/` (spec and prompts in
`docs/ui/assets.md`); if a named file exists, compose it, and if it is missing,
draw the simplest SVG placeholder in the same palette:

| file | used for |
|---|---|
| `camp-ground.jpg` | home scene background |
| `tent-interior.jpg` | tent interior background |
| `tent.png`, `tent-warped.png` | project tent / read-error tent |
| `board.png` | the TABULA OPERUM board behind the notes |
| `note.png` | one job note |
| `desk.png` | the working desk |
| `role-<role>.png` | one chibi per role (see `centuria cast`) |

Never fetch images, fonts or icons from the network, and never ship or trace
the reference JPEGs.

## Acceptance

- [ ] `/` renders one camp scene with one tent per discovered centuria; tent
      banners show the real project names; counts match `legio ls`.
- [ ] A tent route shows TABULA OPERUM with all jobs in the correct lane
      (waiting / active / terminal from the flags) and the cast with duties.
- [ ] The role named in `live` is drawn at the desk with the working treatment
      (`data-state="working"`, hearts/sparkles); no `live` means no role
      highlighted; stale `live` means "last seen".
- [ ] `/api/camp` returns only documented fields; broken projects produce a
      visible error, not an empty healthy camp.
- [ ] Browsing changes nothing: `git status` in each project stays clean and no
      `job.json` mtime moves.
- [ ] No network requests other than `/api/camp`; no external assets; the two
      reference JPEGs are not shipped.
- [ ] `prefers-reduced-motion` disables the loops; nav and tents are keyboard
      reachable with labels.
- [ ] stdlib `unittest` fixtures with fake centuriae cover the endpoint, the
      route HTML hooks, empty/error states, lane assignment and the read-only
      rule.

## Must keep / may cut

Must keep: the camp-as-scene home, the TABULA OPERUM tent with the working
chibi, the palette/shape language, the nav, empty and error states, read-only.

May cut if the PR is running long: the MILITES separate route (a cast strip is
enough), denarii, the strolling soldiers, the notifications fold animation,
job-detail notes, mobile polish.

## Out of scope

Auth, remote access, databases, frameworks or build steps, writes to the
pipeline, websockets/live push, mobile app, push notifications, new
dependencies, shipping or tracing the reference JPEGs.

## Verification

`python3 -m unittest discover -s tests -p 'test_*.py'` and `checks.sh`; then the
human opens `legio web` at the needs-human stage and judges the look.

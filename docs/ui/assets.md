# Camp Legio — AI image asset list

Everything the webapp needs that code cannot paint. Generate in this order:
the two backgrounds first, then tents, then the tent objects, then the cast.

## How to generate (read once)

**Use the two mockups as style reference in every generation.** They are style
references only — do not slice, trace or ship them:

- `docs/ui/reference/camp-home.jpg`
- `docs/ui/reference/tabula-operum.jpg`

**Style block** — prepend to every prompt:

> Cozy storybook gouache illustration, soft watercolor texture, hand-drawn warm
> brown (#5D3A2E) outlines, rounded friendly shapes, pastel palette: parchment
> cream #FCEED9, peach #EFC896, terracotta #C15850, olive #81905B, dusty blue
> #98AFC1, blush #F2B8B5, brass #E8B84B. Warm top-left light, soft two-tone
> shading, gentle whimsical mood, queer-camp friendly, clean edges, high detail.

**Negative prompt:**

> text, letters, numbers, typography, watermark, signature, logo, border, frame,
> UI elements, photo, photorealistic, 3D render, harsh black outlines, neon,
> oversaturated, busy background, gradient background, drop shadow

**Rules for every image:**

- **No text of any kind.** All labels, banners, notes and names are HTML over
  the art; generated letters are gibberish and will be rejected.
- Generate at ~2x the final size (the sizes below are final targets).
- Attach both reference mockups as style reference; keep the same seed/model
  settings across all sprites so the cast and props match.
- **Sprites**: isolated on a flat solid background (pure white preferred; or
  export transparent PNG if your tool supports alpha), generous margin, **no
  ground shadow, no background scenery** — the app draws shadows itself.
  If the tool cannot do transparency, flat white is fine; I will cut it out.
- **Backgrounds**: scene only — no UI chrome, no labels, no frames.
- Keep the line weight and lighting consistent between all assets. Put the
  generated files in `docs/ui/assets-src/` with the exact filenames below.

## P0 — the minimum for the reference look (15 files)

### Backgrounds (opaque, 2560x1440, 16:9, JPG)

**`camp-ground.jpg`** — the home scene's ground layer.
Prompt: *A softly painted Roman legion camp ground seen from a high three-quarter
view: sage-green grass, a winding sandy path crossing the frame, small stones,
olive trees, bushes, wooden crates and lanterns, distant soft hills and a few
very small distant tents near the horizon, warm afternoon light. Keep the lower
two-thirds open grass with no foreground tents; no people.*

**`tent-interior.jpg`** — the inside of one command tent.
Prompt: *Inside a cozy Roman command tent: cream canvas ceiling with dusty-blue
drapes tied at the sides, wooden floorboards, a soft round rug, potted plants,
a wooden chest, a round shield with a pink heart painted on it hanging on the
back wall, warm lantern light. Leave the center-left wall/floor area and the
right side open (a board and a desk will be placed there); no people.*

### Tents (transparent PNG, 1024x1024, front view, full tent in frame)

**`tent.png`** — a project's tent on the camp map.
Prompt: *A single round Roman canvas tent seen from the front, cream canvas with
soft peach shading, a red pennant on the top pole, ropes and pegs, a warm glow
from the entrance, cute and friendly. No name banner, no text, no people.*

**`tent-warped.png`** — the error state for a project that cannot be read.
Prompt: *The same round Roman canvas tent but sagging and warped, a patched grey
canvas, one broken pole, a small red warning pennant, a muddy puddle at its
base; still cute and sad, never scary or gross.*

### Tent objects (transparent PNG)

**`board.png`** — the TABULA OPERUM board (1600x1200, 4:3).
Prompt: *A large wooden notice board seen from the front: warm timber planks
with a carved wooden frame, a wide blank header plank across the top, and three
blank vertical parchment panels separated by wood strips, two small carved
finials. No text, no notes, no posts.*

**`note.png`** — one job note pinned to the board (512x512).
Prompt: *A single small blank parchment paper note with softly torn edges and a
tiny red wax seal at the top center, no writing, isolated.*
(Generate 2-3 slight variations and name them `note-1.png`, `note-2.png`,
`note-3.png`; `note.png` is enough if you only make one.)

**`desk.png`** — the working desk the chibi sits behind (1200x800).
Prompt: *A small wooden writing desk seen from the front, with an unrolled blank
scroll, an inkwell and a white quill resting on it, warm wood, cute proportions,
no person, no text.*

### The cast — eight chibi roles (transparent PNG, 1024x1024 each)

All eight must read as **one cast**: same chibi proportions (about 2.5 heads
tall), same cream tunic with terracotta leather lorica trimmed in brass, same
face and line weight, full body including feet, standing, facing slightly left.
Each gets one prop and one accent. PG-13, friendly, no violence, no weapons.
Best consistency: generate one 4x2 sprite sheet (4096x2048, flat background,
even cells) and slice it; otherwise generate them one by one with the same
style reference and seed.

Prompt template: *A cute chibi Roman legionary, about 2.5 heads tall, friendly
smile, rosy cheeks, full body standing, cream tunic, terracotta leather lorica,
brass trim, [PROP], [ACCENT], isolated.*

| file | prop | accent |
|---|---|---|
| `role-tesserarius.png` | a big brass gate key | doorkeeper's hooded cloak, small lantern |
| `role-signifer.png` | a tall standard with a heart emblem | braided hair, cream sash |
| `role-fabri.png` | a wooden mallet and a chisel | leather work apron, rolled sleeves |
| `role-probator.png` | a large magnifying glass | a wax tablet under the arm |
| `role-medicus.png` | a mortar and pestle | herb satchel, bandage roll |
| `role-mensor.png` | a folding wooden ruler | surveyor's cap, plumb line |
| `role-librator.png` | a brass spirit level | engineer's cap, measuring staff |
| `role-primus-pilus.png` | a whistle and a laurel wreath | red commander's cloak |

## P1 — worth generating if you have the energy (7 files)

**`tent-open.png`** (1024x1024) — same tent with the flap open and warm light
spilling out, for hover/active state.
**`logo.png`** (1024x1024) — *a small emblem: a Roman legionary helmet in
profile with a heart-shaped crest, brass and terracotta, isolated, no text.*
**`avatar.png`** (512x512) — *a cute Roman citizen portrait bust, warm smile,
laurel wreath, cream and terracotta, isolated.* (the top-right medallion)
**`mascot-eagle.png`** (512x512) — *a chubby friendly eagle mascot wearing a
tiny laurel, isolated.* (the HELP button; in the three-panel dashboard it
carries the "needs you" messages and rides on Legatus's shoulder)
**`seal.png`** (256x256) — *a single red wax seal blob, isolated.*
**`soldiers.png`** (2048x512 sheet, 4 cells) — *four tiny chibi legionaries
walking in different directions, side view, sprite sheet, flat background.*
(ambient walkers on the camp map)
**`hearts-sparkles.png`** (512x512) — *a small cluster of blush-pink hearts and
warm sparkles, isolated.* (floating around the working role)

## P2 — only if you want the last 10% (optional)

- `icons.png` (1024x1024 sprite sheet) — small rounded UI icons in warm-brown
  line style: tent, helmet, laurel, chat bubble, bell, coin, heart, level.
  (The app can use inline SVG instead, so skip if it is a hassle.)
- `tent-alt-1.png`, `tent-alt-2.png` (1024x1024) — two more tent colourways so
  the camp does not look repetitive.
- `role-<name>-working.png` x8 (512x512) — the same eight chibis seated at a
  desk, writing with a quill. Optional: the app can put the standing chibi
  behind `desk.png` and animate it, which reads fine. Generate these only if
  you want the exact reference pose for the glowing role.

## Legatus — the legio agent (2 files)

Legatus is the assistant in the dashboard's right panel: the one you talk to,
who knows every centuria and proposes the `legio` commands you approve. He is
**not** one of the eight roles. He never works a job stage, so he must never be
mistaken for one: same style as the cast, but he reads as the one in charge.

- **Same world as the cast:** same gouache style, line weight, face and warm
  top-left light, so he clearly belongs to the camp.
- **But set apart:** slightly older and taller than the chibis (about 3 heads
  tall instead of 2.5), a calmer pose, and the only character in **imperial
  purple**. No role uses purple, so his chat messages are recognisable at a
  glance.
- **Handsome, and still cute:** tousled dark curls, a warm easy half-smile,
  soft rosy cheeks, kind eyes. Charming, not stern; no armour bulk, no helmet.
- **Props:** a stylus and a wax tablet (he takes your orders), a laurel wreath,
  and a tiny chubby eagle perched on his shoulder. The eagle is the same
  character as `mascot-eagle.png`: the eagle carries the "needs you" messages,
  so the two belong together.

**`role-legatus.png`** (1024x1024) — standing, full body including feet.
Prompt: *A cute, handsome young Roman legate, about 3 heads tall, slightly older
and taller than the chibi legionaries, tousled dark curly hair, warm easy
half-smile, kind eyes, rosy cheeks, laurel wreath, white tunic with an
imperial-purple sash knotted around a brass breastplate, short purple cloak,
holding a wax tablet and a stylus, a tiny chubby eagle with a laurel perched on
his shoulder, relaxed confident pose, full body standing, facing slightly
left, isolated.*

**`role-legatus-working.png`** (1024x1024) — the same character seated at the
same desk as the cast's working sprites, for the chat header and his avatar.
Prompt: *The same handsome young Roman legate seated at a small wooden desk,
writing on a wax tablet with a stylus, looking up with a warm smile, the tiny
eagle perched on the desk corner, same purple sash and laurel wreath, isolated.*

Wiring notes: `web/tools/prepare_assets.py` crops every `head-<role>` from that
role's `-working` sprite, but only for the eight names in its `ROLES` list, so
add `legatus` there (or a separate list) to get `head-legatus.webp`. Until the
art exists, the prototype uses `avatar.webp` (the laurel bust) as a stand-in.

## Delivery

- Put everything in `docs/ui/assets-src/` using the filenames above.
- Keep the originals; do not downscale — I will normalise, slice, cut
  backgrounds and optimise for the web.
- Tell me when they are there. I will then wire the job: the sprites go into
  `web/assets/` in the job branch, the code composes them, and any missing
  asset must fall back to an inline-SVG placeholder (the issue requires that).

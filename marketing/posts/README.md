# PrepWithTee social posts

A template engine for Instagram posts. Each folder is one **series** with its own look;
each `posts.json` holds the words. Change the words, re-run, and you get new PNGs.

```
.venv\Scripts\python marketing\posts\build.py                  # build + render everything
.venv\Scripts\python marketing\posts\build.py --series memes   # one series
.venv\Scripts\python marketing\posts\build.py --only mm-03     # one post
.venv\Scripts\python marketing\posts\build.py --html-only      # just preview.html, no PNGs
.venv\Scripts\python marketing\posts\build.py --scale 1        # half-size PNGs, for quick checks
```

Needs `pip install playwright` + `playwright install chromium`. If a Chromium is already installed
elsewhere (e.g. a cloud container), point at it with `PW_CHROMIUM=/path/to/chrome` instead.
Fonts come from Google Fonts, so the build needs internet; it stops if a font fails to load.

Output per series: `png/<id>.png` for a single post, `png/<id>/01.png ...` for a carousel
(2160x2700, Instagram 4:5 at 2x; stories 2160x3840), `CAPTIONS.md` (caption + hashtags +
any "check before posting" note), `preview.html` (every slide side by side). `gallery.html`
in this folder is a contact sheet of the whole library. The PNGs are gitignored, so run
the build again to get them back.

## Why it looks like this (from the `post_ideas/` reference posts)

The old posters were all adverts in two colours (purple or cream), with price, phone
number and feature chips on every one. The reference account does five things differently,
and this system copies those habits rather than the account itself:

1. **Several formats, each with its own look**: notebook paper, solid bright colours,
   big type, moody photos, memes, testimonial cards. The feed has variety, but each
   format is recognisable.
2. **Hand-drawn touches on clean type**: marker circles, scribbled arrows, highlighter,
   sparkles, handwriting for asides.
3. **Value first, selling last**: a carousel is hook → useful slides → one quiet CTA. Most
   posts carry only the logo and the URL.
4. **Short, Gen Z copy**: "not vibes", "no planners, no lies". Lower case is fine.
5. **Memes get the reach** (their best likes); everything else turns that reach into sign-ups.

The owl and the navy stay as the anchor; the bright accents are new.

## The series

| Folder | What it is | Look |
|---|---|---|
| `study-tips/` | study advice, habits, mark-scheme literacy | lined / grid paper, journal on a desk |
| `subject-qa/` | one exam-technique question per subject | Maths lilac, Physics mint, CS bubblegum, owl character, torn lined note |
| `big-type/` | one idea in 5 huge words | one solid bright colour, one word swaps colour |
| `memes/` | relatable, shareable, barely selling | born-to/forced-to, types of students, bingo, expectation vs reality, POV |
| `testimonials/` | real student/parent words | tilted colour cards with stars |
| `features/` | what the website does | real screenshots in a laptop + zoomed cards + handwritten callouts |
| `mood/` | calm, cinematic advice carousel | dark, warm lamp-light, white text (post with music) |
| `promos/` | the class batches | sticker style: bright bg, price burst, chips, WhatsApp bar |
| `seasonal/` | exam calendar moments, stories | varies |
| `puzzles/` | 2-slide quizzes, Exam Wordle, spot the mistake (question, then answer) | bright colour + answer cards |
| `cheat-sheets/` | one topic's formulas on one save-able slide | colour per subject, white formula cards in real maths type |
| `trends/` | study life in internet formats: chats, tweets, lock screens, receipts, search, playlist, Wrapped, error pop-ups, starter packs, notes app, flags, meters | each format copies the real app's look |
| `engagement/` | this-or-that, tier lists, comment prompts (no selling) | bright, sticker-like |
| `myths/` | myth (struck through) vs fact, study + subject misconceptions | red/green split cards |

**Suggested weekly mix (5-6 posts):** 1 meme or trend, 1 study tip or cheat sheet, 1 puzzle or
engagement post, 1 subject Q&A / myth / big type,
1 feature or testimonial, 1 promo at most, plus stories. Keep about 1 in 5 posts selling.

## Adding a post

Copy a post in any `posts.json`, give it a new `id` (the prefix keeps files sorted), change
the words, run the build. A post is:

```json
{"id": "st-05-...", "bg": "paper", "caption": "...", "hashtags": ["olevel"],
 "note": "optional reminder that ends up in CAPTIONS.md",
 "size": "feed | story",
 "slides": [ {"layout": "hook", "title": "..."}, {"layout": "tip", ...} ]}
```

Anything set on the post (`bg`, `pop`, `swap`, `url`) is the default for its slides; a
slide can override it.

### Inline markup (any text field)

| Write | Get |
|---|---|
| `**bold**` / `*italic*` | bold / italic |
| `((words))` | hand-drawn marker circle (colour = `pop`) |
| `__words__` | scribbled underline |
| `==words==` | highlighter |
| `[[words]]` | swap colour (`swap`, default white) |
| `{{words}}` | handwriting font |
| `~~words~~` | strike-through |
| new line (`\n`) | line break |

### Layouts and their fields

- `hook`: `title`, `size` (xxl/xl/l/m/s), `eyebrow`, `kicker`, `sub`, `note` (torn lime
  note), `note_right`, `align` (top/bottom/center), `next_pill` (lime arrow pill instead of "swipe")
- `tip`: `num`, `title`, `body`, `try` (the highlighted "try this" tag)
- `qa`: `subject`, `label_c` (subject colour), `question`, `answer` [lines], `mistake`,
  `owl_at` [x, y, rotation], `owl_says`
- `steps`: `title`, `sub`, `items` [[title, text]]
- `checklist`: `title`, `sub`, `items` [text or [text, small]], `boxed`, `tail`
- `defs`: `title`, `items` [[term, meaning]], `colours`, `tail`
- `bigtype`: `lines` [...], `px` (font size), `after`
- `quote`: `quote`, `name`, `role`, `tail`, `tail_sub`
- `cards`: `title`, `cards` [{text, name, role, emoji}] (up to 3), `colours`
- `rows`: `rows` [{title, items [[emoji, caption] x3]}] (born to / forced to)
- `grid4`: `title`, `tiles` [[emoji, title, text] x4], `colours`, `foot`
- `bingo`: `title`, `sub`, `cells` (24; the centre is the owl), `hits` (cell numbers 0-24 to circle)
- `versus`: `title`, `halves` [{tag, bg, say, emoji []}] x2
- `journal`: `title`, `sub`, `note` {text, meta}, `sticky`, `polaroids` [[emoji, caption, colour]], `button`
- `mood`: `title`, `sub`, `light` (lamp-right, lamp-left, blue, candle, dawn), `bokeh`
  [[x, y, size, colour?]], `photo` (optional real photo, path from repo root)
- `device`: `eyebrow`, `title`, `sub`, `shot` (file in website/static/demos/hero/),
  `laptop_at` [x, y, width], `zooms` [{crop [x, y, w, h] in screenshot px, w, at [x, y], rot}],
  `callouts` [[text, x, y, rotation, colour]]
- `cta`: `title`, `sub`, `button`, `whatsapp` (true = WhatsApp button)
- `promo`: `eyebrow`, `title`, `sub`, `chips` [], `badge` [text, colour], `burst`
  {top, big, bottom, at [x, y, size], bg, rot}, `bar_title`

Internet-format layouts (styles in `assets/formats.css`; most take `title` and `foot`):

- `quiz`: `tags` [[text, colour]], `q`, `options` [4], `answer` (0-3), `cta`, `why`, `reveal`.
  Two-slide puzzle = the question slide, then `{"inherit": true, "reveal": true}`.
- `spot` (spot the mistake): `tags`, `title`, `lines` [], `bad` (index), `fix`, `ask`, `mono`, `reveal`
- `wordle`: `answer` (5 letters), `guesses` [], `reveal`
- `formula` (cheat sheet): `eyebrow`, `title`, `cells` [{name, f, note, wide, bg, words}], `dense`.
  `f` uses formula markup: `^{sup}`, `_{sub}`, `{numerator // denominator}`; sin/cos/tan and
  logic operators stay upright. `words: true` = a sentence, not a formula (upright sans).
  `dense: true` shrinks the cards when a sheet has 7 or more.
- `chat`: `contact`, `avatar` (emoji), `av_bg`, `status`, `msgs` [[me|them|time|read, text]].
  Fits about 10 short messages.
- `tweet`: `text`, `when`, `after`
- `notif` (lock screen, use bg wall / wall2): `date`, `clock`, `notifs` [[emoji, app, title, body, time]], `cap`
- `receipt`: `store`, `meta`, `items` [[left, right]], `total` [[left, right]], `footer`, `rot`,
  `note`, `note_at` [x, y], `note_c`
- `search`: `query`, `suggestions` [endings]
- `playlist` (use bg spot): `kind`, `title`, `by`, `cover_bg`, `cover_emoji`, `cover_text`, `now`,
  `tracks` [[title, subtitle, duration]]
- `wrapped` (use bg wall): `eyebrow`, `blocks` [{label, big, sub, bg, rot, list}]
- `error` (use bg retro / navy): `app`, `icon`, `msg`, `detail`, `buttons` [] (last = highlighted), `top`
- `ticket` (boarding pass): `eyebrow`, `ticket` {airline, cls, from_l, from, to_l, to, fields
  [[label, value] x6], name, stub_l, stub}, `bar`, `bar_title`
- `starter`: `items` [[emoji, text] x6]
- `flags`: `green` [], `red` []
- `notes` (notes app): `date`, `items` [text or [text, done]]
- `meters`: `sub`, `rows` [[label, percent, colour?]]
- `tier`: `rows` [[S|A|B|C|D|F, [[emoji, text]]]]
- `tot` (this or that): `pairs` [[emoji, text, emoji, text]]
- `myth`: `items` [[myth, fact]] (4 fit)

Extra backgrounds for these: `wall`, `wall2` (phone wallpapers), `spot` (music app), `black`, `retro`.

Every slide also takes `bg` (paper, grid, plain, white, cream, lime, lilac, sky, sun, tang,
bubble, mint, coral, navy, desk, mood), `pop`, `swap`, `ink`, `logo` (right / none),
`url` (false hides the footer URL), `inset` (CSS inset of the content box) and
`doodles` [[name, x, y, width, rotation, colour]]. The doodle names are arrow-curl,
arrow-down, arrow-right, arrow-loop, arrow-up, sparkle, sparkle-o, burst, squiggle, swirl,
heart, star, crown, underline, circle, zigzag and lamp. Positions are pixels on the
1080 x 1350 canvas.

The build prints `<-- OVERFLOW` when text spills out of the content box. A slide with a
rotated note can trigger it harmlessly, so look at the PNG before changing anything.

## Rules

- **Never invent a testimonial.** The `testimonials/` series and `bt-03` slide 3 reuse the
  quotes on the website's homepage. Confirm they are real and the students agreed to be named.
- Prices, dates and limits must match the website (`billing.PERIODS`, class pages).
  Today: O Level/IGCSE classes PKR 8,499/month, A Level from 12,999 per course, batches start
  31 Oct 2026, money-back after the first paid class, free plan = 3 topical booklets a month,
  yearly past papers free without sign-up.
- Chats in `trends/` and `pr-06` are jokes or reenactments, never a real person's messages;
  `pr-06` carries a note saying so. No fake follower counts, likes or "x students" figures.
- About 1 post in 5 sells. Puzzles, trends, engagement and most myths do not mention classes.
- Facts in `cheat-sheets/`, `puzzles/` and `myths/` were checked against the syllabuses;
  re-check any line you edit.
- Exam-technique facts in `subject-qa/` follow the Cambridge rubrics and mark-scheme
  conventions. Re-check them if a syllabus changes.

## Checking the output

The build prints `<-- OVERFLOW` when something pokes outside the content box. Rotated cards
(starter packs, Wrapped, torn notes) trip it harmlessly; anything else usually means too much
text. Look at the PNGs, ideally as a contact sheet, before posting: `gallery.html` shows every
post with a series filter, search, a full-size viewer (arrow keys) and a "Copy caption" button.

## Scaling up

Each new post is a few lines of JSON, so hundreds are cheap. Good sources of content:
- **Subject Q&A from the question bank**: one post per chapter per subject ("most common
  mistake in Vectors"), using the stored explanations' "common mistakes" lists.
- **Big type** for every feature and stat; **bingo/grid4/rows** memes for each exam season.
- **Puzzles**: one quiz per chapter per subject; every answer must be worked out and checked.
- **Cheat sheets**: one per chapter; formulas checked against the syllabus formula lists.
- **Trends**: new internet formats appear constantly; add a layout to `build.py` + `formats.css`
  once and every future post in that format is just JSON.
- **Mood** carousels re-skinned with different `light` settings, or with real or stock photos via `photo`.

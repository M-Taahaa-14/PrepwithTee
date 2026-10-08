# PrepWithTee social posts

A template engine for Instagram posts. Each folder is one **series** with its own look;
each `posts.json` holds the words. Change the words, re-run, and you get new PNGs.

```
.venv\Scripts\python marketing\posts\build.py                  # build + render everything
.venv\Scripts\python marketing\posts\build.py --series memes   # one series
.venv\Scripts\python marketing\posts\build.py --only mm-03     # one post
.venv\Scripts\python marketing\posts\build.py --html-only      # just preview.html, no PNGs
```

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

**Suggested weekly mix (5-6 posts):** 1 meme, 1 study tip, 1 subject Q&A or big type,
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
- Exam-technique facts in `subject-qa/` follow the Cambridge rubrics and mark-scheme
  conventions. Re-check them if a syllabus changes.

## Scaling up

Each new post is a few lines of JSON, so hundreds are cheap. Good sources of content:
- **Subject Q&A from the question bank**: one post per chapter per subject ("most common
  mistake in Vectors"), using the stored explanations' "common mistakes" lists.
- **Big type** for every feature and stat; **bingo/grid4/rows** memes for each exam season.
- **Mood** carousels re-skinned with different `light` settings, or with real or stock photos via `photo`.

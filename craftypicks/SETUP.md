# Craftypicks — setup

Everything below is free. No card required at any step. Budget about 45 minutes
the first time.

You'll end up with: a site that rebuilds itself every morning at 9:00 AM ET,
posts the plays it finds, grades yesterday's, and pushes the whole thing live —
with nobody touching it.

---

## What you need first

Four free accounts. Make them in this order:

| Account | Why | Link |
|---|---|---|
| GitHub | Stores the site and runs the daily job | github.com/signup |
| The Odds API | The odds feed (500 credits/month free) | the-odds-api.com |
| Cloudflare | Hosting | dash.cloudflare.com/sign-up |
| beehiiv | The email list (free to 2,500 subs) | beehiiv.com |

---

## 1. Get the odds API key

1. Go to **the-odds-api.com** and request a free key. It arrives by email in a
   minute or two.
2. Keep that key somewhere private. It's a password — anyone with it can burn
   through your monthly credits.

**About the budget:** the free tier is 500 credits a month. This project spends
roughly 6 credits pulling odds and 4 grading results per day, so about **300 a
month** with two leagues in season. `scripts/config.py` has a `MIN_CREDITS_REMAINING`
floor that stops the job rather than draining the last of the month in a bad loop.

If you ever go over, nothing breaks — the site just posts "no plays today" until
the quota resets on the 1st.

---

## 2. Put the code on GitHub

1. Create a new repository named `craftypicks`. **Public** is fine and actually
   useful — a public log is the whole pitch — but private works too.
2. Upload every file and folder from this project. Keep the structure exactly as
   it is; the scripts use relative paths.
3. In the repo, go to **Settings → Secrets and variables → Actions → New
   repository secret**:
   - Name: `ODDS_API_KEY`
   - Value: the key from step 1
4. Go to **Settings → Actions → General → Workflow permissions** and select
   **Read and write permissions**. Without this the daily job can't commit the
   plays it finds.

### Test it before trusting it

In the **Actions** tab, open "Post daily plays" and click **Run workflow**. It
should finish green in under a minute. Open the log and you'll see how many
games it scanned, how many edges it found, and how many credits are left.

---

## 3. Put it online with Cloudflare Pages

1. In the Cloudflare dashboard: **Workers & Pages → Create → Pages → Connect to
   Git**, and pick your `craftypicks` repo.
2. Build settings — this trips people up, so read carefully:
   - **Framework preset:** None
   - **Build command:** *leave completely empty*
   - **Build output directory:** `/`
3. Save and deploy.

Your site is live at `craftypicks.pages.dev` (or similar). Every time the daily
job commits, Cloudflare redeploys within about a minute. There is no build step
because the HTML is already built and committed — that's deliberate, and it's
why hosting stays free and fast.

### A real domain (optional, ~$10/year)

The only thing on this list that costs money. Buy the domain at Cloudflare
Registrar (they sell at cost, no first-year gimmick), then **Pages → your
project → Custom domains → Set up a domain**. DNS is automatic if the domain is
already in your Cloudflare account.

---

## 4. Hook up the email list

1. Create a free beehiiv publication.
2. In beehiiv: **Grow → Subscribe Forms → Create**, pick the embed style, and
   copy the **embed URL**. It looks like
   `https://embeds.beehiiv.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.
3. Open `scripts/config.py`, paste it into `BEEHIIV_EMBED_URL`, and commit.

The signup form on all three pages switches over automatically on the next
build. Until you do this, the form politely says signup isn't connected yet
rather than pretending to work.

**Sending the daily email** is manual for now: beehiiv's free tier doesn't
include automated RSS-to-email. Each morning you can copy the day's plays into a
beehiiv post, or just let the site be the product and treat the list as an
announcement channel.

---

## 5. Make it yours

`scripts/config.py` is the whole control panel:

| Setting | What it does |
|---|---|
| `MIN_EDGE_PCT` | How big an edge has to be to get posted. Raise it for fewer, better plays. |
| `MAX_PLAYS_PER_DAY` | Hard cap on the card. Six is deliberate — short cards are honest cards. |
| `MIN_BOOKS` | Minimum books needed before a game counts. Lower than 6 gets noisy fast. |
| `LEAGUES` | Which sports to scan. Each in-season league costs ~3 credits/day. |
| `MARKETS` | `h2h`, `spreads`, `totals`. **Each one multiplies your credit spend.** |
| `MIN_PRICE` / `MAX_PRICE` | Ignore long shots, where "edges" are mostly noise. |

After any change: commit, then run the workflow by hand to see the effect.

---

## Running it locally

```bash
# preview with synthetic data — spends zero credits
CRAFTYPICKS_MOCK=1 python3 scripts/run_daily.py

# real run, needs your key
export ODDS_API_KEY=your_key_here
python3 scripts/run_daily.py

# rebuild the HTML without touching the data
python3 _src/build.py

# view it
python3 -m http.server 8000
```

Mock runs stamp a yellow "sample data" banner across every page so test plays
can never be mistaken for real ones. Delete `data/*.json` and rerun before going
live if you've been testing.

---

## When something breaks

**The workflow fails with a 401** — the `ODDS_API_KEY` secret is missing,
misspelled, or has a stray space.

**It runs green but posts no plays** — usually correct behavior. Nothing cleared
the edge threshold, or nothing is in season. Check the run log: it prints the
game and edge count per league.

**It runs but the site doesn't update** — check that Cloudflare's build output
directory is `/` and the build command is empty. Also confirm the workflow
actually pushed a commit.

**"Nothing changed today"** in the log — the job ran and found the same state as
before. Harmless.

**Credits gone early** — you probably added markets or leagues. Each market ×
each region × each request is a credit. Drop back to `["h2h", "totals"]` and
watch it for a week.

---

## The honest caveats

Read these before you tell anyone the site is a winning system.

- **This finds price edges, not winners.** It has no idea a starter got
  scratched or that a team is on a bad travel spot. It knows what every book is
  charging and whether one of them is out of line.
- **The edge only exists at the listed book and number.** If the price moved,
  the play is gone. The site says this on every card; believe it.
- **A real edge still needs hundreds of plays to show up.** Fifty plays tells
  you nothing. Anyone drawing conclusions from two weeks is reading noise.
- **The free odds feed is mostly soft books.** That's fine — it's where a
  recreational bettor can actually get a bet down — but it means the consensus
  is softer than a sharp market's.
- **Grading is automatic and unforgiving.** Whatever gets posted gets graded,
  including the days you'd rather forget. Don't add a way to delete plays; the
  moment you do, the record stops meaning anything.

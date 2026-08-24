# Craftypicks

A free daily betting-plays site that runs itself. Every morning it reads the
odds at every major US book, finds where one book is priced meaningfully off the
market consensus, posts those plays with the math attached, grades yesterday's
against the final scores, and rebuilds the site.

No pick sales, no premium tier, no deleted losers.

**Setup instructions: [SETUP.md](SETUP.md)**

---

## How it decides what to post

The system does not predict games. It prices them.

1. **Read the board.** Moneyline, spread and total at every book, for every game
   in season. Games priced by fewer than 6 books are skipped.
2. **Strip the vig.** Both sides of a market always add to more than 100%.
   Removing that margin proportionally turns a price into the book's honest
   estimate of the real odds.
3. **Build a consensus.** Average those honest estimates across books — leaving
   out the book being evaluated, so an outlier can't drag its own baseline.
4. **Measure the gap.** If the best available price beats consensus by
   `MIN_EDGE_PCT` in expected value, it goes on the card at a flat 1 unit.
5. **Grade it.** The next run pulls final scores and marks every posted play
   win, loss or push. Nothing is edited afterward.

What this catches: slow books, books with lopsided action, books that simply
disagree with the market. What it can't catch: injuries, weather, travel, or
anything else that hasn't reached the prices yet.

---

## Layout

```
index.html  plays.html  record.html  about.html   generated — don't hand-edit
_src/
  base.css            all styling
  *.body.html         page templates with {{TOKENS}}
  render.py           data → HTML fragments
  build.py            assembles the four pages
scripts/
  config.py           every tunable setting
  odds_client.py      API wrapper, credit accounting, mock mode
  odds_math.py        american odds, de-vigging, EV, profit
  find_plays.py       scan markets → today's card
  grade.py            final scores → win/loss/push
  stats.py            graded log → the numbers on the site
  run_daily.py        the whole job, in order
data/
  plays.json          today's card
  history.json        every play ever posted — the permanent record
  stats.json          computed totals
.github/workflows/daily.yml    the 9:00 AM ET cron
```

The four HTML files are build output and are committed on purpose: it's what
makes hosting free, instant, and dependency-free.

---

## Commands

```bash
CRAFTYPICKS_MOCK=1 python3 scripts/run_daily.py   # test with fake odds, 0 credits
python3 scripts/run_daily.py                      # real run (needs ODDS_API_KEY)
python3 _src/build.py                             # rebuild HTML from existing data
python3 -m http.server 8000                       # preview locally
```

Pure Python 3.9+, standard library only. No pip install, no node_modules.

---

## Running cost

| | |
|---|---|
| Hosting (Cloudflare Pages) | $0 |
| Daily automation (GitHub Actions) | $0 |
| Odds feed (The Odds API free tier) | $0 — ~300 of 500 monthly credits |
| Email list (beehiiv, to 2,500 subs) | $0 |
| Domain | ~$10/year, optional |

---

## Rules worth keeping

- **Never delete a posted play.** A record you can edit isn't a record.
- **Never change a stake after the fact.** Flat 1u is what makes the log honest.
- **A day with no plays is a good day.** Forcing a card is how this turns into
  every other tout site.
- **21+, entertainment only.** Not a sportsbook, not financial advice, no
  guarantees. If gambling stops being fun: 1-800-GAMBLER.

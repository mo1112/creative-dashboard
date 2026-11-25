# Creative Performance Dashboard

A password-protected creative dashboard for one brand's Meta ads, hosted free on GitHub Pages and refreshed about every 4 hours from Triple Whale.

**Tabs:** Overview (daily/weekly/monthly metrics), Attribution (campaign → ad set → ad), Win Rate, Angles, Concepts, ICP, Formats, NVP Buckets, Breakdowns, Analysis (multi-level pivot), Data Clean Up (merge messy tag values). There's also an in-dashboard ad player and Ads Manager links.

**Numbers:**
- Spend, impressions, clicks, revenue and purchases are Meta-reported, through Triple Whale.
- New-customer and new-visitor figures are Triple Whale pixel numbers for the same ads (Triple Attribution, 7-day).
- All of the shop's Meta ad accounts are included.
- Copies and renamed ads of the same video or image roll up into one creative.

## How it works

```
GitHub Actions (every ~4h)
  scripts/fetch_data.py    Triple Whale SQL API → public/data/latest.json  (ad names parsed by scripts/naming.py)
  scripts/encrypt_data.py  AES-GCM with DASHBOARD_PASSWORD → only ciphertext is published
  app/ (React + Vite)      built and copied next to the data → GitHub Pages
```

The data is never committed. If a refresh fails, the last published data is kept.

## Repo secrets

| Secret | What |
|---|---|
| `TW_API_KEY` | Triple Whale API key for the shop. Create it at app.triplewhale.com → Settings → API Keys with read scopes (Summary Page, Pixel Attribution). |
| `DASHBOARD_PASSWORD` | The password the team types to open the page. |
| `DASHBOARD_CONFIG` | The contents of `config.json`. It's kept out of the repo. |

## config.json

```json
{
  "name": "Brand Name",
  "shop": "your-store.myshopify.com",
  "business_ids": {"<ad account id>": "<business manager id>"},
  "labels": {"icp": "Audience"},
  "naming": {
    "source": "ad",
    "separator": "_",
    "slots": ["creative_no", "product", "angle", "concept", "icp", "format", "strategist", "editor"],
    "min_slots": 6,
    "key_slot": "creative_no",
    "aliases": {"strategist": {"jd": "John Doe"}}
  }
}
```

- **`shop`:** the Triple Whale shop id, which is the store's `.myshopify.com` domain.
- **`business_ids`** (optional): makes Ads Manager links open inside the right Business Manager.
- **`labels`** (optional): renames a field in the UI.
- **`naming`:** maps the brand's ad-name convention to dashboard fields.
  - Slot names you can use: `creative_no, product, angle, sub_angle, concept, icp, script, format, awareness_stage, funnel, strategist, editor, hook, batch, landing_page`. Use `-` to skip a slot.
  - If one separator can't describe the convention, rewrite `parse()` in `scripts/naming.py`.

## Local commands

```bash
python3 scripts/sample_data.py                 # made-up data, no key needed
python3 scripts/fetch_data.py --check          # test key + shop (yesterday's Meta spend per account)
python3 scripts/fetch_data.py --names 60       # top ad names + whether they parse
python3 scripts/fetch_data.py                  # real refresh → public/data/latest.json
```

For local runs, put `TW_API_KEY=...` in `.env` and the config in `config.json`. Both are gitignored.

To preview locally (with sample or real data), run:

```bash
cd app && npm install && npm run build && cp -R dist/. ../public/ && python3 -m http.server 8000 -d ../public
```

Then open http://localhost:8000. Local data isn't encrypted, so there's no password prompt.

## Upkeep

- GitHub pauses scheduled workflows after 60 days without a commit. Push any small commit, or re-enable the workflow under Actions.
- If the naming convention changes, update `naming` in `config.json`, then run `gh secret set DASHBOARD_CONFIG < config.json` and re-run the workflow.

#!/usr/bin/env python3
"""Pull the brand's Meta ad data from the Triple Whale SQL API and build public/data/latest.json.

Everything is Meta: spend, delivery, revenue and purchases are Meta-reported (through Triple Whale);
new-customer and new-visitor figures are Triple Whale's pixel numbers for those Meta ads. All of the
shop's Meta ad accounts are included. A creative is one video (Triple Whale's content hash) or one
image, so copies and renamed ads roll together.

Env:
  TW_API_KEY          Triple Whale API key for the shop (locally: put TW_API_KEY=... in ./.env)
  DASHBOARD_CONFIG    the config JSON (in CI); locally ./config.json is read instead
  LIVE_DATA_URL       optional: published latest.json, reused if this refresh fails

Usage:
  python3 scripts/fetch_data.py            full refresh -> public/data/latest.json
  python3 scripts/fetch_data.py --check    test the key + shop id (yesterday's Meta spend)
  python3 scripts/fetch_data.py --names 60 print the top ad / ad set names (to set up naming)
"""
import json, os, pathlib, re, sys, time, urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from naming import clean, configure, parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.triplewhale.com/api/v2/orcabase/api/sql"
META = "channel = 'facebook-ads' AND model = 'Triple Attribution' AND attribution_window = '7_days'"
WINDOW_DAYS = 120          # days of history shown
MATURE_DAYS = 14           # a creative counts in win rates once it is this many days old
LOOKBACK = "2024-01-01"    # how far back to look for an ad's first spend day
THUMBS = "https://files.triplewhale.com/thumbnails/facebook-ads"
DIMS = ["product", "angle", "sub_angle", "concept", "icp", "script", "format", "awareness_stage", "creative_no",
        "strategist", "editor", "hook", "batch", "landing_page"]


def load_env():
    """Local runs: read KEY=value lines from ./.env (gitignored) for anything not already set."""
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not k.startswith("#") and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config():
    raw = os.environ.get("DASHBOARD_CONFIG") or (ROOT / "config.json").read_text()
    c = json.loads(raw)
    for k in ("name", "shop"):
        if not c.get(k):
            sys.exit(f"config is missing '{k}'")
    return c


def sql(shop, query, start, end, key, tries=4):
    body = json.dumps({"shopId": shop, "query": query, "period": {"startDate": start, "endDate": end}}).encode()
    for attempt in range(tries):
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "x-api-key": key, "content-type": "application/json", "accept": "application/json",
            "user-agent": "Mozilla/5.0 (creative-dashboard refresh)"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            if isinstance(data, dict):
                data = data.get("data") or data.get("rows") or []
            return data
        except HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(15 * (attempt + 1))
                continue
            raise RuntimeError(f"Triple Whale {e.code} for {shop}: {msg}")
    return []


def n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def r2(v):
    v = round(v, 2)
    return int(v) if v == int(v) else v


def acct_id(v):
    return str(v or "").removeprefix("act_")


def manager_url(biz, act, ad):
    b = f"&business_id={biz}&global_scope_id={biz}" if biz else ""
    return f"https://adsmanager.facebook.com/adsmanager/manage/ads/edit/standalone?act={act}{b}&selected_ad_ids={ad}"


def landing(url):
    if not url:
        return None
    p = urlparse(url)
    tail = p.path.rstrip("/").split("/")[-1] if p.path.strip("/") else "home"
    return tail or "home"


def pull(c, key, start, end):
    """Daily per-ad Meta rows, per-ad details, and each ad's first spend day."""
    shop, s, e = c["shop"], start.isoformat(), end.isoformat()
    daily, d = [], start
    while d <= end:
        x = min(d + timedelta(days=6), end)
        a, b = d.isoformat(), x.isoformat()
        daily += sql(shop, f"""
            SELECT toString(ad_id) AS ad, toString(event_date) AS d, sum(spend) AS spend,
                   sum(channel_reported_conversion_value) AS meta_rev, sum(channel_reported_conversions) AS meta_orders,
                   sum(order_revenue) AS px_rev, sum(orders_quantity) AS px_orders,
                   sum(new_customer_order_revenue) AS nc_rev, sum(new_customer_orders) AS nc_orders,
                   sum(new_visitors) AS nv, sum(unique_visitors) AS vis,
                   sum(impressions) AS imps, sum(outbound_clicks) AS clk
            FROM pixel_joined_tvf() WHERE {META} AND event_date BETWEEN '{a}' AND '{b}'
            GROUP BY ad, d HAVING spend > 0 OR meta_rev > 0 OR px_rev > 0""", a, b, key)
        d = x + timedelta(days=1)
    ads = sql(shop, f"""
        SELECT toString(ad_id) AS ad, argMax(ad_name, event_date) AS name, argMax(adset_name, event_date) AS adset,
               argMax(campaign_name, event_date) AS campaign, replaceOne(toString(argMax(account_id, event_date)), 'act_', '') AS account,
               argMax(toString(campaign_id), event_date) AS campaign_id, argMax(toString(adset_id), event_date) AS adset_id,
               argMaxIf(video_content_hash, event_date, video_content_hash != '') AS vhash,
               argMaxIf(video_url, event_date, video_url != '') AS vurl,
               argMaxIf(ad_image_url, event_date, ad_image_url != '') AS img,
               argMaxIf(destination_url, event_date, destination_url != '') AS dest,
               argMax(ad_type, event_date) AS kind, sum(spend) AS total
        FROM pixel_joined_tvf() WHERE {META} AND event_date BETWEEN '{s}' AND '{e}'
        GROUP BY ad HAVING total > 0""", s, e, key)
    first = sql(shop, f"""
        SELECT toString(ad_id) AS ad, toString(minIf(event_date, spend > 0)) AS first_day
        FROM pixel_joined_tvf() WHERE {META} AND event_date BETWEEN '{LOOKBACK}' AND '{e}'
          AND ad_id IN (SELECT DISTINCT ad_id FROM pixel_joined_tvf() WHERE {META} AND event_date BETWEEN '{s}' AND '{e}' AND spend > 0)
        GROUP BY ad""", LOOKBACK, e, key)
    return daily, ads, {r["ad"]: str(r["first_day"])[:10] for r in first}


def build(c, daily, ads, first, start, end):
    biz = c.get("business_ids", {})
    configure(c)
    # Start once there is both new-customer data and spend: NC ratios never divide by spend the
    # pixel missed, and charts don't open on an empty stretch.
    nc_days = [r["d"][:10] for r in daily if n(r["nc_rev"]) > 0]
    spend_days = [r["d"][:10] for r in daily if n(r["spend"]) > 0]
    cut = max(min(nc_days or [start.isoformat()]), min(spend_days or [start.isoformat()]))
    if cut > start.isoformat():
        start = date.fromisoformat(cut)
        daily = [r for r in daily if r["d"][:10] >= cut]
    per = defaultdict(list)
    for r in daily:
        per[r["ad"]].append(r)
    days = sorted({r["d"][:10] for r in daily})
    didx = {d: i for i, d in enumerate(days)}
    monday = lambda d: (date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())).isoformat()
    weeks = sorted({monday(d) for d in days})
    widx = {w: i for i, w in enumerate(weeks)}

    groups = defaultdict(list)
    for a in ads:
        a["tags"] = {k: v for k, v in parse(a.get("name") or "", a.get("adset") or "", a.get("campaign") or "").items() if v not in (None, "")}
        img = re.sub(r"\?.*", "", a.get("img") or "")
        gk = ("v:" + a["vhash"] if a.get("vhash") else "i:" + img if img else "n:" + clean(a.get("name") or a["ad"]))
        groups[gk].append(a)

    out = []
    start_s, end_s = start.isoformat(), end.isoformat()
    last_days = set(days[-2:])
    for gk, rows in groups.items():
        rows.sort(key=lambda a: -n(a.get("total")))
        tags = {}
        for a in sorted(rows, key=lambda a: (not a["tags"].get("structured"), -n(a.get("total")))):
            for k, v in a["tags"].items():
                tags.setdefault(k, v)
        ids = [a["ad"] for a in rows]
        dd, wk = defaultdict(lambda: [0.0] * 9), defaultdict(lambda: [0.0] * 4)
        for i in ids:
            for r in per.get(i, []):
                d = r["d"][:10]
                vals = [n(r[k]) for k in ("spend", "meta_rev", "meta_orders", "nc_rev", "nc_orders", "nv", "vis", "imps", "clk")]
                v = dd[didx[d]]
                for j, x in enumerate(vals):
                    v[j] += x
                w = wk[widx[monday(d)]]
                w[0] += vals[0]; w[1] += vals[1]; w[2] += vals[3]; w[3] += vals[4]
        t = [sum(v[j] for v in dd.values()) for j in range(9)]
        spend, rev, txns, nc_rev, nc_txns, nv, vis, imps, clk = t
        if spend <= 0 and rev <= 0:
            continue
        firsts = sorted(first[i] for i in ids if first.get(i))
        fd = firsts[0] if firsts else None
        m = {"spend": round(spend, 2), "rev": round(rev, 2), "txns": txns, "pixel_rev": round(rev, 2), "pixel_txns": txns,
             "meta_rev": round(rev, 2), "meta_txns": txns, "nc_rev": round(nc_rev, 2), "nc_txns": nc_txns,
             "ncroas": round(nc_rev / spend, 4) if spend else None, "nccpa": round(spend / nc_txns, 2) if nc_txns else None,
             "new_visitors": nv, "visitors": vis, "pct_new_visitors": round(nv / vis * 100, 2) if vis else None,
             "impressions": imps, "clicks": clk, "roas": round(rev / spend, 4) if spend else 0,
             "pct_new": round(nc_txns / txns * 100, 2) if txns else None, "aov": round(rev / txns, 2) if txns else None,
             "cpa": round(spend / txns, 4) if txns else None, "cpm": round(spend / imps * 1000, 4) if imps else 0,
             "cpc": round(spend / clk, 4) if clk else None, "ctr": round(clk / imps * 100, 4) if imps else None}
        m["pixel_roas"] = m["meta_roas"] = m["roas"]
        if fd and fd >= start_s:
            cut = (date.fromisoformat(fd) + timedelta(days=13)).isoformat()
            s14 = sum(v[0] for k, v in dd.items() if days[k] <= cut)
            n14 = sum(v[3] for k, v in dd.items() if days[k] <= cut)
            m.update(spend_d14=round(s14, 2), nc_rev_d14=round(n14, 2), ncroas_d14=round(n14 / s14, 4) if s14 else None)
        top = rows[0]
        act = "act_" + acct_id(top.get("account"))
        image = next((a["img"] for a in rows if a.get("img")), None)
        video = next((a["vurl"] for a in rows if a.get("vurl")), None)
        kind = (top.get("kind") or "").lower()
        fmt = tags.get("format") or {"video": "Video", "image": "Static", "dynamic": "Dynamic"}.get(kind)
        camp = top.get("campaign") or ""
        bt = re.search(r"\b(CBO|ABO|ASC)\b", camp, re.I)
        dt = fd[2:4] + fd[5:7] + fd[8:10] if fd else None
        carry = bool(fd and fd < start_s)
        mature = bool(fd and (end - date.fromisoformat(fd)).days >= MATURE_DAYS)
        conv = "renamed" if tags.get("structured") else "inferred" if tags.get("concept") else "untagged"
        rec = {"ad_name": tags.get("display") or clean(top.get("name")) or top["ad"],
               "creative_key": tags.get("creative_key") or gk, "new_ad_name": clean(top.get("name")),
               **{k: tags.get(k) for k in DIMS}, "format": fmt, "funnel": tags.get("funnel"),
               "landing_page": next((landing(a.get("dest")) for a in rows if a.get("dest")), None),
               "naming_status": {"renamed": "Follows naming convention", "inferred": "Partly read from name",
                                 "untagged": "No naming convention"}[conv],
               "reviewed": conv != "untagged", "convention": conv, "campaign": camp, "adset": top.get("adset"),
               "campaigns": sorted({a.get("campaign") or "" for a in rows})[:15],
               "adsets": sorted({a.get("adset") or "" for a in rows})[:15], "meta_ad_count": len(rows),
               "buying_type": bt.group(1).upper() if bt else None, "attribution_window": None, "geo": None,
               "date": dt, "launch_date": fd, "meta_ad_ids": ids, "metrics": m,
               "wk": [[k, round(v[0], 2), round(v[1], 2), round(v[2], 2), v[3]] for k, v in sorted(wk.items())],
               "dd": [[k] + [r2(x) for x in v] for k, v in sorted(dd.items())],
               "ad_account": act, "thumbnail_candidates": ([image] if image else []) + [f"{THUMBS}/{act}/{ids[0]}.jpg"],
               "thumbnail_url": image or f"{THUMBS}/{act}/{ids[0]}.jpg",
               "preview_link": manager_url(biz.get(acct_id(act), ""), acct_id(act), ids[0]), "video_url": video,
               "carry_over": carry, "mature": mature,
               "launch_status": ("Carry-over (live before window)" if carry else "Launched in window" if mature
                                 else f"Too new (< {MATURE_DAYS} days)")}
        out.append(rec)

    for k in DIMS:   # one spelling per value: the one with the most spend
        best = defaultdict(Counter)
        sk = lambda v: re.sub(r"\W+", "", str(v).lower())
        for a in out:
            if a.get(k):
                best[sk(a[k])][a[k]] += a["metrics"]["spend"]
        for a in out:
            if a.get(k):
                a[k] = best[sk(a[k])].most_common(1)[0][0]
    out.sort(key=lambda a: -a["metrics"]["spend"])
    for i, a in enumerate(out, 1):
        a["spend_rank"] = i

    tot = sum(a["metrics"]["spend"] for a in out) or 1
    rev = sum(a["metrics"]["rev"] for a in out)
    nc = sum(a["metrics"]["nc_rev"] for a in out)
    named = sum(a["metrics"]["spend"] for a in out if a["convention"] == "renamed")
    accounts = Counter()
    for a in ads:
        accounts["act_" + acct_id(a.get("account"))] += sum(n(r["spend"]) for r in per.get(a["ad"], []))

    # Attribution tab: campaign > ad set > ad, with Meta-reported and pixel numbers side by side.
    camps, sets, attr_ads = {}, {}, []
    for a in ads:
        rows = per.get(a["ad"], [])
        act = acct_id(a.get("account"))
        cid, sid = [x if x not in ("", "0") else "" for x in (a.get("campaign_id") or "", a.get("adset_id") or "")]
        cname, sname = a.get("campaign") or "(no campaign)", a.get("adset") or "(no ad set)"
        ck = cid or f"{act}|{cname}"
        camps.setdefault(ck, [len(camps), ck, cname, "", None, None, cid])
        sk_ = sid or f"{ck}|{sname}"
        sets.setdefault(sk_, [len(sets), sk_, sname, camps[ck][0], "", None, None, sid])
        dd = []
        for r in sorted(rows, key=lambda r: r["d"]):
            row = [n(r[k]) for k in ("spend", "meta_rev", "meta_orders", "px_rev", "px_orders", "imps", "clk", "nc_rev", "nc_orders")] + [0, 0, 0, 0, n(r["nv"]), n(r["vis"])]
            if any(row):
                dd.append([didx[r["d"][:10]]] + [r2(x) for x in row])
        if dd:
            live = any(r["d"][:10] in last_days and n(r["spend"]) > 0 for r in rows)
            attr_ads.append([a["ad"], a.get("name") or a["ad"], sets[sk_][0], "SPENDING" if live else "IDLE", act, dd, a.get("img") or "", a.get("vurl") or ""])
    return {
        "brand": {"name": c["name"], "business_ids": biz, "labels": c.get("labels") or {}},
        "weeks": weeks, "days": days, "mature_days": MATURE_DAYS,
        "baseline": {"roas": round(rev / tot, 4), "ncroas": round(nc / tot, 4)},
        "generated_at": datetime.now(timezone.utc).isoformat(), "period": {"start": start_s, "end": end_s},
        "source": "triple-whale-sql-api", "shop": c["shop"], "has_nc": True,
        "attribution": {"primary": "Meta-reported, via Triple Whale",
                        "secondary": "New-customer and new-visitor figures are Triple Whale's numbers for these Meta ads",
                        "window": "Meta account setting"},
        "ad_accounts": sorted(k for k, v in accounts.items() if v > 0),
        "account_spend": {k: round(v, 2) for k, v in accounts.items() if v > 0},
        "scope_note": (f"Meta only: every ad that spent in {c['name']}'s {sum(1 for v in accounts.values() if v > 0)} Meta ad account(s), {start_s} → {end_s}, "
                       f"rolled up to {len(out):,} creatives (copies and renamed ads of the same video count as one). "
                       f"{named / tot:.0%} of spend follows the naming convention; the rest shows as (untagged). Spend, revenue, purchases, "
                       f"impressions and clicks are Meta-reported. New-customer and new-visitor figures are Triple Whale's for the same ads. "
                       f"Launch date is the ad's first spend day. Win rates count creatives launched in the window and at least {MATURE_DAYS} days old."),
        "ad_count": len(out), "ads": out,
        "attr": {"campaigns": [v[1:] for v in sorted(camps.values())], "adsets": [v[1:] for v in sorted(sets.values())],
                 "ads": attr_ads, "has_funnel": False, "has_budgets": False, "meta_api": False,
                 "tw_label": "Triple Whale pixel, Triple Attribution, 7-day", "note": "Meta-reported numbers come through Triple Whale.",
                 "fields": ["spend", "meta_rev", "meta_conv", "px_rev", "px_orders", "imps", "clk", "nc_rev", "nc_orders", "lpv", "view", "atc", "ic", "nv", "vis"]},
    }



def check(c, key, end):
    d = end.isoformat()
    rows = sql(c["shop"], f"""
        SELECT replaceOne(toString(account_id), 'act_', '') AS account, sum(spend) AS spend,
               sum(channel_reported_conversion_value) AS meta_rev, count() AS n
        FROM pixel_joined_tvf() WHERE {META} AND event_date = '{d}' GROUP BY account ORDER BY spend DESC""", d, d, key)
    if not rows:
        sys.exit(f"Key works but no Meta rows on {d} for shop {c['shop']} (wrong shop id, or no Meta spend that day)")
    for r in rows:
        print(f"{d}  act_{r['account']}: Meta spend ${float(r['spend'] or 0):,.2f}, Meta revenue ${float(r['meta_rev'] or 0):,.2f}")
    print("OK: the key and shop id work. Compare these with Ads Manager for the same day.")


def names(c, key, end, limit):
    s = (end - timedelta(days=29)).isoformat()
    rows = sql(c["shop"], f"""
        SELECT argMax(ad_name, event_date) AS ad, argMax(adset_name, event_date) AS adset, sum(spend) AS total
        FROM pixel_joined_tvf() WHERE {META} AND event_date BETWEEN '{s}' AND '{end}'
        GROUP BY ad_id ORDER BY total DESC LIMIT {int(limit)}""", s, end.isoformat(), key)
    configure(c)
    for r in rows:
        t = parse(r["ad"] or "", r["adset"] or "", "")
        flag = "OK " if t.get("structured") else "-- "
        print(f"{flag}${float(r['total'] or 0):>10,.0f}  {r['ad']}   [ad set: {r['adset']}]")
    ok = sum(float(r["total"] or 0) for r in rows if parse(r["ad"] or "", r["adset"] or "", "").get("structured"))
    tot = sum(float(r["total"] or 0) for r in rows) or 1
    print(f"\n{ok / tot:.0%} of this spend parses with the current naming config (OK = parsed).")


def main():
    load_env()
    c = config()
    key = os.environ.get("TW_API_KEY")
    if not key:
        sys.exit("TW_API_KEY is not set")
    # Latest full day in US time (shops report in their own US time zone).
    end = (datetime.now(timezone.utc) - timedelta(hours=8)).date() - timedelta(days=1)
    if "--check" in sys.argv:
        return check(c, key, end)
    if "--names" in sys.argv:
        i = sys.argv.index("--names")
        return names(c, key, end, sys.argv[i + 1] if len(sys.argv) > i + 1 else 60)
    end = end + timedelta(days=1)   # include today's partial day in the full refresh
    start = end - timedelta(days=WINDOW_DAYS - 1)
    out = ROOT / "public" / "data"
    out.mkdir(parents=True, exist_ok=True)
    # The repo is public, so its Actions logs are too: on CI, keep brand, shop and account details out.
    public = bool(os.environ.get("GITHUB_ACTIONS"))
    hide = lambda t: t.replace(c["shop"], "***").replace(c["name"], "***") if public else t
    print(f"== {start} -> {end}" if public else f"== {c['name']} ({c['shop']}) {start} -> {end}", flush=True)
    try:
        daily, ads, first = pull(c, key, start, end)
        if not daily or not ads:
            raise RuntimeError("no Meta rows")
        m = build(c, daily, ads, first, start, end)
        (out / "latest.json").write_text(json.dumps(m, separators=(",", ":"), default=str))
        s = sum(a["metrics"]["spend"] for a in m["ads"])
        cov = {k: sum(a["metrics"]["spend"] for a in m["ads"] if a.get(k)) / s for k in ("concept", "angle", "format", "strategist", "product", "landing_page")}
        if public:
            print(f"  refreshed: {len(m['ads'])} creatives", flush=True)
        else:
            print(f"  {len(m['ads'])} creatives from {len(ads)} ads · spend ${s:,.0f} · ROAS {m['baseline']['roas']:.2f} · "
                  f"{(out / 'latest.json').stat().st_size / 1e6:.1f} MB · accounts {', '.join(m['ad_accounts'])}", flush=True)
            for k, v in sorted(m["account_spend"].items()):
                print(f"  {k}: ${v:,.0f}", flush=True)
            print("  tagged share of spend: " + ", ".join(f"{k} {v:.0%}" for k, v in cov.items()), flush=True)
    except Exception as err:
        print(f"::warning::Dashboard data not refreshed: {hide(str(err))[:300]}", flush=True)
        url = os.environ.get("LIVE_DATA_URL")
        try:
            raw = urllib.request.urlopen(url, timeout=60).read() if url else b"{}"
            if json.loads(raw).get("encrypted"):
                (out / "latest.json").write_bytes(raw)
                print("  keeping the last published data", flush=True)
                return
        except Exception as e2:
            print(f"  no earlier data to keep: {str(e2)[:120]}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

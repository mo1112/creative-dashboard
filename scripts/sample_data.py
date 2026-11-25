#!/usr/bin/env python3
"""Write made-up data to public/data/latest.json so the app can be previewed without an API key.

    python3 scripts/sample_data.py && (cd app && npm run dev)

Goes through the same build() as the real refresh, so the page looks exactly like it will.
"""
import json, pathlib, random, sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_data as fd

random.seed(7)
end = (datetime.now(timezone.utc) - timedelta(hours=8)).date()
start = end - timedelta(days=fd.WINDOW_DAYS - 1)
cfg = {"name": "Sample Brand", "shop": "sample", "naming": {
    "separator": "_", "slots": ["creative_no", "product", "angle", "concept", "icp", "format", "strategist", "editor"],
    "min_slots": 6, "key_slot": "creative_no"}}

angles = ["Mechanism", "Testimonial", "Problem-Agitate", "Founder Story", "Comparison"]
concepts = ["Morning Routine", "Doctor Explains", "Before After", "3 Mistakes", "Us vs Them", "Street Interview"]
formats = ["UGC", "Talking Head", "Static", "Animated", "VSL"]
people = ["Alex", "Sam", "Jordan", "Riley"]
ads, daily, first = [], [], {}
for i in range(160):
    ad = str(120000000000000000 + i)
    launch = start + timedelta(days=random.randint(-30, fd.WINDOW_DAYS - 5))
    named = random.random() < 0.8
    name = (f"{1000 + i}_Hero_{random.choice(angles)}_{random.choice(concepts)}_F35_{random.choice(formats)}_"
            f"{random.choice(people)}_{random.choice(people)}") if named else f"Old ad {i} - Copy"
    ads.append({"ad": ad, "name": name, "adset": f"Test {i // 6}", "campaign": random.choice(["TOF - ABO Testing", "Scale - CBO"]),
                "account": "1234567890", "campaign_id": "", "adset_id": "", "vhash": f"h{i}", "vurl": "", "img": "",
                "dest": "https://example.com/products/hero", "kind": "video", "total": 0})
    first[ad] = launch.isoformat()
    scale = random.choice([30, 80, 200, 900, 3000]) if random.random() < 0.9 else 12000
    roas = random.uniform(0.4, 2.4)
    d = max(launch, start)
    while d <= end:
        if random.random() < 0.85:
            sp = scale * random.uniform(0.5, 1.5)
            rev = sp * roas * random.uniform(0.6, 1.4)
            orders = rev / 60
            daily.append({"ad": ad, "d": d.isoformat(), "spend": sp, "meta_rev": rev, "meta_orders": orders,
                          "px_rev": rev * 0.9, "px_orders": orders * 0.9, "nc_rev": rev * 0.6, "nc_orders": orders * 0.6,
                          "nv": sp * 1.5, "vis": sp * 2.2, "imps": sp * 70, "clk": sp * 0.9})
        d += timedelta(days=1)
    ads[-1]["total"] = sum(r["spend"] for r in daily if r["ad"] == ad)

m = fd.build(cfg, daily, [a for a in ads if a["total"] > 0], first, start, end)
out = fd.ROOT / "public" / "data"
out.mkdir(parents=True, exist_ok=True)
(out / "latest.json").write_text(json.dumps(m, separators=(",", ":"), default=str))
print(f"sample data: {len(m['ads'])} creatives -> {out / 'latest.json'}")

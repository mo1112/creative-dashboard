"""Read the brand's ad naming convention into the dashboard's creative fields.

Driven by config.json -> "naming" (no code changes needed for a plain delimited convention):

  "naming": {
    "source": "ad",                 # which name to read: "ad", "adset" or "campaign"
    "separator": "_",               # what splits the slots: "_", " - ", "|", ...
    "slots": ["creative_no", "product", "angle", "concept", "icp", "format", "strategist", "editor"],
    "min_slots": 5,                 # a name with fewer parts counts as "untagged"
    "key_slot": "creative_no",      # slot that identifies one creative across copies (optional)
    "aliases": {"strategist": {"jd": "John Doe"}}   # spelling fixes per field (lower-case keys)
  }

Slot names the dashboard understands: creative_no, product, angle, sub_angle, concept, icp,
script, format, awareness_stage, funnel, strategist, editor, hook, batch, landing_page.
Use "-" for a slot to ignore (e.g. a date). If the convention is more complex than one
delimiter, write a custom function in parse() below (see the docstring there).
"""
import re

COPY = re.compile(r"\s*[-–]\s*Copy(\s*\d+)?\s*", re.I)
FIELDS = {"creative_no", "product", "angle", "sub_angle", "concept", "icp", "script", "format",
          "awareness_stage", "funnel", "strategist", "editor", "hook", "batch", "landing_page"}
PEOPLE = {"strategist", "editor"}
NONE = {"", "NONE", "NA", "N/A", "X", "-", "NULL"}

CFG = {}


def configure(cfg):
    CFG.clear()
    CFG.update(cfg.get("naming") or {})


def clean(name):
    return re.sub(r"\s+", " ", COPY.sub(" ", name or "")).strip(" -")


def _value(field, v):
    v = (v or "").strip()
    if v.upper() in NONE:
        return None
    alias = ((CFG.get("aliases") or {}).get(field) or {}).get(v.lower())
    if alias:
        return alias
    if field in PEOPLE and (v.islower() or v.isupper()):
        return v[:1].upper() + v[1:].lower()
    if field == "funnel":
        return v.upper()
    return v


def parse(name, adset="", campaign=""):
    """Return {field: value, ..., "display": shown name, "structured": True if the name followed
    the convention, "creative_key": groups copies of one creative}.

    Custom conventions: replace the body below with your own reading of name/adset/campaign and
    return the same keys. Only "display" is required; anything missing shows as (untagged)."""
    if CFG.get("custom") == "adset-reader":
        return parse_free_text(name, adset, campaign)
    src = {"ad": name, "adset": adset, "campaign": campaign}.get(CFG.get("source", "ad"), name)
    n = clean(src)
    slots = CFG.get("slots") or []
    sep = CFG.get("separator") or "_"
    out = {"display": clean(name) or n}
    if not slots:
        return out
    parts = [p.strip() for p in n.split(sep)] if sep.strip() else [p.strip() for p in re.split(re.escape(sep), n)]
    if len(parts) < int(CFG.get("min_slots") or len(slots)):
        return out
    for field, v in zip(slots, parts):
        if field in FIELDS:
            val = _value(field, v)
            if val:
                out[field] = val
    out["structured"] = True
    ks = CFG.get("key_slot")
    if ks and out.get(ks):
        out["creative_key"] = re.sub(r"\W+", "", str(out[ks])).upper()
    return out


# ---- Free-text names: no fixed convention, so read what the ad and ad set names do carry. ----
# Prospecting ad sets look like "<Concept> - <Strategist> - <date>"; retargeting ad sets start with
# "VC" or "ATC". Ads may carry a hook as "H1".."H9" or "HC". Brand-specific words (strategist
# names, generic ad set names, ad names that aren't concepts) live in config.json -> naming:
#   "custom": "adset-reader",
#   "strategists": {"<regex>": "<display name>"},
#   "generic_adsets": "<regex of ad set names that say nothing about the concept>",
#   "skip_concepts": ["<ad names that aren't concepts>"]
# Nothing is guessed: a field the names don't show is left empty and shows as (untagged).
RETARGET = re.compile(r"^\s*(VC|ATC)\b|retarget", re.I)
HOOK = re.compile(r"(?:^|[\s-])(H\d+|HC)\b", re.I)
DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
TASK = re.compile(r"^\s*(task\s*\d+|T-?\d+)\s*$", re.I)
COLOUR = re.compile(r"\s-\s(Black|White)\b", re.I)


def _tidy(t):
    t = DATE.sub(" ", COPY.sub(" ", t or ""))
    t = re.sub(r"(\s*-\s*)+", " - ", t)
    return re.sub(r"\s+", " ", t).strip(" -")


def parse_free_text(name, adset="", campaign=""):
    strats = [(re.compile(rx, re.I), who) for rx, who in (CFG.get("strategists") or {}).items()]
    generic = re.compile(CFG.get("generic_adsets") or r"(?!x)x", re.I)
    skip = {x.lower() for x in CFG.get("skip_concepts") or []}
    out = {"display": clean(name)}
    rt = bool(RETARGET.search(adset or ""))
    out["funnel"] = "Retargeting" if rt else "Prospecting"
    h = HOOK.search(name or "")
    if h:
        out["hook"] = h.group(1).upper()
    strat = rx_hit = None
    for rx, who in strats:
        if rx.search(adset or "") or rx.search(name or ""):
            strat, rx_hit = who, rx
            break
    if strat:
        out["strategist"] = strat
    ad_concept = _tidy(HOOK.sub(" ", name or ""))
    if rx_hit:
        ad_concept = _tidy(rx_hit.sub(" ", ad_concept))
    if re.fullmatch(r"[\d.\s-]*", ad_concept or "") or (ad_concept or "").lower() in skip:
        ad_concept = None
    if rx_hit and rx_hit.search(adset or "") and not rt:
        c = _tidy(COLOUR.sub(" ", rx_hit.sub(" ", adset or "")))
        out["concept"] = ad_concept if (TASK.match(c) or not c) and ad_concept else (c or ad_concept)
    elif ad_concept:
        out["concept"] = ad_concept
    elif not rt and not generic.search(adset or ""):
        out["concept"] = _tidy(adset) or None
    if out.get("concept"):
        out["concept"] = out["concept"][:1].upper() + out["concept"][1:]
    return out

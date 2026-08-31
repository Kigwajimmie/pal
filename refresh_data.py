#!/usr/bin/env python3
"""
Palworld breeding data refresh — pulls the current palcalc dataset, builds the
files the calculator serves, validates them, and writes them into ./data.
Keys everything by unique Paldex id (e.g. "012", "012B") because display names
are NOT unique (two Pals share the name "Gumoss").

If palcalc changes shape, this fails loudly rather than shipping wrong data.
"""
import json, math, urllib.request, datetime, sys, os
from collections import Counter

PALCALC_DB  = "https://raw.githubusercontent.com/tylercamp/palcalc/main/PalCalc.Model/db.json"
PALCALC_TBL = "https://raw.githubusercontent.com/tylercamp/palcalc/main/PalCalc.Model/breeding.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)

def dex_of(p):
    return str(p["Id"]["PalDexNo"]).zfill(3) + ("B" if p["Id"]["IsVariant"] else "")

def main():
    print("Fetching palcalc dataset...")
    db  = fetch(PALCALC_DB)
    tbl = fetch(PALCALC_TBL)["Breeding"]

    p0 = db["Pals"][0]
    for f in ("Name","InternalName","BreedingPower","BreedingPowerPriority","Id"):
        if f not in p0: sys.exit(f"FATAL: palcalc db.json missing '{f}' — schema changed.")
    if not tbl or "ChildInternalName" not in tbl[0]:
        sys.exit("FATAL: palcalc breeding.json shape changed.")

    int2dex  = {p["InternalName"]: dex_of(p) for p in db["Pals"]}
    dex2name = {dex_of(p): p["Name"] for p in db["Pals"]}
    palI     = {p["InternalName"]: p for p in db["Pals"]}   # by internal (unique)

    # carry element data forward if a previous pals.json had it
    prev = {}
    pj = os.path.join(OUT, "pals.json")
    if os.path.exists(pj):
        try: prev = {x["dex"]: x.get("elements", []) for x in json.load(open(pj))}
        except Exception: pass

    # pals.json — unique label disambiguates shared names
    name_counts = Counter(p["Name"] for p in db["Pals"])
    pals = []
    for p in db["Pals"]:
        d = dex_of(p)
        label = p["Name"] if name_counts[p["Name"]] == 1 else f'{p["Name"]} #{d}'
        pals.append({"name": p["Name"], "label": label, "dex": d, "elements": prev.get(d, [])})
    pals.sort(key=lambda x: (int(x["dex"][:3]), x["dex"]))

    # breeding.json — authoritative, from palcalc, keyed by sorted dex pair
    forward, gendered = {}, {}
    for e in tbl:
        a, b, c = e["Parent1InternalName"], e["Parent2InternalName"], e["ChildInternalName"]
        if a not in int2dex or b not in int2dex or c not in int2dex:
            sys.exit(f"FATAL: unknown internal name in table ({a},{b},{c}).")
        da, dbx, dc = int2dex[a], int2dex[b], int2dex[c]
        key = "|".join(sorted((da, dbx)))
        if e["Parent1Gender"] != "WILDCARD" or e["Parent2Gender"] != "WILDCARD":
            gendered.setdefault(key, []).append(
                {"p1": da, "p1_gender": e["Parent1Gender"], "p2": dbx,
                 "p2_gender": e["Parent2Gender"], "child": dc})
        else:
            forward[key] = dc

    # derive special-combo overrides (for result badges) + validate reconstruction
    truth = {frozenset((a, b)): c for e in tbl
             for a, b, c in [(e["Parent1InternalName"], e["Parent2InternalName"], e["ChildInternalName"])]
             if e["Parent1Gender"]=="WILDCARD" and e["Parent2Gender"]=="WILDCARD" and a != b}
    cnt   = Counter(truth.values())
    uniq  = {c for c, n in cnt.items() if n <= 20}
    never = {nm for nm in palI if nm not in cnt}
    excl  = uniq | never
    def formula(a, b, ex):
        tp = math.floor((palI[a]["BreedingPower"] + palI[b]["BreedingPower"] + 1) / 2)
        best = None
        for nm, pp in palI.items():
            if nm in ex: continue
            key = (abs(pp["BreedingPower"] - tp), -pp["BreedingPowerPriority"], 1 if pp["Id"]["IsVariant"] else 0)
            if best is None or key < best[0]: best = (key, nm)
        return best[1]
    overrides = {k: v for k, v in truth.items() if v in uniq}
    overrides = {k: v for k, v in overrides.items() if formula(*tuple(k), excl) != v}
    mism = sum(1 for k, c in truth.items()
               if (overrides[k] if k in overrides else formula(*tuple(k), excl)) != c)

    special = []
    for k, v in overrides.items():
        a, b = tuple(k)
        special.append({"p1": int2dex[a], "p2": int2dex[b], "child": int2dex[v]})
    special.sort(key=lambda s: dex2name[s["child"]])

    os.makedirs(OUT, exist_ok=True)
    json.dump(pals, open(os.path.join(OUT, "pals.json"), "w"), ensure_ascii=False, indent=1)
    json.dump({"forward": forward, "gendered": gendered},
              open(os.path.join(OUT, "breeding.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(special, open(os.path.join(OUT, "special_combos.json"), "w"), ensure_ascii=False, indent=1)
    json.dump({"source": "tylercamp/palcalc", "palcalc_version": db.get("Version"),
               "built": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "pals": len(pals), "pairs": len(forward), "gendered_pairs": len(gendered),
               "special_combos": len(special),
               "validation": "ok" if mism == 0 else f"warn:{mism}"},
              open(os.path.join(OUT, "meta.json"), "w"), indent=1)

    print(f"pals={len(pals)} pairs={len(forward)} gendered={len(gendered)} special={len(special)}")
    print("validation:", "OK — formula reproduces table" if mism == 0
          else f"::warning:: {mism} mismatches (table stays authoritative; badges may drift)")

if __name__ == "__main__":
    main()

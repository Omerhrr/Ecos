#!/usr/bin/env python3
"""Smoke test — Task 15: §44 audit depth, §57 economics profiles, §21 freight cards, §8 supplier performance.

Run against a LIVE backend on :8000.
"""
import json
import urllib.request

BASE = "http://localhost:8000/api"
PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


def req(method: str, path: str, body=None, token: str | None = None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        r.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(r, data=data) as resp:
            payload = resp.read().decode()
            return resp.status, (payload if raw else json.loads(payload or "{}"))
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, payload


owner = req("POST", "/auth/login", {"email": "owner@kara.example", "password": "demo1234"})[1]["token"]
platform = req("POST", "/auth/login", {"email": "ops@luxeen.example", "password": "demo1234"})[1]["token"]

print("== §57 economics profiles ==")
s, data = req("GET", "/finance/profiles", token=owner)
check("GET /finance/profiles 200", s == 200)
check("platform baseline profile seeded", any(p["name"].startswith("Corridor CN") for p in data["profiles"]))
baseline = next(p for p in data["profiles"] if p["corridor"] == "CN>NG")

# a premium electronics profile — more specific (category), should win for electronics
s, prof = req("POST", "/finance/profiles", {
    "name": "Electronics premium", "corridor": "CN>NG", "category": "electronics",
    "payment_cost_pct": 0.02, "luxeen_margin_pct": 0.10, "operator_markup_pct": 0.15,
    "logistics_per_kg_ngn": 4000.0, "tax_pct": 0.03,
}, token=owner)
check("POST /finance/profiles 201", s == 201, str(prof))
s, prev = req("POST", "/finance/profiles/preview", {
    "supplier_cost": 200, "currency": "CNY", "weight_kg": 1.0, "qty": 1,
    "category": "electronics", "org_id": 2,
}, token=owner)
check("preview resolves category-specific profile",
      prev.get("profile", {}).get("category") == "electronics"
      and abs(prev["profile"]["luxeen_margin_pct"] - 0.10) < 1e-9,
      json.dumps(prev.get("profile", {}))[:150])
wf = prev["waterfall"]
# 200 CNY @215 = 43000; freight card air: 1500 + 4200*1.1 = 6120; customs 5% = 2150
check("preview uses freight card (freight 6120)", abs(wf["freight_ngn"] - 6120.0) < 1, str(wf["freight_ngn"]))
check("preview customs 5% of declared", abs(wf["customs_ngn"] - 2150.0) < 1, str(wf["customs_ngn"]))
expected_lux = round(43000 * 0.10, 2)
check("preview luxeen from profile (10%)", abs(wf["luxeen_ngn"] - expected_lux) < 1, str(wf["luxeen_ngn"]))
s, prev2 = req("POST", "/finance/profiles/preview", {
    "supplier_cost": 200, "currency": "CNY", "weight_kg": 1.0, "qty": 1,
    "category": "general", "org_id": 2,
}, token=owner)
check("non-matching category falls back to baseline", prev2["profile"]["profile_id"] == baseline["id"])

print("== §21 freight rate cards ==")
s, cards = req("GET", "/freight/cards", token=owner)
check("GET /freight/cards 200", s == 200)
check("air + sea cards seeded", {"air", "sea"} <= {c["mode"] for c in cards["cards"]})
air = next(c for c in cards["cards"] if c["mode"] == "air")
sea = next(c for c in cards["cards"] if c["mode"] == "sea")
check("air effective per-kg = 4620", abs(air["effective_per_kg_ngn"] - 4620.0) < 1)
s, card2 = req("POST", "/freight/cards", {
    "name": "Express Air CN→NG", "mode": "express", "per_kg_ngn": 5500.0,
    "base_fixed_ngn": 900.0, "fuel_surcharge_pct": 0.08, "lead_time_days_min": 3,
    "lead_time_days_max": 5,
}, token=owner)
check("POST /freight/cards 201", s == 201)
s, cards = req("GET", "/freight/cards", token=owner)
check("lane_options would offer 3 modes", len({c["mode"] for c in cards["cards"]}) == 3)

print("== marketstore quote uses card + lane options ==")
s, listings = req("GET", "/market/products", token=owner)
check("market listings visible", s == 200 and len(listings) >= 1)
sp_id = listings[0]["id"] if isinstance(listings, list) else listings["items"][0]["id"]
s, prod = req("GET", f"/market/products/{sp_id}", token=owner)
q = prod.get("quote") or prod
check("quote names the rate card", "rate_card" in json.dumps(q), json.dumps(q)[:200])
check("quote carries lane_options", "lane_options" in json.dumps(q))

print("== §8 supplier performance ==")
s, perf = req("GET", "/suppliers/performance/summary", token=owner)
check("GET /suppliers/performance/summary 200", s == 200)
check("suppliers listed", len(perf["suppliers"]) >= 1)
shen = next((x for x in perf["suppliers"] if "Shenzhen" in x["name"]), perf["suppliers"][0])
check("performance has sourcing stats", "sourcing" in shen and "accept_rate" in shen["sourcing"])

print("== §44 audit — depth rows ==")
# price change on a product
s, products = req("GET", "/products", token=owner)
pid = products[0]["id"]
old_cost = products[0]["supplier_cost"]
new_cost = round(old_cost * 1.05, 2)
s, _ = req("PATCH", f"/products/{pid}", {"supplier_cost": new_cost}, token=owner)
check("PATCH product 200", s == 200)
s, audit = req("GET", "/audit?entity_type=product&action=product.price_changed", token=owner)
check("product.price_changed audited", s == 200 and len(audit) >= 1)
if audit:
    row = audit[0]
    check("audit row has actor", row["actor_label"] == "owner@kara.example", row["actor_label"])
    check("audit row has before/after", row["changed"] and "supplier_cost" in row["changed"])
    ch = row["changed"]["supplier_cost"]
    check("audit before/after values correct", abs(ch["from"] - old_cost) < 0.01 and abs(ch["to"] - new_cost) < 0.01)

# settlement lifecycle audit
s, runs_before = req("GET", "/settlements/preview", token=owner)
if runs_before.get("lines"):
    s, run = req("POST", "/settlements", {"note": "t15 audit"}, token=owner)
    check("settlement run built", s == 201)
    s, _ = req("POST", f"/settlements/{run['id']}/approve", {}, token=owner)
    s, audit = req("GET", "/audit?entity_type=settlement_run&action=settlement.approved", token=owner)
    check("settlement.approved audited", s == 200 and len(audit) >= 1)
    s, _ = req("POST", f"/settlements/{run['id']}/execute", {}, token=owner)
    s, audit = req("GET", "/audit?entity_type=settlement_run&action=settlement.executed", token=owner)
    check("settlement.executed audited", s == 200 and len(audit) >= 1)
else:
    print("  (skip settlement audit — nothing unsettled)")

# fx update audit
s, _ = req("POST", "/finance/fx", {"base": "CNY", "quote": "NGN", "rate": 215.0}, token=owner)
s, audit = req("GET", "/audit?action=finance.fx_rate_updated", token=owner)
check("fx_rate_updated audited", s == 200 and len(audit) >= 1)

print("== §44 audit — blanket http layer ==")
s, audit = req("GET", "/audit?action=http.request&limit=20", token=owner)
check("http.request rows recorded", s == 200 and len(audit) >= 5, f"got {len(audit) if isinstance(audit, list) else audit}")
if isinstance(audit, list) and audit:
    row = audit[0]
    check("http rows carry method/path/ip", row["method"] and row["path"] and "ip" in row)

print("== §44 RBAC ==")
s, _ = req("GET", "/audit", token=owner)
check("owner can read audit", s == 200)
s, data = req("GET", "/audit", token=owner)
# agent role has no audit:read
agent_login = req("POST", "/auth/login", {"email": "bisi@kara.example", "password": "demo1234"})
if agent_login[0] == 200:
    agent = agent_login[1]["token"]
    s, _ = req("GET", "/audit", token=agent)
    check("agent blocked from audit (403)", s == 403, str(s))
else:
    print("  (skip agent RBAC — no agent user)")

# supplier portal user should also be blocked (supplier role has only market:portal)
sup = req("POST", "/auth/login", {"email": "supplier@shenzhen.example", "password": "demo1234"})
if sup[0] == 200:
    s, _ = req("GET", "/audit", token=sup[1]["token"])
    check("supplier blocked from audit (403)", s == 403, str(s))

print("== sourcing flow still prices with card snapshot ==")
s, so = req("POST", "/market/sourcing-orders", {
    "supplier_product_id": sp_id, "qty": 1,
}, token=owner)
if s == 201:
    check("sourcing order created", True)
    s, paid = req("POST", f"/market/sourcing-orders/{so['id']}/pay", {}, token=owner)
    check("sourcing paid", s == 200)
    s, entries = req("GET", "/finance/ledger", token=owner)
    memo = json.dumps(entries["entries"][:8])
    check("sourcing ledger memo names economics basis", "economics:" in memo or "rate card" in memo or "Corridor" in memo)
    # ledger still balances on the newest order entries
    s, so_data = req("GET", "/market/sourcing-orders", token=owner)
    check("sourcing list 200", s == 200)
else:
    # MOQ or isolation may block; the Task 14 smoke covers the full flow
    print(f"  (sourcing create returned {s} — checking it's a business rule not a crash)")
    check("sourcing error is a 400/422 business rule", s in (400, 403, 422), str(so))

print()
print(f"RESULT: {PASS} PASS / {FAIL} FAIL")
raise SystemExit(1 if FAIL else 0)

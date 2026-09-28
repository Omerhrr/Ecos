#!/usr/bin/env python3
"""Task 12 smoke — items 1-4 of the remaining list.

1. §24 COD remittance register (open/attach -> submit -> reconcile -> ledger true-up)
2. §10 Catalog depth (variants/SKUs/videos + variant-aware checkout + snapshots)
3. §15 LP versioning/scheduling (publish snapshots, restore, scheduled auto-publish)
4. §43 Token refresh (rotate, new token works, old token still valid until exp)
"""
import json
import time
import urllib.request

BASE = "http://localhost:8000/api"
PASSED = 0
FAILED = 0


def call(method, path, token=None, body=None, expect=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            status, payload = r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
    if expect and status != expect:
        raise AssertionError(f"{method} {path} -> {status} (expected {expect}): {payload}")
    return status, payload


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}  {extra}")


print("== login ==")
_, login = call("POST", "/auth/login", body={"email": "owner@kara.example", "password": "demo1234"}, expect=200)
TOKEN = login["token"]
check("login returns token", bool(TOKEN))

print("== item 2: catalog depth (§10 variants/videos) ==")
_, prods = call("GET", "/products", token=TOKEN, expect=200)
target = next(p for p in prods if p["variants"])
vid = target["variants"][0]["id"]
base_price = target["pricing"]["ecos_price_ngn"]
v_price = target["variants"][0]["unit_price_ngn"]
check("admin product carries variants + waterfall price", v_price > 0 and target["variants"], target["variants"])
check("product videos exposed to admin", isinstance(target["videos"], list))

_, variant_added = call("POST", f"/products/{target['id']}/variants", token=TOKEN, expect=201,
                        body={"option_name": "Color", "option_value": "Smoke Test Edition",
                              "cost_delta": 8.0, "weight_delta_kg": 0.05, "stock": 3})
check("variant create auto-SKUs", variant_added["sku"].startswith(f"P{target['id']}-"), variant_added)

_, pdp = call("GET", f"/public/products/{target['slug']}", expect=200)
check("public PDP shows variants (customer-safe)", any(v["id"] == variant_added["id"] for v in pdp["variants"]))
check("public variant hides SKU/cost", all("sku" not in v and "cost_delta" not in v for v in pdp["variants"]))
check("public PDP shows videos", isinstance(pdp["videos"], list))

_, quote = call("POST", "/public/checkout/quote", expect=200,
                body={"items": [{"product_slug": target["slug"], "qty": 2, "variant_id": variant_added["id"]}]})
check("quote prices variant line + label",
      quote["lines"][0]["title"].endswith("Smoke Test Edition") and quote["lines"][0]["unit_price"] == variant_added["unit_price_ngn"], quote)

bad_status, _ = call("POST", "/public/checkout/quote",
                     body={"items": [{"product_slug": target["slug"], "qty": 1, "variant_id": 999999}]})
check("unknown variant rejected", bad_status == 400, bad_status)

stock_before = target["stock"]
variant_stock_before = variant_added["stock"]
_, co = call("POST", "/public/checkout", expect=201, body={
    "items": [{"product_slug": target["slug"], "qty": 2, "variant_id": variant_added["id"]}],
    "full_name": "Ada Variant", "contact_phone": "+234 807 777 1201",
    "address": "12 Variant Lane", "city": "Lagos", "state": "Lagos",
    "payment_method": "cod",
})
check("variant checkout places real order", co.get("ok") and co["order_id"] > 0, co)
_, order = call("GET", f"/orders/{co['order_id']}", token=TOKEN, expect=200)
oi = order["items"][0]
check("order item snapshots variant label", oi.get("variant_label") == "Color: Smoke Test Edition", oi)
check("order item snapshot price = variant waterfall", abs(oi["unit_price"] - variant_added["unit_price_ngn"]) < 0.01, oi["unit_price"])
_, prods_after = call("GET", "/products", token=TOKEN, expect=200)
t_after = next(p for p in prods_after if p["id"] == target["id"])
v_after = next(v for v in t_after["variants"] if v["id"] == variant_added["id"])
check("product stock decremented by 2", t_after["stock"] == stock_before - 2, t_after["stock"])
check("variant stock decremented by 2", v_after["stock"] == variant_stock_before - 2, v_after["stock"])

print("== item 1: COD remittance register (§24) ==")
# confirm the fresh order, then drive it to delivered so its COD is collected
call("POST", f"/orders/{co['order_id']}/transition", token=TOKEN, expect=200,
     body={"status": "confirmed", "actor": "smoke"})
_, ship = call("POST", f"/shipments/create-for-order/{co['order_id']}", token=TOKEN, expect=201)
CARRIER = ship["carrier"]
for code in ["picked_up", "customs", "out_for_delivery", "delivered"]:
    call("POST", f"/shipments/{ship['id']}/events", token=TOKEN, expect=200,
         body={"code": code, "description": f"smoke {code}", "location": "Lagos"})
_, pay_list = call("GET", "/payments", token=TOKEN, expect=200)
pay = next(p for p in pay_list if p["order_id"] == co["order_id"])
check("COD auto-collected at delivery", pay["status"] == "paid" and pay["reconciled"] in (0, False), pay)

_, reg = call("POST", "/cod/registers", token=TOKEN, expect=201,
              body={"carrier": CARRIER, "note": "smoke run"})
my_line = next(l for l in reg["lines"] if l["order_id"] == co["order_id"])
other_lines = [l for l in reg["lines"] if l["order_id"] != co["order_id"]]
check("register auto-attaches collected COD (incl. ours)",
      my_line in reg["lines"] and abs(my_line["expected_amount"] - pay["amount"]) < 0.01, reg)
_, submitted = call("POST", f"/cod/registers/{reg['id']}/submit", token=TOKEN, expect=200,
                    body={"remitted_amount": reg["expected_amount"] - 1000, "reference": "SMOKE-RCPT-1"})
check("remittance recorded (shortage 1000)", submitted["status"] == "remitted" and submitted["remitted_amount"] == reg["expected_amount"] - 1000)
_, recon = call("POST", f"/cod/registers/{reg['id']}/reconcile", token=TOKEN, expect=200,
                body={"counts": [{"line_id": my_line["id"], "counted_amount": my_line["expected_amount"] - 1000}]})
check("reconcile closes with variance -1000", recon["status"] == "reconciled" and abs(recon["variance_amount"] + 1000) < 0.01, recon)
_, ledger = call("GET", "/finance/ledger", token=TOKEN, expect=200)
cod_var = [e for e in ledger["entries"] if e["entry_type"] == "cod_variance"]
check("cod_variance ledger true-up written (courier -1000 / operator +1000)",
      any(abs(e["amount"] + 1000) < 0.01 and e["party"] == "logistics" for e in cod_var)
      and any(abs(e["amount"] - 1000) < 0.01 and e["party"] == "operator" for e in cod_var), cod_var)
check("ledger still balances after variance (double-entry)",
      abs(sum(ledger["totals_by_type"].values())) < 0.01, ledger["totals_by_type"])
_, pay_after = call("GET", f"/payments", token=TOKEN, expect=200)
pay_after_row = next(p for p in pay_after if p["id"] == pay["id"])
check("payment stamped reconciled", pay_after_row["reconciled"] in (1, True), pay_after_row)
_, summary = call("GET", "/cod/summary", token=TOKEN, expect=200)
check("summary shows no outstanding for the carrier", all(b["carrier"] != CARRIER for b in summary["outstanding_by_carrier"]))
second_status, _second = call("POST", "/cod/registers", token=TOKEN, body={"carrier": CARRIER})
check("second register with nothing attached -> 404", second_status == 404, second_status)

print("== item 3: LP versioning + scheduling (§15) ==")
_, lp = call("POST", "/landing-pages", token=TOKEN, expect=201, body={
    "title": "Smoke LP", "slug": f"smoke-lp-{int(time.time())}",
    "blocks": [{"id": "b1", "type": "hero", "headline": "V1 headline"}],
    "theme": {"primary": "#00b374"}, "seo": {},
})
lp_id = lp["id"]
_, pub = call("POST", f"/landing-pages/{lp_id}/publish", token=TOKEN, expect=200)
check("first publish -> published", pub["status"] == "published")
_, versions = call("GET", f"/landing-pages/{lp_id}/versions", token=TOKEN, expect=200)
snaps = [v for v in versions if not v["is_current"]]
check("publish snapshot v1 recorded", len(snaps) == 1 and snaps[-1]["version_no"] == 1, versions)
call("PATCH", f"/landing-pages/{lp_id}", token=TOKEN, expect=200,
     body={"blocks": [{"id": "b1", "type": "hero", "headline": "V2 headline — new angle"}]})
call("POST", f"/landing-pages/{lp_id}/publish", token=TOKEN, expect=200)
_, versions2 = call("GET", f"/landing-pages/{lp_id}/versions", token=TOKEN, expect=200)
check("republish -> v2 snapshot", len([v for v in versions2 if not v["is_current"]]) == 2)
_, pub_slug = call("GET", f"/public/pages/{lp['slug']}", expect=200)
check("live page serves v2 copy", pub_slug["blocks"][0]["headline"] == "V2 headline — new angle")
_, restored = call("POST", f"/landing-pages/{lp_id}/versions/1/restore", token=TOKEN, expect=200, body={"publish": False})
check("restore v1 on a live page -> rollback live immediately + snapshot",
      restored["blocks"][0]["headline"] == "V1 headline" and restored["status"] == "published", restored["status"])
# draft-path restore: unpublish, diverge the draft, restore v1 -> stays draft
call("POST", f"/landing-pages/{lp_id}/unpublish", token=TOKEN, expect=200)
call("PATCH", f"/landing-pages/{lp_id}", token=TOKEN, expect=200,
     body={"blocks": [{"id": "b1", "type": "hero", "headline": "draft experiment"}]})
_, restored2 = call("POST", f"/landing-pages/{lp_id}/versions/1/restore", token=TOKEN, expect=200, body={"publish": False})
check("restore v1 on a draft page -> stays draft for review",
      restored2["blocks"][0]["headline"] == "V1 headline" and restored2["status"] == "draft", restored2["status"])
# scheduled publish: +2 minutes; scheduler ticks every 60s (boot tick already ran)
from datetime import datetime, timedelta, timezone
when = (datetime.now(timezone.utc) + timedelta(seconds=130)).isoformat()
_, sched = call("POST", f"/landing-pages/{lp_id}/schedule", token=TOKEN, expect=200, body={"publish_at": when})
check("schedule accepted", sched["scheduled_at"] is not None)
past_status, _ = call("POST", f"/landing-pages/{lp_id}/schedule", token=TOKEN,
                      body={"publish_at": "2020-01-01T00:00:00Z"})
check("past schedule rejected", past_status == 400, past_status)
print("  ...  waiting for the scheduler tick (needs the due moment to pass)")
deadline = time.time() + 200
flipped = None
while time.time() < deadline:
    time.sleep(10)
    _, page_now = call("GET", f"/landing-pages/{lp_id}", token=TOKEN, expect=200)
    if page_now["status"] == "published" and not page_now["scheduled_at"]:
        flipped = True
        break
check("scheduler auto-published the page on time", flipped is True)
_, versions3 = call("GET", f"/landing-pages/{lp_id}/versions", token=TOKEN, expect=200)
notes = [v.get("note") for v in versions3 if not v["is_current"]]
check("scheduled publish snapshotted as version", any("scheduled publish" in (n or "") for n in notes), notes)
_, live3 = call("GET", f"/public/pages/{lp['slug']}", expect=200)
check("public now serves restored v1 copy", live3["blocks"][0]["headline"] == "V1 headline")

print("== item 4: token refresh (§43) ==")
_, fresh = call("POST", "/auth/refresh", token=TOKEN, expect=200)
check("refresh rotates the token", bool(fresh["token"]) and fresh["token"] != TOKEN)
_, me2 = call("GET", "/auth/me", token=fresh["token"], expect=200)
check("rotated token authenticates", me2["user"]["email"] == "owner@kara.example")
_, me3 = call("GET", "/auth/me", token=TOKEN, expect=200)
check("previous token still valid (12h lease, no blacklist)", me3["user"]["id"] == me2["user"]["id"])
stale_status, _ = call("POST", "/auth/refresh", token="garbage.token.value")
check("garbage token cannot refresh", stale_status == 401, stale_status)

print(f"\n==== {PASSED} PASS / {FAILED} FAIL ====")
raise SystemExit(1 if FAILED else 0)

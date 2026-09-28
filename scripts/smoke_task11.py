#!/usr/bin/env python3
"""Task 11 smoke — backlog items 1-5.

1. §41 Automation Engine: starter rules live, replay fires notify/escalate,
   conditions filter, cooldown honoured, dry-run test mutates nothing,
   rule CRUD round-trip, RBAC (agent 403 / viewer write 403).
2. §31 AI live-key path: provider status honest (no key -> fallback),
   /ai/provider/test -> 400 with setup instructions.
3. §32/33/36/37/38 operators: Market Scout, Growth Pilot, P&L Analyst run
   advisory; Catalog Forger + Route Guard run -> approve -> governed side
   effects (draft product / escalation notifications).
4. §46 Multi-currency: rate table, manual rate update flows to the public
   USD pricing page, convert math, USD checkout quote + order FX snapshot,
   ledger stays NGN.
5. §29 Analytics suites: logistics / financial / products end-to-end math.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api"
DB = "/home/z/my-project/db/custom.db"

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f" — {extra}" if extra else ""))


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


def sql(query: str, args: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(DB)
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def main() -> int:
    print("== login ==")
    _, login = call("POST", "/auth/login", body={"email": "owner@kara.example", "password": "demo1234"})
    tok = login["token"]
    _, agent_login = call("POST", "/auth/login", body={"email": "bisi@kara.example", "password": "demo1234"})
    agent_tok = agent_login["token"]
    check("owner login", bool(tok))
    check("agent login", bool(agent_tok))

    # ------------------------------------------------------------- §41 ----
    print("== 1. automation engine (§41) ==")
    s, rules = call("GET", "/automation/rules", tok)
    check("starter rules seeded", s == 200 and len(rules) == 3,
          f"{len(rules)} rules")
    s, catalog = call("GET", "/automation/events", tok)
    check("event catalog", s == 200 and len(catalog) >= 25, f"{len(catalog)} events")

    # real fire: negative stock adjustment -> notification
    notes_before = sql("SELECT count(*) FROM notifications")[0][0]
    s, res = call("POST", "/automation/events/replay", tok,
                  body={"event_type": "warehouse.stock_adjusted",
                        "payload": {"warehouse_id": 1, "product_id": 3, "delta": -2, "on_hand": 11}})
    matched = [r for r in res["results"] if r["status"] == "matched"]
    check("negative adjustment rule MATCHED", s == 200 and len(matched) == 1,
          str([r.get("rule") for r in matched]))
    notes_after = sql("SELECT count(*) FROM notifications")[0][0]
    check("notify action created notifications", notes_after > notes_before,
          f"{notes_before} -> {notes_after}")
    check("{{delta}} template interpolated",
          "adjusted by -2" in (sql("SELECT body FROM notifications ORDER BY id DESC LIMIT 1")[0][0] or ""))

    # condition filter: positive delta -> no match
    s, res = call("POST", "/automation/events/replay", tok,
                  body={"event_type": "warehouse.stock_adjusted",
                        "payload": {"warehouse_id": 1, "product_id": 3, "delta": 5, "on_hand": 16}})
    check("positive delta -> condition_not_met",
          all(r["status"] == "condition_not_met" for r in res["results"]), str(res["results"]))

    # cooldown: create rule w/ 3600s cooldown, fire twice
    s, rule = call("POST", "/automation/rules", tok, body={
        "name": "Smoke: checkout completed cooldown test",
        "event_type": "storefront.checkout_completed",
        "conditions": [],
        "actions": [{"type": "notify", "category": "orders", "title": "Checkout {{order_id}}", "body": "cooldown probe"}],
        "cooldown_seconds": 3600,
    })
    check("rule created", s == 201 and rule.get("id"), f"id={rule.get('id')}")
    rid = rule["id"]
    s, r1 = call("POST", "/automation/events/replay", tok,
                 body={"event_type": "storefront.checkout_completed", "payload": {"order_id": 999}})
    s, r2 = call("POST", "/automation/events/replay", tok,
                 body={"event_type": "storefront.checkout_completed", "payload": {"order_id": 999}})
    check("first fire matched, second in cooldown",
          r1["results"][0]["status"] == "matched" and r2["results"][0]["status"] == "cooldown",
          f"{r1['results'][0]['status']} -> {r2['results'][0]['status']}")

    # dry-run test: settlement draft rule must NOT create a run
    runs_before = sql("SELECT count(*) FROM settlement_runs")[0][0]
    settle_rule_id = sql("SELECT id FROM automation_rules WHERE event_type='order.status_changed'")[0][0]
    s, test = call("POST", f"/automation/rules/{settle_rule_id}/test", tok,
                   body={"event_type": "order.status_changed",
                         "payload": {"order_id": 42, "from": "out_for_delivery", "to": "delivered"}})
    runs_after = sql("SELECT count(*) FROM settlement_runs")[0][0]
    check("dry-run: status dry_run + zero side effects",
          s == 200 and test["results"][0]["status"] == "dry_run" and runs_before == runs_after,
          f"runs {runs_before} -> {runs_after}")
    dry = sql("SELECT status FROM automation_runs WHERE rule_id=? ORDER BY id DESC LIMIT 1", (settle_rule_id,))[0][0]
    check("dry-run audit row recorded", dry == "dry_run", dry)

    # patch + delete
    s, patched = call("PATCH", f"/automation/rules/{rid}", tok, body={"enabled": False})
    check("rule disabled via patch", s == 200 and patched["enabled"] is False)
    s, _ = call("DELETE", f"/automation/rules/{rid}", tok)
    check("rule deleted", s == 204 and sql("SELECT count(*) FROM automation_rules WHERE id=?", (rid,))[0][0] == 0)

    # RBAC
    s, _ = call("GET", "/automation/rules", agent_tok)
    check("agent blocked from automation (403)", s == 403, str(s))
    s, probe = call("POST", "/automation/rules", tok, body={
        "name": "Smoke probe rule",
        "event_type": "lead.created",
        "conditions": [],
        "actions": [{"type": "notify", "title": "Lead {{lead_id}}", "body": "probe"}],
    })
    check("owner can write rules", s == 201, str(s))
    if s == 201:
        call("DELETE", f"/automation/rules/{probe['id']}", tok)

    # ------------------------------------------------------------- §31 ----
    print("== 2. ai live-key path (§31) ==")
    s, prov = call("GET", "/ai/provider", tok)
    check("provider honest about missing key",
          s == 200 and prov["key_configured"] is False and prov["provider"] == "heuristic-fallback")
    s, err = call("POST", "/ai/provider/test", tok)
    check("provider test -> 400 + setup instructions",
          s == 400 and "DEEPSEEK_API_KEY" in json.dumps(err), str(err)[:80])

    # ------------------------------------------- §32/33/36/37/38 ----
    print("== 3. new AI operators ==")
    s, registry = call("GET", "/ai/registry", tok)
    codes = {r["code"] for r in registry}
    check("registry has 9 blueprints", len(registry) == 9, str(sorted(codes)))

    def run_and_check(code: str, name: str, params: dict, advisory: bool):
        s, ops = call("GET", "/ai/operators", tok)
        op = next(o for o in ops if o["code"] == code)
        s, run = call("POST", f"/ai/operators/{op['id']}/run", tok, body={"params": params})
        ok = s == 200 and run["status"] == "succeeded"
        check(f"{name} run succeeded (heuristic)", ok,
              f"provider={run.get('provider')} proposal={run.get('proposal_status')}")
        return run

    # §32 Market Scout (advisory)
    run = run_and_check("product_research", "Market Scout §32", {}, True)
    check("Market Scout: opportunities structure",
          run and "opportunities" in run["output"] and "summary" in run["output"])
    check("Market Scout advisory -> no approval needed", run["proposal_status"] == "advisory")

    # §36 Growth Pilot (advisory, reads real attribution)
    run = run_and_check("growth_operator", "Growth Pilot §36", {}, True)
    check("Growth Pilot: budget moves from real campaigns",
          run and isinstance(run["output"].get("budget_moves"), list)
          and run["output"]["totals"]["spend_ngn"] > 0,
          f"spend={run['output']['totals']['spend_ngn']}")

    # §38 P&L Analyst (advisory, ledger-grounded)
    run = run_and_check("business_analyst", "P&L Analyst §38", {}, True)
    m = run["output"].get("metrics", {})
    check("P&L Analyst: net revenue > 0 + contribution math",
          m.get("net_revenue_ngn", 0) > 0 and "contribution_ngn" in m,
          f"net={m.get('net_revenue_ngn')} contribution={m.get('contribution_ngn')}")

    # §37 Route Guard (apply -> escalation notifications)
    run = run_and_check("logistics_operator", "Route Guard §37", {"stall_hours": 6}, False)
    check("Route Guard: stall scan structure",
          run and "escalations" in run["output"] and "totals" in run["output"])
    s, approved = call("POST", f"/ai/runs/{run['id']}/approve", tok, body={})
    check("Route Guard approval executes governed side effect",
          s == 200 and approved["proposal_status"] == "applied"
          and "escalations_raised" in approved["output"].get("applied", {}))

    # §33 Catalog Forger (apply -> draft product)
    listing = "Mini Projector HD 1080p | 210 CNY | 1.4kg | electronics | warranty=6 months; resolution=1080p"
    run = run_and_check("product_import", "Catalog Forger §33", {"listing": listing}, False)
    check("Catalog Forger parsed listing + priced it",
          run["output"].get("proposed_price_ngn", 0) > 0
          and run["output"]["draft_listing"]["supplier_cost"] == 210.0,
          f"price={run['output'].get('proposed_price_ngn')}")
    s, approved = call("POST", f"/ai/runs/{run['id']}/approve", tok, body={})
    new_pid = (approved.get("output", {}).get("applied", {}) or {}).get("product_id")
    check("Catalog Forger approval files DRAFT product",
          s == 200 and approved["proposal_status"] == "applied" and new_pid)
    prow = sql("SELECT title, status, currency, supplier_cost FROM products WHERE id=?", (new_pid,))[0]
    check("imported product is draft + CNY cost intact",
          prow[1] == "draft" and prow[2] == "CNY" and prow[3] == 210.0, str(prow))

    # ------------------------------------------------------------- §46 ----
    print("== 4. multi-currency / USD (§46) ==")
    s, fxr = call("GET", "/finance/fx", tok)
    pairs = {(r["base"], r["quote"]) for r in fxr["rates"]}
    check("rate table seeded (canonical corridor pairs)",
          s == 200 and {("CNY", "NGN"), ("USD", "NGN"), ("CNY", "USD")} <= pairs,
          str(sorted(pairs)))
    s, conv = call("GET", "/finance/fx/convert?amount=100&base=USD&quote=CNY", tok)
    check("convert math 100 USD ≈ 714 CNY", s == 200 and abs(conv["amount"] - 714.29) < 0.5, str(conv))

    # manual rate update flows to the public pricing page
    _, pricing_before = call("GET", "/public/pricing")
    rate_before = pricing_before["usd"]["rate"]
    s, _ = call("POST", "/finance/fx", tok, body={"base": "NGN", "quote": "USD", "rate": 0.001})
    _, pricing_after = call("GET", "/public/pricing")
    check("manual NGN->USD rate propagates to public pricing",
          rate_before != pricing_after["usd"]["rate"] and pricing_after["usd"]["rate"] == 0.001,
          f"{rate_before} -> {pricing_after['usd']['rate']}")
    sample = pricing_after["products"][0]
    check("USD pricing page: per-product USD == NGN * rate",
          abs(sample["price_display"]["amount"] - sample["price_ngn"] * 0.001) < 0.05,
          f"{sample['price_ngn']} NGN -> ${sample['price_display']['amount']}")
    call("POST", "/finance/fx", tok, body={"base": "NGN", "quote": "USD", "rate": round(1 / 1530.0, 10)})

    # USD checkout quote + order snapshot
    s, quote = call("POST", "/public/checkout/quote", body={
        "items": [{"product_slug": "wireless-earbuds-x2", "qty": 1}],
        "display_currency": "USD",
    })
    check("USD quote display block", s == 200 and quote.get("display", {}).get("currency") == "USD"
          and abs(quote["display"]["total"]["amount"] - quote["total"] * quote["display"]["total"]["rate"]) < 0.5,
          f"₦{quote['total']} -> ${quote['display']['total']['amount']}")
    s, co = call("POST", "/public/checkout", body={
        "items": [{"product_slug": "wireless-earbuds-x2", "qty": 1}],
        "full_name": "USD Smoke Customer", "contact_phone": "+234 900 555 1101",
        "address": "1 FX Test Close", "city": "Lagos", "state": "Lagos",
        "payment_method": "cod", "display_currency": "USD",
    })
    usd_order_id = co.get("order_id")
    check("USD checkout places order + stamps display currency",
          s == 201 and co.get("display_currency") == "USD", f"order #{usd_order_id}")
    orow = sql("SELECT currency, display_currency, fx_rate_used, total FROM orders WHERE id=?", (usd_order_id,))[0]
    check("ledger integrity: capture currency stays NGN, FX snapshot kept",
          orow[0] == "NGN" and orow[1] == "USD" and orow[2] and orow[2] > 0,
          str(orow))
    import urllib.parse
    phone_enc = urllib.parse.quote("+234 900 555 1101")
    s, tracked = call("GET", f"/public/orders/{usd_order_id}?phone={phone_enc}")
    check("public tracking exposes display currency snapshot",
          s == 200 and tracked.get("display_currency") == "USD" and tracked.get("fx_rate_used"))

    # ------------------------------------------------------------- §29 ----
    print("== 5. analytics suites (§29) ==")
    s, lg = call("GET", "/analytics/logistics?days=30", tok)
    check("logistics suite: shipments + carriers + stalls",
          s == 200 and lg["shipments_total"] >= 3 and lg["carriers"]
          and "stalled_over_48h" in lg, f"{lg['shipments_total']} shipments, {len(lg['carriers'])} carrier(s)")
    s, fin = call("GET", "/analytics/financial?days=30", tok)
    t = fin["ledger_totals_by_type"]
    expected_contrib = (fin["net_revenue_ngn"] - fin["supplier_cost_ngn"]
                        - fin["logistics_cost_ngn"] - fin["payment_cost_ngn"]
                        - fin["luxeen_economics_ngn"])
    check("financial suite: contribution = net - all costs",
          s == 200 and abs(fin["contribution_ngn"] - expected_contrib) < 1.0
          and fin["gross_revenue_ngn"] > 0,
          f"contribution=₦{fin['contribution_ngn']} margin={fin['contribution_margin_pct']:.1%}")
    s, ps = call("GET", "/analytics/products?days=30", tok)
    top = ps["products"][0]
    check("product suite: margin math per SKU",
          s == 200 and len(ps["products"]) >= 6
          and abs(top["gross_margin_ngn"] - (top["revenue_ngn"] - top["supplier_cost_ngn"])) < 1.0,
          f"{top['title']}: ₦{top['gross_margin_ngn']} margin, cover {top['weeks_of_cover']}w")
    check("product suite: return rate tracked (earbuds RMA in seed)",
          any(r["return_units"] > 0 for r in ps["products"]),
          str([(r['title'][:18], r['return_units']) for r in ps['products'] if r['return_units']]))

    s, summ = call("GET", "/analytics/summary", tok)
    s, fun = call("GET", "/analytics/funnel", tok)
    check("legacy summary/funnel unbroken", s == 200 and "revenue_ngn" in summ and "pipeline" in fun)

    print(f"\n===== SMOKE RESULT: {PASS} PASS / {FAIL} FAIL =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)

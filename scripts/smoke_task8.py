#!/usr/bin/env python3
"""Task 8 smoke tests: warehouse §22 (PO receipts -> putaway, pick waves),
public checkout cart -> direct orders §14, notifications channel workers §39 P3.

Run: backend/.venv/bin/python scripts/smoke_task8.py
"""
import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8000/api"
TOKEN = None
PASSES = 0
FAILS = 0


def req(method: str, path: str, body=None, auth=True, expect=200):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if auth and TOKEN:
        r.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(r) as resp:
            code, payload = resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        code, payload = e.code, json.loads(e.read().decode() or "{}")
    return code, payload


def check(name: str, cond: bool, detail: str = ""):
    global PASSES, FAILS
    if cond:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILS += 1
        print(f"  FAIL  {name}  {detail}")


def main() -> int:
    global TOKEN

    print("== setup ==")
    code, data = req("POST", "/auth/login", {"email": "owner@kara.example", "password": "demo1234"}, auth=False)
    TOKEN = data.get("token")
    check("login (token field)", code == 200 and bool(TOKEN))
    code, data = req("POST", "/auth/login", {"email": "bisi@kara.example", "password": "demo1234"}, auth=False)
    AGENT_TOKEN = data.get("token")

    print("== warehouse §22: locations + opening stock ==")
    code, whs = req("GET", "/warehouse")
    check("list warehouses", code == 200 and len(whs) >= 1)
    main_wh = next((w for w in whs if w["is_default"]), whs[0])
    check("default warehouse exists", main_wh.get("is_default") is True, str(main_wh.get("code")))
    check("opening balances received", main_wh["sku_count"] >= 6 and main_wh["units_on_hand"] > 500,
          f"skus={main_wh['sku_count']} units={main_wh['units_on_hand']}")

    code, new_wh = req("POST", "/warehouse", {"name": "Abuja Satellite", "city": "Abuja", "is_default": False})
    check("create warehouse", code == 201 and new_wh["code"].startswith("WH-"))

    code, overview = req("GET", "/warehouse/overview")
    check("stock overview rows", code == 200 and len(overview) >= 6)
    fan_row = next(r for r in overview if r["product_title"] == "Portable Neck Fan")
    fan_id = fan_row["product_id"]

    code, movements = req("GET", "/warehouse/movements?movement_type=receipt")
    check("receipt movements recorded", code == 200 and len(movements) >= 6)
    check("movement references seed", any(m["reference_type"] == "seed" for m in movements))

    print("== warehouse §22: adjust + transfer ==")
    # top up so re-runs never hit the negative guard
    code, _ = req("POST", "/warehouse/adjust",
                  {"warehouse_id": main_wh["id"], "product_id": fan_id, "delta": +10, "reason": "found pallet in back room"})
    check("adjust top-up (+10)", code == 200)
    stock_before = fan_row["on_hand"] + 10
    code, _ = req("POST", "/warehouse/adjust",
                  {"warehouse_id": main_wh["id"], "product_id": fan_id, "delta": -2, "reason": "damaged in storage"})
    check("adjust down (-2)", code == 200)
    code, row = req("GET", f"/warehouse/overview?product_id={fan_id}")
    row = next(r for r in row if r["warehouse_id"] == main_wh["id"])
    check("on_hand decremented", row["on_hand"] == stock_before - 2, f"{stock_before} -> {row['on_hand']}")

    transfer_qty = min(3, max(1, row["on_hand"]))
    code, _ = req("POST", "/warehouse/transfer",
                  {"from_warehouse_id": main_wh["id"], "to_warehouse_id": new_wh["id"],
                   "product_id": fan_id, "qty": transfer_qty})
    check(f"transfer {transfer_qty} unit(s) to Abuja", code == 200)
    code, rows = req("GET", f"/warehouse/overview?product_id={fan_id}")
    src = next(r for r in rows if r["warehouse_id"] == main_wh["id"])
    dst = next(r for r in rows if r["warehouse_id"] == new_wh["id"])
    check("transfer legs correct", src["on_hand"] == stock_before - 2 - transfer_qty and dst["on_hand"] == transfer_qty,
          f"src={src['on_hand']} dst={dst['on_hand']}")
    code, mvs = req("GET", f"/warehouse/movements?movement_type=transfer_out&product_id={fan_id}")
    check("transfer_out movement recorded", len(mvs) >= 1 and mvs[0]["qty"] == -transfer_qty)

    code, _ = req("POST", "/warehouse/transfer",
                  {"from_warehouse_id": main_wh["id"], "to_warehouse_id": new_wh["id"],
                   "product_id": fan_id, "qty": 99999})
    check("transfer overstock rejected", code == 400)

    print("== procurement x §22: PO goods receipt putaway ==")
    code, pos = req("GET", "/procurement?status=submitted")
    po = pos[0] if pos else None
    if po is None:
        # re-run friendly: no submitted PO left, raise one manually
        code, prods_adm = req("GET", "/products?status=active")
        code, sup = req("GET", "/suppliers")
        code, po = req("POST", "/procurement", {
            "supplier_id": prods_adm[0]["supplier_id"],
            "lines": [{"product_id": prods_adm[0]["id"], "qty": 5}],
            "note": "smoke test restock",
        })
        req("POST", f"/procurement/{po['id']}/submit")
        code, pos = req("GET", "/procurement?status=submitted")
        po = next(p for p in pos if p["id"] == po["id"])
    check("submitted PO present", po is not None)
    if po:
        receipts = {l["id"]: l["qty_ordered"] for l in po["lines"]}
        product_id = po["lines"][0]["product_id"]
        code, prod_before = req("GET", f"/products")
        before_stock = next(p["stock"] for p in prod_before if p["id"] == product_id)
        code, _ = req("POST", f"/procurement/{po['id']}/confirm")
        check("PO confirm", code == 200)
        code, _ = req("POST", f"/procurement/{po['id']}/receive", {"receipts": receipts, "warehouse_id": new_wh["id"]})
        check("PO receive to Abuja warehouse", code == 200)
        code, prod_after = req("GET", "/products")
        after_stock = next(p["stock"] for p in prod_after if p["id"] == product_id)
        check("product.stock incremented", after_stock - before_stock == sum(receipts.values()))
        code, rows = req("GET", f"/warehouse/overview?product_id={product_id}")
        dst_row = next(r for r in rows if r["warehouse_id"] == new_wh["id"])
        check("putaway landed at target warehouse", dst_row["on_hand"] == sum(receipts.values()),
              f"on_hand={dst_row['on_hand']} expected={sum(receipts.values())}")
        code, mvs = req("GET", f"/warehouse/movements?movement_type=receipt&product_id={product_id}")
        check("receipt movement refs PO", any(m["reference_type"] == "purchase_order" and m["reference_id"] == po["id"] for m in mvs))

    print("== pick waves §22: create -> pick -> pack -> complete ==")
    code, orders = req("GET", "/orders?status=confirmed")
    wave_orders = [o for o in orders if o["status"] == "confirmed"][:2]
    check("confirmed orders available", len(wave_orders) >= 1, f"got {len(wave_orders)}")
    if wave_orders:
        ids = [o["id"] for o in wave_orders]
        code, wave = req("POST", "/warehouse/waves", {"order_ids": ids})
        check("create wave", code == 201 and wave["status"] == "open" and wave["order_count"] == len(ids))
        check("wave lines built", len(wave.get("lines") or []) >= len(ids))

        # agent (front-line) can read but not write
        global_req = urllib.request.Request(BASE + "/warehouse/waves")
        global_req.add_header("Authorization", f"Bearer {AGENT_TOKEN}")
        try:
            with urllib.request.urlopen(global_req) as resp:
                agent_code = resp.status
        except urllib.error.HTTPError as e:
            agent_code = e.code
        check("agent reads warehouse OK", agent_code == 200)
        agent_req = urllib.request.Request(BASE + f"/warehouse/waves/{wave['id']}/pick", data=b"{}", method="POST")
        agent_req.add_header("Content-Type", "application/json")
        agent_req.add_header("Authorization", f"Bearer {AGENT_TOKEN}")
        try:
            with urllib.request.urlopen(agent_req) as resp:
                agent_pick = resp.status
        except urllib.error.HTTPError as e:
            agent_pick = e.code
        check("agent pick denied (403)", agent_pick == 403)

        code, wave = req("POST", f"/warehouse/waves/{wave['id']}/pick")
        check("pick wave", code == 200 and wave["status"] == "picking")
        check("lines picked", all(l["status"] == "picked" for l in wave["lines"]))
        code, wave = req("POST", f"/warehouse/waves/{wave['id']}/pack")
        check("pack wave", code == 200 and wave["status"] == "packed")
        code, wave = req("POST", f"/warehouse/waves/{wave['id']}/complete")
        check("complete wave", code == 200 and wave["status"] == "completed")

        code, shipments = req("GET", "/shipments")
        shipped = [s for s in shipments if s["order_id"] in ids]
        check("shipments created for waved orders", len(shipped) >= len(ids),
              f"{len(shipped)} shipments for {len(ids)} orders")
        code, order_detail = req("GET", f"/orders/{ids[0]}")
        check("order advanced to fulfilled", order_detail["status"] == "fulfilled", order_detail["status"])

        code, _ = req("POST", f"/warehouse/waves/{wave['id']}/pick")
        check("illegal re-pick rejected", code == 400)

    print("== checkout §14: quote -> order -> tracking ==")
    code, prods = req("GET", "/public/products", auth=False)
    check("public products", code == 200 and len(prods) >= 2)
    in_stock = [p for p in prods if p["in_stock"]]
    check("in-stock products available", len(in_stock) >= 2, f"got {len(in_stock)}")
    a, b = in_stock[0], in_stock[1]
    items = [{"product_slug": a["slug"], "qty": 2}, {"product_slug": b["slug"], "qty": 1}]

    code, quote = req("POST", "/public/checkout/quote", {"items": items}, auth=False)
    check("quote prices cart", code == 200 and len(quote["lines"]) == 2)
    expected_total = quote["items_total"]
    check("quote math", quote["total"] == expected_total + quote["delivery_fee"])

    checkout = {
        "items": items,
        "full_name": "Checkout Tester",
        "contact_phone": "+234 809 777 1234",
        "address": "5 Smoke Test Crescent",
        "city": "Lagos", "state": "Lagos",
        "payment_method": "cod",
        "note": "smoke test order",
        "utm": {"utm_source": "facebook", "utm_campaign": "q3-lagos-electronics"},
    }
    code, result = req("POST", "/public/checkout", checkout, auth=False)
    check("checkout places order", code == 201 and result["ok"], str(result)[:120])
    order_id = result.get("order_id")

    code, orders = req("GET", "/orders")
    new_order = next((o for o in orders if o["id"] == order_id), None)
    check("order visible to operator", new_order is not None)
    check("order totals match quote", new_order and abs(new_order["total"] - expected_total) < 0.01,
          f"order={new_order and new_order['total']} quote={expected_total}")
    check("order starts pending_confirmation", new_order and new_order["status"] == "pending_confirmation")
    check("COD payment pending", new_order and new_order["payment_method"] == "cod" and new_order["payment_status"] == "pending")

    # repeat checkout with same phone -> customer reused, not duplicated
    code, result2 = req("POST", "/public/checkout", {**checkout, "items": [{"product_slug": a["slug"], "qty": 1}]}, auth=False)
    check("second checkout OK", code == 201, str(result2)[:120])
    check("customer deduped by phone", result2.get("customer_id") == result.get("customer_id"))

    code, status = req("GET", f"/public/orders/{order_id}?phone=" + urllib.parse.quote("+234 809 777 1234"), auth=False)
    check("customer order tracking works", code == 200 and status["order_id"] == order_id)
    code, _ = req("GET", f"/public/orders/{order_id}?phone=wrong", auth=False)
    check("tracking guarded by phone", code == 403)

    code, notifications = req("GET", "/notifications?category=orders&limit=10")
    check("order.created fanned out in-app", any(f"#{order_id}" in n["title"] for n in notifications))

    print("== §39 Phase 3: outbox + channel workers ==")
    code, stats = req("GET", "/notifications/outbox/stats")
    check("outbox stats", code == 200 and "email" in stats["providers"] and "whatsapp" in stats["providers"])
    check("dev-console providers active", stats["providers"]["email"] == "dev-console")
    total_ob = sum(c["total"] for c in stats["by_channel"].values())
    check("outbox has queued rows (seed story)", total_ob > 0, f"total={total_ob}")

    code, rows = req("GET", "/notifications/outbox?channel=email&limit=5")
    check("outbox filtered by channel", code == 200 and all(r["channel"] == "email" for r in rows))
    check("email recipient is user email", all("@" in r["recipient"] for r in rows))

    code, wa = req("GET", "/notifications/outbox?channel=whatsapp&limit=5")
    check("whatsapp recipient is user phone", all("+234" in r["recipient"] for r in wa))

    code, processed = req("POST", "/notifications/outbox/process?limit=100")
    check("workers drain outbox", code == 200 and processed["processed"] > 0, str(processed))
    check("no failures in dev-console mode", processed["failed"] == 0, str(processed))

    code, rows = req("GET", "/notifications/outbox?status=sent&limit=5")
    sent_row = rows[0] if rows else None
    check("sent rows carry provider ref", sent_row and sent_row["provider_ref"].startswith("dev-"))

    # flip email pref for the caller, then send test -> outbox row queued
    code, _ = req("PUT", "/notifications/preferences", {"category": "system", "email": True})
    check("preference update", code == 200)
    code, _ = req("POST", "/notifications/test")
    check("test notification", code == 201)
    code, rows = req("GET", "/notifications/outbox?channel=email&status=queued&limit=5")
    check("pref toggle enqueues email on test", any(r["subject"] == "Test notification" for r in rows))

    print(f"\n{'='*50}\n{PASSES} passed, {FAILS} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

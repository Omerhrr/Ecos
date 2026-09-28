#!/usr/bin/env python3
"""Task 9 smoke — RMA restock -> warehouse movements + public order tracking.

1. RMA journey: eligible order -> create -> approve -> receive (into WH)
   -> assert return_restock StockMovements reference the RMA, per-warehouse
   StockItem AND network product.stock both rose, notification narrated it.
2. Tracking: shipment-carrying order tracked with the right phone (shipment
   block present), wrong phone -> 403, unknown order -> 404.
3. Fresh public checkout -> immediately tracked (ladder step 0, no shipment).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.parse
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
        with urllib.request.urlopen(req, data=data, timeout=15) as r:
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
    token = (login or {}).get("token", "")
    check("owner login returns token", bool(token))
    H = token

    print("== 1. RMA restock -> warehouse movements ==")
    _, whs = call("GET", "/warehouse", token=H)
    wh = next((w for w in whs if w.get("is_default")), whs[0] if whs else None)
    check("default warehouse exists", wh is not None, wh and f"{wh['code']} {wh['name']}")
    wh_id = wh["id"]

    _, eligible = call("GET", "/returns/eligible-orders", token=H)
    target = next((o for o in eligible if (o.get("total") or 0) > 0), None)
    check("eligible order available", target is not None,
          target and f"order #{target['id']} ({target['status']}) ₦{target['total']}")
    if not target:
        return finish()
    order_id = target["id"]

    lines = sql(
        "SELECT product_id, qty FROM order_items WHERE order_id=?", (order_id,))
    units = sum(q for _, q in lines)
    before_product = dict(sql(
        "SELECT id, stock FROM products WHERE id IN (%s)" % ",".join(str(p) for p, _ in lines)))
    before_wh = dict(sql(
        "SELECT product_id, on_hand FROM stock_items WHERE warehouse_id=? AND product_id IN (%s)"
        % ",".join(str(p) for p, _ in lines), (wh_id,)))

    st, rma = call("POST", "/returns", token=H, body={
        "order_id": order_id, "reason": "changed_mind", "resolution": "refund",
        "restock": True, "notes": "task9 smoke restock",
    })
    check("RMA created (201)", st == 201, rma and rma.get("rma_number"))
    rma_id, rma_number = rma["id"], rma["rma_number"]

    st, rma = call("POST", f"/returns/{rma_id}/approve", token=H)
    check("RMA approved", st == 200 and rma["status"] == "approved")

    st, rma = call("POST", f"/returns/{rma_id}/receive?warehouse_id={wh_id}", token=H)
    check("RMA received into WH (query param)", st == 200 and rma["status"] == "received")
    check("order flipped to returned", rma.get("order_status") == "returned")

    _, mvs = call("GET", f"/warehouse/movements?warehouse_id={wh_id}", token=H)
    restocks = [m for m in mvs
                if m["movement_type"] == "return_restock"
                and m["reference_type"] == "return_order"
                and m["reference_id"] == rma_id]
    check("return_restock movements reference the RMA", len(restocks) == len(lines),
          f"{len(restocks)} movement(s) for {len(lines)} line(s)")
    check("movement qty sums to ordered units", sum(m["qty"] for m in restocks) == units,
          f"units={units}")
    check("movements note the RMA", all(rma_number in (m["note"] or "") for m in restocks))

    after_product = dict(sql(
        "SELECT id, stock FROM products WHERE id IN (%s)" % ",".join(str(p) for p, _ in lines)))
    after_wh = dict(sql(
        "SELECT product_id, on_hand FROM stock_items WHERE warehouse_id=? AND product_id IN (%s)"
        % ",".join(str(p) for p, _ in lines), (wh_id,)))
    ok_p = all(after_product[p] - before_product.get(p, 0) == q for p, q in lines)
    ok_w = all(after_wh.get(p, 0) - before_wh.get(p, 0) == q for p, q in lines)
    check("product.stock rose by line qty (network guard)", ok_p,
          json.dumps({p: [before_product.get(p, 0), after_product[p]] for p, _ in lines}))
    check("StockItem.on_hand rose by line qty at WH", ok_w,
          json.dumps({p: [before_wh.get(p, 0), after_wh.get(p, 0)] for p, _ in lines}))

    _, notifs = call("GET", "/notifications?limit=30", token=H)
    narrated = any(f"restocked from {rma_number}" in (n.get("title") or "") for n in notifs)
    check("notification narrated the restock", narrated)

    print("== 2. public tracking (existing order w/ shipment) ==")
    st_ship, shipments = call("GET", "/shipments", token=H)  # logistics router lives at /api/shipments
    check("shipments list reachable", st_ship == 200 and isinstance(shipments, list))
    ship = shipments[0] if shipments else None
    check("at least one shipment exists", ship is not None,
          ship and f"#{ship['id']} order {ship.get('order_id')}")
    if ship:
        s_order = ship["order_id"]
        phone_row = sql(
            "SELECT c.phone FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?",
            (s_order,))
        phone = phone_row[0][0] if phone_row else ship.get("recipient_phone")
        st, trk = call("GET", f"/public/orders/{s_order}?phone={urllib.parse.quote(phone)}")
        check("phone-matched tracking 200", st == 200 and trk.get("order_id") == s_order)
        check("tracking has order_number", trk.get("order_number") == f"#{s_order}")
        check("shipment block present", bool(trk.get("shipment")),
              trk.get("shipment") and trk["shipment"].get("tracking_code"))
        check("tracking_events key present",
              isinstance((trk.get("shipment") or {}).get("tracking_events"), list))
        st2, _ = call("GET", f"/public/orders/{s_order}?phone=0999-wrong")
        check("wrong phone -> 403", st2 == 403)
    st3, _ = call("GET", "/public/orders/999999?phone=0801")
    check("unknown order -> 404", st3 == 404)

    print("== 3. fresh checkout -> instant tracking ==")
    _, prods = call("GET", "/public/products")
    prod = next((p for p in prods if p.get("in_stock")), None)
    check("in-stock product available", prod is not None, prod and prod["slug"])
    st, placed = call("POST", "/public/checkout", body={
        "items": [{"product_slug": prod["slug"], "qty": 1}],
        "full_name": "Track Tester", "contact_phone": "0809-977-7001",
        "address": "1 Smoke Test Ave", "city": "Lagos", "state": "Lagos",
        "payment_method": "cod", "note": "task9 tracking journey", "utm": {},
    })
    check("checkout placed order (201)", st == 201, placed and f"order #{placed.get('order_id')}")
    new_id = placed["order_id"]
    st, trk = call("GET", f"/public/orders/{new_id}?phone=0809-977-7001")
    check("new order tracked instantly", st == 200 and trk["status"] == "pending_confirmation")
    check("no shipment yet (null)", trk.get("shipment") is None)
    check("items visible to customer", len(trk.get("items", [])) == 1)
    return finish()


def finish() -> int:
    print(f"\nRESULT: {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

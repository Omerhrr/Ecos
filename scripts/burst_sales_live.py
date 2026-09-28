#!/usr/bin/env python3
"""Replay the sales-burst story on the LIVE database (no wipe — real orders).

1. A burst of real orders for the two hot movers (hair brush, neck fan)
   plus texture on lamp/earbuds — through /api/orders like real traffic.
2. Owner cycle-count: correct stock down to shelf reality (PATCH /products).
3. Run the Stock Prophet operator so the new velocity produces real
   reorder suggestions for procurement to action.
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000/api"


def call(method, path, token=None, body=None, expect=200):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            code, payload = r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        code, payload = e.code, json.loads(e.read() or b"{}")
    if code != expect:
        print(f"FAIL {method} {path} -> {code}: {str(payload)[:200]}")
        sys.exit(1)
    return payload


token = call("POST", "/auth/login", body={"email": "owner@kara.example", "password": "demo1234"})["token"]

products = {p["title"]: p for p in call("GET", "/products", token)}
customers = call("GET", "/customers", token)

brush = products["Hair Styling Brush Set"]
fan = products["Portable Neck Fan"]
lamp = products["LED Rechargeable Lamp"]
earbuds = products["Wireless Earbuds X2"]
print(f"before burst: brush stock {brush['stock']}, fan stock {fan['stock']}")

burst_plan = (
    [(brush["id"], 1)] * 9
    + [(fan["id"], 1)] * 8
    + [(lamp["id"], 1)] * 2
    + [(earbuds["id"], 1)] * 2
)
created = skipped = 0
for i, (pid, qty) in enumerate(burst_plan):
    cust = customers[i % len(customers)]
    req_body = {
        "store_id": 1, "customer_id": cust["id"], "product_id": pid,
        "qty": qty, "payment_method": "cod" if i % 2 == 0 else "online_transfer",
    }
    # tolerate a sold-out shelf: the API rightly refuses, so skip that unit
    req = urllib.request.Request(BASE + "/orders", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, json.dumps(req_body).encode()) as r:
            order = json.loads(r.read() or b"{}")
        call("POST", f"/orders/{order['id']}/transition", token, body={"status": "confirmed"})
        created += 1
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("detail", "")
        if "Insufficient stock" in detail:
            skipped += 1
            continue
        raise
print(f"created {created} orders, skipped {skipped} (shelves empty)")

# cycle count: shelf reality for the two movers (absolute set)
call("PATCH", f"/products/{brush['id']}", token, body={"stock": 2})
call("PATCH", f"/products/{fan['id']}", token, body={"stock": 1})
print("cycle count: brush -> 2, fan -> 1")

# run Stock Prophet
ops = call("GET", "/ai/operators", token)
prophet = next(o for o in ops if o["code"] == "demand_forecaster")
run = call("POST", f"/ai/operators/{prophet['id']}/run", token, body={"params": {}})
print(f"Stock Prophet run #{run['id']}: {run['status']} via {run['provider']} ({run['latency_ms']}ms)")
out = run.get("output", {})
print("summary:", out.get("summary"))
for p in (out.get("products") or []):
    if p.get("suggested_reorder_qty"):
        print(f"  -> {p.get('product_title')}: reorder {p['suggested_reorder_qty']} ({p.get('risk')})")

# suggestions should exist right away (subscriber)
sugg = call("GET", "/procurement/reorder-suggestions?status=open", token)
print(f"open suggestions: {len(sugg)}")
for s in sugg:
    print(f"  #{s['id']} {s['product_title']} +{s['suggested_qty']} ({s['risk']}, cover {s['weeks_of_cover']}w)")

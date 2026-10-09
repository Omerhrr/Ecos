#!/usr/bin/env python3
"""Task 16 smoke — DROPSHIP MODE: supplier ships direct to customers, skipping AGM.

Covers:
  A. Fresh supplier product through the Luxeen review gate → published
  B. Marketstore dropship buy (no agent, recipient address) + validations
  C. Prepaid waterfall on a dropship order + §9 isolation both directions
  D. Supplier drives the direct ladder to `delivered` — no putaway, no stock
     growth, no AGM touch; buyer notified
  E. Stock-mode regression (own warehouse receive) feeding a storefront order
  F. Storefront order → relay-supplier → corridor leg → customer order
     auto-advances to delivered; COD stays honestly pending
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000/api"
PASS, FAIL = 0, 0


def _http(method, path, tok=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def GET(path, tok=None):
    return _http("GET", path, tok)


def POST(path, tok=None, body=None):
    return _http("POST", path, tok, body if body is not None else {})


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


def login(email, pw):
    _, data = POST("/auth/login", body={"email": email, "password": pw})
    return data["token"]


print("== setup: logins ==")
owner = login("owner@kara.example", "demo1234")
sup = login("supplier@shenzhen.example", "demo1234")
lux = login("ops@luxeen.example", "demo1234")
check("owner + supplier + luxeen logins", bool(owner) and bool(sup) and bool(lux))

# ---------------------------------------------------------------- A. gate
print("== A. supplier upload → review gate → publish ==")
_, j = POST("/market/portal/products", sup, {
    "title": "Dropship Drone Cam X1", "description": "4K foldable drone camera",
    "category": "electronics", "industry": "consumer-electronics",
    "cost_price": 180, "currency": "CNY", "weight_kg": 0.8, "moq": 1,
})
check("supplier uploads product", j.get("id"), str(j)[:200])
sp_id = j["id"]
POST(f"/market/portal/products/{sp_id}/submit", sup)
_, j = POST(f"/market/admin/products/{sp_id}/review", lux,
            {"decision": "approve", "notes": "dropship smoke"})
check("Luxeen approves", j.get("status") == "approved", str(j)[:200])
_, j = POST(f"/market/admin/products/{sp_id}/publish", lux)
catalog_pid = j.get("catalog_product_id")
check("published → catalog product", bool(catalog_pid), str(j)[:200])

_, j = GET(f"/products/{catalog_pid}", owner)
stock_before = j.get("stock", 0)

# ------------------------------------------- B. dropship buy + validations
print("== B. Marketstore dropship buy (no agent) ==")
_, so_a = POST("/market/sourcing-orders", owner, {
    "supplier_product_id": sp_id, "qty": 2, "fulfillment_mode": "dropship",
    "dest_name": "Adaeze Okafor", "dest_phone": "+234 802 555 0117",
    "dest_address": "12 Adeola Odeku Street, Victoria Island",
    "dest_city": "Lagos", "dest_country": "NG",
    "note": "Birthday gift — fragile",
})
check("dropship sourcing order created", so_a.get("id"), str(so_a)[:300])
check("mode is dropship", so_a.get("fulfillment_mode") == "dropship")
check("no agent destination", so_a.get("destination", {}).get("via_agent") is False)
check("recipient on the parcel", so_a.get("destination", {}).get("name") == "Adaeze Okafor")

status, _ = POST("/market/sourcing-orders", owner, {
    "supplier_product_id": sp_id, "qty": 1, "fulfillment_mode": "dropship",
    "dest_name": "X", "dest_phone": "y", "dest_address": "",
})
check("dropship without address → 400", status == 400, f"got {status}")

_, links = GET("/agents/links", owner)
links = links if isinstance(links, list) else []
agent_org = links[0]["agent_org_id"] if links else None
if agent_org:
    status, _ = POST("/market/sourcing-orders", owner, {
        "supplier_product_id": sp_id, "qty": 1, "fulfillment_mode": "dropship",
        "agent_org_id": agent_org,
        "dest_name": "X", "dest_phone": "y", "dest_address": "z",
    })
    check("dropship + agent → 400", status == 400, f"got {status}")
else:
    check("dropship + agent → 400 (skipped: no agent link)", True)

# --------------------------------------------- C. pay + waterfall + §9
print("== C. prepaid waterfall + isolation ==")
status, j = POST(f"/market/sourcing-orders/{so_a['id']}/pay", owner, {"method": "online_transfer"})
check("operator pays the corridor leg", status == 200 and j.get("status") == "paid", str(j)[:200])

_, rows = GET("/finance/ledger", owner)
rows = rows if isinstance(rows, list) else rows.get("entries", [])
sp_row = next((e for e in rows if e.get("entry_type") == "supplier_payable"
               and so_a["order_number"] in (e.get("memo") or "")), None)
check("supplier payable with CNY memo (§46)",
      sp_row is not None and "¥" in (sp_row.get("memo") or ""), str(sp_row)[:200])

_, sup_orders = GET("/market/portal/orders", sup)
sup_a = next(o for o in sup_orders if o["order_number"] == so_a["order_number"])
check("supplier sees the dropship order", sup_a.get("fulfillment_mode") == "dropship")
check("supplier sees recipient to ship to", sup_a["destination"]["name"] == "Adaeze Okafor")
check("supplier payload hides buyer org (§9)",
      "org_id" not in sup_a and "customer_order_id" not in sup_a, str(list(sup_a.keys())))
_, op_rows = GET("/market/sourcing-orders", owner)
op_a = next(o for o in op_rows if o["order_number"] == so_a["order_number"])
check("operator payload hides supplier identity (§9)",
      "supplier_id" not in op_a and "unit_cost_cny" not in op_a, str(list(op_a.keys())))

# --------------------------------------------- D. ladder → delivered
print("== D. supplier drives the direct ladder ==")
def sup_track(so_id, code, desc, loc):
    return POST(f"/market/portal/orders/{so_id}/tracking", sup,
                {"code": code, "description": desc, "location": loc})[0]

status, j = POST(f"/market/portal/orders/{sup_a['id']}/accept", sup)
check("supplier accepts", status == 200 and j.get("status") == "processing", str(j)[:150])
status, _ = POST(f"/market/portal/orders/{sup_a['id']}/receive", sup)
check("receive on dropship → 4xx", status in (400, 404), f"got {status}")

ladder = [
    ("picked_up", "Picked up by line-haul", "Shenzhen, CN"),
    ("origin_warehouse", "Consolidated at origin warehouse", "Shenzhen, CN"),
    ("exported", "Export customs cleared", "Shenzhen, CN"),
    ("in_transit", "International air freight", "CN→NG"),
    ("customs", "Import customs in progress", "Lagos, NG"),
    ("destination_hub", "Arrived at Lagos hub", "Lagos, NG"),
    ("out_for_delivery", "Courier out for final delivery", "Lagos, NG"),
    ("delivered", "Handed to the recipient", "Lagos, NG"),
]
ok_steps = sum(1 for code, desc, loc in ladder if sup_track(sup_a["id"], code, desc, loc) == 200)
check("full dropship ladder posted", ok_steps == len(ladder), f"{ok_steps}/{len(ladder)}")
_, op_rows = GET("/market/sourcing-orders", owner)
op_a = next(o for o in op_rows if o["order_number"] == so_a["order_number"])
check("sourcing order ends DELIVERED", op_a["status"] == "delivered", op_a["status"])
check("timeline has out_for_delivery",
      any(e["code"] == "out_for_delivery" for e in op_a.get("events", [])))
check("no receive state on dropship", op_a.get("received_at") is None)

_, j = GET(f"/products/{catalog_pid}", owner)
check("zero stock growth — nothing landed", j.get("stock") == stock_before,
      f"{stock_before} → {j.get('stock')}")

_, notes = GET("/notifications", owner)
notes = notes if isinstance(notes, list) else notes.get("items", [])
check("buyer notified of door delivery",
      any("delivered to the recipient" in (n.get("title") or "")
          and so_a["order_number"] in n.get("title", "") for n in notes),
      f"{len(notes)} notifications")

# --------------------------------------------- E. stock regression + relay
print("== E. stock buy → own warehouse → storefront order ==")
_, so_b = POST("/market/sourcing-orders", owner, {
    "supplier_product_id": sp_id, "qty": 3, "fulfillment_mode": "stock",
})
check("stock sourcing order created", so_b.get("id") and so_b["fulfillment_mode"] == "stock")
POST(f"/market/sourcing-orders/{so_b['id']}/pay", owner, {})
_, sup_rows = GET("/market/portal/orders", sup)
sup_b = next(o for o in sup_rows if o["order_number"] == so_b["order_number"])
POST(f"/market/portal/orders/{sup_b['id']}/accept", sup)
for code, desc, loc in ladder[:6]:  # through destination_hub
    sup_track(sup_b["id"], code, desc, loc)
sup_track(sup_b["id"], "delivered", "Arrived in Nigeria", "Lagos, NG")  # → arrived (stock map)
_, rows = GET("/market/sourcing-orders", owner)
so_b_now = next(o for o in rows if o["order_number"] == so_b["order_number"])
check("stock ladder ends ARRIVED", so_b_now["status"] == "arrived", so_b_now["status"])
status, j = POST(f"/market/sourcing-orders/{so_b['id']}/receive", owner, {})
check("own-warehouse receive works", status == 200, str(j)[:200])
_, j = GET(f"/products/{catalog_pid}", owner)
stock_after_stock = j["stock"]
check("stock buy grew the pool by 3", stock_after_stock == stock_before + 3,
      f"{stock_before} → {stock_after_stock}")

_, stores = GET("/stores", owner)
store_id = stores[0]["id"]
_, custs = GET("/customers", owner)
cust = next((c for c in custs if c.get("store_id") == store_id), custs[0])
check("store + customer available", bool(store_id) and bool(cust.get("id")))

status, j = POST("/orders", owner, {
    "store_id": store_id, "customer_id": cust["id"],
    "product_id": catalog_pid, "qty": 2, "payment_method": "cod",
})
check("storefront COD order created", status == 201, str(j)[:250])
order_id = j["id"]
POST(f"/orders/{order_id}/transition", owner, {"status": "confirmed", "actor": "smoke"})
_, j = GET(f"/orders/{order_id}", owner)
check("order confirmed", j.get("status") == "confirmed", str(j)[:150])

print("== F. relay to supplier → direct delivery → order advances ==")
# a still-unconfirmed order must not relay
status, j = POST("/orders", owner, {
    "store_id": store_id, "customer_id": cust["id"],
    "product_id": catalog_pid, "qty": 1, "payment_method": "cod",
})
order2_id = j["id"] if status == 201 else None
status, _ = POST(f"/market/orders/{order2_id}/relay-supplier", owner)
check("relay unconfirmed order → 400", status == 400, f"got {status}")

status, j = POST(f"/market/orders/{order_id}/relay-supplier", owner)
check("relay → 201", status == 201, str(j)[:300])
relayed = j["relayed"][0]
so_c = relayed
check("relay is a dropship sourcing order", so_c["fulfillment_mode"] == "dropship")
check("relay linked to the customer order (§51)", so_c["customer_order_id"] == order_id)
check("relay qty follows the order line", so_c["qty"] == 2)
check("recipient = storefront customer", bool(so_c["destination"]["name"]))

status, j = POST(f"/market/orders/{order_id}/relay-supplier", owner)
check("double relay → 400", status == 400, f"got {status}")

status, j = POST(f"/market/sourcing-orders/{so_c['id']}/pay", owner, {})
check("corridor leg paid", status == 200 and j.get("status") == "paid", str(j)[:150])
_, sup_rows = GET("/market/portal/orders", sup)
sup_c = next(o for o in sup_rows if o["order_number"] == so_c["order_number"])
check("supplier sees relay with mode but NOT the storefront order",
      sup_c["fulfillment_mode"] == "dropship" and "customer_order_id" not in sup_c)
POST(f"/market/portal/orders/{sup_c['id']}/accept", sup)
for code, desc, loc in ladder:
    sup_track(sup_c["id"], code, desc, loc)

_, j = GET(f"/orders/{order_id}", owner)
check("customer order auto-advanced to DELIVERED", j.get("status") == "delivered", str(j)[:150])
check("COD stays honestly pending (no fake capture)", j.get("payment_status") == "pending", str(j.get("payment_status")))
_, j = GET(f"/products/{catalog_pid}", owner)
check("dropship leg never touched stock", j["stock"] == stock_after_stock - 3,
      f"{stock_after_stock} → {j['stock']} (expected order1 -2 + order2 -1 at creation)")

_, notes = GET("/notifications", owner)
notes = notes if isinstance(notes, list) else notes.get("items", [])
check("operator told to collect COD themselves",
      any("fulfilled by supplier dropship" in (n.get("title") or "") for n in notes))

print(f"\n=== SMOKE TASK 16: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)

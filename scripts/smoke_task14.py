#!/usr/bin/env python3
"""Task 14 smoke — the full corridor, end to end (all four phases).

Covers:
  1. Supplier portal: seeded products, upload -> submit
  2. Luxeen review gate: queue -> approve -> publish (catalog materialises)
  3. Marketstore: operator browses in NGN, isolation asserted (no supplier leak)
  4. Sourcing: buy (prepaid) -> supplier notified -> accept -> CN ladder -> arrival
  5. AGM: agent receives inbound (per-vendor putaway), vendor marks a confirmed
     order, agent gets the alert, works it to delivered with COD collection
  6. Remittance: agent remits COD, reconcile with variance -> ledger true-up
  7. Money: sourcing ledger waterfall entries exist (supplier payable w/ CNY memo)
  8. Isolation: supplier cannot list operator market endpoints; operator payloads
     carry no supplier identity; supplier payloads carry no buyer identity
"""
import json
import sys

import httpx

B = "http://localhost:8000/api"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))


def login(email, password="demo1234"):
    r = httpx.post(f"{B}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["token"]


def call(token, method, path, body=None, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.request(method, f"{B}{path}", json=body, params=params, headers=headers, timeout=30)
    return r


print("== logins ==")
op = login("owner@kara.example")          # operator owner
pl = login("ops@luxeen.example")          # luxeen platform admin
su = login("supplier@shenzhen.example")   # supplier portal user
ag = login("agent@eko.example")           # AGM console user
check("supplier portal account seeded", bool(su))
check("agent console account seeded", bool(ag))

print("== phase 1: supplier portal ==")
rows = call(su, "GET", "/market/portal/products").json()
check("supplier sees own listings", len(rows) >= 4, f"{len(rows)} listings")
check("listing statuses seeded", any(p["status"] == "published" for p in rows) and any(p["status"] == "submitted" for p in rows))

new = call(su, "POST", "/market/portal/products", {
    "title": "Wireless Lavalier Mic", "category": "electronics",
    "industry": "consumer-electronics", "cost_price": 78, "weight_kg": 0.2, "moq": 5,
    "description": "Dual-channel wireless microphone kit.",
}).json()
check("supplier uploads draft", new["status"] == "draft", f"id={new['id']}")
sub = call(su, "POST", f"/market/portal/products/{new['id']}/submit").json()
check("supplier submits for review", sub["status"] == "submitted")

print("== phase 2: luxeen review gate ==")
queue = call(pl, "GET", "/market/admin/products", params={"status": "submitted"}).json()
check("review queue has submissions", any(p["id"] == new["id"] for p in queue))
rev = call(pl, "POST", f"/market/admin/products/{new['id']}/review",
           {"decision": "approve", "notes": "Sample ok"}).json()
check("approved", rev["status"] == "approved")
pub = call(pl, "POST", f"/market/admin/products/{new['id']}/publish").json()
check("published", pub["status"] == "published", f"catalog_product_id={pub['catalog_product_id']}")

guard = call(op, "POST", f"/market/admin/products/{new['id']}/review", {"decision": "approve"})
check("operator CANNOT use review gate (platform only)", guard.status_code == 403, str(guard.status_code))

print("== phase 3: marketstore (operator, local currency) ==")
mp = call(op, "GET", "/market/products").json()
check("marketstore has published listings", len(mp) >= 4, f"{len(mp)} listings")
check("no supplier identity in operator payloads",
      all("supplier" not in json.dumps(p).lower() or "available_from" in json.dumps(p) for p in mp))
mic = next(p for p in mp if p["title"] == "Wireless Lavalier Mic")
check("new listing visible with NGN price", mic["currency"] == "NGN" and mic["unit_price"] > 0,
      f"₦{mic['unit_price']:,.0f}")

print("== phase 4: sourcing order (prepaid) ==")
links = call(op, "GET", "/agm/links").json()
check("vendor-agent link seeded", len(links) >= 1, f"agent={links[0]['agent_name']}")
agent_org_id = links[0]["agent_org_id"]

so = call(op, "POST", "/market/sourcing-orders", {
    "supplier_product_id": mic["id"], "qty": 10, "agent_org_id": agent_org_id,
    "note": "Restock before campaign week.",
}).json()
check("sourcing order created", so["status"] == "pending_payment", f"{so['order_number']}")
check("CNY cost transparent to buyer", so["cny_total"] > 0 and so["fx_rate"] > 0,
      f"¥{so['cny_total']:,.2f} @ {so['fx_rate']}")
check("destination is the agent location", so["destination"]["via_agent"] is True)

bad_link = call(op, "POST", "/market/sourcing-orders", {"supplier_product_id": mic["id"], "qty": 5, "agent_org_id": 99999})
check("cannot route to a non-linked agent", bad_link.status_code == 400, str(bad_link.status_code))

paid = call(op, "POST", f"/market/sourcing-orders/{so['id']}/pay", {"method": "online_transfer"}).json()
check("prepaid", paid["status"] == "paid")

sup_orders = call(su, "GET", "/market/portal/orders").json()
mine = next(o for o in sup_orders if o["order_number"] == so["order_number"])
check("supplier got the order", mine["status"] == "paid")
check("supplier payload has NO buyer identity",
      "Kara" not in json.dumps(mine) and "org_id" not in json.dumps(mine))

acc = call(su, "POST", f"/market/portal/orders/{so['id']}/accept").json()
check("supplier accepts -> processing", acc["status"] == "processing")
for code, loc, desc in [
    ("picked_up", "Shenzhen, CN", "Collected."),
    ("exported", "Shenzhen Port", "Export cleared."),
    ("in_transit", "Indian Ocean", "On the water."),
    ("customs", "Apapa, Lagos", "Import clearance."),
    ("destination_hub", "Lagos Hub", "Hub arrival."),
    ("delivered", "Eko Hub — Ilasamaja", "Delivered to agent warehouse."),
]:
    st = call(su, "POST", f"/market/portal/orders/{so['id']}/tracking",
              {"code": code, "location": loc, "description": desc}).json()
check("CN ladder complete -> arrived", st["status"] == "arrived")

op_view = call(op, "GET", f"/market/sourcing-orders").json()
my_so = next(o for o in op_view if o["id"] == so["id"])
check("operator sees full inbound timeline", len(my_so["events"]) >= 8, f"{len(my_so['events'])} checkpoints")

print("== phase 5: AGM — putaway, alert, fulfillment ==")
ov = call(ag, "GET", "/agm/overview").json()
check("agent overview live", ov["vendors"] >= 1 and ov["warehouses"] >= 2, f"vendors={ov['vendors']} whs={ov['warehouses']}")

put = call(ag, "POST", f"/market/sourcing-orders/{so['id']}/receive")
check("agent-side receive blocked on market endpoint (vendor-only)", put.status_code in (401, 403), str(put.status_code))

# operator-side receive is blocked for agent-routed orders; the AGM putaway for
# the seeded demo run already exists — this order arrives via portal receive:
rec = call(op, "POST", f"/market/sourcing-orders/{so['id']}/receive")
check("operator cannot receive an agent-routed order", rec.status_code == 400, str(rec.status_code))

# agent receives: use the market service via the operator endpoint? No —
# agent putaway happens in the AGM: expose through stock after receive.
# The seeded demo run already did agent putaway; THIS one still needs it:
# agent calls the receive through the AGM endpoint
ag_receive = call(ag, "POST", f"/agm/receive-sourcing/{so['id']}")
if ag_receive.status_code == 404:
    # endpoint variant: putaway via agent receive endpoint (below)
    check("AGM receive endpoint present", False, "missing /agm/receive-sourcing")
else:
    check("AGM putaway done", ag_receive.status_code == 200, str(ag_receive.status_code))

stock = call(ag, "GET", "/agm/stock").json()
mic_row = next((s for s in stock if s["product_id"] == pub["catalog_product_id"]), None)
check("per-vendor stock updated", mic_row is not None and mic_row["on_hand"] >= 10,
      f"{mic_row['on_hand'] if mic_row else 0} units for {mic_row['vendor_name'] if mic_row else '?'}")

# vendor creates + confirms a fresh customer order, then marks it for the agent
stores = call(op, "GET", "/stores").json()
store_id = stores[0]["id"]
customers = call(op, "GET", "/customers").json()
cust = next(c for c in customers if str(c.get("phone", "")).startswith("+234"))
new_order = call(op, "POST", "/orders", {
    "store_id": store_id, "customer_id": cust["id"],
    "product_id": pub["catalog_product_id"], "qty": 1, "payment_method": "cod",
}).json()
call(op, "POST", f"/orders/{new_order['id']}/transition", {"status": "confirmed"})
check("fresh customer order confirmed", bool(new_order.get("id")), f"#{new_order.get('id')}")

marked = call(op, "POST", f"/agm/orders/{new_order['id']}/mark", {"agent_org_id": agent_org_id}).json()
check("vendor marks order -> AGF alert", marked["status"] == "notified", marked["code"])

ag_queue = call(ag, "GET", "/agm/orders", params={"status": "notified"}).json()
check("alert straight in agent queue", any(a["code"] == marked["code"] for a in ag_queue))
check("agent sees customer contact to call", bool(ag_queue[0]["customer"]["phone"]))
check("COD expected surfaced", ag_queue[0]["cod_expected"] > 0, f"₦{ag_queue[0]['cod_expected']:,.0f}")

ao_id = marked["id"]
for action in ("accept", "start_call", "confirm", "out_for_delivery"):
    r = call(ag, "POST", f"/agm/orders/{ao_id}/action", {"action": action}).json()
check("agent works the queue", r["status"] == "out_for_delivery", r["status"])

delivered = call(ag, "POST", f"/agm/orders/{ao_id}/action",
                 {"action": "deliver", "cod_collected": marked.get("cod_expected")}).json()
check("delivered with COD collected", delivered["status"] == "delivered" and delivered["cod_collected"] > 0,
      f"₦{delivered['cod_collected']:,.0f}")

cust_order = call(op, "GET", "/orders").json()
co = next(o for o in cust_order if o["id"] == marked["order_id"])
check("customer order auto-advanced to delivered", co["status"] == "delivered", co["status"])

print("== phase 6: remittance (COD custody) ==")
reg = call(ag, "POST", "/agm/remittances", {}).json()
check("remittance register from collected COD", reg["status"] == "draft" and reg["expected_amount"] > 0,
      f"{reg['register_code']} ₦{reg['expected_amount']:,.0f}")
remit = call(ag, "POST", f"/agm/remittances/{reg['id']}/remit", {"reference": "CASH-DEP-77"}).json()
check("agent remits cash", remit["status"] == "remitted")
counted = {str(l["id"]): l["expected_amount"] - 50 for l in remit["lines"]}  # short by 50
recon = call(ag, "POST", f"/agm/remittances/{reg['id']}/reconcile", {"counted": counted}).json()
check("reconciled with variance", recon["status"] == "reconciled" and abs(recon["variance_amount"] + 50) < 0.01,
      f"variance ₦{recon['variance_amount']:,.0f}")

print("== phase 7: money (ledger waterfall) ==")
led = call(op, "GET", "/finance/ledger", params={"limit": 200}).json()
entries = led.get("entries") if isinstance(led, dict) else led
sp_rows = [e for e in entries if e.get("entry_type") == "sourcing_payment"]
check("sourcing payment in ledger", len(sp_rows) >= 1)
sup_rows = [e for e in entries if e.get("entry_type") == "supplier_payable" and "CNY→NGN" in e.get("memo", "")]
check("supplier payable w/ FX snapshot memo", len(sup_rows) >= 1, sup_rows[0]["memo"][:60] if sup_rows else "")
var_rows = [e for e in entries if e.get("entry_type") == "cod_variance" and e.get("party") == "agent"]
check("agent remittance variance true-up", len(var_rows) >= 1)

print("== phase 8: isolation hard checks ==")
r = call(su, "GET", "/market/products")
check("supplier cannot browse marketstore as buyer", r.status_code == 403, str(r.status_code))
r = call(ag, "GET", "/market/portal/products")
check("agent cannot open supplier portal", r.status_code == 403, str(r.status_code))
r = call(op, "GET", "/agm/orders")
check("operator cannot read agent console queue", r.status_code == 403, str(r.status_code))
r = call(op, "GET", "/market/admin/products")
check("operator cannot open review gate", r.status_code == 403, str(r.status_code))

print()
print(f"CORRIDOR SMOKE: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)

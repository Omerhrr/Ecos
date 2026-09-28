#!/usr/bin/env python3
"""Smoke test: §39 notifications + procurement/POs actioning Stock Prophet reorders.

Run: python3 scripts/smoke_notifications_procurement.py
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000/api"
PASSED = []
FAILED = []


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
    ok = code == expect
    (PASSED if ok else FAILED).append(f"{method} {path} -> {code} (expect {expect})")
    return payload


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(f"{name} {(': ' + detail) if detail and not cond else ''}")


def login(email, password="demo1234"):
    return call("POST", "/auth/login", body={"email": email, "password": password})


print("== auth ==")
owner = login("owner@kara.example")
token = owner.get("token")
check("owner login returns token", bool(token))

print("== §39 notifications basics ==")
test_note = call("POST", "/notifications/test", token, body={}, expect=201)
check("test notification created", test_note.get("category") == "system", str(test_note)[:120])

feed = call("GET", "/notifications", token)
check("feed non-empty", len(feed) > 0, f"{len(feed)} rows")
check("feed scoped to owner", all(n["recipient_user_id"] == owner["user"]["id"] for n in feed))

unread0 = call("GET", "/notifications/unread-count", token)["unread"]
check("unread counts test notification", unread0 >= 1, f"unread={unread0}")

first_unread = next((n for n in feed if not n["read"]), None)
if first_unread:
    marked = call("POST", f"/notifications/{first_unread['id']}/read", token)
    check("mark one read", marked.get("read") is True)
unread1 = call("GET", "/notifications/unread-count", token)["unread"]
check("unread decremented", unread1 == unread0 - 1, f"{unread0} -> {unread1}")

prefs = call("GET", "/notifications/preferences", token)
check("preferences default set (9 categories)", len(prefs) == 9, f"{len(prefs)} prefs")

mut = call("PUT", "/notifications/preferences", token,
           body={"category": "payments", "in_app": False, "email": True})
check("mute payments in_app + email on", mut["in_app"] is False and mut["email"] is True)
call("PUT", "/notifications/preferences", token, body={"category": "payments", "in_app": True, "email": False})

print("== procurement: Stock Prophet suggestions ==")
summary = call("POST", "/procurement/reorder-suggestions/refresh", token, body={})
check("refresh backfills from latest run", summary.get("open_suggestions", 0) >= 0, str(summary))

sugg = call("GET", "/procurement/reorder-suggestions?status=open", token)
check("open suggestions exist", len(sugg) > 0, f"{len(sugg)} open")
if sugg:
    print(f"   {len(sugg)} open suggestions, e.g.: "
          + ", ".join(f"{s['product_title']} (+{s['suggested_qty']}, {s['risk']})" for s in sugg[:3]))

print("== procurement: RBAC ==")
agent = login("bisi@kara.example")
check("agent login", bool(agent.get("token")))
call("GET", "/procurement", agent.get("token"), expect=403)  # agent lacks procurement:read
call("GET", "/notifications", agent.get("token"))            # notifications need no perm
call("POST", "/procurement/reorder-suggestions/create-po", agent.get("token"),
     body={"suggestion_ids": []}, expect=403)                # and lacks procurement:write

print("== procurement: suggestions -> POs -> receive ==")
if sugg:
    stock_before = {s["product_id"]: s["product_stock"] for s in sugg}
    picked = [s["id"] for s in sugg[:2]]
    pos = call("POST", "/procurement/reorder-suggestions/create-po", token,
               body={"suggestion_ids": picked}, expect=201)
    check("POs created from suggestions", len(pos) >= 1, f"{len(pos)} PO(s)")
    check("POs tagged stock_prophet", all(p["source"] == "stock_prophet" for p in pos))

    conv = call("GET", "/procurement/reorder-suggestions?status=converted", token)
    conv_ids = {s["id"] for s in conv}
    check("picked suggestions now converted", set(picked) <= conv_ids, str(picked))

    for po in pos:
        po_id = po["id"]
        call("POST", f"/procurement/{po_id}/submit", token, body={})
        call("POST", f"/procurement/{po_id}/confirm", token, body={})
        lines = call("GET", f"/procurement/{po_id}", token)["lines"]
        # partial receive on the first line, then the rest
        l0 = lines[0]
        half = max(1, l0["qty_ordered"] // 2)
        r1 = call("POST", f"/procurement/{po_id}/receive", token,
                  body={"receipts": {str(l0["id"]): half}})
        check(f"PO {po['po_number']} partial receive ok", r1["status"] == "confirmed", r1["status"])
        remaining = {str(l["id"]): l["qty_outstanding"] for l in r1["lines"] if l["qty_outstanding"] > 0}
        if remaining:
            r2 = call("POST", f"/procurement/{po_id}/receive", token, body={"receipts": remaining})
            check(f"PO {po['po_number']} fully received", r2["status"] == "received", r2["status"])

    # stock actually went up
    from_product = call("GET", "/products", token)
    stock_after = {p["id"]: p["stock"] for p in from_product}
    gained = {pid: stock_after[pid] - stock_before[pid] for pid in stock_before
              if stock_after.get(pid, 0) - stock_before[pid] != 0}
    check("product stock increased by received units", len(gained) > 0, str(gained))
    print(f"   stock deltas: {gained}")

    # cancel path reopens suggestions
    fresh = call("GET", "/procurement/reorder-suggestions?status=open", token)
    if fresh:
        one = fresh[0]["id"]
        po2 = call("POST", "/procurement/reorder-suggestions/create-po", token,
                   body={"suggestion_ids": [one]}, expect=201)
        pid = po2[0]["id"]
        call("POST", f"/procurement/{pid}/cancel", token, body={})
        reopened = call("GET", "/procurement/reorder-suggestions?status=open", token)
        check("cancel PO reopens its suggestion", any(s["id"] == one for s in reopened))
        # leave it dismissed so the demo board isn't noisy
        call("POST", f"/procurement/reorder-suggestions/{one}/dismiss", token, body={})

    bad = call("POST", "/procurement/reorder-suggestions/create-po", token,
               body={"suggestion_ids": []}, expect=400)
    check("no open suggestions left -> 400", "No open" in bad.get("detail", ""))

print("== §39: events fanned out to notifications ==")
proc_notes = call("GET", "/notifications?category=procurement", token)
titles = [n["title"] for n in proc_notes]
check("reorder.suggested notification present",
      any("Stock Prophet" in t for t in titles), str(titles[:4]))
check("po_created notification present", any("raised to" in t for t in titles))
check("po_received notification present", any("fully received" in t for t in titles))

# cross-domain: transition an order -> order notification
orders = call("GET", "/orders?status=pending_confirmation", token)
if orders:
    oid = orders[0]["id"]
    call("POST", f"/orders/{oid}/transition", token, body={"status": "confirmed"})
    order_notes = call("GET", "/notifications?category=orders", token)
    check("order.status_changed notification",
          any(f"Order #{oid}" in n["title"] for n in order_notes),
          str([n["title"] for n in order_notes[:4]]))

call("POST", "/notifications/read-all", token)
final_unread = call("GET", "/notifications/unread-count", token)["unread"]
check("read-all zeroes unread", final_unread == 0, f"unread={final_unread}")

print("\n========================")
print(f"PASS: {len(PASSED)}  FAIL: {len(FAILED)}")
for f in FAILED:
    print("  FAIL:", f)
sys.exit(1 if FAILED else 0)

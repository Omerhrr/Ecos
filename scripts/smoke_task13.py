#!/usr/bin/env python3
"""Task 13 smoke — §34/§35 operator depth + §31 DeepSeek key flow.

1. Key flow: DB-stored key -> instant live flip (mock DeepSeek server),
   masked hints, recorded test result, clear -> fallback, agent RBAC.
2. §34 Page Architect: full landing page proposal -> approval files a real
   draft page in the LP engine (blocks survive sanitization, unique slugs).
3. §35 Customer Sentinel: 7-bucket watchlist -> approval runs the safe ops
   playbook (real notifications).
"""
import json
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = "http://localhost:8000/api"
PASSED = 0
FAILED = 0
MOCK_KEY = "sk-mock-live-key-0001"


def call(method, path, token=None, body=None, expect=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            status, payload = r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
    if expect and status != expect:
        raise AssertionError(f"{method} {path} -> {status} (expected {expect}): {str(payload)[:300]}")
    return status, payload


def check(name, cond, extra=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}  {extra}")


# --------------------------------------------------------------------------
# Mock DeepSeek server: echoes the operator's [[HEURISTIC]] payload back as
# the completion — exercises the FULL live path (DB key -> base_url override
# -> chat -> JSON parse) deterministically, no external network needed.
# --------------------------------------------------------------------------

class MockDeepSeek(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        auth = self.headers.get("Authorization", "")
        if not auth.endswith(MOCK_KEY):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "auth fails"}}')
            return
        system = next((m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
        idx = system.find("[[HEURISTIC]]")
        payload = system[idx + len("[[HEURISTIC]]"):].strip() if idx >= 0 else "{}"
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            payload = "{}"
        resp = {
            "choices": [{"message": {"content": payload}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 24},
            "model": body.get("model", "deepseek-chat"),
        }
        raw = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start_mock():
    server = HTTPServer(("127.0.0.1", 8901), MockDeepSeek)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


print("== login ==")
_, login = call("POST", "/auth/login", body={"email": "owner@kara.example", "password": "demo1234"}, expect=200)
TOKEN = login["token"]
check("owner login", bool(TOKEN))
_, agent_login = call("POST", "/auth/login", body={"email": "bisi@kara.example", "password": "demo1234"}, expect=200)
AGENT = agent_login["token"]

print("== §31 key flow ==")
start_mock()
call("PUT", "/ai/provider/settings", token=TOKEN, body={"api_key": ""})  # clean slate
_, p0 = call("GET", "/ai/provider", token=TOKEN, expect=200)
check("no key -> heuristic fallback", p0["provider"] == "heuristic-fallback" and p0["key_source"] is None)
_, _, = call("POST", "/ai/provider/test", token=TOKEN, expect=400)  # no key -> setup instructions

_, p1 = call("PUT", "/ai/provider/settings", token=TOKEN,
             body={"api_key": MOCK_KEY, "model": "deepseek-chat", "base_url": "http://127.0.0.1:8901"}, expect=200)
check("storing key flips provider live instantly", p1["provider"] == "deepseek", p1)
check("key source is database", p1["key_source"] == "database")
check("key hint masked (no full key)", p1["key_hint"] and MOCK_KEY not in json.dumps(p1), p1.get("key_hint"))

_, pt = call("POST", "/ai/provider/test", token=TOKEN, expect=200)
check("provider test pings live model", pt.get("ok") is True and pt.get("model") == "deepseek-chat", pt)
_, p2 = call("GET", "/ai/provider", token=TOKEN, expect=200)
check("test outcome recorded on settings", p2["last_test_ok"] is True and p2["last_test_at"], p2)

_, run = call("POST", "/ai/operators/2/run", token=TOKEN, body={"params": {}}, expect=200)  # Stock Prophet
check("operator run goes through live mock DeepSeek", run["provider"] == "deepseek" and run["status"] == "succeeded",
      {"provider": run["provider"], "status": run["status"], "error": run["error"][:120]})
check("live run parses real JSON output", isinstance(run["output"].get("products"), list), list(run["output"].keys())[:6])
check("live run tokens recorded", run["prompt_tokens"] == 42 and run["completion_tokens"] == 24)

sa, _pa = call("PUT", "/ai/provider/settings", token=AGENT, body={"api_key": "x"})
check("agent blocked from provider settings (403)", sa == 403, sa)

call("PUT", "/ai/provider/settings", token=TOKEN, body={"api_key": ""}, expect=200)
_, p3 = call("GET", "/ai/provider", token=TOKEN, expect=200)
check("clearing key returns to heuristic fallback", p3["provider"] == "heuristic-fallback" and p3["key_source"] is None)

print("== §34 Page Architect ==")
_, reg = call("GET", "/ai/registry", token=TOKEN, expect=200)
lp_blueprint = next((b for b in reg if b["code"] == "landing_page_architect"), None)
check("registry exposes landing_page_architect (§34)", lp_blueprint is not None)
check("§34 input asks for product + optional angle",
      any(f["key"] == "product_id" for f in lp_blueprint["input_fields"])
      and any(f["key"] == "angle" for f in lp_blueprint["input_fields"]))

_, prods = call("GET", "/products", token=TOKEN, expect=200)
pid = prods[0]["id"]
_, r34 = call("POST", "/ai/operators", token=TOKEN, body={"code": "landing_page_architect"}, expect=201)
_, run34 = call("POST", f"/ai/operators/{r34['id']}/run", token=TOKEN, body={"params": {"product_id": pid}}, expect=200)
out34 = run34["output"]
check("§34 run succeeded + pending approval", run34["status"] == "succeeded" and run34["proposal_status"] == "pending")
page = out34.get("page", {})
block_types = [b.get("type") for b in page.get("blocks", [])]
check("§34 composes a full page (hero+story+features+social+faq+cta)",
      {"hero", "image_text", "feature_grid", "testimonials", "faq", "cta"}.issubset(set(block_types)), block_types)
tracking = out34.get("tracking", {})
check("§34 CTAs carry UTM attribution (§16 handshake)",
      tracking.get("utm_source") == "lp" and tracking.get("utm_campaign", "").endswith("-launch")
      and "utm_campaign" in tracking.get("cta_href", ""), tracking)
check("§34 proposes selling angle with rationale",
      bool(out34.get("selling_angle", {}).get("angle")) and bool(out34.get("selling_angle", {}).get("rationale")))

_, ap34 = call("POST", f"/ai/runs/{run34['id']}/approve", token=TOKEN, expect=200)
applied = ap34["output"].get("applied", {})
check("§34 approval files a draft landing page", applied.get("status") == "draft" and applied.get("landing_page_id"))
lp_id, lp_slug = applied["landing_page_id"], applied["slug"]
_, page_saved = call("GET", f"/landing-pages/{lp_id}", token=TOKEN, expect=200)
check("§34 draft survives block sanitization (editable in LP engine)",
      page_saved.get("status") == "draft" and len(page_saved.get("blocks", [])) == applied.get("block_count"),
      {"saved": len(page_saved.get("blocks", [])), "claimed": applied.get("block_count")})

_, run34b = call("POST", f"/ai/operators/{r34['id']}/run", token=TOKEN, body={"params": {"product_id": pid}}, expect=200)
_, ap34b = call("POST", f"/ai/runs/{run34b['id']}/approve", token=TOKEN, expect=200)
applied_b = ap34b["output"].get("applied", {})
base_slug = prods[0]["slug"] + "-ai"
check("§34 second apply gets a unique slug",
      applied_b.get("slug") != lp_slug and applied_b.get("slug", "").startswith(base_slug)
      and lp_slug.startswith(base_slug),
      {"first": lp_slug, "second": applied_b.get("slug"), "base": base_slug})

print("== §35 Customer Sentinel ==")
_, r35 = call("POST", "/ai/operators", token=TOKEN, body={"code": "customer_ops"}, expect=201)
_, run35 = call("POST", f"/ai/operators/{r35['id']}/run", token=TOKEN, body={"params": {}}, expect=200)
out35 = run35["output"]
check("§35 run succeeded + pending approval", run35["status"] == "succeeded" and run35["proposal_status"] == "pending")
watch = out35.get("watchlist", [])
buckets = {w["bucket"] for w in watch}
check("§35 monitors all 7 buckets",
      buckets == {"new_leads", "abandoned_opportunities", "pending_confirmations", "unreachable_customers",
                  "failed_deliveries", "repeat_customers", "support_issues"}, buckets)
totals = out35.get("totals", {})
check("§35 counts consistent between watchlist and totals",
      all(w["count"] == totals.get(w["bucket"], -1) for w in watch), totals)
check("§35 every bucket has a recommended action",
      all(w.get("recommended_action") for w in watch))
check("§35 playbook targets critical/warning buckets only",
      all(s["priority"] in ("critical", "warning") for s in out35.get("playbook", [])))

_, ap35 = call("POST", f"/ai/runs/{run35['id']}/approve", token=TOKEN, expect=200)
applied35 = ap35["output"].get("applied", {})
check("§35 approval executes the ops playbook", applied35.get("notifications_sent", 0) > 0
      and len(applied35.get("actions_executed", [])) > 0, applied35)
_, notifs = call("GET", "/notifications?limit=30", token=TOKEN, expect=200)
ops_notes = [n for n in notifs if n["title"].startswith("Customer Ops —")]
check("§35 playbook notifications landed in the feed", len(ops_notes) >= len(applied35.get("actions_executed", [])),
      [n["title"] for n in ops_notes])
check("§35 critical bucket escalated at critical level",
      any(n["level"] == "critical" for n in ops_notes), [n["level"] for n in ops_notes])

sr, _rr = call("POST", f"/ai/operators/{r35['id']}/run", token=AGENT, body={"params": {}})
check("agent blocked from running operators (403)", sr == 403, sr)

_, ops_all = call("GET", "/ai/operators", token=TOKEN, expect=200)
check("idempotent deploy — no duplicate operators after this smoke", len(ops_all) == 11,
      f"{len(ops_all)} operators")

print(f"\n{'='*50}\nPASSED: {PASSED}   FAILED: {FAILED}")
raise SystemExit(1 if FAILED else 0)

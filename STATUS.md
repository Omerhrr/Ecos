# ECOS Build Status — Audit vs Plan (62 sections)

Snapshot against `PLAN.md` after Task 16 (dropship mode: supplier ships direct to customers, skipping AGM).
Legend: ✅ core built & verified · 🟡 partial (core exists, gaps listed) · ❌ not started · ◻ vision/context (no code implied).

| § | Section | Status | Evidence / remaining gap |
|---|---------|--------|--------------------------|
| 1 | Executive Summary | ◻ | North-star context |
| 2 | Company & Product Structure | ◻ | Context (Plannexis/Luxeen/Ascendra) |
| 3 | Core Thesis | ◻ | Context |
| 4 | What Ecos Is Not | ◻ | Context |
| 5 | Participants | ✅ | Luxeen platform org + operator orgs + suppliers in data model; consumers via public storefront |
| 6 | Global Commerce Vision | 🟡 | Corridor abstraction: supplier orgs (any origin country), FX table + fallbacks, sourcing orders CN→NG with full ladder; no first-class corridor entity (by design OK for one corridor) |
| 7 | Core Domains | ✅ | Modular monolith, 28 routers, 45 tables — `automation/` is the only §7 domain with no module |
| 8 | Supply Network | 🟡 | Suppliers + verification + **supplier portal: self-upload → submit → Luxeen review gate → publish** + **performance panel (accept rate, transit days, arrival/cancel rates derived from live sourcing)**; comms/messaging still light |
| 9 | Supplier Isolation | ✅ | `public_card()` + Marketstore/sourcing serializers: operator payloads carry no supplier identity, supplier payloads no buyer identity — smoke-asserted |
| 10 | Product Catalog | ✅ | Variants/SKUs, video media, per-variant stock guards, PDP option picker, admin variants/videos manager; supplier listings materialise catalog products on publish |
| 11 | Product Discovery | 🟡 | **Marketstore live**: published listings, category/industry/search filters, NGN supply quotes (§12 waterfall, no retail markup); demand-scored discovery still future |
| 12 | Pricing Engine | 🟡 | Full waterfall — **now profile-driven (§57 WaterfallProfile: org/lane/category specificity) + §21 freight rate cards (air/sea/express per-kg, fuel, customs, lead time)**; promotions/volume pricing still future |
| 13 | Operator Store | ✅ | Store w/ branding, currency, country, products, pages |
| 14 | Storefront Engine | ✅ | Public store/PDP/cart/checkout/order tracking; customer accounts & collections not built |
| 15 | Landing Page Engine | ✅ | 9-block registry, editor with icon+accent palette thumbnails, immutable publish versions w/ rollback, scheduled auto-publish (60s scheduler), theme/SEO, UTM tagging |
| 16 | Marketing Infrastructure | 🟡 | Campaigns + UTM last-touch + attribution report (CPA/CPL/conversion); no pixel/impressions/clicks/creatives |
| 17 | CRM | ✅ | Pipeline incl. alternative paths, convert→order, storefront leads, campaign attribution |
| 18 | Customer Intelligence | ❌ | Data accumulating (orders/RMAs/attributions); no intelligence features yet |
| 19 | Order Engine | ✅ | Full state machine w/ branch states, price/cost/weight snapshots, per-line items |
| 20 | Fulfillment Engine | ✅ | Order→warehouse pick waves→shipments; supplier step modeled as `supplier_processing`; **sourcing orders: supplier accepts and drives the §23 ladder end-to-end**; **dropship mode: relay a confirmed storefront order to its supplier — per-line direct-to-door parcels (MOQ waived), customer order auto-completes, COD honestly stays pending for the operator** |
| 21 | Logistics Engine | ✅ | Shipments + normalized checkpoints, forward + reverse codes; **sourcing events ladder (CN pickup → export → customs → NG hub → arrival → AGM putaway)** + **freight rate cards: per-mode lane pricing (base/fuel/customs/min-charge/lead-time) quoted on the Marketstore and snapshotted onto sourcing orders** |
| 22 | Logistics Abstraction | 🟡 | Carrier field + normalization layer; **AGM: agent warehouses + per-vendor inventory as the local-leg executor**; **dropship as the second fulfillment mode (no AGM leg, ladder ends at the recipient's door)**; route engine / multi-carrier integration not built |
| 23 | Tracking | ✅ | Unified timeline (`TrackingEvent` + `SourcingEvent`, status/order maps) + public tracking page + operator sourcing timeline; **public /track now renders the dropship corridor for supplier-direct orders, with supplier identity scrubbed from free text (§9)** |
| 24 | Cash on Delivery | ✅ | COD default, delivery auto-collect, courier remittance register + **AGM agent remittance registers** (collect → remit → reconcile w/ variance → cod_variance true-up), double-entry ledger, /finance UI |
| 25 | Payments | ✅ | Statuses, refund/void, ledger hooks, provider field; single internal gateway (interface ready) |
| 26 | Financial Ledger | ✅ | Immutable signed entries for every money event incl. refunds + **sourcing waterfall (sourcing_payment / supplier_payable w/ CNY+FX memo / logistics / payment / luxeen)** |
| 27 | Settlement Engine | ✅ | Ledger-derived runs, counterparty buckets, approve/execute/cancel/preview; holds/adjustments/disputes pending |
| 28 | Returns & Refunds | ✅ | RMA state machine, restock→warehouse movements, ledger refunds; inspection/replacement flows light |
| 29 | Analytics | ✅ | Dashboard KPIs + attribution + three operator suites (§29): logistics (transit/carrier/stalls), financial (contribution economics from ledger), product (margin/returns/cover) + /analytics page |
| 30 | Command Center | 🟡 | Dashboard + notification feed + automation escalations; no unified "what needs attention" AI surface yet |
| 31 | Ecos Harness | ✅ | 11-operator bench, runs w/ token/latency audit, human-in-loop governance; **key flow complete**: DB-stored key (obfuscated at rest) editable from the admin UI flips live instantly (no restart), env var fallback, provider test w/ recorded outcome, masked key hints — set a key and the whole bench goes live DeepSeek |
| 32 | Product Research Operator | ✅ | "Market Scout" — velocity/margin/category-gap scan, advisory; live prose once key is set |
| 33 | Product Import Operator | ✅ | "Catalog Forger" — parses raw supplier listing → waterfall-priced DRAFT product on approval (human activates in Catalog) |
| 34 | Landing Page Operator | ✅ | **Page Architect**: audience analysis (lead sources, repeat-buyer share) → selling-angle pick (5 deterministic data-driven angles) → full 8-block page (hero/badges/story/features/testimonials/FAQ/CTA/showcase) → UTM-tagged CTAs (§16 handshake) → approval files an editable §15 draft (sanitized blocks, unique slugs) |
| 35 | Customer Operations Operator | ✅ | **Customer Sentinel**: monitors all 7 buckets (new leads, abandoned opportunities, pending confirmations, unreachable, failed deliveries, repeat customers, support issues/RMAs) w/ per-bucket recommended actions; approval executes the safe ops playbook (real notifications, critical escalation); calls/deliveries stay human per §39 |
| 36 | Growth Operator | ✅ | "Growth Pilot" — CPA-ranked budget moves (scale/fix/pause/investigate) from the live attribution report; advisory |
| 37 | Logistics Operator | ✅ | "Route Guard" — checkpoint-freshness SLA scan; approval raises ops escalation notifications |
| 38 | Business Analyst Operator | ✅ | "P&L Analyst" — ledger-grounded digest: highlights, risks, recommendations, metrics; advisory |
| 39 | AI Governance | ✅ | Approval gate, per-domain perms incl. `ai_harness:approve`, full run audit; escalation partial |
| 40 | Event-Driven Architecture | ✅ | Domain event bus, 25+ event types, 20+ subscriber handlers across domains |
| 41 | Automation Engine | ✅ | `automation/` module: WHEN/AND/THEN rules on the event bus (25-event catalog, 11 condition ops, 4 action types incl. settlement-draft), cooldowns, dry-run test, per-rule SAVEPOINT isolation, full match audit + /automation UI |
| 42 | Architecture Philosophy | ✅ | Folder structure mirrors §42 (fulfillment=warehouse, api=main.py) |
| 43 | Identity & Tenancy | ✅ | Orgs (luxeen/operator/supplier/agent), roles incl. supplier + agm, per-domain permissions, cross-org isolation, platform staff scope, token refresh |
| 44 | Security & Audit | ✅ | **audit_logs domain: semantic depth rows (actor/role/action/object/before/after/changed/source/auth-context/IP) on products, prices, payments, refunds, settlements, AI approvals, market gate, FX, profiles, rate cards, users** + blanket HTTP middleware (every mutating request) + /audit page w/ filters + diff detail; RBAC audit:read (agent/supplier/agm blocked) |
| 45 | Financial Integrity | ✅ | Immutable ledger, settlement stamping, no mutable money records |
| 46 | Multi-Currency | ✅ | `fx_rates` + conversion (direct/inverse/triangulated w/ cycle-guard/static), USD pricing page, **sourcing orders in NGN with CNY cost + FX snapshot; supplier payables memo-carried in CNY**; ledger money stays in capture currency (NGN) by design (§45) |
| 47 | Globalization | ❌ | Country fields only; config-driven country behavior not built |
| 48 | Network Intelligence | ❌ | Future — needs cross-operator volume |
| 49 | Ecos as Commerce Graph | ◻ | FK chain exists de facto (§51); graph reasoning is vision |
| 50 | Operator Experience | ✅ | Single environment achieved by construction |
| 51 | One Product, One Environment | ✅ | FK traceability: product→page→campaign→lead→order→shipment→payment→settlement→analytics |
| 52 | Commerce Intelligence Loop | 🟡 | Attribution→Stock Prophet→PO→putaway loop closed; full measure→learn→improve loop emerging |
| 53 | Ascendra Integration | ❌ | Partner referral layer — nothing to build yet |
| 54 | Plannexis Role | ◻ | Context |
| 55 | Luxeen Role | ◻ | Context |
| 56 | Ecos Business Model | ◻ | Context (economics partially modeled in ledger waterfall) |
| 57 | The Economic Model | ✅ | **WaterfallProfile: the §26/§12 rates are DATA** — resolve most-specific active profile (org > platform, corridor, category), freight from §21 rate cards w/ profile fallback, preview endpoint simulates cost→retail under any profile; ledger memos name the profile+card used; UI manages profiles + simulation |
| 58 | Ecos Control Plane | ◻ | Vision framing |
| 59 | Long-Term Vision | ◻ | Vision framing |
| 60 | Fundamental Product Loop | ✅ | Loop closed end-to-end in the running system (source→…→settlement→analytics→restock) |
| 61 | North-Star Definition | ◻ | Lives in the FastAPI app description |
| 62 | Final System View | ◻ | Vision framing |

**Score: 44 ✅ core · 3 🟡 partial · 5 ❌ not started · 12 ◻ vision/context** (after Task 16)

---

## Remaining engineering list (ranked, after Task 16)

1. **DeepSeek live key (§31)** — flow complete; paste a real key in AI Harness → Provider (or env) whenever Luxeen supplies it.
2. **Supplier comms/messaging (§8)** — structured negotiation/Q&A between operator and supplier on listings + sourcing orders (identity stays hidden).
3. **Later bets (§11, §18, §22, §47, §48, §53)** — demand-driven discovery, customer intelligence, route engine / multi-carrier, globalization config, network intelligence, Ascendra referral.

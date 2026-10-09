/**
 * Ecos API client + shared types.
 * The Nitro dev proxy forwards /api/** to FastAPI on :8000.
 *
 * All calls run through `req`, an authed $fetch instance: it attaches the
 * Bearer token and redirects to /login on 401 from admin-only paths
 * (plan §43).
 */

export interface PricingInfo {
  ecos_price_ngn: number
  fx_rate: number
  components: Record<string, number>
}

export interface ProductVariant {
  id: number
  product_id: number
  sku: string
  option_name: string
  option_value: string
  cost_delta: number
  weight_delta_kg: number
  stock: number
  image: string | null
  status: string
  label: string
  unit_price_ngn: number
  delta_vs_base_ngn: number
}

export interface Product {
  id: number
  slug: string | null
  supplier_id: number
  supplier_name: string | null
  supplier_lead_time_days: number | null
  title: string
  description: string
  category: string
  brand: string
  currency: string
  supplier_cost: number
  weight_kg: number
  markup_pct: number | null
  status: string
  stock: number
  country_of_origin: string
  images: string[]
  videos: string[]
  specs: Record<string, unknown>
  pricing: PricingInfo
  variants: ProductVariant[]
}

export interface Supplier {
  id: number
  name: string
  country: string
  city: string
  status: string
  rating: number
  lead_time_days: number
}

export interface Store {
  id: number
  org_id: number
  name: string
  slug: string
  country: string
  currency: string
  status: string
}

export interface Lead {
  id: number
  store_id: number
  store_name: string | null
  product_id: number
  product_title: string | null
  customer_id: number | null
  contact_name: string
  contact_phone: string
  status: string
  source: string
  campaign: string
  campaign_id: number | null
  campaign_name: string | null
  utm: Record<string, string>
  assigned_agent: string
  notes: string
  created_at: string
}

export interface OrderItem {
  id: number
  product_id: number
  title: string
  qty: number
  unit_price: number
  supplier_cost_cny: number
  weight_kg?: number
}

export interface Order {
  id: number
  store_id: number
  store_name: string | null
  customer_id: number
  customer_name: string | null
  customer_phone: string | null
  status: string
  payment_method: string
  payment_status: string
  currency: string
  items_total: number
  delivery_fee: number
  total: number
  created_at: string
}

export interface OrderDetail extends Order {
  customer: {
    id: number
    full_name: string
    phone: string
    address: string
    city: string
    state: string
    country: string
  } | null
  items: OrderItem[]
  allowed_transitions: string[]
}

export interface Shipment {
  id: number
  order_id: number
  status: string
  carrier: string
  tracking_code: string
  origin_country: string
  destination_country: string
  recipient_name: string
  recipient_phone: string
  recipient_address: string
  weight_kg: number
  created_at: string
  delivered_at: string | null
  timeline: TrackingEvent[]
}

export interface TrackingEvent {
  id: number
  code: string
  description: string
  location: string
  occurred_at: string
}

export interface Payment {
  id: number
  order_id: number
  method: string
  status: string
  amount: number
  currency: string
  provider: string
  reference: string
  reconciled: boolean
  collected_at: string | null
  created_at: string
}

export interface LedgerEntry {
  id: number
  order_id: number | null
  entry_type: string
  party: string
  amount: number
  currency: string
  memo: string
  created_at: string
}

export interface DomainEvent {
  id: number
  name: string
  payload: Record<string, unknown>
  created_at: string
}

/* ---------------- §16 marketing attribution ---------------- */

export interface Campaign {
  id: number
  org_id: number
  name: string
  channel: string
  status: string
  utm_campaign: string
  landing_page_slug: string
  budget_ngn: number
  notes: string
  created_at: string
}

export interface CampaignRow {
  id: number
  name: string
  channel: string
  status: string
  utm_campaign: string
  landing_page_slug: string
  spend_ngn: number
  leads: number
  converted_leads: number
  conversion_rate: number
  orders: number
  revenue_ngn: number
  cpa_ngn: number | null
  cost_per_lead_ngn: number | null
}

export interface SourceRow {
  source: string
  leads: number
  converted_leads: number
  orders: number
  revenue_ngn: number
}

export interface AttributionReport {
  campaigns: CampaignRow[]
  by_source: SourceRow[]
  totals: {
    leads: number
    converted_leads: number
    conversion_rate: number
    revenue_ngn: number
    spend_ngn: number
    attributed_lead_pct: number
  }
}

/* ---------------- §28 returns ---------------- */

export interface ReturnOrder {
  id: number
  rma_number: string
  order_id: number
  store_id: number
  customer_id: number
  customer_name: string | null
  order_total: number | null
  order_status: string | null
  status: string
  reason: string
  resolution: string
  restock: boolean
  refund_amount: number
  currency: string
  notes: string
  allowed_transitions: string[]
  created_at: string
}

export interface EligibleOrder {
  id: number
  status: string
  total: number
  currency: string
  payment_status: string
  customer_name: string | null
}

/* ---------------- §27 settlements ---------------- */

export interface SettlementLine {
  id: number
  entry_type: string
  party: string
  counterparty: string
  currency: string
  amount: number
  entry_count: number
  entry_ids: number[]
}

export interface SettlementRun {
  id: number
  run_number: string
  org_id: number | null
  status: 'draft' | 'approved' | 'executed' | 'cancelled'
  currency: string
  total_amount: number
  entry_count: number
  line_count: number
  note: string
  executed_at: string | null
  created_at: string | null
  lines?: SettlementLine[]
}

export interface SettlementPreview {
  lines: SettlementLine[]
  total_amount: number
  entry_count: number
  currencies: string[]
}

/* ---------------- §39 notifications ---------------- */

export interface EcosNotification {
  id: number
  recipient_user_id: number
  org_id: number | null
  category: string
  level: 'info' | 'success' | 'warning' | 'critical'
  title: string
  body: string
  entity_type: string
  entity_id: number | null
  meta: Record<string, unknown>
  read: boolean
  read_at: string | null
  created_at: string | null
}

export interface NotificationPreference {
  category: string
  in_app: boolean
  email: boolean
  whatsapp: boolean
  updated_at: string | null
}

/* ---------------- §21/§22 procurement ---------------- */

export interface ReorderSuggestion {
  id: number
  product_id: number
  product_title: string | null
  product_stock: number | null
  supplier_id: number | null
  supplier_name: string | null
  supplier_lead_time_days: number | null
  run_id: number
  org_id: number | null
  status: 'open' | 'converted' | 'dismissed' | 'superseded'
  risk: string
  weekly_velocity: number
  weeks_of_cover: number | null
  stock_at_time: number
  suggested_qty: number
  po_id: number | null
  created_at: string | null
  resolved_at: string | null
}

export interface PurchaseOrderLine {
  id: number
  product_id: number
  product_title: string | null
  qty_ordered: number
  qty_received: number
  qty_outstanding: number
  unit_cost: number
  line_total: number
}

export interface PurchaseOrder {
  id: number
  po_number: string
  supplier_id: number
  supplier_name: string | null
  supplier_lead_time_days: number | null
  status: 'draft' | 'submitted' | 'confirmed' | 'received' | 'cancelled'
  currency: string
  items_total: number
  freight: number
  expected_at: string | null
  note: string
  source: string
  source_run_id: number | null
  org_id: number | null
  allowed_transitions: string[]
  lines?: PurchaseOrderLine[]
  created_at: string | null
}

export interface SuggestionRefreshSummary {
  run_id: number
  open_suggestions: number
  new_suggestions: number
}

/* ---------------- §31+ AI harness ---------------- */

export interface AiInputField {
  key: string
  label: string
  type: string
  required: boolean
  placeholder?: string
}

export interface AiBlueprint {
  code: string
  name: string
  role_description: string
  advisory: boolean
  input_fields: AiInputField[]
}

export interface AiOperator {
  id: number
  org_id: number | null
  code: string
  name: string
  role_description: string
  autonomy: string
  status: 'active' | 'paused'
  input_fields: AiInputField[]
  advisory: boolean
  runs_total: number
  runs_pending: number
  last_run_id: number | null
  last_run_status: string | null
  last_run_at: string | null
  created_at: string | null
}

export interface AiRun {
  id: number
  operator_id: number
  operator_name: string | null
  operator_code: string | null
  status: 'succeeded' | 'failed'
  proposal_status: 'pending' | 'approved' | 'rejected' | 'applied' | 'advisory' | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  error: string
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  approved_by: number | null
  approved_at: string | null
  created_at: string
}

export interface AiProviderInfo {
  provider: 'deepseek' | 'heuristic-fallback'
  model: string
  key_configured: boolean
  key_source: 'database' | 'env' | null
  key_hint: string | null
  base_url: string | null
  last_test_ok: boolean | null
  last_test_at: string | null
  last_test_latency_ms: number | null
  last_test_error: string
  live_instructions: string | null
}

export interface Summary {
  revenue_ngn: number
  cod_pending_ngn: number
  orders_total: number
  orders_delivered: number
  orders_in_flight: number
  orders_problem: number
  delivery_rate: number
  aov_ngn: number
  leads_total: number
  leads_active: number
  lead_conversion: number
}

export interface Funnel {
  pipeline: { status: string; count: number }[]
  exits: { status: string; count: number }[]
}

export interface TopProduct {
  product_id: number
  title: string
  units: number
  revenue_ngn: number
}

/* ---------------- §15 landing pages ---------------- */

export interface BlockFieldDef {
  key: string
  label: string
  ftype: 'text' | 'textarea' | 'url' | 'color' | 'select' | 'number' | 'lines' | 'csv_ids'
  options: string[] | null
  default: string
  hint: string
}

export interface BlockTypeDef {
  type: string
  label: string
  icon?: string
  accent?: string
  fields: BlockFieldDef[]
}

export interface LandingPageBlock {
  id: string
  type: string
  [key: string]: unknown
}

export interface LandingPageSummary {
  id: number
  org_id: number
  slug: string
  title: string
  status: 'draft' | 'published'
  block_count: number
  updated_at: string | null
  published_at: string | null
  scheduled_at?: string | null
}

export interface LandingPage extends LandingPageSummary {
  blocks: LandingPageBlock[]
  theme: { primary?: string }
  seo: { title?: string; description?: string; og_image?: string }
}

export interface LpVersion {
  id: number | null
  page_id: number
  version_no: number | 'live'
  block_count: number
  published_by: number | null
  published_at: string | null
  note: string
  is_current?: boolean
}

/* ---------------- §24 COD remittance register ---------------- */

export interface CodRegisterLine {
  id: number
  payment_id: number
  order_id: number
  order_number: string
  shipment_id: number | null
  expected_amount: number
  counted_amount: number
  collected_at: string | null
}

export interface CodRegister {
  id: number
  register_code: string
  org_id: number
  carrier: string
  status: 'draft' | 'remitted' | 'reconciled' | 'cancelled'
  currency: string
  expected_amount: number
  remitted_amount: number
  counted_amount: number
  variance_amount: number
  reference: string
  note: string
  line_count: number
  created_at: string | null
  remitted_at: string | null
  reconciled_at: string | null
  lines?: CodRegisterLine[]
}

export interface CodSummary {
  outstanding_by_carrier: { carrier: string; outstanding_amount: number; outstanding_count: number }[]
  outstanding_total: number
  registers_reconciled: number
  last_reconciled_at: string | null
}

/* ---------------- §14 public storefront ---------------- */

export interface PublicProduct {
  id: number
  slug: string | null
  title: string
  category: string
  brand: string
  price_ngn: number
  image: string | null
  images: string[]
  in_stock: boolean
}

export interface PublicProductDetail extends PublicProduct {
  description: string
  specs: Record<string, unknown>
  videos: string[]
  variants: PublicVariant[]
}

export interface PublicVariant {
  id: number
  label: string
  price_ngn: number
  stock: number
  image: string | null
  in_stock: boolean
  price_display?: { amount: number; rate: number; source: string }
}

export interface PublicStore {
  id: number
  name: string
  slug: string
  country: string
  currency: string
}

export interface PublicHome {
  store: PublicStore
  page: {
    id: number
    slug: string
    title: string
    blocks: LandingPageBlock[]
    theme: { primary?: string }
    seo: Record<string, string>
  } | null
  products: PublicProduct[]
}

export interface PublicPage {
  id: number
  slug: string
  title: string
  blocks: LandingPageBlock[]
  theme: { primary?: string }
  seo: Record<string, string>
}

/* ---------------- §46 multi-currency ---------------- */

export interface FxRateRow {
  base: string
  quote: string
  rate: number
  source: string
  updated_by: number | null
  updated_at: string | null
}

/* ---------------- §57 economics profiles / §21 freight cards / §44 audit ---------------- */

export interface WaterfallProfile {
  id: number
  org_id: number | null
  name: string
  corridor: string
  category: string
  payment_cost_pct: number | null
  luxeen_margin_pct: number | null
  operator_markup_pct: number | null
  logistics_per_kg_ngn: number | null
  tax_pct: number | null
  active: boolean
  priority: number
  created_at: string | null
}

export interface WaterfallPreview {
  fx: { amount: number; rate: number; from: string; to: string; source: string }
  profile: Record<string, unknown>
  rate_card: FreightRateCard | null
  waterfall: {
    supplier_ngn: number
    freight_ngn: number
    customs_ngn: number
    logistics_ngn: number
    payment_ngn: number
    luxeen_ngn: number
    economics_basis: Record<string, unknown>
  }
  supply_total_ngn: number
  ecos_price_ngn: number
}

export interface FreightRateCard {
  id: number
  org_id: number | null
  name: string
  mode: string
  origin_country: string
  dest_country: string
  base_fixed_ngn: number
  per_kg_ngn: number
  fuel_surcharge_pct: number
  customs_pct: number
  min_charge_ngn: number
  lead_time_days_min: number
  lead_time_days_max: number
  active: boolean
  priority: number
  effective_per_kg_ngn: number
}

export interface AuditRow {
  id: number
  org_id: number | null
  actor_user_id: number | null
  actor_label: string
  actor_role: string
  action: string
  entity_type: string
  entity_id: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  changed: Record<string, { from: unknown; to: unknown }> | null
  source: string
  method: string
  path: string
  ip: string
  auth_context: string
  created_at: string | null
}

export interface SupplierPerf {
  supplier_id: number
  name: string
  city: string
  country: string
  status: string
  listings: { total: number; by_status: Record<string, number>; published: number }
  sourcing: {
    orders_total: number
    cancelled: number
    cancel_rate: number | null
    accept_rate: number | null
    avg_accept_hours: number | null
    avg_transit_days: number | null
    arrival_rate: number | null
    received_orders: number
    units_received: number
  }
  last_activity: string | null
}

export interface FxMoney {
  amount: number
  rate: number
  source: string
}

export interface PublicPricing {
  base_currency: string
  display_currencies: string[]
  usd: { rate: number; source: string }
  products: (PublicProduct & { price_display?: FxMoney })[]
}

/* ---------------- §41 automation engine ---------------- */

export interface AutomationCondition {
  path: string
  op: string
  value?: unknown
  actual?: unknown
  ok?: boolean
}

export interface AutomationAction {
  type: string
  title?: string
  body?: string
  level?: string
  category?: string
  reason?: string
  product_id?: number | null
  product_path?: string
  notifications?: number
  run_number?: string
  skipped?: boolean
  dry_run?: boolean
}

export interface AutomationRule {
  id: number
  org_id: number | null
  name: string
  description: string
  event_type: string
  enabled: boolean
  conditions: AutomationCondition[]
  actions: AutomationAction[]
  cooldown_seconds: number
  match_count: number
  last_matched_at: string | null
  created_at: string | null
}

export interface AutomationRunRow {
  id: number
  rule_id: number
  rule_name: string
  event_type: string
  status: 'matched' | 'condition_not_met' | 'cooldown' | 'dry_run' | 'failed'
  conditions_result: AutomationCondition[]
  actions_executed: AutomationAction[]
  error: string
  created_at: string | null
}

export interface AutomationEventDef {
  name: string
  label: string
  sample: string
}

/* ---------------- §29 analytics suites ---------------- */

export interface AnalyticsLogistics {
  window_days: number
  shipments_total: number
  shipments_delivered: number
  shipments_active: number
  avg_transit_hours: number | null
  stalled_over_48h: { shipment_id: number; order_id: number; tracking_code: string; last_checkpoint: string | null }[]
  carriers: { carrier: string; shipments: number; delivered: number; active: number; delivered_share: number }[]
  reverse_checkpoints: number
  checkpoint_total: number
}

export interface AnalyticsFinancial {
  window_days: number
  ledger_totals_by_type: Record<string, number>
  gross_revenue_ngn: number
  refunds_ngn: number
  net_revenue_ngn: number
  supplier_cost_ngn: number
  logistics_cost_ngn: number
  payment_cost_ngn: number
  luxeen_economics_ngn: number
  operator_economics_ngn: number
  contribution_ngn: number
  contribution_margin_pct: number
  cod_collected_ngn: number
  cod_pending_ngn: number
  payments_count: number
  unsettled_obligations: { amount: number; entries: number; lines: { counterparty: string; amount: number; entry_count: number }[] }
}

export interface AnalyticsProductRow {
  product_id: number
  title: string
  units_sold: number
  revenue_ngn: number
  supplier_cost_ngn: number
  gross_margin_ngn: number
  margin_per_unit_ngn: number
  return_units: number
  return_rate: number
  stock_on_hand: number
  weekly_velocity: number
  weeks_of_cover: number | null
  status: string | null
}

export interface AnalyticsProducts {
  window_days: number
  products: AnalyticsProductRow[]
  catalog_total: number
  catalog_active: number
  never_sold_with_stock: { product_id: number; title: string; stock: number }[]
}

/* ---------------- §39 notifications + §39 Phase 3 outbox ---------------- */

export interface OutboxRow {
  id: number
  org_id: number | null
  user_id: number
  channel: 'email' | 'whatsapp'
  recipient: string
  category: string
  subject: string
  body: string
  notification_id: number | null
  status: 'queued' | 'sent' | 'failed' | 'skipped'
  attempts: number
  max_attempts: number
  provider: string
  provider_ref: string
  last_error: string
  available_at: string | null
  sent_at: string | null
  created_at: string | null
}

export interface OutboxStats {
  providers: { email: string; whatsapp: string }
  by_channel: Record<string, { queued: number; sent: number; failed: number; total: number }>
}

/* ---------------- §22 warehouse / fulfillment ---------------- */

export interface WarehouseInfo {
  id: number
  code: string
  name: string
  city: string
  country: string
  address: string
  status: string
  is_default: boolean
  org_id: number | null
  sku_count: number
  units_on_hand: number
  open_waves: number
  created_at: string | null
}

export interface StockRow {
  id: number
  warehouse_id: number
  warehouse_code: string | null
  warehouse_name: string | null
  product_id: number
  product_title: string | null
  product_stock: number | null
  on_hand: number
  reserved: number
  available: number
  updated_at: string | null
}

export interface StockMovementRow {
  id: number
  warehouse_id: number
  warehouse_code: string | null
  product_id: number
  product_title: string | null
  movement_type: 'receipt' | 'pick' | 'adjustment' | 'transfer_in' | 'transfer_out' | 'return_restock'
  qty: number
  balance_after: number
  reference_type: string
  reference_id: number | null
  note: string
  created_by: number | null
  created_at: string | null
}

export interface PickLineRow {
  id: number
  order_id: number
  product_id: number
  title: string
  qty: number
  picked_qty: number
  status: 'pending' | 'picked' | 'packed'
}

export interface PickWave {
  id: number
  wave_number: string
  warehouse_id: number
  warehouse_code: string | null
  warehouse_name: string | null
  org_id: number | null
  status: 'open' | 'picking' | 'packed' | 'completed' | 'cancelled'
  order_count: number
  note: string
  created_by: number | null
  picked_at: string | null
  packed_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  created_at: string | null
  allowed_transitions: string[]
  lines?: PickLineRow[]
}

/* ---------------- §14 checkout (public, no auth) ---------------- */

export interface CheckoutQuote {
  currency: string
  lines: { product_slug: string; title: string; qty: number; unit_price: number; line_total: number; in_stock: boolean }[]
  items_total: number
  delivery_fee: number
  total: number
}

export interface CheckoutResult {
  ok: boolean
  order_id: number
  status: string
  total: number
  currency: string
  payment_method: string
  customer_id: number
  message: string
}

export interface TrackingCheckpoint {
  code: string
  description: string
  location: string
  occurred_at: string | null
}

export interface PublicShipment {
  tracking_code: string
  carrier: string
  status: string
  created_at: string | null
  delivered_at: string | null
  tracking_events: TrackingCheckpoint[]
}

export interface PublicOrderStatus {
  order_id: number
  order_number: string
  status: string
  payment_method: string
  payment_status: string
  total: number
  currency: string
  placed_at: string | null
  items: { title: string; qty: number; unit_price: number }[]
  shipment: PublicShipment | null
}

/* ---------------- §43 auth ---------------- */

export interface LoginResponse {
  token: string
  user: {
    id: number
    org_id: number
    name: string
    email: string
    role: string
    is_active: boolean
  }
  org: { id: number; name: string; type: string; country: string; currency: string }
  permissions: string[]
}

const PUBLIC_PATHS = ['/', '/login', '/lp', '/products', '/cart', '/track', '/pricing']

// ---- §8-11 Marketstore / sourcing / AGM types ----

export interface MarketListing {
  id: number
  catalog_product_id: number | null
  title: string
  description: string
  category: string
  industry: string
  images: string[]
  specs: Record<string, unknown>
  moq: number
  weight_kg: number
  currency: string
  unit_price: number
  pricing: Record<string, number>
  economics: { profile_id: number | null; profile_name: string; rate_card: string; rate_card_id: number | null }
  lane_options: FreightRateCard[]
  available_from: string
  lead_time_days: number
}

export interface SourcingEvent {
  id: number
  code: string
  description: string
  location: string
  occurred_at: string | null
}

export interface SourcingOrder {
  id: number
  order_number: string
  title: string
  qty: number
  cny_total: number
  fx_rate: number
  local_currency: string
  local_total: number
  status: string
  payment_method: string
  payment_reference: string
  paid_at: string | null
  destination: { name: string; phone: string; address: string; city: string; country: string; via_agent: boolean }
  supplier_note: string
  received_at: string | null
  catalog_product_id: number | null
  created_at: string | null
  events?: SourcingEvent[]
  receive_result?: Record<string, unknown>
}

export interface SupplierProduct {
  id: number
  title: string
  description: string
  category: string
  industry: string
  cost_price: number
  currency: string
  weight_kg: number
  moq: number
  images: string[]
  specs: Record<string, unknown>
  status: string
  review_notes: string
  catalog_product_id: number | null
  allowed_transitions?: string[]
}

export interface SourcingSupplierView {
  id: number
  order_number: string
  title: string
  qty: number
  unit_cost_cny: number
  cny_total: number
  status: string
  destination: { name: string; phone: string; address: string; city: string; country: string }
  note: string
  events?: SourcingEvent[]
}

export interface AgentCard {
  agent_org_id: number
  company: string
  contact_name: string
  phone: string
  whatsapp: string
  city: string
  country: string
  address: string
  capacity_note: string
  rating: number
  warehouses: number
  status: string
  linked: boolean
  link_status: string | null
}

export interface AgentLinkRow {
  id: number
  agent_org_id: number
  agent_name?: string
  vendor_org_id?: number
  vendor_name?: string
  city?: string
  phone?: string
  warehouses?: number
  status: string
  created_at: string | null
}

export interface AgentOrder {
  id: number
  code: string
  agent_org_id: number
  vendor_org_id: number
  order_id: number
  product_id: number
  title: string
  qty: number
  customer: { name: string; phone: string; address: string; city: string }
  payment_method: string
  cod_expected: number
  cod_collected: number
  collected_at: string | null
  remittance_id: number | null
  status: string
  note: string
  failed_reason: string
  created_at: string | null
  allowed_transitions: string[]
}

export interface AgmOverview {
  company: string
  vendors: number
  warehouses: number
  queue: Record<string, number>
  pending_alerts: number
  cod_awaiting_remit: number
  units_held: number
}

export interface AgentWarehouseRow {
  id: number
  code: string
  name: string
  city: string
  country: string
  address: string
  is_default: boolean
  status: string
}

export interface AgentStockRow {
  id: number
  warehouse_id: number
  vendor_org_id: number
  vendor_name: string
  product_id: number
  product_title: string
  product_image: string | null
  on_hand: number
  reserved: number
  sellable: number
}

export interface AgentRemittance {
  id: number
  register_code: string
  agent_org_id: number
  vendor_org_id: number | null
  status: string
  currency: string
  expected_amount: number
  remitted_amount: number
  counted_amount: number
  variance_amount: number
  reference: string
  note: string
  remitted_at: string | null
  reconciled_at: string | null
  created_at: string | null
  lines?: { id: number; agent_order_id: number; order_id: number; vendor_org_id: number; expected_amount: number; counted_amount: number }[]
}

function isPublicPath(path: string) {
  if (path === '/' || path === '/login' || path === '/cart') return true
  return PUBLIC_PATHS.some(p => p !== '/' && path.startsWith(p))
}

export function useApi() {
  const baseReq = $fetch.create({
    onRequest({ options }) {
      if (import.meta.client) {
        const token = localStorage.getItem('ecos:token')
        if (token) {
          const headers = new Headers(options.headers as HeadersInit | undefined)
          headers.set('Authorization', `Bearer ${token}`)
          options.headers = headers
        }
      }
    },
  })

  // ---- §43 token refresh (session continuity) ---------------------------
  // Rotate a still-valid token for a fresh 12h lease. `current` lets the
  // caller pass the exact credential that just failed (localStorage may
  // already have been cleared by an earlier failure).
  async function refreshToken(current?: string): Promise<string | null> {
    if (!import.meta.client) return null
    const token = current ?? localStorage.getItem('ecos:token')
    if (!token) return null
    try {
      const res = await $fetch<LoginResponse>('/api/auth/refresh', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      localStorage.setItem('ecos:token', res.token)
      return res.token
    }
    catch {
      return null
    }
  }

  // Every admin API call funnels through here: on a 401 we try ONE silent
  // token rotation + retry (covers the "session older than 12h" case).
  // If the refresh also fails the session is genuinely dead -> clear + login.
  async function req<T>(url: string, opts: Record<string, unknown> = {}): Promise<T> {
    try {
      return await baseReq<T>(url as never, opts as never)
    }
    catch (err: unknown) {
      const status = (err as { status?: number; response?: { status?: number } })?.status
        ?? (err as { response?: { status?: number } })?.response?.status
      if (status === 401 && import.meta.client && !isPublicPath(window.location.pathname)) {
        const captured = localStorage.getItem('ecos:token') ?? undefined
        const fresh = await refreshToken(captured)
        if (fresh) return await baseReq<T>(url as never, opts as never)
        localStorage.removeItem('ecos:token')
        navigateTo('/login')
      }
      throw err
    }
  }

  return {
    // ---- auth (§43) ----
    login: (email: string, password: string) =>
      req<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } }),
    me: () => req<LoginResponse>('/api/auth/me'),
    // §43 session continuity: rotate the current token for a fresh 12h lease
    refreshToken: async () => {
      if (!import.meta.client) return false
      const token = localStorage.getItem('ecos:token')
      if (!token) return false
      try {
        const res = await $fetch<LoginResponse>('/api/auth/refresh', {
          method: 'POST', headers: { Authorization: `Bearer ${token}` },
        })
        localStorage.setItem('ecos:token', res.token)
        return true
      }
      catch { return false }
    },
    createUser: (body: Record<string, unknown>) =>
      req<Record<string, unknown>>('/api/users', { method: 'POST', body }),

    // ---- analytics ----
    summary: () => req<Summary>('/api/analytics/summary'),
    funnel: () => req<Funnel>('/api/analytics/funnel'),
    topProducts: () => req<TopProduct[]>('/api/analytics/top-products'),

    // ---- §29 analytics suites ----
    analyticsLogistics: (days = 30) =>
      req<AnalyticsLogistics>('/api/analytics/logistics', { params: { days } }),
    analyticsFinancial: (days = 30) =>
      req<AnalyticsFinancial>('/api/analytics/financial', { params: { days } }),
    analyticsProducts: (days = 30) =>
      req<AnalyticsProducts>('/api/analytics/products', { params: { days } }),

    // ---- §41 automation engine ----
    automationRules: () => req<AutomationRule[]>('/api/automation/rules'),
    automationEvents: () => req<AutomationEventDef[]>('/api/automation/events'),
    automationRuns: (params?: { rule_id?: number; status?: string; limit?: number }) =>
      req<AutomationRunRow[]>('/api/automation/runs', { params }),
    createAutomationRule: (body: {
      name: string
      description?: string
      event_type: string
      enabled?: boolean
      conditions: { path: string; op: string; value?: unknown }[]
      actions: { type: string; title?: string; body?: string; level?: string; category?: string; reason?: string }[]
      cooldown_seconds?: number
    }) => req<AutomationRule>('/api/automation/rules', { method: 'POST', body }),
    patchAutomationRule: (id: number, body: Partial<Pick<AutomationRule, 'name' | 'description' | 'enabled' | 'conditions' | 'actions' | 'cooldown_seconds'>>) =>
      req<AutomationRule>(`/api/automation/rules/${id}`, { method: 'PATCH', body }),
    deleteAutomationRule: (id: number) =>
      req<void>(`/api/automation/rules/${id}`, { method: 'DELETE' }),
    testAutomationRule: (id: number, eventType: string, payload: Record<string, unknown>) =>
      req<{ rule_id: number; results: AutomationRunRow[] }>(`/api/automation/rules/${id}/test`, { method: 'POST', body: { event_type: eventType, payload } }),
    replayAutomationEvent: (event_type: string, payload: Record<string, unknown>) =>
      req<{ event_type: string; results: AutomationRunRow[] }>('/api/automation/events/replay', { method: 'POST', body: { event_type, payload } }),

    // ---- §46 multi-currency ----
    fxRates: () => req<{ rates: FxRateRow[]; supported: string[] }>('/api/finance/fx'),
    setFxRate: (body: { base: string; quote: string; rate: number }) =>
      req<FxRateRow>('/api/finance/fx', { method: 'POST', body }),

    // ---- §57 economics profiles / §21 freight cards / §44 audit / §8 perf ----
    waterfallProfiles: () =>
      req<{ profiles: WaterfallProfile[]; defaults: { payment_cost_pct: number; luxeen_margin_pct: number; logistics_per_kg_ngn: number } }>('/api/finance/profiles'),
    createProfile: (body: Partial<WaterfallProfile>) =>
      req<WaterfallProfile>('/api/finance/profiles', { method: 'POST', body }),
    patchProfile: (id: number, body: Partial<WaterfallProfile>) =>
      req<WaterfallProfile>(`/api/finance/profiles/${id}`, { method: 'PATCH', body }),
    previewWaterfall: (body: { supplier_cost: number; currency?: string; weight_kg?: number; qty?: number; org_id?: number | null; category?: string; markup_pct?: number | null }) =>
      req<WaterfallPreview>('/api/finance/profiles/preview', { method: 'POST', body }),
    freightCards: () => req<{ cards: FreightRateCard[]; modes: string[] }>('/api/freight/cards'),
    createFreightCard: (body: Partial<FreightRateCard>) =>
      req<FreightRateCard>('/api/freight/cards', { method: 'POST', body }),
    patchFreightCard: (id: number, body: Partial<FreightRateCard>) =>
      req<FreightRateCard>(`/api/freight/cards/${id}`, { method: 'PATCH', body }),
    audit: (params?: { entity_type?: string; entity_id?: string; action?: string; source?: string; include_http?: boolean; limit?: number }) =>
      req<AuditRow[]>('/api/audit', { params }),
    supplierPerformance: () => req<{ suppliers: SupplierPerf[] }>('/api/suppliers/performance/summary'),

    suppliers: () => req<Supplier[]>('/api/suppliers'),
    stores: () => req<Store[]>('/api/stores'),

    products: (params?: { status?: string }) => req<Product[]>('/api/products', { params }),
    createProduct: (body: Partial<Product>) =>
      req<Product>('/api/products', { method: 'POST', body }),
    patchProduct: (id: number, body: Record<string, unknown>) =>
      req<Product>(`/api/products/${id}`, { method: 'PATCH', body }),

    // ---- §10 catalog depth: variants ----
    createVariant: (productId: number, body: { sku?: string; option_name?: string; option_value: string; cost_delta?: number; weight_delta_kg?: number; stock?: number; image?: string | null }) =>
      req<ProductVariant>(`/api/products/${productId}/variants`, { method: 'POST', body }),
    patchVariant: (id: number, body: Record<string, unknown>) =>
      req<ProductVariant>(`/api/products/variants/${id}`, { method: 'PATCH', body }),
    archiveVariant: (id: number) =>
      req<void>(`/api/products/variants/${id}`, { method: 'DELETE' }),

    leads: () => req<Lead[]>('/api/leads'),
    createLead: (body: Record<string, unknown>) =>
      req<Lead>('/api/leads', { method: 'POST', body }),
    patchLead: (id: number, body: Record<string, unknown>) =>
      req<Lead>(`/api/leads/${id}`, { method: 'PATCH', body }),
    convertLead: (id: number) =>
      req<{ order_id: number }>(`/api/leads/${id}/convert`, { method: 'POST' }),

    // ---- marketing attribution (§16) ----
    campaigns: () => req<Campaign[]>('/api/marketing/campaigns'),
    createCampaign: (body: Record<string, unknown>) =>
      req<Campaign>('/api/marketing/campaigns', { method: 'POST', body }),
    patchCampaign: (id: number, body: Record<string, unknown>) =>
      req<Campaign>(`/api/marketing/campaigns/${id}`, { method: 'PATCH', body }),
    attribution: () => req<AttributionReport>('/api/marketing/attribution'),

    // ---- returns (§28) ----
    returns: () => req<ReturnOrder[]>('/api/returns'),
    eligibleOrders: () => req<EligibleOrder[]>('/api/returns/eligible-orders'),
    createReturn: (body: Record<string, unknown>) =>
      req<ReturnOrder>('/api/returns', { method: 'POST', body }),
    returnAction: (id: number, action: 'approve' | 'reject' | 'receive' | 'refund' | 'close', body?: Record<string, unknown>) =>
      req<ReturnOrder>(`/api/returns/${id}/${action}`, { method: 'POST', body: body ?? {} }),

    // ---- settlements (§27) ----
    settlementPreview: () => req<SettlementPreview>('/api/settlements/preview'),
    settlements: () => req<SettlementRun[]>('/api/settlements'),
    settlement: (id: number) => req<SettlementRun>(`/api/settlements/${id}`),
    buildSettlement: (body?: Record<string, unknown>) =>
      req<SettlementRun>('/api/settlements', { method: 'POST', body: body ?? {} }),
    settlementAction: (id: number, action: 'approve' | 'execute' | 'cancel') =>
      req<SettlementRun>(`/api/settlements/${id}/${action}`, { method: 'POST', body: {} }),

    // ---- AI harness (§31+, DeepSeek) ----
    aiProvider: () => req<AiProviderInfo>('/api/ai/provider'),
    aiProviderTest: () =>
      req<{ ok: boolean; model: string; latency_ms: number; reply: string }>('/api/ai/provider/test', { method: 'POST', body: {} }),
    aiSaveProviderSettings: (body: { api_key?: string | null; model?: string | null; base_url?: string | null }) =>
      req<AiProviderInfo>('/api/ai/provider/settings', { method: 'PUT', body }),
    aiRegistry: () => req<AiBlueprint[]>('/api/ai/registry'),
    aiOperators: () => req<AiOperator[]>('/api/ai/operators'),
    deployAiOperator: (code: string) =>
      req<AiOperator>('/api/ai/operators', { method: 'POST', body: { code } }),
    patchAiOperator: (id: number, body: Record<string, unknown>) =>
      req<AiOperator>(`/api/ai/operators/${id}`, { method: 'PATCH', body }),
    runAiOperator: (id: number, params: Record<string, unknown>) =>
      req<AiRun>(`/api/ai/operators/${id}/run`, { method: 'POST', body: { params } }),
    aiRuns: (operatorId?: number) =>
      req<AiRun[]>('/api/ai/runs', { params: operatorId ? { operator_id: operatorId } : {} }),
    aiRunAction: (id: number, action: 'approve' | 'reject', body?: Record<string, unknown>) =>
      req<AiRun>(`/api/ai/runs/${id}/${action}`, { method: 'POST', body: body ?? {} }),

    // ---- notifications (§39) ----
    notifications: (params?: { unread_only?: boolean; category?: string; limit?: number }) =>
      req<EcosNotification[]>('/api/notifications', { params }),
    unreadCount: () => req<{ unread: number }>('/api/notifications/unread-count'),
    markNotificationRead: (id: number) =>
      req<EcosNotification>(`/api/notifications/${id}/read`, { method: 'POST', body: {} }),
    markAllNotificationsRead: () =>
      req<{ marked: number }>('/api/notifications/read-all', { method: 'POST', body: {} }),
    notificationPreferences: () => req<NotificationPreference[]>('/api/notifications/preferences'),
    updateNotificationPreference: (body: { category: string; in_app?: boolean; email?: boolean; whatsapp?: boolean }) =>
      req<NotificationPreference>('/api/notifications/preferences', { method: 'PUT', body }),
    sendTestNotification: () => req<EcosNotification>('/api/notifications/test', { method: 'POST', body: {} }),

    // ---- §39 Phase 3 outbound channels ----
    outbox: (params?: { channel?: string; status?: string; limit?: number }) =>
      req<OutboxRow[]>('/api/notifications/outbox', { params }),
    outboxStats: () => req<OutboxStats>('/api/notifications/outbox/stats'),
    processOutbox: () =>
      req<{ processed: number; sent: number; failed: number; retried: number }>('/api/notifications/outbox/process', { method: 'POST', body: {} }),

    // ---- procurement (§21/§22) ----
    reorderSuggestions: (status?: string) =>
      req<ReorderSuggestion[]>('/api/procurement/reorder-suggestions', { params: status ? { status } : {} }),
    refreshSuggestions: () =>
      req<SuggestionRefreshSummary>('/api/procurement/reorder-suggestions/refresh', { method: 'POST', body: {} }),
    dismissSuggestion: (id: number) =>
      req<ReorderSuggestion>(`/api/procurement/reorder-suggestions/${id}/dismiss`, { method: 'POST', body: {} }),
    createPoFromSuggestions: (body: { suggestion_ids?: number[]; note?: string }) =>
      req<PurchaseOrder[]>('/api/procurement/reorder-suggestions/create-po', { method: 'POST', body }),
    purchaseOrders: (status?: string) =>
      req<PurchaseOrder[]>('/api/procurement', { params: status ? { status } : {} }),
    createPurchaseOrder: (body: { supplier_id: number; lines: { product_id: number; qty: number }[]; note?: string }) =>
      req<PurchaseOrder>('/api/procurement', { method: 'POST', body }),
    poAction: (id: number, action: 'submit' | 'confirm' | 'cancel') =>
      req<PurchaseOrder>(`/api/procurement/${id}/${action}`, { method: 'POST', body: {} }),
    receivePo: (id: number, receipts: Record<number, number>, warehouseId?: number) =>
      req<PurchaseOrder>(`/api/procurement/${id}/receive`, { method: 'POST', body: { receipts, warehouse_id: warehouseId ?? null } }),

    // ---- warehouse / fulfillment (§22) ----
    warehouses: () => req<WarehouseInfo[]>('/api/warehouse'),
    createWarehouse: (body: { name: string; city?: string; country?: string; address?: string; is_default?: boolean }) =>
      req<WarehouseInfo>('/api/warehouse', { method: 'POST', body }),
    stockOverview: (params?: { warehouse_id?: number; product_id?: number }) =>
      req<StockRow[]>('/api/warehouse/overview', { params }),
    stockMovements: (params?: { warehouse_id?: number; product_id?: number; movement_type?: string; limit?: number }) =>
      req<StockMovementRow[]>('/api/warehouse/movements', { params }),
    adjustStock: (body: { warehouse_id: number; product_id: number; delta: number; reason: string }) =>
      req<{ ok: boolean }>('/api/warehouse/adjust', { method: 'POST', body }),
    transferStock: (body: { from_warehouse_id: number; to_warehouse_id: number; product_id: number; qty: number }) =>
      req<{ ok: boolean }>('/api/warehouse/transfer', { method: 'POST', body }),
    pickWaves: (status?: string) =>
      req<PickWave[]>('/api/warehouse/waves', { params: status ? { status } : {} }),
    createPickWave: (body: { order_ids: number[]; warehouse_id?: number; note?: string }) =>
      req<PickWave>('/api/warehouse/waves', { method: 'POST', body }),
    waveAction: (id: number, action: 'pick' | 'pack' | 'complete' | 'cancel') =>
      req<PickWave>(`/api/warehouse/waves/${id}/${action}`, { method: 'POST', body: {} }),

    orders: (params?: { status?: string }) => req<Order[]>('/api/orders', { params }),
    order: (id: number) => req<OrderDetail>(`/api/orders/${id}`),
    createOrder: (body: Record<string, unknown>) =>
      req<{ id: number }>('/api/orders', { method: 'POST', body }),
    transitionOrder: (id: number, status: string) =>
      req<OrderDetail>(`/api/orders/${id}/transition`, { method: 'POST', body: { status } }),

    shipments: () => req<Shipment[]>('/api/shipments'),
    shipment: (id: number) => req<Shipment>(`/api/shipments/${id}`),
    createShipmentForOrder: (orderId: number) =>
      req<Shipment>(`/api/shipments/create-for-order/${orderId}`, { method: 'POST' }),
    addTrackingEvent: (shipmentId: number, body: { code: string; location?: string; description?: string }) =>
      req<Shipment>(`/api/shipments/${shipmentId}/events`, { method: 'POST', body }),

    payments: (params?: { method?: string }) => req<Payment[]>('/api/payments', { params }),
    capturePayment: (id: number) =>
      req<Payment>(`/api/payments/${id}/capture`, { method: 'POST', body: {} }),

    ledger: () => req<{ entries: LedgerEntry[]; totals_by_type: Record<string, number> }>('/api/finance/ledger'),
    events: (name?: string) => req<DomainEvent[]>('/api/events', { params: name ? { name } : {} }),

    // ---- landing page engine (§15) ----
    landingPages: () => req<LandingPageSummary[]>('/api/landing-pages'),
    landingPage: (id: number) => req<LandingPage>(`/api/landing-pages/${id}`),
    blockRegistry: () => req<BlockTypeDef[]>('/api/landing-pages/blocks'),
    createLandingPage: (body: Record<string, unknown>) =>
      req<LandingPage>('/api/landing-pages', { method: 'POST', body }),
    patchLandingPage: (id: number, body: Record<string, unknown>) =>
      req<LandingPage>(`/api/landing-pages/${id}`, { method: 'PATCH', body }),
    publishLandingPage: (id: number) =>
      req<LandingPage>(`/api/landing-pages/${id}/publish`, { method: 'POST', body: {} }),
    unpublishLandingPage: (id: number) =>
      req<LandingPage>(`/api/landing-pages/${id}/unpublish`, { method: 'POST', body: {} }),
    deleteLandingPage: (id: number) =>
      req<void>(`/api/landing-pages/${id}`, { method: 'DELETE' }),

    // ---- §15 versioning + scheduling ----
    lpVersions: (id: number) => req<LpVersion[]>(`/api/landing-pages/${id}/versions`),
    restoreLpVersion: (id: number, versionNo: number, publish = false) =>
      req<LandingPage>(`/api/landing-pages/${id}/versions/${versionNo}/restore`, { method: 'POST', body: { publish } }),
    scheduleLandingPage: (id: number, publishAt: string) =>
      req<LandingPage>(`/api/landing-pages/${id}/schedule`, { method: 'POST', body: { publish_at: publishAt } }),
    cancelLpSchedule: (id: number) =>
      req<LandingPage>(`/api/landing-pages/${id}/schedule`, { method: 'DELETE' }),

    // ---- §24 COD remittance register ----
    codRegisters: (status?: string) =>
      req<CodRegister[]>('/api/cod/registers', { params: status ? { status } : {} }),
    codRegister: (id: number) => req<CodRegister>(`/api/cod/registers/${id}`),
    openCodRegister: (carrier: string, note = '') =>
      req<CodRegister>('/api/cod/registers', { method: 'POST', body: { carrier, note } }),
    submitCodRegister: (id: number, remittedAmount: number, reference = '') =>
      req<CodRegister>(`/api/cod/registers/${id}/submit`, { method: 'POST', body: { remitted_amount: remittedAmount, reference } }),
    reconcileCodRegister: (id: number, counts: { line_id: number; counted_amount: number }[] = []) =>
      req<CodRegister>(`/api/cod/registers/${id}/reconcile`, { method: 'POST', body: { counts } }),
    cancelCodRegister: (id: number) =>
      req<CodRegister>(`/api/cod/registers/${id}/cancel`, { method: 'POST', body: {} }),
    codSummary: () => req<CodSummary>('/api/cod/summary'),

    // ---- public storefront (§14, no auth) ----
    publicStore: () => req<PublicStore | null>('/api/public/store'),
    publicHome: (currency = 'NGN') => req<PublicHome>('/api/public/home', { params: { currency } }),
    publicProducts: (currency = 'NGN') => req<PublicProduct[]>('/api/public/products', { params: { currency } }),
    publicProduct: (slug: string, currency = 'NGN') => req<PublicProductDetail>(`/api/public/products/${slug}`, { params: { currency } }),
    publicPricing: () => req<PublicPricing>('/api/public/pricing'),
    publicFx: (quote = 'USD') => req<{ base: string; rate: number; source: string }>('/api/public/fx', { params: { quote } }),
    publicPage: (slug: string) => req<PublicPage>(`/api/public/pages/${slug}`),
    submitOrderIntent: (body: { product_slug: string; contact_name: string; contact_phone: string; qty: number; note?: string; utm?: Record<string, string> }) =>
      req<{ ok: boolean; lead_id: number; message: string }>('/api/public/leads', { method: 'POST', body }),

    // ---- §14 checkout (public, no auth) ----
    checkoutQuote: (body: { items: { product_slug: string; qty: number }[]; delivery_fee?: number }) =>
      req<CheckoutQuote>('/api/public/checkout/quote', { method: 'POST', body }),
    checkout: (body: {
      items: { product_slug: string; qty: number; variant_id?: number }[]
      full_name: string
      contact_phone: string
      address: string
      city: string
      state: string
      payment_method: 'cod' | 'online_transfer'
      note?: string
      utm?: Record<string, string>
    }) => req<CheckoutResult>('/api/public/checkout', { method: 'POST', body }),
    publicOrderStatus: (orderId: number, phone: string) =>
      req<PublicOrderStatus>(`/api/public/orders/${orderId}`, { params: { phone } }),

    // ---- §8-11 Marketstore + sourcing (corridor) ----
    marketProducts: (params?: { category?: string; industry?: string; q?: string }) =>
      req<MarketListing[]>('/api/market/products', { params }),
    marketProduct: (id: number) => req<MarketListing>(`/api/market/products/${id}`),
    sourcingOrders: () => req<SourcingOrder[]>('/api/market/sourcing-orders'),
    createSourcingOrder: (body: { supplier_product_id: number; qty: number; agent_org_id?: number | null; note?: string; dest_name?: string; dest_phone?: string; dest_address?: string; dest_city?: string }) =>
      req<SourcingOrder>('/api/market/sourcing-orders', { method: 'POST', body }),
    paySourcingOrder: (id: number, method = 'online_transfer') =>
      req<SourcingOrder>(`/api/market/sourcing-orders/${id}/pay`, { method: 'POST', body: { method } }),
    cancelSourcingOrder: (id: number) =>
      req<SourcingOrder>(`/api/market/sourcing-orders/${id}/cancel`, { method: 'POST', body: {} }),
    receiveSourcingOrder: (id: number, warehouseId?: number) =>
      req<SourcingOrder>(`/api/market/sourcing-orders/${id}/receive`, { method: 'POST', body: { warehouse_id: warehouseId ?? null } }),

    // ---- §8 supplier portal (role=supplier) ----
    portalProducts: () => req<SupplierProduct[]>('/api/market/portal/products'),
    portalUploadProduct: (body: Record<string, unknown>) =>
      req<SupplierProduct>('/api/market/portal/products', { method: 'POST', body }),
    portalPatchProduct: (id: number, body: Record<string, unknown>) =>
      req<SupplierProduct>(`/api/market/portal/products/${id}`, { method: 'PATCH', body }),
    portalSubmitProduct: (id: number) =>
      req<SupplierProduct>(`/api/market/portal/products/${id}/submit`, { method: 'POST', body: {} }),
    portalOrders: () => req<SourcingSupplierView[]>('/api/market/portal/orders'),
    portalAcceptOrder: (id: number) =>
      req<SourcingSupplierView>(`/api/market/portal/orders/${id}/accept`, { method: 'POST', body: {} }),
    portalAddTracking: (id: number, body: { code: string; location?: string; description?: string }) =>
      req<SourcingSupplierView>(`/api/market/portal/orders/${id}/tracking`, { method: 'POST', body }),

    // ---- §8 review gate + provisioning (platform) ----
    adminMarketProducts: (status?: string) =>
      req<SupplierProduct[]>('/api/market/admin/products', { params: status ? { status } : {} }),
    reviewMarketProduct: (id: number, decision: 'approve' | 'reject', notes = '') =>
      req<SupplierProduct>(`/api/market/admin/products/${id}/review`, { method: 'POST', body: { decision, notes } }),
    publishMarketProduct: (id: number) =>
      req<SupplierProduct>(`/api/market/admin/products/${id}/publish`, { method: 'POST', body: {} }),
    createSupplierOrg: (body: { company: string; contact_name: string; email: string; password: string; city?: string; country?: string }) =>
      req<{ org: { id: number; name: string }; supplier_id: number }>('/api/market/admin/supplier-orgs', { method: 'POST', body }),

    // ---- AGM: agents (§20-24) ----
    agentDirectory: () => req<AgentCard[]>('/api/agm/directory'),
    agentLinks: () => req<AgentLinkRow[]>('/api/agm/links'),
    addAgentLink: (agentOrgId: number) =>
      req<{ ok: boolean }>(`/api/agm/links`, { method: 'POST', body: { agent_org_id: agentOrgId } }),
    markOrderForAgent: (orderId: number, agentOrgId: number) =>
      req<AgentOrder>(`/api/agm/orders/${orderId}/mark`, { method: 'POST', body: { agent_org_id: agentOrgId } }),
    vendorAgentOrders: () => req<AgentOrder[]>('/api/agm/vendor-orders'),

    // ---- AGM console (role=agm) ----
    agmOverview: () => req<AgmOverview>('/api/agm/overview'),
    agmWarehouses: () => req<AgentWarehouseRow[]>('/api/agm/warehouses'),
    agmCreateWarehouse: (body: { name: string; city?: string; country?: string; address?: string; is_default?: boolean }) =>
      req<{ id: number; code: string; name: string }>('/api/agm/warehouses', { method: 'POST', body }),
    agmStock: (warehouseId?: number) =>
      req<AgentStockRow[]>('/api/agm/stock', { params: warehouseId ? { warehouse_id: warehouseId } : {} }),
    agmReceiveSourcing: (soId: number, warehouseId?: number) =>
      req<{ ok: boolean; warehouse: string; qty: number }>(`/api/agm/receive-sourcing/${soId}`, { method: 'POST', body: { warehouse_id: warehouseId ?? null } }),
    agmOrders: (status?: string) =>
      req<AgentOrder[]>('/api/agm/orders', { params: status ? { status } : {} }),
    agmOrderAction: (id: number, body: { action: string; cod_collected?: number | null; note?: string; failed_reason?: string }) =>
      req<AgentOrder>(`/api/agm/orders/${id}/action`, { method: 'POST', body }),
    agmRemittances: () => req<AgentRemittance[]>('/api/agm/remittances'),
    agmCreateRemittance: (body?: { vendor_org_id?: number | null; agent_order_ids?: number[]; reference?: string }) =>
      req<AgentRemittance>('/api/agm/remittances', { method: 'POST', body: body ?? {} }),
    agmRemit: (id: number, reference = '') =>
      req<AgentRemittance>(`/api/agm/remittances/${id}/remit`, { method: 'POST', body: { reference } }),
    agmReconcile: (id: number, counted: Record<string, number>) =>
      req<AgentRemittance>(`/api/agm/remittances/${id}/reconcile`, { method: 'POST', body: { counted } }),
  }
}

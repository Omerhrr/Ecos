/**
 * Ecos API client + shared types.
 * The Nitro dev proxy forwards /api/** to FastAPI on :8000.
 */

export interface PricingInfo {
  ecos_price_ngn: number
  fx_rate: number
  components: Record<string, number>
}

export interface Product {
  id: number
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
  specs: Record<string, unknown>
  pricing: PricingInfo
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

export function useApi() {
  return {
    health: () => $fetch<{ status: string; system: string }>('/api/health'),
    summary: () => $fetch<Summary>('/api/analytics/summary'),
    funnel: () => $fetch<Funnel>('/api/analytics/funnel'),
    topProducts: () => $fetch<TopProduct[]>('/api/analytics/top-products'),

    suppliers: () => $fetch<Supplier[]>('/api/suppliers'),
    stores: () => $fetch<Store[]>('/api/stores'),

    products: (params?: { status?: string }) => $fetch<Product[]>('/api/products', { params }),
    createProduct: (body: Partial<Product>) =>
      $fetch<Product>('/api/products', { method: 'POST', body }),
    patchProduct: (id: number, body: Record<string, unknown>) =>
      $fetch<Product>(`/api/products/${id}`, { method: 'PATCH', body }),

    leads: () => $fetch<Lead[]>('/api/leads'),
    createLead: (body: Record<string, unknown>) =>
      $fetch<Lead>('/api/leads', { method: 'POST', body }),
    patchLead: (id: number, body: Record<string, unknown>) =>
      $fetch<Lead>(`/api/leads/${id}`, { method: 'PATCH', body }),
    convertLead: (id: number) =>
      $fetch<{ order_id: number }>(`/api/leads/${id}/convert`, { method: 'POST' }),

    orders: (params?: { status?: string }) => $fetch<Order[]>('/api/orders', { params }),
    order: (id: number) => $fetch<OrderDetail>(`/api/orders/${id}`),
    createOrder: (body: Record<string, unknown>) =>
      $fetch<{ id: number }>('/api/orders', { method: 'POST', body }),
    transitionOrder: (id: number, status: string) =>
      $fetch<OrderDetail>(`/api/orders/${id}/transition`, { method: 'POST', body: { status } }),

    shipments: () => $fetch<Shipment[]>('/api/shipments'),
    shipment: (id: number) => $fetch<Shipment>(`/api/shipments/${id}`),
    createShipmentForOrder: (orderId: number) =>
      $fetch<Shipment>(`/api/shipments/create-for-order/${orderId}`, { method: 'POST' }),
    addTrackingEvent: (shipmentId: number, body: { code: string; location?: string; description?: string }) =>
      $fetch<Shipment>(`/api/shipments/${shipmentId}/events`, { method: 'POST', body }),

    payments: (params?: { method?: string }) => $fetch<Payment[]>('/api/payments', { params }),
    capturePayment: (id: number) =>
      $fetch<Payment>(`/api/payments/${id}/capture`, { method: 'POST', body: {} }),

    ledger: () => $fetch<{ entries: LedgerEntry[]; totals_by_type: Record<string, number> }>('/api/finance/ledger'),
    events: (name?: string) => $fetch<DomainEvent[]>('/api/events', { params: name ? { name } : {} }),
  }
}

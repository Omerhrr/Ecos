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
}

export interface LandingPage extends LandingPageSummary {
  blocks: LandingPageBlock[]
  theme: { primary?: string }
  seo: { title?: string; description?: string; og_image?: string }
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

const PUBLIC_PATHS = ['/', '/login', '/lp', '/products']

function isPublicPath(path: string) {
  if (path === '/' || path === '/login') return true
  return PUBLIC_PATHS.some(p => p !== '/' && path.startsWith(`${p}/`))
}

export function useApi() {
  const req = $fetch.create({
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
    onResponseError({ response }) {
      if (
        response.status === 401
        && import.meta.client
        && !isPublicPath(window.location.pathname)
      ) {
        localStorage.removeItem('ecos:token')
        navigateTo('/login')
      }
    },
  })

  return {
    // ---- auth (§43) ----
    login: (email: string, password: string) =>
      req<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } }),
    me: () => req<LoginResponse>('/api/auth/me'),
    createUser: (body: Record<string, unknown>) =>
      req<Record<string, unknown>>('/api/users', { method: 'POST', body }),

    // ---- analytics ----
    summary: () => req<Summary>('/api/analytics/summary'),
    funnel: () => req<Funnel>('/api/analytics/funnel'),
    topProducts: () => req<TopProduct[]>('/api/analytics/top-products'),

    suppliers: () => req<Supplier[]>('/api/suppliers'),
    stores: () => req<Store[]>('/api/stores'),

    products: (params?: { status?: string }) => req<Product[]>('/api/products', { params }),
    createProduct: (body: Partial<Product>) =>
      req<Product>('/api/products', { method: 'POST', body }),
    patchProduct: (id: number, body: Record<string, unknown>) =>
      req<Product>(`/api/products/${id}`, { method: 'PATCH', body }),

    leads: () => req<Lead[]>('/api/leads'),
    createLead: (body: Record<string, unknown>) =>
      req<Lead>('/api/leads', { method: 'POST', body }),
    patchLead: (id: number, body: Record<string, unknown>) =>
      req<Lead>(`/api/leads/${id}`, { method: 'PATCH', body }),
    convertLead: (id: number) =>
      req<{ order_id: number }>(`/api/leads/${id}/convert`, { method: 'POST' }),

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

    // ---- public storefront (§14, no auth) ----
    publicStore: () => req<PublicStore | null>('/api/public/store'),
    publicHome: () => req<PublicHome>('/api/public/home'),
    publicProducts: () => req<PublicProduct[]>('/api/public/products'),
    publicProduct: (slug: string) => req<PublicProductDetail>(`/api/public/products/${slug}`),
    publicPage: (slug: string) => req<PublicPage>(`/api/public/pages/${slug}`),
    submitOrderIntent: (body: { product_slug: string; contact_name: string; contact_phone: string; qty: number; note?: string }) =>
      req<{ ok: boolean; lead_id: number; message: string }>('/api/public/leads', { method: 'POST', body }),
  }
}

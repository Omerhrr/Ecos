<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()
const route = useRoute()
const orderId = computed(() => Number(route.params.id))

const order = ref<OrderDetail | null>(null)
const shipment = ref<Shipment | null>(null)
const payment = ref<Payment | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')

const TRACKING_FLOW = [
  'supplier_processing', 'picked_up', 'origin_warehouse', 'exported',
  'in_transit', 'customs', 'destination_hub', 'local_courier',
  'out_for_delivery', 'delivered',
]

async function load() {
  loading.value = true
  try {
    order.value = await api.order(orderId.value)
    const ships = await $fetch<Shipment[]>('/api/shipments')
    shipment.value = ships.find(s => s.order_id === orderId.value) ?? null
    const pays = await api.payments()
    payment.value = pays.find(p => p.order_id === orderId.value) ?? null
  }
  catch { error.value = 'Order not found' }
  finally { loading.value = false }
}

onMounted(load)

async function run(fn: () => Promise<unknown>) {
  busy.value = true
  error.value = ''
  try { await fn(); await load() }
  catch (e: unknown) {
    const msg = (e as { data?: { detail?: string } })?.data?.detail
    error.value = msg ?? 'Action failed'
  }
  finally { busy.value = false }
}

const nextTrackingCode = computed(() => {
  if (!shipment.value) return null
  const last = shipment.value.timeline.at(-1)?.code
  const idx = last ? TRACKING_FLOW.indexOf(last) : -1
  return idx >= 0 && idx < TRACKING_FLOW.length - 1 ? TRACKING_FLOW[idx + 1] : TRACKING_FLOW[0]
})
</script>

<template>
  <div>
    <div v-if="loading" class="empty">Loading order…</div>
    <template v-else-if="order">
      <div class="page-head">
        <div>
          <h1>Order #{{ order.id }}</h1>
          <div class="sub">
            {{ order.store_name }} · {{ date(order.created_at) }}
            <StatusBadge :status="order.status" />
            <StatusBadge :status="order.payment_status" />
          </div>
        </div>
        <div class="row">
          <button
            v-for="t in order.allowed_transitions" :key="t" class="ghost"
            :disabled="busy" @click="run(() => api.transitionOrder(order.id, t))"
          >
            → {{ t.replaceAll('_', ' ') }}
          </button>
        </div>
      </div>

      <div v-if="error" class="card" style="border-color:#fecaca;color:#991b1b;margin-bottom:1rem">{{ error }}</div>

      <div class="kpi-grid">
        <KpiCard label="Order total" :value="money(order.total)" :sub="`${order.items.length} item(s)`" />
        <KpiCard label="Payment" :value="order.payment_method.replace('_', ' ')" :sub="order.payment_status" />
        <KpiCard
          label="Shipment"
          :value="shipment ? shipment.status : 'not created'"
          :sub="shipment ? shipment.tracking_code : 'fulfill order first'"
        />
      </div>

      <div class="grid-2">
        <div>
          <div class="card" style="margin-bottom:.9rem">
            <h2 style="margin-bottom:.6rem">Items</h2>
            <table>
              <thead><tr><th>Product</th><th>Qty</th><th>Unit</th><th>Cost (CNY)</th></tr></thead>
              <tbody>
                <tr v-for="i in order.items" :key="i.id">
                  <td>{{ i.title }}</td>
                  <td>{{ i.qty }}</td>
                  <td>{{ money(i.unit_price) }}</td>
                  <td class="mono">¥{{ i.supplier_cost_cny }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="card" style="margin-bottom:.9rem">
            <h2 style="margin-bottom:.6rem">Customer</h2>
            <div v-if="order.customer">
              <strong>{{ order.customer.full_name }}</strong>
              <div class="mono muted">{{ order.customer.phone }}</div>
              <div class="muted" style="margin-top:.3rem">
                {{ order.customer.address }}, {{ order.customer.city }}, {{ order.customer.state }}, {{ order.customer.country }}
              </div>
            </div>
          </div>

          <div class="card">
            <h2 style="margin-bottom:.6rem">Payment</h2>
            <template v-if="payment">
              <div class="spread">
                <span>
                  <StatusBadge :status="payment.status" />
                  <span class="muted" style="margin-left:.5rem">{{ payment.method.replace('_', ' ') }} · {{ money(payment.amount) }}</span>
                </span>
                <button
                  v-if="payment.status === 'pending' && order.payment_method !== 'cod'"
                  class="small" :disabled="busy"
                  @click="run(() => api.capturePayment(payment!.id))"
                >
                  Simulate gateway capture
                </button>
              </div>
              <div v-if="payment.reference" class="mono muted" style="margin-top:.4rem;font-size:.74rem">ref {{ payment.reference }}</div>
              <div class="muted" style="font-size:.74rem;margin-top:.3rem">
                COD payments auto-collect when the shipment is delivered (§24).
              </div>
            </template>
            <div v-else class="empty">No payment record</div>
          </div>
        </div>

        <div class="card">
          <div class="spread" style="margin-bottom:.8rem">
            <h2>Tracking</h2>
            <button
              v-if="!shipment && ['confirmed', 'processing'].includes(order.status)"
              class="small" :disabled="busy"
              @click="run(() => api.createShipmentForOrder(order.id))"
            >
              Fulfill → create shipment
            </button>
          </div>

          <template v-if="shipment">
            <div class="mono muted" style="font-size:.75rem;margin-bottom:.8rem">
              {{ shipment.carrier }} · {{ shipment.origin_country }} → {{ shipment.destination_country }}
            </div>
            <ul class="timeline">
              <li v-for="ev in shipment.timeline" :key="ev.id">
                <div class="tl-code">{{ ev.code.replaceAll('_', ' ') }}</div>
                <div class="tl-meta">{{ ev.location }} · {{ date(ev.occurred_at) }}</div>
              </li>
            </ul>
            <div
              v-if="nextTrackingCode && !['delivered', 'returned'].includes(shipment.status)"
              style="margin-top:1rem"
            >
              <button
                class="ghost small" :disabled="busy"
                @click="run(() => api.addTrackingEvent(shipment!.id, { code: nextTrackingCode!, location: 'network update' }))"
              >
                Record: {{ nextTrackingCode.replaceAll('_', ' ') }}
              </button>
            </div>
          </template>
          <div v-else class="empty">
            No shipment yet — confirm the order, then fulfill it to start the logistics flow (§20).
          </div>
        </div>
      </div>
    </template>
    <div v-else class="empty">{{ error }}</div>
  </div>
</template>

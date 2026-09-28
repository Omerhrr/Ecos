<script setup lang="ts">
const api = useApi()
const { money, pct } = useFormat()

const summary = ref<Summary | null>(null)
const funnel = ref<Funnel | null>(null)
const topProducts = ref<TopProduct[]>([])
const orders = ref<Order[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const [s, f, tp, o] = await Promise.all([
      api.summary(), api.funnel(), api.topProducts(),
      api.orders(),
    ])
    summary.value = s
    funnel.value = f
    topProducts.value = tp
    orders.value = o.slice(0, 8)
  }
  catch {
    error.value = 'Backend unreachable — is uvicorn running on :8000?'
  }
  finally {
    loading.value = false
  }
})

const maxFunnel = computed(() =>
  Math.max(1, ...(funnel.value?.pipeline.map(p => p.count) ?? [])),
)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Command Center</h1>
        <div class="sub">Live view of the commerce network — China → Nigeria corridor</div>
      </div>
    </div>

    <div v-if="error" class="card" style="border-color:#fecaca;color:#991b1b">{{ error }}</div>
    <div v-else-if="loading" class="empty">Loading network state…</div>

    <template v-else-if="summary">
      <div class="kpi-grid">
        <KpiCard label="Collected revenue" :value="money(summary.revenue_ngn)" :sub="`${summary.orders_delivered} delivered`" />
        <KpiCard label="COD pending" :value="money(summary.cod_pending_ngn)" sub="collects on delivery" />
        <KpiCard label="Orders" :value="String(summary.orders_total)" :sub="`${summary.orders_in_flight} in flight`" />
        <KpiCard label="Delivery rate" :value="pct(summary.delivery_rate)" :sub="`${summary.orders_problem} problem orders`" />
        <KpiCard label="Avg order value" :value="money(summary.aov_ngn)" sub="per paid order" />
        <KpiCard label="Active leads" :value="String(summary.leads_active)" :sub="`of ${summary.leads_total} total`" />
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="spread" style="margin-bottom:.8rem">
            <h2>Recent orders</h2>
            <NuxtLink to="/orders"><button class="ghost small">All orders</button></NuxtLink>
          </div>
          <table>
            <thead>
              <tr><th>#</th><th>Customer</th><th>Total</th><th>Payment</th><th>Status</th></tr>
            </thead>
            <tbody>
              <tr v-for="o in orders" :key="o.id">
                <td>
                  <NuxtLink :to="`/orders/${o.id}`" class="mono">#{{ o.id }}</NuxtLink>
                </td>
                <td>{{ o.customer_name }}</td>
                <td>{{ money(o.total) }}</td>
                <td><StatusBadge :status="o.payment_status" /></td>
                <td><StatusBadge :status="o.status" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card">
          <h2 style="margin-bottom:.8rem">Lead pipeline</h2>
          <template v-if="funnel">
            <div v-for="p in funnel.pipeline" :key="p.status" class="funnel-row">
              <div class="fl-label"><StatusBadge :status="p.status" /></div>
              <div class="fl-bar" :style="{ width: `${(p.count / maxFunnel) * 100}%` }"></div>
              <div class="fl-count">{{ p.count }}</div>
            </div>
            <div v-if="funnel.exits.some(e => e.count)" style="margin-top:1rem">
              <div class="muted" style="font-size:.75rem;margin-bottom:.4rem">EXITS</div>
              <div v-for="e in funnel.exits.filter(x => x.count)" :key="e.status" class="funnel-row">
                <div class="fl-label"><StatusBadge :status="e.status" /></div>
                <div class="fl-count">{{ e.count }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <div class="card" style="margin-top:.9rem">
        <h2 style="margin-bottom:.8rem">Top products by revenue</h2>
        <table>
          <thead><tr><th>Product</th><th>Units</th><th>Revenue</th></tr></thead>
          <tbody>
            <tr v-for="p in topProducts" :key="p.product_id">
              <td>{{ p.title }}</td>
              <td>{{ p.units }}</td>
              <td>{{ money(p.revenue_ngn) }}</td>
            </tr>
            <tr v-if="!topProducts.length"><td colspan="3" class="empty">No sales yet</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

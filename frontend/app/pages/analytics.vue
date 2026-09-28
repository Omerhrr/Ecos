<script setup lang="ts">
/**
 * Analytics suites (plan §29) — logistics, financial, product.
 * All figures computed live from domain tables / the immutable ledger.
 */
const api = useApi()
const { money, date } = useFormat()

const tab = ref<'logistics' | 'financial' | 'products'>('financial')
const days = ref(30)
const loading = ref(true)
const logistics = ref<AnalyticsLogistics | null>(null)
const financial = ref<AnalyticsFinancial | null>(null)
const products = ref<AnalyticsProducts | null>(null)

async function load() {
  loading.value = true
  try {
    const [l, f, p] = await Promise.all([
      api.analyticsLogistics(days.value), api.analyticsFinancial(days.value), api.analyticsProducts(days.value),
    ])
    logistics.value = l
    financial.value = f
    products.value = p
  }
  finally { loading.value = false }
}
onMounted(load)
watch(days, load)

const pct = (v: number) => `${(v * 100).toFixed(1)}%`
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Analytics</h1>
        <div class="sub">Three operator suites (§29) — logistics performance, contribution economics, product margin & returns. Computed live from domain data.</div>
      </div>
      <select v-model="days" class="days-select">
        <option :value="7">Last 7 days</option>
        <option :value="30">Last 30 days</option>
        <option :value="90">Last 90 days</option>
      </select>
    </div>

    <div class="tabs">
      <button :class="{ active: tab === 'financial' }" @click="tab = 'financial'">Financial (§26/§57)</button>
      <button :class="{ active: tab === 'logistics' }" @click="tab = 'logistics'">Logistics (§21-23)</button>
      <button :class="{ active: tab === 'products' }" @click="tab = 'products'">Products (§10)</button>
    </div>

    <div v-if="loading" class="empty">Crunching the corridor…</div>

    <!-- FINANCIAL -->
    <div v-else-if="tab === 'financial' && financial">
      <div class="kpis">
        <div class="card pad"><div class="kpi-label">Net revenue</div><div class="kpi-value">{{ money(financial.net_revenue_ngn) }}</div><div class="muted" style="font-size:.74rem">gross {{ money(financial.gross_revenue_ngn) }} − refunds {{ money(Math.abs(financial.refunds_ngn)) }}</div></div>
        <div class="card pad"><div class="kpi-label">Contribution</div><div class="kpi-value" :class="financial.contribution_ngn > 0 ? 'pos' : 'neg'">{{ money(financial.contribution_ngn) }}</div><div class="muted" style="font-size:.74rem">{{ pct(financial.contribution_margin_pct) }} of net — after all waterfall costs</div></div>
        <div class="card pad"><div class="kpi-label">Operator economics</div><div class="kpi-value pos">{{ money(Math.abs(financial.operator_economics_ngn)) }}</div><div class="muted" style="font-size:.74rem">owed to the operator · Luxeen took {{ money(financial.luxeen_economics_ngn) }}</div></div>
        <div class="card pad"><div class="kpi-label">COD pending</div><div class="kpi-value warn">{{ money(financial.cod_pending_ngn) }}</div><div class="muted" style="font-size:.74rem">collected {{ money(financial.cod_collected_ngn) }} this window</div></div>
      </div>
      <div class="grid2">
        <div class="card pad">
          <h3>Cost waterfall (ledger-derived, window {{ financial.window_days }}d)</h3>
          <table>
            <tbody>
              <tr><td>Supplier payables</td><td class="mono neg">{{ money(-financial.supplier_cost_ngn) }}</td></tr>
              <tr><td>Logistics</td><td class="mono neg">{{ money(-financial.logistics_cost_ngn) }}</td></tr>
              <tr><td>Payment processing</td><td class="mono neg">{{ money(-financial.payment_cost_ngn) }}</td></tr>
              <tr><td>Luxeen economics</td><td class="mono neg">{{ money(-financial.luxeen_economics_ngn) }}</td></tr>
              <tr class="total-row"><td><b>Contribution</b></td><td class="mono"><b :class="financial.contribution_ngn > 0 ? 'pos' : 'neg'">{{ money(financial.contribution_ngn) }}</b></td></tr>
            </tbody>
          </table>
          <div class="muted" style="font-size:.76rem;margin-top:.5rem">Every number traces to immutable ledger entries (§26/§45) — nothing here is a mutable balance.</div>
        </div>
        <div class="card pad">
          <h3>Settlement obligations</h3>
          <div class="oblig">
            <div class="kpi-value warn">{{ money(financial.unsettled_obligations.amount) }}</div>
            <div class="muted" style="font-size:.78rem">{{ financial.unsettled_obligations.entries }} unsettled payable entries across {{ financial.unsettled_obligations.lines.length }} counterparty bucket(s)</div>
          </div>
          <table v-if="financial.unsettled_obligations.lines.length">
            <thead><tr><th>Counterparty</th><th>Entries</th><th style="text-align:right">Amount</th></tr></thead>
            <tbody>
              <tr v-for="l in financial.unsettled_obligations.lines" :key="l.counterparty">
                <td style="font-size:.78rem">{{ l.counterparty }}</td>
                <td class="mono">{{ l.entry_count }}</td>
                <td class="mono" style="text-align:right">{{ money(l.amount) }}</td>
              </tr>
            </tbody>
          </table>
          <NuxtLink to="/settlements" class="muted" style="font-size:.78rem">Open Settlements →</NuxtLink>
        </div>
      </div>
    </div>

    <!-- LOGISTICS -->
    <div v-else-if="tab === 'logistics' && logistics">
      <div class="kpis">
        <div class="card pad"><div class="kpi-label">Shipments ({{ logistics.window_days }}d)</div><div class="kpi-value">{{ logistics.shipments_total }}</div><div class="muted" style="font-size:.74rem">{{ logistics.shipments_delivered }} delivered · {{ logistics.shipments_active }} active</div></div>
        <div class="card pad"><div class="kpi-label">Avg door-to-door</div><div class="kpi-value">{{ logistics.avg_transit_hours != null ? `${logistics.avg_transit_hours}h` : '—' }}</div><div class="muted" style="font-size:.74rem">created → delivered on completed runs</div></div>
        <div class="card pad"><div class="kpi-label">Stalled &gt; 48h</div><div class="kpi-value" :class="logistics.stalled_over_48h.length ? 'neg' : 'pos'">{{ logistics.stalled_over_48h.length }}</div><div class="muted" style="font-size:.74rem">no checkpoint advance — escalate these</div></div>
        <div class="card pad"><div class="kpi-label">Checkpoints</div><div class="kpi-value">{{ logistics.checkpoint_total }}</div><div class="muted" style="font-size:.74rem">{{ logistics.reverse_checkpoints }} on reverse (return) legs</div></div>
      </div>
      <div class="grid2">
        <div class="card pad">
          <h3>Carrier leaderboard</h3>
          <table>
            <thead><tr><th>Carrier</th><th>Shipments</th><th>Delivered</th><th>Share</th><th>Active</th></tr></thead>
            <tbody>
              <tr v-for="c in logistics.carriers" :key="c.carrier">
                <td><b>{{ c.carrier }}</b></td>
                <td class="mono">{{ c.shipments }}</td>
                <td class="mono">{{ c.delivered }}</td>
                <td class="mono">{{ pct(c.delivered_share) }}</td>
                <td class="mono">{{ c.active }}</td>
              </tr>
              <tr v-if="!logistics.carriers.length"><td colspan="5" class="empty">No shipments in this window</td></tr>
            </tbody>
          </table>
        </div>
        <div class="card pad">
          <h3>Needs attention (stalled lanes)</h3>
          <table v-if="logistics.stalled_over_48h.length">
            <thead><tr><th>Tracking</th><th>Order</th><th>Last checkpoint</th></tr></thead>
            <tbody>
              <tr v-for="s in logistics.stalled_over_48h" :key="s.shipment_id">
                <td class="mono" style="font-size:.76rem">{{ s.tracking_code }}</td>
                <td class="mono">#{{ s.order_id }}</td>
                <td class="muted">{{ s.last_checkpoint || 'none yet' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">Every active shipment has a fresh checkpoint in the last 48h. Route Guard (AI Harness) can watch these for you.</div>
        </div>
      </div>
    </div>

    <!-- PRODUCTS -->
    <div v-else-if="tab === 'products' && products">
      <div class="kpis">
        <div class="card pad"><div class="kpi-label">SKUs sold</div><div class="kpi-value">{{ products.products.length }}</div><div class="muted" style="font-size:.74rem">catalog: {{ products.catalog_active }} active / {{ products.catalog_total }} total</div></div>
        <div class="card pad"><div class="kpi-label">Revenue ({{ products.window_days }}d)</div><div class="kpi-value">{{ money(products.products.reduce((s, p) => s + p.revenue_ngn, 0)) }}</div></div>
        <div class="card pad"><div class="kpi-label">Gross margin</div><div class="kpi-value pos">{{ money(products.products.reduce((s, p) => s + p.gross_margin_ngn, 0)) }}</div><div class="muted" style="font-size:.74rem">revenue − supplier cost (CNY @ corridor FX)</div></div>
        <div class="card pad"><div class="kpi-label">Returns</div><div class="kpi-value warn">{{ products.products.reduce((s, p) => s + p.return_units, 0) }} units</div><div class="muted" style="font-size:.74rem">RMA-linked, this window</div></div>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>SKU</th><th>Units</th><th>Revenue</th><th>Margin / unit</th><th>Return rate</th><th>Stock</th><th>Velocity</th><th>Cover</th></tr></thead>
          <tbody>
            <tr v-for="p in products.products" :key="p.product_id">
              <td><b>{{ p.title }}</b></td>
              <td class="mono">{{ p.units_sold }}</td>
              <td class="mono">{{ money(p.revenue_ngn) }}</td>
              <td class="mono" :class="p.margin_per_unit_ngn > 0 ? 'pos' : 'neg'">{{ money(p.margin_per_unit_ngn) }}</td>
              <td class="mono" :class="p.return_rate > 0.15 ? 'neg' : ''">{{ pct(p.return_rate) }}</td>
              <td class="mono" :class="p.stock_on_hand < 20 ? 'warn-text' : ''">{{ p.stock_on_hand }}</td>
              <td class="mono">{{ p.weekly_velocity }}/wk</td>
              <td class="mono" :class="p.weeks_of_cover != null && p.weeks_of_cover < 2 ? 'neg' : ''">{{ p.weeks_of_cover != null ? `${p.weeks_of_cover}w` : '—' }}</td>
            </tr>
            <tr v-if="!products.products.length"><td colspan="8" class="empty">No sales in this window</td></tr>
          </tbody>
        </table>
      </div>
      <div v-if="products.never_sold_with_stock.length" class="card pad" style="margin-top:1rem">
        <h3>Never sold, holding stock</h3>
        <div class="row" style="flex-wrap:wrap;gap:.4rem">
          <span v-for="p in products.never_sold_with_stock" :key="p.product_id" class="chip">{{ p.title }} · {{ p.stock }} units</span>
        </div>
        <div class="muted" style="font-size:.76rem;margin-top:.4rem">Dead-stock candidates — Market Scout or a promo page can help move them.</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: .4rem; margin: .8rem 0; }
.tabs button { background: transparent; border: 1px solid #26324a; color: #94a3b8; padding: .35rem .9rem; border-radius: 8px; cursor: pointer; font-size: .8rem; }
.tabs button.active { color: #e2e8f0; border-color: #00b374; background: rgba(0, 179, 116, .08); }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin-bottom: 1rem; }
@media (max-width: 1000px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
.card.pad { padding: .9rem 1.1rem; }
.kpi-label { color: #94a3b8; font-size: .74rem; text-transform: uppercase; letter-spacing: .04em; }
.kpi-value { font-size: 1.45rem; font-weight: 700; margin: .15rem 0; }
.pos { color: #00d68f; }
.neg { color: #f87171; }
.warn { color: #eab308; }
.warn-text { color: #eab308; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; align-items: start; }
@media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
.total-row td { border-top: 1px solid #26324a; padding-top: .5rem; }
.oblig { margin-bottom: .7rem; }
.days-select { background: #131b2c; color: #e2e8f0; border: 1px solid #26324a; border-radius: 8px; padding: .4rem .6rem; }
.chip { background: #131b2c; border: 1px solid #26324a; border-radius: 6px; padding: .15rem .5rem; font-size: .74rem; }
</style>

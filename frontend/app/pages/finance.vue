<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const data = ref<{ entries: LedgerEntry[]; totals_by_type: Record<string, number> } | null>(null)
const loading = ref(true)

// §46 multi-currency panel
const fx = ref<FxRateRow[]>([])
const fxEdit = ref<{ base: string; quote: string; rate: string } | null>(null)
const fxError = ref('')
const fxSaved = ref('')

const NET_TYPES = ['customer_payment', 'supplier_payable', 'logistics_cost', 'payment_cost']

async function loadFx() {
  try {
    fx.value = (await api.fxRates()).rates
  }
  catch { /* no finance:read — panel stays hidden */ }
}

onMounted(async () => {
  try { data.value = await api.ledger() }
  finally { loading.value = false }
  await loadFx()
})

const balance = computed(() =>
  data.value ? Object.values(data.value.totals_by_type).reduce((a, b) => a + b, 0) : 0,
)

async function saveRate(row: FxRateRow) {
  if (!fxEdit.value) return
  fxError.value = ''
  fxSaved.value = ''
  try {
    await api.setFxRate({ base: fxEdit.value.base, quote: fxEdit.value.quote, rate: Number(fxEdit.value.rate) })
    fxSaved.value = `${fxEdit.value.base}/${fxEdit.value.quote} updated — public USD prices re-rate instantly`
    fxEdit.value = null
    await loadFx()
  }
  catch (e: unknown) {
    fxError.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Update failed'
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Finance · Ledger</h1>
        <div class="sub">Immutable financial events (§26, §45) — every entry flows from a business event</div>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading ledger…</div>
    <template v-else-if="data">
      <div class="kpi-grid">
        <KpiCard label="Gross collected" :value="money(data.totals_by_type.customer_payment ?? 0)" sub="customer payments" />
        <KpiCard
          label="Supplier payable"
          :value="money(-(data.totals_by_type.supplier_payable ?? 0))"
          sub="owed to suppliers"
        />
        <KpiCard
          label="Luxeen economics"
          :value="money(-(data.totals_by_type.luxeen_economics ?? 0))"
          sub="network margin (§57)"
        />
        <KpiCard
          label="Operator economics"
          :value="money(-(data.totals_by_type.operator_economics ?? 0))"
          sub="operator margin (§57)"
        />
        <KpiCard
          label="Ledger balance"
          :value="money(balance)"
          :sub="Math.abs(balance) < 0.01 ? 'balanced ✓' : 'IMBALANCE'"
        />
      </div>

      <!-- §46 FX rate table -->
      <div class="card" style="padding:1rem 1.2rem;margin:1rem 0">
        <div class="row" style="justify-content:space-between;align-items:baseline">
          <h3 style="margin:0">FX rate table (§46)</h3>
          <span class="muted" style="font-size:.76rem">drives the public USD pricing page + storefront display currency — ledger money stays in its capture currency</span>
        </div>
        <div v-if="fxSaved" class="fx-msg ok">{{ fxSaved }}</div>
        <div v-if="fxError" class="fx-msg err">{{ fxError }}</div>
        <table v-if="fx.length">
          <thead><tr><th>Base</th><th>Quote</th><th>Rate</th><th>Source</th><th>Updated</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in fx" :key="`${r.base}-${r.quote}`">
              <td class="mono">{{ r.base }}</td>
              <td class="mono">{{ r.quote }}</td>
              <td class="mono">
                <template v-if="fxEdit && fxEdit.base === r.base && fxEdit.quote === r.quote">
                  <input v-model="fxEdit.rate" type="number" step="any" min="0" style="width:9rem" class="rate-input">
                </template>
                <template v-else>{{ r.rate }}</template>
              </td>
              <td><span class="badge gray">{{ r.source }}</span></td>
              <td class="muted" style="font-size:.74rem">{{ r.updated_at ? date(r.updated_at) : '—' }}</td>
              <td>
                <template v-if="fxEdit && fxEdit.base === r.base && fxEdit.quote === r.quote">
                  <div class="row" style="gap:.3rem">
                    <button class="small" @click="saveRate(r)">Save</button>
                    <button class="small ghost" @click="fxEdit = null">Cancel</button>
                  </div>
                </template>
                <button v-else class="small ghost" @click="fxEdit = { base: r.base, quote: r.quote, rate: String(r.rate) }">Edit</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">No rates yet</div>
        <NuxtLink to="/pricing" target="_blank" class="muted" style="font-size:.78rem">See the public USD pricing page →</NuxtLink>
      </div>

      <div class="card" style="padding:0">
        <table>
          <thead>
            <tr><th>#</th><th>Order</th><th>Type</th><th>Party</th><th>Amount</th><th>Memo</th><th>When</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in data.entries" :key="e.id">
              <td class="mono">{{ e.id }}</td>
              <td><NuxtLink v-if="e.order_id" :to="`/orders/${e.order_id}`" class="mono">#{{ e.order_id }}</NuxtLink><span v-else class="muted">—</span></td>
              <td><span class="badge" :class="e.amount > 0 ? 'green' : 'gray'">{{ e.entry_type.replaceAll('_', ' ') }}</span></td>
              <td>{{ e.party.replaceAll('_', ' ') }}</td>
              <td :style="{ fontWeight: 700, color: e.amount >= 0 ? '#166534' : '#991b1b' }">
                {{ money(e.amount) }}
              </td>
              <td class="muted" style="font-size:.76rem">{{ e.memo }}</td>
              <td class="muted" style="font-size:.74rem">{{ date(e.created_at) }}</td>
            </tr>
            <tr v-if="!data.entries.length"><td colspan="7" class="empty">No ledger entries yet</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.fx-msg { font-size: .78rem; margin: .5rem 0; }
.fx-msg.ok { color: #00d68f; }
.fx-msg.err { color: #f87171; }
.rate-input { background: #131b2c; color: #e2e8f0; border: 1px solid #26324a; border-radius: 6px; padding: .25rem .4rem; }
</style>

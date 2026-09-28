<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const data = ref<{ entries: LedgerEntry[]; totals_by_type: Record<string, number> } | null>(null)
const loading = ref(true)

const NET_TYPES = ['customer_payment', 'supplier_payable', 'logistics_cost', 'payment_cost']

onMounted(async () => {
  try { data.value = await api.ledger() }
  finally { loading.value = false }
})

const balance = computed(() =>
  data.value ? Object.values(data.value.totals_by_type).reduce((a, b) => a + b, 0) : 0,
)
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

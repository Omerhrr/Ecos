<script setup lang="ts">
const api = useApi()
const { date } = useFormat()

const shipments = ref<Shipment[]>([])
const loading = ref(true)

// §21 freight rate cards
const cards = ref<FreightRateCard[]>([])
const modes = ref<string[]>([])
const cardMsg = ref('')
const cardErr = ref('')
const cardForm = reactive({
  name: '', mode: 'air', origin_country: 'CN', dest_country: 'NG',
  base_fixed_ngn: '1500', per_kg_ngn: '', fuel_surcharge_pct: '0.10',
  customs_pct: '0.05', min_charge_ngn: '0',
  lead_time_days_min: '7', lead_time_days_max: '12',
})

async function loadCards() {
  try {
    const r = await api.freightCards()
    cards.value = r.cards
    modes.value = r.modes
  }
  catch { /* no logistics:read — panel stays hidden */ }
}

async function createCard() {
  cardErr.value = ''; cardMsg.value = ''
  try {
    const c = await api.createFreightCard({
      name: cardForm.name,
      mode: cardForm.mode,
      origin_country: cardForm.origin_country,
      dest_country: cardForm.dest_country,
      base_fixed_ngn: Number(cardForm.base_fixed_ngn) || 0,
      per_kg_ngn: Number(cardForm.per_kg_ngn),
      fuel_surcharge_pct: Number(cardForm.fuel_surcharge_pct) || 0,
      customs_pct: Number(cardForm.customs_pct) || 0,
      min_charge_ngn: Number(cardForm.min_charge_ngn) || 0,
      lead_time_days_min: Number(cardForm.lead_time_days_min) || 0,
      lead_time_days_max: Number(cardForm.lead_time_days_max) || 14,
      active: true,
    })
    cardMsg.value = `Rate card "${c.name}" created — Marketstore quotes and the ledger waterfall now price with it`
    cardForm.name = ''; cardForm.per_kg_ngn = ''
    await loadCards()
  }
  catch (e: unknown) {
    cardErr.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not create the rate card'
  }
}

async function toggleCard(c: FreightRateCard) {
  await api.patchFreightCard(c.id, { active: !c.active })
  await loadCards()
}

onMounted(async () => {
  try { shipments.value = await api.shipments() }
  finally { loading.value = false }
  await loadCards()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Logistics</h1>
        <div class="sub">Normalized shipments across carriers (§22-23) — external tracking mapped to one timeline</div>
      </div>
    </div>

    <!-- §21 freight rate cards -->
    <div class="card" style="padding:1rem 1.2rem;margin-bottom:1rem">
      <div class="row" style="justify-content:space-between;align-items:baseline">
        <h3 style="margin:0">Freight rate cards (§21)</h3>
        <span class="muted" style="font-size:.76rem">per-mode corridor pricing — air is the default quote, sea is offered as an option</span>
      </div>
      <div v-if="cardMsg" class="card-msg ok">{{ cardMsg }}</div>
      <div v-if="cardErr" class="card-msg err">{{ cardErr }}</div>

      <table v-if="cards.length">
        <thead><tr><th>Card</th><th>Lane</th><th>Base</th><th>Per-kg</th><th>Fuel</th><th>Customs</th><th>Min charge</th><th>Lead time</th><th>Active</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in cards" :key="c.id" :style="{ opacity: c.active ? 1 : 0.45 }">
            <td><b>{{ c.name }}</b> <span class="badge" :class="c.mode === 'air' ? 'blue' : c.mode === 'sea' ? 'gray' : 'amber'">{{ c.mode }}</span></td>
            <td class="mono">{{ c.origin_country }}→{{ c.dest_country }}</td>
            <td class="mono">{{ c.base_fixed_ngn ? '₦' + c.base_fixed_ngn.toLocaleString() : '—' }}</td>
            <td class="mono">₦{{ c.effective_per_kg_ngn.toLocaleString() }}<span v-if="c.fuel_surcharge_pct" class="muted" style="font-size:.68rem"> (incl. fuel)</span></td>
            <td class="mono">{{ (c.fuel_surcharge_pct * 100).toFixed(0) }}%</td>
            <td class="mono">{{ (c.customs_pct * 100).toFixed(0) }}%</td>
            <td class="mono">{{ c.min_charge_ngn ? '₦' + c.min_charge_ngn.toLocaleString() : '—' }}</td>
            <td class="mono">{{ c.lead_time_days_min }}-{{ c.lead_time_days_max }}d</td>
            <td><span class="badge" :class="c.active ? 'green' : 'gray'">{{ c.active ? 'active' : 'off' }}</span></td>
            <td><button class="small ghost" @click="toggleCard(c)">{{ c.active ? 'Disable' : 'Enable' }}</button></td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">No rate cards — quotes fall back to the profile's flat per-kg</div>

      <div class="cardform">
        <b style="font-size:.8rem">Add a rate card</b>
        <div class="row" style="gap:.4rem;flex-wrap:wrap;margin-top:.4rem">
          <input v-model="cardForm.name" placeholder="Name — e.g. Express Air CN→NG" style="max-width:14rem">
          <select v-model="cardForm.mode" style="max-width:7rem">
            <option v-for="m in modes" :key="m" :value="m">{{ m }}</option>
          </select>
          <input v-model="cardForm.origin_country" placeholder="CN" style="max-width:4rem">
          <input v-model="cardForm.dest_country" placeholder="NG" style="max-width:4rem">
          <input v-model="cardForm.base_fixed_ngn" type="number" placeholder="base ₦" style="max-width:7rem">
          <input v-model="cardForm.per_kg_ngn" type="number" placeholder="₦/kg" style="max-width:7rem">
          <input v-model="cardForm.fuel_surcharge_pct" type="number" step="0.01" placeholder="fuel %" style="max-width:6rem">
          <input v-model="cardForm.customs_pct" type="number" step="0.01" placeholder="customs %" style="max-width:7rem">
          <input v-model="cardForm.min_charge_ngn" type="number" placeholder="min ₦" style="max-width:7rem">
          <input v-model="cardForm.lead_time_days_min" type="number" placeholder="lead min" style="max-width:6rem">
          <input v-model="cardForm.lead_time_days_max" type="number" placeholder="lead max" style="max-width:6rem">
        </div>
        <button style="margin-top:.5rem" :disabled="!cardForm.name || !cardForm.per_kg_ngn" @click="createCard">Create rate card</button>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading shipments…</div>
    <div v-else class="card" style="padding:0">
      <table>
        <thead>
          <tr><th>Tracking code</th><th>Order</th><th>Recipient</th><th>Route</th><th>Progress</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in shipments" :key="s.id">
            <td class="mono">{{ s.tracking_code }}</td>
            <td><NuxtLink :to="`/orders/${s.order_id}`" class="mono">#{{ s.order_id }}</NuxtLink></td>
            <td>{{ s.recipient_name }}<div class="muted" style="font-size:.72rem">{{ s.recipient_address }}</div></td>
            <td>{{ s.origin_country }} → {{ s.destination_country }}</td>
            <td>
              <div class="muted" style="font-size:.72rem">
                {{ s.timeline.length }} events
                <span v-if="s.timeline.length"> · last: {{ s.timeline.at(-1)?.code.replaceAll('_', ' ') }}</span>
              </div>
            </td>
            <td><StatusBadge :status="s.status" /></td>
          </tr>
          <tr v-if="!shipments.length"><td colspan="6" class="empty">No shipments yet</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.card-msg { font-size: .78rem; margin: .5rem 0; }
.card-msg.ok { color: #00d68f; }
.card-msg.err { color: #f87171; }
.cardform { background: #131b2c; border: 1px solid #26324a; border-radius: 10px; padding: .8rem; margin-top: .8rem; }
</style>

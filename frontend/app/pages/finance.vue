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

// §24 COD remittance register
const cod = ref<CodSummary | null>(null)
const codRegisters = ref<CodRegister[]>([])
const codDetail = ref<CodRegister | null>(null)
const codOpenCarrier = ref('')
const codRemit = ref<{ id: number; amount: string; reference: string } | null>(null)
const codCounts = ref<Record<number, string>>({})
const codMsg = ref('')
const codErr = ref('')

const NET_TYPES = ['customer_payment', 'supplier_payable', 'logistics_cost', 'payment_cost']

async function loadFx() {
  try {
    fx.value = (await api.fxRates()).rates
  }
  catch { /* no finance:read — panel stays hidden */ }
}

async function loadCod() {
  try {
    const [summary, registers] = await Promise.all([
      api.codSummary(),
      api.codRegisters(),
    ])
    cod.value = summary
    codRegisters.value = registers
  }
  catch { /* no finance:read — panel stays hidden */ }
}

async function openCodDetail(r: CodRegister) {
  codDetail.value = await api.codRegister(r.id)
  codCounts.value = {}
}

async function openRegister() {
  if (!codOpenCarrier.value.trim()) return
  codErr.value = ''
  codMsg.value = ''
  try {
    const reg = await api.openCodRegister(codOpenCarrier.value.trim())
    codMsg.value = `Register ${reg.register_code} opened — ${reg.line_count} collection(s), ${money(reg.expected_amount)} expected`
    codOpenCarrier.value = ''
    await loadCod()
  }
  catch (e: unknown) {
    const err = e as { response?: { _data?: { detail?: string } } }
    codErr.value = err.response?._data?.detail ?? 'Could not open the register'
  }
}

async function submitRemit() {
  if (!codRemit.value) return
  codErr.value = ''
  codMsg.value = ''
  try {
    await api.submitCodRegister(codRemit.value.id, Number(codRemit.value.amount) || 0, codRemit.value.reference)
    codMsg.value = 'Remittance recorded — reconcile the cash to close the register'
    codRemit.value = null
    await loadCod()
  }
  catch (e: unknown) {
    const err = e as { response?: { _data?: { detail?: string } } }
    codErr.value = err.response?._data?.detail ?? 'Submit failed'
  }
}

async function reconcile(r: CodRegister) {
  codErr.value = ''
  codMsg.value = ''
  try {
    const counts = Object.entries(codCounts.value).map(([line_id, amount]) => ({
      line_id: Number(line_id),
      counted_amount: Number(amount) || 0,
    }))
    const reg = await api.reconcileCodRegister(r.id, counts)
    codMsg.value = reg.variance_amount === 0
      ? `${reg.register_code} reconciled clean — payments stamped reconciled`
      : `${reg.register_code} closed with variance ${money(reg.variance_amount)} — cod_variance true-up written to the ledger`
    codDetail.value = null
    await loadCod()
  }
  catch (e: unknown) {
    const err = e as { response?: { _data?: { detail?: string } } }
    codErr.value = err.response?._data?.detail ?? 'Reconcile failed'
  }
}

// §57 economics profiles
const profiles = ref<WaterfallProfile[]>([])
const defaults = ref<{ payment_cost_pct: number; luxeen_margin_pct: number; logistics_per_kg_ngn: number } | null>(null)
const profMsg = ref('')
const profErr = ref('')
const profForm = reactive({ name: '', corridor: 'CN>NG', category: '', payment_cost_pct: '', luxeen_margin_pct: '', operator_markup_pct: '', logistics_per_kg_ngn: '', tax_pct: '', priority: 0 })
const previewForm = reactive({ supplier_cost: '200', weight_kg: '1', qty: '1', category: '' })
const previewOut = ref<WaterfallPreview | null>(null)
const previewBusy = ref(false)

async function loadProfiles() {
  try {
    const r = await api.waterfallProfiles()
    profiles.value = r.profiles
    defaults.value = r.defaults
  }
  catch { /* no finance:read — panel stays hidden */ }
}

async function createProfile() {
  profErr.value = ''; profMsg.value = ''
  try {
    const p = await api.createProfile({
      name: profForm.name,
      corridor: profForm.corridor,
      category: profForm.category,
      payment_cost_pct: profForm.payment_cost_pct === '' ? null : Number(profForm.payment_cost_pct),
      luxeen_margin_pct: profForm.luxeen_margin_pct === '' ? null : Number(profForm.luxeen_margin_pct),
      operator_markup_pct: profForm.operator_markup_pct === '' ? null : Number(profForm.operator_markup_pct),
      logistics_per_kg_ngn: profForm.logistics_per_kg_ngn === '' ? null : Number(profForm.logistics_per_kg_ngn),
      tax_pct: profForm.tax_pct === '' ? null : Number(profForm.tax_pct),
      priority: profForm.priority,
      active: true,
    })
    profMsg.value = `Profile "${p.name}" created — the waterfall now uses it wherever it is the most specific match`
    profForm.name = ''; profForm.category = ''
    await loadProfiles()
  }
  catch (e: unknown) {
    profErr.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not create the profile'
  }
}

async function toggleProfile(p: WaterfallProfile) {
  await api.patchProfile(p.id, { active: !p.active })
  await loadProfiles()
}

async function runPreview() {
  previewBusy.value = true
  profErr.value = ''
  try {
    previewOut.value = await api.previewWaterfall({
      supplier_cost: Number(previewForm.supplier_cost),
      weight_kg: Number(previewForm.weight_kg),
      qty: Number(previewForm.qty),
      category: previewForm.category || undefined,
    })
  }
  catch (e: unknown) {
    profErr.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Preview failed'
  }
  finally { previewBusy.value = false }
}

onMounted(async () => {
  try { data.value = await api.ledger() }
  finally { loading.value = false }
  await Promise.all([loadFx(), loadCod(), loadProfiles()])
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

      <!-- §57 economics profiles -->
      <div class="card" style="padding:1rem 1.2rem;margin:1rem 0">
        <div class="row" style="justify-content:space-between;align-items:baseline">
          <h3 style="margin:0">Economics profiles (§57)</h3>
          <span class="muted" style="font-size:.76rem">the waterfall's rates are DATA — most specific active profile wins (org > platform, lane, category)</span>
        </div>
        <div v-if="profMsg" class="fx-msg ok">{{ profMsg }}</div>
        <div v-if="profErr" class="fx-msg err">{{ profErr }}</div>

        <table v-if="profiles.length">
          <thead><tr><th>Profile</th><th>Lane</th><th>Category</th><th>Payment</th><th>Luxeen</th><th>Markup</th><th>Per-kg</th><th>Tax</th><th>Active</th><th></th></tr></thead>
          <tbody>
            <tr v-for="p in profiles" :key="p.id" :style="{ opacity: p.active ? 1 : 0.45 }">
              <td><b>{{ p.name }}</b> <span v-if="p.org_id" class="badge blue" style="font-size:.6rem">org {{ p.org_id }}</span><span v-else class="badge gray" style="font-size:.6rem">platform</span></td>
              <td class="mono">{{ p.corridor || 'any' }}</td>
              <td>{{ p.category || 'any' }}</td>
              <td class="mono">{{ p.payment_cost_pct != null ? (p.payment_cost_pct * 100).toFixed(1) + '%' : '—' }}</td>
              <td class="mono">{{ p.luxeen_margin_pct != null ? (p.luxeen_margin_pct * 100).toFixed(1) + '%' : '—' }}</td>
              <td class="mono">{{ p.operator_markup_pct != null ? (p.operator_markup_pct * 100).toFixed(0) + '%' : '—' }}</td>
              <td class="mono">{{ p.logistics_per_kg_ngn != null ? money(p.logistics_per_kg_ngn) : '—' }}</td>
              <td class="mono">{{ p.tax_pct ? (p.tax_pct * 100).toFixed(1) + '%' : '—' }}</td>
              <td><span class="badge" :class="p.active ? 'green' : 'gray'">{{ p.active ? 'active' : 'off' }}</span></td>
              <td><button class="small ghost" @click="toggleProfile(p)">{{ p.active ? 'Disable' : 'Enable' }}</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="defaults" class="muted" style="font-size:.74rem;margin:.4rem 0">
          Fallback constants when no profile matches: payment {{ (defaults.payment_cost_pct * 100).toFixed(1) }}% · luxeen {{ (defaults.luxeen_margin_pct * 100).toFixed(1) }}% · logistics {{ money(defaults.logistics_per_kg_ngn) }}/kg
        </div>

        <div class="profile-forms">
          <div class="profile-form">
            <b style="font-size:.8rem">New profile</b>
            <div class="row" style="gap:.4rem;flex-wrap:wrap;margin-top:.4rem">
              <input v-model="profForm.name" placeholder="Name — e.g. Electronics premium" style="max-width:14rem">
              <input v-model="profForm.corridor" placeholder="Lane CN>NG" style="max-width:7rem">
              <input v-model="profForm.category" placeholder="Category (blank = any)" style="max-width:10rem">
              <input v-model="profForm.payment_cost_pct" type="number" step="0.001" placeholder="payment %" style="max-width:7rem">
              <input v-model="profForm.luxeen_margin_pct" type="number" step="0.001" placeholder="luxeen %" style="max-width:7rem">
              <input v-model="profForm.operator_markup_pct" type="number" step="0.01" placeholder="markup %" style="max-width:7rem">
              <input v-model="profForm.logistics_per_kg_ngn" type="number" placeholder="₦/kg" style="max-width:7rem">
              <input v-model="profForm.tax_pct" type="number" step="0.001" placeholder="tax %" style="max-width:6rem">
            </div>
            <button style="margin-top:.5rem" :disabled="!profForm.name" @click="createProfile">Create profile</button>
          </div>
          <div class="profile-form">
            <b style="font-size:.8rem">Simulate the waterfall</b>
            <div class="row" style="gap:.4rem;flex-wrap:wrap;margin-top:.4rem">
              <input v-model="previewForm.supplier_cost" type="number" placeholder="cost (CNY)" style="max-width:8rem">
              <input v-model="previewForm.weight_kg" type="number" step="0.1" placeholder="kg" style="max-width:6rem">
              <input v-model="previewForm.qty" type="number" min="1" placeholder="qty" style="max-width:5rem">
              <input v-model="previewForm.category" placeholder="category" style="max-width:10rem">
              <button class="ghost" :disabled="previewBusy" @click="runPreview">Preview</button>
            </div>
            <div v-if="previewOut" class="preview-out">
              <div class="row" style="gap:.4rem;flex-wrap:wrap">
                <span class="badge blue">{{ (previewOut.profile as any).profile_name }}</span>
                <span v-if="previewOut.rate_card" class="badge green">{{ previewOut.rate_card.name }} · {{ previewOut.rate_card.mode }} · {{ previewOut.rate_card.lead_time_days_min }}-{{ previewOut.rate_card.lead_time_days_max }}d</span>
              </div>
              <table style="margin-top:.5rem">
                <tbody>
                  <tr><td>Supplier cost</td><td class="mono">{{ money(previewOut.waterfall.supplier_ngn) }}</td></tr>
                  <tr><td>Freight</td><td class="mono">{{ money(previewOut.waterfall.freight_ngn) }}</td></tr>
                  <tr><td>Customs</td><td class="mono">{{ money(previewOut.waterfall.customs_ngn) }}</td></tr>
                  <tr><td>Payment cost</td><td class="mono">{{ money(previewOut.waterfall.payment_ngn) }}</td></tr>
                  <tr><td>Luxeen economics</td><td class="mono">{{ money(previewOut.waterfall.luxeen_ngn) }}</td></tr>
                  <tr><td><b>Supply total (operator pays)</b></td><td class="mono"><b>{{ money(previewOut.supply_total_ngn) }}</b></td></tr>
                  <tr><td>Ecos price (retail)</td><td class="mono">{{ money(previewOut.ecos_price_ngn) }}</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- §24 COD remittance register -->
      <div class="card" style="padding:1rem 1.2rem;margin:1rem 0">
        <div class="row" style="justify-content:space-between;align-items:baseline">
          <h3 style="margin:0">COD remittance register (§24)</h3>
          <span class="muted" style="font-size:.76rem">courier custody: collected → remitted → counted → ledger true-up on variance</span>
        </div>
        <div v-if="codMsg" class="fx-msg ok">{{ codMsg }}</div>
        <div v-if="codErr" class="fx-msg err">{{ codErr }}</div>

        <div v-if="cod" class="kpi-grid" style="margin:.8rem 0">
          <KpiCard label="Cash with couriers" :value="money(cod.outstanding_total)" :sub="`${cod.outstanding_by_carrier.reduce((a, b) => a + b.outstanding_count, 0)} collection(s) outstanding`" />
          <KpiCard label="Registers reconciled" :value="String(cod.registers_reconciled)" :sub="cod.last_reconciled_at ? `last ${date(cod.last_reconciled_at)}` : 'none yet'" />
        </div>
        <div v-if="cod?.outstanding_by_carrier.length" class="cod-carriers">
          <div v-for="b in cod.outstanding_by_carrier" :key="b.carrier" class="cod-carrier-chip">
            <b>{{ b.carrier }}</b> holds {{ money(b.outstanding_amount) }}
            <span class="muted">({{ b.outstanding_count }})</span>
          </div>
        </div>

        <div class="row" style="margin:.7rem 0;gap:.5rem">
          <input
            v-model="codOpenCarrier"
            placeholder="Courier name — e.g. GIG Logistics"
            style="max-width:20rem"
          >
          <button :disabled="!codOpenCarrier.trim()" @click="openRegister">Open register</button>
        </div>

        <table v-if="codRegisters.length">
          <thead><tr><th>Register</th><th>Carrier</th><th>Status</th><th>Expected</th><th>Remitted</th><th>Counted</th><th>Variance</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in codRegisters" :key="r.id">
              <td class="mono">{{ r.register_code }}</td>
              <td>{{ r.carrier }}</td>
              <td><span class="badge" :class="r.status === 'reconciled' ? 'green' : r.status === 'cancelled' ? 'gray' : 'amber'">{{ r.status }}</span></td>
              <td>{{ money(r.expected_amount) }}</td>
              <td>{{ r.remitted_amount ? money(r.remitted_amount) : '—' }}</td>
              <td>{{ r.status === 'reconciled' ? money(r.counted_amount) : '—' }}</td>
              <td :style="{ fontWeight: 700, color: r.variance_amount < 0 ? '#f87171' : '#00d68f' }">
                {{ r.status === 'reconciled' ? money(r.variance_amount) : '—' }}
              </td>
              <td>
                <div class="row" style="gap:.3rem;justify-content:flex-end">
                  <button class="small ghost" @click="openCodDetail(r)">Lines</button>
                  <button
                    v-if="r.status === 'draft'"
                    class="small"
                    @click="codRemit = { id: r.id, amount: String(r.expected_amount), reference: '' }"
                  >Record remittance</button>
                  <button v-if="r.status === 'remitted'" class="small" @click="reconcile(r)">Reconcile</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">No registers yet — open one after couriers deliver COD orders</div>

        <!-- record remittance inline form -->
        <div v-if="codRemit" class="cod-inline" style="margin-top:.7rem">
          <b>Record remittance for register #{{ codRemit.id }}</b>
          <div class="row" style="margin-top:.4rem;gap:.5rem">
            <input v-model="codRemit.amount" type="number" min="0" step="0.01" placeholder="Remitted amount" style="max-width:12rem">
            <input v-model="codRemit.reference" placeholder="Courier receipt ref (optional)" style="max-width:16rem">
            <button @click="submitRemit">Save remittance</button>
            <button class="ghost" @click="codRemit = null">Cancel</button>
          </div>
        </div>

        <!-- line-level counting -->
        <div v-if="codDetail && codDetail.status === 'remitted'" class="cod-inline" style="margin-top:.7rem">
          <b>Count the cash — {{ codDetail.register_code }} ({{ codDetail.carrier }})</b>
          <table style="margin-top:.5rem">
            <thead><tr><th>Order</th><th>Expected</th><th>Counted</th></tr></thead>
            <tbody>
              <tr v-for="l in codDetail.lines" :key="l.id">
                <td class="mono">{{ l.order_number }}</td>
                <td>{{ money(l.expected_amount) }}</td>
                <td>
                  <input
                    v-model="codCounts[l.id]"
                    type="number"
                    min="0"
                    step="0.01"
                    :placeholder="String(l.expected_amount)"
                    class="rate-input"
                    style="width:9rem"
                  >
                </td>
              </tr>
            </tbody>
          </table>
          <div class="muted" style="font-size:.74rem;margin:.4rem 0">Leave a line blank to accept the expected amount as counted.</div>
          <button @click="reconcile(codDetail)">Reconcile register</button>
        </div>
        <div v-else-if="codDetail" class="cod-inline muted" style="margin-top:.7rem;font-size:.8rem">
          {{ codDetail.register_code }} · {{ codDetail.lines?.length ?? 0 }} line(s) ·
          {{ codDetail.status === 'reconciled' ? `reconciled ${codDetail.reconciled_at ? date(codDetail.reconciled_at) : ''}` : 'not yet remitted' }}
        </div>
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
.cod-carriers { display: flex; flex-wrap: wrap; gap: .5rem; margin: .4rem 0 .7rem; }
.cod-carrier-chip {
  border: 1px solid #26324a; border-radius: 10px; padding: .45rem .7rem; font-size: .8rem;
  background: #131b2c;
}
.cod-inline { border-top: 1px dashed #26324a; padding-top: .7rem; }
.profile-forms { display: grid; grid-template-columns: 1.1fr 1fr; gap: 1rem; border-top: 1px dashed #26324a; padding-top: .8rem; margin-top: .8rem; }
.profile-form { background: #131b2c; border: 1px solid #26324a; border-radius: 10px; padding: .8rem; }
.preview-out table td { padding: .18rem .5rem; font-size: .78rem; }
.preview-out table td:first-child { color: #94a3b8; }
@media (max-width: 1100px) { .profile-forms { grid-template-columns: 1fr; } }
</style>

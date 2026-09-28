<script setup lang="ts">
/**
 * Procurement / Purchase Orders (plan §21-22) — actioning Stock Prophet.
 * The demand forecaster's advisory output lands here as reorder
 * suggestions; converting them raises POs grouped per supplier, and the
 * goods receipt puts the units back into stock.
 */
const api = useApi()
const { date, money } = useFormat()

const suggestions = ref<ReorderSuggestion[]>([])
const pos = ref<PurchaseOrder[]>([])
const loading = ref(true)
const busyId = ref(0)
const suggFilter = ref<'open' | 'converted' | 'dismissed' | 'superseded'>('open')
const poFilter = ref<string>('')
const expanded = ref<number | null>(null)
const error = ref('')
const flash = ref('')

// receive modal state
const receiveTarget = ref<PurchaseOrder | null>(null)
const receiveQty = ref<Record<number, number>>({})

// manual PO modal state
const showCreate = ref(false)
const createSupplierId = ref<number | null>(null)
const createLines = ref<{ product_id: number | null; qty: number }[]>([])
const createNote = ref('')

const suppliers = ref<Supplier[]>([])
const products = ref<Product[]>([])

const RISK_COLOR: Record<string, string> = {
  stockout: '#f87171', watch: '#f59e0b', healthy: '#00b374',
}
const PO_STATUS_COLOR: Record<string, string> = {
  draft: '#eab308', submitted: '#38bdf8', confirmed: '#a78bfa',
  received: '#00b374', cancelled: '#94a3b8',
}
const SUGG_STATUS_COLOR: Record<string, string> = {
  open: '#f59e0b', converted: '#00b374', dismissed: '#94a3b8', superseded: '#64748b',
}

const openSuggestions = computed(() => suggestions.value.filter(s => s.status === 'open'))
const filteredSuggestions = computed(() =>
  suggestions.value.filter(s => s.status === suggFilter.value),
)
const filteredPos = computed(() =>
  poFilter.value ? pos.value.filter(p => p.status === poFilter.value) : pos.value,
)
const totalOpenUnits = computed(() => openSuggestions.value.reduce((a, s) => a + s.suggested_qty, 0))

function say(msg: string) {
  flash.value = msg
  setTimeout(() => { flash.value = '' }, 2500)
}

async function load() {
  loading.value = true
  try {
    const [s, p] = await Promise.all([
      api.reorderSuggestions(),
      api.purchaseOrders(),
    ])
    suggestions.value = s
    pos.value = p
  }
  finally { loading.value = false }
}
onMounted(async () => {
  const [sup, prd] = await Promise.all([api.suppliers(), api.products({ status: 'active' })])
  suppliers.value = sup
  products.value = prd
  await load()
})

async function refreshFromProphet() {
  error.value = ''
  try {
    const r = await api.refreshSuggestions()
    say(`Stock Prophet run #${r.run_id}: ${r.open_suggestions} open suggestion(s)`)
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Refresh failed'
  }
}

async function convertAll() {
  error.value = ''
  try {
    const created = await api.createPoFromSuggestions({ suggestion_ids: [] })
    say(`${created.length} PO(s) raised from open suggestions`)
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Convert failed'
  }
}

async function convertOne(s: ReorderSuggestion) {
  error.value = ''
  try {
    await api.createPoFromSuggestions({ suggestion_ids: [s.id] })
    say(`PO raised for ${s.product_title}`)
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Convert failed'
  }
}

async function dismiss(s: ReorderSuggestion) {
  await api.dismissSuggestion(s.id)
  await load()
}

async function poAct(po: PurchaseOrder, action: 'submit' | 'confirm' | 'cancel') {
  busyId.value = po.id
  error.value = ''
  try {
    await api.poAction(po.id, action)
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Action failed'
  }
  finally { busyId.value = 0 }
}

function openReceive(po: PurchaseOrder) {
  receiveTarget.value = po
  receiveQty.value = {}
  for (const l of po.lines || []) {
    if (l.qty_outstanding > 0) receiveQty.value[l.id] = l.qty_outstanding
  }
}

async function confirmReceive() {
  const po = receiveTarget.value
  if (!po) return
  busyId.value = po.id
  error.value = ''
  try {
    const receipts: Record<number, number> = {}
    for (const [lineId, qty] of Object.entries(receiveQty.value)) {
      if (qty > 0) receipts[Number(lineId)] = qty
    }
    await api.receivePo(po.id, receipts)
    receiveTarget.value = null
    await load()
    say(`Goods receipt posted on ${po.po_number} — stock updated`)
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Receive failed'
  }
  finally { busyId.value = 0 }
}

function addCreateLine() {
  createLines.value.push({ product_id: null, qty: 1 })
}

async function submitCreate() {
  error.value = ''
  const lines = createLines.value
    .filter(l => l.product_id && l.qty > 0)
    .map(l => ({ product_id: l.product_id as number, qty: l.qty }))
  if (!createSupplierId.value || !lines.length) {
    error.value = 'Pick a supplier and at least one line'
    return
  }
  try {
    await api.createPurchaseOrder({ supplier_id: createSupplierId.value, lines, note: createNote.value })
    showCreate.value = false
    createLines.value = []
    createNote.value = ''
    createSupplierId.value = null
    await load()
    say('PO created as draft')
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Create failed'
  }
}

const cny = (n: number) => money(n, 'CNY')
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Procurement · Purchase Orders</h1>
        <div class="sub">plan §21/§22 — Stock Prophet's advisory reorders become POs here: convert → submit → confirm → goods receipt puts units back on the shelf</div>
      </div>
      <div class="row" style="gap:.5rem">
        <button class="ghost" @click="refreshFromProphet">Sync from Stock Prophet</button>
        <button class="ghost" @click="showCreate = true">New manual PO</button>
        <button :disabled="!openSuggestions.length" @click="convertAll">
          Convert all open ({{ openSuggestions.length }})
        </button>
      </div>
    </div>

    <div v-if="flash" class="flash">{{ flash }}</div>
    <div v-if="error" class="err">{{ error }}</div>

    <!-- Stock Prophet suggestions -->
    <div class="card" style="margin-bottom:1rem">
      <div class="card-head">
        <h3>Stock Prophet reorders</h3>
        <div class="row" style="gap:.35rem">
          <button
            v-for="st in ['open', 'converted', 'dismissed', 'superseded']" :key="st"
            class="chip" :class="{ on: suggFilter === st }" @click="suggFilter = st">{{ st }}</button>
          <span v-if="suggFilter === 'open' && openSuggestions.length" class="muted" style="font-size:.76rem;margin-left:.4rem">
            {{ totalOpenUnits }} units across {{ openSuggestions.length }} product(s)
          </span>
        </div>
      </div>
      <div v-if="loading" class="empty">Loading suggestions…</div>
      <table v-else>
        <thead>
          <tr>
            <th>Product</th><th>Supplier</th><th>Shelf</th><th>Velocity</th>
            <th>Cover</th><th>Lead time</th><th style="text-align:right">Suggested qty</th><th>Status</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in filteredSuggestions" :key="s.id">
            <td>
              {{ s.product_title }}
              <div class="muted" style="font-size:.7rem">from run #{{ s.run_id }}</div>
            </td>
            <td>{{ s.supplier_name || '—' }}</td>
            <td class="mono">{{ s.product_stock ?? s.stock_at_time }}</td>
            <td class="mono">{{ s.weekly_velocity.toFixed(1) }}/wk</td>
            <td>
              <span class="risk" :style="{ color: RISK_COLOR[s.risk] || '#94a3b8' }">
                {{ s.weeks_of_cover != null ? `${s.weeks_of_cover}w` : '—' }} · {{ s.risk }}
              </span>
            </td>
            <td class="mono muted">{{ s.supplier_lead_time_days ?? '—' }}d</td>
            <td style="text-align:right" class="mono"><b>+{{ s.suggested_qty }}</b></td>
            <td>
              <span class="st" :style="{ color: SUGG_STATUS_COLOR[s.status] }">{{ s.status }}</span>
              <div v-if="s.po_id" class="muted mono" style="font-size:.7rem">PO #{{ s.po_id }}</div>
            </td>
            <td>
              <div v-if="s.status === 'open'" class="row" style="gap:.3rem">
                <button class="small" @click="convertOne(s)">Raise PO</button>
                <button class="small danger" @click="dismiss(s)">Dismiss</button>
              </div>
              <span v-else class="muted" style="font-size:.74rem">—</span>
            </td>
          </tr>
          <tr v-if="!filteredSuggestions.length">
            <td colspan="9" class="empty">
              No {{ suggFilter }} suggestions — run Stock Prophet in the AI Harness, then "Sync from Stock Prophet".
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Purchase orders -->
    <div class="card">
      <div class="card-head">
        <h3>Purchase orders</h3>
        <div class="row" style="gap:.35rem">
          <button class="chip" :class="{ on: !poFilter }" @click="poFilter = ''">All · {{ pos.length }}</button>
          <button v-for="st in ['draft', 'submitted', 'confirmed', 'received', 'cancelled']" :key="st"
                  class="chip" :class="{ on: poFilter === st }" @click="poFilter = poFilter === st ? '' : st">{{ st }}</button>
        </div>
      </div>
      <div v-if="loading" class="empty">Loading POs…</div>
      <table v-else>
        <thead>
          <tr><th></th><th>PO</th><th>Supplier</th><th>Status</th><th>Source</th><th>Lines</th><th style="text-align:right">Total</th><th>Expected</th><th>Actions</th></tr>
        </thead>
        <tbody>
          <template v-for="po in filteredPos" :key="po.id">
            <tr>
              <td><button class="ghost small" @click="expanded = expanded === po.id ? null : po.id">{{ expanded === po.id ? '▾' : '▸' }}</button></td>
              <td class="mono">
                {{ po.po_number }}
                <div class="muted" style="font-size:.7rem">{{ date(po.created_at || '') }}</div>
              </td>
              <td>{{ po.supplier_name }}</td>
              <td><span class="st" :style="{ color: PO_STATUS_COLOR[po.status] }">{{ po.status }}</span></td>
              <td>
                <span class="src" :class="po.source">{{ po.source === 'stock_prophet' ? 'Stock Prophet' : 'manual' }}</span>
              </td>
              <td class="mono">{{ po.lines?.length || 0 }}</td>
              <td style="text-align:right" class="mono"><b>{{ cny(po.items_total) }}</b> <span class="muted">{{ po.currency }}</span></td>
              <td class="muted" style="font-size:.76rem">{{ po.expected_at ? date(po.expected_at) : '—' }}</td>
              <td>
                <div class="row" style="gap:.3rem;flex-wrap:wrap">
                  <button v-if="po.status === 'draft'" class="small" :disabled="busyId === po.id" @click="poAct(po, 'submit')">Submit</button>
                  <button v-if="po.status === 'submitted'" class="small" :disabled="busyId === po.id" @click="poAct(po, 'confirm')">Confirm</button>
                  <button v-if="po.status === 'confirmed'" class="small" :disabled="busyId === po.id" @click="openReceive(po)">Receive</button>
                  <button v-if="po.status !== 'received' && po.status !== 'cancelled'" class="small danger" :disabled="busyId === po.id" @click="poAct(po, 'cancel')">Cancel</button>
                  <span v-if="po.status === 'received' || po.status === 'cancelled'" class="muted" style="font-size:.74rem">—</span>
                </div>
              </td>
            </tr>
            <tr v-if="expanded === po.id">
              <td />
              <td colspan="9">
                <div v-if="po.note" class="muted" style="font-size:.76rem;margin:.2rem 0 .5rem">{{ po.note }}</div>
                <table class="inner">
                  <thead>
                    <tr><th>Product</th><th>Ordered</th><th>Received</th><th>Outstanding</th><th style="text-align:right">Unit cost</th><th style="text-align:right">Line total</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="l in po.lines || []" :key="l.id">
                      <td>{{ l.product_title }}</td>
                      <td class="mono">{{ l.qty_ordered }}</td>
                      <td class="mono" style="color:#00b374">{{ l.qty_received }}</td>
                      <td class="mono" :style="{ color: l.qty_outstanding ? '#f59e0b' : '#64748b' }">{{ l.qty_outstanding }}</td>
                      <td style="text-align:right" class="mono">{{ cny(l.unit_cost) }}</td>
                      <td style="text-align:right" class="mono">{{ cny(l.line_total) }}</td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
          <tr v-if="!filteredPos.length"><td colspan="10" class="empty">No purchase orders yet</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Receive modal -->
    <div v-if="receiveTarget" class="modal-backdrop" @click.self="receiveTarget = null">
      <div class="modal">
        <h2 style="margin-bottom:.4rem">Goods receipt — {{ receiveTarget.po_number }}</h2>
        <p class="muted" style="font-size:.8rem">
          {{ receiveTarget.supplier_name }} · receiving adds units straight back into product stock.
        </p>
        <table class="inner" style="margin:.8rem 0">
          <thead><tr><th>Product</th><th>Outstanding</th><th>Receive now</th></tr></thead>
          <tbody>
            <tr v-for="l in receiveTarget.lines!.filter(l => l.qty_outstanding > 0)" :key="l.id">
              <td>{{ l.product_title }}</td>
              <td class="mono">{{ l.qty_outstanding }}</td>
              <td>
                <input
                  v-model.number="receiveQty[l.id]" type="number" min="0" :max="l.qty_outstanding"
                  style="width:90px" />
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="receiveTarget = null">Cancel</button>
          <button :disabled="busyId === receiveTarget.id" @click="confirmReceive">Post receipt</button>
        </div>
      </div>
    </div>

    <!-- Manual PO modal -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal">
        <h2 style="margin-bottom:.8rem">New manual PO</h2>
        <div class="field">
          <label>Supplier</label>
          <select v-model.number="createSupplierId">
            <option :value="null" disabled>Choose supplier…</option>
            <option v-for="s in suppliers" :key="s.id" :value="s.id">
              {{ s.name }} ({{ s.city }} · {{ s.lead_time_days }}d lead)
            </option>
          </select>
        </div>
        <div class="field">
          <label>Lines</label>
          <div v-for="(l, i) in createLines" :key="i" class="row" style="gap:.5rem;margin-bottom:.45rem">
            <select v-model.number="l.product_id" style="flex:1">
              <option :value="null" disabled>Product…</option>
              <option v-for="p in products.filter(p => p.supplier_id === createSupplierId)" :key="p.id" :value="p.id">
                {{ p.title }} — {{ cny(p.supplier_cost) }}
              </option>
            </select>
            <input v-model.number="l.qty" type="number" min="1" style="width:90px" />
            <button class="ghost small" @click="createLines.splice(i, 1)">✕</button>
          </div>
          <button class="ghost small" :disabled="!createSupplierId" @click="addCreateLine">+ add line</button>
          <div v-if="!createSupplierId" class="muted" style="font-size:.74rem;margin-top:.3rem">Pick a supplier first — lines filter to its products.</div>
        </div>
        <div class="field">
          <label>Note</label>
          <input v-model="createNote" placeholder="e.g. Top-up before Q4 push" />
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showCreate = false">Cancel</button>
          <button @click="submitCreate">Create draft PO</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card-head { display: flex; justify-content: space-between; align-items: center; padding: .8rem 1rem .4rem; flex-wrap: wrap; gap: .5rem; }
.card-head h3 { margin: 0; }
.st { font-weight: 600; font-size: .8rem; }
.risk { font-weight: 600; font-size: .78rem; }
.src { font-size: .7rem; padding: .12rem .5rem; border-radius: 999px; }
.src.stock_prophet { background: rgba(167,139,250,.14); color: #a78bfa; }
.src.manual { background: rgba(148,163,184,.14); color: #94a3b8; }
table.inner { margin: .3rem 0 .5rem; }
table.inner th { font-size: .7rem; }
.chip { font-size: .74rem; padding: .28rem .65rem; border-radius: 999px; border: 1px solid rgba(148,163,184,.25); background: transparent; color: #cbd5e1; cursor: pointer; }
.chip.on { border-color: #38bdf8; color: #38bdf8; background: rgba(56,189,248,.08); }
.flash { margin-bottom: .6rem; padding: .5rem .8rem; border-radius: 8px; background: rgba(0,179,116,.1); color: #00d68f; font-size: .8rem; border: 1px solid rgba(0,179,116,.3); }
.err { color: #f87171; font-size: .8rem; margin-bottom: .6rem; }
input[type='number'], select { background: rgba(15, 23, 42, .6); border: 1px solid rgba(148, 163, 184, .25); color: #e2e8f0; border-radius: 8px; padding: .4rem .55rem; }
</style>

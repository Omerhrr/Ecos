<script setup lang="ts">
/**
 * Warehouse / Fulfillment (plan §22 deep-dive).
 * Tabs: Stock (per-warehouse levels) · Pick waves (order fulfillment:
 * create -> pick -> pack -> complete -> shipments) · Movements (immutable
 * stock ledger) · Warehouses (locations). PO receipts land here as
 * `receipt` movements via procurement goods-receipt.
 */
const api = useApi()
const { date, money } = useFormat()

const tab = ref<'stock' | 'waves' | 'movements' | 'warehouses'>('stock')

const warehouses = ref<WarehouseInfo[]>([])
const stockRows = ref<StockRow[]>([])
const movements = ref<StockMovementRow[]>([])
const waves = ref<PickWave[]>([])
const products = ref<Product[]>([])
const waveOrders = ref<Order[]>([])

const loading = ref(true)
const busyId = ref(0)
const error = ref('')
const flash = ref('')

const stockWarehouseFilter = ref<number | ''>('')
const movementFilter = ref<string>('')
const movementTypeFilter = ref<string>('')
const expandedWave = ref<number | null>(null)
const showCreateWh = ref(false)
const createWh = reactive({ name: '', city: '', country: 'NG', address: '', is_default: false })
const showCreateWave = ref(false)
const waveOrderIds = ref<number[]>([])
const showAdjust = ref(false)
const adjustForm = reactive({ warehouse_id: null as number | null, product_id: null as number | null, delta: 1, reason: '' })
const showTransfer = ref(false)
const transferForm = reactive({ from_warehouse_id: null as number | null, to_warehouse_id: null as number | null, product_id: null as number | null, qty: 1 })

const MV_COLOR: Record<string, string> = {
  receipt: '#00b374', pick: '#38bdf8', adjustment: '#f59e0b',
  transfer_in: '#a78bfa', transfer_out: '#c084fc', return_restock: '#4ade80',
}
const WAVE_COLOR: Record<string, string> = {
  open: '#eab308', picking: '#38bdf8', packed: '#a78bfa',
  completed: '#00b374', cancelled: '#94a3b8',
}

const defaultWh = computed(() => warehouses.value.find(w => w.is_default) ?? warehouses.value[0])
const activeStockRows = computed(() =>
  stockWarehouseFilter.value ? stockRows.value.filter(r => r.warehouse_id === stockWarehouseFilter.value) : stockRows.value,
)
const filteredMovements = computed(() => movements.value.filter(m =>
  (!movementFilter.value || String(m.warehouse_id) === movementFilter.value)
  && (!movementTypeFilter.value || m.movement_type === movementTypeFilter.value),
))
const wavedOrderIds = computed(() => new Set(waves.value.filter(w => w.status !== 'cancelled').flatMap(w => (w.lines ?? []).map(l => l.order_id))))
const waveableOrders = computed(() =>
  waveOrders.value.filter(o => ['confirmed', 'processing'].includes(o.status) && !wavedOrderIds.value.has(o.id)),
)

function say(msg: string) {
  flash.value = msg
  setTimeout(() => { flash.value = '' }, 2500)
}
function fail(e: unknown, fallback: string) {
  const err = e as { response?: { _data?: { detail?: string } } }
  error.value = err.response?._data?.detail || fallback
  setTimeout(() => { error.value = '' }, 5000)
}

async function load() {
  loading.value = true
  try {
    const [whs, rows, mvs, wvs] = await Promise.all([
      api.warehouses(),
      api.stockOverview(),
      api.stockMovements({ limit: 120 }),
      api.pickWaves(),
    ])
    warehouses.value = whs
    stockRows.value = rows
    movements.value = mvs
    waves.value = wvs
  }
  finally { loading.value = false }
}
onMounted(async () => {
  const [prd, ords] = await Promise.all([
    api.products({ status: 'active' }),
    api.orders(),
  ])
  products.value = prd
  waveOrders.value = ords
  await load()
})

async function createWarehouse() {
  try {
    await api.createWarehouse({ ...createWh })
    showCreateWh.value = false
    createWh.name = ''; createWh.city = ''; createWh.address = ''; createWh.is_default = false
    say('Warehouse created')
    await load()
  }
  catch (e) { fail(e, 'Could not create warehouse') }
}

async function adjust() {
  if (!adjustForm.warehouse_id || !adjustForm.product_id) return
  try {
    await api.adjustStock({
      warehouse_id: adjustForm.warehouse_id,
      product_id: adjustForm.product_id,
      delta: adjustForm.delta,
      reason: adjustForm.reason,
    })
    showAdjust.value = false
    adjustForm.reason = ''
    say('Stock adjusted — movement posted')
    await load()
  }
  catch (e) { fail(e, 'Adjustment failed') }
}

async function transfer() {
  if (!transferForm.from_warehouse_id || !transferForm.to_warehouse_id || !transferForm.product_id) return
  try {
    await api.transferStock({ ...transferForm })
    showTransfer.value = false
    say('Transfer posted — two ledger movements')
    await load()
  }
  catch (e) { fail(e, 'Transfer failed') }
}

async function createWave() {
  try {
    const w = await api.createPickWave({ order_ids: waveOrderIds.value })
    showCreateWave.value = false
    waveOrderIds.value = []
    say(`Wave ${w.wave_number} created — ${w.order_count} order(s)`)
    await load()
  }
  catch (e) { fail(e, 'Could not create wave') }
}

async function waveAction(w: PickWave, action: 'pick' | 'pack' | 'complete' | 'cancel') {
  busyId.value = w.id
  error.value = ''
  try {
    await api.waveAction(w.id, action)
    say(`Wave ${w.wave_number}: ${action} done${action === 'complete' ? ' — shipments created' : ''}`)
    await load()
  }
  catch (e) { fail(e, `Wave ${action} failed`) }
  finally { busyId.value = 0 }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Warehouse · Fulfillment</h1>
        <p class="muted">Stock rooms, pick waves and the movement ledger (§22) — PO receipts land here as putaway.</p>
      </div>
      <div class="head-actions">
        <button class="ghost" @click="showAdjust = true">Adjust stock</button>
        <button class="ghost" @click="showTransfer = true">Transfer</button>
        <button class="primary" @click="showCreateWave = true">New pick wave</button>
      </div>
    </div>

    <div v-if="flash" class="flash">{{ flash }}</div>
    <div v-if="error" class="form-error">{{ error }}</div>

    <div class="tabs">
      <button :class="{ active: tab === 'stock' }" @click="tab = 'stock'">Stock</button>
      <button :class="{ active: tab === 'waves' }" @click="tab = 'waves'">Pick waves</button>
      <button :class="{ active: tab === 'movements' }" @click="tab = 'movements'">Movements</button>
      <button :class="{ active: tab === 'warehouses' }" @click="tab = 'warehouses'">Warehouses</button>
    </div>

    <!-- STOCK -->
    <div v-if="tab === 'stock'" class="panel">
      <div v-if="loading" class="muted">Loading…</div>
      <table v-else class="tbl">
        <thead>
          <tr>
            <th>Warehouse</th><th>Product</th><th class="num">On hand</th>
            <th class="num">Reserved</th><th class="num">Available</th><th class="num">Network stock</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in activeStockRows" :key="r.id">
            <td><b>{{ r.warehouse_code }}</b> <span class="muted">{{ r.warehouse_name }}</span></td>
            <td>{{ r.product_title }}</td>
            <td class="num">{{ r.on_hand }}</td>
            <td class="num muted">{{ r.reserved }}</td>
            <td class="num"><b :style="{ color: r.available > 0 ? '#00b374' : '#f87171' }">{{ r.available }}</b></td>
            <td class="num muted">{{ r.product_stock }}</td>
          </tr>
          <tr v-if="!activeStockRows.length"><td colspan="6" class="muted">No stock yet — receive a PO or post an opening balance.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- WAVES -->
    <div v-if="tab === 'waves'" class="panel">
      <div v-if="loading" class="muted">Loading…</div>
      <div v-else class="wave-list">
        <div v-for="w in waves" :key="w.id" class="wave-card" :class="{ open: expandedWave === w.id }">
          <div class="wave-head" @click="expandedWave = expandedWave === w.id ? null : w.id">
            <b>{{ w.wave_number }}</b>
            <span class="muted">{{ w.warehouse_code }} · {{ w.order_count }} order(s) · {{ date(w.created_at) }}</span>
            <StatusBadge :status="w.status" :color="WAVE_COLOR[w.status]" />
            <span class="spacer" />
            <button
              v-for="a in (['pick', 'pack', 'complete', 'cancel'] as const).filter(a => w.allowed_transitions.includes(a === 'pick' ? 'picking' : a === 'pack' ? 'packed' : a === 'complete' ? 'completed' : 'cancelled'))"
              :key="a"
              class="tiny"
              :class="{ danger: a === 'cancel', primary: a === 'complete' }"
              :disabled="busyId === w.id"
              @click.stop="waveAction(w, a)"
            >
              {{ a.charAt(0).toUpperCase() + a.slice(1) }}
            </button>
          </div>
          <div v-if="expandedWave === w.id && w.lines" class="wave-lines">
            <div v-for="l in w.lines" :key="l.id" class="wave-line">
              <span class="muted">#{{ l.order_id }}</span>
              <span>{{ l.title }}</span>
              <span class="num">× {{ l.qty }}</span>
              <StatusBadge :status="l.status" :color="l.status === 'picked' ? '#38bdf8' : l.status === 'packed' ? '#a78bfa' : '#eab308'" />
            </div>
            <div class="muted wave-note">
              Completing hands every order to logistics — shipments are created and orders go to fulfilled.
            </div>
          </div>
        </div>
        <div v-if="!waves.length" class="muted">No pick waves yet — create one from confirmed orders.</div>
      </div>
    </div>

    <!-- MOVEMENTS -->
    <div v-if="tab === 'movements'" class="panel">
      <div class="filter-row">
        <select v-model="movementFilter">
          <option value="">All warehouses</option>
          <option v-for="w in warehouses" :key="w.id" :value="String(w.id)">{{ w.code }} · {{ w.name }}</option>
        </select>
        <select v-model="movementTypeFilter">
          <option value="">All types</option>
          <option v-for="(c, t) in MV_COLOR" :key="t" :value="t">{{ t }}</option>
        </select>
      </div>
      <div v-if="loading" class="muted">Loading…</div>
      <table v-else class="tbl">
        <thead>
          <tr><th>When</th><th>Warehouse</th><th>Product</th><th>Type</th><th class="num">Qty</th><th class="num">Balance</th><th>Reference</th><th>Note</th></tr>
        </thead>
        <tbody>
          <tr v-for="m in filteredMovements" :key="m.id">
            <td class="muted">{{ date(m.created_at) }}</td>
            <td><b>{{ m.warehouse_code }}</b></td>
            <td>{{ m.product_title }}</td>
            <td><span class="mv-type" :style="{ background: MV_COLOR[m.movement_type] }">{{ m.movement_type }}</span></td>
            <td class="num" :style="{ color: m.qty >= 0 ? '#00b374' : '#f87171' }">{{ m.qty >= 0 ? '+' : '' }}{{ m.qty }}</td>
            <td class="num muted">{{ m.balance_after }}</td>
            <td class="muted">{{ m.reference_type }}{{ m.reference_id ? ` #${m.reference_id}` : '' }}</td>
            <td class="muted note-cell">{{ m.note }}</td>
          </tr>
          <tr v-if="!filteredMovements.length"><td colspan="8" class="muted">No movements match.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- WAREHOUSES -->
    <div v-if="tab === 'warehouses'" class="panel">
      <div class="filter-row right">
        <button class="primary" @click="showCreateWh = true">New warehouse</button>
      </div>
      <div v-if="loading" class="muted">Loading…</div>
      <div v-else class="wh-grid">
        <div v-for="w in warehouses" :key="w.id" class="wh-card">
          <div class="wh-head">
            <b>{{ w.code }}</b>
            <span v-if="w.is_default" class="chip default">default</span>
          </div>
          <div class="wh-name">{{ w.name }}</div>
          <div class="muted">{{ w.city }}, {{ w.country }}<template v-if="w.address"> · {{ w.address }}</template></div>
          <div class="wh-stats">
            <div><b>{{ w.sku_count }}</b><span class="muted">SKUs</span></div>
            <div><b>{{ w.units_on_hand }}</b><span class="muted">units</span></div>
            <div><b>{{ w.open_waves }}</b><span class="muted">open waves</span></div>
          </div>
        </div>
        <div v-if="!warehouses.length" class="muted">No warehouses yet.</div>
      </div>
    </div>

    <!-- New pick wave modal -->
    <div v-if="showCreateWave" class="modal-mask" @click.self="showCreateWave = false">
      <div class="modal">
        <h3>New pick wave</h3>
        <p class="muted">Confirmed/processing orders without a shipment. Completing the wave creates the shipments.</p>
        <div class="wave-order-pick">
          <label v-for="o in waveableOrders" :key="o.id" class="wave-order-row">
            <input v-model="waveOrderIds" type="checkbox" :value="o.id">
            <span><b>#{{ o.id }}</b> {{ o.customer_name || `customer ${o.customer_id}` }}</span>
            <span class="muted">{{ o.status }} · {{ money(o.total) }}</span>
          </label>
          <div v-if="!waveableOrders.length" class="muted">No orders ready to wave — everything is already fulfilled or waving.</div>
        </div>
        <div class="modal-actions">
          <button class="ghost" @click="showCreateWave = false">Cancel</button>
          <button class="primary" :disabled="!waveOrderIds.length" @click="createWave">
            Create wave ({{ waveOrderIds.length }})
          </button>
        </div>
      </div>
    </div>

    <!-- Adjust modal -->
    <div v-if="showAdjust" class="modal-mask" @click.self="showAdjust = false">
      <div class="modal">
        <h3>Adjust stock (cycle count)</h3>
        <label class="field"><span>Warehouse</span>
          <select v-model="adjustForm.warehouse_id">
            <option :value="null" disabled>Choose…</option>
            <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.code }} · {{ w.name }}</option>
          </select>
        </label>
        <label class="field"><span>Product</span>
          <select v-model="adjustForm.product_id">
            <option :value="null" disabled>Choose…</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </label>
        <label class="field"><span>Delta (signed)</span>
          <input v-model.number="adjustForm.delta" type="number" step="1" required>
        </label>
        <label class="field"><span>Reason</span>
          <input v-model="adjustForm.reason" minlength="3" required placeholder="e.g. damaged units written off">
        </label>
        <div class="modal-actions">
          <button class="ghost" @click="showAdjust = false">Cancel</button>
          <button class="primary" :disabled="!adjustForm.reason || !adjustForm.warehouse_id || !adjustForm.product_id" @click="adjust">Post adjustment</button>
        </div>
      </div>
    </div>

    <!-- Transfer modal -->
    <div v-if="showTransfer" class="modal-mask" @click.self="showTransfer = false">
      <div class="modal">
        <h3>Transfer stock</h3>
        <div class="cart-form-row">
          <label class="field"><span>From</span>
            <select v-model="transferForm.from_warehouse_id">
              <option :value="null" disabled>Choose…</option>
              <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.code }}</option>
            </select>
          </label>
          <label class="field"><span>To</span>
            <select v-model="transferForm.to_warehouse_id">
              <option :value="null" disabled>Choose…</option>
              <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.code }}</option>
            </select>
          </label>
        </div>
        <label class="field"><span>Product</span>
          <select v-model="transferForm.product_id">
            <option :value="null" disabled>Choose…</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </label>
        <label class="field"><span>Qty</span>
          <input v-model.number="transferForm.qty" type="number" min="1" required>
        </label>
        <div class="modal-actions">
          <button class="ghost" @click="showTransfer = false">Cancel</button>
          <button class="primary" :disabled="!transferForm.from_warehouse_id || !transferForm.to_warehouse_id || !transferForm.product_id" @click="transfer">Transfer</button>
        </div>
      </div>
    </div>

    <!-- New warehouse modal -->
    <div v-if="showCreateWh" class="modal-mask" @click.self="showCreateWh = false">
      <div class="modal">
        <h3>New warehouse</h3>
        <label class="field"><span>Name</span><input v-model="createWh.name" required minlength="2"></label>
        <div class="cart-form-row">
          <label class="field"><span>City</span><input v-model="createWh.city"></label>
          <label class="field"><span>Country code</span><input v-model="createWh.country" maxlength="2"></label>
        </div>
        <label class="field"><span>Address</span><input v-model="createWh.address"></label>
        <label class="check-row"><input v-model="createWh.is_default" type="checkbox"> Default receiving warehouse</label>
        <div class="modal-actions">
          <button class="ghost" @click="showCreateWh = false">Cancel</button>
          <button class="primary" :disabled="createWh.name.length < 2" @click="createWarehouse">Create</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: .8rem; }
.page-head h1 { margin: 0 0 .2rem; }
.head-actions { display: flex; gap: .5rem; flex-wrap: wrap; }
.flash { background: rgba(0,179,116,.12); border: 1px solid rgba(0,179,116,.4); color: #4ade80; padding: .5rem .8rem; border-radius: 8px; margin-bottom: .8rem; font-size: .85rem; }
.form-error { background: rgba(248,113,113,.1); border: 1px solid rgba(248,113,113,.4); color: #fca5a5; padding: .5rem .8rem; border-radius: 8px; margin-bottom: .8rem; font-size: .85rem; }
.tabs { display: flex; gap: .3rem; margin-bottom: 1rem; }
.tabs button { background: transparent; border: 1px solid #1e293b; color: #94a3b8; padding: .4rem .9rem; border-radius: 8px 8px 0 0; cursor: pointer; font-size: .85rem; }
.tabs button.active { color: #e2e8f0; border-color: #334155; background: #0f172a; }
.panel { background: #0f172a; border: 1px solid #1e293b; border-radius: 0 12px 12px 12px; padding: 1rem; }
.tbl { width: 100%; border-collapse: collapse; font-size: .87rem; }
.tbl th { text-align: left; color: #64748b; font-weight: 600; padding: .45rem .6rem; border-bottom: 1px solid #1e293b; font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; }
.tbl td { padding: .55rem .6rem; border-bottom: 1px solid rgba(30,41,59,.6); }
.tbl .num { text-align: right; font-variant-numeric: tabular-nums; }
.filter-row { display: flex; gap: .6rem; margin-bottom: .8rem; }
.filter-row.right { justify-content: flex-end; }
.filter-row select { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; padding: .4rem .6rem; font-size: .85rem; }
.mv-type { color: #0b1220; font-size: .72rem; padding: .15rem .5rem; border-radius: 99px; font-weight: 700; }
.note-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wave-list { display: flex; flex-direction: column; gap: .5rem; }
.wave-card { border: 1px solid #1e293b; border-radius: 10px; background: #0b1220; }
.wave-card.open { border-color: #334155; }
.wave-head { display: flex; align-items: center; gap: .8rem; padding: .6rem .8rem; cursor: pointer; flex-wrap: wrap; }
.wave-head .spacer { flex: 1; }
.wave-lines { padding: 0 .8rem .7rem; border-top: 1px dashed #1e293b; }
.wave-line { display: flex; gap: .8rem; align-items: center; padding: .4rem 0; font-size: .85rem; }
.wave-line .num { margin-left: auto; }
.wave-note { font-size: .75rem; padding-top: .4rem; }
.wave-order-pick { max-height: 260px; overflow-y: auto; border: 1px solid #1e293b; border-radius: 8px; margin: .6rem 0; }
.wave-order-row { display: flex; gap: .6rem; align-items: center; padding: .45rem .6rem; border-bottom: 1px solid rgba(30,41,59,.5); cursor: pointer; font-size: .85rem; }
.wave-order-row:last-child { border-bottom: 0; }
.wave-order-row span:nth-child(2) { flex: 1; }
.wh-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: .8rem; }
.wh-card { border: 1px solid #1e293b; border-radius: 10px; padding: .9rem; background: #0b1220; }
.wh-head { display: flex; justify-content: space-between; align-items: center; }
.wh-name { font-size: 1rem; margin: .3rem 0 .1rem; }
.wh-stats { display: flex; gap: 1.2rem; margin-top: .7rem; }
.wh-stats div { display: flex; flex-direction: column; }
.chip.default { background: rgba(0,179,116,.15); color: #4ade80; font-size: .7rem; padding: .1rem .5rem; border-radius: 99px; }
.modal-mask { position: fixed; inset: 0; background: rgba(2,6,23,.7); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #0f172a; border: 1px solid #334155; border-radius: 14px; padding: 1.2rem; width: min(480px, 92vw); max-height: 86vh; overflow-y: auto; }
.modal h3 { margin: 0 0 .4rem; }
.modal-actions { display: flex; justify-content: flex-end; gap: .5rem; margin-top: 1rem; }
.field { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .7rem; font-size: .85rem; }
.field span { color: #94a3b8; font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; }
.field input, .field select { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; padding: .5rem .6rem; }
.check-row { display: flex; gap: .5rem; align-items: center; font-size: .85rem; margin-bottom: .5rem; }
.cart-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; }
button.tiny { font-size: .72rem; padding: .25rem .6rem; border-radius: 7px; }
button.danger { color: #fca5a5; border-color: rgba(248,113,113,.4); }
</style>

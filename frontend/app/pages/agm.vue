<script setup lang="ts">
/**
 * AGM console (role=agm) — the agent management system.
 * Warehouses, per-vendor inventory, fulfillment alerts (call → ship → COD)
 * and the §24 remittance register, all scoped to the agent's own org.
 */
definePageMeta({ layout: 'agm' })
const api = useApi()
const auth = useAuth()

const tab = ref<'alerts' | 'inventory' | 'warehouses' | 'remit'>('alerts')
const overview = ref<AgmOverview | null>(null)
const orders = ref<AgentOrder[]>([])
const stock = ref<AgentStockRow[]>([])
const warehouses = ref<AgentWarehouseRow[]>([])
const remittances = ref<AgentRemittance[]>([])
const loading = ref(true)
const busy = ref(0)
const flash = ref('')
const error = ref('')

const whOpen = ref(false)
const whForm = reactive({ name: '', city: '', address: '' })
const deliverFor = ref(0)
const codInput = ref(0)
const failFor = ref(0)
const failReason = ref('')

onMounted(async () => {
  auth.restore()
  if (auth.user.value?.role !== 'agm') { navigateTo('/login'); return }
  await load()
})

async function load() {
  loading.value = true
  try {
    const [ov, q, st, wh, rem] = await Promise.all([
      api.agmOverview(), api.agmOrders(), api.agmStock(), api.agmWarehouses(), api.agmRemittances(),
    ])
    overview.value = ov; orders.value = q; stock.value = st
    warehouses.value = wh; remittances.value = rem
  }
  finally { loading.value = false }
}

async function act(ao: AgentOrder, action: string, extra: Record<string, unknown> = {}) {
  busy.value = ao.id
  error.value = ''
  try {
    const updated = await api.agmOrderAction(ao.id, { action, ...extra })
    Object.assign(ao, updated)
    flash.value = `${ao.code} → ${action.replace(/_/g, ' ')}`
    deliverFor.value = 0; failFor.value = 0
    await load()
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Action failed.'
  }
  finally { busy.value = 0 }
}

async function createWarehouse() {
  busy.value = -1
  try {
    await api.agmCreateWarehouse({ ...whForm, is_default: !warehouses.value.length })
    whOpen.value = false
    whForm.name = ''; whForm.city = ''; whForm.address = ''
    flash.value = 'Warehouse created.'
    await load()
  }
  catch { error.value = 'Could not create the warehouse.' }
  finally { busy.value = 0 }
}

async function openRemittance() {
  busy.value = -2
  error.value = ''
  try {
    const reg = await api.agmCreateRemittance({})
    flash.value = `${reg.register_code} opened — ₦${reg.expected_amount?.toLocaleString()} across ${reg.lines?.length ?? 0} delivery(ies).`
    tab.value = 'remit'
    await load()
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Nothing to remit — deliver COD orders first.'
  }
  finally { busy.value = 0 }
}

async function remit(r: AgentRemittance) {
  busy.value = r.id
  try {
    const updated = await api.agmRemit(r.id, `CASH-${r.register_code}`)
    Object.assign(r, updated)
    flash.value = `${r.register_code} remitted — ready to reconcile.`
  }
  catch { error.value = 'Remit failed.' }
  finally { busy.value = 0 }
}

async function reconcile(r: AgentRemittance) {
  busy.value = r.id
  try {
    const counted: Record<string, number> = {}
    for (const l of r.lines ?? []) counted[String(l.id)] = l.expected_amount
    const updated = await api.agmReconcile(r.id, counted)
    Object.assign(r, updated)
    flash.value = `${r.register_code} reconciled — variance ₦${updated.variance_amount?.toLocaleString()}`
    await load()
  }
  catch { error.value = 'Reconcile failed.' }
  finally { busy.value = 0 }
}

const fmt = (n: number) => '₦' + Number(n || 0).toLocaleString()
const tone = (s: string) =>
  ({ notified: 'amber', accepted: 'blue', calling: 'blue', confirmed: 'blue', out_for_delivery: 'blue', delivered: 'green', failed: 'red', returned: 'gray', cancelled: 'gray' }[s] ?? 'gray')
const NEXT: Record<string, { action: string; label: string }[]> = {
  notified: [{ action: 'accept', label: 'Accept' }],
  accepted: [{ action: 'start_call', label: 'Start calling' }],
  calling: [{ action: 'confirm', label: 'Customer confirmed' }],
  confirmed: [{ action: 'out_for_delivery', label: 'Send out for delivery' }],
  out_for_delivery: [],
  failed: [{ action: 'out_for_delivery', label: 'Retry delivery' }],
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>AGM Console — {{ overview?.company }}</h1>
        <div class="sub">Hold vendor stock, call customers, ship out, collect COD, remit (§20-24).</div>
      </div>
      <div class="row">
        <button v-for="t in (['alerts','inventory','warehouses','remit'] as const)" :key="t" :class="tab === t ? '' : 'ghost'" @click="tab = t">
          {{ t === 'remit' ? 'Remittance' : t }}
          <span v-if="t === 'alerts' && overview?.pending_alerts" class="badge amber">{{ overview.pending_alerts }}</span>
        </button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi card"><div class="kpi-label">Vendors</div><div class="kpi-value">{{ overview?.vendors ?? '—' }}</div></div>
      <div class="kpi card"><div class="kpi-label">Warehouses</div><div class="kpi-value">{{ overview?.warehouses ?? '—' }}</div></div>
      <div class="kpi card"><div class="kpi-label">Units held</div><div class="kpi-value">{{ overview?.units_held ?? '—' }}</div></div>
      <div class="kpi card"><div class="kpi-label">Pending alerts</div><div class="kpi-value">{{ overview?.pending_alerts ?? '—' }}</div></div>
      <div class="kpi card"><div class="kpi-label">COD awaiting remit</div><div class="kpi-value">{{ fmt(overview?.cod_awaiting_remit ?? 0) }}</div></div>
    </div>

    <div v-if="flash" class="badge green" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ flash }}</div>
    <div v-if="error" class="badge red" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ error }}</div>

    <!-- ALERTS -->
    <template v-if="tab === 'alerts'">
      <div v-if="loading" class="muted">Loading…</div>
      <div v-else class="card" v-for="ao in orders" :key="ao.id" style="margin-bottom:.8rem"
           :style="ao.status === 'notified' ? 'border-color:var(--warn);border-width:1.5px' : ''">
        <div style="display:flex;justify-content:space-between;gap:.8rem;flex-wrap:wrap;align-items:center">
          <div>
            <b>{{ ao.code }}</b> · {{ ao.qty }} × {{ ao.title }}
            <span class="badge" :class="tone(ao.status)" style="margin-left:.4rem">{{ ao.status.replace(/_/g,' ') }}</span>
            <div style="font-size:.88rem;margin-top:.3rem">
              📞 <b>{{ ao.customer.name }}</b> · {{ ao.customer.phone }} — {{ ao.customer.address }}, {{ ao.customer.city }}
            </div>
            <div class="muted" style="font-size:.8rem;margin-top:.15rem">
              Order #{{ ao.order_id }} · {{ ao.payment_method.toUpperCase() }}
              <template v-if="ao.cod_expected"> · collect {{ fmt(ao.cod_expected) }}</template>
              <template v-if="ao.cod_collected"> · collected {{ fmt(ao.cod_collected) }}</template>
            </div>
            <div v-if="ao.note" class="muted" style="font-size:.78rem">note: {{ ao.note }}</div>
          </div>
          <div style="display:flex;gap:.45rem;flex-wrap:wrap;align-items:center">
            <template v-for="n in (NEXT[ao.status] || [])" :key="n.action">
              <button class="small" :disabled="busy === ao.id" @click="act(ao, n.action)">{{ n.label }}</button>
            </template>
            <template v-if="ao.status === 'out_for_delivery'">
              <button v-if="deliverFor !== ao.id" class="small" @click="deliverFor = ao.id; codInput = ao.cod_expected">Deliver…</button>
              <template v-else>
                <input v-model.number="codInput" type="number" style="width:120px" placeholder="COD collected">
                <button class="small" :disabled="busy === ao.id" @click="act(ao, 'deliver', { cod_collected: codInput })">Confirm delivered</button>
              </template>
              <button class="danger small" @click="failFor = failFor === ao.id ? 0 : ao.id">Failed</button>
              <input v-if="failFor === ao.id" v-model="failReason" style="width:150px" placeholder="reason (e.g. unreachable)">
              <button v-if="failFor === ao.id" class="danger small" :disabled="busy === ao.id" @click="act(ao, 'fail', { failed_reason: failReason })">Confirm failed</button>
            </template>
            <template v-if="['calling'].includes(ao.status)">
              <button class="ghost small" @click="failFor = failFor === ao.id ? 0 : ao.id">Unreachable</button>
              <input v-if="failFor === ao.id" v-model="failReason" style="width:150px" placeholder="reason">
              <button v-if="failFor === ao.id" class="danger small" :disabled="busy === ao.id" @click="act(ao, 'fail', { failed_reason: failReason })">Confirm</button>
            </template>
          </div>
        </div>
      </div>
      <div v-if="!loading && !orders.length" class="card muted">Queue empty — alerts from your vendors land here the moment they confirm an order.</div>
    </template>

    <!-- INVENTORY -->
    <template v-if="tab === 'inventory'">
      <div class="card" style="padding:0">
        <table>
          <thead><tr><th>Product</th><th>Vendor</th><th>Warehouse</th><th>On hand</th><th>Reserved</th><th>Sellable</th></tr></thead>
          <tbody>
            <tr v-for="s in stock" :key="s.id">
              <td><b>{{ s.product_title }}</b></td>
              <td>{{ s.vendor_name }}</td>
              <td class="muted">#{{ s.warehouse_id }} — {{ warehouses.find(w => w.id === s.warehouse_id)?.name || '—' }}</td>
              <td>{{ s.on_hand }}</td>
              <td class="muted">{{ s.reserved }}</td>
              <td><b>{{ s.sellable }}</b></td>
            </tr>
            <tr v-if="!stock.length"><td colspan="6" class="empty">No stock yet — received sourcing orders land here per vendor</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- WAREHOUSES -->
    <template v-if="tab === 'warehouses'">
      <div style="margin-bottom:.8rem"><button @click="whOpen = true">+ New warehouse</button></div>
      <div class="card" v-for="w in warehouses" :key="w.id" style="margin-bottom:.7rem;display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap">
        <div>
          <b>{{ w.name }}</b> <span v-if="w.is_default" class="badge teal">default</span> <span class="badge gray">{{ w.code }}</span>
          <div class="muted" style="font-size:.8rem;margin-top:.2rem">{{ w.address }} · {{ w.city }}, {{ w.country }}</div>
        </div>
        <span class="badge" :class="w.status === 'active' ? 'green' : 'gray'">{{ w.status }}</span>
      </div>
      <div v-if="!warehouses.length" class="card muted">No warehouses yet — create your first location.</div>
    </template>

    <!-- REMITTANCE -->
    <template v-if="tab === 'remit'">
      <div style="margin-bottom:.8rem;display:flex;gap:.5rem">
        <button :disabled="busy === -2" @click="openRemittance">Open register from collected COD</button>
      </div>
      <div v-if="!remittances.length" class="card muted">No registers yet — deliver COD orders, then open a register.</div>
      <div class="card" v-for="r in remittances" :key="r.id" style="margin-bottom:.8rem">
        <div style="display:flex;justify-content:space-between;gap:.8rem;flex-wrap:wrap;align-items:center">
          <div>
            <b>{{ r.register_code }}</b>
            <span class="badge" :class="{ draft: 'amber', remitted: 'blue', reconciled: 'green', cancelled: 'gray' }[r.status]" style="margin-left:.4rem">{{ r.status }}</span>
            <div class="muted" style="font-size:.8rem;margin-top:.2rem">
              Expected {{ fmt(r.expected_amount) }} · remitted {{ fmt(r.remitted_amount) }} · counted {{ fmt(r.counted_amount) }}
              <template v-if="r.variance_amount"> · <span :style="{ color: r.variance_amount < 0 ? 'var(--danger)' : 'var(--accent)' }">variance {{ fmt(r.variance_amount) }}</span></template>
              <template v-if="r.lines"> · {{ r.lines.length }} line(s)</template>
            </div>
          </div>
          <div style="display:flex;gap:.45rem">
            <button v-if="r.status === 'draft'" class="small" :disabled="busy === r.id" @click="remit(r)">Remit cash</button>
            <button v-if="r.status === 'remitted'" class="small" :disabled="busy === r.id" @click="reconcile(r)">Reconcile (all counted)</button>
          </div>
        </div>
        <div v-if="r.lines?.length" style="margin-top:.6rem;border-top:1px solid var(--border);padding-top:.5rem">
          <table>
            <thead><tr><th>Order</th><th>Vendor</th><th>Expected</th><th>Counted</th></tr></thead>
            <tbody>
              <tr v-for="l in r.lines" :key="l.id">
                <td class="mono">#{{ l.order_id }}</td>
                <td class="muted">org {{ l.vendor_org_id }}</td>
                <td>{{ fmt(l.expected_amount) }}</td>
                <td>{{ fmt(l.counted_amount) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- warehouse modal -->
    <div v-if="whOpen" class="modal-backdrop" @click.self="whOpen = false">
      <div class="modal">
        <h2>New warehouse</h2>
        <div class="field"><label>Name</label><input v-model="whForm.name" placeholder="Eko Hub — Surulere"></div>
        <div class="field"><label>City</label><input v-model="whForm.city" placeholder="Lagos"></div>
        <div class="field"><label>Address</label><input v-model="whForm.address"></div>
        <div class="modal-actions">
          <button class="ghost" @click="whOpen = false">Cancel</button>
          <button :disabled="!whForm.name || busy === -1" @click="createWarehouse">Create</button>
        </div>
      </div>
    </div>
  </div>
</template>

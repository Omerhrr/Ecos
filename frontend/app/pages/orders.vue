<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const orders = ref<Order[]>([])
const stores = ref<Store[]>([])
const customers = ref<{ id: number; full_name: string; store_id: number }[]>([])
const products = ref<Product[]>([])
const agents = ref<AgentLinkRow[]>([])
const loading = ref(true)
const statusFilter = ref('')
const showForm = ref(false)
const busy = ref(false)
const markFor = ref<Order | null>(null)
const markAgent = ref<number | null>(null)
const markBusy = ref(false)
const markError = ref('')
const relayFor = ref<Order | null>(null)
const relayBusy = ref(false)
const relayError = ref('')

const form = reactive({
  store_id: 1, customer_id: 0, product_id: 0, qty: 1,
  payment_method: 'cod', delivery_fee: 0,
})

async function load() {
  loading.value = true
  try {
    orders.value = await api.orders(statusFilter.value ? { status: statusFilter.value } : undefined)
  }
  finally { loading.value = false }
}

async function loadFormData() {
  const [s, l, p, ag] = await Promise.all([
    api.stores(),
    $fetch<{ id: number; store_id: number; full_name: string }[]>('/api/customers'),
    api.products({ status: 'active' }),
    api.agentLinks().catch(() => []),
  ])
  stores.value = s
  customers.value = l
  products.value = p
  agents.value = ag
  if (!form.customer_id && l.length) form.customer_id = l[0].id
  if (!form.product_id && p.length) form.product_id = p[0].id
}

onMounted(async () => { await load(); try { await loadFormData() } catch {} loading.value = false })
watch(statusFilter, load)

const unitPrice = computed(() =>
  products.value.find(p => p.id === form.product_id)?.pricing.ecos_price_ngn ?? 0,
)

async function create() {
  busy.value = true
  try {
    const res = await api.createOrder({ ...form })
    showForm.value = false
    navigateTo(`/orders/${res.id}`)
  }
  finally { busy.value = false }
}

// §20-24: hand a confirmed order to the agent — the AGM alert fires instantly
async function openMark(o: Order) {
  markFor.value = o
  markAgent.value = agents.value[0]?.agent_org_id ?? null
  markError.value = ''
}

async function confirmMark() {
  if (!markFor.value || !markAgent.value) return
  markBusy.value = true
  markError.value = ''
  try {
    const ao = await api.markOrderForAgent(markFor.value.id, markAgent.value)
    markFor.value = null
    navigateTo('/agents')
  }
  catch (e: unknown) {
    markError.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not mark the order.'
  }
  finally { markBusy.value = false }
}

// §20 dropship: the supplier ships this order direct to the customer —
// no agent, no putaway. Creates a prepaid corridor leg on /sourcing.
async function confirmRelay() {
  if (!relayFor.value) return
  relayBusy.value = true
  relayError.value = ''
  try {
    await api.relayOrderToSupplier(relayFor.value.id)
    relayFor.value = null
    navigateTo('/sourcing')
  }
  catch (e: unknown) {
    relayError.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not relay the order.'
  }
  finally { relayBusy.value = false }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Orders</h1>
        <div class="sub">The central operational object (§19) — state-driven from confirmation to settlement</div>
      </div>
      <div class="row">
        <select v-model="statusFilter">
          <option value="">All statuses</option>
          <option v-for="s in ['pending_confirmation','confirmed','processing','fulfilled','in_transit','out_for_delivery','delivered','cancelled','failed','returned','refunded']" :key="s" :value="s">{{ s.replaceAll('_',' ') }}</option>
        </select>
        <button @click="showForm = true">New order</button>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading orders…</div>
    <div v-else class="card" style="padding:0">
      <table>
        <thead>
          <tr><th>#</th><th>Customer</th><th>Items</th><th>Total</th><th>Method</th><th>Payment</th><th>Status</th><th>Created</th><th>AGM</th></tr>
        </thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id">
            <td><NuxtLink :to="`/orders/${o.id}`" class="mono">#{{ o.id }}</NuxtLink></td>
            <td>{{ o.customer_name }}<div class="muted mono" style="font-size:.72rem">{{ o.customer_phone }}</div></td>
            <td class="muted">view in detail</td>
            <td><strong>{{ money(o.total) }}</strong></td>
            <td>{{ o.payment_method.replace('_',' ') }}</td>
            <td><StatusBadge :status="o.payment_status" /></td>
            <td><StatusBadge :status="o.status" /></td>
            <td class="muted" style="font-size:.76rem">{{ date(o.created_at) }}</td>
            <td>
              <button v-if="o.status === 'confirmed'" class="ghost small" @click="openMark(o)">Fulfill via agent</button>
              <button v-if="o.status === 'confirmed'" class="ghost small" @click="relayFor = o; relayError = ''">Fulfill via supplier</button>
            </td>
          </tr>
          <tr v-if="!orders.length"><td colspan="9" class="empty">No orders</td></tr>
        </tbody>
      </table>
    </div>

    <!-- §20 dropship: relay the order to its supplier -->
    <div v-if="relayFor" class="modal-backdrop" @click.self="relayFor = null">
      <div class="modal">
        <h2>Fulfill via supplier (dropship)</h2>
        <p class="muted" style="margin-top:-.3rem">Order #{{ relayFor.id }} — {{ relayFor.customer_name }}. The supplier ships each line DIRECT to the customer, skipping the AGM. You pay the prepaid corridor leg, then track it on Sourcing (§23 ladder ends at the customer's door).</p>
        <div class="card" style="background:#f8fafc;padding:.7rem .8rem;margin-bottom:.6rem">
          <div class="muted" style="font-size:.78rem">
            · The supplier sees the recipient's address — never you, your storefront, or your prices (§9).<br>
            · Nothing lands in stock — the parcel goes straight out.<br>
            · COD orders: you still collect the cash yourself — dropship legs never carry your retail money.
          </div>
        </div>
        <div v-if="relayError" class="badge red" style="display:block;padding:.5rem">{{ relayError }}</div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="relayFor = null">Cancel</button>
          <button :disabled="relayBusy" @click="confirmRelay">{{ relayBusy ? 'Relaying…' : 'Relay to supplier' }}</button>
        </div>
      </div>
    </div>

    <!-- §20-24: mark for agent fulfillment -->
    <div v-if="markFor" class="modal-backdrop" @click.self="markFor = null">
      <div class="modal">
        <h2>Fulfill via agent</h2>
        <p class="muted" style="margin-top:-.3rem">Order #{{ markFor.id }} — {{ markFor.customer_name }}. The agent gets the alert instantly, calls the customer and ships out (§20-24).</p>
        <div v-if="!agents.length" class="badge amber" style="display:block;padding:.5rem">No agent linked yet — add one under Agents · AGM first.</div>
        <div v-else class="field">
          <label>Agent</label>
          <select v-model.number="markAgent">
            <option v-for="a in agents" :key="a.agent_org_id" :value="a.agent_org_id">
              {{ a.agent_name }} ({{ a.city }}) — {{ a.warehouses }} warehouse(s)
            </option>
          </select>
        </div>
        <div v-if="markError" class="badge red" style="display:block;padding:.5rem">{{ markError }}</div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="markFor = null">Cancel</button>
          <button :disabled="markBusy || !agents.length" @click="confirmMark">Mark for agent</button>
        </div>
      </div>
    </div>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">New order</h2>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Customer</label>
            <select v-model.number="form.customer_id">
              <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.full_name }}</option>
            </select>
          </div>
          <div class="field" style="flex:1">
            <label>Product</label>
            <select v-model.number="form.product_id">
              <option v-for="p in products" :key="p.id" :value="p.id">{{ p.title }}</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Quantity</label>
            <input v-model.number="form.qty" type="number" min="1" />
          </div>
          <div class="field" style="flex:1">
            <label>Payment method</label>
            <select v-model="form.payment_method">
              <option value="cod">Cash on delivery</option>
              <option value="online_transfer">Online transfer</option>
              <option value="card">Card</option>
            </select>
          </div>
        </div>
        <div class="card" style="background:#f8fafc;margin-bottom:1rem">
          <div class="spread">
            <span class="muted">Unit price (Ecos price)</span>
            <strong>{{ money(unitPrice) }}</strong>
          </div>
          <div class="spread">
            <span class="muted">Order total</span>
            <strong>{{ money(unitPrice * form.qty) }}</strong>
          </div>
        </div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="showForm = false">Cancel</button>
          <button :disabled="busy" @click="create">Create order</button>
        </div>
      </div>
    </div>
  </div>
</template>

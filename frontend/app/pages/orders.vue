<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const orders = ref<Order[]>([])
const stores = ref<Store[]>([])
const customers = ref<{ id: number; full_name: string; store_id: number }[]>([])
const products = ref<Product[]>([])
const loading = ref(true)
const statusFilter = ref('')
const showForm = ref(false)
const busy = ref(false)

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
  const [s, l, p] = await Promise.all([
    api.stores(),
    $fetch<{ id: number; store_id: number; full_name: string }[]>('/api/customers'),
    api.products({ status: 'active' }),
  ])
  stores.value = s
  customers.value = l
  products.value = p
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
          <tr><th>#</th><th>Customer</th><th>Items</th><th>Total</th><th>Method</th><th>Payment</th><th>Status</th><th>Created</th></tr>
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
          </tr>
          <tr v-if="!orders.length"><td colspan="8" class="empty">No orders</td></tr>
        </tbody>
      </table>
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

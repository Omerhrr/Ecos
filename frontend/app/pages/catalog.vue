<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const products = ref<Product[]>([])
const suppliers = ref<Supplier[]>([])
const loading = ref(true)
const showForm = ref(false)
const busy = ref(false)
const statusFilter = ref('')

const form = reactive({
  supplier_id: 0, title: '', category: 'electronics', supplier_cost: 100,
  weight_kg: 0.5, markup_pct: null as number | null, stock: 50, description: '',
})

const pricePreview = computed(() => {
  // mirror of the pricing engine for the form preview
  const fx = 215
  const cost = form.supplier_cost * fx
  const logistics = form.weight_kg * 3800
  const payment = (cost + logistics) * 0.015
  const luxeen = cost * 0.08
  const markup = form.markup_pct ?? 0.10
  return Math.round(((cost + logistics + payment + luxeen) * 1 + cost * markup) / 5) * 5
})

async function load() {
  loading.value = true
  try {
    const [p, s] = await Promise.all([
      api.products(statusFilter.value ? { status: statusFilter.value } : undefined),
      api.suppliers(),
    ])
    products.value = p
    suppliers.value = s
    if (!form.supplier_id && s.length) form.supplier_id = s[0].id
  }
  finally { loading.value = false }
}

onMounted(load)
watch(statusFilter, load)

async function create() {
  busy.value = true
  try {
    await api.createProduct({ ...form, markup_pct: form.markup_pct ?? undefined })
    showForm.value = false
    await load()
  }
  finally { busy.value = false }
}

async function toggleStatus(p: Product) {
  await api.patchProduct(p.id, { status: p.status === 'active' ? 'archived' : 'active' })
  await load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Catalog</h1>
        <div class="sub">Supplier data normalized into Ecos products — pricing via the pricing engine (§12)</div>
      </div>
      <div class="row">
        <select v-model="statusFilter">
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="archived">Archived</option>
        </select>
        <button @click="showForm = true">Add product</button>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading catalog…</div>
    <div v-else class="card" style="padding:0">
      <table>
        <thead>
          <tr>
            <th>Product</th><th>Category</th><th>Supplier</th>
            <th>Cost (CNY)</th><th>Ecos price</th><th>Stock</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in products" :key="p.id">
            <td>
              <strong>{{ p.title }}</strong>
              <div class="muted" style="font-size:.75rem">{{ p.weight_kg }} kg · lead {{ p.supplier_lead_time_days ?? '—' }}d</div>
            </td>
            <td>{{ p.category }}</td>
            <td>{{ p.supplier_name }}</td>
            <td class="mono">¥{{ p.supplier_cost }}</td>
            <td>
              <strong>{{ money(p.pricing.ecos_price_ngn) }}</strong>
              <div class="muted mono" style="font-size:.7rem">
                fx {{ p.pricing.fx_rate }} · log {{ money(p.pricing.components.logistics) }}
              </div>
            </td>
            <td>{{ p.stock }}</td>
            <td><StatusBadge :status="p.status" /></td>
            <td>
              <button class="ghost small" @click="toggleStatus(p)">
                {{ p.status === 'active' ? 'Archive' : 'Activate' }}
              </button>
            </td>
          </tr>
          <tr v-if="!products.length"><td colspan="8" class="empty">No products</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">Add Ecos product</h2>
        <div class="field">
          <label>Supplier</label>
          <select v-model.number="form.supplier_id">
            <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }} — {{ s.city }}</option>
          </select>
        </div>
        <div class="field">
          <label>Title</label>
          <input v-model="form.title" placeholder="e.g. Mini Projector HD" />
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Category</label>
            <input v-model="form.category" />
          </div>
          <div class="field" style="flex:1">
            <label>Supplier cost (CNY)</label>
            <input v-model.number="form.supplier_cost" type="number" min="1" />
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Weight (kg)</label>
            <input v-model.number="form.weight_kg" type="number" step="0.05" min="0.05" />
          </div>
          <div class="field" style="flex:1">
            <label>Markup % (blank = network default 10%)</label>
            <input v-model.number="form.markup_pct" type="number" step="0.01" min="0" />
          </div>
          <div class="field" style="flex:1">
            <label>Stock</label>
            <input v-model.number="form.stock" type="number" min="0" />
          </div>
        </div>
        <div class="card" style="background:#f8fafc;margin-bottom:1rem">
          <div class="spread">
            <span class="muted">Estimated Ecos price (NGN)</span>
            <strong>{{ money(pricePreview) }}</strong>
          </div>
          <div class="muted" style="font-size:.72rem;margin-top:.3rem">
            waterfall: cost × fx + logistics (per kg) + payment + Luxeen economics + operator margin
          </div>
        </div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="showForm = false">Cancel</button>
          <button :disabled="busy || !form.title" @click="create">Create product</button>
        </div>
      </div>
    </div>
  </div>
</template>

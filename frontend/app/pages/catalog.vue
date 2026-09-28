<script setup lang="ts">
const api = useApi()
const { money, date } = useFormat()

const products = ref<Product[]>([])
const suppliers = ref<Supplier[]>([])
const loading = ref(true)
const showForm = ref(false)
const busy = ref(false)
const statusFilter = ref('')

// ---- §10 catalog depth: variants + videos manager ----
const variantTarget = ref<Product | null>(null)
const variantBusy = ref(false)
const variantError = ref('')
const variantForm = reactive({ option_name: 'Package', option_value: '', cost_delta: 0, weight_delta_kg: 0, stock: 0 })
const videosText = ref('')

function openVariants(p: Product) {
  variantTarget.value = p
  variantError.value = ''
  videosText.value = (p.videos ?? []).join('\n')
}

function closeVariants() {
  variantTarget.value = null
}

async function addVariant() {
  const p = variantTarget.value
  if (!p || !variantForm.option_value.trim()) return
  variantBusy.value = true
  variantError.value = ''
  try {
    await api.createVariant(p.id, {
      option_name: variantForm.option_name.trim(),
      option_value: variantForm.option_value.trim(),
      cost_delta: Number(variantForm.cost_delta) || 0,
      weight_delta_kg: Number(variantForm.weight_delta_kg) || 0,
      stock: Number(variantForm.stock) || 0,
    })
    variantForm.option_value = ''
    variantForm.cost_delta = 0
    variantForm.weight_delta_kg = 0
    variantForm.stock = 0
    await load()
    variantTarget.value = products.value.find(x => x.id === p.id) ?? null
  }
  catch (e: unknown) {
    const err = e as { response?: { _data?: { detail?: string } } }
    variantError.value = err.response?._data?.detail ?? 'Could not create the variant'
  }
  finally { variantBusy.value = false }
}

async function bumpVariantStock(v: ProductVariant, delta: number) {
  variantBusy.value = true
  try {
    await api.patchVariant(v.id, { stock: Math.max(0, v.stock + delta) })
    await load()
    variantTarget.value = products.value.find(x => x.id === v.product_id) ?? null
  }
  finally { variantBusy.value = false }
}

async function archiveVariantRow(v: ProductVariant) {
  variantBusy.value = true
  try {
    await api.archiveVariant(v.id)
    await load()
    variantTarget.value = products.value.find(x => x.id === v.product_id) ?? null
  }
  finally { variantBusy.value = false }
}

async function saveVideos() {
  const p = variantTarget.value
  if (!p) return
  variantBusy.value = true
  try {
    const urls = videosText.value.split('\n').map(s => s.trim()).filter(Boolean)
    await api.patchProduct(p.id, { videos: urls })
    await load()
    variantTarget.value = products.value.find(x => x.id === p.id) ?? null
  }
  finally { variantBusy.value = false }
}

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
              <div class="muted" style="font-size:.75rem">
                {{ p.weight_kg }} kg · lead {{ p.supplier_lead_time_days ?? '—' }}d
                <span v-if="p.videos?.length"> · 🎬 {{ p.videos.length }}</span>
              </div>
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
              <div class="row" style="gap:.3rem;justify-content:flex-end">
                <button class="ghost small" @click="openVariants(p)">
                  Variants ({{ p.variants?.length ?? 0 }})
                </button>
                <button class="ghost small" @click="toggleStatus(p)">
                  {{ p.status === 'active' ? 'Archive' : 'Activate' }}
                </button>
              </div>
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

    <!-- §10: variants + videos manager -->
    <div v-if="variantTarget" class="modal-backdrop" @click.self="closeVariants">
      <div class="modal">
        <h2 style="margin-bottom:.2rem">{{ variantTarget.title }}</h2>
        <div class="muted" style="font-size:.8rem;margin-bottom:1rem">
          Variants & video media — each option is priced through the same §12 waterfall
          (supplier cost delta + weight delta), never hand-set.
        </div>

        <div v-if="variantTarget.variants?.length" class="card" style="padding:0;margin-bottom:1rem">
          <table>
            <thead>
              <tr><th>SKU</th><th>Option</th><th>Ecos price</th><th>Δ vs base</th><th>Stock</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="v in variantTarget.variants" :key="v.id">
                <td class="mono" style="font-size:.75rem">{{ v.sku }}</td>
                <td><strong>{{ v.option_value }}</strong><div class="muted" style="font-size:.72rem">{{ v.option_name }}</div></td>
                <td>{{ money(v.unit_price_ngn) }}</td>
                <td :class="v.delta_vs_base_ngn > 0 ? 'ok' : 'muted'">
                  {{ v.delta_vs_base_ngn > 0 ? '+' : '' }}{{ money(v.delta_vs_base_ngn) }}
                </td>
                <td>
                  <div class="row" style="gap:.3rem">
                    <button class="ghost tiny" :disabled="variantBusy || v.stock === 0" @click="bumpVariantStock(v, -1)">−</button>
                    <b>{{ v.stock }}</b>
                    <button class="ghost tiny" :disabled="variantBusy" @click="bumpVariantStock(v, 1)">+</button>
                  </div>
                </td>
                <td><button class="ghost tiny" :disabled="variantBusy" @click="archiveVariantRow(v)">Archive</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty" style="padding:1rem">No variants yet — the base product is the only buyable face.</div>

        <div class="card" style="background:#f8fafc;margin-bottom:1rem">
          <div style="font-weight:700;font-size:.85rem;margin-bottom:.5rem">Add variant</div>
          <div class="row">
            <div class="field" style="flex:1">
              <label>Option name</label>
              <input v-model="variantForm.option_name" placeholder="e.g. Color / Package / Size" />
            </div>
            <div class="field" style="flex:2">
              <label>Option value</label>
              <input v-model="variantForm.option_value" placeholder="e.g. Arctic White" />
            </div>
          </div>
          <div class="row">
            <div class="field" style="flex:1">
              <label>Cost delta (CNY)</label>
              <input v-model.number="variantForm.cost_delta" type="number" step="0.5" />
            </div>
            <div class="field" style="flex:1">
              <label>Weight delta (kg)</label>
              <input v-model.number="variantForm.weight_delta_kg" type="number" step="0.05" />
            </div>
            <div class="field" style="flex:1">
              <label>Stock</label>
              <input v-model.number="variantForm.stock" type="number" min="0" />
            </div>
          </div>
          <button class="ghost" :disabled="variantBusy || !variantForm.option_value.trim()" @click="addVariant">
            + Add variant
          </button>
        </div>

        <div class="field">
          <label>Product videos (one URL per line)</label>
          <textarea v-model="videosText" rows="2" placeholder="https://cdn.example/demo.mp4" />
        </div>

        <div v-if="variantError" class="login-error" style="margin-bottom:.6rem">{{ variantError }}</div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" :disabled="variantBusy" @click="saveVideos">Save videos</button>
          <button @click="closeVariants">Done</button>
        </div>
      </div>
    </div>
  </div>
</template>

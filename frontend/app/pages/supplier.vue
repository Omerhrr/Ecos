<script setup lang="ts">
/**
 * Supplier portal (§8, role=supplier) — the China-side surface.
 * Upload listings -> submit -> Luxeen review -> live on the Marketstore.
 * Receive paid sourcing orders, accept, and drive the §23 tracking ladder.
 */
definePageMeta({ layout: 'supplier' })
const api = useApi()
const auth = useAuth()

const tab = ref<'products' | 'orders'>('products')
const products = ref<SupplierProduct[]>([])
const orders = ref<SourcingSupplierView[]>([])
const loading = ref(true)
const busy = ref(0)
const flash = ref('')
const error = ref('')

const uploadOpen = ref(false)
const uploadBusy = ref(false)
const form = reactive({
  title: '', category: 'electronics', industry: 'consumer-electronics',
  cost_price: 0, currency: 'CNY', weight_kg: 0.5, moq: 1, description: '',
  images: 'https://picsum.photos/seed/new-listing/800/600',
})

const trackOpen = ref(0)
const track = reactive({ code: 'picked_up', location: '', description: '' })
const TRACK_CODES = [
  'supplier_processing', 'picked_up', 'origin_warehouse', 'exported',
  'in_transit', 'customs', 'destination_hub', 'out_for_delivery', 'delivered',
]

onMounted(async () => {
  auth.restore()
  if (auth.user.value?.role !== 'supplier') { navigateTo('/login'); return }
  await load()
})

async function load() {
  loading.value = true
  try {
    products.value = await api.portalProducts()
    orders.value = await api.portalOrders()
  }
  finally { loading.value = false }
}

async function submitUpload() {
  uploadBusy.value = true
  error.value = ''
  try {
    await api.portalUploadProduct({
      title: form.title, category: form.category, industry: form.industry,
      cost_price: Number(form.cost_price), currency: form.currency,
      weight_kg: Number(form.weight_kg), moq: Number(form.moq),
      description: form.description,
      images: form.images ? form.images.split(',').map(s => s.trim()).filter(Boolean) : [],
      specs: {},
    })
    uploadOpen.value = false
    flash.value = `"${form.title}" uploaded as a draft — submit it when ready for review.`
    form.title = ''; form.cost_price = 0; form.description = ''
    await load()
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Upload failed.'
  }
  finally { uploadBusy.value = false }
}

async function act(p: SupplierProduct, action: 'submit' | 'edit-resubmit') {
  busy.value = p.id
  error.value = ''
  try {
    if (action === 'submit') await api.portalSubmitProduct(p.id)
    else await api.portalPatchProduct(p.id, { review_notes: '' })
    flash.value = action === 'submit' ? `"${p.title}" submitted to Luxeen for review.` : 'Listing reopened as draft.'
    await load()
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Action failed.'
  }
  finally { busy.value = 0 }
}

async function acceptOrder(o: SourcingSupplierView) {
  busy.value = o.id
  try {
    const updated = await api.portalAcceptOrder(o.id)
    Object.assign(o, updated)
    flash.value = `${o.order_number} accepted — post checkpoints as you process and ship.`
  }
  catch { error.value = 'Accept failed.' }
  finally { busy.value = 0 }
}

async function postTracking(o: SourcingSupplierView) {
  busy.value = o.id
  try {
    const updated = await api.portalAddTracking(o.id, { ...track })
    Object.assign(o, updated)
    trackOpen.value = 0
    track.location = ''; track.description = ''
    flash.value = `${o.order_number} → ${track.code.replace(/_/g, ' ')}`
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Checkpoint failed.'
  }
  finally { busy.value = 0 }
}

const tone = (s: string) =>
  ({ draft: 'gray', submitted: 'amber', approved: 'blue', rejected: 'red', published: 'green', archived: 'gray' }[s] ?? 'gray')
const soTone = (s: string) =>
  ({ paid: 'blue', processing: 'amber', shipped: 'blue', in_transit: 'blue', customs: 'amber', destination_hub: 'blue', arrived: 'teal', received: 'green', out_for_delivery: 'blue', delivered: 'green', cancelled: 'red', pending_payment: 'gray' }[s] ?? 'gray')
const fmt = (n: number) => '¥' + Number(n || 0).toLocaleString()
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Supplier Portal</h1>
        <div class="sub">Upload products to Ecos, pass the review gate, and fulfil paid sourcing orders. Buyers never see your identity (§9).</div>
      </div>
      <div class="row">
        <button :class="tab === 'products' ? '' : 'ghost'" @click="tab = 'products'">My listings</button>
        <button :class="tab === 'orders' ? '' : 'ghost'" @click="tab = 'orders'">
          Sourcing orders <span class="badge" :class="orders.some(o => o.status === 'paid') ? 'amber' : 'gray'">{{ orders.filter(o => o.status === 'paid').length }}</span>
        </button>
        <button @click="uploadOpen = true">+ Upload product</button>
      </div>
    </div>

    <div v-if="flash" class="badge green" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ flash }}</div>
    <div v-if="error" class="badge red" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ error }}</div>

    <!-- LISTINGS -->
    <template v-if="tab === 'products'">
      <div v-if="loading" class="muted">Loading…</div>
      <div v-else class="card" style="padding:0">
        <table>
          <thead><tr><th>Listing</th><th>Price</th><th>Weight</th><th>MOQ</th><th>Status</th><th>Review note</th><th>Actions</th></tr></thead>
          <tbody>
            <tr v-for="p in products" :key="p.id">
              <td><b>{{ p.title }}</b><div class="muted" style="font-size:.75rem">{{ p.category }} / {{ p.industry || '—' }}</div></td>
              <td>{{ fmt(p.cost_price) }} {{ p.currency }}</td>
              <td>{{ p.weight_kg }}kg</td>
              <td>{{ p.moq }}</td>
              <td><span class="badge" :class="tone(p.status)">{{ p.status }}</span></td>
              <td class="muted" style="font-size:.78rem;max-width:180px">{{ p.review_notes || '—' }}</td>
              <td>
                <button v-if="p.status === 'draft' || p.status === 'rejected'" class="small" :disabled="busy === p.id" @click="act(p, 'submit')">Submit for review</button>
                <span v-else-if="p.status === 'published'" class="badge green">live on Marketstore</span>
                <span v-else-if="p.status === 'submitted'" class="badge amber">awaiting review</span>
              </td>
            </tr>
            <tr v-if="!products.length"><td colspan="7" class="empty">No listings yet — upload your first product</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ORDERS -->
    <template v-if="tab === 'orders'">
      <div v-if="loading" class="muted">Loading…</div>
      <div v-else class="card" v-for="o in orders" :key="o.id" style="margin-bottom:.8rem">
        <div style="display:flex;justify-content:space-between;gap:.8rem;flex-wrap:wrap;align-items:center">
          <div>
            <b>{{ o.order_number }}</b> · {{ o.qty }} × {{ o.title }}
            <span v-if="o.fulfillment_mode === 'dropship'" class="badge violet" style="margin-left:.3rem">dropship — ship direct to recipient</span>
            <span class="badge" :class="soTone(o.status)" style="margin-left:.4rem">{{ o.status.replace('_',' ') }}</span>
            <div class="muted" style="font-size:.8rem;margin-top:.2rem">
              {{ fmt(o.cny_total) }} total · ship to {{ o.destination.name }}, {{ o.destination.city }}, {{ o.destination.country }}
              <template v-if="o.note"> · note: "{{ o.note }}"</template>
            </div>
          </div>
          <div style="display:flex;gap:.45rem;flex-wrap:wrap;align-items:center">
            <button v-if="o.status === 'paid'" class="small" :disabled="busy === o.id" @click="acceptOrder(o)">Accept order</button>
            <button v-if="['processing','shipped','in_transit','customs','destination_hub','arrived'].includes(o.status)" class="ghost small" @click="trackOpen = trackOpen === o.id ? 0 : o.id">
              {{ trackOpen === o.id ? 'Close' : '+ Checkpoint' }}
            </button>
            <span v-if="o.status === 'received'" class="badge green">received at destination</span>
          </div>
        </div>

        <div v-if="trackOpen === o.id" style="margin-top:.7rem;border-top:1px solid var(--border);padding-top:.6rem">
          <div class="row">
            <div class="field" style="flex:1">
              <label>Checkpoint</label>
              <select v-model="track.code">
                <option v-for="c in TRACK_CODES" :key="c" :value="c">{{ c.replace(/_/g,' ') }}</option>
              </select>
            </div>
            <div class="field" style="flex:1">
              <label>Location</label>
              <input v-model="track.location" placeholder="e.g. Shenzhen, CN">
            </div>
          </div>
          <div class="field"><label>Description</label><input v-model="track.description" placeholder="What happened at this checkpoint"></div>
          <button class="small" :disabled="busy === o.id" @click="postTracking(o)">Post checkpoint</button>
        </div>

        <div v-if="o.events?.length" style="margin-top:.6rem;display:flex;gap:.4rem;flex-wrap:wrap">
          <span v-for="e in o.events" :key="e.id" class="badge gray">{{ e.code.replace(/_/g,' ') }}</span>
        </div>
      </div>
      <div v-if="!loading && !orders.length" class="card muted">No sourcing orders yet — paid orders arrive here automatically.</div>
    </template>

    <!-- UPLOAD MODAL -->
    <div v-if="uploadOpen" class="modal-backdrop" @click.self="uploadOpen = false">
      <div class="modal">
        <h2>Upload a product</h2>
        <p class="muted" style="margin-top:-.3rem">Your listing goes to Luxeen's review gate before it reaches the Marketstore (§8).</p>
        <div class="field"><label>Title</label><input v-model="form.title" placeholder="e.g. Mini Projector HD 1080p"></div>
        <div class="row">
          <div class="field" style="flex:1"><label>Category</label>
            <select v-model="form.category"><option>electronics</option><option>home-appliances</option><option>accessories</option><option>beauty</option><option>fashion</option><option>general</option></select>
          </div>
          <div class="field" style="flex:1"><label>Industry</label>
            <select v-model="form.industry"><option>consumer-electronics</option><option>home-living</option><option>beauty</option><option>fashion</option><option>tools</option><option>toys</option></select>
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Cost price ({{ form.currency }})</label><input v-model.number="form.cost_price" type="number" min="0.01" step="0.01"></div>
          <div class="field" style="flex:1"><label>Weight (kg)</label><input v-model.number="form.weight_kg" type="number" min="0.01" step="0.01"></div>
          <div class="field" style="flex:1"><label>MOQ</label><input v-model.number="form.moq" type="number" min="1"></div>
        </div>
        <div class="field"><label>Description</label><textarea v-model="form.description" rows="3"></textarea></div>
        <div class="field"><label>Image URL</label><input v-model="form.images" placeholder="https://…"></div>
        <div class="modal-actions">
          <button class="ghost" @click="uploadOpen = false">Cancel</button>
          <button :disabled="uploadBusy || !form.title || !form.cost_price" @click="submitUpload">Upload draft</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const { date } = useFormat()

const leads = ref<Lead[]>([])
const products = ref<Product[]>([])
const loading = ref(true)
const showForm = ref(false)
const busyId = ref(0)
const advanceTarget = ref<Record<string, string>>({
  new: 'contacted',
  contacted: 'interested',
  interested: 'contacted',
})

const form = reactive({
  store_id: 1, product_id: 0, contact_name: '', contact_phone: '',
  source: 'meta_ads', campaign: '', assigned_agent: 'Bisi Agent',
})

const COLUMNS: { key: string; title: string; next?: string }[] = [
  { key: 'new', title: 'New', next: 'contacted' },
  { key: 'contacted', title: 'Contacted', next: 'interested' },
  { key: 'interested', title: 'Interested', next: undefined }, // -> convert
]

const otherLeads = computed(() =>
  leads.value.filter(l => !['new', 'contacted', 'interested'].includes(l.status)),
)

async function load() {
  loading.value = true
  try {
    const [l, p] = await Promise.all([api.leads(), api.products()])
    leads.value = l
    products.value = p.filter(x => x.status === 'active')
    if (!form.product_id && products.value.length) form.product_id = products.value[0].id
  }
  finally { loading.value = false }
}

onMounted(load)

async function create() {
  await api.createLead({ ...form })
  showForm.value = false
  await load()
}

async function advance(lead: Lead, next: string) {
  busyId.value = lead.id
  try {
    await api.patchLead(lead.id, { status: next })
    await load()
  }
  finally { busyId.value = 0 }
}

async function convert(lead: Lead) {
  busyId.value = lead.id
  try {
    await api.convertLead(lead.id)
    await load()
  }
  finally { busyId.value = 0 }
}

async function markUnreachable(lead: Lead) {
  await api.patchLead(lead.id, { status: 'unreachable' })
  await load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>CRM · Leads</h1>
        <div class="sub">New → Contacted → Interested → Order (§17) — conversion creates the customer + order</div>
      </div>
      <button @click="showForm = true">New lead</button>
    </div>

    <div v-if="loading" class="empty">Loading pipeline…</div>
    <template v-else>
      <div class="board">
        <div v-for="col in COLUMNS" :key="col.key" class="board-col">
          <h3>{{ col.title }} ({{ leads.filter(l => l.status === col.key).length }})</h3>
          <div v-for="lead in leads.filter(l => l.status === col.key)" :key="lead.id" class="lead-card">
            <div class="lc-title">{{ lead.contact_name }}</div>
            <div class="lc-meta">{{ lead.product_title }}</div>
            <div class="lc-meta mono">{{ lead.contact_phone }}</div>
            <div class="lc-meta">{{ lead.source }}<span v-if="lead.campaign"> · {{ lead.campaign }}</span></div>
            <div class="row" style="margin-top:.5rem">
              <button
                v-if="col.next" class="small"
                :disabled="busyId === lead.id" @click="advance(lead, col.next)"
              >
                → {{ col.next }}
              </button>
              <button
                v-else class="small"
                :disabled="busyId === lead.id" @click="convert(lead)"
              >
                Convert to order
              </button>
              <button class="danger small" @click="markUnreachable(lead)">Lost</button>
            </div>
          </div>
          <div v-if="!leads.some(l => l.status === col.key)" class="empty" style="padding:1rem 0">Empty</div>
        </div>
      </div>

      <div class="card" style="margin-top:1rem">
        <h2 style="margin-bottom:.6rem">Beyond the board</h2>
        <table>
          <thead>
            <tr><th>#</th><th>Contact</th><th>Product</th><th>Source</th><th>Status</th><th>Created</th></tr>
          </thead>
          <tbody>
            <tr v-for="lead in otherLeads" :key="lead.id">
              <td class="mono">{{ lead.id }}</td>
              <td>{{ lead.contact_name }}<div class="muted" style="font-size:.74rem">{{ lead.contact_phone }}</div></td>
              <td>{{ lead.product_title }}</td>
              <td>{{ lead.source }}</td>
              <td><StatusBadge :status="lead.status" /></td>
              <td class="muted" style="font-size:.78rem">{{ date(lead.created_at) }}</td>
            </tr>
            <tr v-if="!otherLeads.length"><td colspan="6" class="empty">No converted or closed leads yet</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">New lead</h2>
        <div class="field">
          <label>Product of interest</label>
          <select v-model.number="form.product_id">
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.title }} — {{ p.pricing.ecos_price_ngn.toLocaleString() }} ₦</option>
          </select>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Contact name</label>
            <input v-model="form.contact_name" />
          </div>
          <div class="field" style="flex:1">
            <label>Phone</label>
            <input v-model="form.contact_phone" placeholder="+234 …" />
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Source</label>
            <select v-model="form.source">
              <option value="meta_ads">meta_ads</option>
              <option value="tiktok">tiktok</option>
              <option value="whatsapp">whatsapp</option>
              <option value="organic">organic</option>
              <option value="referral">referral</option>
            </select>
          </div>
          <div class="field" style="flex:1">
            <label>Campaign</label>
            <input v-model="form.campaign" />
          </div>
        </div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="showForm = false">Cancel</button>
          <button :disabled="!form.contact_name || !form.contact_phone" @click="create">Create lead</button>
        </div>
      </div>
    </div>
  </div>
</template>

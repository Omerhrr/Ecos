<script setup lang="ts">
/**
 * CRM · Leads (§17) wired to the storefront (§14) and attribution (§16).
 * Storefront order intents arrive as source=storefront leads with their UTM
 * payload; the board badges the channel and resolves the owning campaign so
 * agents see exactly which campaign every lead came from.
 */
const api = useApi()
const { date } = useFormat()

const leads = ref<Lead[]>([])
const products = ref<Product[]>([])
const campaigns = ref<Campaign[]>([])
const loading = ref(true)
const showForm = ref(false)
const busyId = ref(0)
const sourceFilter = ref('all')

const form = reactive({
  store_id: 1, product_id: 0, contact_name: '', contact_phone: '',
  source: 'meta_ads', campaign: '', assigned_agent: 'Bisi Agent',
})

const COLUMNS: { key: string; title: string; next?: string }[] = [
  { key: 'new', title: 'New', next: 'contacted' },
  { key: 'contacted', title: 'Contacted', next: 'interested' },
  { key: 'interested', title: 'Interested', next: undefined }, // -> convert
]

const SOURCE_CHIPS = [
  'all', 'storefront', 'meta_ads', 'google_ads', 'tiktok', 'whatsapp', 'referral', 'organic',
]

const isStorefront = (l: Lead) => l.source === 'storefront'

const filtered = computed(() =>
  sourceFilter.value === 'all'
    ? leads.value
    : leads.value.filter(l => l.source === sourceFilter.value),
)

const boardLeads = computed(() =>
  filtered.value.filter(l => ['new', 'contacted', 'interested'].includes(l.status)),
)

const otherLeads = computed(() =>
  filtered.value.filter(l => !['new', 'contacted', 'interested'].includes(l.status)),
)

const sourceCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const l of leads.value) counts[l.source] = (counts[l.source] || 0) + 1
  return counts
})

const utmHint = (l: Lead) => {
  const parts: string[] = []
  if (l.utm?.utm_source) parts.push(l.utm.utm_source)
  if (l.utm?.landing_page) parts.push(l.utm.landing_page)
  return parts.join(' · ')
}

async function load() {
  loading.value = true
  try {
    const [l, p, c] = await Promise.all([api.leads(), api.products(), api.campaigns()])
    leads.value = l
    products.value = p.filter(x => x.status === 'active')
    campaigns.value = c.filter(x => x.status === 'active')
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
        <div class="sub">New → Contacted → Interested → Order (§17) — storefront intents (§14) land here with their campaign (§16)</div>
      </div>
      <button @click="showForm = true">New lead</button>
    </div>

    <div class="chips" style="margin-bottom:.8rem">
      <button
        v-for="s in SOURCE_CHIPS"
        :key="s"
        class="chip"
        :class="{ active: sourceFilter === s, storefront: s === 'storefront' }"
        @click="sourceFilter = s"
      >
        {{ s === 'all' ? 'All sources' : s }}
        <span class="chip-count">{{ s === 'all' ? leads.length : (sourceCounts[s] || 0) }}</span>
      </button>
    </div>

    <div v-if="loading" class="empty">Loading pipeline…</div>
    <template v-else>
      <div class="board">
        <div v-for="col in COLUMNS" :key="col.key" class="board-col">
          <h3>{{ col.title }} ({{ boardLeads.filter(l => l.status === col.key).length }})</h3>
          <div v-for="lead in boardLeads.filter(l => l.status === col.key)" :key="lead.id" class="lead-card">
            <div class="row" style="justify-content:space-between;align-items:center">
              <div class="lc-title">{{ lead.contact_name }}</div>
              <span class="src-badge" :class="isStorefront(lead) ? 'sf' : 'paid'">{{ lead.source }}</span>
            </div>
            <div class="lc-meta">{{ lead.product_title }}</div>
            <div class="lc-meta mono">{{ lead.contact_phone }}</div>
            <div v-if="lead.campaign_name" class="lc-campaign" title="Resolved campaign (§16)">
              ◈ {{ lead.campaign_name }}
            </div>
            <div v-else-if="lead.campaign" class="lc-meta">{{ lead.campaign }}</div>
            <div v-if="utmHint(lead)" class="lc-utm mono">{{ utmHint(lead) }}</div>
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
          <div v-if="!boardLeads.some(l => l.status === col.key)" class="empty" style="padding:1rem 0">Empty</div>
        </div>
      </div>

      <div class="card" style="margin-top:1rem">
        <h2 style="margin-bottom:.6rem">Beyond the board</h2>
        <table>
          <thead>
            <tr><th>#</th><th>Contact</th><th>Product</th><th>Source</th><th>Campaign</th><th>Status</th><th>Created</th></tr>
          </thead>
          <tbody>
            <tr v-for="lead in otherLeads" :key="lead.id">
              <td class="mono">{{ lead.id }}</td>
              <td>{{ lead.contact_name }}<div class="muted" style="font-size:.74rem">{{ lead.contact_phone }}</div></td>
              <td>{{ lead.product_title }}</td>
              <td><span class="src-badge" :class="isStorefront(lead) ? 'sf' : 'paid'">{{ lead.source }}</span></td>
              <td>{{ lead.campaign_name || lead.campaign || '—' }}</td>
              <td><StatusBadge :status="lead.status" /></td>
              <td class="muted" style="font-size:.78rem">{{ date(lead.created_at) }}</td>
            </tr>
            <tr v-if="!otherLeads.length"><td colspan="7" class="empty">No converted or closed leads yet</td></tr>
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
              <option value="google_ads">google_ads</option>
              <option value="tiktok">tiktok</option>
              <option value="whatsapp">whatsapp</option>
              <option value="organic">organic</option>
              <option value="referral">referral</option>
              <option value="storefront">storefront</option>
            </select>
          </div>
          <div class="field" style="flex:1">
            <label>Campaign (resolved automatically when it matches a utm key)</label>
            <input v-model="form.campaign" list="campaign-keys" placeholder="e.g. q3-lagos-electronics" />
            <datalist id="campaign-keys">
              <option v-for="c in campaigns" :key="c.id" :value="c.utm_campaign">{{ c.name }}</option>
            </datalist>
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

<style scoped>
.chips { display: flex; gap: .4rem; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--border, #2a2f3a);
  background: transparent; color: inherit;
  padding: .28rem .7rem; border-radius: 999px;
  font-size: .78rem; cursor: pointer;
}
.chip.active { border-color: var(--primary, #00b374); color: var(--primary, #00b374); }
.chip.storefront.active { border-color: #f59e0b; color: #f59e0b; }
.chip-count { opacity: .6; margin-left: .3rem; }
.src-badge {
  font-size: .64rem; letter-spacing: .04em; text-transform: uppercase;
  padding: .14rem .45rem; border-radius: 4px; font-weight: 600; white-space: nowrap;
}
.src-badge.sf { background: rgba(245, 158, 11, .14); color: #f59e0b; border: 1px solid rgba(245, 158, 11, .35); }
.src-badge.paid { background: rgba(100, 116, 139, .16); color: #94a3b8; border: 1px solid rgba(100, 116, 139, .3); }
.lc-campaign { font-size: .74rem; color: #38bdf8; margin-top: .25rem; }
.lc-utm { font-size: .68rem; opacity: .55; margin-top: .15rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

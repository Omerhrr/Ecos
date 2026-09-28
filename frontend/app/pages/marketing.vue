<script setup lang="ts">
/**
 * Marketing · Campaigns & Attribution (plan §16).
 * Where do leads, orders and naira come from? Campaign table with per-campaign
 * conversion + CPA, source breakdown, and campaign management (§16).
 */
const api = useApi()
const report = ref<AttributionReport | null>(null)
const campaigns = ref<Campaign[]>([])
const loading = ref(true)
const showForm = ref(false)
const busyId = ref(0)

const money = (n: number | null | undefined) =>
  n == null ? '—' : `₦${Math.round(n).toLocaleString()}`

const pct = (n: number) => `${(n * 100).toFixed(1)}%`

const form = reactive({
  name: '', channel: 'meta_ads', utm_campaign: '',
  landing_page_slug: '', budget_ngn: 0, notes: '',
})

const maxLeads = computed(() =>
  Math.max(1, ...(report.value?.by_source.map(s => s.leads) ?? [1])),
)

async function load() {
  loading.value = true
  try {
    const [r, c] = await Promise.all([api.attribution(), api.campaigns()])
    report.value = r
    campaigns.value = c
  }
  finally { loading.value = false }
}

onMounted(load)

async function create() {
  await api.createCampaign({ ...form, budget_ngn: Number(form.budget_ngn) || 0 })
  showForm.value = false
  Object.assign(form, { name: '', channel: 'meta_ads', utm_campaign: '', landing_page_slug: '', budget_ngn: 0, notes: '' })
  await load()
}

async function toggleStatus(c: Campaign) {
  busyId.value = c.id
  try {
    const next = c.status === 'active' ? 'paused' : 'active'
    await api.patchCampaign(c.id, { status: next })
    await load()
  }
  finally { busyId.value = 0 }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Marketing · Attribution</h1>
        <div class="sub">Campaign → lead → order (§16) — every storefront lead carries its UTM context into the CRM</div>
      </div>
      <button @click="showForm = true">New campaign</button>
    </div>

    <div v-if="loading" class="empty">Crunching attribution…</div>
    <template v-else-if="report">
      <div class="kpi-grid">
        <KpiCard label="Total leads" :value="String(report.totals.leads)" :sub="`${pct(report.totals.conversion_rate)} converted to orders`" />
        <KpiCard label="Attributed to a campaign" :value="pct(report.totals.attributed_lead_pct)" sub="rest is organic / direct" />
        <KpiCard label="Revenue (all sources)" :value="money(report.totals.revenue_ngn)" sub="live + delivered orders" />
        <KpiCard label="Media spend" :value="money(report.totals.spend_ngn)" sub="campaign budgets" />
      </div>

      <div class="card" style="margin-top:1rem">
        <h2 style="margin-bottom:.6rem">Campaign performance</h2>
        <table>
          <thead>
            <tr>
              <th>Campaign</th><th>Channel</th><th>UTM key</th><th>Spend</th>
              <th>Leads</th><th>Conv. rate</th><th>Orders</th><th>Revenue</th><th>CPA</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in report.campaigns" :key="c.id">
              <td>
                <b>{{ c.name }}</b>
                <div v-if="c.landing_page_slug" class="muted" style="font-size:.72rem">/lp/{{ c.landing_page_slug }}</div>
              </td>
              <td><span class="ch-badge">{{ c.channel }}</span></td>
              <td class="mono" style="font-size:.74rem">{{ c.utm_campaign }}</td>
              <td>{{ money(c.spend_ngn) }}</td>
              <td>{{ c.leads }}<span v-if="c.leads" class="muted"> ({{ c.converted_leads }} conv.)</span></td>
              <td>{{ pct(c.conversion_rate) }}</td>
              <td>{{ c.orders }}</td>
              <td><b>{{ money(c.revenue_ngn) }}</b></td>
              <td>{{ money(c.cpa_ngn) }}</td>
              <td>
                <button
                  class="small ghost" :disabled="busyId === c.id" @click="toggleStatus(campaigns.find(x => x.id === c.id)!)"
                >
                  {{ campaigns.find(x => x.id === c.id)?.status === 'active' ? 'Pause' : 'Activate' }}
                </button>
              </td>
            </tr>
            <tr v-if="!report.campaigns.length"><td colspan="10" class="empty">No campaigns yet — create one and tag your links with its utm_campaign key</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card" style="margin-top:1rem">
        <h2 style="margin-bottom:.6rem">Lead & revenue by source</h2>
        <div v-for="s in report.by_source" :key="s.source" class="src-row">
          <div class="src-label">
            <span class="src-badge" :class="s.source === 'storefront' ? 'sf' : 'paid'">{{ s.source }}</span>
          </div>
          <div class="src-bar-wrap">
            <div class="src-bar" :style="{ width: `${(s.leads / maxLeads) * 100}%` }" />
          </div>
          <div class="src-stats muted">
            {{ s.leads }} lead{{ s.leads === 1 ? '' : 's' }} · {{ s.orders }} order{{ s.orders === 1 ? '' : 's' }} · <b>{{ money(s.revenue_ngn) }}</b>
          </div>
        </div>
      </div>
    </template>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">New campaign</h2>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Name</label>
            <input v-model="form.name" placeholder="e.g. Q4 Detty December Push" />
          </div>
          <div class="field" style="flex:1">
            <label>Channel</label>
            <select v-model="form.channel">
              <option value="meta_ads">meta_ads</option>
              <option value="google_ads">google_ads</option>
              <option value="tiktok">tiktok</option>
              <option value="whatsapp">whatsapp</option>
              <option value="email">email</option>
              <option value="referral">referral</option>
              <option value="organic">organic</option>
              <option value="other">other</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>UTM campaign key (attribution id)</label>
            <input v-model="form.utm_campaign" placeholder="e.g. detty-december" />
          </div>
          <div class="field" style="flex:1">
            <label>Landing page slug (optional)</label>
            <input v-model="form.landing_page_slug" placeholder="e.g. smartwatch-launch" />
          </div>
        </div>
        <div class="row">
          <div class="field" style="flex:1">
            <label>Budget / spend (₦)</label>
            <input v-model.number="form.budget_ngn" type="number" min="0" />
          </div>
          <div class="field" style="flex:1">
            <label>Notes</label>
            <input v-model="form.notes" />
          </div>
        </div>
        <div class="muted" style="font-size:.76rem;margin-bottom:.8rem">
          Tag ad links as <span class="mono">?utm_campaign={{ form.utm_campaign || 'your-key' }}</span> — landing pages, PDPs and the order-intent form propagate it automatically.
        </div>
        <div class="row" style="justify-content:flex-end">
          <button class="ghost" @click="showForm = false">Cancel</button>
          <button :disabled="!form.name || !form.utm_campaign" @click="create">Create campaign</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ch-badge {
  font-size: .68rem; letter-spacing: .04em; text-transform: uppercase;
  padding: .14rem .45rem; border-radius: 4px; font-weight: 600;
  background: rgba(56, 189, 248, .12); color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, .3);
}
.src-row { display: flex; align-items: center; gap: .8rem; padding: .3rem 0; }
.src-label { width: 110px; flex-shrink: 0; }
.src-bar-wrap { flex: 1; height: 10px; border-radius: 999px; background: rgba(148, 163, 184, .12); overflow: hidden; }
.src-bar { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #00b374, #38bdf8); }
.src-stats { width: 320px; flex-shrink: 0; font-size: .78rem; text-align: right; }
</style>

<script setup lang="ts">
const api = useApi()
const { date } = useFormat()

const rows = ref<AuditRow[]>([])
const loading = ref(true)
const action = ref('')
const entityType = ref('')
const source = ref('')
const includeHttp = ref(false)
const expanded = ref<number | null>(null)

const ACTION_CHIPS = [
  '', 'product.price_changed', 'product.updated', 'product.created',
  'payment.captured', 'payment.refunded', 'finance.fx_rate_updated',
  'settlement.approved', 'settlement.executed',
  'ai.run_approved', 'market.product_published', 'market.product_reviewed',
  'identity.user_created', 'finance.profile_created', 'finance.profile_updated',
  'logistics.rate_card_created', 'http.request',
]

async function load() {
  loading.value = true
  try {
    rows.value = await api.audit({
      action: action.value || undefined,
      entity_type: entityType.value || undefined,
      source: source.value || undefined,
      include_http: includeHttp.value,
      limit: 300,
    })
  }
  finally { loading.value = false }
}

onMounted(load)

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v).slice(0, 120)
  return String(v).slice(0, 120)
}

function actionColor(a: string): string {
  if (a.includes('price') || a.includes('fx')) return 'amber'
  if (a.includes('approved') || a.includes('published') || a.includes('executed')) return 'green'
  if (a.includes('cancelled') || a.includes('refunded')) return 'red'
  if (a === 'http.request') return 'gray'
  return ''
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Audit Trail</h1>
        <div class="sub">Security &amp; audit (§44) — who changed what, when, with before/after state and authorization context</div>
      </div>
    </div>

    <div class="card" style="padding: .8rem 1rem; margin-bottom: .8rem">
      <div class="row" style="flex-wrap: wrap; gap: .5rem">
        <select v-model="action" style="max-width: 16rem" @change="load()">
          <option value="">All actions</option>
          <option v-for="a in ACTION_CHIPS.slice(1)" :key="a" :value="a">{{ a }}</option>
        </select>
        <input
          v-model="entityType"
          placeholder="entity type — product, settlement_run…"
          style="max-width: 16rem"
          @keyup.enter="load()"
        >
        <select v-model="source" style="max-width: 10rem" @change="load()">
          <option value="">All sources</option>
          <option value="api">api</option>
          <option value="ai">ai</option>
          <option value="http">http</option>
        </select>
        <label class="row" style="gap: .35rem; font-size: .78rem; align-items: center">
          <input v-model="includeHttp" type="checkbox" @change="load()"> include HTTP layer
        </label>
        <button @click="load()">Filter</button>
        <span v-if="!loading" class="muted" style="font-size:.76rem; margin-left:auto">{{ rows.length }} row(s)</span>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading audit trail…</div>
    <div v-else class="card" style="padding: 0">
      <table>
        <thead>
          <tr>
            <th>When</th><th>Actor</th><th>Action</th><th>Object</th><th>Change</th><th>Source</th><th>Auth ctx</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" :style="{ background: expanded === r.id ? '#131b2c' : '' }">
            <td class="muted" style="font-size:.72rem; white-space:nowrap">{{ date(r.created_at!) }}</td>
            <td>
              <div style="font-size:.78rem">{{ r.actor_label }}</div>
              <div class="muted" style="font-size:.68rem">{{ r.actor_role }}</div>
            </td>
            <td><span class="badge" :class="actionColor(r.action)">{{ r.action.replaceAll('_', ' ') }}</span></td>
            <td class="mono" style="font-size:.76rem">
              {{ r.entity_type }}<template v-if="r.entity_id">#{{ r.entity_id }}</template>
              <div v-if="r.path" class="muted" style="font-size:.66rem">{{ r.method }} {{ r.path }}</div>
            </td>
            <td style="font-size:.74rem; max-width: 22rem">
              <template v-if="r.changed">
                <div v-for="(c, field) in r.changed" :key="field" class="diff-line">
                  <b class="mono">{{ field }}</b>
                  <span class="diff-from">{{ fmt(c.from) }}</span>
                  →
                  <span class="diff-to">{{ fmt(c.to) }}</span>
                </div>
              </template>
              <span v-else-if="r.after" class="muted">{{ Object.keys(r.after).slice(0, 4).join(' · ') }}</span>
              <span v-else class="muted">—</span>
            </td>
            <td><span class="badge gray">{{ r.source }}</span></td>
            <td class="muted mono" style="font-size:.7rem">{{ r.auth_context || '—' }}<div v-if="r.ip" style="font-size:.64rem">{{ r.ip }}</div></td>
            <td>
              <button
                v-if="r.before || r.after"
                class="small ghost"
                @click="expanded = expanded === r.id ? null : r.id"
              >{{ expanded === r.id ? 'Hide' : 'Detail' }}</button>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="8" class="empty">No audit rows match the filters</td></tr>
        </tbody>
      </table>

      <div v-for="r in rows.filter(x => x.id === expanded)" :key="`d-${r.id}`" class="audit-detail">
        <div class="detail-cols">
          <div>
            <h4>Before</h4>
            <pre>{{ JSON.stringify(r.before, null, 2) || '—' }}</pre>
          </div>
          <div>
            <h4>After</h4>
            <pre>{{ JSON.stringify(r.after, null, 2) || '—' }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-line { margin: .1rem 0; }
.diff-from { color: #f87171; }
.diff-to { color: #00d68f; font-weight: 600; }
.audit-detail { border-top: 1px dashed #26324a; padding: .8rem 1.2rem; }
.detail-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.detail-cols h4 { margin: 0 0 .3rem; font-size: .78rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; }
.detail-cols pre {
  margin: 0; background: #0d1420; border: 1px solid #26324a; border-radius: 8px;
  padding: .6rem .8rem; font-size: .72rem; max-height: 16rem; overflow: auto;
}
</style>

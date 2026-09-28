<script setup lang="ts">
/**
 * Automation Engine (plan §41) — operator-owned WHEN/AND/THEN rules.
 * Rules evaluate on the live event bus; every evaluation lands in the
 * match log (§44 audit). Test = dry-run against the event's sample payload.
 */
const api = useApi()
const { date } = useFormat()

const rules = ref<AutomationRule[]>([])
const runs = ref<AutomationRunRow[]>([])
const events = ref<AutomationEventDef[]>([])
const loading = ref(true)
const tab = ref<'rules' | 'runs' | 'events'>('rules')
const busyId = ref(0)
const testResult = ref<Record<number, string>>({})

const showCreate = ref(false)
const error = ref('')
const form = ref(emptyForm())

function emptyForm() {
  return {
    name: '',
    description: '',
    event_type: 'order.status_changed',
    conditions: [{ path: '', op: 'eq', value: '' }] as { path: string; op: string; value: string }[],
    action_type: 'notify',
    title: '',
    body: '',
    level: 'info',
    category: 'automation',
    cooldown_seconds: 0,
  }
}

const OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'in', 'not_in', 'exists', 'truthy']
const ACTION_TYPES = [
  { type: 'notify', hint: 'in-app notification with {{path}} template interpolation' },
  { type: 'escalate', hint: 'critical-level alert for the ops floor' },
  { type: 'flag_product', hint: 'flag a product (payload product_id) for review' },
  { type: 'create_settlement_draft', hint: 'open a §27 draft run from unsettled payables' },
]

async function load() {
  loading.value = true
  try {
    const [r, rn, ev] = await Promise.all([api.automationRules(), api.automationRuns({ limit: 60 }), api.automationEvents()])
    rules.value = r
    runs.value = rn
    events.value = ev
  }
  finally { loading.value = false }
}
onMounted(load)

function sampleFor(eventType: string): string {
  return events.value.find(e => e.name === eventType)?.sample || '{}'
}

async function toggle(rule: AutomationRule) {
  busyId.value = rule.id
  try { await api.patchAutomationRule(rule.id, { enabled: !rule.enabled }); await load() }
  finally { busyId.value = 0 }
}

async function remove(rule: AutomationRule) {
  if (!confirm(`Delete rule "${rule.name}"?`)) return
  busyId.value = rule.id
  try { await api.deleteAutomationRule(rule.id); await load() }
  finally { busyId.value = 0 }
}

async function test(rule: AutomationRule) {
  busyId.value = rule.id
  testResult.value[rule.id] = 'testing…'
  const detail = (e: unknown) => {
    const err = e as { data?: { detail?: unknown }; message?: string }
    const d = err?.data?.detail
    return typeof d === 'string' ? d : d ? JSON.stringify(d) : err?.message || 'test failed'
  }
  try {
    let payload: Record<string, unknown> = {}
    try { payload = JSON.parse(sampleFor(rule.event_type)) } catch { payload = {} }
    const res = await api.testAutomationRule(rule.id, rule.event_type, payload)
    const r = res.results[0] as AutomationRunRow & { actions?: { type?: string }[] }
    const failed = (r.conditions_result || []).filter(c => !c.ok)
    const actionNames = (r.actions_executed?.length ? r.actions_executed : (r.actions || []))
      .map(a => a.type).filter(Boolean)
    testResult.value[rule.id] = (r.status === 'matched' || r.status === 'dry_run')
      ? `✓ would match — actions: ${actionNames.join(', ') || '—'}`
      : `✗ would NOT match (${failed.length} condition(s) failed against the sample payload)`
  }
  catch (e: unknown) {
    testResult.value[rule.id] = `error: ${detail(e)}`
  }
  finally { busyId.value = 0 }
}

async function create() {
  error.value = ''
  const f = form.value
  const conditions = f.conditions
    .filter(c => c.path.trim())
    .map(c => ({ path: c.path.trim(), op: c.op, value: c.value === '' ? null : (isNaN(Number(c.value)) ? c.value : Number(c.value)) }))
  const action: Record<string, unknown> = { type: f.action_type }
  if (f.action_type === 'notify' || f.action_type === 'escalate') {
    action.title = f.title || undefined
    action.body = f.body || undefined
    action.category = f.category || 'automation'
    if (f.action_type === 'notify' && f.level !== 'info') action.level = f.level
  }
  if (f.action_type === 'flag_product') action.reason = f.body || undefined
  try {
    await api.createAutomationRule({
      name: f.name, description: f.description, event_type: f.event_type,
      conditions, actions: [action], cooldown_seconds: Number(f.cooldown_seconds) || 0,
    })
    showCreate.value = false
    form.value = emptyForm()
    tab.value = 'rules'
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Create failed'
  }
}

const statusColor: Record<string, string> = {
  matched: '#00b374', condition_not_met: '#94a3b8', cooldown: '#eab308',
  dry_run: '#38bdf8', failed: '#f87171',
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Automation Engine</h1>
        <div class="sub">WHEN event AND conditions THEN actions (§41) — deterministic rules on the domain event bus; every evaluation is audited (§44)</div>
      </div>
      <button @click="showCreate = true">New rule</button>
    </div>

    <div class="tabs">
      <button :class="{ active: tab === 'rules' }" @click="tab = 'rules'">Rules ({{ rules.length }})</button>
      <button :class="{ active: tab === 'runs' }" @click="tab = 'runs'">Match log</button>
      <button :class="{ active: tab === 'events' }" @click="tab = 'events'">Event catalog ({{ events.length }})</button>
    </div>

    <div v-if="loading" class="empty">Loading…</div>

    <!-- RULES -->
    <div v-else-if="tab === 'rules'" class="card">
      <table>
        <thead>
          <tr><th>Rule</th><th>WHEN</th><th>AND</th><th>THEN</th><th>Matches</th><th>Last match</th><th>Enabled</th><th>Actions</th></tr>
        </thead>
        <tbody>
          <template v-for="r in rules" :key="r.id">
            <tr>
              <td><b>{{ r.name }}</b><div class="muted" style="font-size:.72rem;max-width:26rem">{{ r.description }}</div></td>
              <td><span class="mono chip">{{ r.event_type }}</span></td>
              <td class="muted" style="font-size:.74rem">
                <template v-if="r.conditions.length">
                  <div v-for="(c, i) in r.conditions" :key="i" class="mono">{{ c.path }} {{ c.op }} {{ JSON.stringify(c.value) }}</div>
                </template>
                <template v-else>always</template>
              </td>
              <td>
                <span v-for="(a, i) in r.actions" :key="i" class="chip action-chip">{{ a.type }}</span>
                <div v-if="r.cooldown_seconds" class="muted" style="font-size:.7rem">cooldown {{ r.cooldown_seconds }}s</div>
              </td>
              <td class="mono">{{ r.match_count }}</td>
              <td class="muted" style="font-size:.74rem">{{ r.last_matched_at ? date(r.last_matched_at) : '—' }}</td>
              <td>
                <button class="small" :class="r.enabled ? 'on' : 'ghost'" :disabled="busyId === r.id" @click="toggle(r)">
                  {{ r.enabled ? 'ON' : 'OFF' }}
                </button>
              </td>
              <td>
                <div class="row" style="gap:.3rem">
                  <button class="small ghost" :disabled="busyId === r.id" @click="test(r)">Test</button>
                  <button class="small danger" :disabled="busyId === r.id" @click="remove(r)">Delete</button>
                </div>
              </td>
            </tr>
            <tr v-if="testResult[r.id]">
              <td colspan="8" style="padding:.4rem 1rem" class="mono test-row">{{ testResult[r.id] }}</td>
            </tr>
          </template>
          <tr v-if="!rules.length"><td colspan="8" class="empty">No rules yet — create one</td></tr>
        </tbody>
      </table>
    </div>

    <!-- MATCH LOG -->
    <div v-else-if="tab === 'runs'" class="card">
      <table>
        <thead><tr><th>Time</th><th>Rule</th><th>Event</th><th>Status</th><th>Conditions</th><th>Actions taken</th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td class="muted" style="font-size:.74rem">{{ date(r.created_at) }}</td>
            <td>{{ r.rule_name }}</td>
            <td><span class="mono chip">{{ r.event_type }}</span></td>
            <td><span class="st" :style="{ color: statusColor[r.status] }">{{ r.status }}</span>
              <div v-if="r.error" class="muted" style="font-size:.7rem;max-width:16rem">{{ r.error }}</div>
            </td>
            <td class="mono muted" style="font-size:.72rem">
              <div v-for="(c, i) in r.conditions_result" :key="i" :style="{ color: c.ok ? '' : '#f87171' }">
                {{ c.path }} {{ c.op }} → {{ c.ok ? '✓' : '✗' }}
              </div>
            </td>
            <td>
              <span v-for="(a, i) in r.actions_executed" :key="i" class="chip action-chip">{{ a.type }}</span>
              <span v-if="a?.run_number" class="mono muted" style="font-size:.72rem"> {{ a.run_number }}</span>
            </td>
          </tr>
          <tr v-if="!runs.length"><td colspan="6" class="empty">No evaluations yet — fire some traffic</td></tr>
        </tbody>
      </table>
    </div>

    <!-- EVENT CATALOG -->
    <div v-else class="card">
      <table>
        <thead><tr><th>Event</th><th>Label</th><th>Sample payload</th></tr></thead>
        <tbody>
          <tr v-for="e in events" :key="e.name">
            <td><span class="mono chip">{{ e.name }}</span></td>
            <td>{{ e.label }}</td>
            <td class="mono muted" style="font-size:.72rem">{{ e.sample }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- CREATE MODAL -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal wide">
        <h2 style="margin-bottom:.8rem">New automation rule</h2>
        <div class="field"><label>Name</label><input v-model="form.name" placeholder="e.g. Big COD order -> alert ops" /></div>
        <div class="field"><label>Description</label><input v-model="form.description" placeholder="why this rule exists" /></div>
        <div class="field">
          <label>WHEN event</label>
          <select v-model="form.event_type">
            <option v-for="e in events" :key="e.name" :value="e.name">{{ e.label }} ({{ e.name }})</option>
          </select>
        </div>
        <div class="field">
          <label>AND conditions (dot-path into the payload — leave path empty for "always")</label>
          <div v-for="(c, i) in form.conditions" :key="i" class="row cond-row">
            <input v-model="c.path" placeholder="path e.g. to / total_ngn" style="flex:1.4" />
            <select v-model="c.op" style="flex:.7">
              <option v-for="op in OPS" :key="op" :value="op">{{ op }}</option>
            </select>
            <input v-model="c.value" placeholder="value" style="flex:1" />
            <button class="ghost small" @click="form.conditions.push({ path: '', op: 'eq', value: '' })">+</button>
          </div>
        </div>
        <div class="grid3">
          <div class="field">
            <label>THEN action</label>
            <select v-model="form.action_type">
              <option v-for="a in ACTION_TYPES" :key="a.type" :value="a.type">{{ a.type }}</option>
            </select>
          </div>
          <div class="field" v-if="form.action_type === 'notify'">
            <label>Level</label>
            <select v-model="form.level"><option>info</option><option>success</option><option>warning</option><option>critical</option></select>
          </div>
          <div class="field">
            <label>Cooldown (seconds, 0 = every match)</label>
            <input v-model="form.cooldown_seconds" type="number" min="0" />
          </div>
        </div>
        <div class="field" v-if="form.action_type === 'notify' || form.action_type === 'escalate'">
          <label>Title (payload tokens like &#123;&#123;order_id&#125;&#125; interpolate)</label>
          <input v-model="form.title" placeholder="e.g. Order #12 needs attention" />
        </div>
        <div class="field" v-if="['notify', 'escalate', 'flag_product'].includes(form.action_type)">
          <label>{{ form.action_type === 'flag_product' ? 'Reason' : 'Body' }}</label>
          <input v-model="form.body" placeholder="supports payload tokens like order_id / delta" />
        </div>
        <div class="muted" style="font-size:.74rem">
          Sample payload for <span class="mono">{{ form.event_type }}</span>: <span class="mono">{{ sampleFor(form.event_type) }}</span>
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showCreate = false">Cancel</button>
          <button @click="create">Create rule</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: .4rem; margin: .8rem 0; }
.tabs button { background: transparent; border: 1px solid #26324a; color: #94a3b8; padding: .35rem .9rem; border-radius: 8px; cursor: pointer; font-size: .8rem; }
.tabs button.active { color: #e2e8f0; border-color: #00b374; background: rgba(0, 179, 116, .08); }
.chip { background: #131b2c; border: 1px solid #26324a; border-radius: 6px; padding: .1rem .45rem; font-size: .72rem; }
.action-chip { color: #7dd3fc; margin-right: .25rem; display: inline-block; }
.cond-row { margin-bottom: .35rem; gap: .35rem; }
.grid3 { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: .6rem; }
.st { font-weight: 600; font-size: .78rem; }
.err { color: #f87171; font-size: .8rem; margin-top: .5rem; }
.test-row { color: #7dd3fc; font-size: .74rem; }
.modal.wide { width: min(720px, 94vw); }
button.on { border-color: #00b374; color: #00b374; }
</style>

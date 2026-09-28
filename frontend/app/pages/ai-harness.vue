<script setup lang="ts">
/**
 * AI Harness (plan §31+). DeepSeek-powered operator bench with
 * human-in-the-loop governance: every state-changing run produces a
 * proposal that a human approves before the side effect executes.
 */
const api = useApi()
const { date } = useFormat()

const provider = ref<AiProviderInfo | null>(null)
const operators = ref<AiOperator[]>([])
const registry = ref<AiBlueprint[]>([])
const runs = ref<AiRun[]>([])
const loading = ref(true)
const busyId = ref(0)

const showRun = ref<AiOperator | null>(null)
const runParams = reactive<Record<string, string>>({})
const showDeploy = ref(false)
const viewRun = ref<AiRun | null>(null)
const error = ref('')

// §31 live-key probe
const testing = ref(false)
const testOk = ref(false)
const testMsg = ref('')

const products = ref<{ id: number; title: string }[]>([])
const leads = ref<{ id: number; contact_name: string }[]>([])

async function load() {
  loading.value = true
  try {
    const [p, o, r, runsList] = await Promise.all([
      api.aiProvider(), api.aiOperators(), api.aiRegistry(), api.aiRuns(),
    ])
    provider.value = p
    operators.value = o
    registry.value = r
    runs.value = runsList
  }
  finally { loading.value = false }
}
onMounted(load)

async function openRun(op: AiOperator) {
  error.value = ''
  showRun.value = op
  Object.keys(runParams).forEach(k => delete runParams[k])
  if (op.input_fields.some(f => f.key === 'product_id') && !products.value.length) {
    products.value = (await api.products()).map(p => ({ id: p.id, title: p.title }))
  }
  if (op.input_fields.some(f => f.key === 'lead_id') && !leads.value.length) {
    leads.value = (await api.leads()).map(l => ({ id: l.id, contact_name: l.contact_name }))
  }
}

async function run() {
  if (!showRun.value) return
  error.value = ''
  busyId.value = showRun.value.id
  try {
    const params: Record<string, unknown> = {}
    for (const f of showRun.value.input_fields) {
      const raw = runParams[f.key]
      if (raw != null && raw !== '') {
        params[f.key] = f.type === 'number' ? Number(raw) : raw
      }
      else if (f.required) { error.value = `${f.label} is required`; return }
    }
    const fresh = await api.runAiOperator(showRun.value.id, params)
    showRun.value = null
    viewRun.value = fresh
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Run failed'
  }
  finally { busyId.value = 0 }
}

async function testProvider() {
  testing.value = true
  testMsg.value = ''
  try {
    const res = await api.aiProviderTest()
    testOk.value = true
    testMsg.value = `live ✓ ${res.model} in ${res.latency_ms}ms — "${res.reply?.trim()}"`
  }
  catch (e: unknown) {
    testOk.value = false
    testMsg.value = (e as Error)?.data?.detail || (e as Error)?.message || 'test failed'
  }
  finally { testing.value = false }
}

async function deploy(b: AiBlueprint) {
  await api.deployAiOperator(b.code)
  showDeploy.value = false
  await load()
}

async function toggleStatus(op: AiOperator) {
  await api.patchAiOperator(op.id, { status: op.status === 'active' ? 'paused' : 'active' })
  await load()
}

async function act(run: AiRun, action: 'approve' | 'reject') {
  busyId.value = run.id
  try {
    const fresh = await api.aiRunAction(run.id, action, action === 'reject' ? { note: 'Rejected by approver' } : {})
    viewRun.value = fresh
    await load()
  }
  finally { busyId.value = 0 }
}

const proposalColor: Record<string, string> = {
  pending: '#eab308', applied: '#00b374', rejected: '#f87171',
  advisory: '#38bdf8', approved: '#38bdf8',
}
const pretty = (o: Record<string, unknown>) => JSON.stringify(o, null, 2)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>AI Harness</h1>
        <div class="sub">operator bench with human-in-the-loop governance (§31–38) — runs produce proposals; approvals execute the side effects</div>
      </div>
      <button class="ghost" @click="showDeploy = true">Deploy operator</button>
    </div>

    <div class="card pad prov">
      <div>
        <span class="dot" :class="{ live: provider?.key_configured }" />
        <b v-if="provider?.key_configured">DeepSeek harness</b>
        <b v-else>Heuristic fallback</b>
        <span class="muted" style="margin-left:.5rem">
          model <span class="mono">{{ provider?.model }}</span>
          <template v-if="provider?.key_configured"> · {{ provider?.base_url }}</template>
        </span>
        <button class="small ghost" style="margin-left:.8rem" :disabled="testing" @click="testProvider">
          {{ testing ? 'Pinging…' : 'Test live key' }}
        </button>
        <span v-if="testMsg" class="mono" style="font-size:.74rem;margin-left:.6rem" :style="{ color: testOk ? '#00d68f' : '#f87171' }">{{ testMsg }}</span>
      </div>
      <div class="muted" style="font-size:.76rem">
        <template v-if="provider?.key_configured">Live DeepSeek inference (§31).</template>
        <template v-else>
          No <span class="mono">DEEPSEEK_API_KEY</span> set — operators run on the deterministic
          heuristic engine derived from live Ecos data. Add the key to the project-root <span class="mono">.env</span> and restart to switch to DeepSeek.
        </template>
      </div>
    </div>

    <div class="ops">
      <div v-for="op in operators" :key="op.id" class="card pad op">
        <div class="row" style="justify-content:space-between;align-items:flex-start">
          <div>
            <h3 style="margin:0">{{ op.name }}</h3>
            <div class="muted" style="font-size:.76rem;margin-top:.15rem">{{ op.role_description }}</div>
          </div>
          <span class="st" :style="{ color: op.status === 'active' ? '#00b374' : '#94a3b8' }">{{ op.status }}</span>
        </div>
        <div class="row meta">
          <span class="muted">{{ op.runs_total }} runs</span>
          <span v-if="op.runs_pending" class="pend">{{ op.runs_pending }} pending approval</span>
          <span v-if="op.advisory" class="adv">advisory</span>
        </div>
        <div class="row" style="gap:.4rem;margin-top:.7rem;flex-wrap:wrap">
          <button class="small" :disabled="op.status !== 'active' || busyId === op.id" @click="openRun(op)">Run</button>
          <button class="small ghost" @click="toggleStatus(op)">{{ op.status === 'active' ? 'Pause' : 'Activate' }}</button>
        </div>
      </div>
      <div v-if="!operators.length && !loading" class="card pad empty">No operators deployed yet</div>
    </div>

    <div v-if="loading" class="empty" style="margin-top:1rem">Loading harness…</div>
    <div v-else class="card" style="margin-top:1rem">
      <table>
        <thead>
          <tr><th>Run</th><th>Operator</th><th>Exec</th><th>Proposal</th><th>Provider</th><th>Tokens</th><th>Latency</th><th>When</th><th>Actions</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td class="mono">#{{ r.id }}</td>
            <td>{{ r.operator_name }}<div class="muted" style="font-size:.7rem">{{ r.operator_code }}</div></td>
            <td><StatusBadge :status="r.status === 'succeeded' ? 'succeeded' : 'failed'" /></td>
            <td>
              <span v-if="r.proposal_status" class="st" :style="{ color: proposalColor[r.proposal_status] || 'inherit' }">
                {{ r.proposal_status }}
              </span>
              <span v-else class="muted">—</span>
            </td>
            <td class="muted" style="font-size:.74rem">{{ r.provider }}<div class="mono" style="font-size:.68rem">{{ r.model }}</div></td>
            <td class="mono muted" style="font-size:.74rem">{{ r.prompt_tokens }}/{{ r.completion_tokens }}</td>
            <td class="mono muted" style="font-size:.74rem">{{ r.latency_ms }}ms</td>
            <td class="muted" style="font-size:.74rem">{{ date(r.created_at) }}</td>
            <td>
              <div class="row" style="gap:.3rem;flex-wrap:wrap">
                <button class="small ghost" @click="viewRun = r">View</button>
                <button v-if="r.proposal_status === 'pending'" class="small" :disabled="busyId === r.id" @click="act(r, 'approve')">Approve</button>
                <button v-if="r.proposal_status === 'pending'" class="small danger" :disabled="busyId === r.id" @click="act(r, 'reject')">Reject</button>
              </div>
            </td>
          </tr>
          <tr v-if="!runs.length"><td colspan="9" class="empty">No runs yet — hit Run on an operator</td></tr>
        </tbody>
      </table>
    </div>

    <!-- run modal: blueprint inputs -->
    <div v-if="showRun" class="modal-backdrop" @click.self="showRun = null">
      <div class="modal">
        <h2 style="margin-bottom:.3rem">Run {{ showRun.name }}</h2>
        <div class="muted" style="font-size:.78rem;margin-bottom:1rem">{{ showRun.role_description }}</div>
        <div v-for="f in showRun.input_fields" :key="f.key" class="field">
          <label>{{ f.label }}</label>
          <select v-if="f.key === 'product_id'" v-model.number="runParams[f.key]">
            <option v-for="p in products" :key="p.id" :value="p.id">#{{ p.id }} — {{ p.title }}</option>
          </select>
          <select v-else-if="f.key === 'lead_id'" v-model.number="runParams[f.key]">
            <option v-for="l in leads" :key="l.id" :value="l.id">#{{ l.id }} — {{ l.contact_name }}</option>
          </select>
          <textarea v-else-if="f.type === 'text'" v-model="runParams[f.key]" rows="3"
            :placeholder="f.placeholder || ''" />
          <input v-else v-model="runParams[f.key]" :type="f.type" />
        </div>
        <div v-if="!showRun.input_fields.length" class="muted" style="font-size:.8rem">
          This operator needs no input — it reads the whole working set.
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showRun = null">Cancel</button>
          <button :disabled="busyId === showRun.id" @click="run">Run operator</button>
        </div>
      </div>
    </div>

    <!-- deploy modal -->
    <div v-if="showDeploy" class="modal-backdrop" @click.self="showDeploy = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">Deploy operator</h2>
        <div v-for="b in registry" :key="b.code" class="bp">
          <div class="row" style="justify-content:space-between;align-items:center">
            <div>
              <b>{{ b.name }}</b> <span class="mono muted" style="font-size:.7rem">{{ b.code }}</span>
              <div class="muted" style="font-size:.76rem">{{ b.role_description }}</div>
            </div>
            <button class="small" @click="deploy(b)">Deploy</button>
          </div>
        </div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showDeploy = false">Close</button>
        </div>
      </div>
    </div>

    <!-- output viewer -->
    <div v-if="viewRun" class="modal-backdrop" @click.self="viewRun = null">
      <div class="modal wide">
        <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:.6rem">
          <h2 style="margin:0">Run #{{ viewRun.id }} · {{ viewRun.operator_name }}</h2>
          <span v-if="viewRun.proposal_status" class="st" :style="{ color: proposalColor[viewRun.proposal_status] }">
            {{ viewRun.proposal_status }}
          </span>
        </div>
        <div v-if="viewRun.error" class="err">{{ viewRun.error }}</div>
        <div class="row" style="gap:.6rem;margin:.5rem 0;flex-wrap:wrap">
          <span class="kv">provider <b>{{ viewRun.provider }}</b></span>
          <span class="kv">model <b class="mono">{{ viewRun.model }}</b></span>
          <span class="kv">tokens <b class="mono">{{ viewRun.prompt_tokens }}/{{ viewRun.completion_tokens }}</b></span>
          <span class="kv">latency <b class="mono">{{ viewRun.latency_ms }}ms</b></span>
        </div>
        <div v-if="viewRun.output?.applied" class="applied">
          <b>Applied side effect</b>
          <pre class="json">{{ pretty(viewRun.output.applied as Record<string, unknown>) }}</pre>
        </div>
        <div class="lbl muted">Input</div>
        <pre class="json">{{ pretty(viewRun.input) }}</pre>
        <div class="lbl muted">Output</div>
        <pre class="json">{{ pretty(viewRun.output) }}</pre>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="viewRun = null">Close</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card.pad { padding: 1rem 1.2rem; }
.prov { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
.dot { display: inline-block; width: .55rem; height: .55rem; border-radius: 999px; background: #94a3b8; margin-right: .45rem; }
.dot.live { background: #00b374; box-shadow: 0 0 8px rgba(0, 179, 116, .7); }
.ops { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: .8rem; }
.op .meta { gap: .6rem; font-size: .74rem; margin-top: .5rem; }
.pend { color: #eab308; }
.adv { color: #38bdf8; border: 1px solid rgba(56, 189, 248, .4); border-radius: 4px; padding: 0 .35rem; font-size: .68rem; }
.st { font-weight: 600; font-size: .8rem; }
.bp { border: 1px solid rgba(148, 163, 184, .18); border-radius: 8px; padding: .7rem .9rem; }
.bp + .bp { margin-top: .6rem; }
.err { color: #f87171; font-size: .8rem; margin-top: .5rem; }
.lbl { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; margin-top: .7rem; }
.json {
  background: rgba(0, 0, 0, .28); border: 1px solid rgba(148, 163, 184, .16);
  border-radius: 8px; padding: .7rem .9rem; font-size: .74rem;
  overflow: auto; max-height: 220px; margin: .35rem 0 0;
}
.kv { font-size: .74rem; color: #94a3b8; }
.modal.wide { max-width: 760px; width: 92%; }
.applied {
  border: 1px solid rgba(0, 179, 116, .45); background: rgba(0, 179, 116, .08);
  border-radius: 8px; padding: .6rem .9rem; font-size: .8rem; margin-top: .4rem;
}
</style>

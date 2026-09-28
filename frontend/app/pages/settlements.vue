<script setup lang="ts">
/**
 * Settlements (plan §27).
 * Obligations are derived from the immutable ledger: a run buckets
 * unsettled payables by resolved counterparty, an approver signs off,
 * execution stamps the ledger entries and fires settlement.completed.
 */
const api = useApi()
const { date } = useFormat()

const runs = ref<SettlementRun[]>([])
const preview = ref<SettlementPreview | null>(null)
const loading = ref(true)
const busyId = ref(0)
const expanded = ref<number | null>(null)
const showBuild = ref(false)
const note = ref('')
const error = ref('')

const money = (n: number | null | undefined) =>
  n == null ? '—' : `₦${Math.round(n).toLocaleString()}`

async function load() {
  loading.value = true
  try {
    const [r, p] = await Promise.all([api.settlements(), api.settlementPreview()])
    runs.value = r
    preview.value = p
  }
  finally { loading.value = false }
}
onMounted(load)

async function build() {
  error.value = ''
  try {
    await api.buildSettlement({ note: note.value })
    showBuild.value = false
    note.value = ''
    await load()
  }
  catch (e: unknown) {
    error.value = (e as Error)?.data?.detail || (e as Error)?.message || 'Build failed'
  }
}

async function act(run: SettlementRun, action: 'approve' | 'execute' | 'cancel') {
  busyId.value = run.id
  try {
    await api.settlementAction(run.id, action)
    await load()
  }
  finally { busyId.value = 0 }
}

async function toggle(run: SettlementRun) {
  expanded.value = expanded.value === run.id ? null : run.id
  if (expanded.value === run.id && !run.lines) {
    const detail = await api.settlement(run.id)
    run.lines = detail.lines
  }
}

const statusColor: Record<string, string> = {
  draft: '#eab308', approved: '#38bdf8', executed: '#00b374', cancelled: '#94a3b8',
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Settlements</h1>
        <div class="sub">draft → approved → executed (§27) — unsettled ledger payables bucketed by counterparty; execution stamps the ledger and fires settlement.completed</div>
      </div>
      <button :disabled="!preview?.lines.length" @click="showBuild = true">New settlement run</button>
    </div>

    <div class="grid2">
      <div class="card pad">
        <h3 style="margin-bottom:.6rem">Unsettled payables</h3>
        <div v-if="preview && preview.lines.length">
          <table>
            <thead><tr><th>Counterparty</th><th>Type</th><th>Entries</th><th style="text-align:right">Amount</th></tr></thead>
            <tbody>
              <tr v-for="l in preview.lines" :key="l.entry_type + l.counterparty">
                <td>{{ l.counterparty }}</td>
                <td class="muted" style="font-size:.74rem">{{ l.entry_type }}</td>
                <td class="mono">{{ l.entry_count }}</td>
                <td style="text-align:right" class="mono">{{ money(l.amount) }}</td>
              </tr>
              <tr>
                <td><b>Total payable</b></td><td /><td class="mono">{{ preview.entry_count }}</td>
                <td style="text-align:right" class="mono"><b>{{ money(preview.total_amount) }}</b></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">Everything settled — payables appear here as orders deliver and payments land.</div>
      </div>

      <div class="card pad">
        <h3 style="margin-bottom:.6rem">How settlement works</h3>
        <ol class="how">
          <li><b>Build</b> — unsettled negative ledger entries (supplier, logistics, processor, Luxeen, operator, customer refunds) are bucketed into a draft run.</li>
          <li><b>Approve</b> — finance approver signs off the batch (governance).</li>
          <li><b>Execute</b> — every underlying ledger entry is stamped settled (traceable via entry_ids) and <span class="mono">settlement.completed</span> fires for downstream payouts.</li>
        </ol>
        <div class="muted" style="font-size:.78rem;margin-top:.6rem">
          Balances are never stored as mutable state — they are always derived from the ledger (§26/§45).
        </div>
      </div>
    </div>

    <div v-if="loading" class="empty" style="margin-top:1rem">Loading runs…</div>
    <div v-else class="card" style="margin-top:1rem">
      <table>
        <thead>
          <tr><th></th><th>Run</th><th>Status</th><th>Lines</th><th>Entries</th><th style="text-align:right">Total</th><th>Created</th><th>Executed</th><th>Actions</th></tr>
        </thead>
        <tbody>
          <template v-for="r in runs" :key="r.id">
            <tr>
              <td><button class="ghost small" @click="toggle(r)">{{ expanded === r.id ? '▾' : '▸' }}</button></td>
              <td class="mono">{{ r.run_number }}<div class="muted" style="font-size:.72rem">{{ r.note }}</div></td>
              <td><span class="st" :style="{ color: statusColor[r.status] }">{{ r.status }}</span></td>
              <td class="mono">{{ r.line_count }}</td>
              <td class="mono">{{ r.entry_count }}</td>
              <td style="text-align:right" class="mono"><b>{{ money(r.total_amount) }}</b> <span class="muted">{{ r.currency }}</span></td>
              <td class="muted" style="font-size:.76rem">{{ date(r.created_at) }}</td>
              <td class="muted" style="font-size:.76rem">{{ r.executed_at ? date(r.executed_at) : '—' }}</td>
              <td>
                <div class="row" style="gap:.3rem;flex-wrap:wrap">
                  <button v-if="r.status === 'draft'" class="small" :disabled="busyId === r.id" @click="act(r, 'approve')">Approve</button>
                  <button v-if="r.status === 'approved'" class="small" :disabled="busyId === r.id" @click="act(r, 'execute')">Execute</button>
                  <button v-if="r.status === 'draft' || r.status === 'approved'" class="small danger" :disabled="busyId === r.id" @click="act(r, 'cancel')">Cancel</button>
                  <span v-if="r.status === 'executed' || r.status === 'cancelled'" class="muted" style="font-size:.74rem">—</span>
                </div>
              </td>
            </tr>
            <tr v-if="expanded === r.id">
              <td />
              <td colspan="8">
                <table class="inner">
                  <thead><tr><th>Counterparty</th><th>Entry type</th><th>Entries</th><th>Ledger entry ids</th><th style="text-align:right">Amount</th></tr></thead>
                  <tbody>
                    <tr v-for="l in r.lines || []" :key="l.id">
                      <td>{{ l.counterparty }}</td>
                      <td class="muted" style="font-size:.74rem">{{ l.entry_type }}</td>
                      <td class="mono">{{ l.entry_count }}</td>
                      <td class="mono muted" style="font-size:.72rem">{{ l.entry_ids.join(', ') }}</td>
                      <td style="text-align:right" class="mono">{{ money(l.amount) }}</td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
          <tr v-if="!runs.length"><td colspan="9" class="empty">No settlement runs yet</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="showBuild" class="modal-backdrop" @click.self="showBuild = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">Build settlement run</h2>
        <p class="muted" style="font-size:.82rem">
          Captures the {{ preview?.lines.length }} unsettled counterparty buckets
          ({{ preview?.entry_count }} ledger entries, {{ money(preview?.total_amount) }}) into a draft run.
        </p>
        <div class="field">
          <label>Note</label>
          <input v-model="note" placeholder="e.g. Weekly corridor payout" />
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showBuild = false">Cancel</button>
          <button @click="build">Build draft run</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid2 { display: grid; grid-template-columns: 1.6fr 1fr; gap: 1rem; align-items: start; }
@media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
.card.pad { padding: 1rem 1.2rem; }
.how { font-size: .82rem; line-height: 1.55; padding-left: 1.1rem; }
.how li + li { margin-top: .45rem; }
.st { font-weight: 600; font-size: .8rem; }
table.inner { margin: .3rem 0 .5rem; }
table.inner th { font-size: .7rem; }
.err { color: #f87171; font-size: .8rem; margin-top: .5rem; }
</style>

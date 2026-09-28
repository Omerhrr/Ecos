<script setup lang="ts">
/**
 * Returns · RMA management (plan §28).
 * State machine: requested → approved → received → refunded / closed,
 * with rejection side-exit. `receive` flips the order to `returned` and
 * restocks; `refund` pays the customer back through the finance ledger.
 */
const api = useApi()
const { date } = useFormat()

const rmAs = ref<ReturnOrder[]>([])
const loading = ref(true)
const showForm = ref(false)
const busyId = ref(0)
const statusFilter = ref('open')

const form = reactive({
  order_id: 0, reason: 'defective', resolution: 'refund', restock: true, notes: '',
})

const REASONS = [
  'defective', 'not_as_described', 'wrong_item', 'damaged_in_transit',
  'changed_mind', 'late_delivery', 'other',
]

const OPEN_STATUSES = ['requested', 'approved', 'received']

const filtered = computed(() =>
  statusFilter.value === 'open'
    ? rmAs.value.filter(r => OPEN_STATUSES.includes(r.status))
    : statusFilter.value === 'all'
      ? rmAs.value
      : rmAs.value.filter(r => r.status === statusFilter.value),
)

const money = (n: number | null | undefined) =>
  n == null ? '—' : `₦${Math.round(n).toLocaleString()}`

async function load() {
  loading.value = true
  try {
    rmAs.value = await api.returns()
  }
  finally { loading.value = false }
}

onMounted(load)

async function openForm() {
  const eligible = await api.eligibleOrders()
  eligibleOrders.value = eligible
  if (eligible.length && !form.order_id) form.order_id = eligible[0].id
  showForm.value = true
}

const eligibleOrders = ref<EligibleOrder[]>([])

async function create() {
  await api.createReturn({ ...form, order_id: Number(form.order_id) })
  showForm.value = false
  form.order_id = 0
  await load()
}

async function act(r: ReturnOrder, action: 'approve' | 'reject' | 'receive' | 'refund' | 'close') {
  busyId.value = r.id
  try {
    await api.returnAction(r.id, action, action === 'reject' ? { note: 'Rejected by operator' } : {})
    await load()
  }
  finally { busyId.value = 0 }
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Returns · RMA</h1>
        <div class="sub">requested → approved → received → refunded (§28) — receive flips the order to `returned` and restocks; refund writes the ledger money-out entry</div>
      </div>
      <button @click="openForm">New return</button>
    </div>

    <div class="chips" style="margin-bottom:.8rem">
      <button
        v-for="s in ['open', 'requested', 'approved', 'received', 'refunded', 'closed', 'rejected', 'all']"
        :key="s" class="chip" :class="{ active: statusFilter === s }" @click="statusFilter = s"
      >
        {{ s }}
      </button>
    </div>

    <div v-if="loading" class="empty">Loading RMAs…</div>
    <div v-else class="card">
      <table>
        <thead>
          <tr>
            <th>RMA</th><th>Order</th><th>Customer</th><th>Reason</th><th>Resolution</th>
            <th>Refund</th><th>Status</th><th>Opened</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id">
            <td class="mono">{{ r.rma_number }}</td>
            <td>
              <NuxtLink :to="`/orders/${r.order_id}`" class="mono">#{{ r.order_id }}</NuxtLink>
              <div class="muted" style="font-size:.72rem">{{ money(r.order_total) }} · {{ r.order_status }}</div>
            </td>
            <td>{{ r.customer_name }}</td>
            <td><span class="rs-badge">{{ r.reason }}</span></td>
            <td>{{ r.resolution }}<span v-if="r.restock && r.resolution !== 'refund'" class="muted"> + restock</span></td>
            <td><b>{{ r.refund_amount ? money(r.refund_amount) : '—' }}</b></td>
            <td><StatusBadge :status="r.status" /></td>
            <td class="muted" style="font-size:.76rem">{{ date(r.created_at) }}</td>
            <td>
              <div class="row" style="gap:.3rem;flex-wrap:wrap">
                <button v-if="r.allowed_transitions.includes('approved')" class="small" :disabled="busyId === r.id" @click="act(r, 'approve')">Approve</button>
                <button v-if="r.allowed_transitions.includes('received')" class="small" :disabled="busyId === r.id" @click="act(r, 'receive')">Receive</button>
                <button v-if="r.allowed_transitions.includes('refunded')" class="small" :disabled="busyId === r.id" @click="act(r, 'refund')">Refund</button>
                <button v-if="r.allowed_transitions.includes('closed')" class="small ghost" :disabled="busyId === r.id" @click="act(r, 'close')">Close</button>
                <button v-if="r.allowed_transitions.includes('rejected')" class="small danger" :disabled="busyId === r.id" @click="act(r, 'reject')">Reject</button>
                <span v-if="!r.allowed_transitions.length" class="muted" style="font-size:.74rem">done</span>
              </div>
            </td>
          </tr>
          <tr v-if="!filtered.length"><td colspan="9" class="empty">No returns in this view</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
      <div class="modal">
        <h2 style="margin-bottom:1rem">Open RMA</h2>
        <div v-if="!eligibleOrders.length" class="empty">
          No returnable orders right now — orders in fulfilled / in_transit / out_for_delivery / delivered qualify.
        </div>
        <template v-else>
          <div class="field">
            <label>Order</label>
            <select v-model.number="form.order_id">
              <option v-for="o in eligibleOrders" :key="o.id" :value="o.id">
                #{{ o.id }} — {{ o.customer_name }} — {{ money(o.total) }} ({{ o.status }}, {{ o.payment_status }})
              </option>
            </select>
          </div>
          <div class="row">
            <div class="field" style="flex:1">
              <label>Reason</label>
              <select v-model="form.reason">
                <option v-for="r in REASONS" :key="r" :value="r">{{ r }}</option>
              </select>
            </div>
            <div class="field" style="flex:1">
              <label>Resolution</label>
              <select v-model="form.resolution">
                <option value="refund">refund</option>
                <option value="replacement">replacement</option>
                <option value="store_credit">store_credit</option>
              </select>
            </div>
          </div>
          <div class="field">
            <label>Notes</label>
            <input v-model="form.notes" placeholder="What did the customer say?" />
          </div>
          <label class="row" style="gap:.5rem;align-items:center;font-size:.82rem">
            <input v-model="form.restock" type="checkbox" /> Restock items when received
          </label>
        </template>
        <div class="row" style="justify-content:flex-end;margin-top:.8rem">
          <button class="ghost" @click="showForm = false">Cancel</button>
          <button :disabled="!eligibleOrders.length || !form.order_id" @click="create">Open RMA</button>
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
.rs-badge {
  font-size: .68rem; letter-spacing: .03em;
  padding: .12rem .4rem; border-radius: 4px;
  background: rgba(148, 163, 184, .14); color: #94a3b8;
}
</style>

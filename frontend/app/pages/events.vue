<script setup lang="ts">
const api = useApi()
const { date } = useFormat()

const events = ref<DomainEvent[]>([])
const filter = ref('')
const loading = ref(true)

const EVENT_COLORS: Record<string, string> = {
  product: 'green', lead: 'blue', order: 'violet', shipment: 'amber',
  payment: 'teal', finance: 'green', store: 'gray', supplier: 'gray',
}

function colorFor(name: string) {
  const prefix = name.split('.')[0]
  return EVENT_COLORS[prefix] ?? 'gray'
}

async function load() {
  loading.value = true
  try { events.value = await api.events(filter.value || undefined) }
  finally { loading.value = false }
}

onMounted(load)
watch(filter, load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Event Stream</h1>
        <div class="sub">Append-only domain event log (§40) — the audit trail feeding automation and the AI harness (§41, §31)</div>
      </div>
      <select v-model="filter">
        <option value="">All events</option>
        <option v-for="n in ['product.created','product.updated','lead.created','lead.updated','order.created','order.status_changed','shipment.created','shipment.updated','shipment.delivered','payment.received','finance.settlement_ready']" :key="n" :value="n">{{ n }}</option>
      </select>
    </div>

    <div v-if="loading" class="empty">Loading events…</div>
    <div v-else class="card" style="padding:0">
      <table>
        <thead>
          <tr><th>#</th><th>Event</th><th>Payload</th><th>When</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td class="mono">{{ e.id }}</td>
            <td><span class="badge" :class="colorFor(e.name)">{{ e.name }}</span></td>
            <td class="mono muted" style="font-size:.72rem; max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">
              {{ JSON.stringify(e.payload) }}
            </td>
            <td class="muted" style="font-size:.74rem">{{ date(e.created_at) }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="4" class="empty">No events</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

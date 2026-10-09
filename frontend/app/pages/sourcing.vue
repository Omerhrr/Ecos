<script setup lang="ts">
/**
 * Sourcing · Corridor (§11, §23) — the operator watches their prepaid
 * purchases travel the China→Nigeria ladder and receives them on arrival.
 */
const api = useApi()
const auth = useAuth()
const orders = ref<SourcingOrder[]>([])
const loading = ref(true)
const expanded = ref<number | null>(null)
const busyId = ref<number | null>(null)
const flash = ref('')

onMounted(async () => { auth.restore(); await load() })

async function load() {
  loading.value = true
  try { orders.value = await api.sourcingOrders() }
  finally { loading.value = false }
}

async function pay(o: SourcingOrder) {
  busyId.value = o.id
  try {
    const updated = await api.paySourcingOrder(o.id, 'online_transfer')
    Object.assign(o, updated)
    flash.value = `${o.order_number} paid — the supplier has been alerted.`
  }
  catch { flash.value = 'Payment failed.' }
  finally { busyId.value = null }
}

async function receive(o: SourcingOrder) {
  busyId.value = o.id
  try {
    const updated = await api.receiveSourcingOrder(o.id)
    Object.assign(o, updated)
    flash.value = `${o.order_number} received into ${o.receive_result?.warehouse ?? 'your warehouse'} — units are now sellable.`
  }
  catch (e: unknown) {
    flash.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Receive failed.'
  }
  finally { busyId.value = null }
}

async function cancel(o: SourcingOrder) {
  busyId.value = o.id
  try {
    const updated = await api.cancelSourcingOrder(o.id)
    Object.assign(o, updated)
  }
  catch { flash.value = 'Cancel failed.' }
  finally { busyId.value = null }
}

const fmt = (n: number) => '₦' + Number(n || 0).toLocaleString()
const tone = (s: string) =>
  ({ paid: 'blue', processing: 'amber', shipped: 'blue', in_transit: 'blue', customs: 'amber', destination_hub: 'blue', arrived: 'teal', received: 'green', cancelled: 'red', pending_payment: 'amber' }[s] ?? 'gray')
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Sourcing · Corridor</h1>
        <div class="sub">Your prepaid purchases travelling the China → Nigeria corridor. Money in Naira, goods on the §23 ladder.</div>
      </div>
      <NuxtLink to="/market"><button>Marketstore ↗</button></NuxtLink>
    </div>

    <div v-if="flash" class="badge green" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ flash }}</div>

    <div v-if="loading" class="muted">Loading…</div>
    <div v-else class="card" v-for="o in orders" :key="o.id" style="margin-bottom:.8rem">
      <div style="display:flex;justify-content:space-between;gap:.8rem;flex-wrap:wrap;align-items:center">
        <div>
          <b>{{ o.order_number }}</b> · {{ o.qty }} × {{ o.title }}
          <span class="badge" :class="tone(o.status)" style="margin-left:.4rem">{{ o.status.replace('_',' ') }}</span>
          <div class="muted" style="font-size:.8rem;margin-top:.25rem">
            {{ fmt(o.local_total) }} · corridor cost ¥{{ o.cny_total?.toLocaleString() }} @ {{ o.fx_rate }} ·
            {{ o.destination.via_agent ? `via agent — ${o.destination.name || 'agent warehouse'}, ${o.destination.city}` : `direct — ${o.destination.city || 'your warehouse'}` }}
          </div>
        </div>
        <div style="display:flex;gap:.45rem;flex-wrap:wrap">
          <button v-if="o.status === 'pending_payment'" class="small" :disabled="busyId === o.id" @click="pay(o)">Pay {{ fmt(o.local_total) }}</button>
          <button v-if="o.status === 'arrived' && !o.destination.via_agent" class="small" :disabled="busyId === o.id" @click="receive(o)">Receive into warehouse</button>
          <span v-if="o.status === 'arrived' && o.destination.via_agent" class="badge teal">Agent receives in AGM</span>
          <button v-if="['pending_payment','paid','processing'].includes(o.status)" class="ghost small" :disabled="busyId === o.id" @click="cancel(o)">Cancel</button>
          <button class="ghost small" @click="expanded = expanded === o.id ? null : o.id">
            {{ expanded === o.id ? 'Hide tracking' : 'Tracking' }}
          </button>
        </div>
      </div>

      <div v-if="expanded === o.id" style="margin-top:.8rem;border-top:1px solid var(--border);padding-top:.7rem">
        <div class="muted" style="font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem">Corridor timeline (§23)</div>
        <div v-for="(e, i) in o.events || []" :key="e.id" style="display:flex;gap:.7rem;padding:.3rem 0;align-items:baseline">
          <span class="muted" style="font-size:.72rem;min-width:130px">{{ e.occurred_at?.slice(0, 16).replace('T', ' ') }}</span>
          <span class="badge" :class="i === (o.events?.length ?? 0) - 1 ? 'green' : 'gray'" style="min-width:130px;text-align:center">{{ e.code.replace(/_/g,' ') }}</span>
          <span style="font-size:.85rem">{{ e.description }} <span class="muted">· {{ e.location }}</span></span>
        </div>
        <div class="muted" style="font-size:.75rem;margin-top:.5rem">
          Supplier identity withheld (§9) — you always deal with the Ecos Network.
        </div>
      </div>
    </div>
    <div v-if="!loading && !orders.length" class="muted">No sourcing orders yet — browse the Marketstore to source your first product.</div>
  </div>
</template>

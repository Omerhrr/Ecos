<script setup lang="ts">
/**
 * Agents · AGM (operator side) — add local logistics agents, watch the
 * orders you have marked for agent fulfillment (§5, §20-24).
 */
const api = useApi()
const auth = useAuth()
const directory = ref<AgentCard[]>([])
const links = ref<AgentLinkRow[]>([])
const vendorOrders = ref<AgentOrder[]>([])
const loading = ref(true)
const busy = ref(false)
const flash = ref('')

onMounted(async () => { auth.restore(); await load() })

async function load() {
  loading.value = true
  try {
    directory.value = await api.agentDirectory()
    links.value = await api.agentLinks()
    vendorOrders.value = await api.vendorAgentOrders()
  }
  finally { loading.value = false }
}

async function addAgent(c: AgentCard) {
  busy.value = true
  try {
    await api.addAgentLink(c.agent_org_id)
    flash.value = `${c.company} added — sourcing orders can now be delivered to their warehouse.`
    await load()
  }
  catch (e: unknown) {
    flash.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not add the agent.'
  }
  finally { busy.value = false }
}

const fmt = (n: number) => '₦' + Number(n || 0).toLocaleString()
const tone = (s: string) =>
  ({ notified: 'amber', accepted: 'blue', calling: 'blue', confirmed: 'blue', out_for_delivery: 'blue', delivered: 'green', failed: 'red', returned: 'gray', cancelled: 'gray' }[s] ?? 'gray')
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Agents · AGM</h1>
        <div class="sub">Local logistics partners: they hold your stock per vendor, call your customers and ship out when you confirm (§20-24).</div>
      </div>
    </div>

    <div v-if="flash" class="badge green" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ flash }}</div>

    <div class="grid-2">
      <div>
        <h2>My agents</h2>
        <div v-if="loading" class="muted">Loading…</div>
        <div v-else-if="!links.length" class="card muted">No agents yet — add one from the directory so you can route sourcing deliveries and order fulfillment to them.</div>
        <div v-else class="card" v-for="l in links" :key="l.id" style="margin-bottom:.7rem;display:flex;justify-content:space-between;align-items:center;gap:.6rem;flex-wrap:wrap">
          <div>
            <b>{{ l.agent_name }}</b> <span class="badge" :class="l.status === 'active' ? 'green' : 'gray'">{{ l.status }}</span>
            <div class="muted" style="font-size:.8rem;margin-top:.2rem">{{ l.city }} · {{ l.phone }} · {{ l.warehouses }} warehouse(s)</div>
          </div>
          <span class="badge teal">vendor link</span>
        </div>

        <h2 style="margin-top:1.4rem">Orders with agents</h2>
        <div v-if="!loading && !vendorOrders.length" class="card muted">Nothing marked yet — confirm a customer order, then mark it for agent fulfillment on the Orders page.</div>
        <div v-else class="card" v-for="ao in vendorOrders" :key="ao.id" style="margin-bottom:.7rem">
          <div style="display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap;align-items:center">
            <div>
              <b>{{ ao.code }}</b> · {{ ao.qty }} × {{ ao.title }}
              <span class="badge" :class="tone(ao.status)" style="margin-left:.4rem">{{ ao.status.replace(/_/g,' ') }}</span>
              <div class="muted" style="font-size:.8rem;margin-top:.2rem">
                Order #{{ ao.order_id }} · {{ ao.customer.name }} ({{ ao.customer.city }}) · order #{{ ao.order_id }}
                <template v-if="ao.cod_expected"> · COD {{ fmt(ao.cod_expected) }}</template>
                <template v-if="ao.cod_collected"> · collected {{ fmt(ao.cod_collected) }}</template>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div>
        <h2>Agent directory</h2>
        <div v-if="loading" class="muted">Loading…</div>
        <div v-else class="card" v-for="c in directory" :key="c.agent_org_id" style="margin-bottom:.7rem">
          <div style="display:flex;justify-content:space-between;gap:.6rem;align-items:center;flex-wrap:wrap">
            <div>
              <b>{{ c.company }}</b> <span class="muted" style="font-size:.78rem">★ {{ c.rating }}</span>
              <div class="muted" style="font-size:.8rem;margin-top:.2rem">
                {{ c.contact_name }} · {{ c.city }}, {{ c.country }} · {{ c.warehouses }} warehouse(s)
              </div>
              <div class="muted" style="font-size:.75rem;margin-top:.2rem">{{ c.capacity_note }}</div>
            </div>
            <button v-if="c.link_status !== 'active'" class="small" :disabled="busy" @click="addAgent(c)">
              {{ c.link_status ? 'Re-activate' : '+ Add agent' }}
            </button>
            <span v-else class="badge green">Added</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

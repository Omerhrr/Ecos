<script setup lang="ts">
const api = useApi()
const { date } = useFormat()

const shipments = ref<Shipment[]>([])
const loading = ref(true)

onMounted(async () => {
  try { shipments.value = await api.shipments() }
  finally { loading.value = false }
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Logistics</h1>
        <div class="sub">Normalized shipments across carriers (§22-23) — external tracking mapped to one timeline</div>
      </div>
    </div>

    <div v-if="loading" class="empty">Loading shipments…</div>
    <div v-else class="card" style="padding:0">
      <table>
        <thead>
          <tr><th>Tracking code</th><th>Order</th><th>Recipient</th><th>Route</th><th>Progress</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in shipments" :key="s.id">
            <td class="mono">{{ s.tracking_code }}</td>
            <td><NuxtLink :to="`/orders/${s.order_id}`" class="mono">#{{ s.order_id }}</NuxtLink></td>
            <td>{{ s.recipient_name }}<div class="muted" style="font-size:.72rem">{{ s.recipient_address }}</div></td>
            <td>{{ s.origin_country }} → {{ s.destination_country }}</td>
            <td>
              <div class="muted" style="font-size:.72rem">
                {{ s.timeline.length }} events
                <span v-if="s.timeline.length"> · last: {{ s.timeline.at(-1)?.code.replaceAll('_', ' ') }}</span>
              </div>
            </td>
            <td><StatusBadge :status="s.status" /></td>
          </tr>
          <tr v-if="!shipments.length"><td colspan="6" class="empty">No shipments yet</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

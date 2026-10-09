<script setup lang="ts">
/**
 * Marketstore (§11) — the operator's sourcing storefront.
 * Products come "from the Ecos Network": no supplier identity, no supply
 * economics beyond the price — buyers browse in their own currency, buy
 * prepaid, and track the inbound corridor on /sourcing.
 */
const api = useApi()
const auth = useAuth()
const mounted = ref(false)
const listings = ref<MarketListing[]>([])
const links = ref<AgentLinkRow[]>([])
const q = ref('')
const category = ref('')
const loading = ref(true)
const error = ref('')

const buyOpen = ref(false)
const buyTarget = ref<MarketListing | null>(null)
const buyQty = ref(1)
const buyAgent = ref<number | null>(null)
const buyNote = ref('')
const buying = ref(false)
const lastOrder = ref<SourcingOrder | null>(null)

const CATEGORIES = ['electronics', 'home-appliances', 'accessories', 'beauty', 'fashion', 'general']

onMounted(async () => {
  mounted.value = true
  auth.restore()
  await load()
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (q.value) params.q = q.value
    if (category.value) params.category = category.value
    listings.value = await api.marketProducts(params)
    links.value = await api.agentLinks()
  }
  catch { error.value = 'Could not load the Marketstore.' }
  finally { loading.value = false }
}

function openBuy(p: MarketListing) {
  buyTarget.value = p
  buyQty.value = p.moq
  buyAgent.value = links.value[0]?.agent_org_id ?? null
  buyNote.value = ''
  buyOpen.value = true
}

async function submitBuy() {
  if (!buyTarget.value) return
  buying.value = true
  error.value = ''
  try {
    const so = await api.createSourcingOrder({
      supplier_product_id: buyTarget.value.id,
      qty: buyQty.value,
      agent_org_id: buyAgent.value,
      note: buyNote.value,
    })
    lastOrder.value = so
    buyOpen.value = false
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not create the sourcing order.'
  }
  finally { buying.value = false }
}

async function payLast() {
  if (!lastOrder.value) return
  buying.value = true
  try {
    lastOrder.value = await api.paySourcingOrder(lastOrder.value.id, 'online_transfer')
  }
  catch { error.value = 'Payment failed.' }
  finally { buying.value = false }
}

const fmt = (n: number) => '₦' + Number(n || 0).toLocaleString()
const statusTone = (s: string) =>
  ({ paid: 'blue', processing: 'amber', shipped: 'blue', in_transit: 'blue', customs: 'amber', destination_hub: 'blue', arrived: 'teal', received: 'green', cancelled: 'red' }[s] ?? 'gray')
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Marketstore</h1>
        <div class="sub">Source products from the Ecos Network — priced in Naira, supplier-private (§9), tracked door to hub (§23).</div>
      </div>
      <NuxtLink to="/sourcing"><button class="ghost">My sourcing orders →</button></NuxtLink>
    </div>

    <div class="card" style="margin-bottom:1rem;display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
      <input v-model="q" placeholder="Search the network catalog…" style="flex:1;min-width:200px" @keyup.enter="load">
      <select v-model="category" style="width:auto">
        <option value="">All categories</option>
        <option v-for="c in CATEGORIES" :key="c" :value="c">{{ c }}</option>
      </select>
      <button @click="load">Search</button>
    </div>

    <div v-if="error" class="badge red" style="margin-bottom:.8rem;display:block;padding:.5rem">{{ error }}</div>
    <div v-if="lastOrder" class="card" style="margin-bottom:1rem;border-color:var(--accent)">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.6rem">
        <div>
          <b>{{ lastOrder.order_number }}</b> — {{ lastOrder.qty }} × {{ lastOrder.title }}
          <span class="badge" :class="statusTone(lastOrder.status)" style="margin-left:.4rem">{{ lastOrder.status.replace('_',' ') }}</span>
          <div class="muted" style="margin-top:.2rem">
            {{ fmt(lastOrder.local_total) }} · cost ¥{{ lastOrder.cny_total?.toLocaleString() }} @ {{ lastOrder.fx_rate }} ·
            {{ lastOrder.destination.via_agent ? 'ships to your agent' : 'ships to you' }}
          </div>
        </div>
        <div style="display:flex;gap:.5rem">
          <button v-if="lastOrder.status === 'pending_payment'" :disabled="buying" @click="payLast">Pay now</button>
          <NuxtLink to="/sourcing"><button class="ghost small">Track it</button></NuxtLink>
        </div>
      </div>
    </div>

    <div v-if="loading" class="muted">Loading the network catalog…</div>
    <div v-else class="market-grid">
      <div v-for="p in listings" :key="p.id" class="card listing">
        <img :src="p.images?.[0] || 'https://picsum.photos/seed/ecos/800/600'" alt="" class="listing-img">
        <div class="badge teal" style="margin:.6rem 0 .3rem">{{ p.category }}</div>
        <h3 style="margin:.2rem 0 .3rem;font-size:1rem">{{ p.title }}</h3>
        <p class="muted" style="font-size:.8rem;margin:0 0 .5rem;min-height:2.4em">{{ (p.description || '').slice(0, 110) }}…</p>
        <div class="listing-price">{{ fmt(p.unit_price) }} <span class="muted" style="font-size:.72rem">/ unit · MOQ {{ p.moq }}</span></div>
        <div class="muted" style="font-size:.72rem;margin:.3rem 0 .6rem">From the Ecos Network · ~{{ p.lead_time_days }} days corridor</div>
        <button style="width:100%" @click="openBuy(p)">Source this product</button>
      </div>
    </div>
    <div v-if="!loading && !listings.length" class="muted">No listings match yet — the supply team publishes new products continuously.</div>

    <!-- buy modal -->
    <div v-if="buyOpen" class="modal-backdrop" @click.self="buyOpen = false">
      <div class="modal">
        <h2>Source: {{ buyTarget?.title }}</h2>
        <p class="muted" style="margin-top:-.3rem">Prepaid stock purchase (§11). Units land at your agent's warehouse and become sellable on arrival.</p>
        <div class="field">
          <label>Quantity (MOQ {{ buyTarget?.moq }})</label>
          <input v-model.number="buyQty" type="number" :min="buyTarget?.moq">
        </div>
        <div class="field">
          <label>Deliver to</label>
          <select v-model="buyAgent">
            <option :value="null">My own warehouse (direct)</option>
            <option v-for="l in links" :key="l.agent_org_id" :value="l.agent_org_id">
              Agent: {{ l.agent_name }} ({{ l.city }}) — {{ l.warehouses }} warehouse(s)
            </option>
          </select>
          <small v-if="!links.length">No agent linked yet — add one under Agents · AGM, or ship direct to your warehouse.</small>
        </div>
        <div class="field">
          <label>Note to the network (optional)</label>
          <textarea v-model="buyNote" rows="2" placeholder="e.g. Stock-up before campaign week"></textarea>
        </div>
        <div v-if="buyTarget" class="quote-box">
          <div class="muted" style="font-size:.75rem;text-transform:uppercase;letter-spacing:.05em">Estimated landed quote</div>
          <div v-for="(v, k) in buyTarget.pricing" :key="k" style="display:flex;justify-content:space-between;font-size:.85rem;margin-top:.25rem">
            <span class="muted">{{ k.replace(/_/g, ' ') }}</span><span>{{ k.includes('price') || k.includes('total') ? fmt(v) : '₦' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }) }}</span>
          </div>
        </div>
        <div class="modal-actions">
          <button class="ghost" @click="buyOpen = false">Cancel</button>
          <button :disabled="buying" @click="submitBuy">{{ buying ? 'Placing…' : 'Place sourcing order' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.market-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: .9rem; }
.listing { display: flex; flex-direction: column; padding: .9rem; }
.listing-img { width: 100%; height: 130px; object-fit: cover; border-radius: 8px; background: #eef2f7; }
.listing-price { font-weight: 800; font-size: 1.1rem; color: var(--accent); }
.listing button { margin-top: auto; }
.quote-box { background: #f8fafc; border: 1px dashed var(--border); border-radius: 8px; padding: .7rem .8rem; margin-bottom: .4rem; }
</style>

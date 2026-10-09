<script setup lang="ts">
/**
 * Supplier Network (platform staff, §8) — the Luxeen control room for the
 * China side: review gate for uploaded listings, publish to the Marketstore,
 * and recruit new supplier organizations with portal accounts.
 */
definePageMeta({ layout: 'default' })
const api = useApi()
const auth = useAuth()

const tab = ref<'review' | 'listings' | 'recruit'>('review')
const submitted = ref<SupplierProduct[]>([])
const published = ref<SupplierProduct[]>([])
const busy = ref(0)
const flash = ref('')
const error = ref('')

const recruit = reactive({ company: '', contact_name: '', email: '', password: '', city: '', country: 'CN' })
const recruitBusy = ref(false)

onMounted(async () => {
  auth.restore()
  if (auth.user.value?.role !== 'luxeen_admin') { navigateTo('/dashboard'); return }
  await load()
})

async function load() {
  try {
    submitted.value = await api.adminMarketProducts('submitted')
    published.value = await api.adminMarketProducts('published')
  }
  catch { error.value = 'Could not load the review queue.' }
}

async function review(p: SupplierProduct, decision: 'approve' | 'reject') {
  busy.value = p.id
  error.value = ''
  try {
    await api.reviewMarketProduct(p.id, decision, decision === 'approve' ? 'Sample verified.' : 'Needs better specs/images.')
    flash.value = decision === 'approve' ? `Approved "${p.title}" — ready to publish.` : `Rejected "${p.title}" — the supplier can edit and resubmit.`
    await load()
  }
  catch { error.value = 'Review failed.' }
  finally { busy.value = 0 }
}

async function publish(p: SupplierProduct) {
  busy.value = p.id
  error.value = ''
  try {
    await api.publishMarketProduct(p.id)
    flash.value = `"${p.title}" is live on the Marketstore.`
    await load()
  }
  catch { error.value = 'Publish failed.' }
  finally { busy.value = 0 }
}

async function doRecruit() {
  recruitBusy.value = true
  error.value = ''
  try {
    const r = await api.createSupplierOrg({ ...recruit })
    flash.value = `Supplier org "${r.org.name}" created — portal login: ${recruit.email}`
    recruit.company = ''; recruit.contact_name = ''; recruit.email = ''; recruit.password = ''; recruit.city = ''
    await load()
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Could not create the supplier org.'
  }
  finally { recruitBusy.value = false }
}

const tone = (s: string) =>
  ({ draft: 'gray', submitted: 'amber', approved: 'blue', rejected: 'red', published: 'green', archived: 'gray' }[s] ?? 'gray')
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Supplier Network</h1>
        <div class="sub">The China side of the corridor — every listing goes through your gate before it reaches the Marketstore (§8).</div>
      </div>
      <div class="row">
        <button :class="tab === 'review' ? '' : 'ghost'" @click="tab = 'review'">
          Review queue <span class="badge" :class="submitted.length ? 'amber' : 'gray'">{{ submitted.length }}</span>
        </button>
        <button :class="tab === 'listings' ? '' : 'ghost'" @click="tab = 'listings'">Live listings</button>
        <button :class="tab === 'recruit' ? '' : 'ghost'" @click="tab = 'recruit'">Recruit supplier</button>
      </div>
    </div>

    <div v-if="flash" class="badge green" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ flash }}</div>
    <div v-if="error" class="badge red" style="display:block;padding:.5rem;margin-bottom:.8rem">{{ error }}</div>

    <!-- REVIEW QUEUE -->
    <template v-if="tab === 'review'">
      <div v-if="!submitted.length" class="card muted">Queue clear — nothing awaiting review. Suppliers' submissions land here.</div>
      <div v-else class="card" v-for="p in submitted" :key="p.id" style="margin-bottom:.8rem">
        <div style="display:flex;justify-content:space-between;gap:.8rem;flex-wrap:wrap;align-items:center">
          <div style="display:flex;gap:.8rem;align-items:center">
            <img :src="p.images?.[0]" alt="" style="width:64px;height:64px;object-fit:cover;border-radius:8px;background:#eef2f7">
            <div>
              <b>{{ p.title }}</b> <span class="badge" :class="tone(p.status)">{{ p.status }}</span>
              <div class="muted" style="font-size:.8rem;margin-top:.2rem">
                ¥{{ p.cost_price }} · {{ p.weight_kg }}kg · MOQ {{ p.moq }} · {{ p.category }} / {{ p.industry || '—' }}
              </div>
              <div class="muted" style="font-size:.78rem;margin-top:.15rem">{{ (p.description || '').slice(0, 120) }}</div>
            </div>
          </div>
          <div style="display:flex;gap:.5rem">
            <button class="small" :disabled="busy === p.id" @click="review(p, 'approve')">Approve</button>
            <button class="danger small" :disabled="busy === p.id" @click="review(p, 'reject')">Reject</button>
          </div>
        </div>
      </div>
      <div v-if="submitted.some(p => p.status === 'approved')" style="margin-top:1.4rem">
        <h2>Approved — ready to publish</h2>
        <div class="card" v-for="p in submitted.filter(x => x.status === 'approved')" :key="p.id" style="margin-bottom:.6rem;display:flex;justify-content:space-between;align-items:center;gap:.6rem;flex-wrap:wrap">
          <div><b>{{ p.title }}</b> <span class="badge blue">approved</span>
            <div class="muted" style="font-size:.78rem">¥{{ p.cost_price }} · {{ p.weight_kg }}kg · MOQ {{ p.moq }}</div>
          </div>
          <button class="small" :disabled="busy === p.id" @click="publish(p)">Publish to Marketstore</button>
        </div>
      </div>
    </template>

    <!-- LIVE LISTINGS -->
    <template v-if="tab === 'listings'">
      <div class="card" style="padding:0">
        <table>
          <thead><tr><th>Listing</th><th>Cost</th><th>Weight</th><th>MOQ</th><th>Category</th><th>Catalog product</th><th>Published</th></tr></thead>
          <tbody>
            <tr v-for="p in published" :key="p.id">
              <td><b>{{ p.title }}</b> <span class="badge green">published</span></td>
              <td>¥{{ p.cost_price }}</td>
              <td>{{ p.weight_kg }}kg</td>
              <td>{{ p.moq }}</td>
              <td>{{ p.category }}</td>
              <td class="mono muted">#{{ p.catalog_product_id }}</td>
              <td class="muted" style="font-size:.76rem">live</td>
            </tr>
            <tr v-if="!published.length"><td colspan="7" class="empty">Nothing published yet</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- RECRUIT -->
    <template v-if="tab === 'recruit'">
      <div class="card" style="max-width:560px">
        <h2>Recruit a supplier organization</h2>
        <p class="muted" style="margin-top:-.3rem">Creates the org (type=supplier), a portal user and the linked Supplier record — then send them the credentials (§8/§43).</p>
        <div class="field"><label>Company</label><input v-model="recruit.company" placeholder="Shenzhen Mingda Electronics"></div>
        <div class="row">
          <div class="field" style="flex:1"><label>Contact name</label><input v-model="recruit.contact_name" placeholder="Li Wei"></div>
          <div class="field" style="flex:1"><label>City</label><input v-model="recruit.city" placeholder="Shenzhen"></div>
        </div>
        <div class="row">
          <div class="field" style="flex:1"><label>Portal email</label><input v-model="recruit.email" type="email" placeholder="li@mingda.cn"></div>
          <div class="field" style="flex:1"><label>Temporary password</label><input v-model="recruit.password" placeholder="min 6 chars"></div>
        </div>
        <div class="field"><label>Country</label>
          <select v-model="recruit.country"><option value="CN">CN — China</option><option value="IN">IN — India</option><option value="JP">JP — Japan</option><option value="PK">PK — Pakistan</option></select>
        </div>
        <button :disabled="recruitBusy" @click="doRecruit">{{ recruitBusy ? 'Creating…' : 'Create supplier org + portal user' }}</button>
      </div>
    </template>
  </div>
</template>

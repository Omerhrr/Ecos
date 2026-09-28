<script setup lang="ts">
const api = useApi()

const pages = ref<LandingPageSummary[]>([])
const loading = ref(true)
const error = ref('')
const showCreate = ref(false)
const creating = reactive({ title: '', slug: '' })
const createBusy = ref(false)
const createError = ref('')

async function load() {
  loading.value = true
  try {
    pages.value = await api.landingPages()
  }
  catch {
    error.value = 'Could not load landing pages.'
  }
  finally {
    loading.value = false
  }
}

onMounted(load)

const slugify = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')

watch(() => creating.title, (t) => {
  if (!creating.slug || creating.slug === slugify(creating.slug)) {
    // auto-sync unless the user hand-edited the slug
    creating.slug = slugify(t)
  }
})

async function create() {
  createBusy.value = true
  createError.value = ''
  try {
    const page = await api.createLandingPage({
      title: creating.title,
      slug: creating.slug,
      blocks: [],
      theme: { primary: '#00b374' },
    })
    showCreate.value = false
    creating.title = ''
    creating.slug = ''
    navigateTo(`/landing-pages/${page.id}`)
  }
  catch (e: unknown) {
    createError.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Create failed'
  }
  finally {
    createBusy.value = false
  }
}

async function togglePublish(p: LandingPageSummary) {
  if (p.status === 'published') await api.unpublishLandingPage(p.id)
  else await api.publishLandingPage(p.id)
  await load()
}

async function remove(p: LandingPageSummary) {
  if (!confirm(`Delete "${p.title}"? This cannot be undone.`)) return
  await api.deleteLandingPage(p.id)
  await load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Landing Pages</h1>
        <div class="sub">Block-composed campaign pages and your storefront home (§15)</div>
      </div>
      <button class="primary" @click="showCreate = true">+ New page</button>
    </div>

    <div v-if="error" class="card" style="border-color:#fecaca;color:#991b1b">{{ error }}</div>
    <div v-else-if="loading" class="empty">Loading pages…</div>

    <div v-else class="card">
      <table>
        <thead>
          <tr><th>Title</th><th>Slug</th><th>Blocks</th><th>Status</th><th>Updated</th><th style="width:290px">Actions</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in pages" :key="p.id">
            <td>
              <b>{{ p.title }}</b>
              <span v-if="p.slug === 'home'" class="chip-home">home</span>
            </td>
            <td><code>/lp/{{ p.slug }}</code></td>
            <td>{{ p.block_count }}</td>
            <td><StatusBadge :status="p.status" /></td>
            <td class="muted">{{ p.updated_at ? new Date(p.updated_at).toLocaleDateString() : '—' }}</td>
            <td class="row-actions">
              <NuxtLink :to="`/landing-pages/${p.id}`"><button class="ghost small">Edit</button></NuxtLink>
              <button class="ghost small" @click="togglePublish(p)">
                {{ p.status === 'published' ? 'Unpublish' : 'Publish' }}
              </button>
              <NuxtLink v-if="p.status === 'published'" :to="`/lp/${p.slug}`" target="_blank">
                <button class="ghost small">View ↗</button>
              </NuxtLink>
              <button class="danger small" @click="remove(p)">Delete</button>
            </td>
          </tr>
          <tr v-if="!pages.length">
            <td colspan="6" class="empty">No landing pages yet — create one to start composing.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- create modal -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h2>New landing page</h2>
        <label class="field">
          <span>Title</span>
          <input v-model="creating.title" placeholder="e.g. Earbuds Launch Week" required>
        </label>
        <label class="field">
          <span>Slug (public URL: /lp/…)</span>
          <input v-model="creating.slug" placeholder="earbuds-launch">
        </label>
        <div v-if="createError" class="login-error">{{ createError }}</div>
        <div class="modal-actions">
          <button class="ghost" @click="showCreate = false">Cancel</button>
          <button class="primary" :disabled="createBusy || !creating.title || !creating.slug" @click="create">
            {{ createBusy ? 'Creating…' : 'Create & edit' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

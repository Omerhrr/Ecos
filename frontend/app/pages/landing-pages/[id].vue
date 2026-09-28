<script setup lang="ts">
/**
 * Landing page editor (§15): page meta + theme + ordered block composer.
 * Field inputs are generated from the backend block registry so the UI
 * never drifts from the server-side schema.
 */
const route = useRoute()
const api = useApi()

const pageId = Number(route.params.id)
const page = ref<LandingPage | null>(null)
const registry = ref<BlockTypeDef[]>([])
const loading = ref(true)
const error = ref('')
const saved = ref(false)
const saving = ref(false)
const expanded = ref<string | null>(null)
const newBlockType = ref('')

const title = ref('')
const slug = ref('')
const seoTitle = ref('')
const seoDescription = ref('')
const themePrimary = ref('#00b374')
const blocks = ref<LandingPageBlock[]>([])

const registryMap = computed(() =>
  Object.fromEntries(registry.value.map(r => [r.type, r])),
)

onMounted(async () => {
  try {
    const [p, reg] = await Promise.all([api.landingPage(pageId), api.blockRegistry()])
    page.value = p
    registry.value = reg
    title.value = p.title
    slug.value = p.slug
    seoTitle.value = p.seo.title ?? ''
    seoDescription.value = p.seo.description ?? ''
    themePrimary.value = p.theme.primary ?? '#00b374'
    blocks.value = JSON.parse(JSON.stringify(p.blocks))
    if (blocks.value.length) expanded.value = blocks.value[0].id
  }
  catch {
    error.value = 'Could not load this landing page.'
  }
  finally {
    loading.value = false
  }
})

function addBlock() {
  if (!newBlockType.value) return
  const def = registryMap.value[newBlockType.value]
  if (!def) return
  const block: LandingPageBlock = { id: Math.random().toString(16).slice(2, 10), type: newBlockType.value }
  for (const f of def.fields) block[f.key] = f.default
  blocks.value.push(block)
  expanded.value = block.id
  newBlockType.value = ''
}

function removeBlock(i: number) {
  blocks.value.splice(i, 1)
}

function move(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= blocks.value.length) return
  const arr = blocks.value
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

async function save() {
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const res = await api.patchLandingPage(pageId, {
      title: title.value,
      slug: slug.value,
      seo: { title: seoTitle.value, description: seoDescription.value },
      theme: { primary: themePrimary.value },
      blocks: blocks.value,
    })
    blocks.value = JSON.parse(JSON.stringify(res.blocks))
    slug.value = res.slug
    saved.value = true
    setTimeout(() => (saved.value = false), 2500)
  }
  catch (e: unknown) {
    error.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Save failed'
  }
  finally {
    saving.value = false
  }
}

async function togglePublish() {
  if (!page.value) return
  const res = page.value.status === 'published'
    ? await api.unpublishLandingPage(pageId)
    : await api.publishLandingPage(pageId)
  page.value = res
}

async function removeBlock_(i: number) {
  removeBlock(i)
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>Edit landing page</h1>
        <div class="sub" v-if="page">
          <code>/lp/{{ slug }}</code> ·
          <StatusBadge :status="page.status" />
          <NuxtLink v-if="page.status === 'published'" :to="`/lp/${slug}`" target="_blank" style="margin-left:.5rem">
            View live ↗
          </NuxtLink>
        </div>
      </div>
      <div class="row-actions">
        <button v-if="page" class="ghost" @click="togglePublish">
          {{ page.status === 'published' ? 'Unpublish' : 'Publish' }}
        </button>
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save changes' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="card" style="border-color:#fecaca;color:#991b1b;margin-bottom:.8rem">{{ error }}</div>
    <div v-if="loading" class="empty">Loading editor…</div>

    <template v-else>
      <!-- page settings -->
      <div class="card" style="margin-bottom:.9rem">
        <h2>Page settings</h2>
        <div class="editor-grid">
          <label class="field">
            <span>Title</span>
            <input v-model="title">
          </label>
          <label class="field">
            <span>Slug</span>
            <input v-model="slug">
          </label>
          <label class="field">
            <span>Theme color</span>
            <input v-model="themePrimary" type="color" style="height:2.4rem;padding:.15rem">
          </label>
          <label class="field">
            <span>SEO title</span>
            <input v-model="seoTitle">
          </label>
          <label class="field editor-span2">
            <span>SEO description</span>
            <textarea v-model="seoDescription" rows="2" />
          </label>
        </div>
      </div>

      <!-- blocks -->
      <div class="card">
        <div class="spread" style="margin-bottom:.8rem">
          <h2>Blocks ({{ blocks.length }})</h2>
          <div class="editor-add">
            <select v-model="newBlockType" class="select">
              <option value="" disabled>Add a block…</option>
              <option v-for="r in registry" :key="r.type" :value="r.type">{{ r.label }}</option>
            </select>
            <button class="primary small" :disabled="!newBlockType" @click="addBlock">Add</button>
          </div>
        </div>

        <div v-if="!blocks.length" class="empty">
          No blocks yet — add a Hero to get started.
        </div>

        <div v-for="(block, i) in blocks" :key="block.id" class="block-card">
          <div class="block-head" @click="expanded = expanded === block.id ? null : block.id">
            <b>{{ registryMap[block.type]?.label ?? block.type }}</b>
            <span class="muted">#{{ i + 1 }}</span>
            <span class="block-tools" @click.stop>
              <button class="ghost tiny" :disabled="i === 0" @click="move(i, -1)">↑</button>
              <button class="ghost tiny" :disabled="i === blocks.length - 1" @click="move(i, 1)">↓</button>
              <button class="danger tiny" @click="removeBlock_(i)">✕</button>
            </span>
          </div>

          <div v-if="expanded === block.id" class="block-body">
            <label v-for="f in registryMap[block.type]?.fields ?? []" :key="f.key" class="field">
              <span>{{ f.label }}</span>
              <select v-if="f.ftype === 'select'" v-model="block[f.key]" class="select">
                <option v-for="o in f.options ?? []" :key="o" :value="o">{{ o }}</option>
              </select>
              <textarea
                v-else-if="f.ftype === 'textarea' || f.ftype === 'lines'"
                v-model="block[f.key]"
                rows="3"
                :placeholder="f.hint"
              />
              <input
                v-else-if="f.ftype === 'number'"
                v-model="block[f.key]"
                type="number"
                min="1"
                max="12"
              >
              <input v-else-if="f.ftype === 'color'" v-model="block[f.key]" type="color" style="height:2.4rem;padding:.15rem">
              <input v-else v-model="block[f.key]" :placeholder="f.hint">
              <small v-if="f.hint" class="muted">{{ f.hint }}</small>
            </label>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

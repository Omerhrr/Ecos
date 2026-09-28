<script setup lang="ts">
/**
 * Landing page editor (§15): page meta + theme + ordered block composer,
 * publish versioning + scheduled publishing. Field inputs are generated
 * from the backend block registry so the UI never drifts from the
 * server-side schema; the palette renders each block type as a thumbnail
 * card built from its registry icon + accent color.
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

// §15 versioning + scheduling
const versions = ref<LpVersion[]>([])
const versionsOpen = ref(false)
const scheduleAt = ref('')
const scheduleMsg = ref('')

const title = ref('')
const slug = ref('')
const seoTitle = ref('')
const seoDescription = ref('')
const themePrimary = ref('#00b374')
const blocks = ref<LandingPageBlock[]>([])

const registryMap = computed(() =>
  Object.fromEntries(registry.value.map(r => [r.type, r])),
)

async function loadVersions() {
  try {
    versions.value = await api.lpVersions(pageId)
  }
  catch { /* versions panel just stays empty */ }
}

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
    if (p.scheduled_at) {
      scheduleAt.value = new Date(p.scheduled_at).toISOString().slice(0, 16)
    }
    await loadVersions()
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
  await loadVersions()
}

async function schedule() {
  if (!scheduleAt.value) return
  scheduleMsg.value = ''
  try {
    const res = await api.scheduleLandingPage(pageId, new Date(scheduleAt.value).toISOString())
    page.value = res
    scheduleMsg.value = `Scheduled to go live ${new Date(scheduleAt.value).toLocaleString()} — the scheduler will publish it automatically`
    await loadVersions()
  }
  catch (e: unknown) {
    scheduleMsg.value = (e as { response?: { _data?: { detail?: string } } })?.response?._data?.detail ?? 'Scheduling failed'
  }
}

async function cancelSchedule() {
  const res = await api.cancelLpSchedule(pageId)
  page.value = res
  scheduleAt.value = ''
  scheduleMsg.value = 'Schedule cancelled'
}

async function restoreVersion(versionNo: number, publish: boolean) {
  const res = await api.restoreLpVersion(pageId, versionNo, publish)
  page.value = res
  blocks.value = JSON.parse(JSON.stringify(res.blocks))
  themePrimary.value = res.theme.primary ?? '#00b374'
  seoTitle.value = res.seo.title ?? ''
  seoDescription.value = res.seo.description ?? ''
  scheduleMsg.value = publish
    ? `Restored v${versionNo} and pushed it live`
    : `Restored v${versionNo} as draft — review, then Publish`
  await loadVersions()
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

      <!-- §15 scheduling + versioning -->
      <div class="card" style="margin-bottom:.9rem">
        <div class="spread" style="margin-bottom:.6rem">
          <h2 style="margin:0">Publishing (§15)</h2>
          <button class="ghost small" @click="versionsOpen = !versionsOpen">
            {{ versionsOpen ? 'Hide versions' : `Versions (${versions.filter(v => !v.is_current).length})` }}
          </button>
        </div>
        <div class="editor-grid">
          <label class="field">
            <span>Scheduled go-live</span>
            <input v-model="scheduleAt" type="datetime-local" step="60">
          </label>
          <div class="field">
            <span>&nbsp;</span>
            <div class="row" style="gap:.4rem">
              <button class="primary small" :disabled="!scheduleAt" @click="schedule">Schedule</button>
              <button v-if="page?.scheduled_at" class="ghost small" @click="cancelSchedule">Cancel schedule</button>
            </div>
          </div>
        </div>
        <div v-if="page?.scheduled_at" class="muted" style="font-size:.78rem">
          ⏱ Goes live automatically {{ new Date(page.scheduled_at).toLocaleString() }}
        </div>
        <div v-if="scheduleMsg" class="muted" style="font-size:.78rem">{{ scheduleMsg }}</div>
        <div class="muted" style="font-size:.72rem;margin-top:.4rem">
          Every publish (manual or scheduled) freezes an immutable version — roll back any time.
        </div>

        <div v-if="versionsOpen" class="lp-versions">
          <div v-for="v in versions" :key="String(v.version_no)" class="lp-version-row">
            <div>
              <b>{{ v.version_no === 'live' ? 'Current draft' : `v${v.version_no}` }}</b>
              <span v-if="v.is_current" class="badge gray" style="margin-left:.4rem">editable</span>
              <span v-else-if="Number(v.version_no) === Math.max(...versions.filter(x => !x.is_current).map(x => Number(x.version_no))) && !page?.scheduled_at" class="badge green" style="margin-left:.4rem">live</span>
              <div class="muted" style="font-size:.72rem">
                {{ v.block_count }} blocks · {{ v.published_at ? new Date(v.published_at).toLocaleString() : '—' }}
                {{ v.note ? `· ${v.note}` : '' }}
              </div>
            </div>
            <div v-if="!v.is_current" class="row" style="gap:.3rem">
              <button class="ghost small" @click="restoreVersion(Number(v.version_no), false)">Restore as draft</button>
              <button class="small" @click="restoreVersion(Number(v.version_no), true)">Restore + publish</button>
            </div>
          </div>
        </div>
      </div>

      <!-- blocks -->
      <div class="card">
        <div class="spread" style="margin-bottom:.8rem">
          <h2>Blocks ({{ blocks.length }})</h2>
        </div>

        <!-- §15 block palette with thumbnails -->
        <div class="lp-palette">
          <button
            v-for="r in registry"
            :key="r.type"
            class="lp-palette-card"
            @click="newBlockType = r.type; addBlock()"
          >
            <span class="lp-palette-thumb" :style="{ background: `linear-gradient(135deg, ${r.accent ?? '#64748b'}22, ${r.accent ?? '#64748b'}55)`, color: r.accent ?? '#64748b' }">
              {{ r.icon ?? '□' }}
            </span>
            <span class="lp-palette-label">{{ r.label }}</span>
          </button>
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

<style scoped>
.lp-palette {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: .55rem; margin-bottom: 1rem;
}
.lp-palette-card {
  display: flex; flex-direction: column; align-items: center; gap: .4rem;
  border: 1px solid var(--border); border-radius: 12px; background: #fff;
  padding: .7rem .4rem; cursor: pointer; transition: border-color .15s, transform .15s;
}
.lp-palette-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.lp-palette-thumb {
  width: 42px; height: 42px; border-radius: 10px; display: flex; align-items: center;
  justify-content: center; font-size: 1.25rem; font-weight: 800;
}
.lp-palette-label { font-size: .74rem; font-weight: 600; color: #334155; text-align: center; }
.lp-versions { margin-top: .8rem; display: flex; flex-direction: column; gap: .4rem; }
.lp-version-row {
  display: flex; justify-content: space-between; align-items: center; gap: .8rem;
  border: 1px solid var(--border); border-radius: 10px; padding: .5rem .7rem;
}
</style>

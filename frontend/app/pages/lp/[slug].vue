<script setup lang="ts">
/**
 * Public landing page renderer (§15): /lp/{slug}.
 * Renders any PUBLISHED page's blocks; applies the page theme color.
 * §16: the page itself is a campaign asset — UTM context is captured on
 * arrival and every internal CTA carries the page's utm_campaign tag
 * so downstream product views keep the attribution alive.
 */
definePageMeta({ layout: 'public' })

const route = useRoute()
const api = useApi()
const utm = useUtm()

const page = ref<PublicPage | null>(null)
const loading = ref(true)
const notFound = ref(false)

const themeColor = computed(() => page.value?.theme?.primary || '#00b374')

/** Append this page's utm_campaign to internal CTA hrefs (last-touch persists). */
const taggedBlocks = computed<LandingPageBlock[]>(() => {
  const blocks = page.value?.blocks ?? []
  const tag = String(route.query.utm_campaign || route.params.slug || '')
  return blocks.map((b) => {
    const href = (b as Record<string, unknown>).cta_href
    if (typeof href === 'string' && href.startsWith('/') && !href.includes('utm_campaign=')) {
      const sep = href.includes('?') ? '&' : '?'
      return { ...b, cta_href: `${href}${sep}utm_source=landing_page&utm_campaign=${encodeURIComponent(tag)}` }
    }
    return b
  })
})

onMounted(async () => {
  utm.capture(route.query)
  try {
    page.value = await api.publicPage(String(route.params.slug))
    const seo = page.value?.seo ?? {}
    useHead({
      title: seo.title || page.value?.title,
      meta: seo.description ? [{ name: 'description', content: seo.description }] : [],
    })
  }
  catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 404) notFound.value = true
  }
  finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div v-if="loading" class="pub-loading">Loading page…</div>

    <div v-else-if="notFound || !page" class="pub-empty">
      <h1>Page not found</h1>
      <p class="muted">This page doesn't exist or isn't published.</p>
      <NuxtLink to="/" class="pub-btn">← Back to store</NuxtLink>
    </div>

    <template v-else>
      <div :style="{ '--lp-primary': themeColor }">
        <BlockRenderer v-for="b in taggedBlocks" :key="b.id" :block="b" />
      </div>
    </template>
  </div>
</template>

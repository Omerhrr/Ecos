<script setup lang="ts">
/**
 * Public renderer for §15 landing page blocks.
 * Handles every type in the backend BLOCK_REGISTRY; unknown types are
 * skipped so old pages never break new renderers.
 */
interface Block {
  id: string
  type: string
  [key: string]: unknown
}

const props = defineProps<{ block: Block }>()

const lines = (key: string) =>
  String(props.block[key] ?? '')
    .split('\n')
    .map(l => l.split('|').map(s => s.trim()))
    .filter(parts => parts[0]?.length)

const showcaseProducts = computed(() =>
  (props.block.products as Array<Record<string, unknown>> | undefined) ?? [],
)
const ctaHref = computed(() => String(props.block.cta_href || '/products'))
</script>

<template>
  <section class="blk" :class="`blk-${block.type}`">
    <!-- HERO -->
    <template v-if="block.type === 'hero'">
      <div
        class="blk-hero"
        :style="block.image ? { backgroundImage: `url(${block.image})` } : {}"
      >
        <div class="blk-hero-inner">
          <h1>{{ block.headline }}</h1>
          <p v-if="block.subheadline">{{ block.subheadline }}</p>
          <NuxtLink v-if="block.cta_label" :to="ctaHref" class="pub-btn lg">{{ block.cta_label }}</NuxtLink>
        </div>
      </div>
    </template>

    <!-- RICH TEXT -->
    <div v-else-if="block.type === 'rich_text'" class="blk-narrow">
      <h2 v-if="block.title">{{ block.title }}</h2>
      <p class="blk-body">{{ block.body }}</p>
    </div>

    <!-- IMAGE + TEXT -->
    <div v-else-if="block.type === 'image_text'" class="blk-narrow blk-imgtext" :class="{ reverse: block.image_side === 'right' }">
      <div class="blk-imgtext-img">
        <img v-if="block.image" :src="String(block.image)" :alt="String(block.title || '')" loading="lazy">
      </div>
      <div class="blk-imgtext-txt">
        <h2 v-if="block.title">{{ block.title }}</h2>
        <p class="blk-body">{{ block.body }}</p>
        <NuxtLink v-if="block.cta_label" :to="ctaHref" class="pub-btn">{{ block.cta_label }}</NuxtLink>
      </div>
    </div>

    <!-- FEATURE GRID -->
    <div v-else-if="block.type === 'feature_grid'" class="blk-narrow">
      <h2 v-if="block.title">{{ block.title }}</h2>
      <div class="blk-features">
        <div v-for="(f, i) in lines('items')" :key="i" class="blk-feature">
          <div class="blk-feature-icon">{{ f[0] }}</div>
          <div>
            <div class="blk-feature-title">{{ f[1] }}</div>
            <div v-if="f[2]" class="blk-feature-text">{{ f[2] }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PRODUCT SHOWCASE -->
    <div v-else-if="block.type === 'product_showcase'" class="blk-wide">
      <h2 v-if="block.title" class="blk-center">{{ block.title }}</h2>
      <div class="prod-grid">
        <ProductCard v-for="p in showcaseProducts" :key="String(p.id)" :product="p as any" />
      </div>
      <div v-if="!showcaseProducts.length" class="muted blk-center">Products coming soon.</div>
    </div>

    <!-- TESTIMONIALS -->
    <div v-else-if="block.type === 'testimonials'" class="blk-narrow">
      <h2 v-if="block.title">{{ block.title }}</h2>
      <div class="blk-quotes">
        <figure v-for="(t, i) in lines('items')" :key="i" class="blk-quote">
          <blockquote>“{{ t[1] }}”</blockquote>
          <figcaption>— {{ t[0] }}</figcaption>
        </figure>
      </div>
    </div>

    <!-- FAQ -->
    <div v-else-if="block.type === 'faq'" class="blk-narrow">
      <h2 v-if="block.title">{{ block.title }}</h2>
      <details v-for="(f, i) in lines('items')" :key="i" class="blk-faq">
        <summary>{{ f[0] }}</summary>
        <p>{{ f[1] }}</p>
      </details>
    </div>

    <!-- TRUST BADGES -->
    <div v-else-if="block.type === 'trust_badges'" class="blk-wide">
      <div class="blk-badges">
        <div v-for="(b, i) in lines('items')" :key="i" class="blk-badge">
          <span class="blk-badge-icon">{{ b[0] }}</span>
          <span>{{ b[1] }}</span>
        </div>
      </div>
    </div>

    <!-- CTA -->
    <div v-else-if="block.type === 'cta'" class="blk-cta">
      <h2>{{ block.title }}</h2>
      <p v-if="block.body">{{ block.body }}</p>
      <NuxtLink v-if="block.cta_label" :to="ctaHref" class="pub-btn lg dark">{{ block.cta_label }}</NuxtLink>
    </div>
  </section>
</template>

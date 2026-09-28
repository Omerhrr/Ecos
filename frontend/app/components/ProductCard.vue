<script setup lang="ts">
const props = defineProps<{ product: { id: number; slug: string | null; title: string; price_ngn: number; image: string | null; in_stock: boolean } }>()
const imgBroken = ref(false)
const cart = useCart()
const money = (n: number) => new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(n)
const initials = computed(() => props.product.title.split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase())
</script>

<template>
  <NuxtLink :to="product.slug ? `/products/${product.slug}` : '/products'" class="prod-card">
    <div class="prod-img">
      <img
        v-if="product.image && !imgBroken"
        :src="product.image"
        :alt="product.title"
        loading="lazy"
        @error="imgBroken = true"
      >
      <span v-else class="prod-img-fallback">{{ initials }}</span>
      <span v-if="!product.in_stock" class="prod-oos">Out of stock</span>
    </div>
    <div class="prod-body">
      <div class="prod-title">{{ product.title }}</div>
      <div class="prod-price">{{ money(product.price_ngn) }}</div>
      <div class="prod-cod">Pay on delivery</div>
      <button
        v-if="product.in_stock"
        class="prod-add"
        @click.prevent.stop="cart.add({ ...product })"
      >
        Add to cart
      </button>
    </div>
  </NuxtLink>
</template>

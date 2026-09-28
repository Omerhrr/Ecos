<script setup lang="ts">
const props = defineProps<{ status: string }>()
const color = useStatusColor()
const label = useLabel()
</script>

<template>
  <span class="badge" :class="color(props.status)">{{ label(props.status) }}</span>
</template>

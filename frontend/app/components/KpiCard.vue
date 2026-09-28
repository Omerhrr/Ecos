<script setup lang="ts">
const props = defineProps<{ label: string; value: string; sub?: string }>()
</script>

<template>
  <div class="card kpi">
    <div class="kpi-label">{{ props.label }}</div>
    <div class="kpi-value">{{ props.value }}</div>
    <div v-if="props.sub" class="kpi-sub">{{ props.sub }}</div>
  </div>
</template>

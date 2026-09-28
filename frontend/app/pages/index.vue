<script setup lang="ts">
const api = useApi()

const backendStatus = ref<'checking' | 'online' | 'offline'>('checking')
const items = ref<Item[]>([])
const newName = ref('')
const newDescription = ref('')
const busy = ref(false)

async function refresh() {
  try {
    items.value = await api.listItems()
  }
  catch {
    backendStatus.value = 'offline'
  }
}

onMounted(async () => {
  try {
    const res = await api.health()
    backendStatus.value = res.status === 'ok' ? 'online' : 'offline'
    await refresh()
  }
  catch {
    backendStatus.value = 'offline'
  }
})

async function addItem() {
  if (!newName.value.trim() || busy.value)
    return
  busy.value = true
  try {
    await api.createItem({ name: newName.value, description: newDescription.value || undefined })
    newName.value = ''
    newDescription.value = ''
    await refresh()
  }
  finally {
    busy.value = false
  }
}

async function removeItem(id: number) {
  await api.deleteItem(id)
  await refresh()
}
</script>

<template>
  <section>
    <h2>Stack status</h2>
    <ul class="stack-list">
      <li><strong>Nuxt 4</strong> — frontend running</li>
      <li>
        <strong>FastAPI</strong> —
        <span :class="['badge', backendStatus]">
          {{ backendStatus === 'online' ? 'connected' : backendStatus === 'offline' ? 'offline' : 'checking…' }}
        </span>
      </li>
      <li><strong>SQLAlchemy</strong> — SQLite via backend</li>
    </ul>

    <h2>Items (demo CRUD)</h2>
    <form class="row" @submit.prevent="addItem">
      <input v-model="newName" placeholder="Item name" required>
      <input v-model="newDescription" placeholder="Description (optional)">
      <button type="submit" :disabled="busy">
        Add
      </button>
    </form>

    <ul v-if="items.length" class="item-list">
      <li v-for="item in items" :key="item.id">
        <div>
          <strong>{{ item.name }}</strong>
          <span v-if="item.description" class="muted"> — {{ item.description }}</span>
        </div>
        <button class="danger" @click="removeItem(item.id)">Delete</button>
      </li>
    </ul>
    <p v-else class="muted">
      No items yet — add one above to test the FastAPI + SQLAlchemy round-trip.
    </p>
  </section>
</template>

<style scoped>
.stack-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.badge {
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
}

.badge.online {
  background: #dcfce7;
  color: #166534;
}

.badge.offline {
  background: #fee2e2;
  color: #991b1b;
}

.badge.checking {
  background: #fef9c3;
  color: #854d0e;
}

.row {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.row input {
  flex: 1;
  min-width: 160px;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 0.95rem;
}

button {
  padding: 0.55rem 1rem;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #003c22;
  font-weight: 600;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

button.danger {
  background: transparent;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.item-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.item-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.65rem 1rem;
}

.muted {
  color: var(--muted);
}
</style>

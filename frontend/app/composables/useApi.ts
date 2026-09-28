/**
 * Thin wrapper around $fetch for backend API calls.
 * Thanks to the Nitro dev proxy, /api/** hits FastAPI directly.
 */
export function useApi() {
  return {
    health: () => $fetch<{ status: string }>('/api/health'),
    listItems: () => $fetch<Item[]>('/api/items'),
    createItem: (payload: { name: string; description?: string }) =>
      $fetch<Item>('/api/items', { method: 'POST', body: payload }),
    deleteItem: (id: number) => $fetch<void>(`/api/items/${id}`, { method: 'DELETE' }),
  }
}

export interface Item {
  id: number
  name: string
  description: string | null
  created_at: string
}

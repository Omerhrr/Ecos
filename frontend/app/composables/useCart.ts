/**
 * §14 completion — client-side cart for the public storefront.
 *
 * Lines persist in localStorage (`ecos:cart`) so a shopper can hop between
 * PDP / products / cart without losing state. Prices shown are the last
 * viewed `price_ngn`; the server re-prices everything through the pricing
 * engine at quote/checkout time (never trust the client).
 */
export interface CartLine {
  slug: string
  title: string
  price_ngn: number
  image: string | null
  qty: number
  stock: number
}

const STORAGE_KEY = 'ecos:cart'

export function useCart() {
  const lines = useState<CartLine[]>('cart-lines', () => [])
  const loaded = useState<boolean>('cart-loaded', () => false)

  function load() {
    if (loaded.value || !import.meta.client) return
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) lines.value = JSON.parse(raw)
    }
    catch { /* corrupted cart — start fresh */ }
    loaded.value = true
  }

  function persist() {
    if (!import.meta.client) return
    localStorage.setItem(STORAGE_KEY, JSON.stringify(lines.value))
  }

  function add(product: { slug: string | null; title: string; price_ngn: number; image: string | null; in_stock: boolean; stock?: number }, qty = 1) {
    load()
    if (!product.slug || !product.in_stock) return
    const existing = lines.value.find(l => l.slug === product.slug)
    const maxStock = product.stock ?? 99
    if (existing) {
      existing.qty = Math.min(existing.qty + qty, Math.max(maxStock, 1))
    }
    else {
      lines.value.push({
        slug: product.slug,
        title: product.title,
        price_ngn: product.price_ngn,
        image: product.image,
        qty: Math.min(qty, Math.max(maxStock, 1)),
        stock: maxStock,
      })
    }
    persist()
  }

  function setQty(slug: string, qty: number) {
    load()
    const line = lines.value.find(l => l.slug === slug)
    if (!line) return
    line.qty = Math.max(1, Math.min(qty, Math.max(line.stock, 1)))
    persist()
  }

  function remove(slug: string) {
    load()
    lines.value = lines.value.filter(l => l.slug !== slug)
    persist()
  }

  function clear() {
    lines.value = []
    persist()
  }

  const count = computed(() => lines.value.reduce((n, l) => n + l.qty, 0))
  const itemsTotal = computed(() => lines.value.reduce((n, l) => n + l.qty * l.price_ngn, 0))

  return { lines, load, add, setQty, remove, clear, count, itemsTotal }
}

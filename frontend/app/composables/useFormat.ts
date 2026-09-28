/** Formatting + status color helpers used across the Command Center. */

const NGN = new Intl.NumberFormat('en-NG', {
  style: 'currency', currency: 'NGN', maximumFractionDigits: 0,
})
const CNY = new Intl.NumberFormat('zh-CN', {
  style: 'currency', currency: 'CNY', maximumFractionDigits: 0,
})

export function useFormat() {
  const money = (n: number | null | undefined, currency = 'NGN') => {
    if (n == null) return '—'
    return currency === 'CNY' ? CNY.format(n) : NGN.format(n)
  }
  const pct = (n: number) => `${(n * 100).toFixed(0)}%`
  const date = (iso: string) => new Date(iso).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' })
  return { money, pct, date }
}

const STATUS_COLORS: Record<string, string> = {
  // orders
  draft: 'gray', pending_confirmation: 'amber', confirmed: 'blue', processing: 'blue',
  fulfilled: 'violet', in_transit: 'violet', out_for_delivery: 'violet',
  delivered: 'green', cancelled: 'gray', failed: 'red', returned: 'amber', refunded: 'red',
  // payments
  paid: 'green', pending: 'amber', collected: 'green',
  // suppliers / products
  verified: 'green', active: 'green', suspended: 'red', archived: 'gray',
  // leads
  new: 'blue', contacted: 'amber', interested: 'violet',
  order_created: 'teal', unreachable: 'gray',
  // shipments
  processing: 'amber', return_pending: 'amber', returning: 'amber',
}

export function useStatusColor() {
  return (status: string) => STATUS_COLORS[status] ?? 'gray'
}

export function useLabel() {
  return (s: string) => s.replaceAll('_', ' ')
}

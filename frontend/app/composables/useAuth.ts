/**
 * Auth session state (plan §43).
 *
 * Token + user + permission set persist in localStorage; the global auth
 * middleware restores them client-side and guards admin routes.
 */
export interface AuthUser {
  id: number
  org_id: number
  name: string
  email: string
  role: string
  is_active: boolean
}

export interface AuthOrg {
  id: number
  name: string
  type: string
  country: string
  currency: string
}

const TOKEN_KEY = 'ecos:token'
const USER_KEY = 'ecos:user'
const PERMS_KEY = 'ecos:perms'

export function useAuth() {
  const token = useState<string | null>('ecos-auth-token', () => null)
  const user = useState<AuthUser | null>('ecos-auth-user', () => null)
  const permissions = useState<string[]>('ecos-auth-perms', () => [])

  /** Read persisted session into state (client only, idempotent). */
  const restore = () => {
    if (!import.meta.client) return
    if (!token.value) {
      token.value = localStorage.getItem(TOKEN_KEY)
      try {
        const u = localStorage.getItem(USER_KEY)
        const p = localStorage.getItem(PERMS_KEY)
        if (u) user.value = JSON.parse(u)
        if (p) permissions.value = JSON.parse(p)
      }
      catch {
        localStorage.removeItem(USER_KEY)
        localStorage.removeItem(PERMS_KEY)
      }
    }
  }

  const setSession = (data: { token: string; user: AuthUser; permissions: string[] }) => {
    token.value = data.token
    user.value = data.user
    permissions.value = data.permissions
    if (import.meta.client) {
      localStorage.setItem(TOKEN_KEY, data.token)
      localStorage.setItem(USER_KEY, JSON.stringify(data.user))
      localStorage.setItem(PERMS_KEY, JSON.stringify(data.permissions))
    }
  }

  const logout = () => {
    token.value = null
    user.value = null
    permissions.value = []
    if (import.meta.client) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      localStorage.removeItem(PERMS_KEY)
    }
    navigateTo('/login')
  }

  const can = (perm: string) => permissions.value.includes(perm)

  return { token, user, permissions, restore, setSession, logout, can }
}

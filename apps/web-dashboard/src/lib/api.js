const TOKEN_KEY = 'no7.token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export async function request(path, { method = 'GET', body, silent = false } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    if (res.status === 401) {
      setToken('')
      window.dispatchEvent(new CustomEvent('no7:unauthorized'))
    }
    const detail = data && (data.detail || data.error)
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail || data || res.statusText)
    if (!silent) throw new Error(message)
  }
  return data
}

export const api = {
  get: (path, opts) => request(path, opts),
  post: (path, body = {}, opts = {}) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body = {}, opts = {}) => request(path, { ...opts, method: 'PUT', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
}

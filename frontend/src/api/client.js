import axios from 'axios'

// In dev, baseURL stays '/api' and Vite's proxy forwards it to the backend.
// In production set VITE_API_URL (build-time) to the backend's public URL,
// e.g. VITE_API_URL=https://api.yourdomain.com — used when the frontend and
// backend are served from different domains (no reverse proxy in front).
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Endpoints where a 401 is an expected "bad credentials" response handled by
// the page itself — NOT an expired session. These must not trigger the global
// logout-and-reload, or the page reload would wipe form state and kill the
// error toast before it renders.
const AUTH_ENDPOINTS = ['/auth/login', '/auth/register', '/auth/verify-email', '/auth/forgot-password', '/auth/reset-password']

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || ''
    const isAuthAttempt = AUTH_ENDPOINTS.some((path) => url.includes(path))

    // Only force a logout/redirect when an *authenticated* request hits 401
    // (i.e. the session expired). Skip it for login/registration attempts so
    // the page can show the error inline without a full page reload.
    if (err.response?.status === 401 && !isAuthAttempt) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

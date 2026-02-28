const resolveDefaultBase = () => {
  const explicit = import.meta.env?.VITE_API_BASE
  if (explicit) return explicit

  const protocol = import.meta.env?.VITE_API_PROTOCOL ?? 'http'
  const host = import.meta.env?.VITE_API_HOST ?? 'localhost'
  const port = import.meta.env?.VITE_API_PORT ?? '8000'
  const portSegment = port === '80' || port === '443' ? '' : `:${port}`
  return `${protocol}://${host}${portSegment}/api`
}

const API_BASE = resolveDefaultBase()

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) {
    let detail = response.statusText || 'Request failed'
    try {
      const data = await response.json()
      detail = data.detail ?? detail
    } catch (err) {
      // ignore JSON parse issues and fall back to status text
    }
    throw new Error(detail)
  }
  if (response.status === 204) return null
  return response.json()
}

export function fetchModules() {
  return request('/modules')
}

export function updateModuleControls(moduleId, payload) {
  if (!moduleId) {
    return Promise.reject(new Error('Module id required'))
  }
  return request(`/modules/${moduleId}/control`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload ?? {}),
  })
}

export function fetchTemperatureHistory(options = {}) {
  const windowMinutes = Math.max(1, Math.floor(options.windowMinutes ?? 60))
  const params = new URLSearchParams({ window_minutes: windowMinutes.toString() })
  if (options.moduleId) {
    params.set('module_id', options.moduleId)
  }
  if (options.limit != null) {
    const limit = Math.max(1, Math.floor(options.limit))
    params.set('limit', limit.toString())
  }
  return request(`/temperature/history?${params.toString()}`)
}

export function fetchCycleHistory(windowHours = 24) {
  const clamped = Math.max(1, Math.floor(windowHours))
  const params = new URLSearchParams({ window_hours: clamped.toString() })
  return request(`/cycles/history?${params.toString()}`)
}

export function fetchSpoolUsageHistory(options = {}) {
  const params = new URLSearchParams()
  if (options.windowHours != null) {
    const windowHours = Math.max(1, Math.floor(options.windowHours))
    params.set('window_hours', windowHours.toString())
  }
  if (options.moduleId) {
    params.set('module_id', options.moduleId)
  }
  if (options.limit != null) {
    const limit = Math.max(1, Math.floor(options.limit))
    params.set('limit', limit.toString())
  }
  const query = params.toString()
  return request(`/spool-usage${query ? `?${query}` : ''}`)
}

export function fetchAtoTraceHistory(options = {}) {
  const params = new URLSearchParams()
  if (options.windowHours != null) {
    const windowHours = Math.max(1, Math.floor(options.windowHours))
    params.set('window_hours', windowHours.toString())
  }
  if (options.moduleId) {
    params.set('module_id', options.moduleId)
  }
  if (options.limit != null) {
    const limit = Math.max(1, Math.floor(options.limit))
    params.set('limit', limit.toString())
  }
  const query = params.toString()
  return request(`/ato/history-from-trace${query ? `?${query}` : ''}`)
}

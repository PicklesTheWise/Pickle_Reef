const resolveDefaultBase = () => {
  if (typeof window === 'undefined') {
    return '/api'
  }

  const { protocol, hostname } = window.location
  const port = import.meta.env.VITE_API_PORT ?? '80'
  const portSegment = port === '80' || port === '443' ? '' : `:${port}`
  return `${protocol}//${hostname}${portSegment}/api`
}

const API_BASE = import.meta.env.VITE_API_BASE ?? resolveDefaultBase()

async function request(path) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }
  return response.json()
}

export function fetchTelemetry(limit = 40) {
  return request(`/telemetry?limit=${limit}`)
}

export function fetchTelemetrySummary() {
  return request('/telemetry/summary')
}

export function fetchModules() {
  return request('/modules')
}

export function updateModuleControls(moduleId, payload) {
  return fetch(`${API_BASE}/modules/${moduleId}/control`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Command failed: ${response.status}`)
    }
    return response.json()
  })
}

export function fetchCycleHistory(windowHours = 24) {
  return request(`/cycles/history?window_hours=${windowHours}`)
}

export function fetchWsTrace(limit = 200) {
  return request(`/debug/ws-trace?limit=${limit}`)
}

export function fetchSpoolUsageHistory(windowHours = 72, moduleId) {
  const params = new URLSearchParams()
  params.set('window_hours', windowHours)
  if (moduleId) {
    params.set('module_id', moduleId)
  }
  return request(`/spool-usage?${params.toString()}`)
}

export function deleteModule(moduleId) {
  if (!moduleId) {
    return Promise.reject(new Error('Missing module id'))
  }
  return fetch(`${API_BASE}/modules/${moduleId}`, {
    method: 'DELETE',
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Delete failed: ${response.status}`)
    }
    return response.json()
  })
}

const resolveDefaultBase = () => {
  if (typeof window === 'undefined') {
    return '/api'
  }

  const { protocol, hostname, port: windowPort } = window.location
  const isDevServer = Boolean(import.meta.env?.DEV)
  const configuredPort = import.meta.env?.VITE_API_PORT
  const inferredPort = configuredPort ?? (isDevServer && windowPort ? windowPort : protocol === 'https:' ? '443' : '80')
  const normalizedPort = (inferredPort ?? '').toString().trim()
  const portSegment = !normalizedPort || normalizedPort === '80' || normalizedPort === '443' ? '' : `:${normalizedPort}`
  return `${protocol}//${hostname}${portSegment}/api`
}

const API_BASE = import.meta.env.VITE_API_BASE ?? resolveDefaultBase()

async function readErrorMessage(response, fallbackPrefix = 'Request failed') {
  const status = response?.status ?? 'unknown'
  try {
    const payload = await response.json()
    const detail = payload?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0]
      if (typeof first?.msg === 'string' && first.msg.trim()) {
        return first.msg
      }
    }
    if (typeof payload?.message === 'string' && payload.message.trim()) {
      return payload.message
    }
  } catch {
  }
  return `${fallbackPrefix}: ${status}`
}

async function request(path) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, 'API request failed'))
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

export async function updateModuleControls(moduleId, payload) {
  const response = await fetch(`${API_BASE}/modules/${moduleId}/control`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, 'Command failed'))
  }
  return response.json()
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

export function fetchTemperatureHistory(windowMinutes = 1440, moduleId, limit = 1440) {
  const params = new URLSearchParams()
  params.set('window_minutes', windowMinutes)
  params.set('limit', limit)
  if (moduleId) {
    params.set('module_id', moduleId)
  }
  return request(`/temperature/history?${params.toString()}`)
}

export function fetchSpoolTraceHistory(windowHours = 24, moduleId, limit = 2000) {
  const params = new URLSearchParams()
  params.set('window_hours', windowHours)
  params.set('limit', limit)
  if (moduleId) {
    params.set('module_id', moduleId)
  }
  return request(`/spool/history-from-trace?${params.toString()}`)
}

export function fetchAtoTraceHistory(windowHours = 24, moduleId, limit = 2000) {
  const params = new URLSearchParams()
  params.set('window_hours', windowHours)
  params.set('limit', limit)
  if (moduleId) {
    params.set('module_id', moduleId)
  }
  return request(`/ato/history-from-trace?${params.toString()}`)
}

export function deleteModule(moduleId) {
  if (!moduleId) {
    return Promise.reject(new Error('Missing module id'))
  }
  return fetch(`${API_BASE}/modules/${moduleId}`, {
    method: 'DELETE',
  }).then(async (response) => {
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Delete failed'))
    }
    return response.json()
  })
}

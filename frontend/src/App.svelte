<script>
  import { onDestroy, onMount } from 'svelte'
  import {
    fetchTelemetry,
    fetchTelemetrySummary,
    fetchModules,
    fetchCycleHistory,
    updateModuleControls,
    fetchWsTrace,
    fetchSpoolUsageHistory,
  } from './lib/api'
  import LineChart from './lib/LineChart.svelte'

  const DEFAULT_RUNTIME = 5000
  const DEFAULT_ROLLER_SPEED = 180
  const DEFAULT_PUMP_TIMEOUT_MS = 120000
  const DEFAULT_ALARM_CHIRP_INTERVAL_MS = 120000
  const DEFAULT_SPOOL_LENGTH_MM = 50000
  const DEFAULT_CORE_DIAMETER_MM = 19
  const SPOOL_LENGTH_MIN_MM = 10000
  const SPOOL_LENGTH_MAX_MM = 200000
  const SPOOL_SAMPLE_MM = 10000
  const DEFAULT_MEDIA_THICKNESS_UM = 100
  const MEDIA_THICKNESS_MIN_UM = 40
  const MEDIA_THICKNESS_MAX_UM = 400
  const CORE_DIAMETER_MIN_MM = 12
  const CORE_DIAMETER_MAX_MM = 80

  let telemetry = []
  let summary = []
  let modules = []
  let loading = true
  let error = ''
  let lastUpdated = ''
  let selectedModuleId = ''
  let atoMode = 'auto'
  let motorRunTimeMs = 5000
  let rollerSpeed = 180
  let pumpTimeoutMs = 120000
  let alarmChirpIntervalMs = 120000
  let controlMessage = ''
  let controlError = ''
  let controlBusy = false
  let controlsPrefilledFor = ''
  let spoolResetConfirming = false
  let spoolResetBusy = false
  let calibrationModalOpen = false
  let spoolCalibrationAwaitingAck = false
  let controlsVisible = false
  let calibrationAckTimer = null
  let calibrationAckPollInFlight = false
  const CONTROL_PUSH_DELAY_MS = 600
  let controlUpdateTimer = null
  let controlUpdatePending = false
  let cycleWindow = 24
  let cycleHistory = null
  let cycleHistoryLoading = true
  let cycleHistoryError = ''
  let rollerRuns = []
  let atoRuns = []
  let alertEntries = []
  let alarmEntries = []
  let warningEntries = []
  let displayedAlerts = []
  let alarmQueue = []
  let activeAlarmModal = null
  let lastAlarmKeys = new Set()
  let acknowledgedAlarmKeys = new Set()
  let spoolLengthMm = 50000
  let coreDiameterMm = DEFAULT_CORE_DIAMETER_MM
  let mediaThicknessUm = DEFAULT_MEDIA_THICKNESS_UM
  let mediaProfileBusy = false
  let spoolCalibrationBusy = false
  let wsLogPanelOpen = false
  let wsLogEntries = []
  let wsLogLoading = false
  let wsLogError = ''
  let wsLogInterval = null
  let spoolUsageHistory = []
  const WS_LOG_REFRESH_MS = 3000
  const HOUR_IN_MS = 60 * 60 * 1000
  const USAGE_HISTORY_WINDOW_MS = 30 * 24 * HOUR_IN_MS
  const USAGE_HISTORY_WINDOW_HOURS = USAGE_HISTORY_WINDOW_MS / HOUR_IN_MS
  const usageWindowPresets = [
    { hours: 1, label: '1h', description: 'Rolling last hour' },
    { hours: 6, label: '6h', description: 'Rolling last 6 hours' },
    { hours: 12, label: '12h', description: 'Rolling last 12 hours' },
    { hours: 24, label: '1d', description: 'Rolling last 24 hours' },
    { hours: 72, label: '3d', description: 'Rolling last 3 days' },
    { hours: 30 * 24, label: '1mo', description: 'Rolling last 30 days' },
    { hours: 6 * 30 * 24, label: '6mo', description: 'Rolling last 6 months' },
    { hours: 365 * 24, label: '1yr', description: 'Rolling last year' },
  ]
  const defaultUsagePreset = usageWindowPresets.find((preset) => preset.hours === 24) ?? usageWindowPresets[0]
  let usageChartWindowHours = defaultUsagePreset?.hours ?? 24
  let usageChartWindowMs = usageChartWindowHours * HOUR_IN_MS
  const SPOOL_RESET_EDGE_THRESHOLD = 10
  const spoolSnapshots = new Map()
  const SPOOL_USAGE_STORAGE_KEY = 'pickle-reef::spool-usage-history'
  const SPOOL_RESET_STORAGE_KEY = 'pickle-reef::spool-reset-epoch'
  const spoolResetTimestamps = new Map()
  let spoolResetVersion = 0

  const resolveStorage = () => {
    if (typeof window === 'undefined') return null
    try {
      return window.localStorage ?? null
    } catch (err) {
      console.warn('Local storage unavailable', err)
      return null
    }
  }

  const sanitizeSpoolEntry = (entry) => {
    if (!entry || typeof entry !== 'object') return null
    const moduleId = entry.moduleId ?? entry.module_id
    const timestamp =
      typeof entry.timestamp === 'number'
        ? entry.timestamp
        : new Date(entry.timestamp).getTime()
    if (!moduleId || !Number.isFinite(timestamp)) return null
    return {
      moduleId,
      timestamp,
      deltaEdges: typeof entry.deltaEdges === 'number' ? entry.deltaEdges : entry.delta_edges ?? 0,
      deltaMm: typeof entry.deltaMm === 'number' ? entry.deltaMm : entry.delta_mm ?? 0,
      totalUsedEdges:
        typeof entry.totalUsedEdges === 'number'
          ? entry.totalUsedEdges
          : entry.total_used_edges ?? null,
    }
  }

  function hydrateStoredSpoolUsageHistory() {
    const storage = resolveStorage()
    if (!storage) return []
    try {
      const raw = storage.getItem(SPOOL_USAGE_STORAGE_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) return []
      const cutoff = Date.now() - USAGE_HISTORY_WINDOW_MS
      return parsed
        .map(sanitizeSpoolEntry)
        .filter((entry) => entry && entry.timestamp >= cutoff)
    } catch (err) {
      console.warn('Unable to hydrate spool usage history', err)
      return []
    }
  }

  function persistSpoolUsageHistory(history = []) {
    const storage = resolveStorage()
    if (!storage) return
    try {
      const cutoff = Date.now() - USAGE_HISTORY_WINDOW_MS
      const payload = history
        .map(sanitizeSpoolEntry)
        .filter((entry) => entry && entry.timestamp >= cutoff)
      storage.setItem(SPOOL_USAGE_STORAGE_KEY, JSON.stringify(payload))
    } catch (err) {
      console.warn('Unable to persist spool usage history', err)
    }
  }

  const bumpSpoolResetVersion = () => {
    spoolResetVersion += 1
  }

  function hydrateStoredSpoolResetTimestamps() {
    const storage = resolveStorage()
    if (!storage) return new Map()
    try {
      const raw = storage.getItem(SPOOL_RESET_STORAGE_KEY)
      if (!raw) return new Map()
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object') return new Map()
      const entries = Object.entries(parsed).filter((entry) => {
        const [moduleId, timestamp] = entry
        return typeof moduleId === 'string' && typeof timestamp === 'number' && timestamp > 0
      })
      return new Map(entries)
    } catch (err) {
      console.warn('Unable to hydrate spool reset timestamps', err)
      return new Map()
    }
  }

  function persistSpoolResetTimestamps() {
    const storage = resolveStorage()
    if (!storage) return
    try {
      const now = Date.now()
      const cutoff = now - USAGE_HISTORY_WINDOW_MS
      const payload = {}
      spoolResetTimestamps.forEach((timestamp, moduleId) => {
        if (typeof timestamp === 'number' && timestamp > cutoff) {
          payload[moduleId] = timestamp
        }
      })
      storage.setItem(SPOOL_RESET_STORAGE_KEY, JSON.stringify(payload))
    } catch (err) {
      console.warn('Unable to persist spool reset timestamps', err)
    }
  }

  const getModuleResetBaseline = (moduleId) => {
    const ts = spoolResetTimestamps.get(moduleId)
    return typeof ts === 'number' ? ts : 0
  }

  function markSpoolReset(moduleId, timestamp = Date.now()) {
    if (!moduleId) return
    spoolResetTimestamps.set(moduleId, timestamp)
    bumpSpoolResetVersion()
    persistSpoolResetTimestamps()
  }

  function handleSpoolReset(moduleId, timestamp = Date.now()) {
    if (!moduleId) return
    const hadHistory = spoolUsageHistory.some((entry) => entry.moduleId === moduleId)
    spoolSnapshots.delete(moduleId)
    if (hadHistory) {
      spoolUsageHistory = spoolUsageHistory.filter((entry) => entry.moduleId !== moduleId)
      persistSpoolUsageHistory(spoolUsageHistory)
    }
    markSpoolReset(moduleId, timestamp)
  }

  const normalizeSpoolTelemetry = (module) => {
    if (!module?.module_id) return null
    const spool =
      module.spool_state ??
      module.status_payload?.spool ??
      module.statusPayload?.spool ??
      module.spool ??
      {}
    const fullEdges = coalesceNumber(spool.full_edges)
    if (!fullEdges || fullEdges <= 0) return null
    const totalLength = coalesceNumber(spool.total_length_mm, spool.length_mm) ?? DEFAULT_SPOOL_LENGTH_MM
    if (!totalLength || totalLength <= 0) return null
    const mmPerEdge = totalLength / fullEdges
    const usedEdges = coalesceNumber(spool.used_edges)
    const remainingEdges = coalesceNumber(spool.remaining_edges)
    const normalizedUsedEdges =
      typeof usedEdges === 'number'
        ? usedEdges
        : typeof remainingEdges === 'number'
          ? Math.max(0, fullEdges - remainingEdges)
          : null
    if (normalizedUsedEdges == null) return null
    return { moduleId: module.module_id, normalizedUsedEdges, mmPerEdge }
  }

  function detectSpoolResets(moduleList = []) {
    const now = Date.now()
    moduleList.forEach((module) => {
      const snapshot = normalizeSpoolTelemetry(module)
      if (!snapshot) return
      const previous = spoolSnapshots.get(snapshot.moduleId)
      if (previous) {
        const drop = previous.usedEdges - snapshot.normalizedUsedEdges
        if (drop > SPOOL_RESET_EDGE_THRESHOLD) {
          handleSpoolReset(snapshot.moduleId, now)
        }
      }
      spoolSnapshots.set(snapshot.moduleId, {
        usedEdges: snapshot.normalizedUsedEdges,
        timestamp: now,
      })
    })
  }

  const fallbackTelemetry = [
    {
      module_id: 'reef-probe-01',
      metric: 'temperature',
      value: 25.8,
      unit: '°C',
      captured_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(),
    },
    {
      module_id: 'reef-probe-01',
      metric: 'ph',
      value: 8.12,
      unit: 'pH',
      captured_at: new Date(Date.now() - 1000 * 60 * 3).toISOString(),
    },
    {
      module_id: 'reef-cabinet-ctrl',
      metric: 'orp',
      value: 385,
      unit: 'mV',
      captured_at: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    },
    {
      module_id: 'reef-chiller',
      metric: 'flow_rate',
      value: 420,
      unit: 'L/h',
      captured_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    },
  ]

  const fallbackModules = [
    {
      module_id: 'reef-probe-01',
      label: 'Canary Probe',
      firmware_version: '1.2.0',
      status: 'online',
      ip_address: '192.168.10.54',
      rssi: -48,
      last_seen: new Date().toISOString(),
      status_payload: {
        motor: { state: 'running', speed: 182, run_time_ms: 2400, mode: 'auto' },
        floats: { main: false, min: false, max: true },
        ato: { pump_running: false, manual_mode: false, paused: false, timeout_alarm: false, pump_speed: 140 },
        system: { chirp_enabled: true, uptime_s: 18_200, pump_timeout_ms: 120_000 },
        spool: {
          full_edges: 528_000,
          used_edges: 68_000,
          remaining_edges: 460_000,
          percent_remaining: 87,
          empty_alarm: false,
          total_length_mm: 50_000,
          sample_length_mm: 10_000,
          calibrating: false,
        },
      },
      alarms: [
        {
          code: 'pump_timeout',
          severity: 'warning',
          active: true,
          message: 'ATO pump exceeded pump_timeout_ms',
          timestamp_s: 18_000,
          meta: { timeout_ms: 120000, runtime_ms: 135000 },
          received_at: new Date().toISOString(),
        },
      ],
    },
    {
      module_id: 'reef-cabinet-ctrl',
      label: 'Cabinet Controller',
      firmware_version: '0.9.5',
      status: 'discovering',
      ip_address: '192.168.10.88',
      rssi: -62,
      last_seen: new Date(Date.now() - 1000 * 30).toISOString(),
      status_payload: {
        motor: { state: 'stopped', speed: 0, run_time_ms: 0, mode: 'manual' },
        floats: { main: false, min: true, max: false },
        ato: { pump_running: true, manual_mode: true, paused: false, timeout_alarm: false, pump_speed: 180 },
        system: { chirp_enabled: false, uptime_s: 2600, pump_timeout_ms: 180_000 },
        spool: {
          full_edges: 528_000,
          used_edges: 500_000,
          remaining_edges: 28_000,
          percent_remaining: 5,
          empty_alarm: false,
          total_length_mm: 50_000,
          sample_length_mm: 10_000,
          calibrating: false,
        },
      },
      alarms: [],
    },
  ]

  const fallbackRollerEvents = [
    { hoursAgo: 2, duration: 3200, type: 'roller_auto', trigger: 'main_float' },
    { hoursAgo: 6, duration: 1800, type: 'roller_auto', trigger: 'auto_timer' },
    { hoursAgo: 12, duration: 2400, type: 'roller_manual', trigger: 'manual_button' },
    { hoursAgo: 20, duration: 2800, type: 'roller_auto', trigger: 'main_float' },
    { hoursAgo: 30, duration: 2000, type: 'roller_auto', trigger: 'auto_timer' },
    { hoursAgo: 55, duration: 2600, type: 'roller_auto', trigger: 'main_float' },
    { hoursAgo: 90, duration: 3100, type: 'roller_auto', trigger: 'main_float' },
    { hoursAgo: 130, duration: 2300, type: 'roller_manual', trigger: 'manual_button' },
  ]

  const fallbackPumpEvents = [
    { hoursAgo: 1.5, duration: 7800, type: 'pump_normal', trigger: 'min_float' },
    { hoursAgo: 8, duration: 6400, type: 'pump_normal', trigger: 'auto_timer' },
    { hoursAgo: 16, duration: 7200, type: 'pump_manual', trigger: 'manual_button' },
    { hoursAgo: 26, duration: 6800, type: 'pump_normal', trigger: 'min_float' },
    { hoursAgo: 40, duration: 7100, type: 'pump_normal', trigger: 'min_float' },
    { hoursAgo: 65, duration: 7500, type: 'pump_normal', trigger: 'auto_timer' },
    { hoursAgo: 110, duration: 7000, type: 'pump_manual', trigger: 'manual_button' },
  ]

  const stopWsLogPolling = () => {
    if (wsLogInterval) {
      clearInterval(wsLogInterval)
      wsLogInterval = null
    }
  }

  const startWsLogPolling = () => {
    if (wsLogInterval) return
    refreshWsLog()
    wsLogInterval = setInterval(() => {
      refreshWsLog()
    }, WS_LOG_REFRESH_MS)
  }

  async function refreshWsLog() {
    wsLogLoading = true
    wsLogError = ''
    try {
      const trace = await fetchWsTrace()
      const entries = Array.isArray(trace)
        ? trace
        : Array.isArray(trace?.entries)
          ? trace.entries
          : []
      wsLogEntries = entries
    } catch (err) {
      wsLogError = err.message ?? 'Unable to load WebSocket trace.'
    } finally {
      wsLogLoading = false
    }
  }

  const openWsLogPanel = () => {
    if (wsLogPanelOpen) return
    wsLogPanelOpen = true
    startWsLogPolling()
  }

  const closeWsLogPanel = () => {
    if (!wsLogPanelOpen) return
    wsLogPanelOpen = false
    stopWsLogPolling()
  }

  const summarizeCycles = (records, windowHours) => {
    const count = records.length
    const totalDuration = records.reduce((sum, record) => sum + (record.duration_ms ?? 0), 0)
    const avgDuration = count ? totalDuration / count : 0
    const frequency = count && windowHours ? count / windowHours : 0
    return {
      count,
      total_duration_ms: totalDuration,
      avg_duration_ms: avgDuration,
      frequency_per_hour: frequency,
    }
  }

  const buildFallbackCycleHistory = (windowHours = 24) => {
    const toRecord = (event, index, moduleId) => ({
      id: index + 1,
      module_id: moduleId,
      cycle_type: event.type,
      trigger: event.trigger,
      duration_ms: event.duration,
      timeout: Boolean(event.timeout),
      recorded_at: new Date(Date.now() - event.hoursAgo * 60 * 60 * 1000).toISOString(),
    })

    const rollerRuns = fallbackRollerEvents
      .filter((event) => event.hoursAgo <= windowHours)
      .map((event, index) => toRecord(event, index, 'reef-roller-demo'))
    const atoRuns = fallbackPumpEvents
      .filter((event) => event.hoursAgo <= windowHours)
      .map((event, index) => toRecord(event, index, 'reef-roller-demo'))

    const rollerStats = summarizeCycles(rollerRuns, windowHours)
    const atoStats = summarizeCycles(atoRuns, windowHours)
    atoStats.avg_fill_seconds = atoStats.avg_duration_ms ? atoStats.avg_duration_ms / 1000 : 0

    return {
      window_hours: windowHours,
      roller_runs: rollerRuns,
      roller_stats: rollerStats,
      ato_runs: atoRuns,
      ato_stats: atoStats,
    }
  }

  const metricCopy = {
    temperature: { label: 'Water Temp', unit: '°C' },
    ph: { label: 'pH', unit: '' },
    orp: { label: 'ORP', unit: 'mV' },
    flow_rate: { label: 'Flow Rate', unit: 'L/h' },
  }

  const floatIndicators = [
    { key: 'main', label: 'Filter' },
    { key: 'min', label: 'Min' },
    { key: 'max', label: 'Max' },
  ]

  const severityOrder = { critical: 0, warning: 1, info: 2 }

  const formatWindowLabel = (hours) => (hours >= 24 ? `${hours / 24}d` : `${hours}h`)
  const findUsageWindowPreset = (hours) => usageWindowPresets.find((preset) => preset.hours === hours)
  const formatUsageWindowShort = (hours) => {
    const preset = findUsageWindowPreset(hours)
    if (preset) return preset.label
    return formatWindowLabel(hours)
  }
  const describeUsageWindow = (hours) => {
    const preset = findUsageWindowPreset(hours)
    if (preset?.description) return preset.description
    if (hours >= 24) {
      const days = hours / 24
      return `Rolling last ${days} day${days === 1 ? '' : 's'}`
    }
    return `Rolling last ${hours} hour${hours === 1 ? '' : 's'}`
  }
  const describeSpoolMetricBaseline = (timestamp) => {
    if (!timestamp) return 'Clears when spool resets'
    const date = new Date(timestamp)
    return Number.isNaN(date.getTime()) ? 'Clears when spool resets' : `Since reset ${date.toLocaleString()}`
  }
  const getUsageWindowStart = () => Math.max(Date.now() - usageChartWindowMs, moduleSpoolBaselineMs || 0)

  const formatCycleDuration = (ms) => {
    if (!ms && ms !== 0) return '—'
    if (ms >= 1000) {
      return `${(ms / 1000).toFixed(1)}s`
    }
    return `${ms}ms`
  }

  const formatCycleTimestamp = (timestamp) => {
    if (!timestamp) return '—'
    return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const buildActivationDatasets = (markers, maxValue) => {
    if (!markers?.length || !maxValue) return []
    const data = []
    markers.forEach((marker) => {
      data.push({ x: marker.ts, y: 0 })
      data.push({ x: marker.ts, y: maxValue })
      data.push({ x: null, y: null })
    })
    return [
      {
        label: 'Roller activations',
        data,
        borderColor: 'rgba(248, 251, 255, 0.4)',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
        showLine: true,
        spanGaps: false,
        parsing: false,
        hoverRadius: 0,
        tooltip: { enabled: false },
      },
    ]
  }

  const usageTooltipFormatter = (context) => {
    const raw = context.raw ?? {}
    const value = typeof raw.y === 'number' ? raw.y : context.parsed?.y
    const timeValue = raw.x ?? context.parsed?.x
    if (value === undefined || timeValue === undefined) return ''
    return `${formatSpoolMediaLength(value)} • ${formatCycleTimestamp(timeValue)}`
  }

  const atoTooltipFormatter = (context) => {
    const raw = context.raw ?? {}
    const value = typeof raw.y === 'number' ? raw.y : context.parsed?.y
    const timeValue = raw.x ?? context.parsed?.x
    if (value === undefined || timeValue === undefined) return ''
    return `${formatCycleDuration(value)} • ${formatCycleTimestamp(timeValue)}`
  }

  const deriveDurationTargetMax = (runs) => {
    if (!runs?.length) return 1
    const maxDuration = Math.max(...runs.map((run) => run.duration_ms || 0), 0)
    return Math.max(maxDuration * 1.1, 1)
  }

  const buildChartPoints = (runs) => {
    if (!runs?.length) return []
    const sortedRuns = [...runs].sort(
      (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
    )
    return sortedRuns.map((run) => {
      const ts = new Date(run.recorded_at).getTime()
      const duration = run.duration_ms || 0
      return {
        ts,
        duration,
        timestamp: run.recorded_at,
      }
    })
  }

  const deriveSummary = (dataset) => {
    const buckets = new Map()
    dataset.forEach((row) => {
      const entry = buckets.get(row.metric) ?? { total: 0, count: 0, latest: row.captured_at }
      entry.total += row.value
      entry.count += 1
      entry.latest = new Date(row.captured_at) > new Date(entry.latest) ? row.captured_at : entry.latest
      buckets.set(row.metric, entry)
    })
    return Array.from(buckets.entries()).map(([metric, data]) => ({
      metric,
      avg_value: data.total / data.count,
      last_seen: data.latest,
    }))
  }

  async function refresh() {
    try {
      const [telemetryResponse, summaryResponse, moduleResponse] = await Promise.all([
        fetchTelemetry(),
        fetchTelemetrySummary(),
        fetchModules(),
      ])

      telemetry = telemetryResponse
      summary = summaryResponse
      modules = moduleResponse
      detectSpoolResets(moduleResponse)
      await loadSpoolUsageHistory(moduleResponse)
      error = ''
      controlError = ''
    } catch (err) {
      console.warn('Falling back to demo data', err)
      if (!telemetry.length) {
        telemetry = fallbackTelemetry
        summary = deriveSummary(fallbackTelemetry)
        modules = fallbackModules
        const fallbackForTracking = fallbackModules.map((module) => ({
          ...module,
          spool_state: module.status_payload?.spool ?? module.spool ?? {},
        }))
        trackSpoolUsage(fallbackForTracking)
      }
      error = 'Live modules not responding — displaying demo stream.'
    } finally {
      loading = false
      lastUpdated = new Date().toLocaleTimeString()
    }
  }

  async function loadCycleHistory(windowHours = cycleWindow) {
    cycleHistoryLoading = true
    cycleHistoryError = ''
    try {
      cycleHistory = await fetchCycleHistory(windowHours)
    } catch (err) {
      console.warn('Unable to load cycle history', err)
      if (!cycleHistory) {
        cycleHistory = buildFallbackCycleHistory(windowHours)
      }
      cycleHistoryError = 'Unable to load cycle history — showing cached data.'
    } finally {
      cycleHistoryLoading = false
    }
  }

  onMount(() => {
    spoolUsageHistory = hydrateStoredSpoolUsageHistory()
    if (spoolUsageHistory.length) {
      persistSpoolUsageHistory(spoolUsageHistory)
    }
    const storedResets = hydrateStoredSpoolResetTimestamps()
    spoolResetTimestamps.clear()
    storedResets.forEach((timestamp, moduleId) => {
      if (typeof timestamp === 'number' && moduleId) {
        spoolResetTimestamps.set(moduleId, timestamp)
      }
    })
    if (storedResets.size) {
      bumpSpoolResetVersion()
    }
    refresh()
    loadCycleHistory(cycleWindow)
    const interval = setInterval(() => {
      refresh()
    }, 15000)
    return () => {
      clearInterval(interval)
      stopWsLogPolling()
    }
  })

  onDestroy(() => {
    if (calibrationAckTimer) {
      clearInterval(calibrationAckTimer)
      calibrationAckTimer = null
    }
  })

  $: usageChartWindowMs = usageChartWindowHours * HOUR_IN_MS
  $: latestByMetric = telemetry.reduce((acc, row) => {
    const timestamp = new Date(row.captured_at).getTime()
    const existingTs = acc[row.metric]?.ts ?? 0
    if (timestamp > existingTs) {
      acc[row.metric] = { value: row.value, unit: row.unit, ts: timestamp }
    }
    return acc
  }, {})

  $: moduleCounts = modules.reduce(
    (acc, module) => {
      acc[module.status] = (acc[module.status] ?? 0) + 1
      return acc
    },
    { online: 0, offline: 0, discovering: 0 }
  )

  const statusPalette = {
    online: 'status-online',
    offline: 'status-offline',
    discovering: 'status-discovering',
  }

  const deriveAtoMode = (module) => {
    if (!module) return 'auto'
    if (module.ato?.paused) return 'paused'
    if (module.ato?.manual_mode) return 'manual'
    return 'auto'
  }

  const hydrateModule = (module) => {
    const statusPayload = module?.status_payload ?? {}
    const configPayload = module?.config_payload ?? {}
    const configMotor = configPayload.motor ?? {}
    const statusMotor = statusPayload.motor ?? {}
    const configAto = configPayload.ato ?? {}
    const statusAto = statusPayload.ato ?? {}

    const configSpool = configPayload.spool ?? {}
    const statusSpool = statusPayload.spool ?? {}
    const mergedSpool = module?.spool_state ?? { ...configSpool, ...statusSpool }

    return {
      ...module,
      statusPayload,
      configPayload,
      motor: { ...configMotor, ...statusMotor },
      floats: statusPayload.floats ?? {},
      ato: { ...configAto, ...statusAto },
      system: statusPayload.system ?? {},
      spool: mergedSpool,
      alarms: module.alarms ?? [],
    }
  }

  const coalesceNumber = (...values) => {
    for (const value of values) {
      if (typeof value === 'number' && !Number.isNaN(value)) {
        return value
      }
    }
    return undefined
  }

  function trackSpoolUsage(moduleList = []) {
    const now = Date.now()
    let updatedHistory = [...spoolUsageHistory]

    moduleList.forEach((module) => {
      const snapshot = normalizeSpoolTelemetry(module)
      if (!snapshot) return
      const { moduleId, normalizedUsedEdges, mmPerEdge } = snapshot
      const previous = spoolSnapshots.get(moduleId)
      if (previous) {
        const drop = previous.usedEdges - normalizedUsedEdges
        if (drop > SPOOL_RESET_EDGE_THRESHOLD) {
          handleSpoolReset(moduleId, now)
          spoolSnapshots.set(moduleId, { usedEdges: normalizedUsedEdges, timestamp: now })
          return
        }
      }

      if (!previous) {
        spoolSnapshots.set(moduleId, { usedEdges: normalizedUsedEdges, timestamp: now })
        return
      }

      if (normalizedUsedEdges >= previous.usedEdges) {
        const deltaEdges = normalizedUsedEdges - previous.usedEdges
        if (deltaEdges > 0) {
          const deltaMm = deltaEdges * mmPerEdge
          updatedHistory = [
            ...updatedHistory,
            {
              moduleId,
              timestamp: now,
              deltaEdges,
              deltaMm,
              totalUsedEdges: normalizedUsedEdges,
            },
          ]
        }
      }

      spoolSnapshots.set(moduleId, { usedEdges: normalizedUsedEdges, timestamp: now })
    })

    const cutoff = now - USAGE_HISTORY_WINDOW_MS
    updatedHistory = updatedHistory.filter((entry) => entry.timestamp >= cutoff)
    spoolUsageHistory = updatedHistory
    persistSpoolUsageHistory(spoolUsageHistory)
  }

  async function loadSpoolUsageHistory(moduleSnapshot = []) {
    try {
      const windowHours = Math.round(USAGE_HISTORY_WINDOW_HOURS)
      const history = await fetchSpoolUsageHistory(windowHours)
      const now = Date.now()
      const cutoff = now - USAGE_HISTORY_WINDOW_MS
      spoolUsageHistory = history
        .map((entry) => ({
          moduleId: entry.module_id,
          timestamp: new Date(entry.recorded_at).getTime(),
          deltaEdges: entry.delta_edges ?? 0,
          deltaMm: entry.delta_mm ?? 0,
          totalUsedEdges: entry.total_used_edges ?? null,
        }))
        .filter((entry) => {
          const baseline = getModuleResetBaseline(entry.moduleId)
          const threshold = Math.max(cutoff, baseline)
          return entry.timestamp >= threshold
        })
      persistSpoolUsageHistory(spoolUsageHistory)
    } catch (err) {
      console.warn('Unable to load spool usage history', err)
      if (moduleSnapshot.length) {
        trackSpoolUsage(moduleSnapshot)
      }
    }
  }

  const formatMotorDetails = (motor = {}) => {
    if (motor.speed == null || motor.speed === 0) {
      return motor.state ? 'Idle' : 'No telemetry yet'
    }
    return `${motor.speed} PWM`
  }

  const formatState = (value) => {
    if (typeof value !== 'string' || !value.length) return '—'
    return value.slice(0, 1).toUpperCase() + value.slice(1)
  }

  const describePump = (ato = {}) => {
    if (ato.timeout_alarm) return 'Timeout alarm'
    if (ato.paused) return 'Paused'
    if (ato.manual_mode && ato.pump_running) return 'Manual override'
    if (ato.manual_mode) return 'Manual ready'
    return ato.pump_running ? 'Pump active' : 'Pump idle'
  }

  const severityCopy = {
    critical: { label: 'Critical', badge: 'badge-danger' },
    warning: { label: 'Warning', badge: 'badge-warning' },
    info: { label: 'Info', badge: 'badge-info' },
  }

  const getSeverityMeta = (severity) => severityCopy[severity] ?? severityCopy.info

  const formatAlertTimestamp = (timestamp) => {
    if (timestamp == null) return 'just now'
    if (typeof timestamp === 'number') {
      return `${timestamp}s since boot`
    }
    const date = new Date(timestamp)
    return Number.isNaN(date.getTime()) ? 'just now' : date.toLocaleString()
  }

  const createAlert = (module, details = {}) => {
    const code = details.code ?? `alert-${Date.now()}`
    return {
      key: `${module.module_id}-${code}`,
      code,
      severity: details.severity ?? 'warning',
      description: details.description ?? details.message ?? code,
      message: details.message ?? details.description ?? code,
      moduleId: module.module_id,
      moduleLabel: module.label ?? module.module_id,
      timestamp: details.timestamp ?? module.last_seen,
      meta: details.meta ?? null,
      requiresAck: Boolean(details.requiresAck),
    }
  }

  const formatEdgeCount = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return null
    if (value >= 1_000_000) {
      return `${(value / 1_000_000).toFixed(1)}M`
    }
    if (value >= 1_000) {
      const decimals = value >= 100_000 ? 0 : 1
      return `${(value / 1_000).toFixed(decimals)}k`
    }
    return `${Math.round(value)}`
  }

  const estimateRemainingMillimeters = (spool = {}) => {
    if (!spool || typeof spool !== 'object') return undefined
    const directLength = coalesceNumber(spool.remaining_length_mm, spool.length_mm_remaining)
    if (typeof directLength === 'number') {
      return Math.max(0, directLength)
    }

    const totalLength = coalesceNumber(spool.total_length_mm, spool.length_mm)
    if (typeof totalLength !== 'number' || totalLength <= 0) {
      return undefined
    }

    const fullEdges =
      typeof spool.full_edges === 'number' && spool.full_edges > 0 ? spool.full_edges : undefined

    if (fullEdges) {
      if (typeof spool.remaining_edges === 'number') {
        return Math.max(0, (spool.remaining_edges / fullEdges) * totalLength)
      }
      if (typeof spool.used_edges === 'number') {
        const derivedRemaining = fullEdges - spool.used_edges
        return Math.max(0, (derivedRemaining / fullEdges) * totalLength)
      }
    }

    if (typeof spool.percent_remaining === 'number') {
      return Math.max(0, (spool.percent_remaining / 100) * totalLength)
    }

    return undefined
  }

  const formatSpoolMediaLength = (millimeters) => {
    if (typeof millimeters !== 'number' || Number.isNaN(millimeters)) return null
    const clamped = Math.max(0, millimeters)
    const roundToTenth = (value) => Math.round(value * 10) / 10
    const formatCentimeters = (value) => {
      const rounded = roundToTenth(value)
      return Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)
    }

    if (clamped >= 1000) {
      const totalCentimeters = clamped / 10
      const meters = Math.floor(totalCentimeters / 100)
      const centimeterPart = roundToTenth(totalCentimeters - meters * 100)
      const centimeterLabel = centimeterPart > 0 ? `${formatCentimeters(centimeterPart)} cm` : ''
      return centimeterLabel ? `${meters} m ${centimeterLabel}` : `${meters} m`
    }

    if (clamped > 100) {
      const centimeters = clamped / 10
      return `${formatCentimeters(centimeters)} cm`
    }

    return `${Math.round(clamped)} mm`
  }

  const formatMicrons = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—'
    return `${Math.round(value)} um`
  }

  const formatMmPerEdge = (millimeters) => {
    if (typeof millimeters !== 'number' || Number.isNaN(millimeters)) return null
    if (millimeters >= 10) {
      return `${millimeters.toFixed(1)} mm/edge`
    }
    if (millimeters >= 1) {
      return `${millimeters.toFixed(2)} mm/edge`
    }
    return `${millimeters.toFixed(3)} mm/edge`
  }

  const formatMillimeters = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—'
    return `${value.toLocaleString()} mm`
  }

  const formatMeters = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—'
    const meters = value / 1000
    const decimals = Number.isInteger(meters) ? 0 : 1
    return `${meters.toFixed(decimals)} m`
  }

  const formatChirpInterval = (value) => {
    const numeric = Number(value)
    if (Number.isNaN(numeric)) return '—'
    if (numeric < 60_000) {
      const seconds = numeric / 1000
      const decimals = Number.isInteger(seconds) ? 0 : 1
      return `${seconds.toFixed(decimals)}s`
    }
    const minutes = numeric / 60000
    const decimals = minutes >= 10 || Number.isInteger(minutes) ? 0 : 1
    return `${minutes.toFixed(decimals)} min`
  }

  const computeSpoolPercent = (spool = {}) => {
    if (!spool || typeof spool !== 'object') return undefined
    if (typeof spool.percent_remaining === 'number' && !Number.isNaN(spool.percent_remaining)) {
      return spool.percent_remaining
    }
    const { full_edges, remaining_edges, used_edges } = spool
    if (typeof full_edges === 'number' && full_edges > 0) {
      if (typeof remaining_edges === 'number') {
        return (remaining_edges / full_edges) * 100
      }
      if (typeof used_edges === 'number') {
        return ((full_edges - used_edges) / full_edges) * 100
      }
    }
    return undefined
  }

  const normalizedSpoolPercent = (spool = {}) => {
    const percent = computeSpoolPercent(spool)
    if (typeof percent !== 'number' || Number.isNaN(percent)) return undefined
    return Math.max(0, Math.min(100, Math.round(percent)))
  }

  const formatSpoolPercent = (spool = {}) => {
    const percent = normalizedSpoolPercent(spool)
    if (percent == null) return '—'
    return `${percent}%`
  }

  const describeSpool = (spool = {}) => {
    if (!spool || Object.keys(spool).length === 0) return 'Awaiting spool telemetry'
    if (spool.calibrating) return 'Calibration sample in progress'
    if (spool.empty_alarm) return 'Empty / jammed detected'
    const remainingMedia = formatSpoolMediaLength(estimateRemainingMillimeters(spool))
    if (remainingMedia) return `${remainingMedia} remaining`
    const remaining = formatEdgeCount(spool.remaining_edges)
    if (remaining) return `${remaining} edges remaining`
    const used = formatEdgeCount(spool.used_edges)
    if (used && typeof spool.full_edges === 'number') {
      const total = formatEdgeCount(spool.full_edges)
      return `${used} / ${total ?? '?'} consumed`
    }
    if (typeof spool.total_length_mm === 'number') {
      return `Calibrated for ${formatMillimeters(spool.total_length_mm)}`
    }
    return 'Tracking roller usage'
  }

  const spoolMeterWidth = (spool = {}) => normalizedSpoolPercent(spool) ?? 0

  const isSpoolLow = (spool = {}) => {
    if (!spool) return false
    if (spool.empty_alarm) return true
    const percent = normalizedSpoolPercent(spool)
    return typeof percent === 'number' && percent <= 15
  }

  const buildModuleAlerts = (module = {}) => {
    if (!module?.module_id) return []
    const alerts = []
    const activeFirmwareAlarms = (module.alarms ?? []).filter((alarm) => alarm.active !== false)

    activeFirmwareAlarms.forEach((alarm) => {
      alerts.push(
        createAlert(module, {
          code: alarm.code ?? `alarm-${module.module_id}`,
          severity: alarm.severity ?? 'warning',
          message: alarm.message ?? 'Module alarm',
          timestamp: alarm.received_at ?? alarm.timestamp_s,
          meta: alarm.meta ?? {},
          requiresAck: true,
        })
      )
    })

    const hasTimeoutAlarm = activeFirmwareAlarms.some((alarm) => alarm.code === 'pump_timeout')

    if (module.ato?.timeout_alarm && !hasTimeoutAlarm) {
      alerts.push(
        createAlert(module, {
          code: 'ato-timeout',
          severity: 'warning',
          description: 'ATO timeout alarm',
          requiresAck: false,
        })
      )
    }
    if (module.status === 'offline') {
      alerts.push(
        createAlert(module, {
          code: 'status-offline',
          severity: 'warning',
          description: 'Module offline',
        })
      )
    }
    if (module.ato?.paused) {
      alerts.push(
        createAlert(module, {
          code: 'ato-paused',
          severity: 'info',
          description: 'ATO paused',
        })
      )
    }
    if (module.floats?.min) {
      alerts.push(
        createAlert(module, {
          code: 'float-min',
          severity: 'warning',
          description: 'Low water float triggered',
        })
      )
    }
    if (module.spool?.empty_alarm) {
      alerts.push(
        createAlert(module, {
          code: 'spool-empty',
          severity: 'critical',
          description: 'Filter roll empty',
          meta: {
            percent_remaining: normalizedSpoolPercent(module.spool),
            remaining_edges: formatEdgeCount(module.spool.remaining_edges) ?? module.spool.remaining_edges,
          },
          requiresAck: true,
        })
      )
    } else if (isSpoolLow(module.spool)) {
      alerts.push(
        createAlert(module, {
          code: 'spool-low',
          severity: 'warning',
          description: 'Filter roll running low',
        })
      )
    }
    return alerts
  }

  function presentNextAlarm() {
    if (!alarmQueue.length) {
      activeAlarmModal = null
      return
    }

    const [next, ...rest] = alarmQueue
    alarmQueue = rest

    if (acknowledgedAlarmKeys.has(next.key)) {
      presentNextAlarm()
      return
    }

    activeAlarmModal = next
  }

  function acknowledgeAlarm() {
    if (!activeAlarmModal) return
    const updated = new Set(acknowledgedAlarmKeys)
    updated.add(activeAlarmModal.key)
    acknowledgedAlarmKeys = updated
    activeAlarmModal = null
    presentNextAlarm()
  }

  function focusAlarmModule() {
    if (!activeAlarmModal) return
    selectedModuleId = activeAlarmModal.moduleId
  }

  const formatDuration = (seconds) => {
    if (seconds == null) return '—'
    const hrs = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    if (hrs > 0) {
      return `${hrs}h ${mins}m`
    }
    return `${mins}m` + (seconds % 60 ? ` ${seconds % 60}s` : '')
  }

  const formatValue = (metric) => {
    const latest = latestByMetric[metric]
    if (!latest) {
      return '—'
    }
    const { unit } = metricCopy[metric]
    return `${latest.value.toFixed(2)} ${unit}`.trim()
  }

  const formatTimestamp = (timestamp) => new Date(timestamp).toLocaleTimeString()

  const prefillControls = (module) => {
    if (!module) return
    controlsPrefilledFor = module.module_id
    atoMode = deriveAtoMode(module)
    const configMotor = module.configPayload?.motor ?? {}
    const statusMotor = module.statusPayload?.motor ?? {}
    const configAto = module.configPayload?.ato ?? {}
    const statusAto = module.statusPayload?.ato ?? {}
    const configSystem = module.configPayload?.system ?? {}
    const statusSystem = module.statusPayload?.system ?? {}

    motorRunTimeMs = coalesceNumber(
      configMotor.run_time_ms,
      configMotor.runtime_ms,
      statusMotor.run_time_ms,
      statusMotor.runtime_ms
    ) ?? DEFAULT_RUNTIME

    rollerSpeed = coalesceNumber(configMotor.max_speed, statusMotor.speed) ?? DEFAULT_ROLLER_SPEED
    pumpTimeoutMs =
      coalesceNumber(
        configSystem.pump_timeout_ms,
        statusSystem.pump_timeout_ms,
        module.system?.pump_timeout_ms
      ) ?? DEFAULT_PUMP_TIMEOUT_MS

    alarmChirpIntervalMs =
      coalesceNumber(
        configSystem.alarm_chirp_interval_ms,
        statusSystem.alarm_chirp_interval_ms,
        module.system?.alarm_chirp_interval_ms
      ) ?? DEFAULT_ALARM_CHIRP_INTERVAL_MS

    spoolLengthMm =
      coalesceNumber(
        module.configPayload?.spool?.length_mm,
        module.configPayload?.spool?.total_length_mm,
        module.spool?.total_length_mm,
        module.spool?.length_mm
      ) ?? DEFAULT_SPOOL_LENGTH_MM

    mediaThicknessUm =
      coalesceNumber(
        module.configPayload?.spool?.media_thickness_um,
        module.spool?.media_thickness_um
      ) ?? DEFAULT_MEDIA_THICKNESS_UM

    coreDiameterMm =
      coalesceNumber(
        module.configPayload?.spool?.core_diameter_mm,
        module.spool?.core_diameter_mm
      ) ?? DEFAULT_CORE_DIAMETER_MM
  }

  $: moduleCards = modules.map(hydrateModule)
  $: if (!selectedModuleId && moduleCards.length) {
    selectedModuleId = moduleCards[0].module_id
  }
  $: if (selectedModuleId && selectedModuleId !== controlsPrefilledFor) {
    const target = moduleCards.find((module) => module.module_id === selectedModuleId)
    if (target) {
      prefillControls(target)
    }
  }
  $: selectedModule = moduleCards.find((module) => module.module_id === selectedModuleId)
  $: spoolState = selectedModule?.spool ?? {}
  $: spoolCalibrating = Boolean(spoolState?.calibrating)
  $: spoolSampleLengthMm = spoolState?.sample_length_mm ?? SPOOL_SAMPLE_MM
  $: spoolTotalLengthMm = coalesceNumber(spoolState?.total_length_mm, spoolLengthMm) ?? DEFAULT_SPOOL_LENGTH_MM
  $: spoolMediaThicknessUm =
    coalesceNumber(spoolState?.media_thickness_um, mediaThicknessUm) ?? DEFAULT_MEDIA_THICKNESS_UM
  $: spoolFullEdges = coalesceNumber(spoolState?.full_edges)
  $: spoolUsedEdges = coalesceNumber(spoolState?.used_edges)
  $: spoolRemainingEdges = coalesceNumber(spoolState?.remaining_edges)
  $: spoolMmPerEdge =
    typeof spoolFullEdges === 'number' && spoolFullEdges > 0
      ? spoolTotalLengthMm / spoolFullEdges
      : null
  $: spoolCoreDiameterMm =
    coalesceNumber(spoolState?.core_diameter_mm, coreDiameterMm) ?? DEFAULT_CORE_DIAMETER_MM
  $: calibrationStatusText = spoolCalibrating
    ? 'Ready to calibrate'
    : spoolCalibrationAwaitingAck
      ? 'Awaiting module confirmation'
      : 'Idle'
  $: calibrationInstruction = spoolCalibrating
    ? `Pull ${formatMeters(spoolSampleLengthMm)} of media, then tap Finish to store ${formatMillimeters(spoolLengthMm)}.`
    : spoolCalibrationAwaitingAck
      ? 'Waiting for the module to confirm calibration mode.'
      : 'Open the calibration flow to request confirmation from the module.'
  $: if (spoolCalibrating && spoolCalibrationAwaitingAck) {
    spoolCalibrationAwaitingAck = false
  }
  $: if (!selectedModuleId || (selectedModuleId !== controlsPrefilledFor && spoolCalibrationAwaitingAck)) {
    spoolCalibrationAwaitingAck = false
  }
  $: if (!spoolCalibrationAwaitingAck) {
    stopCalibrationAckPolling()
  }
  $: selectedModuleUsage = spoolUsageHistory.filter((entry) => entry.moduleId === selectedModuleId)
  $: moduleSpoolBaselineMs = (() => {
    void spoolResetVersion
    if (!selectedModuleId) return 0
    return getModuleResetBaseline(selectedModuleId)
  })()
  $: usageEntriesSinceBaseline = (() => {
    const baseline = moduleSpoolBaselineMs || 0
    return selectedModuleUsage.filter((entry) => entry.timestamp >= baseline)
  })()
  $: spoolLifetimeUsageMm = usageEntriesSinceBaseline.reduce((sum, entry) => sum + entry.deltaMm, 0)
  $: spoolLifetimeActivationCount = usageEntriesSinceBaseline.length
  $: spoolAverageActivationLengthMm = spoolLifetimeActivationCount
    ? spoolLifetimeUsageMm / spoolLifetimeActivationCount
    : 0
  $: spoolMetricSubcopy = describeSpoolMetricBaseline(moduleSpoolBaselineMs)
  $: usageChart = (() => {
    const now = Date.now()
    const baseline = moduleSpoolBaselineMs || 0
    const cutoff = Math.max(now - usageChartWindowMs, baseline)
    const entries = selectedModuleUsage
      .filter((entry) => entry.timestamp >= cutoff)
      .sort((a, b) => a.timestamp - b.timestamp)
    let cumulative = 0
    const normalized = entries.map((entry) => {
      cumulative += entry.deltaMm
      return {
        timestamp: entry.timestamp,
        ts: entry.timestamp,
        cumulativeMm: cumulative,
      }
    })
    const maxValue = Math.max(...normalized.map((point) => point.cumulativeMm), 0)
    const points = maxValue > 0 ? normalized : []
    return {
      points,
      totalMm: cumulative,
      windowStart: cutoff,
      maxValue,
    }
  })()
  $: usageActivationMarkers = (() => {
    if (!selectedModuleId) return []
    const now = Date.now()
    const baseline = moduleSpoolBaselineMs || 0
    const cutoff = Math.max(now - usageChartWindowMs, baseline)
    return (rollerRuns ?? [])
      .filter((run) => run.module_id === selectedModuleId)
      .map((run) => ({
        timestamp: run.recorded_at,
        ts: new Date(run.recorded_at).getTime(),
      }))
      .filter((run) => run.ts >= cutoff)
  })()
  $: usageYAxisMax = usageChart.maxValue ? usageChart.maxValue * 1.1 : undefined
  $: usageChartDatasets = usageChart.points.length
    ? [
        {
          label: 'Media used',
          data: usageChart.points.map((point) => ({ x: point.ts, y: point.cumulativeMm })),
          borderColor: 'rgba(72, 229, 194, 0.9)',
          backgroundColor: 'rgba(72, 229, 194, 0.15)',
          borderWidth: 2,
          fill: false,
          tension: 0.25,
          pointRadius: 3,
          pointHoverRadius: 4,
          pointBackgroundColor: '#f6c343',
          pointBorderColor: '#020710',
        },
        ...buildActivationDatasets(usageActivationMarkers, usageChart.maxValue || 0),
      ]
    : []
  $: rollerRuns = cycleHistory?.roller_runs ?? []
  $: atoRuns = cycleHistory?.ato_runs ?? []
  $: atoStats = cycleHistory?.ato_stats ?? {
    count: 0,
    frequency_per_hour: 0,
    avg_duration_ms: 0,
    avg_fill_seconds: 0,
  }
  $: activeCycleWindowHours = cycleHistory?.window_hours ?? cycleWindow
  $: atoChartPoints = buildChartPoints(atoRuns)
  $: atoDurationScaleMax = deriveDurationTargetMax(atoRuns)
  $: atoYAxisMax = atoDurationScaleMax || undefined
  $: atoChartDatasets = atoChartPoints.length
    ? [
        {
          label: 'ATO runtime',
          data: atoChartPoints.map((point) => ({ x: point.ts, y: point.duration })),
          borderColor: 'rgba(95, 179, 255, 0.8)',
          backgroundColor: 'rgba(95, 179, 255, 0.15)',
          borderWidth: 2,
          fill: false,
          tension: 0.35,
          pointRadius: 3,
          pointHoverRadius: 4,
          pointBackgroundColor: '#5fb3ff',
          pointBorderColor: '#020710',
        },
      ]
    : []
  $: alertEntries = moduleCards.flatMap(buildModuleAlerts)
  $: sortedAlerts = [...alertEntries].sort((a, b) => {
    const left = severityOrder[a.severity] ?? 99
    const right = severityOrder[b.severity] ?? 99
    if (left !== right) return left - right
    return (a.moduleLabel ?? '').localeCompare(b.moduleLabel ?? '')
  })
  $: displayedAlerts = sortedAlerts
  $: queueableAlerts = sortedAlerts.filter((entry) => entry.requiresAck)
  $: {
    const currentKeys = new Set(queueableAlerts.map((entry) => entry.key))
    const newAlarms = queueableAlerts.filter((entry) => !lastAlarmKeys.has(entry.key))
    if (newAlarms.length) {
      alarmQueue = [...alarmQueue, ...newAlarms]
      if (!activeAlarmModal) {
        presentNextAlarm()
      }
    }

    const retainedAcknowledged = new Set(
      [...acknowledgedAlarmKeys].filter((key) => currentKeys.has(key))
    )
    acknowledgedAlarmKeys = retainedAcknowledged
    lastAlarmKeys = new Set(currentKeys)
  }

  const openControls = (moduleId) => {
    selectedModuleId = moduleId
    const target = moduleCards.find((module) => module.module_id === moduleId)
    if (target) {
      prefillControls(target)
    }
    controlsVisible = true
  }

  const closeControls = () => {
    controlsVisible = false
    spoolResetConfirming = false
    calibrationModalOpen = false
    spoolCalibrationAwaitingAck = false
    stopCalibrationAckPolling()
    if (controlUpdateTimer) {
      clearTimeout(controlUpdateTimer)
      controlUpdateTimer = null
    }
    controlUpdatePending = false
  }

  const setUsageChartWindow = (hours) => {
    if (usageChartWindowHours === hours) return
    usageChartWindowHours = hours
  }

  const refreshCycleHistory = () => {
    loadCycleHistory(cycleWindow)
  }

  const submitControls = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }

    const payload = {}
    if (atoMode) payload.ato_mode = atoMode
    if (motorRunTimeMs) payload.motor_run_time_ms = Number(motorRunTimeMs)

    const hasValue = (value) => value !== null && value !== undefined && value !== ''
    if (hasValue(rollerSpeed)) payload.roller_speed = Number(rollerSpeed)
    if (hasValue(pumpTimeoutMs)) payload.pump_timeout_ms = Number(pumpTimeoutMs)
    if (hasValue(alarmChirpIntervalMs)) payload.alarm_chirp_interval_ms = Number(alarmChirpIntervalMs)

    if (Object.keys(payload).length === 0) {
      return
    }

    controlBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, payload)
      controlMessage = 'Settings sent to module.'
      await refresh()
    } catch (err) {
      controlError = err.message ?? 'Failed to update module.'
    } finally {
      controlBusy = false
      if (controlUpdatePending) {
        controlUpdatePending = false
        scheduleControlUpdate()
      }
    }
  }

  const startSpoolReset = () => {
    controlError = ''
    controlMessage = ''
    spoolResetConfirming = true
  }

  const cancelSpoolReset = () => {
    spoolResetConfirming = false
  }

  const confirmSpoolReset = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      spoolResetConfirming = false
      return
    }

    spoolResetBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, { reset_spool: true })
      controlMessage = 'Spool reset command sent.'
      await refresh()
    } catch (err) {
      controlError = err.message ?? 'Failed to reset spool.'
    } finally {
      spoolResetBusy = false
      spoolResetConfirming = false
    }
  }

  const openCalibrationModal = () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }
    controlError = ''
    controlMessage = ''
    calibrationModalOpen = true
  }

  const closeCalibrationModal = () => {
    calibrationModalOpen = false
    spoolCalibrationAwaitingAck = false
    stopCalibrationAckPolling()
  }

  const stopCalibrationAckPolling = () => {
    if (calibrationAckTimer) {
      clearInterval(calibrationAckTimer)
      calibrationAckTimer = null
    }
    calibrationAckPollInFlight = false
  }

  const startCalibrationAckPolling = () => {
    stopCalibrationAckPolling()
    calibrationAckTimer = setInterval(async () => {
      if (!spoolCalibrationAwaitingAck) {
        stopCalibrationAckPolling()
        return
      }
      if (calibrationAckPollInFlight) {
        return
      }
      calibrationAckPollInFlight = true
      try {
        await refresh()
      } catch (err) {
        console.warn('Calibration poll refresh failed', err)
      } finally {
        calibrationAckPollInFlight = false
      }
    }, 2000)
  }

  const validateRollLength = (value) => {
    if (Number.isNaN(value)) {
      return 'Enter a roll length before continuing.'
    }
    if (value < SPOOL_LENGTH_MIN_MM || value > SPOOL_LENGTH_MAX_MM) {
      return `Roll length must be between ${SPOOL_LENGTH_MIN_MM.toLocaleString()} mm and ${SPOOL_LENGTH_MAX_MM.toLocaleString()} mm.`
    }
    return ''
  }

  const validateMediaThickness = (value) => {
    if (Number.isNaN(value)) {
      return 'Enter a media thickness before continuing.'
    }
    if (value < MEDIA_THICKNESS_MIN_UM || value > MEDIA_THICKNESS_MAX_UM) {
      return `Media thickness must be between ${MEDIA_THICKNESS_MIN_UM} um and ${MEDIA_THICKNESS_MAX_UM} um.`
    }
    return ''
  }

  const validateCoreDiameter = (value) => {
    if (Number.isNaN(value)) {
      return 'Enter a core diameter before continuing.'
    }
    if (value < CORE_DIAMETER_MIN_MM || value > CORE_DIAMETER_MAX_MM) {
      return `Core diameter must be between ${CORE_DIAMETER_MIN_MM} mm and ${CORE_DIAMETER_MAX_MM} mm.`
    }
    return ''
  }

  const pushMediaProfileUpdate = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }

    const desiredLength = Number(spoolLengthMm)
    const validationError = validateRollLength(desiredLength)
    if (validationError) {
      controlError = validationError
      return
    }

    const desiredThickness = Number(mediaThicknessUm)
    const thicknessError = validateMediaThickness(desiredThickness)
    if (thicknessError) {
      controlError = thicknessError
      return
    }

    const desiredCoreDiameter = Number(coreDiameterMm)
    const coreError = validateCoreDiameter(desiredCoreDiameter)
    if (coreError) {
      controlError = coreError
      return
    }

    mediaProfileBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, {
        spool_length_mm: desiredLength,
        spool_media_thickness_um: desiredThickness,
        spool_core_diameter_mm: desiredCoreDiameter,
      })
      controlMessage = 'Media profile saved to module.'
      await refresh()
    } catch (err) {
      controlError = err.message ?? 'Failed to update media profile.'
    } finally {
      mediaProfileBusy = false
    }
  }

  const startSpoolCalibration = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }

    spoolCalibrationAwaitingAck = true
    spoolCalibrationBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, { spool_calibrate_start: true })
      controlMessage = 'Calibration request sent. Waiting for module confirmation.'
      await refresh()
      startCalibrationAckPolling()
    } catch (err) {
      controlError = err.message ?? 'Failed to start calibration.'
      spoolCalibrationAwaitingAck = false
    } finally {
      spoolCalibrationBusy = false
    }
  }

  const finishSpoolCalibration = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }

    const desiredLength = Number(spoolLengthMm)
    const validationError = validateRollLength(desiredLength)
    if (validationError) {
      controlError = validationError
      return
    }

    spoolCalibrationBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, { spool_calibrate_finish: desiredLength })
      controlMessage = 'Calibration complete. Spool usage reset.'
      await refresh()
      calibrationModalOpen = false
      spoolCalibrationAwaitingAck = false
      stopCalibrationAckPolling()
    } catch (err) {
      controlError = err.message ?? 'Failed to finish calibration.'
    } finally {
      spoolCalibrationBusy = false
    }
  }

  const cancelSpoolCalibration = async () => {
    if (!selectedModuleId) {
      controlError = 'Select a module first.'
      return
    }

    spoolCalibrationBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedModuleId, { spool_calibrate_cancel: true })
      controlMessage = 'Calibration canceled.'
      await refresh()
      calibrationModalOpen = false
    } catch (err) {
      controlError = err.message ?? 'Failed to cancel calibration.'
    } finally {
      spoolCalibrationBusy = false
      spoolCalibrationAwaitingAck = false
      stopCalibrationAckPolling()
    }
  }

  const scheduleControlUpdate = () => {
    if (!selectedModuleId) return
    if (controlBusy) {
      controlUpdatePending = true
      return
    }
    controlError = ''
    controlMessage = ''
    if (controlUpdateTimer) {
      clearTimeout(controlUpdateTimer)
    }
    controlUpdateTimer = setTimeout(() => {
      controlUpdateTimer = null
      submitControls()
    }, CONTROL_PUSH_DELAY_MS)
  }
</script>

<svelte:head>
  <title>Pickle Reef Console</title>
</svelte:head>

<main class="layout dashboard-view">
  <section class="hero">
    <div class="hero-copy">
      <h1 aria-label="Pickle Reef controller console">PICKLE REEF</h1>
      <div class="hero-status" aria-live="polite">
        <div class="status-chips">
          <span class="chip">{moduleCounts.online} modules online</span>
          <span class="chip muted">Updated {lastUpdated || '—'}</span>
        </div>
        <div class="status-alerts">
          {#if displayedAlerts.length === 0}
            <div class="alert-pill ok">
              <span class="badge badge-idle">OK</span>
              <div>
                <strong>Systems nominal</strong>
                <small>All modules reporting</small>
              </div>
            </div>
          {:else}
            <div class="alert-list">
              {#each displayedAlerts.slice(0, 3) as alert}
                <button
                  type="button"
                  class={`alert-pill ${alert.severity}`}
                  on:click={() => (selectedModuleId = alert.moduleId)}
                >
                  <span class={`badge ${getSeverityMeta(alert.severity).badge}`}>
                    {getSeverityMeta(alert.severity).label}
                  </span>
                  <div>
                    <strong>{alert.moduleLabel}</strong>
                    <small>{alert.description}</small>
                  </div>
                </button>
              {/each}
            </div>
            {#if displayedAlerts.length > 3}
              <span class="alert-more">+{displayedAlerts.length - 3} more alerts</span>
            {/if}
          {/if}
        </div>
      </div>
      <div class="hero-actions">
        <button type="button" class="ghost" on:click={openWsLogPanel}>
          WebSocket log
        </button>
      </div>
    </div>
    <div class="hero-logo">
      <img src="/picklereeflogo.png" alt="Pickle Reef logo" />
    </div>
    <div class="glow"></div>
  </section>

  <section class="grid metrics">
    {#each Object.keys(metricCopy) as metric}
      <article class="panel">
        <header>
          <p>{metricCopy[metric].label}</p>
          <span>{formatValue(metric)}</span>
        </header>
        <footer>
          <p>
            Avg {metricCopy[metric].label.toLowerCase()}:
            {summary.find((item) => item.metric === metric)?.avg_value?.toFixed(2) ?? '—'}
          </p>
        </footer>
      </article>
    {/each}
  </section>

  <section class="grid modules">
    <div class="panel module-panel" aria-label="Module overview">
      <header>
        <div>
          <p class="section-label">Modules</p>
          <h2>Connected hardware</h2>
        </div>
      </header>
      <ul>
        {#if moduleCards.length === 0}
          <li class="placeholder">No modules have reported yet.</li>
        {:else}
          {#each moduleCards as module}
            <li class="module-card">
              <div class="module-card__head">
                <div>
                  <p class="module-label">{module.label}</p>
                  <p class="module-meta">{module.module_id}</p>
                </div>
                <div class="module-meta ip-meta">
                  IP {module.ip_address ?? '—'} · RSSI {module.rssi ?? '—'} dBm
                </div>
                <div class="module-card__actions">
                  <span class="pill {statusPalette[module.status] ?? ''}">{formatState(module.status)}</span>
                  <button type="button" class="ghost small" on:click={() => openControls(module.module_id)}>
                    Controls
                  </button>
                </div>
              </div>
              <div class="module-card__insights">
                <div class="insight">
                  <p>Filter</p>
                  <strong>{formatState(module.motor.state)}</strong>
                  <small>{formatMotorDetails(module.motor)}</small>
                </div>
                <div class="insight">
                  <p>ATO</p>
                  <strong>
                    {#if module.ato.pump_running}
                      Pump running
                    {:else if module.ato.paused}
                      Paused
                    {:else}
                      Pump idle
                    {/if}
                  </strong>
                  <small>{describePump(module.ato)}</small>
                </div>
                <div class="insight">
                  <p>Floats</p>
                  <div class="float-pills">
                    {#each floatIndicators as indicator}
                      <span class:active={module.floats[indicator.key]}>{indicator.label}</span>
                    {/each}
                  </div>
                </div>
                <div class="insight spool-insight">
                  <p>Spool</p>
                  <strong class:alarm={module.spool.empty_alarm}>
                    {module.spool.empty_alarm ? 'Empty' : formatSpoolPercent(module.spool)}
                  </strong>
                  <small>{describeSpool(module.spool)}</small>
                  <div
                    class="spool-meter"
                    role="progressbar"
                    aria-label="Remaining filter media"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={normalizedSpoolPercent(module.spool) ?? 0}
                  >
                    <span
                      class:low={isSpoolLow(module.spool)}
                      class:empty={module.spool.empty_alarm}
                      style={`width: ${spoolMeterWidth(module.spool)}%;`}
                    ></span>
                  </div>
                </div>
                <div class="insight">
                  <p>Uptime</p>
                  <strong>{formatDuration(module.system.uptime_s)}</strong>
                  <small>Last seen {formatTimestamp(module.last_seen)}</small>
                </div>
              </div>
            </li>
          {/each}
        {/if}
      </ul>
    </div>

    <div class="panel timeline" aria-label="Last telemetry readings">
      <header>
        <p class="section-label">Recent reads</p>
        <h2>Signal timeline</h2>
      </header>

      <div class="cycle-window">
        <div class="window-label">
          <p>Cycle window</p>
          <button type="button" class="refresh" on:click={refreshCycleHistory} aria-label="Refresh cycle data">
            ↻
          </button>
        </div>
      </div>

      {#if cycleHistoryError}
        <div class="banner warning">{cycleHistoryError}</div>
      {/if}

      <div class="roller-chart usage-chart" aria-label="Estimated filter media usage">
        <div class="cycle-window usage-window">
          <div class="window-label">
            <p>Usage window</p>
          </div>
          <div class="window-buttons">
            {#each usageWindowPresets as preset}
              <button
                type="button"
                class:active={usageChartWindowHours === preset.hours}
                on:click={() => setUsageChartWindow(preset.hours)}
              >
                {preset.label}
              </button>
            {/each}
          </div>
        </div>
        {#if !selectedModuleId}
          <p class="placeholder">Select a module to track filter usage.</p>
        {:else if loading && usageChart.points.length === 0}
          <p class="placeholder">Loading filter usage…</p>
        {:else if usageChart.points.length === 0 && usageActivationMarkers.length === 0}
          <p class="placeholder">
            No filter movement detected in the last {formatUsageWindowShort(usageChartWindowHours)}.
          </p>
        {:else}
          <LineChart
            datasets={usageChartDatasets}
            ariaLabel="Filter usage chart"
            yTitle="Media used (mm)"
            xTitle="Time"
            yTickFormatter={formatSpoolMediaLength}
            xTickFormatter={formatCycleTimestamp}
            tooltipFormatter={usageTooltipFormatter}
            ySuggestedMax={usageYAxisMax}
            height={320}
            fontSize={16}
            fontWeight="600"
            tickColor="rgba(255, 255, 255, 0.95)"
            gridColor="rgba(255, 255, 255, 0.2)"
          />
          <div class="chart-meta usage-meta">
            <div>
              <p>Media used (spool)</p>
              <strong>{formatSpoolMediaLength(spoolLifetimeUsageMm)}</strong>
              <small>{spoolMetricSubcopy}</small>
            </div>
            <div>
              <p>Avg per activation</p>
              <strong>
                {spoolLifetimeActivationCount
                  ? formatSpoolMediaLength(spoolAverageActivationLengthMm)
                  : '—'}
              </strong>
              <small>{spoolMetricSubcopy}</small>
            </div>
            <div>
              <p>Activations (spool)</p>
              <strong>{spoolLifetimeActivationCount}</strong>
              <small>{spoolMetricSubcopy}</small>
            </div>
          </div>
        {/if}
      </div>

      <div class="roller-chart">
        {#if cycleHistoryLoading}
          <p class="placeholder">Loading ATO history…</p>
        {:else if !atoRuns.length}
          <p class="placeholder">No ATO activity in this window.</p>
        {:else}
          <LineChart
            datasets={atoChartDatasets}
            ariaLabel="ATO cycles chart"
            yTitle="Runtime"
            xTitle="Time"
            yTickFormatter={formatCycleDuration}
            xTickFormatter={formatCycleTimestamp}
            tooltipFormatter={atoTooltipFormatter}
            ySuggestedMax={atoYAxisMax}
            height={320}
            fontSize={16}
            fontWeight="600"
            tickColor="rgba(255, 255, 255, 0.95)"
            gridColor="rgba(255, 255, 255, 0.2)"
          />
          <div class="chart-meta">
            <div>
              <p>ATO cycles</p>
              <strong>{atoStats.count}</strong>
              <small>{atoStats.frequency_per_hour?.toFixed(2) ?? '0.00'} /hr</small>
            </div>
            <div>
              <p>Avg fill time</p>
              <strong>{formatCycleDuration((atoStats.avg_fill_seconds ?? 0) * 1000)}</strong>
              <small>Min → Max</small>
            </div>
            <div>
              <p>Avg runtime</p>
              <strong>{formatCycleDuration(atoStats.avg_duration_ms)}</strong>
              <small>Per pump cycle</small>
            </div>
          </div>
        {/if}
      </div>

      <div class="timeline-stats">
        <div>
          <p>ATO cycles</p>
          <strong>{atoStats.count}</strong>
          <small>{atoStats.frequency_per_hour?.toFixed(2) ?? '0.00'} /hr</small>
        </div>
        <div>
          <p>Avg fill time</p>
          <strong>{formatCycleDuration((atoStats.avg_fill_seconds ?? 0) * 1000)}</strong>
          <small>Min → Max</small>
        </div>
        <div>
          <p>Avg runtime</p>
          <strong>{formatCycleDuration(atoStats.avg_duration_ms)}</strong>
          <small>Per pump cycle</small>
        </div>
      </div>

      <div class="timeline-divider"></div>

      <ul>
        {#each telemetry.slice(0, 8) as row}
          <li>
            <div>
              <p class="module-label">{metricCopy[row.metric]?.label ?? row.metric}</p>
              <p class="module-meta">{row.module_id}</p>
            </div>
            <div class="value">{row.value.toFixed(2)} {row.unit}</div>
            <div class="timestamp">{formatTimestamp(row.captured_at)}</div>
          </li>
        {/each}
      </ul>
    </div>

  </section>
</main>

{#if wsLogPanelOpen}
  <div
    class="ws-log-modal-backdrop"
    on:click|self={closeWsLogPanel}
    on:keydown|self={(event) => event.key === 'Escape' && closeWsLogPanel()}
    role="dialog"
    aria-modal="true"
    tabindex="0"
  >
    <div class="ws-log-modal panel">
      <header>
        <div>
          <p class="section-label">Diagnostics</p>
          <h2>WebSocket Trace</h2>
        </div>
        <div class="log-actions">
          <button type="button" class="ghost" on:click={refreshWsLog} disabled={wsLogLoading}>
            {wsLogLoading ? 'Refreshing…' : 'Refresh now'}
          </button>
          <button type="button" class="ghost close" on:click={closeWsLogPanel} aria-label="Close WebSocket log">
            ×
          </button>
        </div>
      </header>
      {#if wsLogError}
        <div class="banner warning">{wsLogError}</div>
      {/if}
      <div class="ws-log-meta-row">
        <p>
          Showing {wsLogEntries.length} frame{wsLogEntries.length === 1 ? '' : 's'} · auto-refresh every
          {(WS_LOG_REFRESH_MS / 1000).toFixed(0)}s
        </p>
      </div>
      <div class="ws-log-list" role="log" aria-live="polite">
        {#if wsLogLoading && wsLogEntries.length === 0}
          <p class="placeholder">Loading WebSocket trace…</p>
        {:else if wsLogEntries.length === 0}
          <p class="placeholder">No WebSocket frames captured yet.</p>
        {:else}
          {#each wsLogEntries as entry, idx (entry.timestamp + entry.direction + idx)}
            <article class={`ws-log-entry ${entry.direction === 'rx' ? 'inbound' : 'outbound'}`}>
              <div class="ws-log-entry__meta">
                <span class={`pill ${entry.direction === 'rx' ? 'status-online' : 'status-discovering'}`}>
                  {entry.direction === 'rx' ? 'Inbound' : 'Outbound'}
                </span>
                {#if entry.module_id}
                  <span class="meta">{entry.module_id}</span>
                {/if}
                <span class="meta">{formatTimestamp(entry.timestamp)}</span>
              </div>
              <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
            </article>
          {/each}
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if controlsVisible}
  <div
    class="control-drawer-backdrop"
    on:click|self={closeControls}
    on:keydown|self={(event) => event.key === 'Escape' && closeControls()}
    role="dialog"
    aria-modal="true"
    tabindex="0"
  >
    <div class="control-drawer" role="dialog" aria-modal="true">
      <header>
        <div>
          <p class="section-label">Module Controls</p>
          <h2>{selectedModule?.label ?? 'Select a module'}</h2>
          <small>{selectedModuleId}</small>
        </div>
        <button type="button" class="ghost close" on:click={closeControls} aria-label="Close controls">
          ×
        </button>
      </header>
      <section class="control-form">
        <small class="control-hint">Changes sync automatically as you adjust settings.</small>

        <div class="form-group">
          <p class="form-label">ATO mode</p>
          <div class="radio-group" on:change={scheduleControlUpdate}>
            <label><input type="radio" name="ato-mode" value="auto" bind:group={atoMode} /> Auto</label>
            <label><input type="radio" name="ato-mode" value="manual" bind:group={atoMode} /> Manual</label>
            <label><input type="radio" name="ato-mode" value="paused" bind:group={atoMode} /> Pause</label>
          </div>
        </div>

        <div class="form-group">
          <label for="motor-runtime">Roller runtime ({(motorRunTimeMs / 1000).toFixed(1)}s)</label>
          <input
            id="motor-runtime"
            type="range"
            min="1000"
            max="30000"
            step="500"
            bind:value={motorRunTimeMs}
            on:change={scheduleControlUpdate}
          />
          <small>Adjusts how long the roller advances after a trigger.</small>
        </div>

        <div class="form-group">
          <label for="roller-speed">Roller speed ({rollerSpeed})</label>
          <input
            id="roller-speed"
            type="range"
            min="50"
            max="255"
            step="1"
            bind:value={rollerSpeed}
            on:change={scheduleControlUpdate}
          />
          <small>Sets the roller motor PWM ceiling (firmware clamps to 50–255).</small>
        </div>

        <div class="form-group">
          <label for="pump-timeout">Pump timeout ({(pumpTimeoutMs / 60000).toFixed(1)} min)</label>
          <input
            id="pump-timeout"
            type="range"
            min="60000"
            max="600000"
            step="5000"
            bind:value={pumpTimeoutMs}
            on:change={scheduleControlUpdate}
          />
          <small>How long the pump keeps running after a trigger to reach the high float target.</small>
        </div>

        <div class="form-group">
          <label for="alarm-interval">Alarm chirp interval ({formatChirpInterval(alarmChirpIntervalMs)})</label>
          <input
            id="alarm-interval"
            type="range"
            min="30000"
            max="600000"
            step="5000"
            bind:value={alarmChirpIntervalMs}
            on:change={scheduleControlUpdate}
          />
          <small>Sets how often the buzzer repeats reminders while any roller/pump alarm is active.</small>
        </div>

        <div class="form-group spool-length">
          <div class="form-label-row">
            <p class="form-label">Roll length</p>
            <span class="length-meta">Stored {formatMillimeters(spoolTotalLengthMm)}</span>
          </div>
          <div class="length-input">
            <input
              id="roll-length"
              type="number"
              min={SPOOL_LENGTH_MIN_MM}
              max={SPOOL_LENGTH_MAX_MM}
              step="500"
              bind:value={spoolLengthMm}
              placeholder="50000"
            />
            <span>mm</span>
          </div>
          <small>
            Used when finishing calibration or when you know the exact roll specification.
          </small>
          <div class="form-label-row">
            <p class="form-label">Core diameter</p>
            <span class="length-meta">Stored {formatMillimeters(spoolCoreDiameterMm)}</span>
          </div>
          <div class="length-input">
            <input
              id="core-diameter"
              type="number"
              min={CORE_DIAMETER_MIN_MM}
              max={CORE_DIAMETER_MAX_MM}
              step="0.5"
              bind:value={coreDiameterMm}
              placeholder="19"
            />
            <span>mm</span>
          </div>
          <small>
            Matches the mechanical hub or adapter your roll rides on (factory shaft is 19 mm).
          </small>
          <div class="form-label-row">
            <p class="form-label">Media thickness</p>
            <span class="length-meta">Stored {formatMicrons(spoolMediaThicknessUm)}</span>
          </div>
          <div class="length-input">
            <input
              id="media-thickness"
              type="number"
              min={MEDIA_THICKNESS_MIN_UM}
              max={MEDIA_THICKNESS_MAX_UM}
              step="1"
              bind:value={mediaThicknessUm}
              placeholder="100"
            />
            <span>um</span>
          </div>
          <small>
            Defaults to 100 um for ~80 gsm paper. Adjust if you swap to thicker or thinner media so usage estimates stay accurate.
          </small>
          <button
            type="button"
            class="primary"
            on:click={pushMediaProfileUpdate}
            disabled={!selectedModuleId || mediaProfileBusy}
          >
            {mediaProfileBusy ? 'Saving…' : 'Save media profile'}
          </button>
        </div>

        <div class="form-group spool-calibration">
          <div class="form-label-row">
            <p class="form-label">Automatic spool calibration</p>
            <span
              class={`calibration-pill ${spoolCalibrating ? 'active' : spoolCalibrationAwaitingAck ? 'pending' : ''}`}
            >
              {#if spoolCalibrating}
                Calibrating
              {:else if spoolCalibrationAwaitingAck}
                Waiting
              {:else}
                Idle
              {/if}
            </span>
          </div>
          <small class="calibration-hint">
            {#if spoolCalibrating}
              Module ready. Pull {formatMeters(spoolSampleLengthMm)} of media, then finish to store
              {formatMillimeters(spoolLengthMm)}.
            {:else if spoolCalibrationAwaitingAck}
              Waiting for the module to confirm calibration mode.
            {:else}
              Launch the guided calibration flow to start, finish, or abort the 10 m sample pull.
            {/if}
          </small>
          <button
            type="button"
            class="primary"
            on:click={openCalibrationModal}
            disabled={!selectedModuleId || spoolCalibrationBusy}
          >
            Open calibration flow
          </button>
        </div>

        <div class="form-group spool-reset">
          <p class="form-label">Filter roll reset</p>
          <small>Zero the spool usage meter after installing a new roll.</small>
          {#if spoolResetConfirming}
            <div class="reset-actions">
              <p>This cannot be undone. Reset spool telemetry to 100%?</p>
              <div class="button-row">
                <button type="button" class="ghost" on:click={cancelSpoolReset} disabled={spoolResetBusy}>
                  Cancel
                </button>
                <button
                  type="button"
                  class="danger"
                  on:click={confirmSpoolReset}
                  disabled={spoolResetBusy || !selectedModuleId}
                >
                  {spoolResetBusy ? 'Resetting…' : 'Confirm reset'}
                </button>
              </div>
            </div>
          {:else}
            <button
              type="button"
              class="danger"
              on:click={startSpoolReset}
              disabled={!selectedModuleId || controlBusy}
            >
              Reset spool meter
            </button>
          {/if}
        </div>

        {#if calibrationModalOpen}
          <div
            class="calibration-modal-backdrop"
            on:click|self={closeCalibrationModal}
            on:keydown|self={(event) => event.key === 'Escape' && closeCalibrationModal()}
            role="dialog"
            aria-modal="true"
            tabindex="0"
          >
            <div class="calibration-modal" role="dialog" aria-modal="true">
              <header>
                <div>
                  <p class="section-label">Spool Calibration</p>
                  <h3>Guided 10 m pull</h3>
                </div>
                <button type="button" class="ghost close" on:click={closeCalibrationModal}>
                  ×
                </button>
              </header>
              <div class="calibration-status-block">
                <span
                  class={`calibration-pill ${spoolCalibrating ? 'active' : spoolCalibrationAwaitingAck ? 'pending' : ''}`}
                >
                  {calibrationStatusText}
                </span>
                <p class="calibration-instruction">{calibrationInstruction}</p>
                <div class="calibration-meta">
                  <span>Sample: {formatMillimeters(spoolSampleLengthMm)}</span>
                  <span>Roll length: {formatMillimeters(spoolLengthMm)}</span>
                  <span>Media thickness: {formatMicrons(spoolMediaThicknessUm)}</span>
                  {#if spoolCoreDiameterMm}
                    <span>Core diameter: {formatMillimeters(spoolCoreDiameterMm)}</span>
                  {/if}
                  {#if spoolFullEdges}
                    <span>Full-roll edges: {formatEdgeCount(spoolFullEdges)}</span>
                  {/if}
                  {#if spoolMmPerEdge}
                    <span>Resolution: {formatMmPerEdge(spoolMmPerEdge)}</span>
                  {/if}
                  {#if spoolUsedEdges != null}
                    <span>Edges used: {formatEdgeCount(spoolUsedEdges)}</span>
                  {/if}
                  {#if spoolRemainingEdges != null}
                    <span>Edges remaining: {formatEdgeCount(spoolRemainingEdges)}</span>
                  {/if}
                </div>
              </div>
              <div class="button-row calibration-actions">
                <button
                  type="button"
                  class="primary"
                  on:click={startSpoolCalibration}
                  disabled={
                    !selectedModuleId || spoolCalibrationBusy || spoolCalibrating || spoolCalibrationAwaitingAck
                  }
                >
                  {spoolCalibrationBusy && !spoolCalibrating ? 'Working…' : 'Request start'}
                </button>
                <button
                  type="button"
                  class="success"
                  on:click={finishSpoolCalibration}
                  disabled={!selectedModuleId || spoolCalibrationBusy || !spoolCalibrating}
                >
                  {spoolCalibrationBusy && spoolCalibrating ? 'Working…' : 'Finish & save'}
                </button>
                <button
                  type="button"
                  class="danger"
                  on:click={cancelSpoolCalibration}
                  disabled={
                    !selectedModuleId || spoolCalibrationBusy || (!spoolCalibrating && !spoolCalibrationAwaitingAck)
                  }
                >
                  Cancel calibration
                </button>
              </div>
              <small class="calibration-note">
                Adjust the target roll length above before finishing if the replacement roll differs.
              </small>
              {#if controlError}
                <div class="banner warning within-modal">{controlError}</div>
              {/if}
              {#if controlMessage}
                <div class="banner info within-modal">{controlMessage}</div>
              {/if}
            </div>
          </div>
        {/if}

        {#if controlError && !calibrationModalOpen}
          <div class="banner warning">{controlError}</div>
        {/if}
        {#if controlMessage && !calibrationModalOpen}
          <div class="banner info">{controlMessage}</div>
        {/if}
      </section>
    </div>
  </div>
{/if}

{#if activeAlarmModal}
  <div class="alarm-modal-backdrop" role="dialog" aria-modal="true">
    <div class="alarm-modal">
      <p class={`modal-severity ${activeAlarmModal.severity}`}>
        {getSeverityMeta(activeAlarmModal.severity).label}
      </p>
      <h3>{activeAlarmModal.description}</h3>
      <p class="modal-module">{activeAlarmModal.moduleLabel}</p>
      <p class="modal-meta">Detected {formatAlertTimestamp(activeAlarmModal.timestamp)}</p>

      {#if activeAlarmModal.meta && Object.keys(activeAlarmModal.meta).length}
        <div class="alarm-meta">
          {#each Object.entries(activeAlarmModal.meta) as [key, value]}
            <div>
              <p class="meta-label">{key.replace(/_/g, ' ')}</p>
              <p class="meta-value">{value}</p>
            </div>
          {/each}
        </div>
      {/if}
      <div class="modal-actions">
        <button type="button" class="ghost" on:click={focusAlarmModule}>
          Inspect module
        </button>
        <button type="button" class="primary" on:click={acknowledgeAlarm}>
          Acknowledge alarm
        </button>
      </div>
    </div>
  </div>
{/if}

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
    deleteModule,
  } from './lib/api'
  import LineChart from './lib/LineChart.svelte'
  import ChartWidget from './lib/ChartWidget.svelte'

  const DEFAULT_RUNTIME = 5000
  const DEFAULT_ROLLER_SPEED = 180
  const DEFAULT_PUMP_TIMEOUT_MS = 120000
  const DEFAULT_ALARM_CHIRP_INTERVAL_MS = 120000
  const DEFAULT_SPOOL_LENGTH_MM = 50000
  const DEFAULT_CORE_DIAMETER_MM = 19
  const DEFAULT_MEDIA_THICKNESS_UM = 100
  const DEFAULT_TANK_CAPACITY_ML = 15000
  const FLOW_ML_PER_MS = 0.0375
  const SPOOL_LENGTH_MIN_MM = 10000
  const SPOOL_LENGTH_MAX_MM = 200000
  const SPOOL_SAMPLE_MM = 10000
  const MEDIA_THICKNESS_MIN_UM = 40
  const MEDIA_THICKNESS_MAX_UM = 400
  const CORE_DIAMETER_MIN_MM = 12
  const CORE_DIAMETER_MAX_MM = 80
  const TANK_RESET_THRESHOLD_ML = 1000

  let telemetry = []
  let summary = []
  let modules = []
  let loading = true
  let error = ''
  let lastUpdated = ''
  let selectedModuleId = ''
  let atoMode = 'auto'
  let motorRunTimeMs = DEFAULT_RUNTIME
  let rollerSpeed = DEFAULT_ROLLER_SPEED
  let pumpTimeoutMs = DEFAULT_PUMP_TIMEOUT_MS
  let alarmChirpIntervalMs = DEFAULT_ALARM_CHIRP_INTERVAL_MS
  let controlMessage = ''
  let controlError = ''
  let controlBusy = false
  let controlsPrefilledFor = ''
  let spoolResetConfirming = false
  let spoolResetBusy = false
  let calibrationModalOpen = false
  let spoolCalibrationAwaitingAck = false
  let controlsVisible = false
  let purgeConfirming = false
  let purgeBusy = false
  let tankRefillConfirming = false
  let tankRefillBusy = false
  let calibrationAckTimer = null
  let calibrationAckPollInFlight = false
  let cycleHistoryRefreshTimer = null
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
  let activeThermistorAlarmDetails = null
  let atoStats = {
    count: 0,
    frequency_per_hour: 0,
    avg_duration_ms: 0,
    avg_fill_seconds: 0,
    total_volume_ml: 0,
    avg_volume_ml: 0,
  }
  let spoolLengthMm = DEFAULT_SPOOL_LENGTH_MM
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
  let tankUsageHistory = new Map()
  let heaterTelemetryHistory = new Map()
  let temperatureSeries = { datasets: [], yMin: undefined, yMax: undefined }
  let temperatureChartDatasets = []
  let temperatureYAxisMin = undefined
  let temperatureYAxisMax = undefined
  let temperatureChartMeta = null
  let temperatureSetpointC = 25
  let heaterSetpointMinC = 24
  let heaterSetpointMaxC = 26
  let latestTemperatureSample = null
  let selectedHeaterSamples = []
  let heaterSamplesInWindow = []
  let isHeaterView = false
  let primaryHeaterSamples = []
  let primaryHeaterSample = null
  let heroCurrentTempC = null
  let heroAverage3dTempC = null

  const WS_LOG_REFRESH_MS = 3000
  const HOUR_IN_MS = 60 * 60 * 1000
  const USAGE_HISTORY_WINDOW_MS = 30 * 24 * HOUR_IN_MS
  const USAGE_HISTORY_WINDOW_HOURS = USAGE_HISTORY_WINDOW_MS / HOUR_IN_MS
  const TANK_USAGE_HISTORY_MS = 30 * 24 * HOUR_IN_MS
  const HEATER_HISTORY_WINDOW_MS = 72 * HOUR_IN_MS
  const HEATER_SETPOINT_MIN_BOUND_C = 10
  const HEATER_SETPOINT_MAX_BOUND_C = 35
  const HERO_AVERAGE_WINDOW_MS = 72 * HOUR_IN_MS
  const TANK_RESET_STORAGE_KEY = 'pickle-reef::tank-reset-epoch'
  const SPOOL_USAGE_STORAGE_KEY = 'pickle-reef::spool-usage-history'
  const SPOOL_RESET_STORAGE_KEY = 'pickle-reef::spool-reset-epoch'
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
  const cycleWindowPresets = usageWindowPresets
  const toWindowButtons = (presets = []) =>
    presets.map((preset) => ({ value: preset.hours, label: preset.label, description: preset.description }))
  const usageWindowButtons = toWindowButtons(usageWindowPresets)
  const cycleWindowButtons = toWindowButtons(cycleWindowPresets)
  const temperatureWindowPresets = [
    { hours: 1, label: '1h', description: 'Last 60 minutes of heater telemetry' },
    { hours: 3, label: '3h', description: 'Rolling last 3 hours' },
    { hours: 6, label: '6h', description: 'Rolling last 6 hours' },
    { hours: 12, label: '12h', description: 'Rolling last 12 hours' },
    { hours: 24, label: '1d', description: 'Full day of heater activity' },
    { hours: 72, label: '3d', description: 'Multi-day heater drift' },
  ]
  const temperatureWindowButtons = toWindowButtons(temperatureWindowPresets)
  const MAX_CYCLE_WINDOW_HOURS = usageWindowPresets.at(-1)?.hours ?? 365 * 24
  const defaultUsagePreset = usageWindowPresets.find((preset) => preset.hours === 24) ?? usageWindowPresets[0]
  const defaultTemperaturePreset = temperatureWindowPresets.find((preset) => preset.hours === 6) ??
    temperatureWindowPresets[0]
  let usageChartWindowHours = defaultUsagePreset?.hours ?? 24
  let usageChartWindowMs = usageChartWindowHours * HOUR_IN_MS
  let temperatureChartWindowHours = defaultTemperaturePreset?.hours ?? 6
  let temperatureChartWindowMs = temperatureChartWindowHours * HOUR_IN_MS
  const SPOOL_RESET_EDGE_THRESHOLD = 10
  const spoolSnapshots = new Map()
  const spoolResetTimestamps = new Map()
  let spoolResetVersion = 0
  const tankResetTimestamps = new Map()

  const hiddenModuleIds = new Set(['spoolticktester', 'alarmtester'])
  const hiddenModuleIdsLower = new Set([...hiddenModuleIds].map((id) => id.toLowerCase()))
  const DEFAULT_OFFICIAL_MODULE_IDS = []
    const PRIMARY_HEATER_MODULE_ID = 'pickleheat'

  const parseModuleIdList = (raw) => {
    if (typeof raw !== 'string') return []
    return raw
      .split(',')
      .map((id) => id.trim())
      .filter(Boolean)
  }

  const normalizeModuleId = (value) => (typeof value === 'string' ? value.trim().toLowerCase() : '')

  const resolveOfficialModuleIds = () => {
    const envValue = import.meta.env?.VITE_OFFICIAL_MODULE_IDS
    if (typeof envValue === 'string') {
      const parsed = parseModuleIdList(envValue)
      if (parsed.length === 1 && parsed[0] === '*') {
        return []
      }
      if (parsed.length) {
        return parsed
      }
      return []
    }
    return DEFAULT_OFFICIAL_MODULE_IDS
  }

  const officialModuleIdsLower = new Set(resolveOfficialModuleIds().map((id) => id.toLowerCase()))
  const shouldDisplayModule = (module) => {
    const id = (module?.module_id ?? module?.moduleId ?? '').toString().trim()
    if (!id) return false
    const normalized = id.toLowerCase()
    if (hiddenModuleIdsLower.has(normalized)) return false
    if (officialModuleIdsLower.size && !officialModuleIdsLower.has(normalized)) return false
    return true
  }

  const filterDisplayableModules = (list = []) => (list ?? []).filter((module) => shouldDisplayModule(module))
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
        system: { chirp_enabled: true, uptime_s: 18200, pump_timeout_ms: 120000 },
        spool: {
          full_edges: 528000,
          used_edges: 68000,
          remaining_edges: 460000,
          percent_remaining: 87,
          empty_alarm: false,
          total_length_mm: 50000,
          sample_length_mm: 10000,
          calibrating: false,
          activations: 128,
        },
      },
      alarms: [
        {
          code: 'pump_timeout',
          severity: 'warning',
          active: true,
          message: 'ATO pump exceeded pump_timeout_ms',
          timestamp_s: 18000,
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
        system: { chirp_enabled: false, uptime_s: 2600, pump_timeout_ms: 180000 },
        spool: {
          full_edges: 528000,
          used_edges: 500000,
          remaining_edges: 28000,
          percent_remaining: 5,
          empty_alarm: false,
          total_length_mm: 50000,
          sample_length_mm: 10000,
          calibrating: false,
          activations: 420,
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

  const SUBSYSTEM_TEMPLATES = {
    roller: { suffix: 'Roller', badge: 'Filter' },
    ato: { suffix: 'ATO', badge: 'ATO' },
  }

  const FALLBACK_SUBSYSTEMS = Object.entries(SUBSYSTEM_TEMPLATES).map(([kind, meta]) => ({
    key: kind,
    kind,
    card_suffix: meta.suffix,
    badge_label: meta.badge,
  }))

  const normalizeSubsystemKind = (value) => {
    if (typeof value !== 'string') return ''
    return value.split(':')[0].toLowerCase()
  }

  const resolveModuleSubsystems = (module) => {
    if (Array.isArray(module?.subsystems) && module.subsystems.length) {
      return module.subsystems
        .map((entry) => (typeof entry === 'string' ? { key: entry } : entry))
        .filter((entry) => entry && typeof entry === 'object')
    }
    return FALLBACK_SUBSYSTEMS
  }

  const buildSubsystemMeta = (baseLabel, definition = {}, index = 0) => {
    const kind = normalizeSubsystemKind(definition.kind ?? definition.key ?? 'roller') || 'roller'
    const template = SUBSYSTEM_TEMPLATES[kind] ?? {}
    const cardSuffix = definition.card_suffix ?? definition.suffix ?? template.suffix ?? ''
    const label = definition.label ?? (cardSuffix ? `${baseLabel} ${cardSuffix}` : baseLabel)
    const badgeLabel = definition.badge_label ?? definition.badge ?? template.badge ?? (cardSuffix || 'Subsystem')
    const key = definition.key ?? `${kind}-${index}`
    return {
      kind,
      label,
      badgeLabel,
      cardSuffix,
      key,
      badgeVariant: definition.badge_variant ?? template.badgeVariant ?? '',
    }
  }

  const createSubsystemCards = (module) => {
    if (!module?.module_id) return []
    const baseLabel = module.label ?? module.module_id
    const definitions = resolveModuleSubsystems(module)
    return definitions.map((definition, index) => {
      const meta = buildSubsystemMeta(baseLabel, definition, index)
      const cardId = definition.card_id ?? `${module.module_id}::${meta.key}`
      return {
        ...module,
        label: meta.label,
        badge_label: meta.badgeLabel,
        badge_variant: meta.badgeVariant,
        subsystem: meta.kind,
        card_id: cardId,
        module_type: module.module_type ?? module.moduleType ?? null,
        subsystem_meta: { ...definition, card_suffix: meta.cardSuffix, kind: meta.kind, key: meta.key },
      }
    })
  }

  const getCardModuleId = (card) => card?.module_id ?? card?.moduleId ?? ''
  const getCardSubsystem = (card) => normalizeSubsystemKind(card?.subsystem ?? card?.subsystem_meta?.kind ?? '')
  const isRollerSubsystem = (subsystem) => normalizeSubsystemKind(subsystem) === 'roller'
  const isHeaterSubsystem = (subsystem) => normalizeSubsystemKind(subsystem) === 'heater'
  const isHeaterCard = (card = {}) => {
    if (!card) return false
    if (isHeaterSubsystem(card.subsystem)) return true
    const moduleType = typeof card.module_type === 'string' ? card.module_type.trim().toLowerCase() : ''
    return moduleType === 'heater'
  }

  const guessSubsystemFromAlert = (alert = {}) => {
    const haystack = `${alert.code ?? ''} ${alert.description ?? ''} ${alert.message ?? ''}`.toLowerCase()
    if (haystack.includes('ato') || haystack.includes('pump') || haystack.includes('reservoir') || haystack.includes('tank')) {
      return 'ato'
    }
    return 'roller'
  }

  const focusModuleCard = (moduleId, subsystem) => {
    if (!moduleId) return
    const desiredSubsystem = normalizeSubsystemKind(subsystem)
    const pool = typeof moduleCards === 'undefined' ? [] : moduleCards
    const match =
      pool.find((card) => {
        if (getCardModuleId(card) !== moduleId) return false
        if (desiredSubsystem && getCardSubsystem(card) !== desiredSubsystem) return false
        return true
      }) ?? pool.find((card) => getCardModuleId(card) === moduleId)
    if (match) {
      selectedModuleId = match.card_id ?? match.module_id
    }
  }

  function hydrateStoredTankResetTimestamps() {
    const storage = resolveStorage()
    if (!storage) return new Map()
    try {
      const raw = storage.getItem(TANK_RESET_STORAGE_KEY)
      if (!raw) return new Map()
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object') return new Map()
      const entries = Object.entries(parsed).filter(([moduleId, timestamp]) => {
        return typeof moduleId === 'string' && typeof timestamp === 'number' && timestamp > 0
      })
      return new Map(entries)
    } catch (err) {
      console.warn('Unable to hydrate tank reset timestamps', err)
      return new Map()
    }
  }

  function persistTankResetTimestamps() {
    const storage = resolveStorage()
    if (!storage) return
    try {
      const cutoff = Date.now() - TANK_USAGE_HISTORY_MS
      const payload = {}
      tankResetTimestamps.forEach((timestamp, moduleId) => {
        if (typeof timestamp === 'number' && timestamp > cutoff) {
          payload[moduleId] = timestamp
        }
      })
      storage.setItem(TANK_RESET_STORAGE_KEY, JSON.stringify(payload))
    } catch (err) {
      console.warn('Unable to persist tank reset timestamps', err)
    }
  }

  function markTankReset(moduleId, timestamp = Date.now()) {
    if (!moduleId) return
    tankResetTimestamps.set(moduleId, timestamp)
    persistTankResetTimestamps()
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

  const convertToCelsius = (value, unit = '°C') => {
    if (typeof value !== 'number' || Number.isNaN(value)) return null
    const normalized = typeof unit === 'string' ? unit.toLowerCase() : ''
    if (normalized.includes('f')) {
      return ((value - 32) * 5) / 9
    }
    return value
  }

  const buildThermometerKey = (label, index) => {
    if (typeof label === 'string' && label.trim().length) {
      const cleaned = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
      return cleaned || `thermometer-${index + 1}`
    }
    return `thermometer-${index + 1}`
  }

  const extractNormalizedThermometers = (module) => {
    const readings = getHeaterThermometers(module)
    if (!readings?.length) return []
    return readings
      .map((reading, index) => {
        const valueC = convertToCelsius(reading.value, reading.unit)
        if (valueC == null) return null
        const label = reading.label ?? `Thermometer ${index + 1}`
        return {
          key: buildThermometerKey(label, index),
          label,
          value: valueC,
        }
      })
      .filter((entry) => entry)
  }

  const recordHeaterTelemetrySnapshot = (moduleList = []) => {
    if (!Array.isArray(moduleList) || moduleList.length === 0) return
    const now = Date.now()
    const cutoff = now - HEATER_HISTORY_WINDOW_MS
    const nextHistory = new Map(heaterTelemetryHistory)
    moduleList.forEach((module) => {
      const moduleId = module?.module_id
      if (!moduleId) return
      const thermometers = extractNormalizedThermometers(module)
      if (!thermometers.length) return
      const heaterState = describeHeaterPowerState(module)
      const sample = {
        timestamp: now,
        thermometers,
        heaterState: heaterState?.active ?? false,
        heaterDescription: heaterState?.description ?? '',
      }
      const samples = nextHistory.get(moduleId) ?? []
      samples.push(sample)
      const filtered = samples.filter((entry) => entry.timestamp >= cutoff)
      nextHistory.set(moduleId, filtered)
    })
    heaterTelemetryHistory = nextHistory
  }

  const THERMOMETER_COLORS = [
    { border: 'rgba(255, 145, 123, 0.9)', background: 'rgba(255, 145, 123, 0.18)' },
    { border: 'rgba(125, 196, 255, 0.9)', background: 'rgba(125, 196, 255, 0.2)' },
    { border: 'rgba(160, 236, 174, 0.9)', background: 'rgba(160, 236, 174, 0.18)' },
  ]

  const buildTemperatureSeries = (samples = [], setpointTarget = null, setpointMin = null, setpointMax = null) => {
    if (!samples.length) {
      return { datasets: [], yMin: undefined, yMax: undefined }
    }

    const seriesMap = new Map()
    const values = []
    const toFiniteNumber = (value) => {
      if (value == null) return null
      const numeric = typeof value === 'number' ? value : Number(value)
      return Number.isFinite(numeric) ? numeric : null
    }
    const finiteSetpoint = toFiniteNumber(setpointTarget)
    const finiteSetpointMin = toFiniteNumber(setpointMin)
    const finiteSetpointMax = toFiniteNumber(setpointMax)

    samples.forEach((sample) => {
      sample.thermometers.forEach((reading, index) => {
        if (typeof reading.value !== 'number' || Number.isNaN(reading.value)) return
        values.push(reading.value)
        const existing = seriesMap.get(reading.key)
        const bucket =
          existing ?? {
            label: reading.label ?? `Thermometer ${index + 1}`,
            points: [],
          }
        bucket.points.push({ x: sample.timestamp, y: reading.value })
        seriesMap.set(reading.key, bucket)
      })
    })

    if (finiteSetpoint != null) {
      values.push(finiteSetpoint)
    }
    if (finiteSetpointMin != null) {
      values.push(finiteSetpointMin)
    }
    if (finiteSetpointMax != null) {
      values.push(finiteSetpointMax)
    }

      if (!values.length) {
        return { datasets: [], yMin: undefined, yMax: undefined }
      }

      const minValue = Math.min(...values)
      const maxValue = Math.max(...values)
      const padding = Math.max(0.5, (maxValue - minValue) * 0.15 || 0.8)
      const yMin = minValue - padding
      const yMax = maxValue + padding

      const datasets = Array.from(seriesMap.values()).map((entry, index) => {
        const palette = THERMOMETER_COLORS[index % THERMOMETER_COLORS.length]
        return {
          label: entry.label,
          data: entry.points,
          borderColor: palette.border,
          backgroundColor: palette.background,
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 4,
          spanGaps: true,
        }
      })

      const heaterHigh = yMax - padding * 0.2
      const heaterLow = yMin + padding * 0.2
      const heaterSeries = samples.map((sample) => ({
        x: sample.timestamp,
        y: sample.heaterState ? heaterHigh : heaterLow,
        heaterOn: sample.heaterState,
      }))
      if (heaterSeries.length) {
        datasets.push({
          label: 'Heater state',
          data: heaterSeries,
          borderColor: 'rgba(246, 195, 67, 0.95)',
          backgroundColor: 'rgba(246, 195, 67, 0.15)',
          borderWidth: 2,
          fill: false,
          stepped: true,
          pointRadius: 0,
          spanGaps: false,
          tension: 0,
        })
      }

      const pushSetpointDataset = (label, value, options = {}) => {
        if (value == null) return
        datasets.push({
          label,
          data: samples.map((sample) => ({
            x: sample.timestamp,
            y: value,
          })),
          borderColor: options.borderColor ?? 'rgba(255, 255, 255, 0.65)',
          borderWidth: options.borderWidth ?? 2,
          borderDash: options.borderDash ?? [6, 4],
          fill: options.fill ?? false,
          pointRadius: 0,
          pointHoverRadius: 0,
          tension: 0,
        })
      }

      pushSetpointDataset('Setpoint', finiteSetpoint, {
        borderColor: 'rgba(255, 255, 255, 0.75)',
        borderDash: [6, 4],
      })
      pushSetpointDataset('Setpoint min', finiteSetpointMin, {
        borderColor: 'rgba(250, 153, 114, 0.85)',
        borderDash: [4, 6],
      })
      pushSetpointDataset('Setpoint max', finiteSetpointMax, {
        borderColor: 'rgba(119, 215, 255, 0.85)',
        borderDash: [8, 4],
      })

      return { datasets, yMin, yMax }
    }

    const buildTemperatureMeta = (sample, module) => {
      if (!sample) return null
      const readings = sample.thermometers?.map((reading) => ({
        label: reading.label,
        value: reading.value,
      }))
      const heaterState = describeHeaterPowerState(module ?? {})
      return {
        timestamp: sample.timestamp,
        readings: readings ?? [],
        heaterOn: heaterState?.active ?? sample.heaterState ?? false,
        description: heaterState?.description ?? sample.heaterDescription ?? '',
      }
    }

    const computeSampleAverageC = (sample) => {
      if (!sample?.thermometers?.length) return null
      const values = sample.thermometers
        .map((reading) => (typeof reading.value === 'number' ? reading.value : Number(reading.value)))
        .filter((value) => Number.isFinite(value))
      if (!values.length) return null
      const sum = values.reduce((total, value) => total + value, 0)
      return sum / values.length
    }
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

  const runtimeMsToMilliliters = (durationMs = 0) => {
    const numeric = typeof durationMs === 'number' ? durationMs : Number(durationMs)
    if (!Number.isFinite(numeric) || numeric <= 0) return 0
    return numeric * FLOW_ML_PER_MS
  }

  const isAtoResetEvent = (run = {}) => {
    const type = (run.cycle_type ?? '').toString().toLowerCase()
    const trigger = (run.trigger ?? '').toString().toLowerCase()
    return type.includes('reset') || trigger.includes('refill') || trigger.includes('reset')
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
  const formatBaselineTimestamp = (timestamp) => {
    if (!timestamp) return '—'
    const date = new Date(timestamp)
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
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

  const buildActivationDatasets = (markers, maxValue, options = {}) => {
    if (!markers?.length || !maxValue) return []
    const data = []
    markers.forEach((marker) => {
      data.push({ x: marker.ts, y: 0 })
      data.push({ x: marker.ts, y: maxValue })
      data.push({ x: null, y: null })
    })
    return [
      {
        label: options.label ?? 'Roller activations',
        data,
        borderColor: options.borderColor ?? 'rgba(248, 251, 255, 0.4)',
        borderWidth: options.borderWidth ?? 1,
        borderDash: options.borderDash ?? [4, 4],
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
    return `${formatMilliliters(value)} • ${formatCycleTimestamp(timeValue)}`
  }

  const temperatureTooltipFormatter = (context) => {
    const raw = context.raw ?? {}
    const datasetLabel = context.dataset?.label ?? 'Temperature'
    const timeValue = raw.x ?? context.parsed?.x
    if (datasetLabel === 'Heater state') {
      const heaterOn = raw.heaterOn ?? (typeof context.parsed?.y === 'number' ? context.parsed.y > 0 : false)
      if (timeValue === undefined) return ''
      return `${datasetLabel}: ${heaterOn ? 'On' : 'Off'} • ${formatCycleTimestamp(timeValue)}`
    }
    const value = typeof raw.y === 'number' ? raw.y : context.parsed?.y
    if (value === undefined || timeValue === undefined) return ''
    return `${datasetLabel}: ${formatCelsiusValue(value)} • ${formatCycleTimestamp(timeValue)}`
  }

  const buildAtoVolumePoints = (runs) => {
    if (!runs?.length) return []
    const sortedRuns = [...runs].sort(
      (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
    )
    let cumulative = 0
    return sortedRuns.map((run) => {
      const ts = new Date(run.recorded_at).getTime()
      const duration = Math.max(0, run.duration_ms ?? 0)
      const volume = runtimeMsToMilliliters(duration)
      const resetEvent = isAtoResetEvent(run)
      if (resetEvent) {
        cumulative = 0
      }
      cumulative += volume
      return {
        ts,
        duration,
        volume,
        cumulative,
        timestamp: run.recorded_at,
        reset: resetEvent,
      }
    })
  }

  const findRecentTankResetTimestamp = (samples = []) => {
    if (!samples?.length) return null
    let previous = null
    for (let idx = samples.length - 1; idx >= 0; idx -= 1) {
      const sample = samples[idx]
      if (!sample) continue
      const used = sample.usedMl
      if (typeof used !== 'number') continue
      if (used <= TANK_RESET_THRESHOLD_ML) {
        return sample.timestamp
      }
      if (previous != null && used + TANK_RESET_THRESHOLD_ML < previous) {
        return sample.timestamp
      }
      previous = used
    }
    return null
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
      const filteredModules = filterDisplayableModules(moduleResponse)
      modules = filteredModules
      detectSpoolResets(filteredModules)
      await loadSpoolUsageHistory(filteredModules)
      recordTankUsageSnapshot(filteredModules)
      recordHeaterTelemetrySnapshot(filteredModules)
      error = ''
      controlError = ''
    } catch (err) {
      console.error('Unable to load live module data', err)
      if (!telemetry.length) {
        telemetry = []
      }
      if (!summary.length) {
        summary = []
      }
      if (!modules.length) {
        modules = []
      }
      error = 'Live modules not responding.'
    } finally {
      loading = false
      lastUpdated = new Date().toLocaleTimeString()
    }
  }

  async function loadCycleHistory(windowHours = cycleWindow, options = {}) {
    const { silent = false } = options
    if (!silent) {
      cycleHistoryLoading = true
      cycleHistoryError = ''
    }
    try {
      cycleHistory = await fetchCycleHistory(windowHours)
      if (!silent) {
        cycleHistoryError = ''
      }
    } catch (err) {
      console.error('Unable to load cycle history', err)
      if (!silent) {
        cycleHistoryError = cycleHistory
          ? 'Unable to refresh cycle history — showing cached data.'
          : 'Unable to load cycle history.'
      }
    } finally {
      if (!silent) {
        cycleHistoryLoading = false
      }
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
    const storedTankResets = hydrateStoredTankResetTimestamps()
    tankResetTimestamps.clear()
    storedTankResets.forEach((timestamp, moduleId) => {
      if (typeof timestamp === 'number' && moduleId) {
        tankResetTimestamps.set(moduleId, timestamp)
      }
    })
    refresh()
    loadCycleHistory(cycleWindow)
    const refreshInterval = setInterval(() => {
      refresh()
    }, 15000)
    cycleHistoryRefreshTimer = setInterval(() => {
      loadCycleHistory(cycleWindow, { silent: true })
    }, 20000)
    return () => {
      clearInterval(refreshInterval)
      if (cycleHistoryRefreshTimer) {
        clearInterval(cycleHistoryRefreshTimer)
        cycleHistoryRefreshTimer = null
      }
      stopWsLogPolling()
    }
  })

  onDestroy(() => {
    if (calibrationAckTimer) {
      clearInterval(calibrationAckTimer)
      calibrationAckTimer = null
    }
  })

  $: activeThermistorAlarmDetails = isThermistorMismatchAlarm(activeAlarmModal)
    ? describeThermistorAlarmMeta(activeAlarmModal)
    : null

  $: usageChartWindowMs = usageChartWindowHours * HOUR_IN_MS
  $: temperatureChartWindowMs = temperatureChartWindowHours * HOUR_IN_MS
  $: latestByMetric = telemetry.reduce((acc, row) => {
    const timestamp = new Date(row.captured_at).getTime()
    const existingTs = acc[row.metric]?.ts ?? 0
    if (timestamp > existingTs) {
      acc[row.metric] = { value: row.value, unit: row.unit, ts: timestamp }
    }
    return acc
  }, {})

  $: moduleCounts = (Array.isArray(moduleCards) ? moduleCards : []).reduce(
    (acc, module) => {
      const status = module.status ?? 'offline'
      acc[status] = (acc[status] ?? 0) + 1
      acc.total += 1
      return acc
    },
    { online: 0, offline: 0, discovering: 0, total: 0 }
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
    const directHeater = statusPayload.heater
    const listHeater = Array.isArray(statusPayload.heaters)
      ? statusPayload.heaters.find((entry) => entry && typeof entry === 'object')
      : null
    const resolvedHeater =
      directHeater && typeof directHeater === 'object'
        ? directHeater
        : listHeater && typeof listHeater === 'object'
          ? listHeater
          : null

    return {
      ...module,
      module_type: module?.module_type ?? module?.moduleType ?? null,
      statusPayload,
      configPayload,
      motor: { ...configMotor, ...statusMotor },
      floats: statusPayload.floats ?? {},
      ato: { ...configAto, ...statusAto },
      system: statusPayload.system ?? {},
      spool: mergedSpool,
      heater: resolvedHeater,
      alarms: module.alarms ?? [],
    }
  }

  const moduleTypeClassName = (value) => {
    if (typeof value !== 'string') return ''
    const normalized = value.trim().toLowerCase()
    if (!normalized) return ''
    return `type-${normalized.replace(/[^a-z0-9]+/g, '-')}`
  }

  const coalesceNumber = (...values) => {
    for (const value of values) {
      if (typeof value === 'number' && !Number.isNaN(value)) {
        return value
      }
    }
    return undefined
  }

  const clampSetpointValue = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return undefined
    return Math.min(Math.max(value, HEATER_SETPOINT_MIN_BOUND_C), HEATER_SETPOINT_MAX_BOUND_C)
  }

  const computeTankUsageSinceRefill = (module) => {
    if (!module) return null
    const statusPayload = module.statusPayload ?? module.status_payload ?? {}
    const configPayload = module.configPayload ?? module.config_payload ?? {}
    const statusAto = statusPayload.ato ?? {}
    const configAto = configPayload.ato ?? {}
    const mergedAto = { ...configAto, ...statusAto, ...(module.ato ?? {}) }
    const capacity = coalesceNumber(
      mergedAto?.tank_capacity_ml,
      configAto?.tank_capacity_ml,
      DEFAULT_TANK_CAPACITY_ML
    )
    const level = coalesceNumber(mergedAto?.tank_level_ml)
    if (capacity == null || level == null) return null
    return Math.max(0, capacity - level)
  }

  const recordTankUsageSnapshot = (moduleList = []) => {
    if (!Array.isArray(moduleList) || moduleList.length === 0) return
    const now = Date.now()
    const cutoff = now - TANK_USAGE_HISTORY_MS
    const nextHistory = new Map(tankUsageHistory)
    moduleList.forEach((module) => {
      const moduleId = module?.module_id
      if (!moduleId) return
      const snapshot = {
        module_id: moduleId,
        ato: {
          ...(module?.config_payload?.ato ?? {}),
          ...(module?.configPayload?.ato ?? {}),
          ...(module?.status_payload?.ato ?? {}),
          ...(module?.statusPayload?.ato ?? {}),
          ...(module?.ato ?? {}),
        },
        configPayload: {
          ato: module?.config_payload?.ato ?? module?.configPayload?.ato ?? {},
        },
        statusPayload: {
          ato: module?.status_payload?.ato ?? module?.statusPayload?.ato ?? {},
        },
      }
      const usedMl = computeTankUsageSinceRefill(snapshot)
      if (usedMl == null) return
      const samples = nextHistory.get(moduleId) ?? []
      const previousSample = samples.length ? samples[samples.length - 1] : null
      const resetDetected =
        previousSample &&
        typeof previousSample.usedMl === 'number' &&
        previousSample.usedMl - usedMl > TANK_RESET_THRESHOLD_ML
      samples.push({ timestamp: now, usedMl })
      const filtered = samples.filter((sample) => sample.timestamp >= cutoff)
      nextHistory.set(moduleId, filtered)

      if (resetDetected || (!previousSample && usedMl <= TANK_RESET_THRESHOLD_ML)) {
        markTankReset(moduleId, now)
      } else if (!tankResetTimestamps.has(moduleId)) {
        const inferred = filtered.find((sample) => sample.usedMl <= TANK_RESET_THRESHOLD_ML)
        if (inferred) {
          markTankReset(moduleId, inferred.timestamp)
        }
      }
    })
    tankUsageHistory = nextHistory
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

  const describeAtoMode = (ato = {}) => {
    if (ato.paused) return 'Paused'
    if (ato.manual_mode) return 'Manual'
    return 'Auto'
  }

  const getHeaterPayload = (module = {}) => {
    const direct = module?.heater
    if (direct && typeof direct === 'object') {
      return direct
    }
    const statusPayload = module?.statusPayload ?? module?.status_payload ?? {}
    if (statusPayload?.heater && typeof statusPayload.heater === 'object') {
      return statusPayload.heater
    }
    if (Array.isArray(statusPayload?.heaters)) {
      const first = statusPayload.heaters.find((entry) => entry && typeof entry === 'object')
      if (first) {
        return first
      }
    }
    return null
  }

  const titleCase = (value) => {
    if (typeof value !== 'string' || !value.trim().length) return ''
    return value
      .trim()
      .replace(/[_-]+/g, ' ')
      .split(' ')
      .map((token) => (token ? token[0].toUpperCase() + token.slice(1) : ''))
      .join(' ')
      .trim()
  }

  const resolveTemperatureReading = (raw, options = {}) => {
    const { fallbackLabel = 'Thermometer', fallbackUnit = '°C' } = options
    if (raw == null) return null
    const coerceNumber = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)
    const fromPrimitive = coerceNumber(raw)
    if (fromPrimitive != null) {
      return { label: fallbackLabel, value: fromPrimitive, unit: fallbackUnit }
    }
    if (typeof raw !== 'object') return null
    const label = typeof raw.label === 'string' && raw.label.trim().length ? raw.label.trim() : fallbackLabel
    const normalizedUnit = (() => {
      const rawUnit = typeof raw.unit === 'string' ? raw.unit.trim().toLowerCase() : ''
      if (rawUnit.includes('f')) return '°F'
      if (rawUnit.includes('c')) return '°C'
      return fallbackUnit
    })()
    const candidateBuckets = [
      { unit: '°C', keys: ['celsius', 'c', 'deg_c', 'temperature_c', 'value_c', 'temp_c'] },
      { unit: '°F', keys: ['fahrenheit', 'f', 'deg_f', 'temperature_f', 'value_f', 'temp_f'] },
      { unit: normalizedUnit, keys: ['value', 'reading', 'temperature'] },
    ]
    for (const bucket of candidateBuckets) {
      for (const key of bucket.keys) {
        const numeric = coerceNumber(raw[key])
        if (numeric != null) {
          return { label, value: numeric, unit: bucket.unit ?? normalizedUnit }
        }
      }
    }
    const fallbackNumeric = coerceNumber(raw.v)
    if (fallbackNumeric != null) {
      return { label, value: fallbackNumeric, unit: normalizedUnit }
    }
    return null
  }

  const buildThermometerKeyVariants = (index) => {
    const suffixes = ['', '_c', '_f']
    const bases = ['thermometer', 'thermo', 'probe', 'temp', 'sensor']
    const separators = ['_', '']
    const variants = []
    bases.forEach((base) => {
      separators.forEach((separator) => {
        suffixes.forEach((suffix) => {
          variants.push(`${base}${separator}${index}${suffix}`.toLowerCase())
        })
      })
    })
    return variants
  }

  const extractThermometerFromKeys = (payload, index, fallbackLabel) => {
    if (!payload || typeof payload !== 'object') return null
    const entries = Object.entries(payload)
    const variants = buildThermometerKeyVariants(index)
    for (const key of variants) {
      const match = entries.find(([entryKey]) => entryKey && entryKey.toLowerCase() === key)
      if (!match) continue
      const [, value] = match
      const fallbackUnit = key.includes('_f') ? '°F' : '°C'
      const reading = resolveTemperatureReading(value, { fallbackLabel, fallbackUnit })
      if (reading) {
        return reading
      }
    }
    return null
  }

  const getHeaterThermometers = (module = {}) => {
    const payload = getHeaterPayload(module)
    if (!payload || typeof payload !== 'object') return []
    const readings = []
    const pushReading = (reading) => {
      if (!reading) return
      if (readings.some((entry) => entry.label === reading.label)) return
      readings.push(reading)
    }

    if (Array.isArray(payload.thermometers)) {
      payload.thermometers.forEach((entry, idx) => {
        if (readings.length >= 2) return
        const label = entry?.label ?? `Thermometer ${idx + 1}`
        pushReading(resolveTemperatureReading(entry, { fallbackLabel: label }))
      })
    } else if (payload.thermometers && typeof payload.thermometers === 'object') {
      Object.entries(payload.thermometers).forEach(([key, value], idx) => {
        if (readings.length >= 2) return
        const label = key ? titleCase(key) : `Thermometer ${idx + 1}`
        pushReading(resolveTemperatureReading(value, { fallbackLabel: label }))
      })
    }

    const pushThermistorArray = (entries, { labelPrefix = 'Thermistor', unit = '°C' } = {}) => {
      if (!Array.isArray(entries) || !entries.length) return
      entries.forEach((value, idx) => {
        if (readings.length >= 2) return
        pushReading(
          resolveTemperatureReading(value, {
            fallbackLabel: `${labelPrefix} ${idx + 1}`,
            fallbackUnit: unit,
          })
        )
      })
    }

    if (readings.length < 2) {
      pushThermistorArray(payload.thermistors_c, { labelPrefix: 'Thermistor', unit: '°C' })
    }
    if (readings.length < 2) {
      pushThermistorArray(payload.thermistors_f, { labelPrefix: 'Thermistor', unit: '°F' })
    }
    if (readings.length < 2) {
      pushThermistorArray(payload.thermistors, { labelPrefix: 'Thermistor' })
    }

    const primaryKeys = [
      'primary_temp_c',
      'primary_temp_f',
      'primary_temp',
      'primary',
      'primary_c',
      'primary_f',
    ]
    const secondaryKeys = [
      'secondary_temp_c',
      'secondary_temp_f',
      'secondary_temp',
      'secondary',
      'secondary_c',
      'secondary_f',
    ]

    const pushFromKeys = (keys, fallbackLabel) => {
      if (readings.length >= 2) return
      for (const key of keys) {
        if (!(key in payload)) continue
        const reading = resolveTemperatureReading(payload[key], { fallbackLabel })
        if (reading) {
          pushReading(reading)
          break
        }
      }
    }

    if (readings.length < 2) {
      pushFromKeys(primaryKeys, 'Primary probe')
    }
    if (readings.length < 2) {
      pushFromKeys(secondaryKeys, 'Secondary probe')
    }

    if (readings.length < 2) {
      pushReading(extractThermometerFromKeys(payload, 1, 'Thermometer 1'))
    }
    if (readings.length < 2) {
      pushReading(extractThermometerFromKeys(payload, 2, 'Thermometer 2'))
    }

    return readings.slice(0, 2)
  }

  const formatThermometerReading = (reading) => {
    if (!reading || typeof reading.value !== 'number' || Number.isNaN(reading.value)) return '—'
    const decimals = Math.abs(reading.value) >= 10 ? 1 : 2
    return `${reading.value.toFixed(decimals)} ${reading.unit ?? '°C'}`
  }

  const formatCelsiusValue = (value, fallback = '—') => {
    if (typeof value !== 'number' || Number.isNaN(value)) return fallback
    return `${value.toFixed(1)} °C`
  }

  const isThermistorMismatchAlarm = (alarm) => alarm?.code === 'thermistor_mismatch'

  const describeThermistorAlarmMeta = (alarm = {}) => {
    if (!alarm) return null
    const meta = alarm.meta ?? {}
    const delta = coalesceNumber(meta.delta_c, meta.delta, meta.deltaC)
    const threshold = coalesceNumber(meta.threshold_c, meta.delta_threshold_c, meta.threshold)
    const primary = coalesceNumber(meta.primary_temp_c, meta.primary_c, meta.primary)
    const secondary = coalesceNumber(meta.secondary_temp_c, meta.secondary_c, meta.secondary)
    if ([delta, threshold, primary, secondary].every((value) => value == null)) {
      return null
    }
    return { delta, threshold, primary, secondary }
  }

  const getHeaterDutyCyclePercent = (module = {}) => {
    const payload = getHeaterPayload(module)
    if (!payload || typeof payload !== 'object') return null
    const candidates = [
      payload.duty_per_min,
      payload.duty_cycle_per_min,
      payload.duty_cycle_per_minute,
      payload.duty_cycle_per_min_avg,
      payload.duty_cycle,
      payload.output_per_min,
      payload.output,
    ]
    for (const candidate of candidates) {
      if (typeof candidate === 'number' && Number.isFinite(candidate)) {
        const percent = candidate > 1 ? candidate : candidate * 100
        if (Number.isFinite(percent)) {
          return Math.max(0, Math.min(100, percent))
        }
      }
    }
    return null
  }

  const formatDutyCycleLabel = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—'
    const clamped = Math.max(0, Math.min(100, value))
    const decimals = clamped >= 10 ? 0 : 1
    return `${clamped.toFixed(decimals)}%`
  }

  const describeHeaterPowerState = (module = {}) => {
    const payload = getHeaterPayload(module) ?? {}
    const rawState = (payload.state ?? payload.status ?? '').toString().trim()
    if (rawState) {
      const normalized = rawState.toLowerCase()
      const active = normalized.includes('heat') || normalized.includes('on') || normalized.includes('active')
      const inactive = normalized.includes('idle') || normalized.includes('off') || normalized.includes('standby')
      return {
        label: active ? 'On' : inactive ? 'Off' : formatState(rawState),
        description: formatState(rawState) || 'Heater state',
        active,
      }
    }
    const dutyPercent = getHeaterDutyCyclePercent(module)
    if (typeof dutyPercent === 'number') {
      const active = dutyPercent >= 1
      return {
        label: active ? 'On' : 'Off',
        description: `${formatDutyCycleLabel(dutyPercent)} duty`,
        active,
      }
    }
    return {
      label: '—',
      description: 'Waiting for heater telemetry',
      active: false,
    }
  }

  const buildHeaterSummary = (module = {}) => ({
    thermometers: getHeaterThermometers(module),
    heaterState: describeHeaterPowerState(module),
    dutyPercent: getHeaterDutyCyclePercent(module),
  })

  const deriveModulePumpTimeout = (module = {}) =>
    coalesceNumber(
      module.system?.pump_timeout_ms,
      module.configPayload?.system?.pump_timeout_ms,
      module.statusPayload?.system?.pump_timeout_ms
    ) ?? DEFAULT_PUMP_TIMEOUT_MS

  const deriveModuleChirpInterval = (module = {}) =>
    coalesceNumber(
      module.system?.alarm_chirp_interval_ms,
      module.configPayload?.system?.alarm_chirp_interval_ms,
      module.statusPayload?.system?.alarm_chirp_interval_ms
    ) ?? DEFAULT_ALARM_CHIRP_INTERVAL_MS

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

  const formatMilliliters = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—'
    if (value >= 1000) {
      const liters = value / 1000
      const decimals = liters >= 10 || Number.isInteger(liters) ? 0 : 1
      return `${liters.toFixed(decimals)} L`
    }
    return `${Math.round(value)} ml`
  }

  const computeTankPercent = (ato = {}) => {
    if (!ato || typeof ato !== 'object') return undefined
    if (typeof ato.tank_percent === 'number') {
      return Math.max(0, Math.min(100, Math.round(ato.tank_percent)))
    }
    if (typeof ato.tank_level_ml === 'number' && typeof ato.tank_capacity_ml === 'number' && ato.tank_capacity_ml > 0) {
      return Math.max(0, Math.min(100, Math.round((ato.tank_level_ml / ato.tank_capacity_ml) * 100)))
    }
    return undefined
  }

  const formatTankPercent = (ato = {}) => {
    const percent = computeTankPercent(ato)
    return percent == null ? '—' : `${percent}%`
  }

  const describeTankVolume = (ato = {}) => {
    const level = coalesceNumber(ato?.tank_level_ml)
    const capacity = coalesceNumber(ato?.tank_capacity_ml)
    if (level != null && capacity != null) {
      return `${formatMilliliters(level)} / ${formatMilliliters(capacity)}`
    }
    if (capacity != null) {
      return `Capacity ${formatMilliliters(capacity)}`
    }
    return 'Awaiting tank telemetry'
  }

  const tankMeterWidth = (ato = {}) => computeTankPercent(ato) ?? 0
  const isTankLow = (ato = {}) => {
    const percent = computeTankPercent(ato)
    return typeof percent === 'number' && percent <= 25
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
    focusModuleCard(activeAlarmModal.moduleId, guessSubsystemFromAlert(activeAlarmModal))
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

  const getMetricAverage = (metric) => {
    const match = summary.find((item) => item.metric === metric)
    if (!match) return null
    const value = typeof match.avg_value === 'number' ? match.avg_value : Number(match.avg_value)
    return Number.isFinite(value) ? value : null
  }

  const formatValue = (metric) => {
    const { unit = '' } = metricCopy[metric] ?? {}
    if (metric === 'temperature') {
      const current = heroCurrentTempC ?? getMetricAverage(metric)
      if (current != null) {
        return `${current.toFixed(2)} ${unit}`.trim()
      }
    }
    const latest = latestByMetric[metric]
    if (!latest || typeof latest.value !== 'number') {
      return '—'
    }
    return `${latest.value.toFixed(2)} ${unit}`.trim()
  }

  const formatTimestamp = (timestamp) => new Date(timestamp).toLocaleTimeString()

  const prefillControls = (module) => {
    if (!module) return
    controlsPrefilledFor = module.module_id
    heaterSetpointMinC = undefined
    heaterSetpointMaxC = undefined
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

    const configHeater = module.configPayload?.heater ?? {}
    const statusHeater = module.statusPayload?.heater ?? {}
    const mergedHeater = { ...configHeater, ...statusHeater, ...(module.heater ?? {}) }

    const resolvedSetpoint = coalesceNumber(
      mergedHeater.setpoint_c,
      mergedHeater.target_c,
      mergedHeater.average_temp_c
    )
    if (resolvedSetpoint != null) {
      temperatureSetpointC = Number(resolvedSetpoint.toFixed(1))
    }

    const resolvedMin = coalesceNumber(
      mergedHeater.setpoint_min_c,
      mergedHeater.setpoint_low_c,
      mergedHeater.minimum_c,
      configHeater.setpoint_min_c
    )
    if (resolvedMin != null) {
      heaterSetpointMinC = clampSetpointValue(resolvedMin)
    }

    const resolvedMax = coalesceNumber(
      mergedHeater.setpoint_max_c,
      mergedHeater.setpoint_high_c,
      mergedHeater.maximum_c,
      configHeater.setpoint_max_c
    )
    if (resolvedMax != null) {
      heaterSetpointMaxC = clampSetpointValue(resolvedMax)
    }

    if (
      heaterSetpointMinC != null &&
      heaterSetpointMaxC != null &&
      heaterSetpointMinC > heaterSetpointMaxC
    ) {
      heaterSetpointMaxC = heaterSetpointMinC
    }
  }

  $: hydratedModules = modules.map(hydrateModule)
  $: moduleCards = hydratedModules
    .flatMap(createSubsystemCards)
    .map((card) => (isHeaterCard(card) ? { ...card, heater_summary: buildHeaterSummary(card) } : card))
  $: if (
    selectedModuleId &&
    !moduleCards.some((module) => (module.card_id ?? module.module_id) === selectedModuleId)
  ) {
    selectedModuleId = moduleCards[0]?.card_id ?? moduleCards[0]?.module_id ?? ''
  }
  $: if (!selectedModuleId && moduleCards.length) {
    selectedModuleId = moduleCards[0].card_id ?? moduleCards[0].module_id
  }
  $: selectedCard = moduleCards.find((module) => (module.card_id ?? module.module_id) === selectedModuleId)
  $: selectedModule = (() => {
    if (!selectedCard) return undefined
    const moduleId = getCardModuleId(selectedCard)
    return hydratedModules.find((module) => module.module_id === moduleId)
  })()
  $: atoWaterUsedSinceRefillMl = computeTankUsageSinceRefill(selectedModule)
  $: selectedPhysicalModuleId = selectedModule?.module_id ?? ''
  $: selectedSubsystem = getCardSubsystem(selectedCard) || 'roller'
  $: isRollerView = isRollerSubsystem(selectedSubsystem)
  $: isAtoView = normalizeSubsystemKind(selectedSubsystem) === 'ato'
  $: isHeaterView = isHeaterSubsystem(selectedSubsystem)
  $: if (selectedPhysicalModuleId && selectedPhysicalModuleId !== controlsPrefilledFor && selectedModule) {
    prefillControls(selectedModule)
  }
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
  $: if (!selectedPhysicalModuleId || (selectedPhysicalModuleId !== controlsPrefilledFor && spoolCalibrationAwaitingAck)) {
    spoolCalibrationAwaitingAck = false
  }
  $: if (!spoolCalibrationAwaitingAck) {
    stopCalibrationAckPolling()
  }
  $: selectedModuleUsage = spoolUsageHistory.filter((entry) => entry.moduleId === selectedPhysicalModuleId)
  $: moduleSpoolBaselineMs = (() => {
    void spoolResetVersion
    if (!selectedPhysicalModuleId) return 0
    return getModuleResetBaseline(selectedPhysicalModuleId)
  })()
  $: usageEntriesSinceBaseline = (() => {
    const baseline = moduleSpoolBaselineMs || 0
    return selectedModuleUsage.filter((entry) => entry.timestamp >= baseline)
  })()
  $: spoolLifetimeUsageMm = usageEntriesSinceBaseline.reduce((sum, entry) => sum + entry.deltaMm, 0)
  $: spoolReportedActivations = coalesceNumber(
    spoolState?.activations,
    spoolState?.activation_count,
    spoolState?.activationCount
  )
  $: spoolLifetimeActivationCount =
    typeof spoolReportedActivations === 'number' && Number.isFinite(spoolReportedActivations)
      ? Math.max(0, Math.round(spoolReportedActivations))
      : null
  $: spoolAverageActivationLengthMm =
    typeof spoolLifetimeActivationCount === 'number' && spoolLifetimeActivationCount > 0
      ? spoolLifetimeUsageMm / spoolLifetimeActivationCount
      : null
  $: spoolBaselineTimestamp = moduleSpoolBaselineMs || null
  $: rawAtoActivationCount = coalesceNumber(
    selectedModule?.ato?.activations,
    selectedModule?.ato?.activation_count,
    selectedModule?.ato?.activationCount,
    selectedModule?.statusPayload?.ato?.activations,
    selectedModule?.status_payload?.ato?.activations
  )
  $: atoLifetimeActivationCount =
    typeof rawAtoActivationCount === 'number' && Number.isFinite(rawAtoActivationCount)
      ? Math.max(0, Math.round(rawAtoActivationCount))
      : null
  $: atoAverageSinceRefillMl =
    atoWaterUsedSinceRefillMl != null &&
    typeof atoLifetimeActivationCount === 'number' &&
    atoLifetimeActivationCount > 0
      ? atoWaterUsedSinceRefillMl / atoLifetimeActivationCount
      : null
  $: tankLastRefillTimestamp = (() => {
    if (!selectedPhysicalModuleId) return null
    const stored = tankResetTimestamps.get(selectedPhysicalModuleId)
    if (typeof stored === 'number') return stored
    return findRecentTankResetTimestamp(selectedTankUsageSamples)
  })()
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
    if (!selectedPhysicalModuleId) return []
    const now = Date.now()
    const baseline = moduleSpoolBaselineMs || 0
    const cutoff = Math.max(now - usageChartWindowMs, baseline)
    return (rollerRuns ?? [])
      .filter((run) => run.module_id === selectedPhysicalModuleId)
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
  $: activeCycleWindowHours = cycleHistory?.window_hours ?? cycleWindow
  $: selectedAtoRuns = selectedPhysicalModuleId
    ? atoRuns.filter((run) => run.module_id === selectedPhysicalModuleId)
    : atoRuns
  $: {
    const effectiveRuns = selectedAtoRuns.length ? selectedAtoRuns : atoRuns
    const derivedCount = effectiveRuns.length
    const totalDuration = effectiveRuns.reduce((sum, run) => sum + (run.duration_ms ?? 0), 0)
    const avgDurationMs = derivedCount ? totalDuration / derivedCount : 0
    const avgFillSeconds = avgDurationMs ? avgDurationMs / 1000 : 0
    const windowVolumeMl = effectiveRuns.reduce((sum, run) => sum + runtimeMsToMilliliters(run.duration_ms ?? 0), 0)
    const frequencyPerHour = activeCycleWindowHours ? derivedCount / activeCycleWindowHours : 0
    atoStats = {
      count: derivedCount,
      frequency_per_hour: frequencyPerHour,
      avg_duration_ms: avgDurationMs,
      avg_fill_seconds: avgFillSeconds,
      total_volume_ml: windowVolumeMl,
      avg_volume_ml: derivedCount ? windowVolumeMl / derivedCount : 0,
    }
  }
  $: tankUsageCutoff = Date.now() - activeCycleWindowHours * HOUR_IN_MS
  $: selectedTankUsageSamples = (() => {
    if (!selectedPhysicalModuleId) return []
    return tankUsageHistory.get(selectedPhysicalModuleId) ?? []
  })()
  $: atoChartPoints = (() => {
    if (!selectedTankUsageSamples.length) return []
    let lastValue = null
    return [...selectedTankUsageSamples]
      .filter((sample) => sample.timestamp >= tankUsageCutoff)
      .sort((a, b) => a.timestamp - b.timestamp)
      .map((sample) => {
        const resetDetected = lastValue != null && sample.usedMl + TANK_RESET_THRESHOLD_ML < lastValue
        lastValue = sample.usedMl
        return {
          ts: sample.timestamp,
          used: sample.usedMl,
          reset: resetDetected,
        }
      })
  })()
  $: atoChartMaxValue = (() => {
    if (!atoChartPoints.length) return 0
    const maxUsed = Math.max(...atoChartPoints.map((point) => point.used), 0)
    const estimatedCapacity =
      coalesceNumber(
        selectedModule?.ato?.tank_capacity_ml,
        selectedModule?.configPayload?.ato?.tank_capacity_ml,
        selectedModule?.config_payload?.ato?.tank_capacity_ml,
        DEFAULT_TANK_CAPACITY_ML
      ) ?? DEFAULT_TANK_CAPACITY_ML
    return Math.max(maxUsed, estimatedCapacity)
  })()
  $: atoYAxisMax = atoChartMaxValue ? atoChartMaxValue * 1.05 : undefined
  $: atoResetMarkers = atoChartPoints.filter((point) => point.reset)
  $: atoActivationMarkers = (() => {
    if (!selectedPhysicalModuleId) return []
    return selectedAtoRuns
      .map((run) => ({ ts: new Date(run.recorded_at).getTime() }))
      .filter((marker) => marker.ts >= tankUsageCutoff)
  })()
  $: atoChartDatasets = atoChartPoints.length
    ? [
        {
          label: 'Water used',
          data: atoChartPoints.map((point) => ({
            x: point.ts,
            y: point.used,
          })),
          borderColor: 'rgba(95, 179, 255, 0.85)',
          backgroundColor: 'rgba(95, 179, 255, 0.15)',
          borderWidth: 2,
          fill: false,
          tension: 0.35,
          pointRadius: 3,
          pointHoverRadius: 4,
          pointBackgroundColor: '#5fb3ff',
          pointBorderColor: '#020710',
        },
        ...buildActivationDatasets(atoActivationMarkers, atoChartMaxValue || 0, {
          label: 'ATO activations',
          borderColor: 'rgba(248, 251, 255, 0.35)',
          borderDash: [3, 6],
        }),
        ...buildActivationDatasets(
          atoResetMarkers.map((point) => ({ ts: point.ts })),
          atoChartMaxValue || 0,
          {
            label: 'Tank refills',
            borderColor: 'rgba(246, 195, 67, 0.8)',
            borderDash: [2, 6],
          }
        ),
      ]
    : []
  $: selectedHeaterSamples = selectedPhysicalModuleId
    ? heaterTelemetryHistory.get(selectedPhysicalModuleId) ?? []
    : []
  $: heaterSamplesInWindow = (() => {
    if (!selectedHeaterSamples.length) return []
    const cutoff = Date.now() - temperatureChartWindowMs
    return selectedHeaterSamples.filter((sample) => sample.timestamp >= cutoff)
  })()
  $: temperatureSeries = buildTemperatureSeries(
    heaterSamplesInWindow,
    temperatureSetpointC,
    heaterSetpointMinC,
    heaterSetpointMaxC
  )
  $: temperatureChartDatasets = temperatureSeries.datasets
  $: temperatureYAxisMin = temperatureSeries.yMin
  $: temperatureYAxisMax = temperatureSeries.yMax
  $: latestTemperatureSample = heaterSamplesInWindow.length
    ? heaterSamplesInWindow[heaterSamplesInWindow.length - 1]
    : null
  $: temperatureChartMeta = buildTemperatureMeta(latestTemperatureSample, selectedModule)
  $: primaryHeaterSamples = (() => {
    if (!PRIMARY_HEATER_MODULE_ID) return []
    for (const [moduleId, samples] of heaterTelemetryHistory.entries()) {
      if (normalizeModuleId(moduleId) !== PRIMARY_HEATER_MODULE_ID) continue
      return Array.isArray(samples) ? samples : []
    }
    return []
  })()
  $: primaryHeaterSample = primaryHeaterSamples.length
    ? primaryHeaterSamples[primaryHeaterSamples.length - 1]
    : null
  $: heroCurrentTempC = computeSampleAverageC(primaryHeaterSample)
  $: heroAverage3dTempC = (() => {
    if (!primaryHeaterSamples.length) return null
    const cutoff = Date.now() - HERO_AVERAGE_WINDOW_MS
    const values = primaryHeaterSamples
      .filter((sample) => sample.timestamp >= cutoff)
      .map((sample) => computeSampleAverageC(sample))
      .filter((value) => typeof value === 'number' && Number.isFinite(value))
    if (!values.length) return null
    const sum = values.reduce((total, value) => total + value, 0)
    return sum / values.length
  })()
  $: alertEntries = hydratedModules.flatMap(buildModuleAlerts)
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

  const openControls = (cardId) => {
    selectedModuleId = cardId
    purgeConfirming = false
    const targetCard = moduleCards.find((module) => (module.card_id ?? module.module_id) === cardId)
    if (targetCard) {
      const physicalTarget = hydratedModules.find((module) => module.module_id === getCardModuleId(targetCard))
      prefillControls(physicalTarget ?? targetCard)
    }
    controlsVisible = true
  }

  const closeControls = () => {
    controlsVisible = false
    spoolResetConfirming = false
    tankRefillConfirming = false
    calibrationModalOpen = false
    spoolCalibrationAwaitingAck = false
    purgeConfirming = false
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

  const setTemperatureChartWindow = (hours) => {
    if (temperatureChartWindowHours === hours) return
    temperatureChartWindowHours = hours
  }

  const updateHeaterSetpointField = (kind, rawValue) => {
    if (rawValue == null || rawValue === '') return null
    const numeric = typeof rawValue === 'number' ? rawValue : Number(rawValue)
    if (Number.isNaN(numeric)) return null
    const clamped = clampSetpointValue(Number(numeric.toFixed(1)))
    if (kind === 'target') {
      temperatureSetpointC = clamped
    } else if (kind === 'min') {
      heaterSetpointMinC = clamped
      if (heaterSetpointMaxC != null && heaterSetpointMinC > heaterSetpointMaxC) {
        heaterSetpointMaxC = heaterSetpointMinC
      }
    } else if (kind === 'max') {
      heaterSetpointMaxC = clamped
      if (heaterSetpointMinC != null && heaterSetpointMaxC < heaterSetpointMinC) {
        heaterSetpointMinC = heaterSetpointMaxC
      }
    }
    return clamped
  }

  const handleSetpointInput = (kind, eventOrValue) => {
    const raw =
      typeof eventOrValue === 'object' && eventOrValue?.target
        ? eventOrValue.target.value
        : eventOrValue
    const result = updateHeaterSetpointField(kind, raw)
    if (result != null) {
      scheduleControlUpdate()
    }
  }

  const nudgeSetpointValue = (kind, delta) => {
    if (typeof delta !== 'number') return
    const baseline = (() => {
      if (kind === 'min') {
        if (typeof heaterSetpointMinC === 'number') return heaterSetpointMinC
        if (typeof temperatureSetpointC === 'number') return temperatureSetpointC
        return HEATER_SETPOINT_MIN_BOUND_C
      }
      if (kind === 'max') {
        if (typeof heaterSetpointMaxC === 'number') return heaterSetpointMaxC
        if (typeof temperatureSetpointC === 'number') return temperatureSetpointC
        return HEATER_SETPOINT_MAX_BOUND_C
      }
      if (typeof temperatureSetpointC === 'number') return temperatureSetpointC
      if (typeof heaterSetpointMinC === 'number' && typeof heaterSetpointMaxC === 'number') {
        return (heaterSetpointMinC + heaterSetpointMaxC) / 2
      }
      return (HEATER_SETPOINT_MIN_BOUND_C + HEATER_SETPOINT_MAX_BOUND_C) / 2
    })()
    const next = Number((baseline + delta).toFixed(1))
    handleSetpointInput(kind, next)
  }

  const setCycleChartWindow = (hours) => {
    const normalized = Math.max(1, Math.min(hours, MAX_CYCLE_WINDOW_HOURS))
    if (cycleWindow === normalized) return
    cycleWindow = normalized
    loadCycleHistory(normalized)
  }

  const refreshCycleHistory = () => {
    loadCycleHistory(cycleWindow)
  }

  const submitControls = async () => {
    if (!selectedPhysicalModuleId) {
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
    if (hasValue(temperatureSetpointC)) payload.heater_setpoint_c = Number(temperatureSetpointC)
    if (hasValue(heaterSetpointMinC)) payload.heater_setpoint_min_c = Number(heaterSetpointMinC)
    if (hasValue(heaterSetpointMaxC)) payload.heater_setpoint_max_c = Number(heaterSetpointMaxC)

    if (Object.keys(payload).length === 0) {
      return
    }

    controlBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedPhysicalModuleId, payload)
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
    if (!selectedPhysicalModuleId) {
      controlError = 'Select a module first.'
      spoolResetConfirming = false
      return
    }

    spoolResetBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedPhysicalModuleId, { reset_spool: true })
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
    if (!selectedPhysicalModuleId) {
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
    if (!selectedPhysicalModuleId) {
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
      await updateModuleControls(selectedPhysicalModuleId, {
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
    if (!selectedPhysicalModuleId) {
      controlError = 'Select a module first.'
      return
    }

    spoolCalibrationAwaitingAck = true
    spoolCalibrationBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedPhysicalModuleId, { spool_calibrate_start: true })
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
    if (!selectedPhysicalModuleId) {
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
      await updateModuleControls(selectedPhysicalModuleId, { spool_calibrate_finish: desiredLength })
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
    if (!selectedPhysicalModuleId) {
      controlError = 'Select a module first.'
      return
    }

    spoolCalibrationBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedPhysicalModuleId, { spool_calibrate_cancel: true })
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

  const startTankRefillConfirmation = () => {
    controlError = ''
    controlMessage = ''
    tankRefillConfirming = true
  }

  const cancelTankRefillConfirmation = () => {
    tankRefillConfirming = false
  }

  const triggerTankRefill = async () => {
    if (!selectedPhysicalModuleId) {
      controlError = 'Select a module first.'
      return
    }
    tankRefillBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await updateModuleControls(selectedPhysicalModuleId, { ato_tank_refill: 1 })
      controlMessage = 'Tank reset to full.'
      markTankReset(selectedPhysicalModuleId, Date.now())
      await refresh()
    } catch (err) {
      controlError = err.message ?? 'Failed to mark tank as refilled.'
    } finally {
      tankRefillBusy = false
      tankRefillConfirming = false
    }
  }

  const startModulePurge = () => {
    controlError = ''
    controlMessage = ''
    purgeConfirming = true
  }

  const cancelModulePurge = () => {
    purgeConfirming = false
  }

  const confirmModulePurge = async () => {
    if (!selectedPhysicalModuleId) {
      controlError = 'Select a module first.'
      purgeConfirming = false
      return
    }

    purgeBusy = true
    controlError = ''
    controlMessage = ''
    try {
      await deleteModule(selectedPhysicalModuleId)
      controlMessage = 'Module removed. It will show up again after it reconnects.'
      purgeConfirming = false
      controlsVisible = false
      selectedModuleId = ''
      await refresh()
    } catch (err) {
      controlError = err.message ?? 'Failed to purge module.'
    } finally {
      purgeBusy = false
    }
  }

  const scheduleControlUpdate = () => {
    if (!selectedPhysicalModuleId) return
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
                  on:click={() => focusModuleCard(alert.moduleId, guessSubsystemFromAlert(alert))}
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
      <article class="panel metric-card" class:metric-card--temperature={metric === 'temperature'}>
        <header class="metric-card__header">
          <div>
            <p>{metricCopy[metric].label}</p>
            {#if metric === 'temperature'}
              <small>Source: PickleHeat</small>
            {/if}
          </div>
          <span class={`metric-card__value ${metric === 'temperature' ? 'metric-card__value--xl' : ''}`}>
            {formatValue(metric)}
          </span>
        </header>
        <footer class="metric-card__footer">
          {#if metric === 'temperature'}
            <p>
              Avg (3d):
              {#if heroAverage3dTempC != null}
                {heroAverage3dTempC.toFixed(2)} {metricCopy[metric].unit}
              {:else if summary.find((item) => item.metric === metric)?.avg_value != null}
                {summary.find((item) => item.metric === metric)?.avg_value?.toFixed(2)} {metricCopy[metric].unit}
              {:else}
                —
              {/if}
            </p>
          {:else}
            <p>
              Avg {metricCopy[metric].label.toLowerCase()}:
              {summary.find((item) => item.metric === metric)?.avg_value?.toFixed(2) ?? '—'}
            </p>
          {/if}
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
            <li
              class="module-card"
              class:selected={(module.card_id ?? module.module_id) === selectedModuleId}
            >
              <div class="module-card__head">
                <div>
                  <p class="module-label">
                    {module.label}
                    {#if module.module_type}
                      <span class={`module-type-pill ${moduleTypeClassName(module.module_type)}`}>
                        {module.module_type}
                      </span>
                    {/if}
                    <span class="module-subsystem-pill">{module.badge_label}</span>
                  </p>
                  <p class="module-meta">{module.module_id}</p>
                </div>
                <div class="module-meta ip-meta">
                  IP {module.ip_address ?? '—'} · RSSI {module.rssi ?? '—'} dBm
                </div>
                <div class="module-card__actions">
                  <span class="pill {statusPalette[module.status] ?? ''}">{formatState(module.status)}</span>
                  <button
                    type="button"
                    class="ghost small"
                    on:click={() => openControls(module.card_id ?? module.module_id)}
                  >
                    Controls
                  </button>
                </div>
              </div>
              <div class="module-card__insights" class:heater-layout={isHeaterCard(module)}>
                {#if isHeaterCard(module)}
                  <div class="insight">
                    <p>{module.heater_summary?.thermometers?.[0]?.label ?? 'Thermometer 1'}</p>
                    <strong>{formatThermometerReading(module.heater_summary?.thermometers?.[0])}</strong>
                    <small>Primary probe</small>
                  </div>
                  <div class="insight">
                    <p>{module.heater_summary?.thermometers?.[1]?.label ?? 'Thermometer 2'}</p>
                    <strong>{formatThermometerReading(module.heater_summary?.thermometers?.[1])}</strong>
                    <small>Secondary probe</small>
                  </div>
                  <div class="insight">
                    <p>Heater state</p>
                    <strong class:active={module.heater_summary?.heaterState?.active}>
                      {module.heater_summary?.heaterState?.label ?? '—'}
                    </strong>
                    <small>{module.heater_summary?.heaterState?.description ?? 'Waiting for heater telemetry'}</small>
                  </div>
                  <div class="insight">
                    <p>Duty / min</p>
                    <strong>{formatDutyCycleLabel(module.heater_summary?.dutyPercent)}</strong>
                    <small>Rolling 60-second average</small>
                  </div>
                {:else if isRollerSubsystem(module.subsystem)}
                  <div class="insight">
                    <p>Filter</p>
                    <strong>{formatState(module.motor.state)}</strong>
                    <small>{formatMotorDetails(module.motor)}</small>
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
                {:else}
                  <div class="insight">
                    <p>ATO pump</p>
                    <strong>{module.ato.pump_running ? 'Filling' : 'Idle'}</strong>
                    <small>{describePump(module.ato)}</small>
                  </div>
                  <div class="insight">
                    <p>ATO mode</p>
                    <strong>{describeAtoMode(module.ato)}</strong>
                    <small>{module.ato.manual_mode ? 'Manual override ready' : 'Automatic sensing'}</small>
                  </div>
                  <div class="insight tank-insight">
                    <p>Reservoir</p>
                    <strong class:alarm={isTankLow(module.ato)}>{formatTankPercent(module.ato)}</strong>
                    <small>{describeTankVolume(module.ato)}</small>
                    <div
                      class="tank-meter"
                      role="progressbar"
                      aria-label="ATO reservoir level"
                      aria-valuemin="0"
                      aria-valuemax="100"
                      aria-valuenow={computeTankPercent(module.ato) ?? 0}
                    >
                      <span class:low={isTankLow(module.ato)} style={`width: ${tankMeterWidth(module.ato)}%;`}></span>
                    </div>
                  </div>
                  <div class="insight">
                    <p>Timeout window</p>
                    <strong>{formatCycleDuration(deriveModulePumpTimeout(module))}</strong>
                    <small>Alerts every {formatChirpInterval(deriveModuleChirpInterval(module))}</small>
                  </div>
                  <div class="insight">
                    <p>Floats</p>
                    <div class="float-pills">
                      {#each floatIndicators as indicator}
                        <span class:active={module.floats[indicator.key]}>{indicator.label}</span>
                      {/each}
                    </div>
                  </div>
                  <div class="insight">
                    <p>Uptime</p>
                    <strong>{formatDuration(module.system.uptime_s)}</strong>
                    <small>Last seen {formatTimestamp(module.last_seen)}</small>
                  </div>
                {/if}
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

      {#if cycleHistoryError}
        <div class="banner warning">{cycleHistoryError}</div>
      {/if}
      <ChartWidget
        ariaLabel="Estimated filter media usage"
        label="Usage window"
        description={describeUsageWindow(usageChartWindowHours)}
        buttons={usageWindowButtons}
        activeValue={usageChartWindowHours}
        on:select={(event) => setUsageChartWindow(event.detail)}
      >
        {#if !selectedPhysicalModuleId}
          <div class="chart-widget__placeholder">
            <p class="placeholder">Select a module to track filter usage.</p>
          </div>
        {:else if loading && usageChart.points.length === 0}
          <div class="chart-widget__placeholder">
            <p class="placeholder">Loading filter usage…</p>
          </div>
        {:else if usageChart.points.length === 0 && usageActivationMarkers.length === 0}
          <div class="chart-widget__placeholder">
            <p class="placeholder">
              No filter movement detected in the last {formatUsageWindowShort(usageChartWindowHours)}.
            </p>
          </div>
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
        {/if}

        <svelte:fragment slot="meta">
          {#if selectedPhysicalModuleId}
            <div class="chart-meta usage-meta">
              <div class="chart-meta__context">
                <p>Data - since last refill on:</p>
                <strong>{formatBaselineTimestamp(spoolBaselineTimestamp)}</strong>
              </div>
              <div>
                <p>Activations (spool)</p>
                <strong>{spoolLifetimeActivationCount ?? '—'}</strong>
              </div>
              <div>
                <p>Avg media use</p>
                <strong>
                  {spoolAverageActivationLengthMm != null
                    ? formatSpoolMediaLength(spoolAverageActivationLengthMm)
                    : '—'}
                </strong>
              </div>
              <div>
                <p>Total media used</p>
                <strong>{formatSpoolMediaLength(spoolLifetimeUsageMm)}</strong>
              </div>
            </div>
          {/if}
        </svelte:fragment>
      </ChartWidget>

      <ChartWidget
        ariaLabel="Heater temperature history"
        label="Heater window"
        description={describeUsageWindow(temperatureChartWindowHours)}
        buttons={temperatureWindowButtons}
        activeValue={temperatureChartWindowHours}
        on:select={(event) => setTemperatureChartWindow(event.detail)}
      >
        {#if !selectedPhysicalModuleId}
          <div class="chart-widget__placeholder">
            <p class="placeholder">Select a module to visualize heater telemetry.</p>
          </div>
        {:else if loading && !temperatureChartDatasets.length}
          <div class="chart-widget__placeholder">
            <p class="placeholder">Loading heater telemetry…</p>
          </div>
        {:else if !temperatureChartDatasets.length}
          <div class="chart-widget__placeholder">
            <p class="placeholder">
              No heater telemetry captured in the last {formatUsageWindowShort(temperatureChartWindowHours)}.
            </p>
          </div>
        {:else}
          <LineChart
            datasets={temperatureChartDatasets}
            ariaLabel="Heater temperature chart"
            yTitle="Temperature (°C)"
            xTitle="Time"
            xTickFormatter={formatCycleTimestamp}
            tooltipFormatter={temperatureTooltipFormatter}
            height={320}
            fontSize={16}
            fontWeight="600"
            tickColor="rgba(255, 255, 255, 0.95)"
            gridColor="rgba(255, 255, 255, 0.2)"
            yBeginAtZero={false}
            yMin={temperatureYAxisMin}
            yMax={temperatureYAxisMax}
            showLegend={true}
          />
        {/if}

        <svelte:fragment slot="controls">
          <label class="setpoint-control" for="temperature-setpoint">
            <span>Setpoint</span>
            <div class="setpoint-control__input">
              <input
                id="temperature-setpoint"
                type="number"
                min={HEATER_SETPOINT_MIN_BOUND_C}
                max={HEATER_SETPOINT_MAX_BOUND_C}
                step="0.1"
                bind:value={temperatureSetpointC}
                inputmode="decimal"
                aria-label="Temperature setpoint"
                on:input={(event) => handleSetpointInput('target', event)}
              />
              <span class="unit">°C</span>
            </div>
          </label>
        </svelte:fragment>

        <svelte:fragment slot="meta">
          {#if temperatureChartMeta}
            <div class="chart-meta temperature-meta">
              <div>
                <p>Last sample</p>
                <strong>{formatTimestamp(temperatureChartMeta.timestamp)}</strong>
              </div>
              {#each temperatureChartMeta.readings as reading}
                <div>
                  <p>{reading.label}</p>
                  <strong>{formatCelsiusValue(reading.value)}</strong>
                </div>
              {/each}
              <div>
                <p>Heater</p>
                <strong class:active={temperatureChartMeta.heaterOn}>
                  {temperatureChartMeta.heaterOn ? 'Heating' : 'Idle'}
                </strong>
                <small>{temperatureChartMeta.description || 'Awaiting heater telemetry'}</small>
              </div>
            </div>
          {/if}
        </svelte:fragment>
      </ChartWidget>

      <ChartWidget
        ariaLabel="ATO cycles chart"
        label="ATO window"
        description={describeUsageWindow(activeCycleWindowHours)}
        buttons={cycleWindowButtons}
        activeValue={activeCycleWindowHours}
        on:select={(event) => setCycleChartWindow(event.detail)}
      >
        <svelte:fragment slot="controls">
          <button type="button" class="refresh" on:click={refreshCycleHistory} aria-label="Refresh cycle data">
            ↻
          </button>
        </svelte:fragment>

        {#if cycleHistoryLoading && !atoChartPoints.length}
          <div class="chart-widget__placeholder">
            <p class="placeholder">Loading ATO water usage…</p>
          </div>
        {:else if !atoChartPoints.length}
          <div class="chart-widget__placeholder">
            <p class="placeholder">No ATO water usage in this window.</p>
          </div>
        {:else}
          <LineChart
            datasets={atoChartDatasets}
            ariaLabel="ATO water usage chart"
            yTitle="Water pumped"
            xTitle="Time"
            yTickFormatter={formatMilliliters}
            xTickFormatter={formatCycleTimestamp}
            tooltipFormatter={atoTooltipFormatter}
            ySuggestedMax={atoYAxisMax}
            height={320}
            fontSize={16}
            fontWeight="600"
            tickColor="rgba(255, 255, 255, 0.95)"
            gridColor="rgba(255, 255, 255, 0.2)"
          />
        {/if}

        <svelte:fragment slot="meta">
          <div class="chart-meta">
            <div class="chart-meta__context">
              <p>Data - since last refill on:</p>
              <strong>{formatBaselineTimestamp(tankLastRefillTimestamp)}</strong>
            </div>
            <div>
              <p>ATO activations</p>
              <strong>{atoLifetimeActivationCount ?? atoStats.count ?? '—'}</strong>
            </div>
            <div>
              <p>Avg water per activation</p>
              <strong>
                {atoAverageSinceRefillMl != null
                  ? formatMilliliters(atoAverageSinceRefillMl)
                  : formatMilliliters(atoStats.avg_volume_ml ?? 0)}
              </strong>
            </div>
            <div>
              <p>Water used</p>
              <strong>
                {atoWaterUsedSinceRefillMl != null
                  ? formatMilliliters(atoWaterUsedSinceRefillMl)
                  : formatMilliliters(atoStats.total_volume_ml ?? 0)}
              </strong>
            </div>
          </div>
        </svelte:fragment>
      </ChartWidget>

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
          <p class="section-label">
            {#if selectedCard}
              {#if isHeaterView}
                Heater Controls
              {:else if isAtoView}
                ATO Controls
              {:else}
                Roller Controls
              {/if}
            {:else}
              Module Controls
            {/if}
          </p>
          <h2>{selectedCard?.label ?? selectedModule?.label ?? 'Select a module'}</h2>
          <small>{selectedPhysicalModuleId}</small>
        </div>
        <button type="button" class="ghost close" on:click={closeControls} aria-label="Close controls">
          ×
        </button>
      </header>
      <section class="control-form">
        <small class="control-hint">Changes sync automatically as you adjust settings.</small>

        {#if isHeaterView}
          <div class="form-group heater-setpoints">
            <div class="form-label-row">
              <p class="form-label">Setpoint band</p>
              <span class="length-meta">
                Target {temperatureSetpointC != null ? formatCelsiusValue(temperatureSetpointC) : '—'}
              </span>
            </div>
            <small>Define the temperature window the heater firmware should hold before toggling output.</small>
            <div class="touch-input primary-touch-input">
              <button
                type="button"
                class="touch-input__button"
                aria-label="Decrease target setpoint"
                on:click={() => nudgeSetpointValue('target', -0.1)}
              >
                −
              </button>
              <div class="length-input">
                <input
                  type="number"
                  min={HEATER_SETPOINT_MIN_BOUND_C}
                  max={HEATER_SETPOINT_MAX_BOUND_C}
                  step="0.1"
                  bind:value={temperatureSetpointC}
                  inputmode="decimal"
                  placeholder="25.0"
                  aria-label="Target heater setpoint"
                  on:input={(event) => handleSetpointInput('target', event)}
                />
                <span>°C</span>
              </div>
              <button
                type="button"
                class="touch-input__button"
                aria-label="Increase target setpoint"
                on:click={() => nudgeSetpointValue('target', 0.1)}
              >
                +
              </button>
            </div>
            <div class="setpoint-range">
              <label>
                <span>Minimum</span>
                <div class="touch-input">
                  <button
                    type="button"
                    class="touch-input__button"
                    aria-label="Decrease minimum setpoint"
                    on:click={() => nudgeSetpointValue('min', -0.1)}
                  >
                    −
                  </button>
                  <div class="length-input">
                    <input
                      type="number"
                      min={HEATER_SETPOINT_MIN_BOUND_C}
                      max={HEATER_SETPOINT_MAX_BOUND_C}
                      step="0.1"
                      bind:value={heaterSetpointMinC}
                      inputmode="decimal"
                      placeholder="24.5"
                      aria-label="Minimum setpoint"
                      on:input={(event) => handleSetpointInput('min', event)}
                    />
                    <span>°C</span>
                  </div>
                  <button
                    type="button"
                    class="touch-input__button"
                    aria-label="Increase minimum setpoint"
                    on:click={() => nudgeSetpointValue('min', 0.1)}
                  >
                    +
                  </button>
                </div>
              </label>
              <label>
                <span>Maximum</span>
                <div class="touch-input">
                  <button
                    type="button"
                    class="touch-input__button"
                    aria-label="Decrease maximum setpoint"
                    on:click={() => nudgeSetpointValue('max', -0.1)}
                  >
                    −
                  </button>
                  <div class="length-input">
                    <input
                      type="number"
                      min={HEATER_SETPOINT_MIN_BOUND_C}
                      max={HEATER_SETPOINT_MAX_BOUND_C}
                      step="0.1"
                      bind:value={heaterSetpointMaxC}
                      inputmode="decimal"
                      placeholder="25.5"
                      aria-label="Maximum setpoint"
                      on:input={(event) => handleSetpointInput('max', event)}
                    />
                    <span>°C</span>
                  </div>
                  <button
                    type="button"
                    class="touch-input__button"
                    aria-label="Increase maximum setpoint"
                    on:click={() => nudgeSetpointValue('max', 0.1)}
                  >
                    +
                  </button>
                </div>
              </label>
            </div>
          </div>
        {/if}

        {#if isAtoView}
          <div class="form-group">
            <p class="form-label">ATO mode</p>
            <div class="radio-group" on:change={scheduleControlUpdate}>
              <label><input type="radio" name="ato-mode" value="auto" bind:group={atoMode} /> Auto</label>
              <label><input type="radio" name="ato-mode" value="manual" bind:group={atoMode} /> Manual</label>
              <label><input type="radio" name="ato-mode" value="paused" bind:group={atoMode} /> Pause</label>
            </div>
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

          <div class="form-group tank-topup">
            <div class="form-label-row">
              <p class="form-label">Reservoir top-up</p>
              <span class="length-meta">
                Tank {formatMilliliters(coalesceNumber(selectedModule?.ato?.tank_capacity_ml))}
              </span>
            </div>
            <small>Use this after every full refill so the firmware resets its reservoir estimate.</small>
            {#if tankRefillConfirming}
              <div class="reset-actions">
                <p>This cannot be undone. Reset reservoir telemetry to 100%?</p>
                <div class="button-row">
                  <button
                    type="button"
                    class="ghost"
                    on:click={cancelTankRefillConfirmation}
                    disabled={tankRefillBusy}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    class="danger"
                    on:click={triggerTankRefill}
                    disabled={!selectedPhysicalModuleId || tankRefillBusy}
                  >
                    {tankRefillBusy ? 'Marking…' : 'Confirm refill'}
                  </button>
                </div>
              </div>
            {:else}
              <button
                type="button"
                class="danger"
                on:click={startTankRefillConfirmation}
                disabled={!selectedPhysicalModuleId || tankRefillBusy}
              >
                Mark full top-up
              </button>
            {/if}
          </div>
        {/if}

        {#if isRollerView}
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
              disabled={!selectedPhysicalModuleId || mediaProfileBusy}
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
              disabled={!selectedPhysicalModuleId || spoolCalibrationBusy}
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
                    disabled={spoolResetBusy || !selectedPhysicalModuleId}
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
                disabled={!selectedPhysicalModuleId || controlBusy}
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
                      !selectedPhysicalModuleId || spoolCalibrationBusy || spoolCalibrating || spoolCalibrationAwaitingAck
                    }
                  >
                    {spoolCalibrationBusy && !spoolCalibrating ? 'Working…' : 'Request start'}
                  </button>
                  <button
                    type="button"
                    class="success"
                    on:click={finishSpoolCalibration}
                    disabled={!selectedPhysicalModuleId || spoolCalibrationBusy || !spoolCalibrating}
                  >
                    {spoolCalibrationBusy && spoolCalibrating ? 'Working…' : 'Finish & save'}
                  </button>
                  <button
                    type="button"
                    class="danger"
                    on:click={cancelSpoolCalibration}
                    disabled={
                      !selectedPhysicalModuleId || spoolCalibrationBusy || (!spoolCalibrating && !spoolCalibrationAwaitingAck)
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
        {/if}

        <div class="form-group module-purge">
          <p class="form-label">Remove module</p>
          <small>Forget this hardware until it reconnects. Helpful after renaming or replacing controllers.</small>
          {#if purgeConfirming}
            <div class="reset-actions">
              <p>This removes {selectedModule?.label ?? selectedPhysicalModuleId} and clears its usage history.</p>
              <div class="button-row">
                <button type="button" class="ghost" on:click={cancelModulePurge} disabled={purgeBusy}>
                  Cancel
                </button>
                <button
                  type="button"
                  class="danger"
                  on:click={confirmModulePurge}
                  disabled={!selectedPhysicalModuleId || purgeBusy}
                >
                  {purgeBusy ? 'Purging…' : 'Confirm removal'}
                </button>
              </div>
            </div>
          {:else}
            <button
              type="button"
              class="danger"
              on:click={startModulePurge}
              disabled={!selectedPhysicalModuleId || controlBusy}
            >
              Remove module
            </button>
          {/if}
        </div>

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

      {#if isThermistorMismatchAlarm(activeAlarmModal) && activeThermistorAlarmDetails}
        <div class="alarm-meta heater">
          <div class="thermistor-delta">
            <p class="meta-label">Probe delta</p>
            <p class="meta-value">{formatCelsiusValue(activeThermistorAlarmDetails.delta)}</p>
            {#if activeThermistorAlarmDetails.threshold != null}
              <p class="meta-subtext">Threshold {formatCelsiusValue(activeThermistorAlarmDetails.threshold)}</p>
            {/if}
          </div>
          <div class="thermistor-probes">
            <div>
              <p class="meta-label">Primary</p>
              <p class="meta-value">{formatCelsiusValue(activeThermistorAlarmDetails.primary)}</p>
            </div>
            <div>
              <p class="meta-label">Secondary</p>
              <p class="meta-value">{formatCelsiusValue(activeThermistorAlarmDetails.secondary)}</p>
            </div>
          </div>
        </div>
      {:else if activeAlarmModal.meta && Object.keys(activeAlarmModal.meta).length}
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

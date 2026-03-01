<script>
  import { onMount } from 'svelte'
  import LineChart from '$lib/LineChart.svelte'
  import {
    fetchModules,
    updateModuleControls,
    fetchTemperatureHistory,
    fetchCycleHistory,
    fetchSpoolUsageHistory,
    fetchAtoTraceHistory,
  } from '$lib/api'
  import {
    deriveLatestUsageTimestamp,
    createUsageBuckets,
    assignActivationRuns,
    assignSpoolUsage,
    assignAtoUsageFromTrace,
    finalizeBuckets,
    normalizeTemperatureHistorySamples,
    alignSamplesByResolution,
    buildHeaterActivationSeries,
    buildUsageSeriesPreferLevels,
    buildAtoUsageSeries,
  } from '$lib/usageBuckets'

  const ENABLE_TOUCH_DEBUG = Boolean(import.meta.env?.VITE_TOUCH_DEBUG)
  const REFRESH_INTERVAL = 15000
  const SWIPE_THRESHOLD = 45
  const HYSTERESIS_C = 0.2
  const CHART_WINDOWS = [1, 6, 12, 24]
  const TEMP_COLORS = [
    { border: '#4dd0e1', background: 'rgba(77,208,225,0.08)' },
    { border: '#ffd166', background: 'rgba(255,209,102,0.08)' },
  ]
  const DEFAULT_CHART_WINDOW = 12
  const HOUR_MS = 60 * 60 * 1000
  const USAGE_BUCKET_MINUTES = 60
  const USAGE_REFRESH_INTERVAL = 60 * 1000
  const FLOW_ML_PER_MS = 0.0375
  const HEATER_HYSTERESIS_MIN_C = 0.1
  const HEATER_HYSTERESIS_MAX_C = 2.0
  const PROBE_TOLERANCE_MIN_C = 0.1
  const PROBE_TOLERANCE_MAX_C = 3
  const PROBE_TIMEOUT_MIN_S = 5
  const PROBE_TIMEOUT_MAX_S = 300
  const RUNAWAY_DELTA_MIN_C = 0.5
  const RUNAWAY_DELTA_MAX_C = 10
  const MAX_HEATER_ON_MIN_MIN = 1
  const MAX_HEATER_ON_MIN_MAX = 120
  const STUCK_RELAY_DELTA_MIN_C = 0.1
  const STUCK_RELAY_DELTA_MAX_C = 5
  const STUCK_RELAY_WINDOW_MIN_S = 10
  const STUCK_RELAY_WINDOW_MAX_S = 600
  const FRONTEND_CHART_ANCHORS = {
    temperature: 'chart-temperature',
    filter: 'chart-filter',
    ato: 'chart-ato',
  }
  const EMBED_CHART_KEYS = ['temperature', 'filter', 'ato']
  const EMBED_CACHE_BUST = Date.now()
  const EMBED_CHART_LABELS = {
    temperature: { eyebrow: 'Temperature', title: 'Heater history' },
    filter: { eyebrow: 'Filter usage', title: 'Roller media usage' },
    ato: { eyebrow: 'ATO usage', title: 'Reservoir usage' },
  }

  const severityOrder = { critical: 0, warning: 1, info: 2 }
  const RESET_ACTIONS = {
    ato: {
      key: 'ato',
      title: 'Reset ATO',
      body: 'Mark the reservoir as freshly refilled so usage counters return to 100%.',
      confirmLabel: 'Confirm ATO reset',
      toast: 'ATO reset sent to module.',
      payload: { ato_tank_refill: true },
    },
    spool: {
      key: 'spool',
      title: 'Reset Spool',
      body: 'Zero the filter roller usage after swapping media. This clears the usage charts immediately.',
      confirmLabel: 'Confirm spool reset',
      toast: 'Spool reset sent to module.',
      payload: { reset_spool: true },
    },
  }

  const clampPercent = (value) => {
    if (value == null) return null
    const numeric = toNumber(value)
    if (numeric == null) return null
    return Math.max(0, Math.min(100, Math.round(numeric)))
  }

  const formatPercent = (value) => {
    const normalized = clampPercent(value)
    return normalized == null ? '—' : `${normalized}%`
  }

  const describeModuleLabel = (module, fallback) => {
    if (!module) return fallback
    return module.label ?? module.module_id ?? fallback
  }

  const getModuleType = (module = {}) => (module?.module_type ?? '').toString().toLowerCase()

  const mergeTelemetryBlock = (value) => {
    return value && typeof value === 'object' ? value : {}
  }

  const getAtoPayload = (module = {}) => {
    const merged = {
      ...mergeTelemetryBlock(module?.config_payload?.ato),
      ...mergeTelemetryBlock(module?.status_payload?.ato),
    }
    return Object.keys(merged).length ? merged : null
  }

  const getSpoolPayload = (module = {}) => {
    if (module?.spool_state && typeof module.spool_state === 'object') {
      return module.spool_state
    }
    const merged = {
      ...mergeTelemetryBlock(module?.config_payload?.spool),
      ...mergeTelemetryBlock(module?.status_payload?.spool),
    }
    return Object.keys(merged).length ? merged : null
  }

  const computeReservoirStats = (module) => {
    if (!module) return null
    const payload = getAtoPayload(module)
    if (!payload) return { module, percent: null }
    const direct = clampPercent(payload.tank_percent)
    const level = toNumber(payload.tank_level_ml)
    const capacity = toNumber(payload.tank_capacity_ml)
    const derived =
      direct != null
        ? direct
        : level != null && capacity
          ? clampPercent((level / capacity) * 100)
          : null
    return { module, percent: derived }
  }

  const computeSpoolStats = (module) => {
    if (!module) return null
    const payload = getSpoolPayload(module)
    if (!payload) return { module, percent: null }
    if (typeof payload.percent_remaining === 'number') {
      return { module, percent: clampPercent(payload.percent_remaining) }
    }
    const fullEdges = toNumber(payload.full_edges)
    if (fullEdges && fullEdges > 0) {
      const remaining = toNumber(payload.remaining_edges)
      if (remaining != null) {
        return { module, percent: clampPercent((remaining / fullEdges) * 100) }
      }
      const used = toNumber(payload.used_edges)
      if (used != null) {
        return { module, percent: clampPercent(((fullEdges - used) / fullEdges) * 100) }
      }
    }
    return { module, percent: null }
  }

  const deriveAtoMode = (module = {}) => {
    const payload = getAtoPayload(module) ?? {}
    const explicitMode = (payload.mode ?? payload.ato_mode ?? '').toString().toLowerCase()
    if (explicitMode === 'manual' || explicitMode === 'paused' || explicitMode === 'auto') {
      return explicitMode
    }
    if (payload.paused) return 'paused'
    if (payload.manual_mode) return 'manual'
    return 'auto'
  }

  const deriveAtoTankLevelPercent = (module = {}) => {
    const payload = getAtoPayload(module) ?? {}
    const direct = clampPercent(payload.tank_percent)
    if (direct != null) return direct
    const level = toNumber(payload.tank_level_ml)
    const capacity = toNumber(payload.tank_capacity_ml)
    if (level != null && capacity && capacity > 0) {
      return clampPercent((level / capacity) * 100)
    }
    return null
  }

  const deriveAtoUsedMl = (module = {}) => {
    const payload = getAtoPayload(module) ?? {}
    const level = toNumber(payload.tank_level_ml)
    const capacity = toNumber(payload.tank_capacity_ml)
    if (level != null && capacity != null && capacity > 0) {
      return Math.max(0, capacity - level)
    }
    const percent = toNumber(payload.tank_percent)
    if (percent != null && capacity != null && capacity > 0) {
      return Math.max(0, capacity * (1 - Math.min(100, Math.max(0, percent)) / 100))
    }
    return null
  }

  const deriveRollerActivations = (module = {}) => {
    const payload = getSpoolPayload(module) ?? {}
    const count = toNumber(payload.activations ?? payload.activation_count ?? payload.activationCount)
    if (count == null) return null
    return Math.max(0, Math.round(count))
  }

  const deriveRollerUsedMm = (module = {}) => {
    const payload = getSpoolPayload(module) ?? {}
    const totalLengthMm = toNumber(payload.total_length_mm ?? payload.length_mm)
    const fullEdges = toNumber(payload.full_edges)
    const usedEdges = toNumber(payload.used_edges)
    const remainingEdges = toNumber(payload.remaining_edges)

    if (totalLengthMm != null && fullEdges && fullEdges > 0) {
      if (usedEdges != null && usedEdges >= 0) {
        return Math.max(0, (usedEdges / fullEdges) * totalLengthMm)
      }
      if (remainingEdges != null && remainingEdges >= 0) {
        return Math.max(0, totalLengthMm - (remainingEdges / fullEdges) * totalLengthMm)
      }
    }

    const remainingPercent = toNumber(payload.percent_remaining)
    if (totalLengthMm != null && remainingPercent != null) {
      const usedRatio = 1 - Math.min(100, Math.max(0, remainingPercent)) / 100
      return Math.max(0, totalLengthMm * usedRatio)
    }
    return null
  }

  const isPickleSumpModule = (module = {}) => {
    const slug = (module?.module_id ?? '').toString().toLowerCase()
    const label = (module?.label ?? '').toString().toLowerCase()
    if (!slug && !label) return false
    if (slug.includes('pickle') && slug.includes('sump')) return true
    return label.includes('pickle sump')
  }


  const buildHeroStats = (list = []) => {
    if (!Array.isArray(list) || list.length === 0) {
      return { total: 0, online: 0, manual: 0, avgTarget: null, avgCurrent: null, delta: null }
    }
    const total = list.length
    const online = list.filter((module) => (module?.status ?? '').toLowerCase() === 'online').length
    const manual = list.filter((module) => module?.meta?.mode === 'manual').length
    const avgTarget = computeAverage(list, (module) => module?.meta?.target)
    const avgCurrent = computeAverage(list, (module) => module?.meta?.current)
    const delta = avgCurrent != null && avgTarget != null ? Number((avgCurrent - avgTarget).toFixed(2)) : null
    return { total, online, manual, avgTarget, avgCurrent, delta }
  }

  const computeAverage = (list, accessor) => {
    const values = list
      .map((entry) => accessor(entry))
      .map((value) => toNumber(value))
      .filter((value) => value != null)
    if (!values.length) return null
    const sum = values.reduce((acc, value) => acc + value, 0)
    return Number((sum / values.length).toFixed(2))
  }

  const extractActiveAlarms = (moduleList = []) => {
    return moduleList
      .flatMap((module) => {
        const alarms = Array.isArray(module?.alarms) ? module.alarms : []
        return alarms
          .filter((alarm) => alarm && alarm.active !== false)
          .map((alarm) => ({
            ...alarm,
            moduleId: module.module_id,
            moduleLabel: module.label ?? module.module_id,
            severity: (alarm.severity ?? 'warning').toLowerCase(),
            timestamp: coerceTimestamp(alarm.received_at ?? alarm.timestamp_s),
          }))
      })
      .sort((a, b) => {
        const severityDelta = (severityOrder[a.severity] ?? 99) - (severityOrder[b.severity] ?? 99)
        if (severityDelta !== 0) return severityDelta
        return (b.timestamp ?? 0) - (a.timestamp ?? 0)
      })
  }

  const coerceTimestamp = (value) => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value > 1e12 ? value : value * 1000
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Date.parse(value)
      if (!Number.isNaN(parsed)) {
        return parsed
      }
    }
    return 0
  }

  let modules = []
  let moduleCards = []
  let activeIndex = 0
  let activeModule = null
  let loading = true
  let error = ''
  let toast = ''
  let atoModeBusyFor = ''
  let keypadVisible = false
  let keypadModule = null
  let keypadValue = ''
  let keypadError = ''
  let keypadBusy = false
  let swipeStart = null
  let swipeDelta = { x: 0, y: 0 }
  let swipeIntent = null
  let swipeIsActive = false
  let swipeStartTime = 0
  let liveDragOffset = 0
  let activePointerId = null
  let activePointerType = null
  let pointerCaptureActive = false
  let scrollDragStart = null
  let pageDrag = null
  let lastTouchY = null
  let touchVelY = 0
  let momentumRafId = null
  let scrollY = 0
  let refreshTimer = null
  let usageTimer = null
  let usageRequestInFlight = false
  let usageRefreshQueued = false
  let toastTimer = null
  let heroStats = buildHeroStats([])
  let heaterCards = []
  let activeAlarms = []
  let bootstrapping = true
  let mainEl = null
  let scrollContentEl = null
  let temperatureHistory = []
  let historyHydrated = false
  let historyHydrationInFlight = false
  let usageLoading = true
  let usageError = ''
  let atoUsageBuckets = []
  let filterUsageBuckets = []
  let atoUsageSummary = { runs: 0, seconds: 0 }
  let filterUsageSummary = { runs: 0, mediaMm: 0 }
  let spoolTraceEntries = []
  let rawAtoTraceEntries = []
  let atoRunsFallback = []
  let touchDebug = {
    pointerType: '',
    intent: '',
    capturing: false,
    lastEvent: '',
  }
  let debugLines = 'loading…'
  let atoModule = null
  let filterModule = null
  let temperatureHero = { value: '—', detail: 'Awaiting telemetry' }
  let atoHero = { value: '—', detail: 'Reservoir' }
  let filterHero = { value: '—', detail: 'Filter roll' }
  let heroCardModels = []
  let activeChartKey = 'temperature'
  let embeddedChartUrls = {}
  let chartWindowSelections = {
    temperature: DEFAULT_CHART_WINDOW,
    ato: DEFAULT_CHART_WINDOW,
    filter: DEFAULT_CHART_WINDOW,
  }
  let lastTemperatureWindowHours = null
  let confirmDialog = null
  let confirmBusy = false
  let confirmError = ''
  let alarmModal = null
  let alarmActionBusy = false
  let alarmActionError = ''
  let hysteresisVisible = false
  let hysteresisModule = null
  let hysteresisSpanC = HYSTERESIS_C
  let hysteresisBusy = false
  let hysteresisError = ''
  let heaterSafetyVisible = false
  let safetyModule = null
  let safetyBusy = false
  let safetyError = ''
  let safetyProbeToleranceC = 0.7
  let safetyProbeTimeoutS = 45
  let safetyRunawayDeltaC = 2
  let safetyMaxHeaterOnMin = 15
  let safetyStuckRelayDeltaC = 0.5
  let safetyStuckRelayWindowS = 60

  const nudgeWindowResize = () => {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new Event('resize'))
  }

  const buildEmbeddedChartUrl = (chartKey) => {
    const key = EMBED_CHART_KEYS.includes(chartKey) ? chartKey : 'temperature'
    return `/dashboard/index.html?embed=compact&chart=${key}&v=${EMBED_CACHE_BUST}`
  }

  const applyEmbeddedChartIsolation = (frame, chartKey) => {
    const targetKey = EMBED_CHART_KEYS.includes(chartKey) ? chartKey : 'temperature'
    const targetAnchorId = FRONTEND_CHART_ANCHORS[targetKey] ?? FRONTEND_CHART_ANCHORS.temperature
    const doc = frame?.contentDocument
    if (!doc) return

    const styleId = 'pickle-touch-embed-style'
    let styleEl = doc.getElementById(styleId)
    if (!styleEl) {
      styleEl = doc.createElement('style')
      styleEl.id = styleId
      doc.head?.appendChild(styleEl)
    }

    styleEl.textContent = `
      .hero,
      .metrics,
      .module-panel,
      .timeline header,
      .timeline-divider,
      .timeline ul {
        display: none !important;
      }

      .layout.dashboard-view {
        padding: 0.2rem !important;
        gap: 0.2rem !important;
      }

      .modules {
        grid-template-columns: minmax(0, 1fr) !important;
      }

      .timeline {
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        min-height: auto !important;
        padding: 0 !important;
      }

      .chart-anchor {
        display: none !important;
      }

      #${targetAnchorId} {
        display: block !important;
        margin: 0 !important;
      }

      #${targetAnchorId} .chart-widget,
      #${targetAnchorId} .roller-chart {
        gap: 0.3rem !important;
        margin: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
      }

      #${targetAnchorId} .chart-widget__body,
      #${targetAnchorId} .roller-chart .chart-shell {
        border: 0 !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 300px !important;
      }

      #${targetAnchorId} .chart-meta {
        margin-top: 0.3rem !important;
      }

      #${targetAnchorId} .chart-widget__controls .setpoint-control {
        display: none !important;
      }

      #${targetAnchorId} .chart-widget__controls:has(#temperature-setpoint) {
        display: none !important;
      }
    `

    const removeSetpointControls = () => {
      const removableNodes = doc.querySelectorAll(
        '.setpoint-control, label[for="temperature-setpoint"], #temperature-setpoint',
      )
      removableNodes.forEach((node) => {
        if (node.classList?.contains('chart-widget__controls')) {
          node.remove()
          return
        }
        const controlsHost = node.closest?.('.chart-widget__controls')
        if (controlsHost) {
          controlsHost.remove()
          return
        }
        node.remove()
      })
    }

    removeSetpointControls()

    const previousObserver = frame.__pickleSetpointObserver
    if (previousObserver && typeof previousObserver.disconnect === 'function') {
      previousObserver.disconnect()
    }

    const observer = new MutationObserver(() => {
      removeSetpointControls()
    })

    if (doc.body) {
      observer.observe(doc.body, { childList: true, subtree: true })
    }
    frame.__pickleSetpointObserver = observer

    frame.style.height = '420px'
  }

  const handleEmbeddedChartFrameLoad = (event, chartKey) => {
    const frame = event?.currentTarget
    if (!(frame instanceof HTMLIFrameElement)) return
    applyEmbeddedChartIsolation(frame, chartKey)
  }

  const closeModeDropdownsOutside = (event) => {
    if (typeof document === 'undefined') return
    const target = event?.target
    if (!(target instanceof Element)) return
    const openDropdowns = document.querySelectorAll('.mode-dropdown[open]')
    openDropdowns.forEach((dropdown) => {
      if (!dropdown.contains(target)) {
        dropdown.removeAttribute('open')
      }
    })
  }

  onMount(() => {
    document.addEventListener('pointerdown', closeModeDropdownsOutside)
    if (typeof window !== 'undefined') {
      if ('scrollRestoration' in history) {
        history.scrollRestoration = 'manual'
      }
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
      scrollY = 0
    }
    hydrateTemperatureHistory()
    loadModules()
    loadUsage()
    const debugTimer = setInterval(() => {
      debugLines = [
        `sY:${Math.round(scrollY)} mST:${Math.round(mainEl?.scrollTop ?? 0)} max:${getMaxScroll()} mH:${mainEl?.clientHeight ?? 0}/${mainEl?.scrollHeight ?? 0}`,
        `drag:${pageDrag ? 'YES velY='+pageDrag.velY?.toFixed(1) : 'no'}`,
        `last:${touchDebug.lastEvent || '-'} ptr:${activePointerType ?? '-'}`,
        `intent:${swipeIntent ?? '-'} ptr:${activePointerType ?? '-'}`,
        `event:${touchDebug.lastEvent || '-'}`,
        `dX:${swipeDelta.x.toFixed(0)} dY:${swipeDelta.y.toFixed(0)}`,
      ].join('\n')
    }, 250)
    refreshTimer = setInterval(() => loadModules({ quiet: true }), REFRESH_INTERVAL)
    usageTimer = setInterval(() => loadUsage({ quiet: true }), USAGE_REFRESH_INTERVAL)
    requestAnimationFrame(() => {
      nudgeWindowResize()
      setTimeout(nudgeWindowResize, 200)
    })
    mainEl?.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      if (refreshTimer) {
        clearInterval(refreshTimer)
        refreshTimer = null
      }
      if (toastTimer) {
        clearTimeout(toastTimer)
        toastTimer = null
      }
      if (usageTimer) {
        clearInterval(usageTimer)
        usageTimer = null
      }
      document.removeEventListener('pointerdown', closeModeDropdownsOutside)
      mainEl?.removeEventListener('wheel', handleWheel)
      clearInterval(debugTimer)
    }
  })

  $: activeModule = moduleCards[activeIndex] ?? null
  $: heaterCards = moduleCards.filter((module) => module.meta?.hasHeater)
  $: heroStats = buildHeroStats(heaterCards)
  $: activeAlarms = extractActiveAlarms(modules)
  $: if (
    alarmModal &&
    !activeAlarms.some(
      (alarm) =>
        alarm.moduleId === alarmModal.moduleId &&
        alarm.code === alarmModal.code &&
        alarm.timestamp === alarmModal.timestamp,
    )
  ) {
    closeAlarmModal()
  }
  $: atoModule =
    modules.find((module) => getModuleType(module) === 'ato') ??
    modules.find((module) => Boolean(getAtoPayload(module))) ??
    null
  $: filterModule =
    modules.find((module) => getModuleType(module) === 'filter') ??
    modules.find((module) => Boolean(getSpoolPayload(module))) ??
    null
  $: temperatureHero = (() => {
    const leader = heaterCards[0]
    if (leader?.meta?.current != null) {
      return {
        value: formatTemp(leader.meta.current),
        detail: describeModuleLabel(leader, 'Primary heater'),
      }
    }
    if (heroStats.avgCurrent != null) {
      return {
        value: formatTemp(heroStats.avgCurrent),
        detail: 'Fleet average',
      }
    }
    return {
      value: '—',
      detail: 'Awaiting heater telemetry',
    }
  })()
  $: atoHero = (() => {
    if (!atoModule) {
      return { value: '—', detail: 'Reservoir offline' }
    }
    const stats = computeReservoirStats(atoModule)
    return {
      value: stats?.percent != null ? formatPercent(stats.percent) : '—',
      detail: describeModuleLabel(atoModule, 'ATO reservoir'),
    }
  })()
  $: filterHero = (() => {
    if (!filterModule) {
      return { value: '—', detail: 'Filter idle' }
    }
    const stats = computeSpoolStats(filterModule)
    return {
      value: stats?.percent != null ? formatPercent(stats.percent) : '—',
      detail: describeModuleLabel(filterModule, 'Filter roll'),
    }
  })()
  $: temperatureWindowHours = Math.max(1, chartWindowSelections.temperature ?? DEFAULT_CHART_WINDOW)
  $: temperatureWindowMs = temperatureWindowHours * HOUR_MS
  $: usageWindowHours = {
    ato: Math.max(1, chartWindowSelections.ato ?? DEFAULT_CHART_WINDOW),
    filter: Math.max(1, chartWindowSelections.filter ?? DEFAULT_CHART_WINDOW),
  }
  $: latestTemperatureSample = temperatureHistory.length ? temperatureHistory[temperatureHistory.length - 1] : null
  $: atoChartActivationCount = atoUsageBuckets.reduce(
    (total, bucket) => total + Math.max(0, toNumber(bucket?.count) ?? 0),
    0,
  )
  $: atoChartWaterUsedMl = atoUsageBuckets.reduce(
    (total, bucket) => total + Math.max(0, toNumber(bucket?.usage) ?? 0),
    0,
  )
  $: atoChartAverageMl = atoChartActivationCount > 0 ? atoChartWaterUsedMl / atoChartActivationCount : null
  $: filterChartActivationCount =
    toNumber(filterModule?.meta?.rollerActivations) ??
    filterUsageBuckets.reduce((total, bucket) => total + Math.max(0, toNumber(bucket?.count) ?? 0), 0)
  $: filterChartMediaUsedMm =
    toNumber(filterModule?.meta?.rollerUsedMm) ??
    filterUsageBuckets.reduce((total, bucket) => total + Math.max(0, toNumber(bucket?.usage) ?? 0), 0)
  $: filterChartAverageMediaMm =
    filterChartActivationCount > 0 ? filterChartMediaUsedMm / filterChartActivationCount : null
  $: heroCardModels = [
    { key: 'temperature', label: 'Temperature', value: temperatureHero.value, detail: temperatureHero.detail },
    { key: 'ato', label: 'ATO remaining', value: atoHero.value, detail: atoHero.detail },
    { key: 'filter', label: 'Filter remaining', value: filterHero.value, detail: filterHero.detail },
  ]
  $: embeddedChartUrls = EMBED_CHART_KEYS.reduce((acc, key) => {
    acc[key] = buildEmbeddedChartUrl(key)
    return acc
  }, {})
  $: activeChartView = (() => {
    if (activeChartKey === 'ato') {
      const subtitle = usageError
        ? usageError
        : usageLoading && !atoUsageBuckets.length
          ? 'Syncing usage history…'
          : `Rolling ${usageWindowHours.ato}-hour window`
      return {
        key: 'ato',
        type: 'usage',
        eyebrow: 'ATO usage',
        title: `Last ${usageWindowHours.ato} hours`,
        subtitle,
        detail: 'Bars = activations per hour · line = water used (mL)',
        buckets: atoUsageBuckets,
        barColor: '#7bffdb',
        lineColor: '#66ccff',
        summary: [
          { label: 'ATO activations', value: atoChartActivationCount ?? 0 },
          {
            label: 'Avg water per activation',
            value: atoChartAverageMl != null ? formatMilliliters(atoChartAverageMl) : '—',
          },
          { label: 'Water used', value: formatMilliliters(atoChartWaterUsedMl) },
        ],
      }
    }
    if (activeChartKey === 'filter') {
      const subtitle = usageError
        ? usageError
        : usageLoading && !filterUsageBuckets.length
          ? 'Syncing usage history…'
          : `Rolling ${usageWindowHours.filter}-hour window`
      return {
        key: 'filter',
        type: 'usage',
        eyebrow: 'Filter usage',
        title: `Last ${usageWindowHours.filter} hours`,
        subtitle,
        detail: 'Bars = advances per hour · line = media consumed (mm)',
        buckets: filterUsageBuckets,
        barColor: '#ffdb6e',
        lineColor: '#ff9f6e',
        summary: [
          { label: 'Activations (spool)', value: filterChartActivationCount ?? '—' },
          {
            label: 'Avg media use',
            value: filterChartAverageMediaMm != null ? formatMediaLength(filterChartAverageMediaMm) : '—',
          },
          { label: 'Total media used', value: formatMediaLength(filterChartMediaUsedMm) },
        ],
      }
    }
    return {
      key: 'temperature',
      type: 'temperature',
      eyebrow: 'Temperature',
      title: `Past ${temperatureWindowHours} hours`,
      subtitle: `Rolling ${temperatureWindowHours}-hour history updates every sync`,
      detail: 'Tap hero cards to switch data views',
      samples: temperatureHistory,
      summary: [
        { label: 'Last sample', value: formatLastSeen(latestTemperatureSample?.timestamp) },
        { label: 'Temp 1', value: formatTemp(latestTemperatureSample?.thermistors?.[0]?.value) },
        { label: 'Temp 2', value: formatTemp(latestTemperatureSample?.thermistors?.[1]?.value) },
        { label: 'Heater', value: latestTemperatureSample?.heaterOn ? 'Heating' : 'Idle' },
      ],
    }
  })()

  $: temperatureChartDatasets = (() => {
    const cutoff = Date.now() - temperatureWindowMs
    const inWindow = temperatureHistory.filter((s) => s.timestamp >= cutoff)
    const samples = inWindow.length ? inWindow : temperatureHistory.slice(-240)
    if (!samples.length) return { datasets: [], yMin: undefined, yMax: undefined }
    const series = [
      { label: 'Temp 1', points: [] },
      { label: 'Temp 2', points: [] },
    ]
    const values = []
    samples.forEach((sample) => {
      const probes = Array.isArray(sample.thermistors) ? sample.thermistors : []
      probes.forEach((probe, idx) => {
        if (typeof probe.value !== 'number' || isNaN(probe.value)) return
        values.push(probe.value)
        if (series[idx]) series[idx].points.push({ x: sample.timestamp, y: probe.value })
      })
    })
    if (!values.length) return { datasets: [], yMin: undefined, yMax: undefined }
    const range = { min: 20, max: 30, padding: 1 }
    const datasets = []
    series.filter((s) => s.points.length).forEach((s, i) => {
      datasets.push({
        label: s.label,
        data: s.points,
        borderColor: TEMP_COLORS[i % TEMP_COLORS.length].border,
        backgroundColor: TEMP_COLORS[i % TEMP_COLORS.length].background,
        borderWidth: 2.6,
        fill: false,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 2,
        spanGaps: true,
      })
    })
    const activationSamples = samples.map((s) => ({ ...s, heaterState: s.heaterOn }))
    const heaterSeries = buildHeaterActivationSeries(activationSamples, range, { insetRatio: 0.2 })
    if (heaterSeries.length) {
      datasets.push({
        label: 'Activation',
        data: heaterSeries,
        borderColor: 'rgba(246,195,67,0.95)',
        backgroundColor: 'rgba(246,195,67,0.15)',
        borderWidth: 2.3,
        fill: false,
        stepped: true,
        pointRadius: 0,
        spanGaps: false,
        tension: 0,
      })
    }
    return { datasets, yMin: range.min, yMax: range.max }
  })()

  $: filterChartDatasets = (() => {
    if (!spoolTraceEntries.length) return []
    const cutoff = Date.now() - usageWindowHours.filter * HOUR_MS
    const deltaEntries = spoolTraceEntries
      .map((e) => ({
        timestamp: coerceTimestamp(e.recorded_at),
        deltaMm: toNumber(e.delta_mm) ?? 0,
      }))
      .filter((e) => e.timestamp > 0 && e.deltaMm > 0)
    const series = buildUsageSeriesPreferLevels({
      levelSamples: [],
      deltaEntries,
      cutoff,
      deltaValueKey: 'deltaMm',
      tailLimit: 500,
    })
    if (!series.points.length) return []
    return [
      {
        label: 'Media used',
        data: series.points.map((p) => ({ x: p.ts, y: p.value })),
        borderColor: 'rgba(72,229,194,0.9)',
        backgroundColor: 'rgba(72,229,194,0.15)',
        borderWidth: 2.6,
        fill: false,
        tension: 0.32,
        pointRadius: 0,
        pointHoverRadius: 2,
      },
    ]
  })()

  $: atoChartDatasets = (() => {
    if (!rawAtoTraceEntries.length && !atoRunsFallback.length) return []
    const cutoff = Date.now() - usageWindowHours.ato * HOUR_MS
    const tankSamples = rawAtoTraceEntries
      .map((e) => ({
        timestamp: toNumber(e.timestamp) ?? coerceTimestamp(e.recorded_at),
        usedMl: toNumber(e.used_ml ?? e.usedMl) ?? 0,
      }))
      .filter((e) => e.timestamp > 0)
    const points = buildAtoUsageSeries({
      tankSamples,
      levelSamples: [],
      fallbackRuns: atoRunsFallback,
      cutoff,
      resetThreshold: 100,
      runtimeMsToMilliliters: (ms) => ms * FLOW_ML_PER_MS,
    })
    if (!points.length) return []
    return [
      {
        label: 'Water used',
        data: points.map((p) => ({ x: p.ts, y: p.used })),
        borderColor: 'rgba(95,179,255,0.85)',
        backgroundColor: 'rgba(95,179,255,0.15)',
        borderWidth: 2.6,
        fill: false,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 2,
      },
    ]
  })()

  $: confirmContent = confirmDialog ? RESET_ACTIONS[confirmDialog.type] ?? null : null

  async function loadModules(options = {}) {
    const quiet = options.quiet ?? false
    if (!quiet) {
      loading = true
    }
    try {
      const response = await fetchModules()
      modules = Array.isArray(response) ? response : []
      moduleCards = normalizeModules(modules)
      recordTemperatureSnapshot(moduleCards)
      if (!historyHydrated && !historyHydrationInFlight) {
        const primaryHeater = moduleCards.find((module) => module.meta?.hasHeater)
        hydrateTemperatureHistory(primaryHeater?.module_id)
      }
      const cardCount = moduleCards.length
      if (activeIndex >= cardCount) {
        activeIndex = Math.max(cardCount - 1, 0)
      }
      error = cardCount ? '' : 'No modules detected yet.'
    } catch (err) {
      error = err?.message ?? 'Unable to load modules.'
    } finally {
      if (!quiet) {
        loading = false
      }
      if (bootstrapping) {
        bootstrapping = false
      }
    }
  }

  async function loadUsage(options = {}) {
    if (usageRequestInFlight) {
      usageRefreshQueued = true
      return
    }
    const overrides = options.windowHours ?? {}
    const windowAto = Math.max(1, overrides.ato ?? usageWindowHours.ato)
    const windowFilter = Math.max(1, overrides.filter ?? usageWindowHours.filter)
    const fetchWindow = Math.max(windowAto, windowFilter)
    const quiet = options.quiet ?? false
    usageRequestInFlight = true
    if (!quiet || (!atoUsageBuckets.length && !filterUsageBuckets.length)) {
      usageLoading = true
    }
    try {
      const [cyclePayload, spoolPayload, atoTracePayload] = await Promise.all([
        fetchCycleHistory(fetchWindow),
        fetchSpoolUsageHistory({ windowHours: fetchWindow, limit: Math.max(500, fetchWindow * 12) }),
        fetchAtoTraceHistory({ windowHours: fetchWindow, limit: Math.max(500, fetchWindow * 20) }),
      ])

      const cycleData = cyclePayload ?? {}
      const spoolEntries = Array.isArray(spoolPayload) ? spoolPayload : []
      const atoTraceEntries = Array.isArray(atoTracePayload) ? [...atoTracePayload] : []
      if (!atoTraceEntries.length) {
        const liveUsedMl = deriveAtoUsedMl(atoModule)
        if (liveUsedMl != null) {
          atoTraceEntries.push({
            timestamp: Date.now(),
            module_id: atoModule?.module_id,
            used_ml: liveUsedMl,
          })
        }
      }
      const atoAnchorTimestamp = deriveLatestUsageTimestamp(cycleData.ato_runs ?? [], atoTraceEntries)
      const filterAnchorTimestamp = deriveLatestUsageTimestamp(
        cycleData.roller_runs ?? [],
        spoolEntries,
      )

      const atoStats = cycleData.ato_stats ?? {}
      const rollerStats = cycleData.roller_stats ?? {}

      const atoBucketsMeta = createUsageBuckets({
        windowHours: windowAto,
        anchorTimestamp: atoAnchorTimestamp,
      })
      assignActivationRuns(atoBucketsMeta, cycleData.ato_runs ?? [], { usageScale: 0 })
      const appliedTraceUsage = assignAtoUsageFromTrace(atoBucketsMeta, atoTraceEntries)
      if (!appliedTraceUsage) {
        assignActivationRuns(atoBucketsMeta, cycleData.ato_runs ?? [], { usageScale: FLOW_ML_PER_MS })
      }
      atoUsageBuckets = finalizeBuckets(atoBucketsMeta)

      const filterBucketsMeta = createUsageBuckets({
        windowHours: windowFilter,
        anchorTimestamp: filterAnchorTimestamp,
      })
      assignActivationRuns(filterBucketsMeta, cycleData.roller_runs ?? [], { usageScale: 0 })
      assignSpoolUsage(filterBucketsMeta, spoolEntries)
      filterUsageBuckets = finalizeBuckets(filterBucketsMeta)

      // Store raw entries for native Chart.js rendering
      spoolTraceEntries = spoolEntries
      rawAtoTraceEntries = [...atoTraceEntries]
      atoRunsFallback = cycleData.ato_runs ?? []

      atoUsageSummary = {
        runs: atoStats.count ?? 0,
        seconds: Math.round((atoStats.total_duration_ms ?? 0) / 1000),
      }

      const mediaMm = spoolEntries.reduce(
        (total, entry) => total + Math.max(0, toNumber(entry?.delta_mm) ?? 0),
        0,
      )

      filterUsageSummary = {
        runs: rollerStats.count ?? 0,
        mediaMm,
      }

      usageError = ''
    } catch (err) {
      usageError = err?.message ?? 'Unable to load usage metrics.'
    } finally {
      usageLoading = false
      usageRequestInFlight = false
      if (usageRefreshQueued) {
        usageRefreshQueued = false
        loadUsage({ quiet: true })
      }
    }
  }

  const changeChartWindow = (key, hours) => {
    const normalized = CHART_WINDOWS.includes(hours) ? hours : null
    if (!normalized) return
    const current = chartWindowSelections[key] ?? DEFAULT_CHART_WINDOW
    if (current === normalized) return
    chartWindowSelections = { ...chartWindowSelections, [key]: normalized }
    if (key === 'temperature') {
      historyHydrated = false
      lastTemperatureWindowHours = null
      temperatureHistory = []
      const primaryHeater = moduleCards.find((module) => module.meta?.hasHeater)
      hydrateTemperatureHistory(primaryHeater?.module_id, { force: true, windowHours: normalized })
    } else if (key === 'ato' || key === 'filter') {
      usageLoading = true
      loadUsage({ quiet: true, windowHours: { [key]: normalized } })
    }
  }

  const normalizeModules = (list = []) => {
    const enriched = (list ?? []).map(enrichModule)
    return enriched.sort((a, b) => {
      const aHeater = a.meta?.hasHeater ? 1 : 0
      const bHeater = b.meta?.hasHeater ? 1 : 0
      if (aHeater !== bHeater) {
        return bHeater - aHeater
      }
      const aLabel = (a.label ?? a.module_id ?? '').toString().toLowerCase()
      const bLabel = (b.label ?? b.module_id ?? '').toString().toLowerCase()
      return aLabel.localeCompare(bLabel)
    })
  }

  const isHeaterCandidate = (module = {}) => {
    const kind = (module?.module_type ?? '').toLowerCase()
    if (kind.includes('heater')) return true
    const payload = module?.status_payload
    if (payload && typeof payload === 'object') {
      const subsystemHeater = getHeaterSubsystemEntry(payload)
      if (subsystemHeater) return true
      if (payload.heater && typeof payload.heater === 'object') return true
      if (Array.isArray(payload.heaters) && payload.heaters.some((entry) => entry && typeof entry === 'object')) {
        return true
      }
    }
    return false
  }

  const getHeaterSubsystemEntry = (statusPayload = {}) => {
    if (!statusPayload || typeof statusPayload !== 'object') return null
    if (!Array.isArray(statusPayload.subsystems)) return null
    return (
      statusPayload.subsystems.find(
        (entry) =>
          entry &&
          typeof entry === 'object' &&
          ((entry.kind ?? '').toString().toLowerCase() === 'heater' ||
            (entry.key ?? '').toString().toLowerCase() === 'heater'),
      ) ?? null
    )
  }

  const enrichModule = (module = {}) => {
    const statusPayload = (module?.status_payload && typeof module.status_payload === 'object')
      ? module.status_payload
      : {}
    const configPayload = (module?.config_payload && typeof module.config_payload === 'object')
      ? module.config_payload
      : {}
    const heaterCapable = isHeaterCandidate(module)
    const heaterSnapshot = heaterCapable ? pickHeater(statusPayload) : null
    const thermometers = heaterSnapshot ? extractThermistors(heaterSnapshot) : []
    const targets = deriveTargetBand(heaterSnapshot ?? {}, configPayload?.heater)
    const current = heaterCapable
      ? thermometers[0]?.value ?? toNumber(heaterSnapshot?.primary_temp_c) ?? toNumber(heaterSnapshot?.average_temp_c)
      : null
    const duty = heaterCapable ? deriveHeaterDutyPercent(heaterSnapshot) : null
    const mode = heaterCapable ? deriveMode(statusPayload, heaterSnapshot) : null

    return {
      ...module,
      status_payload: statusPayload,
      config_payload: configPayload,
      heater: heaterSnapshot,
      thermometers,
      meta: {
        ...targets,
        current,
        duty,
        mode,
        atoMode: deriveAtoMode(module),
        atoTankLevelPercent: deriveAtoTankLevelPercent(module),
        rollerActivations: deriveRollerActivations(module),
        rollerUsedMm: deriveRollerUsedMm(module),
        hasHeater: heaterCapable,
      },
    }
  }

  const pickHeater = (statusPayload = {}) => {
    if (!statusPayload || typeof statusPayload !== 'object') return null

    const direct = statusPayload.heater && typeof statusPayload.heater === 'object'
      ? statusPayload.heater
      : null
    const collection = Array.isArray(statusPayload.heaters)
      ? statusPayload.heaters.find((entry) => entry && typeof entry === 'object') ?? null
      : null
    const subsystem = getHeaterSubsystemEntry(statusPayload)

    if (!direct && !collection && !subsystem) {
      return null
    }

    return {
      ...(subsystem ?? {}),
      ...(collection ?? {}),
      ...(direct ?? {}),
      setpoints: {
        ...((subsystem?.setpoints ?? {})),
        ...((collection?.setpoints ?? {})),
        ...((direct?.setpoints ?? {})),
      },
    }
  }

  const extractThermistors = (heater) => {
    if (!heater || typeof heater !== 'object') return []
    const pools = []
    if (Array.isArray(heater.sensors)) pools.push(...heater.sensors)
    if (Array.isArray(heater.thermistors)) pools.push(...heater.thermistors)
    if (Array.isArray(heater.thermistors_c)) pools.push(...heater.thermistors_c)
    if (Array.isArray(heater.temps_c)) pools.push(...heater.temps_c)
    if (!pools.length) {
      const fallback = toNumber(heater.primary_temp_c ?? heater.average_temp_c)
      if (fallback != null) {
        return [{ label: 'Primary', value: Number(fallback.toFixed(2)) }]
      }
      return []
    }
    return pools
      .map((entry, index) => {
        if (typeof entry === 'number' && Number.isFinite(entry)) {
          return { label: `Probe ${index + 1}`, value: Number(entry.toFixed(2)) }
        }
        if (entry && typeof entry === 'object') {
          const rawReading = toNumber(entry.value ?? entry.c ?? entry.temp ?? entry.temp_c)
          if (rawReading == null) return null
          const unit = (entry.unit ?? entry.units ?? '').toString().toLowerCase()
          const reading = unit === 'f' || unit === '°f'
            ? (rawReading - 32) * (5 / 9)
            : rawReading
          if (reading == null) return null
          return {
            label: entry.label ?? entry.sensor ?? `Probe ${index + 1}`,
            value: Number(reading.toFixed(2)),
          }
        }
        return null
      })
      .filter(Boolean)
  }

  const deriveHeaterDutyPercent = (heater = {}) => {
    if (!heater || typeof heater !== 'object') return null
    const candidates = [
      heater?.setpoints?.duty_cycle_percent,
      heater?.duty_cycle_percent,
      heater?.duty_cycle,
      heater?.duty,
      heater?.output,
    ]
    if (Array.isArray(heater?.sensors)) {
      const sensorDuty = heater.sensors.find((entry) => {
        const label = (entry?.label ?? '').toString().toLowerCase()
        return label.includes('duty')
      })
      if (sensorDuty) {
        candidates.unshift(sensorDuty.value)
      }
    }

    for (const candidate of candidates) {
      const numeric = toNumber(candidate)
      if (numeric == null) continue
      const normalized = numeric > 1 ? numeric : numeric * 100
      if (Number.isFinite(normalized)) {
        return Math.max(0, Math.min(100, Math.round(normalized)))
      }
    }
    return null
  }

  const deriveTargetBand = (heater = {}, configHeater = {}) => {
    const min = toNumber(
      heater?.setpoint_min_c ??
        heater?.setpoints?.setpoint_min_c ??
        heater?.setpoint_low_c ??
        heater?.minimum_c ??
        configHeater?.setpoint_min_c ??
        configHeater?.setpoints?.setpoint_min_c,
    )
    const max = toNumber(
      heater?.setpoint_max_c ??
        heater?.setpoints?.setpoint_max_c ??
        heater?.setpoint_high_c ??
        heater?.maximum_c ??
        configHeater?.setpoint_max_c ??
        configHeater?.setpoints?.setpoint_max_c,
    )
    let target = toNumber(
      heater?.setpoint_c ??
        heater?.setpoints?.setpoint_c ??
        heater?.target_c ??
        configHeater?.setpoint_c ??
        configHeater?.setpoints?.setpoint_c ??
        configHeater?.target_c ??
        heater?.average_temp_c ??
        heater?.primary_temp_c,
    )
    if (target == null && min != null && max != null) {
      target = Number(((min + max) / 2).toFixed(1))
    }
    return { target, min, max }
  }

  const clampValue = (value, min, max, decimals = null) => {
    const numeric = toNumber(value)
    if (numeric == null) return null
    const bounded = Math.min(Math.max(numeric, min), max)
    if (typeof decimals === 'number') {
      return Number(bounded.toFixed(decimals))
    }
    return Math.round(bounded)
  }

  const readHeaterSetpoint = (module = {}) => {
    const heater = module?.heater ?? {}
    const setpoints = heater?.setpoints ?? {}
    return {
      probeToleranceC: toNumber(setpoints.probe_tolerance_c ?? heater.probe_tolerance_c),
      probeTimeoutS: toNumber(setpoints.probe_timeout_s ?? heater.probe_timeout_s),
      runawayDeltaC: toNumber(setpoints.runaway_delta_c ?? heater.runaway_delta_c),
      maxHeaterOnMin: toNumber(setpoints.max_heater_on_min ?? heater.max_heater_on_min),
      stuckRelayDeltaC: toNumber(setpoints.stuck_relay_delta_c ?? heater.stuck_relay_delta_c),
      stuckRelayWindowS: toNumber(setpoints.stuck_relay_window_s ?? heater.stuck_relay_window_s),
    }
  }

  const readHysteresisSpan = (module = {}) => {
    const heater = module?.heater ?? {}
    const setpoints = heater?.setpoints ?? {}
    const direct = toNumber(setpoints.hysteresis_span_c ?? heater.hysteresis_span_c)
    if (direct != null) return direct
    const half = toNumber(setpoints.hysteresis_half_c ?? heater.hysteresis_half_c)
    if (half != null) return half * 2
    const min = toNumber(setpoints.setpoint_min_c ?? heater.setpoint_min_c ?? module?.meta?.min)
    const max = toNumber(setpoints.setpoint_max_c ?? heater.setpoint_max_c ?? module?.meta?.max)
    if (min != null && max != null && max >= min) {
      return Number((max - min).toFixed(2))
    }
    return HYSTERESIS_C
  }

  const hydrateSafetyControls = (module) => {
    const source = readHeaterSetpoint(module)
    safetyProbeToleranceC = clampValue(source.probeToleranceC ?? 0.7, PROBE_TOLERANCE_MIN_C, PROBE_TOLERANCE_MAX_C, 1) ?? 0.7
    safetyProbeTimeoutS = clampValue(source.probeTimeoutS ?? 45, PROBE_TIMEOUT_MIN_S, PROBE_TIMEOUT_MAX_S) ?? 45
    safetyRunawayDeltaC = clampValue(source.runawayDeltaC ?? 2, RUNAWAY_DELTA_MIN_C, RUNAWAY_DELTA_MAX_C, 1) ?? 2
    safetyMaxHeaterOnMin = clampValue(source.maxHeaterOnMin ?? 15, MAX_HEATER_ON_MIN_MIN, MAX_HEATER_ON_MIN_MAX) ?? 15
    safetyStuckRelayDeltaC =
      clampValue(source.stuckRelayDeltaC ?? 0.5, STUCK_RELAY_DELTA_MIN_C, STUCK_RELAY_DELTA_MAX_C, 1) ?? 0.5
    safetyStuckRelayWindowS =
      clampValue(source.stuckRelayWindowS ?? 60, STUCK_RELAY_WINDOW_MIN_S, STUCK_RELAY_WINDOW_MAX_S) ?? 60
  }

  const openHeaterSafety = (module) => {
    if (!module?.meta?.hasHeater) return
    safetyModule = module
    hydrateSafetyControls(module)
    safetyError = ''
    heaterSafetyVisible = true
  }

  const openHysterisisPanel = (module) => {
    if (!module?.meta?.hasHeater) return
    hysteresisModule = module
    hysteresisSpanC =
      clampValue(readHysteresisSpan(module), HEATER_HYSTERESIS_MIN_C, HEATER_HYSTERESIS_MAX_C, 2) ?? HYSTERESIS_C
    hysteresisError = ''
    hysteresisVisible = true
  }

  const closeHysterisisPanel = () => {
    hysteresisVisible = false
    hysteresisModule = null
    hysteresisBusy = false
    hysteresisError = ''
  }

  const saveHysterisis = async () => {
    if (!hysteresisModule?.module_id || hysteresisBusy) return
    const normalized =
      clampValue(hysteresisSpanC, HEATER_HYSTERESIS_MIN_C, HEATER_HYSTERESIS_MAX_C, 2) ?? HYSTERESIS_C
    hysteresisBusy = true
    hysteresisError = ''
    try {
      await updateModuleControls(hysteresisModule.module_id, {
        heater_hysteresis_span_c: normalized,
      })
      showToast(`${hysteresisModule.label ?? hysteresisModule.module_id} hysteresis set to ${normalized.toFixed(2)}°C`)
      closeHysterisisPanel()
      await loadModules({ quiet: true })
    } catch (err) {
      hysteresisError = err?.message ?? 'Unable to update hysteresis'
    } finally {
      hysteresisBusy = false
    }
  }

  const closeHeaterSafety = () => {
    heaterSafetyVisible = false
    safetyModule = null
    safetyBusy = false
    safetyError = ''
  }

  const saveHeaterSafety = async () => {
    if (!safetyModule?.module_id || safetyBusy) return
    safetyBusy = true
    safetyError = ''
    try {
      await updateModuleControls(safetyModule.module_id, {
        probe_tolerance_c: Number(safetyProbeToleranceC),
        probe_timeout_s: Number(safetyProbeTimeoutS),
        runaway_delta_c: Number(safetyRunawayDeltaC),
        max_heater_on_min: Number(safetyMaxHeaterOnMin),
        stuck_relay_delta_c: Number(safetyStuckRelayDeltaC),
        stuck_relay_window_s: Number(safetyStuckRelayWindowS),
      })
      showToast(`${safetyModule.label ?? safetyModule.module_id} safety settings updated`)
      closeHeaterSafety()
      await loadModules({ quiet: true })
    } catch (err) {
      safetyError = err?.message ?? 'Unable to update heater safety settings'
    } finally {
      safetyBusy = false
    }
  }

  const focusModuleById = (moduleId) => {
    if (!moduleId) return
    const index = moduleCards.findIndex((module) => module.module_id === moduleId)
    if (index >= 0) {
      activeIndex = index
    }
  }

  const openAlarmModal = (alarm) => {
    if (!alarm) return
    alarmModal = alarm
    alarmActionBusy = false
    alarmActionError = ''
  }

  const closeAlarmModal = () => {
    alarmModal = null
    alarmActionBusy = false
    alarmActionError = ''
  }

  const snoozeAlarmFromModal = async () => {
    const moduleId = alarmModal?.moduleId
    if (!moduleId || alarmActionBusy) return
    alarmActionBusy = true
    alarmActionError = ''
    try {
      await updateModuleControls(moduleId, { alarm_snooze: true })
      showToast(`${alarmModal.moduleLabel ?? moduleId} alarm snoozed`)
      closeAlarmModal()
      await loadModules({ quiet: true })
    } catch (err) {
      alarmActionError = err?.message ?? 'Unable to snooze alarm'
    } finally {
      alarmActionBusy = false
    }
  }

  const inspectAlarmModule = () => {
    if (!alarmModal?.moduleId) return
    focusModuleById(alarmModal.moduleId)
    closeAlarmModal()
  }

  const deriveMode = (statusPayload = {}, heater = {}) => {
    if (heater && typeof heater.mode === 'string' && heater.mode.trim()) {
      return heater.mode.trim().toLowerCase()
    }
    const ato = statusPayload?.ato ?? {}
    if (ato.manual_mode) return 'manual'
    if (ato.paused) return 'paused'
    return 'auto'
  }

  const toNumber = (value) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() !== '') {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
    return null
  }

  const formatTemp = (value) => {
    if (value == null) return '—'
    return `${Number(value).toFixed(1)}°C`
  }

  const formatLastSeen = (value) => {
    const timestamp = coerceTimestamp(value)
    if (!timestamp) return '—'
    const delta = Date.now() - timestamp
    if (delta < 60_000) return 'Just now'
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(timestamp))
    } catch (err) {
      return new Date(timestamp).toLocaleString()
    }
  }

  const determineHeaterActive = (module = {}) => {
    const heater = module.heater ?? {}
    const candidates = [heater.output, heater.power, heater.duty, heater.duty_cycle]
    for (const candidate of candidates) {
      const numeric = toNumber(candidate)
      if (numeric != null) {
        return numeric > 0.01
      }
    }
    if (typeof heater.state === 'string') {
      const normalized = heater.state.toLowerCase()
      if (normalized.includes('heat') || normalized === 'on' || normalized === 'active') {
        return true
      }
    }
    const duty = toNumber(module.meta?.duty)
    return duty != null ? duty > 0 : false
  }

  const parseTimestampMs = (value) => {
    const numeric = toNumber(value)
    if (numeric != null) return numeric
    if (typeof value === 'string' && value.trim()) {
      const parsed = Date.parse(value)
      if (!Number.isNaN(parsed)) {
        return parsed
      }
    }
    return null
  }

  const formatDurationShort = (seconds) => {
    const totalSeconds = Math.round(Math.max(0, seconds ?? 0))
    if (totalSeconds === 0) return '0s'
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const secs = totalSeconds % 60
    const parts = []
    if (hours) parts.push(`${hours}h`)
    if (minutes) parts.push(`${minutes}m`)
    if (!hours && secs && parts.length < 2) parts.push(`${secs}s`)
    if (!parts.length) return `${secs}s`
    return parts.join(' ')
  }

  const formatMediaLength = (millimeters) => {
    const value = Number(millimeters) || 0
    if (value >= 1000) {
      return `${(value / 1000).toFixed(1)} m`
    }
    if (value >= 10) {
      return `${(value / 10).toFixed(1)} cm`
    }
    return `${Math.round(value)} mm`
  }

  const formatMilliliters = (value) => {
    const numeric = toNumber(value)
    if (numeric == null) return '—'
    if (numeric >= 1000) {
      const liters = numeric / 1000
      const decimals = liters >= 10 || Number.isInteger(liters) ? 0 : 1
      return `${liters.toFixed(decimals)} L`
    }
    return `${Math.round(numeric)} ml`
  }

  const hydrateTemperatureHistory = async (preferredModuleId, options = {}) => {
    const force = options.force ?? false
    const targetWindowHours = Math.max(1, options.windowHours ?? temperatureWindowHours)
    if (!force && historyHydrationInFlight) return
    if (!force && historyHydrated && lastTemperatureWindowHours === targetWindowHours) return
    historyHydrationInFlight = true
    try {
      const windowMinutes = targetWindowHours * 60
      const windowMs = targetWindowHours * HOUR_MS
      const limit = Math.ceil(windowMs / REFRESH_INTERVAL) + 120
      const params = { windowMinutes, limit }
      if (preferredModuleId) {
        params.moduleId = preferredModuleId
      }
      const history = await fetchTemperatureHistory(params)
      const normalized = normalizeTemperatureHistorySamples(history)
      const aligned = alignSamplesByResolution(normalized, REFRESH_INTERVAL)
      if (aligned.length) {
        temperatureHistory = aligned
        historyHydrated = true
        lastTemperatureWindowHours = targetWindowHours
      } else if (force) {
        temperatureHistory = []
      }
    } catch (err) {
      console.warn('Unable to load historical temperature samples', err)
    } finally {
      historyHydrationInFlight = false
    }
  }

  const logTouchDebug = (payload = {}) => {
    touchDebug = {
      pointerType: payload.pointerType ?? touchDebug.pointerType,
      intent: payload.intent ?? touchDebug.intent,
      capturing: payload.capturing ?? touchDebug.capturing,
      lastEvent: payload.lastEvent ?? touchDebug.lastEvent,
    }
  }

  const recordTemperatureSnapshot = (modules = []) => {
    if (!Array.isArray(modules) || !modules.length) return
    const target = modules.find((module) => module.meta?.hasHeater)
    if (!target) return
    const now = Date.now()
    const thermistors = (target.thermometers ?? [])
      .map((probe) => {
        const numeric = toNumber(probe?.value)
        if (numeric == null) return null
        return {
          label: probe?.label ?? probe?.sensor ?? 'Thermometer',
          value: numeric,
        }
      })
      .filter(Boolean)
    if (!thermistors.length && target.meta?.current != null) {
      const snapshot = toNumber(target.meta.current)
      if (snapshot != null) {
        thermistors.push({ label: 'Probe', value: snapshot })
      }
    }
    if (!thermistors.length) return
    const sample = {
      timestamp: now,
      moduleId: target.module_id,
      setpoint: toNumber(target.meta?.target),
      heaterOn: determineHeaterActive(target),
      thermistors,
    }
    const cutoff = now - temperatureWindowMs
    temperatureHistory = [...temperatureHistory.filter((entry) => entry.timestamp >= cutoff), sample]
  }
  const focusTelemetryChart = (chartKey) => {
    if (!chartKey) return
    activeChartKey = chartKey
    if (chartKey === 'ato' || chartKey === 'filter') {
      loadUsage({ quiet: true })
    }
  }

  const isTouchPointer = (pt) => pt === 'touch'
  const isMouseLikePointer = (pt) => pt === 'mouse' || pt === 'pen'

  const beginScrollDrag = (event) => {
    scrollDragStart = {
      startY: event.clientY,
      scrollTop: getScrollTop(),
    }
  }

  const applyScrollDrag = (event) => {
    if (isTouchPointer(activePointerType)) return
    if (!scrollDragStart) {
      beginScrollDrag(event)
    }
    if (!scrollDragStart) return
    const delta = event.clientY - scrollDragStart.startY
    applyScroll(scrollDragStart.scrollTop - delta)
  }

  const tryCapturePointer = (target, pointerId) => {
    if (pointerCaptureActive || pointerId == null || !target?.setPointerCapture) return
    target.setPointerCapture(pointerId)
    pointerCaptureActive = true
    logTouchDebug({ capturing: true, lastEvent: 'capture' })
  }

  const releasePointerCapture = (target) => {
    if (!pointerCaptureActive || !target?.releasePointerCapture || activePointerId == null) return
    target.releasePointerCapture(activePointerId)
    pointerCaptureActive = false
    logTouchDebug({ capturing: false, lastEvent: 'release' })
  }

  const getScrollRoot = () => mainEl

  const getMaxScroll = () => mainEl ? Math.max(0, mainEl.scrollHeight - mainEl.clientHeight) : 0
  const clampScroll = (val) => Math.max(0, Math.min(val, getMaxScroll()))

  const applyScroll = (val) => {
    if (!mainEl) return
    mainEl.scrollTop = clampScroll(val)
    scrollY = mainEl.scrollTop
  }

  const getScrollTop = () => mainEl?.scrollTop ?? 0

  const launchMomentumScroll = (velY) => {
    if (!mainEl) return
    if (momentumRafId) cancelAnimationFrame(momentumRafId)
    let v = velY
    const step = () => {
      if (Math.abs(v) < 0.5) { momentumRafId = null; return }
      mainEl.scrollTop += v
      scrollY = mainEl.scrollTop
      v *= 0.88
      momentumRafId = requestAnimationFrame(step)
    }
    momentumRafId = requestAnimationFrame(step)
  }

  const resetSwipeState = (target) => {
    releasePointerCapture(target)
    swipeStart = null
    swipeDelta = { x: 0, y: 0 }
    swipeIntent = null
    swipeIsActive = false
    liveDragOffset = 0
    lastTouchY = null
    touchVelY = 0
    activePointerId = null
    activePointerType = null
    scrollDragStart = null
    logTouchDebug({ intent: '', pointerType: '', lastEvent: 'reset' })
  }

  const nextCard = () => {
    if (!moduleCards.length) return
    activeIndex = (activeIndex + 1) % moduleCards.length
  }

  const previousCard = () => {
    if (!moduleCards.length) return
    activeIndex = (activeIndex - 1 + moduleCards.length) % moduleCards.length
  }

  const handlePointerDown = (event) => {
    activePointerId = event.pointerId ?? null
    swipeStart = { x: event.clientX, y: event.clientY }
    swipeDelta = { x: 0, y: 0 }
    swipeIntent = null
    swipeIsActive = false
    liveDragOffset = 0
    swipeStartTime = performance.now()
    pointerCaptureActive = false
    activePointerType = event.pointerType ?? null
    if (isMouseLikePointer(activePointerType)) {
      event.preventDefault()
      beginScrollDrag(event)
    }
    logTouchDebug({
      pointerType: activePointerType ?? 'unknown',
      intent: '',
      lastEvent: 'pointerdown',
    })
  }

  const handlePointerMove = (event) => {
    if (!swipeStart || (event.pointerId != null && event.pointerId !== activePointerId)) return
    swipeDelta = { x: event.clientX - swipeStart.x, y: event.clientY - swipeStart.y }
    const absX = Math.abs(swipeDelta.x)
    const absY = Math.abs(swipeDelta.y)

    if (!swipeIntent) {
      if (absX > 12 && absX > absY) {
        swipeIntent = 'horizontal'
        swipeIsActive = true
        event.preventDefault()
        tryCapturePointer(event.currentTarget, event.pointerId)
        logTouchDebug({ intent: 'horizontal', lastEvent: 'detect-horizontal' })
      } else if (absY > 12) {
        swipeIntent = 'vertical'
        releasePointerCapture(event.currentTarget)
        if (isTouchPointer(activePointerType)) {
          lastTouchY = event.clientY
          touchVelY = 0
          event.preventDefault()
        } else {
          event.preventDefault()
          applyScrollDrag(event)
        }
        logTouchDebug({ intent: 'vertical', lastEvent: 'detect-vertical' })
        return
      } else {
        return
      }
    }

    if (swipeIntent === 'horizontal') {
      event.preventDefault()
      const raw = swipeDelta.x
      const atStart = activeIndex === 0
      const atEnd = activeIndex === moduleCards.length - 1
      if ((raw > 0 && atStart) || (raw < 0 && atEnd)) {
        liveDragOffset = raw * 0.25
      } else {
        liveDragOffset = raw
      }
    } else if (swipeIntent === 'vertical') {
      event.preventDefault()
      if (isTouchPointer(activePointerType)) {
        if (typeof window !== 'undefined' && lastTouchY != null) {
          const delta = lastTouchY - event.clientY
          applyScroll(scrollY + delta)
          touchVelY = delta
        }
        lastTouchY = event.clientY
      } else {
        applyScrollDrag(event)
      }
    }
  }

  const resolveSwipe = (event) => {
    if (event?.pointerId != null && event.pointerId !== activePointerId) return
    if (!swipeStart) return

    if (swipeIntent === 'vertical') {
      if (isTouchPointer(activePointerType)) {
        launchMomentumScroll(touchVelY)
      }
      resetSwipeState(event?.currentTarget)
      return
    }

    const { x, y } = swipeDelta
    const elapsed = performance.now() - swipeStartTime
    const velocity = elapsed > 0 ? x / elapsed : 0
    const isFlick = Math.abs(velocity) > 0.35 && Math.abs(x) > 10
    if (swipeIntent === 'horizontal' && Math.abs(x) > Math.abs(y) && (Math.abs(x) > SWIPE_THRESHOLD || isFlick)) {
      if (x < 0) {
        nextCard()
      } else {
        previousCard()
      }
      logTouchDebug({ lastEvent: 'swipe-complete' })
    }
    resetSwipeState(event?.currentTarget)
  }

  const handlePageTouchStart = (event) => {
    if (event.target?.closest('.card-stage')) return
    const touch = event.touches[0]
    if (!touch) return
    pageDrag = {
      identifier: touch.identifier,
      startY: touch.clientY,
      lastY: touch.clientY,
      scrollTop: scrollY,
      velY: 0,
      lastTime: performance.now(),
    }
    logTouchDebug({ lastEvent: 'page-touchstart' })
  }

  const handlePageTouchMove = (event) => {
    if (!pageDrag) return
    const touch = Array.from(event.changedTouches).find(t => t.identifier === pageDrag.identifier)
    if (!touch) return
    const now = performance.now()
    const dt = now - pageDrag.lastTime
    const dy = pageDrag.lastY - touch.clientY
    if (dt > 0) pageDrag.velY = (dy / dt) * 16
    pageDrag.lastY = touch.clientY
    pageDrag.lastTime = now
    applyScroll(pageDrag.scrollTop + (pageDrag.startY - touch.clientY))
    logTouchDebug({ lastEvent: 'page-touchmove', intent: 'page-drag' })
  }

  const handlePageTouchEnd = (event) => {
    if (!pageDrag) return
    launchMomentumScroll(pageDrag.velY)
    pageDrag = null
    logTouchDebug({ lastEvent: 'page-touchend' })
  }

  // Mouse wheel and pointer drag for desktop browser testing
  const handlePagePointerDown = (event) => {
    if (event.target?.closest('.card-stage')) return
    console.log('[page-pd] type:', event.pointerType, 'xy:', event.clientX, event.clientY, 'btns:', event.buttons)
    if (!isMouseLikePointer(event.pointerType)) return
    if (event.buttons !== 1) return
    // Capture pointer so iframes can't swallow pointermove during drag
    try { mainEl?.setPointerCapture(event.pointerId) } catch (_) {}
    pageDrag = {
      identifier: event.pointerId,
      startY: event.clientY,
      lastY: event.clientY,
      scrollTop: getScrollTop(),
      velY: 0,
      lastTime: performance.now(),
    }
  }

  const handlePagePointerMove = (event) => {
    if (!pageDrag || !isMouseLikePointer(event.pointerType)) return
    event.preventDefault()
    const now = performance.now()
    const dt = now - pageDrag.lastTime
    const dy = pageDrag.lastY - event.clientY
    if (dt > 0) pageDrag.velY = (dy / dt) * 16
    pageDrag.lastY = event.clientY
    pageDrag.lastTime = now
    applyScroll(pageDrag.scrollTop + (pageDrag.startY - event.clientY))
  }

  const handlePagePointerUp = (event) => {
    if (!isMouseLikePointer(event.pointerType)) return
    if (pageDrag) launchMomentumScroll(pageDrag.velY)
    pageDrag = null
    try { mainEl?.releasePointerCapture(event.pointerId) } catch (_) {}
  }

  const handleWheel = (event) => {
    event.preventDefault()
    applyScroll(scrollY + event.deltaY)
  }

  const openKeypad = (module) => {
    if (!module || !module.meta?.hasHeater) return
    keypadModule = module
    const baseline = module.meta?.target ?? module.meta?.current ?? 25
    keypadValue = baseline != null ? Number(baseline).toFixed(1) : ''
    keypadError = ''
    keypadVisible = true
  }

  const dismissKeypad = () => {
    keypadVisible = false
    keypadModule = null
    keypadValue = ''
    keypadError = ''
  }

  const handleKeypadInput = (key) => {
    if (key === 'CLR') {
      keypadValue = ''
      keypadError = ''
      return
    }
    if (key === 'DEL') {
      keypadValue = keypadValue.slice(0, -1)
      keypadError = ''
      return
    }
    if (key === '.' && keypadValue.includes('.')) return
    keypadValue = `${keypadValue}${key}`
  }

  const computeBand = (target) => {
    const numeric = Number(target)
    return {
      min: Number((numeric - HYSTERESIS_C).toFixed(1)),
      max: Number((numeric + HYSTERESIS_C).toFixed(1)),
    }
  }

  const confirmSetpoint = async () => {
    if (!keypadModule?.meta?.hasHeater) return
    const numeric = toNumber(keypadValue)
    if (numeric == null) {
      keypadError = 'Enter a temperature first'
      return
    }
    const band = computeBand(numeric)
    keypadBusy = true
    keypadError = ''
    try {
      await updateModuleControls(keypadModule.module_id, {
        heater_setpoint_c: Number(numeric.toFixed(1)),
        heater_hysteresis_span_c: Number((band.max - band.min).toFixed(2)),
      })
      showToast(`${keypadModule.label ?? keypadModule.module_id} target set to ${numeric.toFixed(1)}°C`)
      dismissKeypad()
      loadModules({ quiet: true })
    } catch (err) {
      keypadError = err?.message ?? 'Failed to push setpoint'
    } finally {
      keypadBusy = false
    }
  }

  const setAtoMode = async (module, mode) => {
    if (!module || !isPickleSumpModule(module) || !mode || atoModeBusyFor === module.module_id) return
    const normalized = mode.toLowerCase()
    if (!['auto', 'manual', 'paused'].includes(normalized)) return
    if (module.meta?.atoMode === normalized) return
    atoModeBusyFor = module.module_id
    error = ''
    try {
      await updateModuleControls(module.module_id, { ato_mode: normalized })
      showToast(`${module.label ?? module.module_id} set to ${normalized} mode`)
      await loadModules({ quiet: true })
    } catch (err) {
      error = err?.message ?? 'Unable to update ATO mode'
    } finally {
      atoModeBusyFor = ''
    }
  }

  const chooseAtoMode = async (event, module, mode) => {
    const dropdown = event?.currentTarget?.closest?.('.mode-dropdown')
    await setAtoMode(module, mode)
    dropdown?.removeAttribute('open')
  }

  const openResetDialog = (module, type) => {
    if (!module || !RESET_ACTIONS[type]) return
    confirmDialog = { module, type }
    confirmError = ''
    confirmBusy = false
  }

  const dismissResetDialog = () => {
    confirmDialog = null
    confirmError = ''
    confirmBusy = false
  }

  const performResetAction = async () => {
    if (!confirmDialog) return
    const config = RESET_ACTIONS[confirmDialog.type]
    if (!config) return
    confirmBusy = true
    confirmError = ''
    try {
      await updateModuleControls(confirmDialog.module.module_id, config.payload)
      showToast(config.toast ?? 'Command sent.')
      dismissResetDialog()
      await loadModules({ quiet: true })
    } catch (err) {
      confirmError = err?.message ?? 'Unable to send command'
    } finally {
      confirmBusy = false
    }
  }

  const showToast = (message) => {
    toast = message
    if (toastTimer) {
      clearTimeout(toastTimer)
    }
    toastTimer = setTimeout(() => {
      toast = ''
    }, 4200)
  }

  const sendExitRequest = async () => {
    const hasTauriBridge =
      typeof window !== 'undefined' && (window.__TAURI__ || window.__TAURI_INTERNALS__)
    if (hasTauriBridge) {
      try {
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('exit_app')
        return
      } catch (err) {
        console.warn('Unable to exit app via Tauri', err)
      }
    }
    window.close?.()
  }

  const keypadKeys = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['.', '0', 'DEL'],
  ]
</script>

<main bind:this={mainEl}
  on:pointerdown|capture={handlePagePointerDown}
  on:pointermove|capture={handlePagePointerMove}
  on:pointerup|capture={handlePagePointerUp}
  on:pointercancel|capture={handlePagePointerUp}
>
  <section class="telemetry-pane">
    <header class="telemetry-header">
      <div>
        <p class="eyebrow">Pickle Reef</p>
        <h1>Touch Console</h1>
      </div>
      <div class="header-actions">
        <button type="button" class="refresh" on:click={loadModules} disabled={loading}>
          {loading ? 'Syncing…' : 'Refresh'}
        </button>
        <button type="button" class="ghost" on:click={sendExitRequest}>
          Exit
        </button>
      </div>
    </header>
    <div class="hero-stats">
      {#each heroCardModels as card (card.key)}
        <button
          type="button"
          class="stat-card hero-card"
          class:active={activeChartKey === card.key}
          aria-pressed={activeChartKey === card.key}
          on:click={() => focusTelemetryChart(card.key)}
        >
          <p>{card.label}</p>
          <strong>{card.value}</strong>
          <small>{card.detail ?? 'Tap to highlight the chart below'}</small>
        </button>
      {/each}
    </div>
    <div class="chart-stack">
      {#if activeChartKey === 'temperature'}
      <div class="chart-panel" id="chart-panel-temperature">
        <div class="chart-panel__header">
          <div>
            <p class="eyebrow">Temperature</p>
            <h2>Heater history</h2>
          </div>
          <div class="chart-window-selector">
            {#each CHART_WINDOWS as hours}
              <button
                type="button"
                class:active={chartWindowSelections.temperature === hours}
                on:click={() => changeChartWindow('temperature', hours)}
              >{hours}h</button>
            {/each}
          </div>
        </div>
        {#if !temperatureChartDatasets.datasets?.length}
          <p class="chart-placeholder">Waiting for temperature telemetry…</p>
        {:else}
          <LineChart
            datasets={temperatureChartDatasets.datasets}
            ariaLabel="Heater temperature chart"
            yTitle="°C"
            xTickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            yTickFormatter={(v) => `${Number(v).toFixed(1)}°`}
            height={280}
            fontSize={13}
            fontWeight="600"
            tickColor="rgba(255,255,255,0.85)"
            gridColor="rgba(255,255,255,0.15)"
            yBeginAtZero={false}
            yMin={temperatureChartDatasets.yMin}
            yMax={temperatureChartDatasets.yMax}
            showLegend={true}
          />
        {/if}
      </div>
      {/if}
      {#if activeChartKey === 'filter'}
      <div class="chart-panel" id="chart-panel-filter">
        <div class="chart-panel__header">
          <div>
            <p class="eyebrow">Filter usage</p>
            <h2>Roller media usage</h2>
          </div>
          <div class="chart-window-selector">
            {#each CHART_WINDOWS as hours}
              <button
                type="button"
                class:active={chartWindowSelections.filter === hours}
                on:click={() => changeChartWindow('filter', hours)}
              >{hours}h</button>
            {/each}
          </div>
        </div>
        {#if !filterChartDatasets?.length}
          <p class="chart-placeholder">No filter activity in this window…</p>
        {:else}
          <LineChart
            datasets={filterChartDatasets}
            ariaLabel="Filter media usage chart"
            yTitle="Media (mm)"
            xTickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            yTickFormatter={(v) => `${Number(v).toFixed(1)}mm`}
            height={280}
            fontSize={13}
            fontWeight="600"
            tickColor="rgba(255,255,255,0.85)"
            gridColor="rgba(255,255,255,0.15)"
          />
        {/if}
      </div>
      {/if}
      {#if activeChartKey === 'ato'}
      <div class="chart-panel" id="chart-panel-ato">
        <div class="chart-panel__header">
          <div>
            <p class="eyebrow">ATO usage</p>
            <h2>Reservoir usage</h2>
          </div>
          <div class="chart-window-selector">
            {#each CHART_WINDOWS as hours}
              <button
                type="button"
                class:active={chartWindowSelections.ato === hours}
                on:click={() => changeChartWindow('ato', hours)}
              >{hours}h</button>
            {/each}
          </div>
        </div>
        {#if !atoChartDatasets?.length}
          <p class="chart-placeholder">No ATO activity in this window…</p>
        {:else}
          <LineChart
            datasets={atoChartDatasets}
            ariaLabel="ATO water usage chart"
            yTitle="Water (mL)"
            xTickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            yTickFormatter={(v) => `${Math.round(Number(v))}mL`}
            height={280}
            fontSize={13}
            fontWeight="600"
            tickColor="rgba(255,255,255,0.85)"
            gridColor="rgba(255,255,255,0.15)"
          />
        {/if}
      </div>
      {/if}
      <p class="chart-footnote">Native Chart.js — same pipeline as the main frontend.</p>
    </div>
  </section>

  <section class="controls-pane">
    <div class="pane-header">
      <div>
        <p class="eyebrow">Modules</p>
        <h2>Direct control</h2>
      </div>
      <div class="carousel-status">
        <span>{moduleCards.length ? activeIndex + 1 : 0}/{moduleCards.length}</span>
      </div>
    </div>
    {#if error && !loading}
      <p class="error-line">{error}</p>
    {/if}
    <div
      class="card-stage"
      role="region"
      aria-label="Module carousel"
      on:pointerdown|stopPropagation={handlePointerDown}
      on:pointermove|stopPropagation={handlePointerMove}
      on:pointerup|stopPropagation={resolveSwipe}
      on:pointercancel|stopPropagation={resolveSwipe}
      on:pointerleave|stopPropagation={resolveSwipe}
    >
      {#if moduleCards.length}
        <div class="card-track" class:dragging={swipeIsActive} style={`transform: translateX(calc(-${activeIndex * 100}% + ${liveDragOffset}px));`}>
          {#each moduleCards as module (module.module_id)}
            <article class="module-card" class:active={module.module_id === activeModule?.module_id}>
              <header class="card-header">
                <div>
                  <p class="eyebrow">{module.module_id}</p>
                  <h3>{module.label ?? 'Heater module'}</h3>
                </div>
                <span class={`status-pill ${module.status ?? 'offline'}`}>
                  {module.status ?? 'offline'}
                </span>
              </header>
              {#if module.meta?.hasHeater}
                <div class="temp-readouts">
                  <div>
                    <p>Current</p>
                    <strong>{formatTemp(module.meta?.current)}</strong>
                  </div>
                  <div>
                    <p>Target</p>
                    <button type="button" class="temp-value-button" on:click={() => openKeypad(module)}>
                      {formatTemp(module.meta?.target)}
                    </button>
                    {#if module.meta?.min != null && module.meta?.max != null}
                      <small>Band {module.meta.min.toFixed(1)}—{module.meta.max.toFixed(1)}°C</small>
                    {/if}
                  </div>
                  <div>
                    <p>Duty</p>
                    <strong>{module.meta?.duty != null ? `${module.meta.duty}%` : '—'}</strong>
                  </div>
                </div>
                {#if module.thermometers.length}
                  <div class="probes">
                    {#each module.thermometers.slice(0, 2) as probe}
                      <div class="probe-chip">
                        <small>{probe.label}</small>
                        <span>{probe.value.toFixed(1)}°C</span>
                      </div>
                    {/each}
                  </div>
                {/if}
                <p class="hint">State: {(module.heater?.state ?? 'idle').toString()}</p>
                <div class="card-actions">
                  <button type="button" class="primary" on:click={() => openKeypad(module)}>
                    Set Target
                  </button>
                  <button type="button" class="ghost" on:click={() => openHysterisisPanel(module)}>
                    Hysterisis
                  </button>
                  <button type="button" class="ghost" on:click={() => openHeaterSafety(module)}>
                    Alarm Panel
                  </button>
                </div>
                <p class="hint">Swipe sideways to change modules · Tap target to edit</p>
              {:else}
                {#if isPickleSumpModule(module)}
                  <div class="sump-slot-grid">
                    <div class="slot">
                      <p>ATO mode</p>
                      <details
                        class={`mode-dropdown mode-dropdown--${module.meta?.atoMode ?? 'auto'}`}
                        class:is-busy={atoModeBusyFor === module.module_id}
                      >
                        <summary>
                          <span>{(module.meta?.atoMode ?? 'auto').charAt(0).toUpperCase() + (module.meta?.atoMode ?? 'auto').slice(1)}</span>
                        </summary>
                        <div class="mode-menu" role="listbox" aria-label="ATO mode options">
                          <button
                            type="button"
                            class:active={(module.meta?.atoMode ?? 'auto') === 'auto'}
                            on:click={(event) => chooseAtoMode(event, module, 'auto')}
                            disabled={atoModeBusyFor === module.module_id}
                          >
                            Auto
                          </button>
                          <button
                            type="button"
                            class:active={(module.meta?.atoMode ?? 'auto') === 'manual'}
                            on:click={(event) => chooseAtoMode(event, module, 'manual')}
                            disabled={atoModeBusyFor === module.module_id}
                          >
                            Manual
                          </button>
                          <button
                            type="button"
                            class:active={(module.meta?.atoMode ?? 'auto') === 'paused'}
                            on:click={(event) => chooseAtoMode(event, module, 'paused')}
                            disabled={atoModeBusyFor === module.module_id}
                          >
                            Paused
                          </button>
                        </div>
                      </details>
                    </div>
                    <div class="slot">
                      <p>ATO tank level</p>
                      <strong>{formatPercent(module.meta?.atoTankLevelPercent)}</strong>
                    </div>
                    <div class="slot">
                      <p>Roller activations</p>
                      <strong>{module.meta?.rollerActivations ?? '—'}</strong>
                    </div>
                    <div class="slot">
                      <p>Roller used</p>
                      <strong>{module.meta?.rollerUsedMm != null ? formatMediaLength(module.meta.rollerUsedMm) : '—'}</strong>
                    </div>
                  </div>
                  <div class="card-actions">
                    <button type="button" class="primary" on:click={() => openResetDialog(module, 'ato')}>
                      ATO Reset
                    </button>
                    <button type="button" class="ghost destructive" on:click={() => openResetDialog(module, 'spool')}>
                      Spool Reset
                    </button>
                  </div>
                  <p class="hint">Use after refilling the reservoir or swapping the filter roll.</p>
                {:else}
                  <div class="module-info-grid">
                    <div>
                      <p>Module type</p>
                      <strong>{module.module_type ?? '—'}</strong>
                    </div>
                    <div>
                      <p>Firmware</p>
                      <strong>{module.firmware_version ?? '—'}</strong>
                    </div>
                    <div>
                      <p>Signal</p>
                      <strong>{module.rssi != null ? `${module.rssi} dBm` : '—'}</strong>
                    </div>
                  </div>
                  <div class="module-info-grid secondary">
                    <div>
                      <p>IP address</p>
                      <strong>{module.ip_address ?? '—'}</strong>
                    </div>
                    <div>
                      <p>Last seen</p>
                      <strong>{formatLastSeen(module.last_seen)}</strong>
                    </div>
                    <div>
                      <p>Status</p>
                      <strong>{module.status ?? 'unknown'}</strong>
                    </div>
                  </div>
                  <p class="hint">Status-only module · Controls coming soon</p>
                {/if}
              {/if}
            </article>
          {/each}
        </div>
      {:else if !loading}
        <div class="empty-state">
          <p>No modules have connected yet.</p>
          <small>Bring a controller online to unlock the carousel view.</small>
        </div>
      {/if}
    </div>
  </section>

  {#if activeAlarms.length}
    <section class="alarm-ticker">
      <div class="ticker-header">
        <p class="eyebrow">Active alerts</p>
        <span>{activeAlarms.length} issues</span>
      </div>
      <div class="alarm-track">
        {#each activeAlarms.slice(0, 4) as alarm}
          <button
            type="button"
            class={`alarm-chip severity-${alarm.severity ?? 'warning'}`}
            on:click={() => openAlarmModal(alarm)}
          >
            <strong>{alarm.moduleLabel}</strong>
            <span>{alarm.message ?? 'Check module state'}</span>
          </button>
        {/each}
      </div>
    </section>
  {/if}

  {#if keypadVisible && keypadModule}
    <div class="keypad-overlay" role="dialog" aria-modal="true">
      <div class="keypad-panel">
        <header>
          <div>
            <p class="eyebrow">{keypadModule.module_id}</p>
            <h3>Set target temperature</h3>
          </div>
          <button type="button" class="ghost" on:click={dismissKeypad}>Close</button>
        </header>
        <div class="keypad-display">
          <span>{keypadValue || '--.--'}</span>
          <small>°C</small>
        </div>
        {#if keypadError}
          <p class="error-line">{keypadError}</p>
        {/if}
        <div class="keypad-grid">
          {#each keypadKeys as row}
            {#each row as key}
              <button type="button" on:click={() => handleKeypadInput(key)} class="key-btn">
                {key}
              </button>
            {/each}
          {/each}
        </div>
        <button type="button" class="primary" on:click={confirmSetpoint} disabled={keypadBusy}>
          {keypadBusy ? 'Sending…' : 'Push to module'}
        </button>
      </div>
    </div>
  {/if}

  {#if confirmDialog && confirmContent}
    <div class="confirm-overlay" role="dialog" aria-modal="true">
      <div class="confirm-panel">
        <header>
          <div>
            <p class="eyebrow">{confirmDialog.module.module_id}</p>
            <h3>{confirmContent.title}</h3>
          </div>
          <button type="button" class="ghost" on:click={dismissResetDialog} disabled={confirmBusy}>
            Close
          </button>
        </header>
        <p class="confirm-body">{confirmContent.body}</p>
        <div class="confirm-meta">
          <small>Module</small>
          <strong>{confirmDialog.module.label ?? confirmDialog.module.module_id}</strong>
        </div>
        {#if confirmError}
          <p class="error-line">{confirmError}</p>
        {/if}
        <div class="confirm-actions">
          <button type="button" class="ghost" on:click={dismissResetDialog} disabled={confirmBusy}>
            Cancel
          </button>
          <button type="button" class="primary" on:click={performResetAction} disabled={confirmBusy}>
            {confirmBusy ? 'Sending…' : confirmContent.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if hysteresisVisible && hysteresisModule}
    <div class="confirm-overlay" role="dialog" aria-modal="true">
      <div class="confirm-panel hysteresis-panel">
        <header>
          <div>
            <p class="eyebrow">{hysteresisModule.module_id}</p>
            <h3>Hysterisis</h3>
          </div>
          <button type="button" class="ghost" on:click={closeHysterisisPanel} disabled={hysteresisBusy}>
            Close
          </button>
        </header>
        <label class="hysteresis-control">
          <span>Width ({hysteresisSpanC.toFixed(2)}°C)</span>
          <input
            type="range"
            min={HEATER_HYSTERESIS_MIN_C}
            max={HEATER_HYSTERESIS_MAX_C}
            step="0.05"
            bind:value={hysteresisSpanC}
          />
          <small>Heater cycles ± {(hysteresisSpanC / 2).toFixed(2)}°C around target.</small>
        </label>
        {#if hysteresisError}
          <p class="error-line">{hysteresisError}</p>
        {/if}
        <div class="confirm-actions">
          <button type="button" class="ghost" on:click={closeHysterisisPanel} disabled={hysteresisBusy}>Cancel</button>
          <button type="button" class="primary" on:click={saveHysterisis} disabled={hysteresisBusy}>
            {hysteresisBusy ? 'Saving…' : 'Save Hysterisis'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if heaterSafetyVisible && safetyModule}
    <div class="confirm-overlay" role="dialog" aria-modal="true">
      <div class="confirm-panel heater-safety-panel">
        <header>
          <div>
            <p class="eyebrow">{safetyModule.module_id}</p>
            <h3>Heater safety controls</h3>
          </div>
          <button type="button" class="ghost" on:click={closeHeaterSafety} disabled={safetyBusy}>
            Close
          </button>
        </header>
        <div class="safety-grid">
          <label>
            <span>Probe tolerance ({safetyProbeToleranceC.toFixed(1)}°C)</span>
            <input type="range" min={PROBE_TOLERANCE_MIN_C} max={PROBE_TOLERANCE_MAX_C} step="0.1" bind:value={safetyProbeToleranceC} />
          </label>
          <label>
            <span>Probe timeout ({safetyProbeTimeoutS}s)</span>
            <input type="range" min={PROBE_TIMEOUT_MIN_S} max={PROBE_TIMEOUT_MAX_S} step="1" bind:value={safetyProbeTimeoutS} />
          </label>
          <label>
            <span>Runaway delta ({safetyRunawayDeltaC.toFixed(1)}°C)</span>
            <input type="range" min={RUNAWAY_DELTA_MIN_C} max={RUNAWAY_DELTA_MAX_C} step="0.1" bind:value={safetyRunawayDeltaC} />
          </label>
          <label>
            <span>Max heater on-time ({safetyMaxHeaterOnMin} min)</span>
            <input type="range" min={MAX_HEATER_ON_MIN_MIN} max={MAX_HEATER_ON_MIN_MAX} step="1" bind:value={safetyMaxHeaterOnMin} />
          </label>
          <label>
            <span>Stuck relay delta ({safetyStuckRelayDeltaC.toFixed(1)}°C)</span>
            <input type="range" min={STUCK_RELAY_DELTA_MIN_C} max={STUCK_RELAY_DELTA_MAX_C} step="0.1" bind:value={safetyStuckRelayDeltaC} />
          </label>
          <label>
            <span>Stuck relay window ({safetyStuckRelayWindowS}s)</span>
            <input type="range" min={STUCK_RELAY_WINDOW_MIN_S} max={STUCK_RELAY_WINDOW_MAX_S} step="5" bind:value={safetyStuckRelayWindowS} />
          </label>
        </div>
        {#if safetyError}
          <p class="error-line">{safetyError}</p>
        {/if}
        <div class="confirm-actions">
          <button type="button" class="ghost" on:click={closeHeaterSafety} disabled={safetyBusy}>Cancel</button>
          <button type="button" class="primary" on:click={saveHeaterSafety} disabled={safetyBusy}>
            {safetyBusy ? 'Saving…' : 'Save safety settings'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if alarmModal}
    <div class="confirm-overlay" role="dialog" aria-modal="true">
      <div class="confirm-panel alarm-action-panel">
        <header>
          <div>
            <p class="eyebrow">{alarmModal.moduleId}</p>
            <h3>{alarmModal.message ?? 'Active alarm'}</h3>
          </div>
          <button type="button" class="ghost" on:click={closeAlarmModal} disabled={alarmActionBusy}>Close</button>
        </header>
        <p class="confirm-body">Severity: {(alarmModal.severity ?? 'warning').toUpperCase()}</p>
        <p class="confirm-body">Detected: {formatLastSeen(alarmModal.timestamp)}</p>
        {#if alarmActionError}
          <p class="error-line">{alarmActionError}</p>
        {/if}
        <div class="confirm-actions">
          <button type="button" class="ghost" on:click={inspectAlarmModule} disabled={alarmActionBusy}>Inspect module</button>
          <button type="button" class="ghost" on:click={closeAlarmModal} disabled={alarmActionBusy}>Dismiss</button>
          <button type="button" class="primary" on:click={snoozeAlarmFromModal} disabled={alarmActionBusy}>
            {alarmActionBusy ? 'Snoozing…' : 'Snooze alarm'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  {#if toast}
    <div class="toast" aria-live="polite">
      {toast}
    </div>
  {/if}

  {#if true}
    <div class="touch-debug-panel">
      <strong>Debug</strong>
      {#each debugLines.split('\n') as line}
        <p>{line}</p>
      {/each}
    </div>
  {/if}

  {#if bootstrapping}
    <div class="loading-overlay">
      <div class="spinner"></div>
      <p>Syncing modules…</p>
    </div>
  {/if}
</main>

<style>
:global(html) {
  height: 100%;
  overflow: hidden;
}

:global(body) {
  margin: 0;
  height: 100%;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Helvetica Neue', sans-serif;
  background: #010812;
  color: #f3fbff;
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}

main,
main * {
  -webkit-user-select: none;
  user-select: none;
}

main {
  height: 100%;
  overflow-y: scroll;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 1.25rem 1.25rem 2rem;
  box-sizing: border-box;
  background:
    radial-gradient(circle at 20% 20%, rgba(20, 93, 255, 0.25), transparent 55%),
    radial-gradient(circle at 80% 0%, rgba(24, 255, 211, 0.2), transparent 50%),
    linear-gradient(180deg, rgba(2, 6, 22, 0.95), rgba(1, 3, 12, 0.98));
  touch-action: pan-y;
}

.telemetry-pane,
.controls-pane {
  flex: 0 0 auto;
  background: rgba(2, 12, 24, 0.55);
  border: 1px solid rgba(91, 168, 255, 0.2);
  border-radius: 28px;
  padding: 1.5rem;
  backdrop-filter: blur(18px);
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.35);
}

.telemetry-pane {
  min-height: 320px;
}

.telemetry-header,
.pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.header-actions {
  display: flex;
  gap: 0.6rem;
}

.eyebrow {
  margin: 0;
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(166, 214, 255, 0.85);
}

h1,
h2,
h3 {
  margin: 0;
}

.refresh {
  border: 1px solid rgba(150, 219, 255, 0.5);
  background: rgba(0, 35, 71, 0.6);
  color: #e7faff;
  padding: 0.6rem 1.2rem;
  border-radius: 999px;
  font-size: 0.95rem;
  cursor: pointer;
}

.refresh:disabled {
  opacity: 0.7;
  cursor: wait;
}

.chart-panel {
  margin-top: 0.65rem;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.03);
  background: rgba(2, 8, 20, 0.45);
  padding: 0.75rem;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.chart-stack {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chart-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.2rem;
}

.chart-embed-shell {
  width: 100%;
  min-height: 0;
  border-radius: 16px;
  overflow: hidden;
  border: 0;
  background: transparent;
}

.chart-embed-frame {
  width: 100%;
  height: 420px;
  border: 0;
  background: transparent;
}

.chart-window-selector button {
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.04);
  color: #e0f4ff;
  padding: 0.35rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.chart-window-selector button.active {
  border-color: rgba(118, 206, 255, 0.8);
  background: linear-gradient(135deg, rgba(32, 153, 255, 0.4), rgba(30, 237, 255, 0.25));
  color: #fff;
}

.chart-placeholder {
  margin: 0;
  padding: 1rem;
  text-align: center;
  color: rgba(214, 232, 255, 0.75);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 16px;
}

.chart-footnote {
  margin: 0.2rem 0 0;
  font-size: 0.8rem;
  color: rgba(207, 238, 255, 0.6);
}

.chart-footnote.warning {
  color: #ffbfbf;
}

.hero-stats {
  margin-top: 1.2rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.9rem;
}

.stat-card {
  border-radius: 18px;
  padding: 1rem 1.1rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
}

.stat-card strong {
  display: block;
  font-size: 1.6rem;
  margin-top: 0.2rem;
}

.stat-card small {
  color: rgba(207, 238, 255, 0.7);
}

.stat-card.accent {
  background: linear-gradient(135deg, rgba(32, 201, 255, 0.3), rgba(32, 63, 255, 0.25));
  border-color: rgba(118, 206, 255, 0.6);
}

.hero-card {
  appearance: none;
  -webkit-appearance: none;
  font: inherit;
  color: inherit;
  text-align: left;
  width: 100%;
  cursor: pointer;
  transition: border-color 0.25s ease, box-shadow 0.28s ease, transform 0.25s ease;
}

.hero-card:hover {
  border-color: rgba(118, 206, 255, 0.65);
}

.hero-card:focus-visible {
  outline: 2px solid rgba(118, 206, 255, 0.9);
  outline-offset: 3px;
}

.hero-card.active {
  border-color: rgba(94, 210, 255, 0.9);
  box-shadow: 0 20px 40px rgba(13, 52, 94, 0.55);
  background: linear-gradient(135deg, rgba(36, 153, 255, 0.28), rgba(29, 237, 255, 0.2));
  transform: translateY(-2px);
}

.controls-pane {
  margin-top: 0.5rem;
  min-height: 360px;
  display: flex;
  flex-direction: column;
}

.pane-header h2 {
  font-size: 1.6rem;
}

.carousel-status {
  font-size: 0.9rem;
  color: rgba(231, 250, 255, 0.8);
  border: 1px solid rgba(231, 250, 255, 0.2);
  border-radius: 999px;
  padding: 0.25rem 0.85rem;
}

.error-line {
  color: #ff8f8f;
  margin: 0.5rem 0 0.75rem;
}

.card-stage {
  position: relative;
  overflow: hidden;
  margin-top: 1rem;
  touch-action: none;
  -webkit-user-select: none;
  user-select: none;
}

.card-track {
  display: flex;
  width: 100%;
  height: 100%;
  transition: transform 0.42s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
  -webkit-backface-visibility: hidden;
  backface-visibility: hidden;
}

.card-track.dragging {
  transition: none;
}

.module-card {
  min-width: 100%;
  flex: 0 0 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.2rem 1.4rem 1.5rem;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(3, 14, 33, 0.7);
  opacity: 0.75;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
}

.module-card.active {
  border-color: rgba(94, 210, 255, 0.9);
  opacity: 1;
  box-shadow: 0 25px 50px rgba(4, 16, 36, 0.7);
}

.card-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}

.status-pill {
  text-transform: capitalize;
  padding: 0.35rem 0.8rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 0.85rem;
  align-self: flex-start;
}

.status-pill.online {
  color: #73ffba;
  border: 1px solid rgba(115, 255, 186, 0.4);
}

.status-pill.offline {
  color: #ff9f9f;
  border: 1px solid rgba(255, 159, 159, 0.4);
}

.temp-readouts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 1rem;
  text-align: center;
}

.temp-readouts p {
  margin: 0;
  color: rgba(230, 247, 255, 0.7);
}

.temp-readouts strong {
  font-size: 1.8rem;
  color: #fefefe;
}

.temp-value-button {
  border: none;
  background: none;
  color: #fefefe;
  font: inherit;
  font-size: 1.8rem;
  padding: 0;
  cursor: pointer;
}

.temp-value-button:focus-visible {
  outline: 2px solid rgba(94, 210, 255, 0.8);
  outline-offset: 2px;
}

.module-info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.module-info-grid div {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.02);
}

.module-info-grid.secondary {
  margin-top: 0.5rem;
}

.module-info-grid p {
  margin: 0;
  font-size: 0.8rem;
  color: rgba(207, 238, 255, 0.7);
}

.module-info-grid strong {
  display: block;
  margin-top: 0.15rem;
  font-size: 1rem;
}

.sump-slot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.sump-slot-grid .slot {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 0.9rem 1rem;
  background: rgba(255, 255, 255, 0.02);
  min-height: 112px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.sump-slot-grid .slot p {
  margin: 0;
  font-size: 0.95rem;
  color: rgba(230, 247, 255, 0.7);
}

.sump-slot-grid .slot strong {
  display: block;
  margin-top: 0.2rem;
  font-size: 1.8rem;
  line-height: 1.1;
  color: #fefefe;
}

.mode-dropdown {
  margin-top: 0.2rem;
  width: 100%;
  max-width: 100%;
  position: relative;
  box-sizing: border-box;
}

.mode-dropdown summary {
  list-style: none;
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 100%;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(9, 23, 40, 0.9);
  color: #f5fbff;
  padding: 0.7rem 2.1rem 0.7rem 0.8rem;
  font-size: 1.05rem;
  font-family: inherit;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
  transition: border-color 0.2s ease, background 0.2s ease;
  cursor: pointer;
  box-sizing: border-box;
  overflow: hidden;
}

.mode-dropdown summary::-webkit-details-marker {
  display: none;
}

.mode-dropdown summary::after {
  content: '';
  position: absolute;
  right: 0.8rem;
  top: calc(50% + 1px);
  width: 0.5rem;
  height: 0.5rem;
  border-right: 2px solid rgba(233, 246, 255, 0.95);
  border-bottom: 2px solid rgba(233, 246, 255, 0.95);
  transform: translateY(-50%) rotate(45deg);
  transition: transform 0.18s ease;
}

.mode-dropdown[open] summary::after {
  transform: translateY(-25%) rotate(225deg);
}

.mode-dropdown:focus-within summary,
.mode-dropdown[open] summary {
  border-color: rgba(118, 206, 255, 0.85);
  outline: 2px solid rgba(118, 206, 255, 0.9);
  outline-offset: 2px;
}

.mode-menu {
  position: absolute;
  z-index: 20;
  left: 0;
  right: 0;
  top: calc(100% + 0.35rem);
  display: grid;
  gap: 0.35rem;
  padding: 0.45rem;
  border-radius: 12px;
  border: 1px solid rgba(120, 182, 255, 0.42);
  background: linear-gradient(180deg, rgba(8, 27, 48, 0.98), rgba(5, 19, 36, 0.98));
  box-shadow: 0 14px 30px rgba(1, 7, 18, 0.45);
}

.mode-menu button {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  color: #eaf6ff;
  font: inherit;
  font-size: 1rem;
  font-weight: 600;
  padding: 0.58rem 0.65rem;
  text-align: left;
  cursor: pointer;
}

.mode-menu button.active {
  border-color: rgba(118, 206, 255, 0.75);
  background: linear-gradient(135deg, rgba(25, 102, 196, 0.45), rgba(27, 166, 220, 0.3));
}

.mode-menu button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.mode-dropdown.is-busy {
  opacity: 0.8;
}

.mode-dropdown--auto summary {
  border-color: rgba(118, 206, 255, 0.65);
  background: linear-gradient(135deg, rgba(33, 115, 255, 0.35), rgba(33, 237, 255, 0.2));
}

.mode-dropdown--manual summary {
  border-color: rgba(255, 214, 117, 0.7);
  background: linear-gradient(135deg, rgba(255, 170, 64, 0.35), rgba(255, 214, 117, 0.18));
}

.mode-dropdown--paused summary {
  border-color: rgba(255, 128, 128, 0.7);
  background: linear-gradient(135deg, rgba(255, 101, 117, 0.35), rgba(255, 155, 107, 0.18));
}

.temp-readouts small {
  display: block;
  margin-top: 0.1rem;
  color: rgba(204, 236, 255, 0.75);
}

.probes {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.probe-chip {
  flex: 1;
  min-width: 140px;
  padding: 0.75rem 1rem;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.probe-chip small {
  display: block;
  margin-bottom: 0.2rem;
  color: rgba(207, 238, 255, 0.7);
}

.probe-chip span {
  font-size: 1.2rem;
}

.card-actions button,
.key-btn,
.primary,
.ghost {
  font-family: inherit;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(9, 23, 40, 0.9);
  padding: 0.9rem 1rem;
  color: #f5fbff;
  font-size: 1rem;
  cursor: pointer;
}

.card-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.8rem;
}

.card-actions .primary {
  background: linear-gradient(135deg, #20c9ff, #1f74ff);
  border: none;
}

.card-actions .ghost {
  background: rgba(255, 255, 255, 0.05);
}

.card-actions .destructive {
  border-color: rgba(255, 140, 140, 0.5);
  color: #ffc5c5;
}

.hint {
  margin: 0;
  text-align: center;
  color: rgba(219, 239, 255, 0.65);
  font-size: 0.9rem;
}

.empty-state {
  text-align: center;
  padding: 2rem 1rem;
  color: rgba(227, 242, 255, 0.8);
}

.alarm-ticker {
  background: rgba(1, 9, 18, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 24px;
  padding: 0.9rem 1.1rem 1.2rem;
}

.ticker-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.8rem;
}

.ticker-header span {
  font-size: 0.85rem;
  color: rgba(230, 246, 255, 0.7);
}

.alarm-track {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.alarm-chip {
  appearance: none;
  -webkit-appearance: none;
  font: inherit;
  color: inherit;
  text-align: left;
  flex: 1;
  min-width: 200px;
  padding: 0.75rem 1rem;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  cursor: pointer;
}

.alarm-chip:focus-visible {
  outline: 2px solid rgba(118, 210, 255, 0.85);
  outline-offset: 2px;
}

.alarm-chip strong {
  font-size: 0.95rem;
}

.alarm-chip span {
  font-size: 0.85rem;
  color: rgba(224, 246, 255, 0.8);
}

.alarm-chip.severity-critical {
  border-color: rgba(255, 120, 120, 0.6);
  background: rgba(255, 58, 80, 0.15);
}

.alarm-chip.severity-warning {
  border-color: rgba(255, 207, 119, 0.5);
  background: rgba(255, 184, 77, 0.12);
}

.alarm-chip.severity-info {
  border-color: rgba(121, 220, 255, 0.4);
  background: rgba(80, 185, 255, 0.12);
}

.keypad-overlay,
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(1, 6, 15, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  backdrop-filter: blur(18px);
  z-index: 20;
}

.keypad-panel,
.confirm-panel {
  width: min(420px, 95vw);
  background: rgba(0, 11, 27, 0.95);
  border-radius: 28px;
  border: 1px solid rgba(118, 210, 255, 0.35);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.keypad-panel header,
.confirm-panel header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.keypad-display {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 1rem 1.2rem;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.05);
  font-size: 2.8rem;
}

.keypad-display small {
  font-size: 1.2rem;
  color: rgba(214, 239, 255, 0.9);
}

.keypad-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

.key-btn {
  font-size: 1.3rem;
  padding: 0.85rem 0;
}

.keypad-panel .primary {
  margin-top: 0.5rem;
  background: linear-gradient(135deg, #17c8ff, #2e8bff);
  border: none;
}

.confirm-body {
  margin: 0;
  color: rgba(211, 237, 255, 0.9);
  line-height: 1.4;
}

.confirm-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.confirm-meta small {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.75rem;
  color: rgba(166, 214, 255, 0.7);
}

.confirm-meta strong {
  font-size: 1.1rem;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.confirm-actions .primary {
  background: linear-gradient(135deg, #ff9f6e, #ff6575);
  border: none;
}

.heater-safety-panel {
  width: min(560px, 96vw);
}

.hysteresis-panel {
  width: min(460px, 95vw);
}

.hysteresis-control {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.hysteresis-control span {
  font-size: 0.95rem;
  color: rgba(216, 241, 255, 0.88);
}

.hysteresis-control input[type='range'] {
  width: 100%;
}

.hysteresis-control small {
  color: rgba(204, 232, 255, 0.75);
}

.safety-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.85rem;
}

.safety-grid label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.safety-grid span {
  font-size: 0.9rem;
  color: rgba(216, 241, 255, 0.88);
}

.safety-grid input[type='range'] {
  width: 100%;
}

.alarm-action-panel {
  width: min(460px, 95vw);
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 1.5rem;
  transform: translateX(-50%);
  background: rgba(10, 32, 52, 0.9);
  border: 1px solid rgba(130, 223, 255, 0.4);
  padding: 0.8rem 1.5rem;
  border-radius: 999px;
  z-index: 15;
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.4);
}

.touch-debug-panel {
  position: fixed;
  top: 0.5rem;
  left: 0.5rem;
  min-width: 200px;
  background: rgba(0, 0, 0, 0.92);
  border: 2px solid rgba(0, 255, 200, 0.9);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  font-size: 0.85rem;
  z-index: 9999;
  pointer-events: none;
  color: #f3fbff;
}

.touch-debug-panel strong {
  display: block;
  margin-bottom: 0.25rem;
  color: #ffffff;
}

.touch-debug-panel p {
  margin: 0.15rem 0;
  font-size: 0.8rem;
}

.loading-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(1, 5, 12, 0.65);
  backdrop-filter: blur(10px);
  z-index: 10;
  gap: 1rem;
}

.spinner {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #68dfff;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .telemetry-pane,
  .controls-pane {
    padding: 1.2rem;
  }

  .temp-readouts {
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  }

  .hero-stats {
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  }
}
</style>

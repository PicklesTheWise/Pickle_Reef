const toNumber = (value) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
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

const formatHourLabel = (timestamp) => {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).format(new Date(timestamp))
  } catch {
    const date = new Date(timestamp)
    const hour = date.getHours().toString().padStart(2, '0')
    return `${hour}:00`
  }
}

export const deriveLatestUsageTimestamp = (...collections) => {
  let latest = null
  collections.forEach((collection) => {
    if (!Array.isArray(collection)) return
    collection.forEach((entry) => {
      const timestamp = parseTimestampMs(
        entry?.recorded_at ?? entry?.recorded_at_ms ?? entry?.timestamp_ms ?? entry?.timestamp,
      )
      if (timestamp == null) return
      latest = latest == null ? timestamp : Math.max(latest, timestamp)
    })
  })
  return latest
}

export const createUsageBuckets = (options = {}) => {
  const bucketMinutes = Math.max(1, options.bucketMinutes ?? 60)
  const bucketMs = bucketMinutes * 60 * 1000
  const windowHours = Math.max(1, options.windowHours ?? 12)
  const bucketCount = Math.max(1, Math.round((windowHours * 60) / bucketMinutes))
  const totalWindow = bucketMs * Math.max(1, bucketCount)
  const anchor = toNumber(options.anchorTimestamp)
  const bucketEnd = anchor != null ? anchor : Date.now()
  const start = bucketEnd - totalWindow
  const buckets = Array.from({ length: Math.max(1, bucketCount) }, (_, index) => {
    const bucketStart = start + index * bucketMs
    return {
      start: bucketStart,
      end: bucketStart + bucketMs,
      label: formatHourLabel(bucketStart),
      count: 0,
      usage: 0,
    }
  })
  return { buckets, bucketMs, start }
}

const resolveBucketIndex = (meta, timestamp) => {
  if (!meta?.buckets?.length || !meta.bucketMs) return -1
  if (timestamp < meta.start) return -1
  const rawIndex = Math.floor((timestamp - meta.start) / meta.bucketMs)
  if (rawIndex < 0) return -1
  return Math.min(meta.buckets.length - 1, rawIndex)
}

export const assignActivationRuns = (meta, runs = [], options = {}) => {
  if (!meta?.buckets?.length) return meta
  const usageScale = options.usageScale ?? 1
  runs.forEach((run) => {
    const timestamp = parseTimestampMs(run?.recorded_at ?? run?.recorded_at_ms)
    if (timestamp == null) return
    const index = resolveBucketIndex(meta, timestamp)
    if (index < 0) return
    const bucket = meta.buckets[index]
    bucket.count += 1
    if (usageScale !== 0) {
      const durationMs = toNumber(run?.duration_ms)
      if (durationMs != null && durationMs > 0) {
        bucket.usage += durationMs * usageScale
      }
    }
  })
  return meta
}

export const assignSpoolUsage = (meta, entries = []) => {
  if (!meta?.buckets?.length) return meta
  entries.forEach((entry) => {
    const timestamp = parseTimestampMs(entry?.recorded_at)
    if (timestamp == null) return
    const index = resolveBucketIndex(meta, timestamp)
    if (index < 0) return
    const delta = toNumber(entry?.delta_mm)
    if (delta != null && delta > 0) {
      meta.buckets[index].usage += delta
    }
  })
  return meta
}

export const assignAtoUsageFromTrace = (meta, entries = []) => {
  if (!meta?.buckets?.length || !Array.isArray(entries) || !entries.length) return false

  const normalized = entries
    .map((entry) => {
      const timestamp = parseTimestampMs(entry?.timestamp ?? entry?.recorded_at)
      const usedMl = toNumber(entry?.used_ml ?? entry?.usedMl)
      if (timestamp == null || usedMl == null) return null
      return {
        timestamp,
        usedMl: Math.max(0, usedMl),
      }
    })
    .filter(Boolean)
    .sort((left, right) => left.timestamp - right.timestamp)

  if (!normalized.length) return false

  normalized.forEach((point) => {
    const bucketIndex = resolveBucketIndex(meta, point.timestamp)
    if (bucketIndex < 0) return
    const bucket = meta.buckets[bucketIndex]
    if (point.usedMl > bucket.usage) {
      bucket.usage = point.usedMl
    }
  })

  return true
}

export const finalizeBuckets = (meta) => {
  if (!meta?.buckets?.length) return []
  return meta.buckets.map((bucket) => ({
    label: bucket.label,
    count: bucket.count,
    usage: Number(bucket.usage.toFixed(2)),
  }))
}

export const findRecentResetTimestamp = (samples = [], options = {}) => {
  if (!Array.isArray(samples) || !samples.length) return null
  const valueKey = options.valueKey ?? 'usedMl'
  const resetThreshold = toNumber(options.resetThreshold) ?? 100
  let previous = null
  for (let idx = samples.length - 1; idx >= 0; idx -= 1) {
    const sample = samples[idx]
    if (!sample) continue
    const used = toNumber(sample[valueKey])
    if (used == null) continue
    if (used <= resetThreshold) {
      return toNumber(sample.timestamp) ?? null
    }
    if (previous != null && used + resetThreshold < previous) {
      return toNumber(sample.timestamp) ?? null
    }
    previous = used
  }
  return null
}

export const buildUsageSeriesPreferLevels = (options = {}) => {
  const cutoff = toNumber(options.cutoff) ?? Date.now() - 24 * 60 * 60 * 1000
  const levelSamples = Array.isArray(options.levelSamples) ? options.levelSamples : []
  const deltaEntries = Array.isArray(options.deltaEntries) ? options.deltaEntries : []
  const levelValueKey = options.levelValueKey ?? 'usedMm'
  const deltaValueKey = options.deltaValueKey ?? 'deltaMm'
  const tailLimit = Math.max(1, options.tailLimit ?? 240)

  const inWindowLevelSamples = levelSamples.filter((sample) => {
    const ts = toNumber(sample?.timestamp)
    return ts != null && ts >= cutoff
  })
  const preferredLevelSamples = inWindowLevelSamples.length ? inWindowLevelSamples : levelSamples.slice(-tailLimit)

  if (preferredLevelSamples.length) {
    const points = preferredLevelSamples
      .map((sample) => {
        const ts = toNumber(sample?.timestamp)
        const value = toNumber(sample?.[levelValueKey])
        if (ts == null || value == null) return null
        return { ts, value }
      })
      .filter(Boolean)
    const maxValue = Math.max(...points.map((point) => point.value), 0)
    return {
      points: maxValue > 0 ? points : [],
      total: points.length ? points[points.length - 1].value : 0,
      maxValue,
      windowStart: cutoff,
    }
  }

  const entries = deltaEntries.filter((entry) => {
    const ts = toNumber(entry?.timestamp)
    return ts != null && ts >= cutoff
  })
  let cumulative = 0
  const points = entries
    .map((entry) => {
      const ts = toNumber(entry?.timestamp)
      const delta = toNumber(entry?.[deltaValueKey])
      if (ts == null || delta == null) return null
      cumulative += delta
      return { ts, value: cumulative }
    })
    .filter(Boolean)
  const maxValue = Math.max(...points.map((point) => point.value), 0)
  return {
    points: maxValue > 0 ? points : [],
    total: cumulative,
    maxValue,
    windowStart: cutoff,
  }
}

export const buildAtoUsageSeries = (options = {}) => {
  const cutoff = toNumber(options.cutoff) ?? Date.now() - 24 * 60 * 60 * 1000
  const resetThreshold = toNumber(options.resetThreshold) ?? 100
  const tankSamples = Array.isArray(options.tankSamples) ? options.tankSamples : []
  const levelSamples = Array.isArray(options.levelSamples) ? options.levelSamples : []
  const tailLimit = Math.max(1, options.tailLimit ?? 240)

  const normalizeSeries = (samples) => {
    let lastValue = null
    return samples
      .map((sample) => {
        const ts = toNumber(sample?.timestamp)
        const used = toNumber(sample?.usedMl)
        if (ts == null || used == null) return null
        const reset = lastValue != null && used + resetThreshold < lastValue
        lastValue = used
        return { ts, used, reset }
      })
      .filter(Boolean)
  }

  const preferredTank = normalizeSeries(
    [...tankSamples]
      .filter((sample) => toNumber(sample?.timestamp) != null && sample.timestamp >= cutoff)
      .sort((a, b) => a.timestamp - b.timestamp),
  )
  if (preferredTank.length) return preferredTank

  const inWindowLevels = levelSamples.filter((sample) => toNumber(sample?.timestamp) != null && sample.timestamp >= cutoff)
  const selectedLevels = inWindowLevels.length ? inWindowLevels : levelSamples.slice(-tailLimit)
  const normalizedLevels = normalizeSeries(selectedLevels)
  if (normalizedLevels.length) return normalizedLevels

  const fallbackRuns = Array.isArray(options.fallbackRuns) ? options.fallbackRuns : []
  const runtimeMsToMilliliters =
    typeof options.runtimeMsToMilliliters === 'function' ? options.runtimeMsToMilliliters : (duration) => duration / 1000

  let cumulative = 0
  return fallbackRuns
    .map((run) => {
      const ts = parseTimestampMs(run?.recorded_at)
      if (ts == null || ts < cutoff) return null
      const duration = Math.max(0, toNumber(run?.duration_ms) ?? 0)
      const volume = Math.max(0, toNumber(runtimeMsToMilliliters(duration)) ?? 0)
      const reset = Boolean(run?.is_reset_event)
      if (reset) {
        cumulative = 0
      }
      cumulative += volume
      return { ts, used: cumulative, reset }
    })
    .filter(Boolean)
}

const normalizeThermistors = (list = []) => {
  if (!Array.isArray(list)) return []
  return list
    .map((probe, index) => {
      if (probe == null) return null
      if (typeof probe === 'number' && Number.isFinite(probe)) {
        return {
          label: `Probe ${index + 1}`,
          value: Number(probe.toFixed(2)),
        }
      }
      if (typeof probe === 'object') {
        const labelCandidate = [probe.label, probe.sensor].find(
          (entry) => typeof entry === 'string' && entry.trim(),
        )
        const numeric = toNumber(
          probe.value ?? probe.value_c ?? probe.c ?? probe.temp ?? probe.temp_c ?? probe.reading,
        )
        if (numeric == null) return null
        return {
          label: labelCandidate ?? `Probe ${index + 1}`,
          value: Number(numeric.toFixed(2)),
        }
      }
      return null
    })
    .filter(Boolean)
}

export const normalizeTemperatureHistorySamples = (entries = [], options = {}) => {
  const moduleKey = options.moduleKey ?? 'module_id'
  return (entries ?? [])
    .map((entry) => {
      const timestamp = parseTimestampMs(entry?.timestamp ?? entry?.timestamp_ms ?? entry?.recorded_at)
      const thermistors = normalizeThermistors(entry?.thermistors)
      if (timestamp == null || !thermistors.length) {
        return null
      }
      return {
        timestamp,
        moduleId: entry?.[moduleKey] ?? entry?.moduleId ?? entry?.module ?? 'unknown',
        setpoint: toNumber(entry?.setpoint ?? entry?.setpoint_c),
        heaterOn: Boolean(entry?.heater_on ?? entry?.heaterOn),
        thermistors,
      }
    })
    .filter(Boolean)
    .sort((a, b) => a.timestamp - b.timestamp)
}

export const alignSamplesByResolution = (entries = [], resolutionMs = 15_000) => {
  if (!Array.isArray(entries) || !entries.length || !resolutionMs || resolutionMs <= 0) {
    return entries ?? []
  }
  const span = Math.max(1, resolutionMs)
  const collapsed = []
  let lastBucket = null
  for (const sample of entries) {
    const timestamp = toNumber(sample?.timestamp)
    if (timestamp == null) continue
    const bucket = Math.floor(timestamp / span)
    if (bucket === lastBucket && collapsed.length) {
      collapsed[collapsed.length - 1] = sample
    } else {
      collapsed.push(sample)
      lastBucket = bucket
    }
  }
  return collapsed
}

export const computePaddedRange = (values = [], options = {}) => {
  const numericValues = (Array.isArray(values) ? values : [])
    .map((value) => toNumber(value))
    .filter((value) => value != null)

  if (!numericValues.length) {
    return { min: undefined, max: undefined, padding: 0 }
  }

  const minPadding = toNumber(options.minPadding) ?? 0
  const fallbackPadding = toNumber(options.fallbackPadding) ?? minPadding
  const paddingRatio = toNumber(options.paddingRatio) ?? 0
  const minValue = Math.min(...numericValues)
  const maxValue = Math.max(...numericValues)
  const spread = maxValue - minValue
  const computedPadding = spread > 0 ? spread * paddingRatio : fallbackPadding
  const padding = Math.max(minPadding, computedPadding)

  return {
    min: minValue - padding,
    max: maxValue + padding,
    padding,
  }
}

export const buildHeaterActivationSeries = (samples = [], range = {}, options = {}) => {
  if (!Array.isArray(samples) || !samples.length) return []
  const yMin = toNumber(range.min)
  const yMax = toNumber(range.max)
  const padding = toNumber(range.padding) ?? 0
  if (yMin == null || yMax == null) return []

  const activationInsetRatio = toNumber(options.insetRatio) ?? 0.2
  const high = yMax - padding * activationInsetRatio
  const low = yMin + padding * activationInsetRatio

  return samples
    .map((sample) => {
      const timestamp = toNumber(sample?.timestamp)
      if (timestamp == null) return null
      return {
        x: timestamp,
        y: sample?.heaterState ? high : low,
        heaterOn: Boolean(sample?.heaterState),
      }
    })
    .filter(Boolean)
}

export const buildVerticalMarkerSegments = (markers = [], maxValue) => {
  const yMax = toNumber(maxValue)
  if (!Array.isArray(markers) || !markers.length || yMax == null || yMax <= 0) return []
  const data = []
  markers.forEach((marker) => {
    const ts = toNumber(marker?.ts)
    if (ts == null) return
    data.push({ x: ts, y: 0 })
    data.push({ x: ts, y: yMax })
    data.push({ x: null, y: null })
  })
  return data
}
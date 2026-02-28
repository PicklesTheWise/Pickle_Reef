<script>
  import TouchChartFrame from '$lib/TouchChartFrame.svelte'

  export let samples = []
  export let windowMs = 60 * 60 * 1000
  export let height = 150

  const VIEW_WIDTH = 1000
  const VIEW_HEIGHT = 260
  const ACTIVATION_BAND = 34
  const TEMP_1_COLOR = '#4dd0e1'
  const TEMP_2_COLOR = '#ffd166'
  const ACTIVATION_COLOR = '#ffb347'
  const SETPOINT_COLOR = '#fefefe'

  const formatTime = (timestamp) => {
    if (!timestamp) return '--'
    try {
      return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch (err) {
      return '--'
    }
  }

  $: sortedSamples = [...(samples ?? [])].sort((a, b) => a.timestamp - b.timestamp)
  $: now = sortedSamples.at(-1)?.timestamp ?? Date.now()
  $: startWindow = now - windowMs
  $: values = sortedSamples.flatMap((sample) => {
    const bucket = []
    if (typeof sample.setpoint === 'number') bucket.push(sample.setpoint)
    const probes = Array.isArray(sample.thermistors) ? sample.thermistors : []
    probes.forEach((probe) => {
      if (typeof probe.value === 'number') bucket.push(probe.value)
    })
    return bucket
  })
  $: yMin = values.length ? Math.min(...values) : 20
  $: yMax = values.length ? Math.max(...values) : 30
  $: padding = Math.max(0.5, (yMax - yMin) * 0.15)
  $: domainMin = yMin - padding
  $: domainMax = yMax + padding
  $: domainSpan = Math.max(1, domainMax - domainMin)

  const toX = (timestamp) => {
    if (!windowMs) return 0
    const clamped = Math.max(0, Math.min(windowMs, timestamp - startWindow))
    return (clamped / windowMs) * VIEW_WIDTH
  }

  const toY = (value) => {
    if (value == null) return VIEW_HEIGHT
    const clamped = Math.max(domainMin, Math.min(domainMax, value))
    const ratio = (clamped - domainMin) / domainSpan
    return VIEW_HEIGHT - ratio * VIEW_HEIGHT
  }

  const buildLinePath = (points = []) => {
    if (!points.length) return ''
    return points
      .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)},${point.y.toFixed(2)}`)
      .join(' ')
  }

  const getProbe = (sample, index) => {
    const probes = Array.isArray(sample?.thermistors) ? sample.thermistors : []
    const candidate = probes[index]
    return typeof candidate?.value === 'number' ? candidate.value : null
  }

  $: temp1Points = sortedSamples
    .map((sample) => {
      const value = getProbe(sample, 0)
      if (value == null) return null
      return { x: toX(sample.timestamp), y: toY(value), value }
    })
    .filter(Boolean)

  $: temp2Points = sortedSamples
    .map((sample) => {
      const value = getProbe(sample, 1)
      if (value == null) return null
      return { x: toX(sample.timestamp), y: toY(value), value }
    })
    .filter(Boolean)

  $: setpointPoints = sortedSamples
    .filter((sample) => typeof sample.setpoint === 'number')
    .map((sample) => ({ x: toX(sample.timestamp), y: toY(sample.setpoint), value: sample.setpoint }))

  $: activationPoints = sortedSamples.map((sample) => ({
    x: toX(sample.timestamp),
    y: sample.heaterOn ? VIEW_HEIGHT - ACTIVATION_BAND : VIEW_HEIGHT,
    active: Boolean(sample.heaterOn),
  }))

  $: hasChartData =
    temp1Points.length > 0 ||
    temp2Points.length > 0 ||
    setpointPoints.length > 0 ||
    activationPoints.length > 0

  $: latestSample = sortedSamples.at(-1) ?? null

  $: midWindow = startWindow + windowMs / 2
</script>

<TouchChartFrame
  isEmpty={!hasChartData}
  emptyText="Waiting for temperature telemetry…"
  {height}
>
  <svelte:fragment slot="chart">
    <svg
      class="temp-chart"
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      preserveAspectRatio="none"
    >
      <g class="grid-lines">
        {#each [0, 0.25, 0.5, 0.75, 1] as ratio}
          <line x1="0" x2={VIEW_WIDTH} y1={VIEW_HEIGHT * ratio} y2={VIEW_HEIGHT * ratio} />
        {/each}
      </g>
      {#if activationPoints.length}
        <path d={buildLinePath(activationPoints)} class="activation-line" stroke={ACTIVATION_COLOR} />
      {/if}
      {#if setpointPoints.length}
        <path d={buildLinePath(setpointPoints)} class="setpoint-line" stroke={SETPOINT_COLOR} />
      {/if}
      {#if temp1Points.length}
        <path d={buildLinePath(temp1Points)} stroke={TEMP_1_COLOR} class="probe-line" />
      {/if}
      {#if temp2Points.length}
        <path d={buildLinePath(temp2Points)} stroke={TEMP_2_COLOR} class="probe-line" />
      {/if}
    </svg>
  </svelte:fragment>

  <svelte:fragment slot="axis">
    <div class="time-axis">
      <span>{formatTime(startWindow)}</span>
      <span>{formatTime(midWindow)}</span>
      <span>{formatTime(now)}</span>
    </div>
  </svelte:fragment>

  <svelte:fragment slot="legend">
    <div class="chart-legend">
      <span class="legend-item" class:muted={!temp1Points.length}>
        <span class="swatch" style={`background:${TEMP_1_COLOR}`}></span>
        Temp 1
      </span>
      <span class="legend-item" class:muted={!temp2Points.length}>
        <span class="swatch" style={`background:${TEMP_2_COLOR}`}></span>
        Temp 2
      </span>
      <span class="legend-item" class:muted={!setpointPoints.length}>
        <span class="swatch" style={`background:${SETPOINT_COLOR}`}></span>
        Setpoint
      </span>
      <span class="legend-item heater" class:muted={!activationPoints.length}>
        <span class="swatch heater"></span>
        Activations
      </span>
    </div>
  </svelte:fragment>
</TouchChartFrame>

<style>
.temp-chart {
  width: 100%;
  height: 100%;
}

.grid-lines line {
  stroke: rgba(255, 255, 255, 0.08);
  stroke-width: 1;
}

.setpoint-line {
  fill: none;
  stroke-width: 2.4;
  stroke-dasharray: 6 6;
}

.activation-line {
  fill: none;
  stroke-width: 2.2;
  stroke-dasharray: 4 5;
  opacity: 0.9;
}

.probe-line {
  fill: none;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.95;
}

.time-axis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.25rem;
  font-size: 0.7rem;
  color: rgba(221, 240, 255, 0.65);
}

.time-axis span:nth-child(2) {
  text-align: center;
}

.time-axis span:last-child {
  text-align: right;
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: rgba(223, 241, 255, 0.85);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.legend-item.muted {
  opacity: 0.45;
}

.swatch {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  display: inline-flex;
}

.swatch.heater {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.8), rgba(255, 193, 7, 0.15));
  border: 1px solid rgba(255, 193, 7, 0.6);
}
</style>

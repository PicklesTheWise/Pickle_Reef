<script>
  import { onDestroy, onMount } from 'svelte'
  import { Chart, registerables } from 'chart.js'

  Chart.register(...registerables)

  export let datasets = []
  export let ariaLabel = 'Line chart'
  export let height = 240
  export let xTickFormatter = (value) => value
  export let yTickFormatter = (value) => value
  export let xTitle = ''
  export let yTitle = ''
  export let tooltipFormatter = null
  export let ySuggestedMax = undefined
  export let tickColor = 'rgba(248, 251, 255, 0.9)'
  export let gridColor = 'rgba(248, 251, 255, 0.15)'
  export let fontSize = 12
  export let fontWeight = '600'
  export let yBeginAtZero = true
  export let showLegend = false
  export let yMin = undefined
  export let yMax = undefined

  let canvas
  let chart

  const buildOptions = () => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { intersect: false, mode: 'index' },
    elements: {
      line: {
        borderWidth: 2.5,
        cubicInterpolationMode: 'monotone',
      },
      point: {
        radius: 0,
        hoverRadius: 3,
        hitRadius: 10,
      },
    },
    scales: {
      x: {
        type: 'linear',
        grid: { color: gridColor, lineWidth: 0.5 },
        ticks: {
          color: tickColor,
          callback: (value) => (xTickFormatter ? xTickFormatter(Number(value)) : value),
          maxRotation: 0,
          autoSkipPadding: 12,
          font: { size: fontSize, weight: fontWeight },
        },
        title: {
          display: Boolean(xTitle),
          text: xTitle,
          color: tickColor,
          font: { size: fontSize + 2, weight: fontWeight },
        },
      },
      y: {
        beginAtZero: yBeginAtZero,
        min: yMin,
        max: yMax,
        grid: { color: gridColor, lineWidth: 0.5 },
        ticks: {
          color: tickColor,
          callback: (value) => (yTickFormatter ? yTickFormatter(Number(value)) : value),
          font: { size: fontSize, weight: fontWeight },
        },
        title: {
          display: Boolean(yTitle),
          text: yTitle,
          color: tickColor,
          font: { size: fontSize + 2, weight: fontWeight },
        },
        suggestedMax: ySuggestedMax,
      },
    },
    plugins: {
      legend: {
        display: showLegend,
        labels: {
          color: tickColor,
          font: { size: fontSize * 0.9, weight: fontWeight },
          usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(2, 7, 16, 0.95)',
        borderColor: tickColor,
        borderWidth: 1,
        titleColor: tickColor,
        bodyColor: tickColor,
        bodyFont: { size: fontSize },
        titleFont: { size: fontSize + 1 },
        callbacks: tooltipFormatter
          ? {
              label(context) {
                return tooltipFormatter(context)
              },
            }
          : {},
      },
    },
  })

  onMount(() => {
    chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: datasets ?? [] },
      options: buildOptions(),
    })
  })

  onDestroy(() => {
    chart?.destroy()
    chart = null
  })

  $: if (chart) {
    chart.data.datasets = datasets ?? []
    const updatedOptions = buildOptions()
    // Merge options rather than replacing the object, so Chart.js
    // reliably picks up scale min/max changes on each update.
    chart.options.animation = updatedOptions.animation
    chart.options.interaction = updatedOptions.interaction
    chart.options.elements = updatedOptions.elements
    chart.options.plugins = updatedOptions.plugins
    const yScale = chart.options.scales.y
    yScale.beginAtZero = updatedOptions.scales.y.beginAtZero
    yScale.min = updatedOptions.scales.y.min
    yScale.max = updatedOptions.scales.y.max
    yScale.suggestedMax = updatedOptions.scales.y.suggestedMax
    chart.update('none')
  }
</script>

<div class="chart-shell" style={`height: ${height}px;`} role="img" aria-label={ariaLabel}>
  <canvas bind:this={canvas} aria-label={ariaLabel}></canvas>
</div>

<style>
  .chart-shell {
    width: 100%;
  }

  canvas {
    width: 100% !important;
    height: 100% !important;
  }
</style>

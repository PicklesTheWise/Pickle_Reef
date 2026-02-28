<script>
  import TouchChartFrame from '$lib/TouchChartFrame.svelte'

  export let buckets = []
  export let height = 150
  export let barColor = '#73ffba'
  export let lineColor = '#ffd166'

  const BAR_WIDTH = 22
  const BAR_GAP = 10

  $: sanitizedBuckets = Array.isArray(buckets) ? buckets : []
  $: bucketCount = sanitizedBuckets.length
  $: chartWidth = Math.max(1, bucketCount * (BAR_WIDTH + BAR_GAP) + BAR_GAP)
  $: maxCount = Math.max(1, ...sanitizedBuckets.map((bucket) => Number(bucket?.count) || 0))
  $: maxUsage = Math.max(1, ...sanitizedBuckets.map((bucket) => Number(bucket?.usage) || 0))

  const resolveBarHeight = (value) => {
    if (!value || maxCount === 0) return 0
    return (value / maxCount) * (height - 20)
  }

  const resolveUsageY = (value) => {
    if (!value || maxUsage === 0) return height - 20
    const ratio = value / maxUsage
    return Math.min(height - 5, Math.max(5, height - 20 - (height - 40) * ratio))
  }

  $: linePoints = sanitizedBuckets
    .map((bucket, index) => {
      const centerX = BAR_GAP + index * (BAR_WIDTH + BAR_GAP) + BAR_WIDTH / 2
      const usageValue = Number(bucket?.usage) || 0
      const y = resolveUsageY(usageValue)
      return `${centerX},${y.toFixed(2)}`
    })
    .join(' ')
</script>

<TouchChartFrame isEmpty={!sanitizedBuckets.length} emptyText="No activity yet." {height}>
  <svelte:fragment slot="chart">
    <svg
      viewBox={`0 0 ${chartWidth} ${height}`}
      preserveAspectRatio="none"
      class="usage-chart"
    >
      {#each sanitizedBuckets as bucket, index}
        {#if bucket?.count}
          <rect
            x={BAR_GAP + index * (BAR_WIDTH + BAR_GAP)}
            y={height - 20 - resolveBarHeight(bucket.count)}
            width={BAR_WIDTH}
            height={resolveBarHeight(bucket.count)}
            fill={barColor}
            opacity="0.85"
            rx="4"
          />
        {/if}
      {/each}
      {#if sanitizedBuckets.some((bucket) => bucket?.usage)}
        <polyline
          points={linePoints}
          fill="none"
          stroke={lineColor}
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      {/if}
    </svg>
  </svelte:fragment>

  <svelte:fragment slot="axis">
    <div class="usage-axis">
      {#each sanitizedBuckets as bucket}
        <span>{bucket?.label ?? ''}</span>
      {/each}
    </div>
  </svelte:fragment>
</TouchChartFrame>

<style>
.usage-chart {
  width: 100%;
  height: 100%;
}

.usage-axis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(28px, 1fr));
  gap: 0.25rem;
  font-size: 0.7rem;
  color: rgba(221, 240, 255, 0.65);
  text-align: center;
}
</style>

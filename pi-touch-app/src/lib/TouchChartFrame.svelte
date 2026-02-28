<script>
  export let isEmpty = false
  export let emptyText = 'No data yet.'
  export let height = 180
</script>

<div class="touch-chart-frame">
  {#if isEmpty}
    <p class="chart-empty">{emptyText}</p>
  {:else}
    <div class="chart-surface" style={`height:${height}px`}>
      <slot name="chart" />
    </div>
    <div class="chart-axis">
      <slot name="axis" />
    </div>
    <div class="chart-legend">
      <slot name="legend" />
    </div>
  {/if}
</div>

<style>
.touch-chart-frame {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chart-surface {
  width: 100%;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(5, 15, 32, 0.9);
  overflow: hidden;
}

.chart-axis {
  min-height: 0.95rem;
}

.chart-legend {
  min-height: 0.95rem;
}

.chart-empty {
  margin: 0;
  padding: 1rem;
  text-align: center;
  color: rgba(221, 240, 255, 0.7);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 16px;
  font-size: 0.85rem;
}
</style>
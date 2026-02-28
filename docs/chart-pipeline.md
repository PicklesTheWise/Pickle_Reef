# Chart Pipeline (Maintainer Guide)

Use a single data-transform pipeline for all chart data used by both dashboards.

## Source of truth
- Shared implementation: [shared/chartPipeline.js](../shared/chartPipeline.js)
- Frontend wrapper: [frontend/src/lib/chartPipeline.js](../frontend/src/lib/chartPipeline.js)
- Touch wrapper: [pi-touch-app/src/lib/usageBuckets.js](../pi-touch-app/src/lib/usageBuckets.js)

## Contract
- Input to pipeline functions should be raw API/trace/cycle arrays.
- Pipeline functions return normalized series/buckets for chart components.
- UI components should render only; they should not re-implement parsing/bucketing.

## Existing standard functions
- `deriveLatestUsageTimestamp(...)`
- `createUsageBuckets(options)`
- `assignActivationRuns(meta, runs, options)`
- `assignSpoolUsage(meta, entries)`
- `assignAtoUsageFromTrace(meta, entries)`
- `finalizeBuckets(meta)`
- `buildUsageSeriesPreferLevels(options)`
- `buildAtoUsageSeries(options)`
- `findRecentResetTimestamp(samples, options)`
- `normalizeTemperatureHistorySamples(entries, options)`
- `alignSamplesByResolution(entries, resolutionMs)`
- `computePaddedRange(values, options)`
- `buildHeaterActivationSeries(samples, range, options)`
- `buildVerticalMarkerSegments(markers, maxValue)`

## How to add a new chart transform
1. Add the transform to [shared/chartPipeline.js](../shared/chartPipeline.js).
2. Keep it framework-agnostic (plain JS, no Svelte imports or DOM usage).
3. Export it through wrappers:
   - [frontend/src/lib/chartPipeline.js](../frontend/src/lib/chartPipeline.js)
   - [pi-touch-app/src/lib/usageBuckets.js](../pi-touch-app/src/lib/usageBuckets.js)
4. Consume it in UI routes/components; avoid local duplicate parsing logic.
5. Validate both apps build:
   - `cd frontend && npm run build`
   - `cd pi-touch-app && npm run build`

## Rules for future charts
- Prefer trace/history sources over inferred/fallback values when available.
- Keep fallback behavior explicit in the pipeline (not spread across UI files).
- Keep timestamp parsing and reset-detection logic centralized in shared pipeline code.
- If a transform changes shape, update both wrappers in the same PR.

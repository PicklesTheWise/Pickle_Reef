<script>
  import { createEventDispatcher } from 'svelte'

  export let label = ''
  export let description = ''
  export let buttons = []
  export let activeValue = null
  export let disabled = false
  export let ariaLabel = undefined

  const dispatch = createEventDispatcher()

  const handleSelect = (value) => {
    if (disabled || value === activeValue) return
    dispatch('select', value)
  }

  let hasControlsSlot = false
  let hasMetaSlot = false

  $: hasControlsSlot = Boolean($$slots.controls)
  $: hasMetaSlot = Boolean($$slots.meta)
</script>

<section class="roller-chart chart-widget" aria-label={ariaLabel}>
  <div class="chart-widget__toolbar">
    <div class="chart-widget__label window-label">
      {#if label}
        <p>{label}</p>
      {/if}
      {#if description}
        <small>{description}</small>
      {/if}
    </div>
    {#if buttons?.length}
      <div class="window-buttons">
        {#each buttons as button (button.value)}
          <button
            type="button"
            class:active={button.value === activeValue}
            title={button.description}
            on:click={() => handleSelect(button.value)}
          >
            {button.label}
          </button>
        {/each}
      </div>
    {/if}
    {#if hasControlsSlot}
      <div class="chart-widget__controls">
        <slot name="controls" />
      </div>
    {/if}
  </div>
  <div class="chart-widget__body">
    <slot />
  </div>
  {#if hasMetaSlot}
    <div class="chart-widget__meta">
      <slot name="meta" />
    </div>
  {/if}
</section>

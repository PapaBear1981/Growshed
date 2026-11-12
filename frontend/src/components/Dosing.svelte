<script>
  // pH and nutrient dosing pumps. The hub and the dosing node enforce every limit; this
  // page asks, shows what was refused and why, and makes turning on automatic dosing a
  // deliberate act.
  import { createEventDispatcher, onMount } from 'svelte';
  import { control, values, nodes, now, command } from '../lib/stores.js';
  import { nodeDown } from '../lib/format.js';

  const dispatch = createEventDispatcher();
  const MODES = [
    { id: 'off', label: 'Off' },
    { id: 'suggest', label: 'Suggest' },
    { id: 'auto', label: 'Automatic' },
  ];
  const EXPLAIN = {
    off: 'Off: nothing is dosed unless you press a button below.',
    suggest: 'Suggest: the hub proposes one small dose at a time and waits for you to approve it.',
    auto: 'Automatic: the hub doses by itself, within the limits.',
  };
  const MANUAL = [
    { kind: 'ph_down', label: 'pH down', amount: 'ph' },
    { kind: 'ph_up', label: 'pH up', amount: 'ph' },
    { kind: 'nutrients', label: 'Nutrients A + B', amount: 'nutrients' },
  ];

  let message = '';
  let confirming = false; // the "are you sure" box for automatic mode
  let measured = {}; // pump -> mL typed in after a timed run
  let pumpNote = {};
  let cancelButton;

  $: d = $control.dosing;

  // Bottle levels: capacity entered at refill, minus everything dosed since.
  let bottles = [];
  let capacity = {};
  async function loadBottles() {
    try {
      bottles = await (await fetch('/api/bottles')).json();
    } catch (err) {
      bottles = [];
    }
  }
  async function refill(pump) {
    const ml = Number(capacity[pump]);
    if (!(ml > 0)) {
      pumpNote[pump] = 'Enter the bottle size in mL.';
      return;
    }
    pumpNote[pump] = await command('/api/bottles', { pump: pump, capacity_ml: ml });
    loadBottles();
  }
  const bottleOf = (list, pump) => list.find((b) => b.pump === pump) || {};
  onMount(loadBottles);
  $: $control, loadBottles();
  $: offline = nodeDown($nodes.dosing, $now);

  async function send(path, body) {
    message = await command(path, body);
    if (!message) dispatch('dosed');
  }
  function choose(mode) {
    if (mode === 'auto' && d.mode !== 'auto') {
      confirming = true; // nothing is sent until the person presses Continue
      setTimeout(() => cancelButton && cancelButton.focus(), 0);
    } else {
      send('/api/dosing/mode', { mode: mode });
    }
  }
  function confirmAuto() {
    confirming = false;
    send('/api/dosing/mode', { mode: 'auto', acknowledged: true });
  }
  function onKey(event) {
    if (confirming && event.key === 'Escape') confirming = false;
  }

  const RUN_S = 30;
  async function runPump(pump, seconds) {
    pumpNote[pump] = await command('/api/dosing/prime', { pump: pump, seconds: seconds });
    if (!pumpNote[pump] && seconds === RUN_S) pumpNote[pump] = 'Running for 30 seconds. When it stops, read the cup and enter the mL below.';
  }
  async function saveRate(pump) {
    const ml = Number(measured[pump]);
    if (!(ml > 0)) {
      pumpNote[pump] = 'Enter how many mL the pump delivered in 30 seconds.';
      return;
    }
    pumpNote[pump] = await command('/api/dosing/rate', { pump: pump, ml: ml, seconds: RUN_S });
    if (!pumpNote[pump]) {
      pumpNote[pump] = 'Saved.';
      measured[pump] = '';
    }
  }
  const running = (all, pump) => all['dosing/switch/' + pump] && all['dosing/switch/' + pump].value === true;
</script>

<svelte:window on:keydown={onKey} />

{#if d}
  <h3>Dosing pumps</h3>
  <div class="segmented" role="group" aria-label="Dosing mode">
    {#each MODES as m (m.id)}
      <button class:selected={d.mode === m.id} class:auto={m.id === 'auto' && d.mode === 'auto'} aria-pressed={d.mode === m.id} on:click={() => choose(m.id)}>{m.label}</button>
    {/each}
  </div>
  <p class="hint">
    {EXPLAIN[d.mode]} Targets: pH {d.targets.ph_low} to {d.targets.ph_high}; nutrients are added below EC
    {(d.targets.ec_low / 1000).toFixed(2)} mS/cm.
  </p>

  {#if offline}<p class="warn">The dosing node is offline.</p>{/if}
  {#if d.locked}
    <div class="stopped">
      <b>Dosing is stopped:</b> {d.locked}. Find and fix the cause first.
      <button class="plain" on:click={() => send('/api/dosing/unlock')}>Re-enable dosing</button>
    </div>
  {:else if d.mode !== 'off' && d.blocked}
    <p class="hint">Not dosing right now: {d.blocked}.</p>
  {/if}

  {#if d.suggestion}
    <div class="suggestion">
      <div>
        <b>Suggested: add {d.suggestion.ml} mL of {d.suggestion.label}</b>
        <div class="hint">{d.suggestion.why}. Everything is checked again when you approve.</div>
      </div>
      <div class="buttons">
        <button class="primary" on:click={() => send('/api/dosing/approve')}>Approve</button>
        <button class="plain" on:click={() => send('/api/dosing/dismiss')}>Not now</button>
      </div>
    </div>
  {/if}

  <div class="buttons manual">
    {#each MANUAL as m (m.kind)}
      <button class="plain" disabled={offline} on:click={() => send('/api/dosing/manual', { kind: m.kind })}>
        Dose {m.label} ({d.doses[m.amount]} mL{m.kind === 'nutrients' ? ' each' : ''})
      </button>
    {/each}
  </div>
  {#if message}<p class="bad">{message}</p>{/if}

  <details>
    <summary>Pumps and flow calibration</summary>
    <p class="hint">
      A pump must be calibrated before it can dose. Put the pump's outlet tube in a measuring cup
      (<b>not in the reservoir</b>), press <b>Run 30 s</b>, then enter how many mL came out.
      Use <b>Prime</b> the same way to fill a new tube.
    </p>
    {#each d.pumps as p (p.pump)}
      <div class="pump">
        <div>
          <b>{p.label}</b>
          <span class="chip" class:on={running($values, p.pump)}>{running($values, p.pump) ? 'RUNNING' : 'idle'}</span>
          <div class="hint">
            {p.rate > 0 ? p.rate.toFixed(2) + ' mL per second' : 'not calibrated'} · {p.day_ml} of {d.max_day_ml} mL used today
          </div>
          <div class="hint" class:bad={bottleOf(bottles, p.pump).low}>
            {bottleOf(bottles, p.pump).capacity_ml ? 'Bottle: about ' + bottleOf(bottles, p.pump).left_ml + ' of ' + bottleOf(bottles, p.pump).capacity_ml + ' mL left' : 'Bottle size not entered'}
          </div>
        </div>
        <div class="buttons">
          <button class="plain" disabled={offline} on:click={() => runPump(p.pump, 5)}>Prime 5 s</button>
          <button class="plain" disabled={offline} on:click={() => runPump(p.pump, RUN_S)}>Run 30 s</button>
          <label>mL in 30 s <input type="number" min="0" step="0.5" bind:value={measured[p.pump]} /></label>
          <button class="plain" on:click={() => saveRate(p.pump)}>Save</button>
          <label>Bottle mL <input type="number" min="0" step="50" bind:value={capacity[p.pump]} /></label>
          <button class="plain" on:click={() => refill(p.pump)}>Refilled</button>
        </div>
      </div>
      {#if pumpNote[p.pump]}<p class="hint" class:bad={pumpNote[p.pump].indexOf('Saved') < 0 && pumpNote[p.pump].indexOf('Running') < 0}>{pumpNote[p.pump]}</p>{/if}
    {/each}
  </details>
{/if}

{#if confirming}
  <div class="overlay">
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="auto-title" aria-describedby="auto-text">
      <h2 id="auto-title">Turn on automatic dosing?</h2>
      <div id="auto-text">
        <p><b>Incorrect dosing can kill your plants.</b> In automatic mode the system adds pH adjuster and nutrients to the reservoir by itself, with nobody checking each dose.</p>
        <p>It relies on low-cost probes that drift and can fail. The built-in limits reduce the risk; they cannot remove it.</p>
        <p>Only continue if:</p>
        <ul>
          <li>the pH and EC probes were calibrated recently and agree with a handheld meter;</li>
          <li>every pump's flow was measured and its tube goes to the right bottle;</li>
          <li>you have used <b>Suggest</b> mode long enough to trust what it proposes.</li>
        </ul>
      </div>
      <div class="buttons end">
        <button class="plain" bind:this={cancelButton} on:click={() => (confirming = false)}>Cancel</button>
        <button class="danger" on:click={confirmAuto}>Continue</button>
      </div>
    </div>
  </div>
{/if}

<style>
  h3 {
    margin: 18px 0 8px;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }
  .hint {
    margin: 6px 0;
    color: var(--muted);
    font-size: 0.88rem;
  }
  .bad {
    color: var(--bad);
  }
  .warn {
    color: var(--warn);
    font-weight: 600;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-width: 84px;
    min-height: 44px;
    border: 0;
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button.selected {
    background: var(--accent);
    color: var(--bg);
  }
  .segmented button.selected.auto {
    background: var(--warn);
    color: #fff;
  }
  .stopped,
  .suggestion {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    margin: 10px 0;
    padding: 12px;
    border-radius: 10px;
    border-left: 6px solid var(--bad);
    background: var(--bad-bg);
  }
  .suggestion {
    border-left-color: var(--accent);
    background: var(--on-bg);
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
  }
  .buttons > * {
    margin: 4px 8px 4px 0;
  }
  .buttons.end {
    justify-content: flex-end;
    margin-top: 12px;
  }
  .manual {
    margin-top: 8px;
  }
  button.plain,
  button.primary,
  button.danger {
    min-height: 44px;
    padding: 0 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--off-bg);
    font-weight: 600;
    cursor: pointer;
  }
  button.primary {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--bg);
  }
  button.danger {
    border-color: var(--bad);
    background: var(--bad);
    color: #fff;
  }
  button:disabled {
    opacity: 0.45;
    cursor: default;
  }
  details {
    margin-top: 10px;
  }
  summary {
    min-height: 44px;
    line-height: 44px;
    cursor: pointer;
    font-weight: 600;
  }
  .pump {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    padding: 8px 0;
    border-top: 1px solid var(--line);
  }
  .chip {
    margin-left: 6px;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--off-bg);
    color: var(--muted);
  }
  .chip.on {
    background: var(--on-bg);
    color: var(--good);
  }
  label {
    font-size: 0.8rem;
    color: var(--muted);
  }
  input {
    display: block;
    width: 90px;
    min-height: 44px;
    padding: 0 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  .overlay {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    background: rgba(0, 0, 0, 0.55);
  }
  .dialog {
    max-width: 520px;
    max-height: 100%;
    overflow-y: auto;
    padding: 20px;
    border-radius: 14px;
    border: 2px solid var(--bad);
    background: var(--card);
    color: var(--text);
  }
  .dialog h2 {
    margin: 0 0 10px;
    font-size: 1.2rem;
  }
  .dialog p,
  .dialog ul {
    margin: 0 0 10px;
  }
  .dialog ul {
    padding-left: 20px;
  }
</style>

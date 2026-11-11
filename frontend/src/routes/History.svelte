<script>
  // One measure per chart (never two y-axes), one line per sensor, shared time axis.
  import { onMount, onDestroy } from 'svelte';
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { config, settings } from '../lib/stores.js';

  const MEASURES = [
    { kind: 'temperature', label: 'Temperature' },
    { kind: 'humidity', label: 'Humidity' },
    { kind: 'illuminance', label: 'Light' },
    { kind: 'soil_moisture', label: 'Soil moisture' },
    { kind: 'ph', label: 'pH' },
    { kind: 'ec', label: 'EC' },
  ];
  const RANGES = [
    { hours: 6, label: '6 h' },
    { hours: 24, label: '24 h' },
    { hours: 168, label: '7 d' },
    { hours: 720, label: '30 d' },
  ];

  let kind = 'temperature';
  let hours = 24;
  let host;
  let plot = null;
  let status = 'Loading…';
  let timer;
  let requestId = 0;

  const zoneName = (id) => $config.zones.find((z) => z.id === id).name;
  // Colour is tied to the sensor's position in config.yaml, so it never changes
  // when the range or the data does.
  $: sensors = $config.sensors.filter((s) => s.component === 'sensor' && s.kind === kind);
  // Only offer measures that have sensors in config.yaml.
  $: measures = MEASURES.filter((m) => $config.sensors.some((s) => s.kind === m.kind));
  $: unit = kind === 'temperature' ? ($settings.display_units === 'imperial' ? '°F' : '°C') : kind === 'illuminance' ? 'lx' : kind === 'ph' ? 'pH' : kind === 'ec' ? 'mS/cm' : '%';
  $: decimals = kind === 'illuminance' ? 0 : kind === 'ph' || kind === 'ec' ? 2 : 1;
  $: chemistry = kind === 'ph' || kind === 'ec';
  let doses = []; // manual additions inside the charted range, drawn as markers
  // EC is stored in µS/cm and charted in mS/cm.
  $: convert = kind === 'temperature' && $settings.display_units === 'imperial' ? (v) => (v * 9) / 5 + 32 : kind === 'ec' ? (v) => v / 1000 : (v) => v;

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // A dashed vertical line at each logged addition, so its effect on the curve is visible.
  function drawDoses(u) {
    if (!chemistry || !doses.length) return;
    const ctx = u.ctx;
    ctx.save();
    ctx.strokeStyle = css('--muted');
    ctx.lineWidth = Math.max(1, devicePixelRatio || 1);
    ctx.setLineDash([6, 6]);
    doses.forEach((d) => {
      const x = Math.round(u.valToPos(d.ts, 'x', true));
      if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
      ctx.beginPath();
      ctx.moveTo(x, u.bbox.top);
      ctx.lineTo(x, u.bbox.top + u.bbox.height);
      ctx.stroke();
    });
    ctx.restore();
  }

  function draw(body) {
    const keys = sensors.map((s) => s.node + '/sensor/' + s.key);
    const data = [body.t].concat(
      keys.map((k) => body.series[k].map((v) => (v === null ? null : convert(v))))
    );
    const hasData = data.slice(1).some((col) => col.some((v) => v !== null));
    status = hasData ? '' : kind === 'soil_moisture'
        ? 'No soil history to show. Soil sensors appear here once they are calibrated (System page).'
        : chemistry
        ? 'Nothing to show. pH and EC appear here once the probes are calibrated (System page).'
        : 'No history for this range yet. Readings are saved from the moment the hub starts.';
    if (plot) plot.destroy();
    plot = null;
    if (!hasData || !host) return;
    const axis = { stroke: css('--muted'), grid: { stroke: css('--grid'), width: 1 }, ticks: { show: false } };
    plot = new uPlot(
      {
        width: host.clientWidth,
        height: Math.max(240, Math.min(420, Math.round(window.innerHeight * 0.5))),
        cursor: { points: { size: 9 } },
        hooks: { draw: [drawDoses] },
        scales: { x: { time: true } },
        axes: [axis, Object.assign({ size: 56, values: (u, ticks) => ticks.map((t) => t + ' ' + unit) }, axis)],
        series: [{}].concat(
          sensors.map((s, i) => ({
            label: zoneName(s.zone) + ' · ' + s.name,
            stroke: css('--series-' + ((i % 6) + 1)),
            width: 2,
            spanGaps: false,
            points: { show: false },
            value: (u, v) => (v === null || v === undefined ? '—' : v.toFixed(decimals) + ' ' + unit),
          }))
        ),
      },
      data,
      host
    );
  }

  async function load() {
    if (!sensors.length) {
      status = 'No sensors of this kind are configured.';
      return;
    }
    const mine = ++requestId;
    const end = Math.floor(Date.now() / 1000);
    const keys = sensors.map((s) => s.node + '/sensor/' + s.key).join(',');
    try {
      const res = await fetch('/api/history?keys=' + encodeURIComponent(keys) + '&start=' + (end - hours * 3600) + '&end=' + end);
      if (!res.ok) throw new Error('bad response');
      const body = await res.json();
      doses = [];
      if (chemistry) {
        const zones = sensors.map((s) => s.zone);
        const all = await (await fetch('/api/doses?since=' + (end - hours * 3600))).json();
        doses = all.filter((d) => zones.indexOf(d.zone) >= 0);
      }
      if (mine === requestId) draw(body); // ignore answers to an older selection
    } catch (err) {
      if (mine === requestId) status = 'Could not load history from the hub.';
    }
  }

  // Reload when the measure, range or units change.
  $: kind, hours, $settings.display_units, host && load();

  function onResize() {
    if (plot && host) plot.setSize({ width: host.clientWidth, height: plot.height });
  }

  onMount(() => {
    timer = setInterval(load, 60000);
    window.addEventListener('resize', onResize);
  });
  onDestroy(() => {
    clearInterval(timer);
    window.removeEventListener('resize', onResize);
    if (plot) plot.destroy();
  });
</script>

<div class="controls">
  <div class="segmented" role="group" aria-label="Measure">
    {#each measures as m (m.kind)}
      <button class:selected={kind === m.kind} aria-pressed={kind === m.kind} on:click={() => (kind = m.kind)}>{m.label}</button>
    {/each}
  </div>
  <div class="segmented" role="group" aria-label="Time range">
    {#each RANGES as r (r.hours)}
      <button class:selected={hours === r.hours} aria-pressed={hours === r.hours} on:click={() => (hours = r.hours)}>{r.label}</button>
    {/each}
  </div>
</div>

<section class="card">
  {#if status}<p class="status">{status}</p>{/if}
  <div class="chart" bind:this={host}></div>
  {#if chemistry && doses.length}
    <p class="hint">Dashed lines mark what you added: {doses.slice(0, 6).map((d) => d.product + ' ' + d.amount + ' ' + d.unit).join(', ')}{doses.length > 6 ? ', …' : ''}.</p>
  {/if}
  <p class="hint">Touch or hover the chart to read values. Tap a name in the legend to hide or show that line.</p>
</section>

<style>
  .controls {
    display: flex;
    flex-wrap: wrap;
    margin: -6px -6px 10px;
  }
  .segmented {
    display: inline-flex;
    margin: 6px;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
    background: var(--card);
  }
  .segmented button {
    min-height: 44px;
    padding: 0 14px;
    border: 0;
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button.selected {
    background: var(--accent);
    color: var(--bg);
  }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 12px;
  }
  .status,
  .hint {
    margin: 6px 4px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .chart {
    width: 100%;
    overflow: hidden;
  }
  /* uPlot's legend: readable ink for names and values, colour only on the swatch. */
  .chart :global(.u-legend) {
    text-align: left;
    color: var(--text);
    font-size: 0.85rem;
  }
  .chart :global(.u-legend .u-series) {
    display: inline-block;
    padding: 6px 10px 6px 0;
  }
  .chart :global(.u-legend .u-marker) {
    width: 14px;
    height: 4px;
    border-radius: 2px;
  }
</style>

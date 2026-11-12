<script>
  // Grow history: every grow, past and present, with what the conditions were and how it
  // turned out. Finished grows keep their numbers forever.
  import { onMount } from 'svelte';
  import { config, settings, command } from '../lib/stores.js';
  import { formatReading } from '../lib/format.js';

  let grows = [];
  let details = {}; // id -> grow with summary
  let open = {};
  let profiles = [];
  let message = '';
  let ending = {}; // id -> { yield_g, notes } while the "end" form is open
  const today = () => new Date().toISOString().slice(0, 10);
  let form = { name: '', zone: '', crop: '', started: today(), applyProfile: true };

  const json = async (path) => (await fetch(path)).json();
  const zoneName = (id) => {
    const zone = $config.zones.find((z) => z.id === id);
    return zone ? zone.name : id;
  };
  const day = (ts) => new Date(ts * 1000).toLocaleDateString();
  const days = (g) => Math.max(1, Math.round(((g.ended_at || Date.now() / 1000) - g.started_at) / 86400));
  $: tents = $config.zones.filter((z) => z.kind === 'tent');
  $: running = grows.filter((g) => !g.ended_at);
  $: finished = grows.filter((g) => g.ended_at);

  async function load() {
    try {
      grows = await json('/api/grows');
      profiles = (await json('/api/tunables')).profiles;
      // Running grows always show their live numbers.
      for (const g of grows.filter((x) => !x.ended_at)) details[g.id] = await json('/api/grows/' + g.id);
      details = details;
    } catch (err) {
      message = 'Could not load the grows from the hub.';
    }
  }
  onMount(load);

  async function start() {
    if (!form.name.trim() || !form.zone) {
      message = 'Give the grow a name and choose its tent.';
      return;
    }
    message = await command('/api/grows', {
      name: form.name, zone: form.zone, crop: form.crop,
      started_at: new Date(form.started + 'T12:00:00').getTime() / 1000,
    });
    if (message) return;
    if (form.applyProfile && profiles.indexOf(form.crop) >= 0) {
      await command('/api/profiles/apply', { zone: form.zone, profile: form.crop });
    }
    form = { name: '', zone: form.zone, crop: '', started: today(), applyProfile: true };
    load();
  }

  async function toggle(g) {
    open[g.id] = !open[g.id];
    if (open[g.id] && !details[g.id]) details[g.id] = await json('/api/grows/' + g.id);
  }
  async function finish(g) {
    const body = { action: 'end', notes: ending[g.id].notes || null };
    if (ending[g.id].yield_g !== '' && ending[g.id].yield_g !== undefined) body.yield_g = Number(ending[g.id].yield_g);
    message = await command('/api/grows/' + g.id + '/status', body);
    delete ending[g.id];
    delete details[g.id];
    ending = ending;
    load();
  }
  async function reopen(g) {
    message = await command('/api/grows/' + g.id + '/status', { action: 'reopen' });
    delete details[g.id];
    load();
  }

  const chartLink = (g) => '#/history?start=' + g.started_at + '&end=' + Math.floor(g.ended_at || Date.now() / 1000);
  const show = (kind, v) => {
    const r = formatReading({ kind: kind, unit: '' }, v, $settings.display_units);
    return r.text + (kind === 'ph' ? '' : ' ' + r.unit);
  };
  const weight = (g) => (g.yield_g === null || g.yield_g === undefined ? '' : $settings.display_units === 'imperial' ? g.yield_g + ' g (' + (g.yield_g / 28.35).toFixed(1) + ' oz)' : g.yield_g + ' g');
  const headline = (s) => {
    // The two or three numbers worth comparing between grows.
    const pick = (kind, word) => s.sensors.find((x) => x.kind === kind && x.name.indexOf(word) >= 0);
    const parts = [];
    const air = pick('temperature', 'Air');
    const ph = s.sensors.find((x) => x.kind === 'ph');
    const ec = s.sensors.find((x) => x.kind === 'ec');
    if (air) parts.push('air ' + show('temperature', air.avg));
    if (ph) parts.push('pH ' + show('ph', ph.avg));
    if (ec) parts.push('EC ' + show('ec', ec.avg));
    return parts.join(' · ');
  };
</script>

<section class="card">
  <h2>Start a grow</h2>
  <div class="form">
    <label>Name <input type="text" maxlength="80" placeholder="Winter lettuce" bind:value={form.name} /></label>
    <label>Tent
      <select bind:value={form.zone}>
        <option value="">choose…</option>
        {#each tents as z (z.id)}<option value={z.id}>{z.name}</option>{/each}
      </select>
    </label>
    <label>Crop
      <input type="text" maxlength="80" list="crop-list" bind:value={form.crop} />
      <datalist id="crop-list">{#each profiles as p (p)}<option value={p}></option>{/each}</datalist>
    </label>
    <label>Started <input type="date" bind:value={form.started} /></label>
    <button on:click={start}>Start</button>
  </div>
  {#if profiles.indexOf(form.crop) >= 0}
    <label class="check"><input type="checkbox" bind:checked={form.applyProfile} /> Also set this tent's alert limits for {form.crop}</label>
  {/if}
  {#if message}<p class="bad">{message}</p>{/if}
</section>

{#each [{ title: 'Growing now', list: running }, { title: 'Past grows', list: finished }] as group (group.title)}
  <section class="card">
    <h2>{group.title}</h2>
    {#if group.list.length === 0}
      <p class="hint">{group.title === 'Growing now' ? 'Nothing is growing yet. Start a grow above.' : 'Finished grows are kept here so you can look back and compare.'}</p>
    {/if}
    {#each group.list as g (g.id)}
      {@const d = details[g.id] || g}
      <article>
        <div class="head">
          <div>
            <b>{g.name}</b>{g.crop ? ' · ' + g.crop : ''}
            <div class="hint">
              {zoneName(g.zone)} · {day(g.started_at)}{g.ended_at ? ' to ' + day(g.ended_at) : ''} · {g.ended_at ? days(g) + (days(g) === 1 ? ' day' : ' days') : 'day ' + days(g)}{weight(g) ? ' · harvest ' + weight(g) : ''}
            </div>
            {#if d.summary}<div class="hint">Averages: {headline(d.summary) || 'no readings in this period'}</div>{/if}
          </div>
          <div class="buttons">
            <button class="plain" on:click={() => toggle(g)}>{open[g.id] ? 'Hide' : 'Details'}</button>
            <a class="plain" href={chartLink(g)}>Charts</a>
            {#if !g.ended_at}
              <button class="plain" on:click={() => (ending[g.id] = { yield_g: '', notes: g.notes })}>End grow</button>
            {:else}
              <button class="plain" on:click={() => reopen(g)}>Reopen</button>
            {/if}
          </div>
        </div>

        {#if ending[g.id]}
          <div class="form end">
            <label>Harvest weight (grams, optional) <input type="number" min="0" step="1" bind:value={ending[g.id].yield_g} /></label>
            <label class="wide">Notes: what worked, what to change <textarea rows="2" maxlength="4000" bind:value={ending[g.id].notes}></textarea></label>
            <button on:click={() => finish(g)}>Finish and save</button>
            <button class="plain" on:click={() => { delete ending[g.id]; ending = ending; }}>Cancel</button>
          </div>
        {/if}

        {#if open[g.id] && d.summary}
          {#if g.notes}<p class="notes">{g.notes}</p>{/if}
          <table>
            <thead><tr><th>Reading</th><th>Lowest</th><th>Average</th><th>Highest</th></tr></thead>
            <tbody>
              {#each d.summary.sensors as s (s.key)}
                <tr><td>{s.name}</td><td>{show(s.kind, s.min)}</td><td><b>{show(s.kind, s.avg)}</b></td><td>{show(s.kind, s.max)}</td></tr>
              {/each}
            </tbody>
          </table>
          <ul class="facts">
            <li>{d.summary.alerts} alert{d.summary.alerts === 1 ? '' : 's'} in this tent</li>
            <li>Electricity: {d.summary.energy_kwh} kWh, about {d.summary.energy_cost.toFixed(2)}</li>
            {#if d.summary.waterings}<li>{d.summary.waterings} pump doses (watering and top-off)</li>{/if}
            {#each d.summary.additions as a (a.product + a.unit)}<li>{a.product}: {a.total} {a.unit} in {a.times} addition{a.times === 1 ? '' : 's'}</li>{/each}
            {#if d.summary.plants.length}<li>Plants: {d.summary.plants.map((p) => p.name).join(', ')}</li>{/if}
            <li>{d.summary.journal_entries} journal note{d.summary.journal_entries === 1 ? '' : 's'}</li>
          </ul>
        {/if}
      </article>
    {/each}
  </section>
{/each}

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
    max-width: 860px;
  }
  h2 {
    margin: 0 0 10px;
    font-size: 1.1rem;
  }
  .hint {
    color: var(--muted);
    font-size: 0.88rem;
  }
  .bad {
    color: var(--bad);
  }
  article {
    border-top: 1px solid var(--line);
    padding: 12px 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
  }
  .buttons > * {
    margin: 4px 0 4px 6px;
  }
  .form {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
  }
  .form > * {
    margin: 0 8px 8px 0;
  }
  .form.end {
    margin-top: 10px;
    padding: 12px 12px 4px;
    border-radius: 10px;
    background: var(--off-bg);
  }
  label {
    display: block;
    font-size: 0.85rem;
    color: var(--muted);
  }
  label.wide {
    flex: 1 1 260px;
  }
  label.check {
    font-size: 0.95rem;
    color: var(--text);
  }
  select,
  input[type='text'],
  input[type='number'],
  input[type='date'],
  textarea {
    display: block;
    width: 170px;
    max-width: 100%;
    min-height: 44px;
    margin-top: 2px;
    padding: 6px 8px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
  }
  label.wide textarea {
    width: 100%;
  }
  input[type='checkbox'] {
    width: 20px;
    height: 20px;
    vertical-align: middle;
  }
  button,
  a.plain {
    display: inline-block;
    min-height: 44px;
    line-height: 42px;
    padding: 0 16px;
    border: 0;
    border-radius: 10px;
    background: var(--accent);
    color: var(--bg);
    font-weight: 700;
    text-decoration: none;
    cursor: pointer;
  }
  .plain {
    border: 1px solid var(--line);
    background: var(--off-bg);
    color: var(--text);
    font-weight: 600;
  }
  .notes {
    white-space: pre-wrap;
  }
  table {
    width: 100%;
    margin-top: 8px;
    border-collapse: collapse;
    font-size: 0.92rem;
    font-variant-numeric: tabular-nums;
  }
  th {
    text-align: left;
    color: var(--muted);
    font-weight: 600;
  }
  th,
  td {
    padding: 6px 8px 6px 0;
    border-top: 1px solid var(--line);
  }
  .facts {
    margin: 10px 0 0;
    padding-left: 20px;
    font-size: 0.92rem;
  }
</style>

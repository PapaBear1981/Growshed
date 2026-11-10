<script>
  import { config, nodes, values, settings, link, now, saveUnits } from '../lib/stores.js';
  import { formatDuration, isStale } from '../lib/format.js';

  const diag = (all, node, component, entity) => {
    const entry = all[node + '/' + component + '/' + entity];
    return entry ? entry.value : null;
  };
  const options = [
    { id: 'imperial', label: '°F' },
    { id: 'metric', label: '°C' },
  ];
</script>

<section class="card">
  <h2>Display units</h2>
  <p class="hint">Applies to every screen, including the wall tablet.</p>
  <div class="segmented">
    {#each options as option (option.id)}
      <button
        class:selected={$settings.display_units === option.id}
        aria-pressed={$settings.display_units === option.id}
        on:click={() => saveUnits(option.id)}
      >
        {option.label}
      </button>
    {/each}
  </div>
</section>

<section class="card">
  <h2>Hub</h2>
  <ul class="rows">
    <li><span>This screen ↔ hub</span><b class:bad={!$link.ws}>{$link.ws ? 'Connected' : 'Disconnected'}</b></li>
    <li><span>Hub ↔ MQTT broker</span><b class:bad={!$link.mqtt}>{$link.mqtt ? 'Connected' : 'Disconnected'}</b></li>
  </ul>
</section>

<section class="card">
  <h2>Nodes</h2>
  {#each $config.nodes as node (node.id)}
    {@const info = $nodes[node.id]}
    {@const online = info && info.status === 'online'}
    {@const mode = diag($values, node.id, 'text_sensor', 'mode')}
    {@const rssi = diag($values, node.id, 'sensor', 'wifi_rssi')}
    <div class="node">
      <div class="node-head">
        <b>{node.name}</b>
        <span class="chip" class:online class:bad={!online}>{online ? 'online' : info ? info.status : 'never seen'}</span>
      </div>
      <dl>
        <div><dt>Mode</dt><dd class:warn={mode === 'fallback'}>{mode || '—'}</dd></div>
        <div><dt>WiFi</dt><dd>{rssi === null ? '—' : rssi.toFixed(0) + ' dBm'}</dd></div>
        <div><dt>Uptime</dt><dd>{formatDuration(diag($values, node.id, 'sensor', 'uptime'))}</dd></div>
        <div>
          <dt>Last seen</dt>
          <dd>{info && info.last_seen ? formatDuration($now - info.last_seen) + ' ago' : '—'}</dd>
        </div>
      </dl>
    </div>
  {/each}
</section>

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
    max-width: 720px;
  }
  h2 {
    margin: 0 0 8px;
    font-size: 1.1rem;
  }
  .hint {
    margin: 0 0 12px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-width: 72px;
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
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-top: 1px solid var(--line);
  }
  .bad {
    color: var(--bad);
  }
  .warn {
    color: var(--warn);
    font-weight: 600;
  }
  .node {
    border-top: 1px solid var(--line);
    padding: 12px 0;
  }
  .node-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .chip {
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--off-bg);
  }
  .chip.online {
    background: var(--on-bg);
    color: var(--good);
  }
  dl {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    grid-gap: 8px;
    margin: 0;
  }
  dt {
    font-size: 0.8rem;
    color: var(--muted);
  }
  dd {
    margin: 0;
  }
</style>

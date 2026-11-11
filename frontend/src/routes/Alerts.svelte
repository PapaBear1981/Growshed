<script>
  import { onMount } from 'svelte';
  import { alerts, ackAlert } from '../lib/stores.js';
  import { formatTime, formatDuration } from '../lib/format.js';

  let recent = [];
  let configured = null;
  let testResult = '';

  async function load() {
    try {
      const body = await (await fetch('/api/alerts')).json();
      recent = body.recent;
      configured = body.notifications_configured;
    } catch (err) {
      // hub unreachable: the banner at the top already says so
    }
  }

  async function sendTest() {
    testResult = 'Sending…';
    try {
      const body = await (await fetch('/api/alerts/test', { method: 'POST' })).json();
      testResult = body.sent ? 'Sent. Check your phone.' : 'Could not reach the notification server.';
    } catch (err) {
      testResult = 'Could not reach the hub.';
    }
  }

  onMount(load);
  // Refresh the log whenever the set of active alerts changes.
  $: $alerts, load();
</script>

<section class="card">
  <h2>Active</h2>
  {#if $alerts.length === 0}
    <p class="calm">Nothing is wrong right now.</p>
  {/if}
  {#each $alerts as alert (alert.id)}
    <div class="alert {alert.severity}">
      <div class="text">
        <span class="tag">{alert.severity === 'critical' ? 'Critical' : 'Warning'}</span>
        <b>{alert.name}</b>
        <div>{alert.subject}{alert.detail ? ': ' + alert.detail : ''}</div>
        <div class="meta">
          since {formatTime(alert.started_at)}{alert.acked_at ? ' · acknowledged ' + formatTime(alert.acked_at) : ''}
        </div>
      </div>
      {#if !alert.acked_at}
        <button on:click={() => ackAlert(alert.id)}>Acknowledge</button>
      {/if}
    </div>
  {/each}
  <p class="hint">
    Acknowledging stops repeat notifications. The alert stays here until the problem is fixed.
  </p>
</section>

<section class="card">
  <h2>Phone notifications</h2>
  {#if configured === false}
    <p>Not set up. Add <code>GROWSHED_NTFY_URL</code> to the hub's <code>.env</code> file (see deploy/README.md).</p>
  {:else if configured}
    <p>Set up. Alerts are sent to your ntfy topic.</p>
    <button class="plain" on:click={sendTest}>Send a test notification</button>
    <span class="hint">{testResult}</span>
  {/if}
</section>

<section class="card">
  <h2>History</h2>
  {#if recent.length === 0}
    <p class="calm">No alerts have been recorded yet.</p>
  {:else}
    <table>
      <thead><tr><th>Started</th><th>Alert</th><th>Lasted</th></tr></thead>
      <tbody>
        {#each recent as event (event.id)}
          <tr>
            <td>{formatTime(event.started_at)}</td>
            <td><b>{event.name}</b><br />{event.subject}{event.detail ? ': ' + event.detail : ''}</td>
            <td>{event.ended_at ? formatDuration(event.ended_at - event.started_at) : 'ongoing'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 16px;
    max-width: 760px;
  }
  h2 {
    margin: 0 0 10px;
    font-size: 1.1rem;
  }
  .calm,
  .hint,
  .meta {
    color: var(--muted);
    font-size: 0.9rem;
  }
  .alert {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px;
    margin-bottom: 10px;
    border-radius: 10px;
    border-left: 6px solid var(--warn);
    background: var(--warn-bg);
  }
  .alert.critical {
    border-left-color: var(--bad);
    background: var(--bad-bg);
  }
  .tag {
    display: inline-block;
    margin-right: 6px;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 700;
    color: #fff;
    background: var(--warn);
  }
  .critical .tag {
    background: var(--bad);
  }
  button {
    min-height: 44px;
    margin-left: 12px;
    padding: 0 16px;
    border: 0;
    border-radius: 10px;
    background: var(--accent);
    color: var(--bg);
    font-weight: 700;
    cursor: pointer;
  }
  button.plain {
    margin: 0 10px 0 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--muted);
    font-weight: 600;
  }
  th,
  td {
    padding: 8px 8px 8px 0;
    border-top: 1px solid var(--line);
    vertical-align: top;
  }
  code {
    font-size: 0.85rem;
  }
</style>

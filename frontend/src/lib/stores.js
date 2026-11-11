// Live application state, fed by one WebSocket to the hub.
import { writable } from 'svelte/store';

export const config = writable(null); // zones, nodes, sensors, devices
export const values = writable({}); // "node/component/entity" -> { value, ts }
export const nodes = writable({}); // node id -> { status, last_seen }
export const settings = writable({ display_units: 'imperial' });
export const link = writable({ ws: false, mqtt: false });
export const alerts = writable([]); // active alerts, critical first
export const calibration = writable({}); // sensor key -> { dry, wet, calibrated }

// Hub time in seconds. We track the offset to the hub's clock because an old
// tablet's own clock can be badly wrong, which would make fresh data look stale.
let clockOffset = 0;
export const now = writable(Date.now() / 1000);
setInterval(() => now.set(Date.now() / 1000 + clockOffset), 5000);

export async function loadConfig() {
  for (;;) {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        config.set(await res.json());
        return;
      }
    } catch (err) {
      // hub not reachable yet; retry below
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

function handle(msg) {
  if (msg.type === 'snapshot') {
    clockOffset = msg.server_time - Date.now() / 1000;
    now.set(msg.server_time);
    values.set(msg.values);
    nodes.set(msg.nodes);
    settings.set(msg.settings);
    alerts.set(msg.alerts || []);
    calibration.set(msg.calibration || {});
    link.set({ ws: true, mqtt: msg.mqtt_connected });
  } else if (msg.type === 'value') {
    values.update((all) => {
      all[msg.key] = { value: msg.value, ts: msg.ts, raw: msg.raw };
      return all;
    });
    // Any message from a node proves it is alive. This is also how a board that is
    // not in config.yaml first shows up (auto-discovery).
    const nodeId = msg.key.split('/')[0];
    nodes.update((all) => {
      const known = all[nodeId] || { status: 'unknown' };
      all[nodeId] = { status: known.status, last_seen: msg.ts };
      return all;
    });
  } else if (msg.type === 'node') {
    nodes.update((all) => {
      all[msg.id] = { status: msg.status, last_seen: msg.last_seen };
      return all;
    });
  } else if (msg.type === 'settings') {
    settings.set({ display_units: msg.display_units });
  } else if (msg.type === 'calibration') {
    calibration.set(msg.calibration);
  } else if (msg.type === 'alerts') {
    alerts.set(msg.active);
  } else if (msg.type === 'hub') {
    link.update((l) => ({ ws: l.ws, mqtt: msg.mqtt_connected }));
  }
}

export function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.host + '/ws');
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = () => {
    link.set({ ws: false, mqtt: false });
    setTimeout(connect, 3000); // the wall tablet must recover by itself after a hub restart
  };
}

export async function saveUnits(displayUnits) {
  await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_units: displayUnits }),
  });
}

export async function ackAlert(id) {
  await fetch('/api/alerts/' + id + '/ack', { method: 'POST' });
}

// Ask the hub to store the sensor's current reading as its "dry" or "wet" point.
// Returns '' on success or a message to show the user.
export async function saveCalibration(key, point) {
  try {
    const res = await fetch('/api/calibration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, point: point }),
    });
    if (res.ok) return '';
    return res.status === 409 ? 'No fresh reading from this sensor. Is it connected?' : 'Could not save.';
  } catch (err) {
    return 'Could not reach the hub.';
  }
}

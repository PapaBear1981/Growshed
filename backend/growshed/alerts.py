"""Alert engine: decides when something is wrong, records it, and says who to tell.

Design notes (why it works this way):
- A condition has three answers: bad, fine, or UNKNOWN (no trustworthy data). Unknown
  never raises an alert and never clears one. A leak alert must not silently vanish
  just because the node that reported it went offline; that node going quiet raises its
  own "Node offline" alert instead.
- A condition must hold for `for_s` before alerting and stay fine for `clear_after_s`
  before clearing, so a value hovering at a limit does not spam phones.
- Events live in SQLite, so a hub restart neither loses nor re-announces active alerts.

This module has no clocks, network or MQTT of its own: `tick(now)` is a pure step over
the live state, which keeps every rule unit-testable.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from .config import AlertRule, Sensor, SiteConfig
from .notify import Notification
from .state import LiveState
from .units import format_value

NODE_QUIET_S = 120  # a node that has said nothing for this long counts as down
CheckResult = tuple[bool | None, str]  # (bad / fine / unknown, detail text)


@dataclass
class Condition:
    key: str
    name: str
    subject: str
    severity: str
    for_s: float
    repeat_s: float | None
    check: Callable[[float], CheckResult]


@dataclass
class _Track:
    bad_since: float | None = None
    ok_since: float | None = None
    event_id: int | None = None
    started_at: float | None = None
    acked_at: float | None = None
    last_notified: float | None = None
    detail: str = ""


class AlertEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        site: SiteConfig,
        live: LiveState,
        started_at: float,
        get_units: Callable[[], str] = lambda: "imperial",
    ) -> None:
        self.conn = conn
        self.site = site
        self.live = live
        self.started_at = started_at
        self.get_units = get_units
        self.cfg = site.alerts
        self.conditions = {c.key: c for c in self._build_conditions()}
        self.tracks = {key: _Track() for key in self.conditions}
        self.changed = False  # set whenever the active list changes; the caller resets it
        self._restore(started_at)

    # ------------------------------------------------------------ conditions
    def node_alive(self, node: str, now: float) -> bool | None:
        """True / False, or None if the node has never been heard from since the hub started."""
        info = self.live.nodes.get(node)
        if info is None:
            return None
        if info["status"] == "offline":
            return False
        if info["last_seen"] is None:
            return None
        return now - info["last_seen"] <= NODE_QUIET_S

    def _rule_check(self, rule: AlertRule, sensor: Sensor) -> Callable[[float], CheckResult]:
        key = sensor.state_key

        def check(now: float) -> CheckResult:
            entry = self.live.values.get(key)
            if entry is None or entry["value"] is None:
                return None, ""
            value = entry["value"]
            if rule.when_on is not None:
                # On/off states are only re-sent on change: trust them while the node lives.
                if self.node_alive(sensor.node, now) is not True:
                    return None, ""
                return value == rule.when_on, ""
            if now - entry["ts"] > self.cfg.sensor_stale_after_s:
                return None, ""
            limit = rule.above if rule.above is not None else rule.below
            bad = value > limit if rule.above is not None else value < limit
            units = self.get_units()
            shown = format_value(sensor.kind, value, units)
            return bad, f"{shown} (limit {format_value(sensor.kind, limit, units)})"

        return check

    def _build_conditions(self) -> list[Condition]:
        zones = {z.id: z for z in self.site.zones}
        out: list[Condition] = []
        for rule in self.cfg.rules:
            for sensor in self.site.sensors:
                zone = zones[sensor.zone]
                if sensor.kind != rule.sensor_kind:
                    continue
                if rule.zone_kinds is not None and zone.kind not in rule.zone_kinds:
                    continue
                out.append(
                    Condition(
                        key=f"rule:{rule.name}:{sensor.state_key}",
                        name=rule.name,
                        subject=f"{zone.name} · {sensor.name}",
                        severity=rule.severity,
                        for_s=rule.for_s,
                        repeat_s=rule.repeat_s,
                        check=self._rule_check(rule, sensor),
                    )
                )

        for node in self.site.nodes:

            def offline(now: float, node_id: str = node.id) -> CheckResult:
                alive = self.node_alive(node_id, now)
                return (None if alive is None else not alive), ""

            def fallback(now: float, node_id: str = node.id) -> CheckResult:
                if self.node_alive(node_id, now) is not True:
                    return None, ""
                mode = self.live.values.get(f"{node_id}/text_sensor/mode")
                return (mode is not None and mode["value"] == "fallback"), ""

            out.append(
                Condition(
                    f"node_offline:{node.id}",
                    "Node offline",
                    node.name,
                    "warning",
                    self.cfg.node_offline_after_s,
                    None,
                    offline,
                )
            )
            out.append(
                Condition(
                    f"node_fallback:{node.id}",
                    "Node lost contact with the hub",
                    node.name,
                    "warning",
                    60,
                    None,
                    fallback,
                )
            )

        for sensor in self.site.sensors:
            if sensor.component != "sensor":
                continue

            def stale(now: float, s: Sensor = sensor) -> CheckResult:
                # If the whole node is down, "Node offline" covers it: no alert storm.
                if self.node_alive(s.node, now) is not True:
                    return None, ""
                last = self.live.last_valid.get(s.state_key, self.started_at)
                return now - last > self.cfg.sensor_stale_after_s, ""

            out.append(
                Condition(
                    f"stale:{sensor.state_key}",
                    "Sensor not reporting",
                    f"{zones[sensor.zone].name} · {sensor.name}",
                    "warning",
                    0,
                    None,
                    stale,
                )
            )
        return out

    # ------------------------------------------------------------ persistence
    def _restore(self, now: float) -> None:
        """Pick up alerts that were active when the hub last stopped."""
        rows = self.conn.execute("SELECT * FROM alert_event WHERE ended_at IS NULL").fetchall()
        for row in rows:
            track = self.tracks.get(row["key"])
            if track is None or track.event_id is not None:
                # The rule or sensor no longer exists (config changed), or a duplicate.
                self.conn.execute(
                    "UPDATE alert_event SET ended_at = ? WHERE id = ?", (int(now), row["id"])
                )
                continue
            track.event_id = row["id"]
            track.started_at = row["started_at"]
            track.acked_at = row["acked_at"]
            track.detail = row["detail"]
            track.bad_since = row["started_at"]
            track.last_notified = now
        self.conn.commit()

    # ------------------------------------------------------------ evaluation
    def tick(self, now: float) -> list[Notification]:
        """Evaluate every condition once. Returns the notifications to send."""
        notes: list[Notification] = []
        for key, cond in self.conditions.items():
            track = self.tracks[key]
            bad, detail = cond.check(now)
            active = track.event_id is not None

            if bad is True:
                track.ok_since = None
                if track.bad_since is None:
                    track.bad_since = now
                if not active and now - track.bad_since >= cond.for_s:
                    self._raise(cond, track, detail, now)
                    notes.append(self._note(cond, detail, "raised"))
                elif active:
                    track.detail = detail
                    due = (
                        cond.repeat_s is not None
                        and track.acked_at is None
                        and now - (track.last_notified or 0) >= cond.repeat_s
                    )
                    if due:
                        track.last_notified = now
                        notes.append(self._note(cond, detail, "repeat"))
            elif bad is False:
                track.bad_since = None
                if active:
                    if track.ok_since is None:
                        track.ok_since = now
                    if now - track.ok_since >= self.cfg.clear_after_s:
                        self._clear(track, now)
                        notes.append(self._note(cond, "", "resolved"))
            else:  # unknown: never raise, never clear
                track.ok_since = None
                if not active:
                    track.bad_since = None
        return notes

    def _raise(self, cond: Condition, track: _Track, detail: str, now: float) -> None:
        cur = self.conn.execute(
            "INSERT INTO alert_event (key, name, subject, severity, detail, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cond.key, cond.name, cond.subject, cond.severity, detail, int(now)),
        )
        self.conn.commit()
        track.event_id = cur.lastrowid
        track.started_at = int(now)
        track.acked_at = None
        track.last_notified = now
        track.detail = detail
        self.changed = True

    def _clear(self, track: _Track, now: float) -> None:
        self.conn.execute(
            "UPDATE alert_event SET ended_at = ? WHERE id = ?", (int(now), track.event_id)
        )
        self.conn.commit()
        track.event_id = track.started_at = track.acked_at = None
        track.ok_since = track.bad_since = track.last_notified = None
        track.detail = ""
        self.changed = True

    @staticmethod
    def _note(cond: Condition, detail: str, kind: str) -> Notification:
        body = cond.subject + (f": {detail}" if detail else "")
        if kind == "resolved":
            return Notification(f"Resolved: {cond.name}", body, 2, ("white_check_mark",))
        critical = cond.severity == "critical"
        prefix = "Still active" if kind == "repeat" else ("CRITICAL" if critical else "Warning")
        return Notification(
            f"{prefix}: {cond.name}",
            body,
            5 if critical else 3,
            ("rotating_light",) if critical else ("warning",),
        )

    # ------------------------------------------------------------ queries / actions
    def active(self) -> list[dict]:
        out = []
        for key, track in self.tracks.items():
            if track.event_id is None:
                continue
            cond = self.conditions[key]
            out.append(
                {
                    "id": track.event_id,
                    "name": cond.name,
                    "subject": cond.subject,
                    "severity": cond.severity,
                    "detail": track.detail,
                    "started_at": track.started_at,
                    "acked_at": track.acked_at,
                }
            )
        # Critical first, then newest first.
        return sorted(out, key=lambda a: (a["severity"] != "critical", -a["started_at"]))

    def ack(self, event_id: int, now: float) -> bool:
        """Acknowledge an active alert: stops repeat notifications. It stays active until fixed."""
        for track in self.tracks.values():
            if track.event_id == event_id:
                if track.acked_at is None:
                    track.acked_at = int(now)
                    self.conn.execute(
                        "UPDATE alert_event SET acked_at = ? WHERE id = ?", (int(now), event_id)
                    )
                    self.conn.commit()
                    self.changed = True
                return True
        return False

    def recent(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, subject, severity, detail, started_at, ended_at, acked_at "
            "FROM alert_event ORDER BY started_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

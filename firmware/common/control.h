// Growshed node control logic: pure C++ with no ESPHome dependencies, so the exact code
// that runs on the boards is also compiled and unit-tested on a PC (firmware/tests).
//
// Every rule here implements docs/SAFETY.md. Do not weaken one without changing that
// document first.
#pragma once

#include <cmath>
#include <cstring>
#include <string>

namespace gs {

const int MODE_AUTO = 0;
const int MODE_ON = 1;
const int MODE_OFF = 2;

inline int parse_mode(const char *text) {
  if (std::strcmp(text, "on") == 0) return MODE_ON;
  if (std::strcmp(text, "off") == 0) return MODE_OFF;
  return MODE_AUTO;  // anything unexpected falls back to automatic
}

struct Decision {
  bool on;
  const char *source;     // auto | manual | fallback | interlock
  const char *interlock;  // SAFETY.md rule id when source is "interlock", else nullptr
};

// The single place that decides whether a relay is on.
//   mode      what the hub asked for (auto / on / off)
//   fallback  true when the hub has been silent for 3 minutes: manual modes are ignored
//   auto_on   what the node's own automation wants
//   block     a rule id if an interlock forbids running, else nullptr. Always wins.
//   force     a rule id if an interlock demands running, else nullptr
// An interlock is only reported when it actually changes the outcome, so "reservoir is
// full, top-off not wanted anyway" does not show up as a safety event.
inline Decision decide(int mode, bool fallback, bool auto_on, const char *block, const char *force) {
  bool want;
  const char *source;
  if (fallback) {
    want = auto_on;
    source = "fallback";
  } else if (mode == MODE_ON) {
    want = true;
    source = "manual";
  } else if (mode == MODE_OFF) {
    want = false;
    source = "manual";
  } else {
    want = auto_on;
    source = "auto";
  }
  if (block != nullptr) {
    if (want) return {false, "interlock", block};
    return {false, source, nullptr};
  }
  if (force != nullptr && !want) return {true, "interlock", force};
  return {want, source, nullptr};
}

// Daily window in minutes since midnight. Handles windows that cross midnight.
// Equal on and off times mean "never on".
inline bool in_window(int now_min, int on_min, int off_min) {
  if (on_min == off_min) return false;
  if (on_min < off_min) return now_min >= on_min && now_min < off_min;
  return now_min >= on_min || now_min < off_min;
}

// Heating thermostat with a dead band so the relay does not chatter.
// An unreadable temperature keeps the previous demand; the sensor-failure interlock
// (which waits a little longer) is what shuts the heater down.
inline bool heat_demand(bool was_on, float temp, float setpoint, float band) {
  if (std::isnan(temp)) return was_on;
  if (temp < setpoint - band) return true;
  if (temp > setpoint + band) return false;
  return was_on;
}

// Exhaust fan: on above either limit, off only when both are comfortably below.
// A missing reading is ignored here (the sensor-failure interlock forces the fan on).
inline bool exhaust_demand(bool was_on, float temp, float rh, float max_temp, float max_rh) {
  bool temp_ok = !std::isnan(temp);
  bool rh_ok = !std::isnan(rh);
  if ((temp_ok && temp > max_temp) || (rh_ok && rh > max_rh)) return true;
  if ((!temp_ok || temp < max_temp - 2.0f) && (!rh_ok || rh < max_rh - 5.0f)) return false;
  return was_on;
}

// Repeating on/off cycle (e.g. tower pump 15 min on, 45 min off).
inline bool cycle_on(unsigned long seconds, int on_s, int off_s) {
  if (on_s <= 0) return false;
  if (off_s <= 0) return true;
  return (seconds % (unsigned long) (on_s + off_s)) < (unsigned long) on_s;
}

// True once a condition has held continuously for `hold_s` seconds.
struct Held {
  int seconds = 0;
  bool update(bool condition, int dt_s, int hold_s) {
    if (!condition) {
      seconds = 0;
      return false;
    }
    if (seconds < hold_s) seconds += dt_s;
    return seconds >= hold_s;
  }
};

// Latching over-temperature cutoff (I-4): trips after the temperature has been above
// `trip` for `hold_s`, and only clears once it is back below `clear`.
struct OverTemp {
  bool tripped = false;
  Held above;
  bool update(float temp, float trip, float clear, int dt_s, int hold_s) {
    if (std::isnan(temp)) {
      above.update(false, dt_s, hold_s);
      return tripped;  // unknown temperature: keep whatever state we were in
    }
    if (above.update(temp > trip, dt_s, hold_s)) tripped = true;
    if (tripped && temp < clear) tripped = false;
    return tripped;
  }
};

// A pump that only ever runs in short, limited doses (soil watering I-11, top-off I-9).
// The hub asks for a number of seconds; the node enforces the hard limits whatever it
// is asked for: maximum run time, a rest between doses, and a daily cap.
struct Doser {
  int max_s;
  int rest_s;
  int max_per_day;
  int remaining = 0;
  int resting = 0;
  int count = 0;
  int window = 0;
  const char *refused = nullptr;  // why the last request was refused or cut short

  Doser(int max_run_s, int rest_between_s, int doses_per_day)
      : max_s(max_run_s), rest_s(rest_between_s), max_per_day(doses_per_day) {}

  // Call once per `dt_s`. request_s > 0 asks for a dose. `block` is a rule id when
  // running is forbidden (leak, tank low, reservoir full, fallback). Returns true while
  // the pump should run.
  bool step(int request_s, const char *block, int dt_s) {
    window += dt_s;
    if (window >= 86400) {
      window = 0;
      count = 0;
    }
    if (resting > 0) resting -= dt_s;
    if (request_s > 0) {
      if (block != nullptr) {
        refused = block;
      } else if (remaining > 0 || resting > 0) {
        refused = "busy";
      } else if (count >= max_per_day) {
        refused = "daily-cap";
      } else {
        remaining = request_s < max_s ? request_s : max_s;
        resting = rest_s;
        count++;
        refused = nullptr;
      }
    }
    if (remaining > 0 && block != nullptr) {
      remaining = 0;  // abort a dose in progress the moment an interlock appears
      refused = block;
    }
    if (remaining > 0) {
      remaining -= dt_s;
      return true;
    }
    return false;
  }

  const char *status(bool on) const { return on ? "dosing" : (refused != nullptr ? "refused" : "idle"); }
};

// A chemical dosing pump (SAFETY.md §4): asked for in millilitres, timed in milliseconds.
// Whatever the hub asks for, the node enforces: a calibrated pump, a maximum single dose,
// a maximum per day, a rest between doses, and an absolute limit on run time.
struct MlDoser {
  float max_ml;
  float max_day_ml;
  long rest_ms;
  long remaining_ms = 0;
  long resting_ms = 0;
  long window_ms = 0;
  float day_ml = 0;
  const char *refused = nullptr;

  static constexpr long MAX_RUN_MS = 60000;  // no single dose may run longer than this

  MlDoser(float max_dose_ml, float max_per_day_ml, long rest_between_ms)
      : max_ml(max_dose_ml), max_day_ml(max_per_day_ml), rest_ms(rest_between_ms) {}

  // Call every `dt_ms`. request_ml > 0 asks for a dose; ml_per_s is the pump's measured
  // flow rate (0 = never calibrated). Returns true while the pump should run.
  bool step(float request_ml, float ml_per_s, const char *block, long dt_ms) {
    window_ms += dt_ms;
    if (window_ms >= 86400000L) {
      window_ms = 0;
      day_ml = 0;
    }
    if (resting_ms > 0) resting_ms -= dt_ms;
    if (request_ml > 0) {
      const float ml = request_ml < max_ml ? request_ml : max_ml;
      if (block != nullptr) {
        refused = block;
      } else if (!(ml_per_s > 0)) {
        refused = "uncalibrated";  // without a flow rate, millilitres mean nothing
      } else if (remaining_ms > 0 || resting_ms > 0) {
        refused = "busy";
      } else if (day_ml + ml > max_day_ml) {
        refused = "daily-cap";
      } else {
        long run = (long) (ml / ml_per_s * 1000.0f);
        remaining_ms = run < MAX_RUN_MS ? run : MAX_RUN_MS;
        resting_ms = rest_ms;
        day_ml += ml;
        refused = nullptr;
      }
    }
    if (remaining_ms > 0 && block != nullptr) {
      remaining_ms = 0;  // abort at once if an interlock appears mid-dose
      refused = block;
    }
    if (remaining_ms > 0) {
      remaining_ms -= dt_ms;
      return true;
    }
    return false;
  }

  bool accepted_now(float day_ml_before) const { return day_ml > day_ml_before; }
  const char *status(bool on) const { return on ? "dosing" : (refused != nullptr ? "refused" : "idle"); }
};

// Runs a pump for a few seconds on request, to fill its tube or measure its flow rate.
// The outlet must be in a measuring cup, not the reservoir: this is not a counted dose.
struct Primer {
  long remaining_ms = 0;
  bool step(int request_s, int max_s, const char *block, long dt_ms) {
    if (block != nullptr) {
      remaining_ms = 0;
      return false;
    }
    if (request_s > 0 && remaining_ms <= 0) remaining_ms = 1000L * (request_s < max_s ? request_s : max_s);
    if (remaining_ms > 0) {
      remaining_ms -= dt_ms;
      return true;
    }
    return false;
  }
};

// Milliseconds since something last happened, saturating (never wraps around).
struct Since {
  long ms = 2000000000L;
  void tick(long dt_ms) {
    if (ms < 2000000000L) ms += dt_ms;
  }
  void reset() { ms = 0; }
  bool within(long window_ms) const { return ms < window_ms; }
};

// Drive a relay to match a decision. Templated so tests can pass a fake switch.
template<typename SwitchT> void apply(SwitchT *relay, bool on) {
  if (on != relay->state) {
    if (on)
      relay->turn_on();
    else
      relay->turn_off();
  }
}

// Publish a device's source (and the interlock id, if any) whenever it changes.
template<typename TextT, typename LastT>
void report(TextT *source, LastT *last_interlock, const char *text, const char *interlock, const char *device,
            std::string &previous) {
  std::string now = text;
  if (interlock != nullptr) now += std::string(" ") + interlock;
  if (now == previous) return;
  previous = now;
  source->publish_state(text);
  if (interlock != nullptr) last_interlock->publish_state(std::string(interlock) + " " + device);
}

}  // namespace gs

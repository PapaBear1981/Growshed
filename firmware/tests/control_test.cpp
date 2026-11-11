// Native unit tests for common/control.h. Run through pytest (tools/tests) or by hand:
//   g++ -std=c++17 -Wall -Werror -o /tmp/control_test firmware/tests/control_test.cpp && /tmp/control_test
#include "../common/control.h"

#include <cassert>
#include <cstdio>
#include <vector>

using namespace gs;

static bool is(const Decision &d, bool on, const char *source, const char *interlock = nullptr) {
  bool same_lock = (interlock == nullptr) ? d.interlock == nullptr
                                          : (d.interlock != nullptr && std::strcmp(d.interlock, interlock) == 0);
  return d.on == on && std::strcmp(d.source, source) == 0 && same_lock;
}

static void test_decide() {
  // normal operation
  assert(is(decide(MODE_AUTO, false, true, nullptr, nullptr), true, "auto"));
  assert(is(decide(MODE_AUTO, false, false, nullptr, nullptr), false, "auto"));
  assert(is(decide(MODE_ON, false, false, nullptr, nullptr), true, "manual"));
  assert(is(decide(MODE_OFF, false, true, nullptr, nullptr), false, "manual"));
  // fallback ignores manual modes in both directions
  assert(is(decide(MODE_ON, true, false, nullptr, nullptr), false, "fallback"));
  assert(is(decide(MODE_OFF, true, true, nullptr, nullptr), true, "fallback"));
  // a blocking interlock beats manual ON, auto and fallback
  assert(is(decide(MODE_ON, false, false, "I-1", nullptr), false, "interlock", "I-1"));
  assert(is(decide(MODE_AUTO, false, true, "I-1", nullptr), false, "interlock", "I-1"));
  assert(is(decide(MODE_AUTO, true, true, "I-1", nullptr), false, "interlock", "I-1"));
  // ...but is not reported when the device was going to be off anyway
  assert(is(decide(MODE_AUTO, false, false, "I-9", nullptr), false, "auto"));
  assert(is(decide(MODE_OFF, false, true, "I-9", nullptr), false, "manual"));
  // a forcing interlock beats manual OFF, and is silent when already wanted
  assert(is(decide(MODE_OFF, false, false, nullptr, "I-5"), true, "interlock", "I-5"));
  assert(is(decide(MODE_AUTO, false, true, nullptr, "I-5"), true, "auto"));
  // block wins over force
  assert(is(decide(MODE_AUTO, false, false, "I-1", "I-5"), false, "auto"));
  assert(is(decide(MODE_ON, false, false, "I-1", "I-5"), false, "interlock", "I-1"));
  // unknown mode text is treated as auto
  assert(parse_mode("on") == MODE_ON && parse_mode("off") == MODE_OFF);
  assert(parse_mode("auto") == MODE_AUTO && parse_mode("garbage") == MODE_AUTO && parse_mode("") == MODE_AUTO);
}

static void test_in_window() {
  assert(in_window(360, 360, 1320) && in_window(1319, 360, 1320));
  assert(!in_window(359, 360, 1320) && !in_window(1320, 360, 1320));
  // crossing midnight: 20:00 -> 06:00
  assert(in_window(1300, 1200, 360) && in_window(0, 1200, 360) && in_window(359, 1200, 360));
  assert(!in_window(360, 1200, 360) && !in_window(720, 1200, 360));
  assert(!in_window(500, 600, 600));  // equal times: never on
}

static void test_heat_demand() {
  assert(heat_demand(false, 19.0f, 20.0f, 0.5f));
  assert(!heat_demand(true, 21.0f, 20.0f, 0.5f));
  assert(heat_demand(true, 20.2f, 20.0f, 0.5f) && !heat_demand(false, 20.2f, 20.0f, 0.5f));  // dead band
  assert(heat_demand(true, NAN, 20.0f, 0.5f) && !heat_demand(false, NAN, 20.0f, 0.5f));
}

static void test_exhaust_demand() {
  assert(exhaust_demand(false, 29.0f, 50.0f, 28.0f, 70.0f));   // too hot
  assert(exhaust_demand(false, 22.0f, 75.0f, 28.0f, 70.0f));   // too humid
  assert(exhaust_demand(true, 27.0f, 60.0f, 28.0f, 70.0f));    // inside the dead band: stays on
  assert(!exhaust_demand(false, 27.0f, 60.0f, 28.0f, 70.0f));  // ...or stays off
  assert(!exhaust_demand(true, 25.0f, 60.0f, 28.0f, 70.0f));   // both comfortably low
  assert(exhaust_demand(false, NAN, 80.0f, 28.0f, 70.0f));     // one reading missing: use the other
  assert(!exhaust_demand(true, NAN, NAN, 28.0f, 70.0f));
}

static void test_cycle() {
  assert(cycle_on(0, 900, 2700) && cycle_on(899, 900, 2700));
  assert(!cycle_on(900, 900, 2700) && !cycle_on(3599, 900, 2700) && cycle_on(3600, 900, 2700));
  assert(!cycle_on(5, 0, 100) && cycle_on(5, 100, 0));
}

static void test_held_and_overtemp() {
  Held h;
  for (int i = 0; i < 9; i++) assert(!h.update(true, 1, 10));
  assert(h.update(true, 1, 10));
  assert(!h.update(false, 1, 10) && !h.update(true, 1, 10));  // resets completely

  OverTemp hot;
  for (int i = 0; i < 119; i++) assert(!hot.update(36.0f, 35.0f, 30.0f, 1, 120));
  assert(hot.update(36.0f, 35.0f, 30.0f, 1, 120));       // trips after two minutes
  assert(hot.update(32.0f, 35.0f, 30.0f, 1, 120));       // stays tripped until properly cool
  assert(hot.update(NAN, 35.0f, 30.0f, 1, 120));         // a lost sensor does not un-trip it
  assert(!hot.update(29.5f, 35.0f, 30.0f, 1, 120));
  // a brief spike never trips it
  OverTemp spike;
  for (int i = 0; i < 100; i++) spike.update(36.0f, 35.0f, 30.0f, 1, 120);
  spike.update(34.0f, 35.0f, 30.0f, 1, 120);
  for (int i = 0; i < 100; i++) assert(!spike.update(36.0f, 35.0f, 30.0f, 1, 120));
}

static int run(Doser &d, int request, const char *block, int seconds) {
  int on = 0;
  for (int i = 0; i < seconds; i++) on += d.step(i == 0 ? request : 0, block, 1) ? 1 : 0;
  return on;
}

static void test_doser() {
  Doser d(20, 600, 3);
  assert(run(d, 8, nullptr, 30) == 8);              // runs exactly the requested time
  assert(run(d, 8, nullptr, 30) == 0);              // must rest first
  assert(std::strcmp(d.refused, "busy") == 0);
  assert(run(d, 0, nullptr, 600) == 0);
  assert(run(d, 500, nullptr, 700) == 20);          // never longer than the hard maximum
  assert(run(d, 5, "I-10", 700) == 0);              // refused outright during a leak
  assert(std::strcmp(d.refused, "I-10") == 0 && std::strcmp(d.status(false), "refused") == 0);
  assert(run(d, 5, nullptr, 700) == 5);             // third and last dose of the day
  assert(run(d, 5, nullptr, 700) == 0 && std::strcmp(d.refused, "daily-cap") == 0);
  assert(run(d, 0, nullptr, 86400) == 0);           // a day later the cap resets
  assert(run(d, 5, nullptr, 10) == 5 && d.refused == nullptr);

  // an interlock appearing mid-dose stops the pump at once
  Doser e(20, 600, 3);
  assert(e.step(15, nullptr, 1) && e.step(0, nullptr, 1));
  assert(!e.step(0, "I-12", 1) && !e.step(0, nullptr, 1));
  assert(std::strcmp(e.refused, "I-12") == 0);
  assert(run(e, -4, nullptr, 5) == 0);              // nonsense requests do nothing
}

struct FakeSwitch {
  bool state = false;
  int toggles = 0;
  void turn_on() { state = true; toggles++; }
  void turn_off() { state = false; toggles++; }
};
struct FakeText {
  std::vector<std::string> published;
  void publish_state(const std::string &s) { published.push_back(s); }
};

static void test_apply_and_report() {
  FakeSwitch relay;
  apply(&relay, true);
  apply(&relay, true);
  apply(&relay, false);
  assert(relay.toggles == 2 && !relay.state);  // only switches on a change

  FakeText source, last;
  std::string previous;
  report(&source, &last, "auto", nullptr, "lights", previous);
  report(&source, &last, "auto", nullptr, "lights", previous);
  report(&source, &last, "interlock", "I-4", "lights", previous);
  report(&source, &last, "interlock", "I-4", "lights", previous);
  report(&source, &last, "auto", nullptr, "lights", previous);
  assert(source.published == (std::vector<std::string>{"auto", "interlock", "auto"}));
  assert(last.published == (std::vector<std::string>{"I-4 lights"}));
}

int main() {
  test_decide();
  test_in_window();
  test_heat_demand();
  test_exhaust_demand();
  test_cycle();
  test_held_and_overtemp();
  test_doser();
  test_apply_and_report();
  std::puts("control.h: all tests passed");
  return 0;
}

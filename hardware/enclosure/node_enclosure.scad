// Growshed node enclosure — parametric, prints without supports.
//
// Houses one ESP32 on a screw-terminal breakout board, a 12V->5V buck
// converter, and spare room for a fuse holder / MOSFET board.
// Mount it OUTSIDE the tent with the cable slots facing DOWN.
//
// Export:  openscad -D 'part="base"' -o node_enclosure_base.stl node_enclosure.scad
//          openscad -D 'part="lid"'  -o node_enclosure_lid.stl  node_enclosure.scad
//
// All dimensions in mm. MEASURE YOUR BOARDS and adjust the "Board" and
// "Buck converter" sections before printing.

part = "both"; // "base", "lid", or "both" (preview, lid placed beside base)

/* [Box] */
inner_w = 150;      // interior width  (X)
inner_d = 100;      // interior depth  (Y). Y=0 wall is the cable (bottom) side
inner_h = 35;       // interior height (Z)
wall    = 2.4;
floor_t = 2.4;
lid_t   = 2.4;
corner_r = 3;

/* [Board: ESP32 screw-terminal breakout] */
board_hole_dx = 60; // mounting-hole spacing in X  <-- measure yours
board_hole_dy = 50; // mounting-hole spacing in Y  <-- measure yours
board_cx = 50;      // board centre, from interior left wall
board_cy = 60;      // board centre, from interior cable wall
standoff_h = 5;
standoff_d = 7;
standoff_pilot = 2.5; // 2.5 = M3 self-tapping into plastic

/* [Buck converter pocket (default: LM2596 module, 43 x 21)] */
buck_l = 43.6;
buck_w = 21.6;
buck_cx = 120;
buck_cy = 79;

/* [Cable entry] */
slot_count = 6;
slot_w = 7;         // fits sensor cables and a USB cable
slot_pitch = 15;
slot_first_x = 20;  // centre of first slot, from interior left wall
slot_floor_gap = 10; // slot bottom, above interior floor
jack_d = 8.2;       // panel-mount DC barrel jack hole (0 = none)
jack_x = 125;
jack_z = 18;        // above interior floor

/* [Lid screws] */
post = 8;           // corner post size
post_pilot = 2.5;   // 2.5 = M3 self-tapping; use 4.0 for M3 heat-set inserts
lid_hole = 3.4;
lip_h = 3;
lip_t = 1.6;
lip_clear = 0.35;

/* [Mounting ears] */
ear_w = 16;
ear_len = 12;
ear_t = 3;
ear_hole = 4.5;     // #8 wood screw, or a zip tie around a tent pole

$fn = 48;
outer_w = inner_w + 2*wall;
outer_d = inner_d + 2*wall;
outer_h = inner_h + floor_t;
eps = 0.01;

module rounded_rect(w, d, r) {
    translate([r, r]) offset(r) square([w - 2*r, d - 2*r]);
}

function slot_x(i) = slot_first_x + i*slot_pitch;

// ---------------------------------------------------------------- base
module ear(x, y, dir) { // dir = +1 extends +Y, -1 extends -Y
    translate([x, y, 0]) difference() {
        hull() {
            translate([0, dir > 0 ? -eps : -eps, 0]) cube([ear_w, eps*2, ear_t]);
            translate([ear_w/2, dir*(ear_len - ear_w/2 + 2), 0]) cylinder(d = ear_w, h = ear_t);
        }
        translate([ear_w/2, dir*(ear_len - ear_w/2 + 2), -1]) cylinder(d = ear_hole, h = ear_t + 2);
    }
}

module shell() {
    difference() {
        linear_extrude(outer_h) rounded_rect(outer_w, outer_d, corner_r);
        translate([wall, wall, floor_t])
            linear_extrude(inner_h + 1) rounded_rect(inner_w, inner_d, max(corner_r - wall, 0.5));
    }
}

module corner_posts(pilot = true) {
    for (x = [0, inner_w - post], y = [0, inner_d - post])
        translate([wall + x, wall + y, floor_t - eps]) difference() {
            cube([post, post, inner_h + eps]);
            if (pilot) translate([post/2, post/2, inner_h - 14]) cylinder(d = post_pilot, h = 15);
        }
}

module standoffs() {
    for (sx = [-1, 1], sy = [-1, 1])
        translate([wall + board_cx + sx*board_hole_dx/2, wall + board_cy + sy*board_hole_dy/2, floor_t - eps])
            difference() {
                cylinder(d = standoff_d, h = standoff_h + eps);
                translate([0, 0, 0.6]) cylinder(d = standoff_pilot, h = standoff_h + 1);
            }
}

module buck_pocket() { // four corner brackets; wires exit at the open ends
    t = 1.6; h = 4; leg = 8;
    translate([wall + buck_cx, wall + buck_cy, floor_t - eps])
        for (sx = [-1, 1], sy = [-1, 1]) scale([sx, sy, 1])
            translate([buck_l/2, buck_w/2, 0]) {
                translate([-leg, 0, 0]) cube([leg + t, t, h]);
                translate([0, -leg, 0]) cube([t, leg + t, h]);
            }
}

module tie_bar() { // cables lie over the bar; zip ties pass through the tunnels
    bar_h = 8; bar_t = 4; y0 = 12;
    x0 = slot_x(0) - 8; x1 = slot_x(slot_count - 1) + 8;
    translate([wall, wall, floor_t - eps]) difference() {
        translate([x0, y0, 0]) cube([x1 - x0, bar_t, bar_h]);
        for (i = [0 : slot_count - 1])
            translate([slot_x(i) - 2.5, y0 - 1, 3]) cube([5, bar_t + 2, 2.6]);
    }
}

module cable_slots() {
    for (i = [0 : slot_count - 1])
        translate([wall + slot_x(i) - slot_w/2, -1, floor_t + slot_floor_gap]) {
            cube([slot_w, wall + 2, inner_h]);
            translate([slot_w/2, 0, 0]) rotate([-90, 0, 0]) cylinder(d = slot_w, h = wall + 2);
        }
}

module jack_hole() {
    if (jack_d > 0)
        translate([wall + jack_x, -1, floor_t + jack_z]) rotate([-90, 0, 0]) cylinder(d = jack_d, h = wall + 2);
}

module vents() { // side walls only, so drips from above cannot enter
    n = 6; pitch = 8; vw = 2.2; vh = 14;
    for (x = [-1, outer_w - wall - 1], i = [0 : n - 1])
        translate([x, outer_d/2 + (i - (n - 1)/2)*pitch - vw/2, floor_t + 13])
            cube([wall + 2, vw, vh]);
}

module base() {
    difference() {
        union() {
            shell();
            corner_posts();
            standoffs();
            buck_pocket();
            tie_bar();
            ear(0, outer_d, 1);
            ear(outer_w - ear_w, outer_d, 1);
            ear(0, 0, -1);
            ear(outer_w - ear_w, 0, -1);
        }
        cable_slots();
        jack_hole();
        vents();
    }
}

// ---------------------------------------------------------------- lid
// Modelled as it prints: flat face down, locating lip up.
module lid() {
    c = lip_clear;
    difference() {
        union() {
            linear_extrude(lid_t) rounded_rect(outer_w, outer_d, corner_r);
            translate([0, 0, lid_t - eps]) linear_extrude(lip_h) difference() {
                translate([wall + c, wall + c]) square([inner_w - 2*c, inner_d - 2*c]);
                translate([wall + c + lip_t, wall + c + lip_t])
                    square([inner_w - 2*c - 2*lip_t, inner_d - 2*c - 2*lip_t]);
                // clear the corner posts
                for (x = [0, inner_w - post - c], y = [0, inner_d - post - c])
                    translate([wall + x, wall + y]) square([post + c, post + c]);
            }
        }
        for (x = [post/2, inner_w - post/2], y = [post/2, inner_d - post/2])
            translate([wall + x, wall + y, -1]) cylinder(d = lid_hole, h = lid_t + 2);
    }
}

if (part == "base") base();
else if (part == "lid") lid();
else { base(); translate([0, outer_d + 30, 0]) lid(); }

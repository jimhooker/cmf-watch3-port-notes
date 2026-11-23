#!/usr/bin/env python3
"""Add one extra entry to the stock Watch 3 Pro app list in the emulator, using only stock calls made from the UI
thread, the way a stub would after the stock layout has run. Emulator only; nothing touches a watch.

usage: scripts/emu_applist_add.py PATH_TO_cmf-watch-utils WORK_DIR RUN_NAME list|grid [SHOWN]

SHOWN is how many stock entries the list shows (default 28: the emulator's virtual watch hides entries 9 and 11).
The extra entry borrows stock entry 28 (Settings): its icon, its text and its click target, so no guest memory has
to be prepared. Expected result in WORK_DIR/runs/RUN_NAME/calls: a second Settings entry (first row in List, the
free place after the last icon in Grid) and, after the tap, the Settings screen.

Addresses are for firmware 1.0.1.77; data/app-list.csv says what each one is.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TIMER_HANDLER = "10148f30"  # the UI thread enters it every few milliseconds, also when the screen is idle
BORROW = 28


def list_steps(shown):
    steps = ["settle:wait:4", "open:input:crown:6", "before:shot",
             "row:10138b49:$view/14/4:0:0.2",                            # lv_obj_create(container)
             "size:101e4e23:$row:18a:0.2:60",                            # lv_obj_set_size(row, 0x18A, 96)
             "ud:poke:$row+10:%x" % BORROW,                              # row->user_data = entry index
             "cb:10136aa1:$row:10046fe5:0.2:4:$view/14",                 # add_event_cb(row, stock click, 4, data)
             "al:101e4e85:$row:1:0.2:10:50",                             # lv_obj_align(row, TOP_LEFT, 0x10, 0x50)
             "img:10041959:$row:0:0.2",                                  # simple_img_create(row)
             "f1:101e4367:$img:4000:0.2",                                # add_flag(img, EVENT_BUBBLE)
             "src:101c675d:$img:$view/14+%x:0.2" % (0xC + 12 * BORROW),  # simple_img_set_src(img, &data.icon[n])
             "lab:1014bb49:$row:0:0.2",                                  # lv_label_create(row)
             "ls:101e4e23:$lab:112:0.2:$view/14/274",                    # set_size(label, 0x172 - 96, line height)
             "st:1013aa71:$lab:$view/14+264:0.2:0",                      # lv_obj_add_style(label, &data.style, 0)
             "lm:1014c611:$lab:3:0.2",                                   # lv_label_set_long_mode(label, 3)
             "tx:1014c5d1:$lab:$view/14+%x:0.2" % (0x174 + 8 * BORROW),  # lv_label_set_string_dsc(label, &text[n])
             "sc:101ece0b:$lab:0:0.2:ffffffff:0",                        # the stock label scroll setup
             "f2:101e4367:$lab:4000:0.2",                                # add_flag(label, EVENT_BUBBLE)
             "la:10139c45:$lab:$img:0.2:14:18:0",                        # align_to(label, img, OUT_RIGHT_MID, 0x18, 0)
             "n:101e66d9:$view/14/4:0:0.2"]                              # lv_obj_get_child_cnt(container)
    previous = "$row"
    for i in range(shown):  # chain the stock rows below the new one
        steps += ["c%d:101e66bb:$view/14/4:%x:0.1" % (i, i),             # lv_obj_get_child(container, i)
                  "a%d:10139c45:$c%d:%s:0.1:d:0:8" % (i, i, previous)]   # align_to(row, previous, OUT_BOTTOM_LEFT, 0, 8)
        previous = "$c%d" % i
    steps += ["ev:10136a3d:$view/14/4:b:2:0",                            # lv_event_send(container, SCROLL, NULL)
              "added:shot", "s1:input:swipe 233 300 233 180:3", "scrolled:shot",
              "s2:input:swipe 233 180 233 420:3", "top:shot", "t:input:tap 200 128:5", "tapped:shot"]
    return ["--capture", "view:10047164:r0", "--dump-after", "children:$view/14/4/8/0:80"] + steps


def grid_steps(shown):
    rows = -(-(shown + 1) // 3)
    steps = ["settle:wait:4", "open:input:crown:6", "before:shot",
             "n:101e66d9:$view/14/1e4:0:0.2",                            # lv_obj_get_child_cnt(container)
             "img:10041959:$view/14/1e4:0:0.2",                          # simple_img_create(container)
             "slot:poke:$view/14+%x:$img" % (0x16C + 4 * shown),         # data.icon_obj[shown] = img
             "src:101c675d:$img:$view/14+%x:0.2" % (4 + 12 * BORROW),    # simple_img_set_src(img, &data.icon[n])
             "pv:101c67a7:$img:50:0.2:50",                               # pivot at the centre of a 160 x 160 icon
             "f0:101e4367:$img:1:0.2",                                   # add_flag(img, HIDDEN)
             "cb:10136aa1:$img:100467f9:0.2:4:$view/14",                 # add_event_cb(img, stock click, 4, data)
             "f1:101e4367:$img:2:0.2",                                   # add_flag(img, CLICKABLE)
             "f2:101e4367:$img:4000:0.2",                                # add_flag(img, EVENT_BUBBLE)
             "ud:poke:$img+10:%x" % BORROW,                              # img->user_data = entry index
             "range:poke:$view/14+1f8:%x" % ((480 - 160 * rows) & 0xFFFFFFFF),  # lowest scroll position
             "pos:101c70eb:$view/14:0:2", "added:shot"]                  # the stock position function
    steps += ["s%d:input:swipe 233 380 233 120:2.5" % i for i in range(8)]
    steps += ["bottom:shot", "t:input:tap 233 392:5", "tapped:shot"]
    # 0x101C6FC2 is where the stock "which style" getter returns: 1 selects Grid without changing a setting
    return ["--force", "101c6fc2:r0:1", "--capture", "view:10046b6c:r0", "--dump-after", "data:$view/14:294"] + steps


def main():
    if len(sys.argv) < 5 or sys.argv[4] not in ("list", "grid"):
        sys.exit(__doc__)
    shown = int(sys.argv[5]) if len(sys.argv) > 5 else 28
    if not 1 <= shown <= 29:
        sys.exit("SHOWN must be 1..29: with all 30 stock entries shown the Grid has no free slot")
    steps = list_steps(shown) if sys.argv[4] == "list" else grid_steps(shown)
    sys.exit(subprocess.call([sys.executable, str(HERE / "scripts" / "emu_call.py"), sys.argv[1], sys.argv[2],
                              sys.argv[3], TIMER_HANDLER] + steps))


if __name__ == "__main__":
    main()

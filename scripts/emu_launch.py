"""How the other emu_* scripts start the emulator: stock Watch 3 Pro firmware at the watch face, or a modified
app image when EMU_APP names one. Emulator only; nothing touches a watch."""
import os
import subprocess
from pathlib import Path

# cmf-watch-utils applies its watch-face preview (skip the setup screens) only to the stock app. For a modified
# image its own preview function is run on that image, as an external tool, the way cmf-watch-sdk's tests do.
PREVIEW = ("import sys; from cmf_watch_utils.emu.preview import watch_face_preview as p; "
           "rom = bytearray(open(sys.argv[2], 'rb').read()); "
           "open(sys.argv[3], 'wb').write(p(open(sys.argv[1], 'rb').read(), rom)); "
           "open(sys.argv[4], 'wb').write(rom)")


def command(utils, work, run, port, seconds):
    """The emulator command line. `run` is the new run directory; a modified image is staged next to it."""
    base = ["uv", "run", "cmf-watch-utils", "emu", "run", "--profile", "wp3-stock",
            "--fixtures", str(work / "fixtures-wp3"), "--qemu", str(work / "runtime" / "qemu-system-arm"),
            "--headless", "--seconds", str(seconds), "--allow-reboot", "--gdb-port", str(port), "--output", str(run)]
    rom = work / "runtime" / "compat.bin"
    app = os.environ.get("EMU_APP")
    if not app:
        return base + ["--rom", str(rom), "--watch-face-preview"]
    staged = run.with_name(run.name + ".preview")
    staged.mkdir(parents=True)
    subprocess.run(["uv", "run", "python", "-c", PREVIEW, str(Path(app).resolve()), str(rom),
                    str(staged / "app.bin"), str(staged / "compat.bin")], cwd=utils, check=True)
    return base + ["--rom", str(staged / "compat.bin"), "--app", str(staged / "app.bin")]

"""Emulator only. Run `cmf-watch-utils` with the QEMU machine's exploratory mode on (QEMU_WP2_EXPLORATORY=1)
instead of the hard-coded 0, so an access to a device register the emulator does not model is logged and
skipped rather than stopping the run. The firmware and the files given to it are unchanged.

usage (from the cmf-watch-utils checkout): uv run python KIT/scripts/emu_exploratory.py emu run ...
"""
import sys

from cmf_watch_utils import cli
from cmf_watch_utils.emu import vm

_run_env = vm.run_env


def run_env(args, model, output, nor, nand):
    env = _run_env(args, model, output, nor, nand)
    env[model.env_prefix + "EXPLORATORY"] = "1"
    return env


vm.run_env = run_env
sys.exit(cli.main(sys.argv[1:]))

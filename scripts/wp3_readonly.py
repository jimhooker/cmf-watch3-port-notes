#!/usr/bin/env python3
"""Ask a real Watch 3 Pro a few read-only questions over Bluetooth. No pairing, no handshake, nothing is set.

usage: wp3_readonly.py [--scan SECONDS] [--scan-only]
Run it with a Python that has `bleak`, for example the cmf-watch-utils environment:
    (cd cmf-watch-utils && uv run python KIT/scripts/wp3_readonly.py)

It scans, picks the strongest device whose name starts with NAME, connects, subscribes to the text shell's
notify characteristic, writes each command in QUERIES to the shell's write characteristic and prints the reply.

QUERIES is a fixed list. Each handler was read in the 1.0.1.77 app.bin and only reads a value and replies
(data/boot-recovery.csv, "AT command table"). The same table holds commands that change the watch (SETSN,
SETBTMAC, SETSECRET, SHIPMODE, SHUTDOWN, REBOOT), so there is deliberately no way to pass a command in.

The phone must be disconnected from the watch (Bluetooth off on the phone), or the shell does not answer.
The watch's address, the last four characters of its name and its serial number are personal data: this script
never prints the first two and never asks for the third.
"""
import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner

NAME = "CMF Watch 3 Pro"
SHELL_WRITE = "77d4ff01-2fe2-2334-0d35-9ccd078f529c"
SHELL_NOTIFY = "77d4ff02-2fe2-2334-0d35-9ccd078f529c"
QUERIES = (  # command, its handler in 1.0.1.77, what the handler does
    ("AT GETVERSION", 0x100E814D, "UX2SYS_GET of property 0x11"),
    ("AT GETPID", 0x100E78C1, "reads the APP_PID setting"),
    ("AT GETFLASH", 0x100E763D, "prints the flash id kept in RAM at 0x38043D00"),
    ("AT GETBATLV", 0x100E6815, "reads the battery voltage"),
)
DONE = (b"OK", b"FAIL", b"ERROR")


async def ask(client, replies, command, timeout=6.0):
    """Send one command and return the reply that names it. The watch was seen to send a reply twice, so a
    reply to an earlier command can arrive after the next one is written: those are skipped, not printed."""
    name = command.split()[1].encode()
    await client.write_gatt_char(SHELL_WRITE, (command + "\r\n").encode(), response=True)
    loop, reply = asyncio.get_running_loop(), b""
    deadline = loop.time() + timeout
    while True:
        remain = deadline - loop.time()
        if remain <= 0:
            return "(no reply)"
        try:
            reply += await asyncio.wait_for(replies.get(), remain)
        except asyncio.TimeoutError:
            return "(no reply)"
        for line in reply.replace(b"\r", b"\n").split(b"\n"):
            if line.startswith(name) and any(mark in line for mark in DONE):
                return line.decode("latin1", "replace").strip()


async def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", type=float, default=12.0, help="seconds to scan (default 12)")
    parser.add_argument("--scan-only", action="store_true", help="report whether the watch is visible, then stop")
    args = parser.parse_args()

    found = await BleakScanner.discover(timeout=args.scan, return_adv=True)
    watches = [(adv.rssi, device) for device, adv in found.values()
               if (adv.local_name or device.name or "").startswith(NAME)]
    print("scan: %d devices seen, %d named '%s-****'" % (len(found), len(watches), NAME))
    if not watches:
        sys.exit("watch not visible: bring it close, and turn Bluetooth off on the phone so it advertises")
    rssi, device = max(watches, key=lambda item: item[0])
    print("strongest signal: %d dBm" % rssi)
    if args.scan_only:
        return

    replies = asyncio.Queue()
    async with BleakClient(device, timeout=30.0) as client:
        print("connected:", client.is_connected)
        await client.start_notify(SHELL_NOTIFY, lambda _, data: replies.put_nowait(bytes(data)))
        try:
            for command, handler, what in QUERIES:
                print("%-14s -> %s" % (command, await ask(client, replies, command)))
        finally:
            await client.stop_notify(SHELL_NOTIFY)
    print("disconnected")


if __name__ == "__main__":
    asyncio.run(main())

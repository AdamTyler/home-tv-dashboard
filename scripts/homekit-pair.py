#!/usr/bin/env python3
"""Pair the Pi with a HomeKit accessory (e.g. an ecobee) and save the keys.

Run on the Pi with the dashboard's venv:
  /opt/tv-dashboard/venv/bin/python scripts/homekit-pair.py <device-id> <pin> <alias> [pairings.json]

<device-id> is the HomeKit id (from `avahi-browse -rt _hap._tcp`, the "id=" field),
<pin> the 8-digit code on the device (XXX-XX-XXX). Keys are saved to pairings.json
(default /opt/tv-dashboard/homekit-pairings.json, never committed) and verified by
reading the accessory list before reporting success.

(aiohomekit 4's own `aiohomekitctl pair` doesn't save the new pairing; losing the
keys leaves the device paired to nobody until its HomeKit pairing is reset.)
"""
import asyncio
import json
import os
import re
import sys

from aiohomekit import Controller
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf


async def main(device_id, pin, alias, path):
    if not re.match(r"^\d{3}-\d{2}-\d{3}$", pin):
        pin = "%s-%s-%s" % (pin[:3], pin[3:5], pin[5:])
    saved = {}
    if os.path.exists(path):
        with open(path) as f:
            saved = json.load(f)
    if alias in saved:
        sys.exit('"%s" is already paired in %s' % (alias, path))

    zc = AsyncZeroconf()
    async with zc:
        # aiohomekit's controller expects browsers for both HomeKit service types.
        browser = AsyncServiceBrowser(zc.zeroconf, ["_hap._tcp.local.", "_hap._udp.local."],
                                      handlers=[lambda **kw: None])
        controller = Controller(async_zeroconf_instance=zc)
        async with controller:
            discovery = await controller.async_find(device_id)
            finish = await discovery.async_start_pairing(alias)
            pairing = await finish(pin)

            # Save the keys first, so they survive even if the check below fails.
            saved[alias] = pairing.pairing_data
            fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(saved, f, indent=2)
            os.replace(path + ".tmp", path)

            accessories = await pairing.list_accessories_and_characteristics()
            print('Paired "%s": %d accessories; keys saved to %s' % (alias, len(accessories), path))
        await browser.async_cancel()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3],
                     sys.argv[4] if len(sys.argv) > 4 else "/opt/tv-dashboard/homekit-pairings.json"))

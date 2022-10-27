"""Support for Klyqa smart devices."""
###############################################################################
#
#                   The Klyqa Home Assistant Integration
#
# Company: QConnex GmbH / Klyqa
#
# Author: Frederick Stallmeyer <frederick.stallmeyer@gmx.de>
#
###############################################################################
#
#   Features:
#       + On try switchup lamp, search the lamp in the network
#       + Load and cache profiles
#       + Address cache on discover devices and connections
#       + Mutexes asyncio lock based
#       + (Rooms working), Timers, Routines, Device Groups
#       + Remove entities when they are gone from the klyqa account
#
#   QA:
#       + Convert magicvalues to constants (commands, arguments, values)
#
##############################################################################
from __future__ import annotations
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_POLLING, DOMAIN, CONF_SYNC_ROOMS, LOGGER
from homeassistant.helpers.typing import ConfigType

from datetime import timedelta
from .datacoordinator import HAKlyqaAccount
import klyqa_ctl as klyqa_api

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    CONF_SCAN_INTERVAL,
)

PLATFORMS: list[Platform] = [Platform.LIGHT]
SCAN_INTERVAL_SECS = 120
SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECS)


class KlyqaData:
    """KlyqaData class."""

    def __init__(
        self, data_communicator: klyqa_api.Data_communicator, polling: bool = True
    ) -> None:
        """Initialize the system."""
        self.data_communicator: klyqa_api.Data_communicator = data_communicator
        self.polling: bool = polling
        self.entity_ids: set[str | None] = set()
        self.entries: dict[str, ConfigEntry] = {}
        self.remove_listeners: list[Callable] = []


async def async_setup(hass: HomeAssistant, yaml_config: ConfigType) -> bool:
    """Set up the klyqa component."""
    if DOMAIN in hass.data:
        return True
    hass.data[DOMAIN]: KlyqaData = KlyqaData(klyqa_api.Data_communicator())
    klyqa: KlyqaData = hass.data[DOMAIN]

    await klyqa.data_communicator.bind_ports()

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up or change Klyqa integration from a config entry."""

    username = str(entry.data.get(CONF_USERNAME))
    password = str(entry.data.get(CONF_PASSWORD))
    host = (
        str(entry.data.get(CONF_HOST))
        if entry.data.get(CONF_HOST) is not None
        else "https://app-api.prod.qconnex.io"
    )
    scan_interval_raw = entry.data.get(CONF_SCAN_INTERVAL)
    scan_interval = (
        int(scan_interval_raw) if scan_interval_raw is not None else SCAN_INTERVAL_SECS
    )
    polling = (
        bool(entry.data.get(CONF_POLLING))
        if entry.data.get(CONF_POLLING) is not None
        else True
    )
    global SCAN_INTERVAL
    SCAN_INTERVAL = timedelta(seconds=scan_interval)
    sync_rooms = (
        entry.data.get(CONF_SYNC_ROOMS) if entry.data.get(CONF_SYNC_ROOMS) else False
    )

    klyqa_data: KlyqaData = hass.data[DOMAIN]

    account: HAKlyqaAccount | None = None

    if (
        # DOMAIN in hass.data
        # and hasattr(klyqa_data, "entries")
        # and
        entry.entry_id
        in klyqa_data.entries
    ):
        account = klyqa_data.entries[entry.entry_id]
        await hass.async_add_executor_job(account.shutdown)

        account.username = username
        account.password = password
        account.host = host
        account.sync_rooms = sync_rooms
        account.polling = (polling,)
        account.scan_interval = scan_interval
        account.data_communicator = klyqa_data.data_communicator

    else:
        account = HAKlyqaAccount(
            klyqa_data.data_communicator,
            # component.udp,
            # component.tcp,
            username,
            password,
            host,
            hass,
            sync_rooms=sync_rooms,
            polling=polling,
            scan_interval=scan_interval,
        )
        if not hasattr(klyqa_data, "entries"):
            klyqa_data.entries = {}
        klyqa_data.entries[entry.entry_id] = account

    if not await account.login():
        return False

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, account.shutdown)

    # For previous config entries where unique_id is None
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(
            entry, unique_id=entry.data[CONF_USERNAME]
        )

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    klyqa_data: KlyqaData = hass.data[DOMAIN]

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if not unload_ok:
        return unload_ok

    while klyqa_data.remove_listeners:
        listener = klyqa_data.remove_listeners.pop(-1)
        if callable(listener):
            listener()

    if DOMAIN in hass.data:
        if entry.entry_id in klyqa_data.entries:
            if klyqa_data.entries[entry.entry_id]:
                account: klyqa_api.Klyqa_account = klyqa_data.entries[entry.entry_id]
                await hass.async_add_executor_job(account.shutdown)
            klyqa_data.entries.pop(entry.entry_id)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update."""
    await hass.config_entries.async_reload(entry.entry_id)

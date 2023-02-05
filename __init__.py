"""Support for Klyqa smart devices."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from klyqa_ctl.account import Account
from klyqa_ctl.communication.cloud import CloudBackend
from klyqa_ctl.controller_data import ControllerData
from klyqa_ctl.general.general import (
    TRACE,
    DeviceConfig,
    DeviceType,
    async_json_cache,
    format_uid,
    set_debug_logger,
)
from klyqa_ctl.klyqa_ctl import Client

from homeassistant.components.light import ENTITY_ID_FORMAT as LIGHT_ENTITY_ID_FORMAT
from homeassistant.components.vacuum import ENTITY_ID_FORMAT as VACUUM_ENTITY_ID_FORMAT
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_RESTORED,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as ent_reg
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.VACUUM]
SCAN_INTERVAL: timedelta = timedelta(seconds=120)

""" Ignore type, because the Klyqa_account class is in another file and --follow-imports=strict is on"""


class KlyqaAccount(Account):  # type: ignore[misc]
    """Klyqa account."""

    hass: HomeAssistant

    polling: bool

    def __init__(
        self,
        ctl_data: ControllerData,
        cloud: CloudBackend | None,
        hass: HomeAssistant,
        # data_communicator: api.Data_communicator,
        # username: str = "",
        # password: str = "",
        polling: bool = True,
        config_entry: ConfigEntry | None = None,
        # device_configs={},
    ) -> None:
        """HAKlyqaAccount."""

        super().__init__(ctl_data, cloud)
        self.hass = hass
        self.polling = polling
        self.config_entry: ConfigEntry | None = config_entry

        self.add_light_entity: Callable[[dict], Awaitable[None]] | None = None
        self.add_light_group_entity: Callable[[dict], Awaitable[None]] | None = None
        self.add_cleaner_entity: Callable[[dict], Awaitable[None]] | None = None

    @classmethod
    async def create_klyqa_acc(
        cls: Any,
        client: Client,
        hass: HomeAssistant,
        username: str = "",
        password: str = "",
    ) -> KlyqaAccount:
        """Factory for an account."""

        acc: KlyqaAccount = KlyqaAccount(client, client.cloud, hass)
        acc.username = username
        acc.password = password

        acc._attr_settings_lock = asyncio.Lock()
        await acc.init()
        return acc

    async def login(self) -> bool:
        """Login."""
        ret: bool = await super().login()
        if ret:
            await async_json_cache(
                {CONF_USERNAME: self.username, CONF_PASSWORD: self.password},
                "last.klyqa_integration_data.cache.json",
            )
        return ret

    async def update_account(self) -> None:
        """Update_account."""

        # await self.request_account_settings()
        await self.request_account_settings_eco()

        await self.sync_account_devices_with_ha_entities()

    async def sync_account_devices_with_ha_entities(self) -> None:

        if self.settings is None:
            return None

        entity_registry = ent_reg.async_get(self.hass)

        add_entity: Callable[[dict], Awaitable[None]] | None = None
        for device in self.settings["devices"]:
            # look if any onboarded device is not in the entity registry already
            u_id = format_uid(device["localDeviceId"])

            platform: str = ""
            entity_id: str = ""
            if self.add_light_entity and device["productId"].find(".lighting") > -1:
                platform = Platform.LIGHT
                entity_id = LIGHT_ENTITY_ID_FORMAT.format(u_id)
                add_entity = self.add_light_entity
            elif self.add_cleaner_entity and device["productId"].find(".cleaning") > -1:
                platform = Platform.VACUUM
                entity_id = VACUUM_ENTITY_ID_FORMAT.format(u_id)
                add_entity = self.add_cleaner_entity
            else:
                continue
            registered_entity_id = entity_registry.async_get_entity_id(
                platform, DOMAIN, u_id
            )

            existing = (
                self.hass.states.get(registered_entity_id)
                if registered_entity_id
                else self.hass.states.get(entity_id)
            )
            if (
                not registered_entity_id
                or not existing
                or ATTR_RESTORED in existing.attributes
            ) and add_entity:
                await add_entity(device)  # pylint: disable=not-callable

        if self.add_light_group_entity:
            for group in self.settings["deviceGroups"]:
                u_id = format_uid(group["id"])
                entity_id = LIGHT_ENTITY_ID_FORMAT.format(slugify(group["id"]))

                registered_entity_id = entity_registry.async_get_entity_id(
                    Platform.LIGHT, DOMAIN, slugify(group["id"])  # u_id
                )
                existing = (
                    self.hass.states.get(registered_entity_id)
                    if registered_entity_id
                    else self.hass.states.get(entity_id)
                )

                if (
                    not registered_entity_id
                    or not existing
                    or ATTR_RESTORED in existing.attributes
                ):
                    # found klyqa device not in the light entities
                    if (
                        len(group["devices"]) > 0
                        and "productId" in group["devices"][0]
                        and group["devices"][0]["productId"].startswith(
                            "@klyqa.lighting"
                        )
                    ):
                        await self.add_light_group_entity(
                            group
                        )  # pylint: disable=not-callable


class KlyqaControl:
    """KlyqaData class."""

    def __init__(self, polling: bool = True) -> None:
        """Initialize the system."""

        self.polling: bool = polling
        self.entity_ids: set[str | None] = set()
        self.entries: dict[str, KlyqaAccount] = {}
        self.remove_listeners: list[Callable] = []
        self.entities_area_update: dict[str, set[str]] = {}
        self.client: Client | None = None

    async def init(self) -> None:
        """Initialize klyqa control data."""
        self.client = await Client.create_worker()


async def async_setup(hass: HomeAssistant, yaml_config: ConfigType) -> bool:
    """Set up the klyqa component."""

    if DOMAIN in hass.data:
        return True

    klyqa: KlyqaControl = KlyqaControl()
    hass.data[DOMAIN] = klyqa

    await klyqa.init()

    set_debug_logger(level=TRACE)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up or change Klyqa integration from a config entry."""

    username: str = str(entry.data.get(CONF_USERNAME))
    password: str = str(entry.data.get(CONF_PASSWORD))

    klyqa: KlyqaControl = hass.data[DOMAIN]

    acc: KlyqaAccount | None = None

    if entry.entry_id in klyqa.entries:
        acc = klyqa.entries[entry.entry_id]
        if acc:
            await hass.async_add_executor_job(acc.shutdown)

            acc.username = username
            acc.password = password
            await acc.init()

    elif klyqa.client:
        acc = await KlyqaAccount.create_klyqa_acc(
            klyqa.client, hass, username, password
        )
        acc.config_entry = entry

        if not hasattr(klyqa, "entries"):
            klyqa.entries = {}
        klyqa.entries[entry.entry_id] = acc
        klyqa.client.accounts[username] = acc

    if not acc:
        return False

    await acc.login()
    await acc.get_account_state(print_onboarded_devices=False)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async def shutdown_klyqa_account(*_: Any) -> None:
        if acc:
            await acc.shutdown()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown_klyqa_account)

    # For previous config entries where unique_id is None
    if entry.unique_id is None:
        hass.config_entries.async_update_entry(
            entry, unique_id=entry.data[CONF_USERNAME]
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    klyqa_data: KlyqaControl = hass.data[DOMAIN]

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    while klyqa_data.remove_listeners:
        listener: Callable = klyqa_data.remove_listeners.pop(-1)
        if callable(listener):
            listener()

    if DOMAIN in hass.data:
        if entry.entry_id in klyqa_data.entries:
            if klyqa_data.entries[entry.entry_id]:
                account: KlyqaAccount = klyqa_data.entries[entry.entry_id]
                await hass.async_add_executor_job(account.shutdown)
            klyqa_data.entries.pop(entry.entry_id)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update."""
    await hass.config_entries.async_reload(entry.entry_id)

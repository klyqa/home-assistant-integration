"""Support for Klyqa smart devices."""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from datetime import timedelta
from logging import DEBUG
from typing import Any

from klyqa_ctl.account import Account, AccountDevice
from klyqa_ctl.communication.cloud import CloudBackend
from klyqa_ctl.controller_data import ControllerData
from klyqa_ctl.devices.device import Device
from klyqa_ctl.devices.light.commands import RequestCommand
from klyqa_ctl.devices.light.light import Light
from klyqa_ctl.devices.vacuum.vacuum import VacuumCleaner
from klyqa_ctl.general.general import (
    DEFAULT_SEND_TIMEOUT_MS,
    TRACE,
    DeviceConfig,
    TypeJson,
    format_uid,
    set_debug_logger,
    set_logger,
    LOGGER_DBG,
)
from klyqa_ctl.general.message import Message, MessageState
from klyqa_ctl.klyqa_ctl import Client

from homeassistant.components.light import ENTITY_ID_FORMAT
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_RESTORED,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State
from homeassistant.data_entry_flow import _LOGGER
from homeassistant.helpers import entity_registry as ent_reg
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.VACUUM]
SCAN_INTERVAL: timedelta = timedelta(minutes=2)
DEBUG_LEVEL = TRACE


class KlyqaAccount(Account):
    """Klyqa account."""

    hass: HomeAssistant

    polling: bool

    def __init__(
        self,
        ctl_data: ControllerData,
        cloud: CloudBackend | None,
        hass: HomeAssistant,
        polling: bool = True,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """HAKlyqaAccount."""

        super().__init__(ctl_data, cloud)
        self.hass = hass
        self.polling = polling
        self.config_entry: ConfigEntry | None = config_entry

        self.add_light_entity: Callable[
            [str, AccountDevice], Awaitable[None]
        ] | None = None
        self.add_light_group_entity: Callable[
            [dict], Awaitable[None]
        ] | None = None
        self.add_cleaner_entity: Callable[
            [str, AccountDevice], Awaitable[None]
        ] | None = None
        # self.entities_added: bool = False  # for now we add entities
        self.entity_ids: set[str | None] = set()

    @classmethod
    async def create_klyqa_acc(
        cls: Any,
        client: Client,
        hass: HomeAssistant,
        username: str = "",
        password: str = "",
    ) -> KlyqaAccount:
        """Factory for a Klyqa user account."""

        acc: KlyqaAccount = KlyqaAccount(client, client.cloud, hass)
        acc.username = username
        acc.password = password

        await acc.init()
        return acc

    async def update_account(self) -> None:
        """Update the user account."""

        try:
            await self.request_account_settings_eco()
        except:
            pass  # we continue offline

        # if not self.entities_added:
        await self.sync_account_devices_with_ha_entities()
        # self.entities_added = True

    async def is_entity_registered(self, uid: str, platform: str) -> bool:
        """Check if entity is already registered in Home Assistant."""

        entity_registry: ent_reg.EntityRegistry = ent_reg.async_get(self.hass)
        entity_id: str = ENTITY_ID_FORMAT.format(uid)

        registered_entity_id: str | None = entity_registry.async_get_entity_id(
            platform, DOMAIN, uid
        )

        existing: State | None = (
            self.hass.states.get(registered_entity_id)
            if registered_entity_id
            else self.hass.states.get(entity_id)
        )

        if (
            not registered_entity_id
            or not existing
            or ATTR_RESTORED in existing.attributes
        ):
            return False

        return True

    async def sync_account_device(
        self, u_id: str, acc_dev: AccountDevice
    ) -> None:
        """Synchronize account device with Home Assistant."""

        add_entity: Callable[
            [str, AccountDevice], Awaitable[None]
        ] | None = None

        platform: str = ""
        if self.add_light_entity and isinstance(acc_dev.device, Light):
            platform = Platform.LIGHT
            add_entity = self.add_light_entity
        elif self.add_cleaner_entity and isinstance(
            acc_dev.device, VacuumCleaner
        ):
            platform = Platform.VACUUM
            add_entity = self.add_cleaner_entity
        else:
            return

        if await self.is_entity_registered(u_id, platform):
            return

        if add_entity:
            await add_entity(u_id, acc_dev)  # pylint: disable=not-callable
            self.entity_ids.add(u_id)

    async def sync_account_group(self, group: TypeJson) -> None:
        """Synchronize account device group with Home Assistant."""

        u_id: str = format_uid(group["id"])

        if (
            await self.is_entity_registered(u_id, Platform.LIGHT)
            or u_id in self.entity_ids
        ):
            return

        if self.add_light_group_entity:
            # found klyqa device not in the light entities
            if (
                len(group["devices"]) > 0
                and "productId" in group["devices"][0]
                and group["devices"][0]["productId"].startswith(
                    "@klyqa.lighting"
                )
            ):
                await self.add_light_group_entity(  # pylint: disable=not-callable,line-too-long
                    group
                )

                self.entity_ids.add(u_id)

    async def sync_account_devices_with_ha_entities(self) -> None:
        """Synchronize account devices with Home Assistant."""

        if self.settings is None:
            return None

        for u_id, device in self.devices.items():
            if u_id not in self.entity_ids:
                await self.sync_account_device(u_id, device)

        if self.add_light_group_entity:
            for group in self.settings["deviceGroups"]:
                await self.sync_account_group(group)


class KlyqaControl:
    """KlyqaData class."""

    def __init__(self, polling: bool = True) -> None:
        """Initialize the system."""

        self.polling: bool = polling
        self.entries: dict[str, KlyqaAccount] = {}
        self.client: Client | None = None

    async def init(self) -> None:
        """Initialize klyqa control data."""

        self.client = await Client.create_worker()


def set_klyqa_logger(yaml_config: ConfigType) -> None:
    """Use integration logger for klyqa-ctl. If desired add debug logging."""

    set_logger(logger=_LOGGER)

    if (
        "logger" in yaml_config
        and "logs" in yaml_config["logger"]
        and (
            (
                "custom_components.klyqa" in yaml_config["logger"]["logs"]
                and yaml_config["logger"]["logs"]["custom_components.klyqa"]
                == "debug"
            )
            or (
                "homeassistant.components.klyqa"
                in yaml_config["logger"]["logs"]
                and yaml_config["logger"]["logs"]["custom_components.klyqa"]
                == "debug"
            )
        )
    ):
        set_debug_logger(level=DEBUG_LEVEL)
        LOGGER_DBG.propagate = False  # prevent double logging


async def async_setup(hass: HomeAssistant, yaml_config: ConfigType) -> bool:
    """Set up the klyqa component."""

    if DOMAIN in hass.data:
        return True

    set_klyqa_logger(yaml_config)

    klyqa: KlyqaControl = KlyqaControl()
    hass.data[DOMAIN] = klyqa

    await klyqa.init()

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
            await acc.shutdown()

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

    try:
        await acc.login()
        await acc.get_account_state(print_onboarded_devices=False)
    except:
        pass  # offline we continue with cache if available

    async def on_hass_stop(event: Event) -> None:
        """Logout from account."""

        await acc.shutdown()

    listener: CALLBACK_TYPE = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, on_hass_stop
    )

    entry.async_on_unload(listener)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

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

    if DOMAIN in hass.data:
        if entry.entry_id in klyqa_data.entries:
            if klyqa_data.entries[entry.entry_id]:
                acc: KlyqaAccount = klyqa_data.entries[entry.entry_id]
                await acc.shutdown()
            klyqa_data.entries.pop(entry.entry_id)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class KlyqaEntity(Entity):
    """Representation of a Klyqa entity."""

    def __init__(
        self,
        acc_dev: AccountDevice,
        acc: KlyqaAccount,
        entity_id: str,
        hass: HomeAssistant,
        should_poll: bool = True,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the Klyqa entity."""

        super().__init__()

        self.device_config: DeviceConfig = {}
        self.settings: dict[Any, Any] = {}
        self._added_to_hass: bool = False
        self.config_entry: ConfigEntry | None = None

        self._kq_acc: KlyqaAccount = acc
        self._kq_acc_dev: AccountDevice = acc_dev
        self._kq_dev: Device = acc_dev.device

        self.u_id: str = format_uid(acc_dev.acc_settings["localDeviceId"])
        self._attr_unique_id: str = format_uid(self.u_id)
        self.entity_id = entity_id

        self._attr_should_poll = False
        self.config_entry = config_entry

        def status_update_cb() -> None:
            self.update_device_state(acc_dev.device.status)

        acc_dev.device.add_status_update_cb(status_update_cb)

    async def send(
        self, command, time_to_live_secs=DEFAULT_SEND_TIMEOUT_MS
    ) -> Message | None:
        """Send command to device."""

        _LOGGER.info(
            "Send to bulb %s%s: %s",
            str(self.entity_id),
            " (" + self.name + ")" if self.name else "",
            command.msg_str(),
        )
        msg: Message | None = await self._kq_dev.send_msg_local(
            [command], time_to_live_secs=time_to_live_secs
        )
        if not msg or msg.state != MessageState.ANSWERED:
            self.update_device_state(None)
        else:
            self.update_device_state(self._kq_dev.status)
        return msg

    async def async_update_klyqa(self) -> None:
        """Fetch settings from klyqa cloud account."""

        if self._added_to_hass:
            await self._kq_acc.update_account()
        await self.async_update_settings()

    @abstractmethod
    async def async_update_settings(self) -> None:
        """Set device specific settings from the klyqa settings cloud."""

    @abstractmethod
    def update_device_state(self, state_complete) -> None:
        """Process state request response from the device to the entity
        state."""

    @abstractmethod
    async def request_device_state(self) -> None:
        """Send device state request to device."""

    async def async_update(self) -> None:
        """Fetch new state data for this device. Called by HA."""

        if not self.hass or not self.enabled:
            return

        async def update() -> None:

            name: str = f" ({self.name})" if self.name else ""
            LOGGER.info("Update device %s%s", self.entity_id, name)

            await self.async_update_klyqa()
            await self.request_device_state()

        self.hass.add_job(update)

    async def async_added_to_hass(self) -> None:
        """Added to hass."""
        await super().async_added_to_hass()
        self._added_to_hass = True

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

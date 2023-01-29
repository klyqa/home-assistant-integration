"""Support for klyqa vacuum cleaners."""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

from klyqa_ctl import klyqa_ctl as api
from klyqa_ctl.devices.device import format_uid
from klyqa_ctl.devices.vacuum import KlyqaVCResponseStatus
from klyqa_ctl.general.general import TypeJSON

from homeassistant.components.vacuum import (
    ENTITY_ID_FORMAT,
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RETURNING,
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import KlyqaAccount
from .const import DOMAIN, EVENT_KLYQA_NEW_VC, LOGGER

TIMEOUT_SEND = 30
SCAN_INTERVAL: timedelta = timedelta(seconds=210)

SUPPORT_KLYQA: int = (
    VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.START
    | VacuumEntityFeature.STATE
    | VacuumEntityFeature.STATUS
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.TURN_ON
    | VacuumEntityFeature.TURN_OFF
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Async_setup_entry."""
    klyqa: KlyqaAccount | None = None

    klyqa = hass.data[DOMAIN].entries[entry.entry_id]
    if klyqa:
        await async_setup_klyqa(
            hass, ConfigType(entry.data), async_add_entities, entry=entry, klyqa=klyqa
        )


async def async_setup_klyqa(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    klyqa: KlyqaAccount,
    discovery_info: DiscoveryInfoType | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set up the Klyqa Vacuum."""

    async def on_hass_stop(event: Event) -> None:
        """Stop push updates when hass stops."""
        await klyqa.search_and_send_loop_task_stop()
        await hass.async_add_executor_job(klyqa.shutdown)

    listener: CALLBACK_TYPE = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, on_hass_stop
    )

    if entry:
        entry.async_on_unload(listener)

    entity_registry: EntityRegistry = er.async_get(hass)

    async def add_new_entity(event: Event) -> None:

        user: str = event.data["user"]
        if user != entry.data.get(CONF_USERNAME):
            return

        device_settings: dict[str, Any] = event.data["data"]

        u_id: str = format_uid(device_settings["localDeviceId"])

        entity_id: str = ENTITY_ID_FORMAT.format(u_id)

        device_state: api.KlyqaVC = (
            klyqa.devices[u_id] if u_id in klyqa.devices else api.KlyqaVC()
        )

        registered_entity_id: str | None = entity_registry.async_get_entity_id(
            Platform.VACUUM, DOMAIN, u_id
        )

        if registered_entity_id and registered_entity_id != entity_id:
            entity_registry.async_remove(str(registered_entity_id))

        registered_entity_id = entity_registry.async_get_entity_id(
            Platform.VACUUM, DOMAIN, u_id
        )

        LOGGER.info("Add entity %s (%s)", entity_id, device_settings.get("name"))
        new_entity: KlyqaVC = KlyqaVC(
            device_settings,
            device_state,
            klyqa,
            entity_id,
            should_poll=klyqa.polling,
            config_entry=entry,
            hass=hass,
        )
        await new_entity.async_update_settings()
        new_entity.update_device_state(device_state.status)
        if new_entity:
            add_entities([new_entity], True)

    hass.data[DOMAIN].remove_listeners.append(
        hass.bus.async_listen(EVENT_KLYQA_NEW_VC, add_new_entity)
    )

    await klyqa.update_account(device_type=api.DeviceType.cleaner.name)
    return


class KlyqaVC(StateVacuumEntity):
    """Representation of the Klyqa vacuum cleaner."""

    _klyqa_api: KlyqaAccount
    _klyqa_device: api.KlyqaVC
    settings: dict[Any, Any] = {}
    """synchronise rooms to HA"""

    config_entry: ConfigEntry | None = None
    entity_registry: EntityRegistry | None = None
    """entity added finished"""
    _added_klyqa: bool = False
    u_id: str
    send_event_cb: asyncio.Event
    hass: HomeAssistant
    _state: str | None = None

    def __init__(
        self,
        settings: dict[str, Any],
        device: api.KlyqaVC,
        klyqa_api: KlyqaAccount,
        entity_id: str,
        hass: HomeAssistant,
        should_poll: bool = True,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize a Klyqa vacuum cleaner."""
        self.hass = hass

        self._attr_supported_features = SUPPORT_KLYQA

        self._klyqa_account = klyqa_api

        self.u_id = format_uid(settings["localDeviceId"])
        self._attr_unique_id: str = format_uid(self.u_id)
        self._klyqa_device = device
        self.entity_id = entity_id

        self._attr_should_poll = should_poll

        self.config_entry = config_entry
        self.send_event_cb = asyncio.Event()

        self.device_config: api.Device_config = {}
        self.settings = {}

        self._attr_fan_speed_list = [
            api.VC_SUCTION_STRENGTHS.NULL.name,
            api.VC_SUCTION_STRENGTHS.SMALL.name,
            api.VC_SUCTION_STRENGTHS.NORMAL.name,
            api.VC_SUCTION_STRENGTHS.STRONG.name,
            api.VC_SUCTION_STRENGTHS.MAX.name,
        ]
        self._state = None
        self._attr_battery_level = 0
        self.state_complete: KlyqaVCResponseStatus | None = None

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum cleaner, do not return to base."""
        args: list[str] = ["set", "--cleaning", "off"]

        await self.send_to_devices(args)

    async def async_start(self) -> None:
        """Start or resume the cleaning task.

        This method must be run in the event loop.
        """
        args: list[str] = ["set", "--cleaning", "on"]

        await self.send_to_devices(args)

    async def async_update_settings(self) -> None:
        """Set device specific settings from the klyqa settings cloud."""

        if self._klyqa_account.acc_settings is None:
            return

        """Look up profile."""
        if self._klyqa_device.device_config:
            self.device_config = self._klyqa_device.device_config
        else:
            acc: KlyqaAccount = self._klyqa_account
            response_object: TypeJSON | None = await acc.request(
                "/config/product/" + self.settings["productId"],
                timeout=30,
            )
            if response_object is not None:
                self.device_config = response_object

        devices_settings: Any | None = (
            self._klyqa_account.acc_settings["devices"]
            if "devices" in self._klyqa_account.acc_settings
            else None
        )

        if devices_settings is None:
            return
        device_result: list[Any] = [
            x
            for x in devices_settings
            if format_uid(str(x["localDeviceId"])) == self.u_id
        ]
        if len(device_result) < 1:
            return

        self.settings = device_result[0]

        self._attr_name = self.settings["name"]
        self._attr_unique_id = format_uid(self.settings["localDeviceId"])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self.name,
            manufacturer="QConnex GmbH",
            model=self.settings["productId"],
            sw_version=self.settings["firmwareVersion"],
            hw_version=self.settings["hardwareRevision"],
        )

        if (
            self.device_config
            and "productId" in self.device_config
            and self.device_config["productId"] in api.PRODUCT_URLS
        ):
            self._attr_device_info["configuration_url"] = api.PRODUCT_URLS[
                self.device_config["productId"]
            ]

        entity_registry: EntityRegistry = er.async_get(self.hass)
        entity_id: str | None = entity_registry.async_get_entity_id(
            Platform.VACUUM, DOMAIN, str(self.unique_id)
        )
        entity_registry_entry: RegistryEntry | None = None
        if entity_id:
            entity_registry_entry = entity_registry.async_get(str(entity_id))

        device_registry: dr.DeviceRegistry = dr.async_get(self.hass)

        if self.config_entry:

            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id, **self._attr_device_info
            )

        if entity_registry_entry:
            self._attr_device_info["suggested_area"] = entity_registry_entry.area_id

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the vacuum on and start cleaning."""
        args: list[str] = ["--power", "on"]

        await self.send_to_devices(args)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the vacuum off stopping the cleaning and returning home."""

        args: list[str] = ["set", "--workingmode", "CHARGE_GO"]

        await self.send_to_devices(args)

    async def async_update_klyqa(self) -> None:
        """Fetch settings from klyqa cloud account."""

        await self._klyqa_account.request_account_settings()  # _settings_eco()
        if self._added_klyqa:
            await self._klyqa_account.process_account_settings(device_type="vacuum")
        await self.async_update_settings()

    async def async_update(self) -> None:
        """Fetch new state data for this device. Called by HA."""

        name: str = f" ({self.name})" if self.name else ""
        LOGGER.info("Update device %s%s", self.entity_id, name)

        await self.async_update_klyqa()

        await self.send_to_devices(["get", "--all"])

        if self.u_id in self._klyqa_account.devices:
            self.update_device_state(self._klyqa_account.devices[self.u_id].status)

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""
        if self.u_id not in self._klyqa_account.devices:
            return
        set_to: str = "on"
        status: KlyqaVCResponseStatus | None = self._klyqa_account.devices[
            self.u_id
        ].status
        if status is not None and status.beeping == "on":
            # if self.state_complete and self.state_complete["beeping"] == "on":
            set_to = "off"
        await self.send_to_devices(["set", "--beeping", set_to])

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed.

        This method must be run in the event loop.
        """

        await self.send_to_devices(["set", "--suction", fan_speed])

    async def async_pause(self) -> None:
        """Pause the cleaning task.

        This method must be run in the event loop.
        """
        await self.send_to_devices(["set", "--workingmode", "STANDBY"])

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock.

        This method must be run in the event loop.
        """
        await self.send_to_devices(["set", "--workingmode", "CHARGE_GO"])

    async def send_to_devices(
        self,
        args: list[str],
        callback: Callable[[Any, str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Send_to_devices."""

        async def send_answer_cb(msg: api.Message, uid: str) -> None:
            nonlocal callback
            if callback is not None:
                await callback(msg, uid)

            LOGGER.debug("Send_answer_cb %s", str(uid))
            # ttl ended
            if uid != self.u_id or self.u_id not in self._klyqa_account.devices:
                return

            if self.u_id in self._klyqa_account.devices:
                self.update_device_state(self._klyqa_account.devices[self.u_id].status)
                if self._added_klyqa:
                    self.schedule_update_ha_state()

        parser: argparse.ArgumentParser = api.get_description_parser()
        args = ["--local", "--device_unitids", f"{self.u_id}"] + args
        args.insert(0, api.DeviceType.cleaner.name)
        api.add_config_args(parser=parser)
        api.add_command_args_cleaner(parser=parser)

        args_parsed = parser.parse_args(args=args)

        LOGGER.info("Send start!")
        new_task = asyncio.create_task(
            self._klyqa_account.send_to_devices(
                args_parsed,
                args,
                async_answer_callback=send_answer_cb,
                timeout_ms=TIMEOUT_SEND * 1000,
            )
        )
        try:
            await asyncio.wait([new_task], timeout=0.001)
        except asyncio.TimeoutError:
            pass

    async def async_added_to_hass(self) -> None:
        """Added to hass."""
        await super().async_added_to_hass()
        self._added_klyqa = True

        self.schedule_update_ha_state()
        await self.async_update_settings()

    def update_device_state(self, state_complete: api.KlyqaVCResponseStatus) -> None:
        """Process state request response from the device to the entity state."""
        self._attr_assumed_state = True

        if not state_complete or not isinstance(
            state_complete, api.KlyqaVCResponseStatus
        ):
            return

        LOGGER.debug(
            "Update vc state %s%s",
            str(self.entity_id),
            " (" + self.name + ")" if self.name else "",
        )

        if state_complete.type == "error":
            LOGGER.error(state_complete.type)
            return

        state_type: str = state_complete.type
        if not state_type or state_type != "status":
            return

        self._klyqa_device.status = state_complete

        self._attr_battery_level = (
            int(state_complete.battery) if state_complete.battery else 0
        )

        status: list[str] = [
            STATE_IDLE,
            STATE_PAUSED,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_CLEANING,
            STATE_RETURNING,
            STATE_DOCKED,
            STATE_IDLE,
            STATE_DOCKED,
            STATE_ERROR,
        ]

        self._state = (
            status[state_complete.workingstatus - 1]
            if state_complete.workingstatus is not None
            and state_complete.workingstatus > 0
            and state_complete.workingstatus < len(status)
            else None
        )
        speed_name: str | None = (
            list(api.VC_SUCTION_STRENGTHS)[state_complete.suction - 1].name
            if state_complete.suction is not None
            else None
        )

        # retranslate our suction ids to HA
        speed: int | None = (
            int(self._attr_fan_speed_list.index(speed_name))
            if speed_name is not None
            else None
        )
        self._attr_fan_speed = (
            self._attr_fan_speed_list[speed] if speed is not None and speed > -1 else ""
        )

        self._attr_assumed_state = False
        self.state_complete = state_complete

    @property
    def state(self) -> str | None:
        """Return the state of the vacuum cleaner."""
        if self._state is None:
            return STATE_ERROR
        return self._state

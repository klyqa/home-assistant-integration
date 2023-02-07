"""Support for klyqa vacuum cleaners."""
from __future__ import annotations

from typing import Any

from klyqa_ctl import klyqa_ctl as api
from klyqa_ctl.account import AccountDevice
from klyqa_ctl.communication.cloud import RequestMethod
from klyqa_ctl.devices.vacuum.commands import (
    RequestGetCommand,
    RequestResetCommand,
    RequestSetCommand,
)
from klyqa_ctl.devices.vacuum.general import (
    VcSuctionStrengths,
    VcWorkingMode,
    VcWorkingStatus,
)
from klyqa_ctl.devices.vacuum.response_status import ResponseStatus
from klyqa_ctl.general.general import PRODUCT_URLS, TypeJson, format_uid

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
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import SCAN_INTERVAL, KlyqaAccount, KlyqaEntity
from .const import DOMAIN, LOGGER

TIMEOUT_SEND = 30
# SCAN_INTERVAL: timedelta = timedelta(minutes=5)

SUPPORT_KLYQA: VacuumEntityFeature = (
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
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Async_setup_entry."""

    klyqa: KlyqaAccount | None = None

    klyqa = hass.data[DOMAIN].entries[entry.entry_id]
    if klyqa:
        await async_setup_klyqa(
            hass,
            ConfigType(entry.data),
            async_add_entities,
            entry=entry,
            acc=klyqa,
        )


async def async_setup_klyqa(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    acc: KlyqaAccount,
    discovery_info: DiscoveryInfoType | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set up the Klyqa Vacuum."""

    async def on_hass_stop(event: Event) -> None:
        """Stop push updates when hass stops."""

        await hass.async_add_executor_job(acc.shutdown)

    listener: CALLBACK_TYPE = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, on_hass_stop
    )

    if entry:
        entry.async_on_unload(listener)

    entity_registry: EntityRegistry = er.async_get(hass)

    async def add_cleaner_entity(u_id: str, acc_dev: AccountDevice) -> None:

        entity_id: str = ENTITY_ID_FORMAT.format(u_id)

        registered_entity_id: str | None = entity_registry.async_get_entity_id(
            Platform.VACUUM, DOMAIN, u_id
        )

        if registered_entity_id and registered_entity_id != entity_id:
            entity_registry.async_remove(str(registered_entity_id))

        registered_entity_id = entity_registry.async_get_entity_id(
            Platform.VACUUM, DOMAIN, u_id
        )

        LOGGER.info(
            "Add entity %s (%s)", entity_id, acc_dev.acc_settings.get("name")
        )
        new_entity: KlyqaVCEntity = KlyqaVCEntity()
        new_entity.init(
            acc_dev,
            acc,
            entity_id,
            should_poll=acc.polling,
            config_entry=entry,
            hass=hass,
        )
        if new_entity:
            add_entities([new_entity], True)

    acc.add_cleaner_entity = add_cleaner_entity

    await acc.update_account()
    return


class KlyqaVCEntity(StateVacuumEntity, KlyqaEntity):
    """Representation of the Klyqa vacuum cleaner."""

    _state: str | None = None

    def __init__(
        self,
    ) -> None:
        """Initialize a Klyqa vacuum cleaner."""

        super().__init__()

        self._attr_supported_features = SUPPORT_KLYQA

        self._attr_fan_speed_list = [
            VcSuctionStrengths.NULL.name,
            VcSuctionStrengths.SMALL.name,
            VcSuctionStrengths.NORMAL.name,
            VcSuctionStrengths.STRONG.name,
            VcSuctionStrengths.MAX.name,
        ]
        self._attr_state = None
        self._state: str | None = None
        self._attr_battery_level = 0
        self.state_complete: ResponseStatus | None = None

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum cleaner, do not return to base."""

        await self.send(RequestSetCommand(cleaning="off"))

    async def async_start(self) -> None:
        """Start or resume the cleaning task."""

        await self.send(RequestSetCommand(cleaning="on"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the vacuum on and start cleaning."""

        await self.send(RequestSetCommand(power="on"))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the vacuum off stopping the cleaning and returning home."""

        await self.send(RequestSetCommand(workingmode="CHARGE_GO"))

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""

        if self.u_id not in self._kq_acc.devices:
            return

        set_to: str = "on"
        status: ResponseStatus | None = self._kq_dev.status()

        if status is not None and status.beeping == "on":
            set_to = "off"

        await self.send(RequestSetCommand(beeping=set_to))

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed.

        This method must be run in the event loop.
        """

        await self.send(RequestSetCommand(suction=fan_speed))

    async def async_pause(self) -> None:
        """Pause the cleaning task.

        This method must be run in the event loop.
        """

        await self.send(RequestSetCommand(workingmode="STANDBY"))

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock.

        This method must be run in the event loop.
        """

        await self.send(RequestSetCommand(workingmode="CHARGE_GO"))

    async def async_update_settings(self) -> None:
        """Set device specific settings from the klyqa settings cloud."""

        settings: TypeJson = self._kq_acc_dev.acc_settings

        if self._kq_acc.settings is None:
            return

        # Look up profile.
        if self._kq_dev.device_config:
            self.device_config = self._kq_dev.device_config
        else:
            acc: KlyqaAccount = self._kq_acc
            response_object: TypeJson | None = await acc.request_beared(
                RequestMethod.GET,
                "/config/product/" + settings["productId"],
                timeout=30,
            )
            if response_object is not None:
                self.device_config = response_object

        devices_settings: Any | None = (
            self._kq_acc.settings["devices"]
            if "devices" in self._kq_acc.settings
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

        settings = device_result[0]

        self._attr_name = settings["name"]
        self._attr_unique_id = format_uid(settings["localDeviceId"])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=self.name,
            manufacturer="QConnex GmbH",
            model=settings["productId"],
            sw_version=settings["firmwareVersion"],
            hw_version=settings["hardwareRevision"],
        )

        if (
            self.device_config
            and "productId" in self.device_config
            and self.device_config["productId"] in PRODUCT_URLS
        ):
            self._attr_device_info["configuration_url"] = PRODUCT_URLS[
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
                config_entry_id=self.config_entry.entry_id,
                **self._attr_device_info,
            )

        if entity_registry_entry:
            self._attr_device_info[
                "suggested_area"
            ] = entity_registry_entry.area_id

    def update_device_state(self, state_complete: ResponseStatus) -> None:
        """Process state request response from the device to the entity state."""

        self._attr_assumed_state = True

        if not state_complete or not isinstance(
            state_complete, ResponseStatus
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

        self._kq_dev.status = state_complete

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
            list(VcSuctionStrengths)[state_complete.suction - 1].name
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
            self._attr_fan_speed_list[speed]
            if speed is not None and speed > -1
            else ""
        )

        self._attr_assumed_state = False
        self.state_complete = state_complete

    @property
    def state(self) -> str | None:
        """Return the state of the vacuum cleaner."""
        if self._state is None:
            return STATE_ERROR
        return self._state

"""Support for klyqa lights."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

import klyqa_ctl as api
from klyqa_ctl.devices.device import Device as KlyqaDevice
from klyqa_ctl.devices.light.commands import (
    RequestCommand,
    PowerCommand,
    ColorCommand,
    TemperatureCommand,
    BrightnessCommand,
    RoutinePutCommand,
    TransitionCommand,
)
from klyqa_ctl.devices.light.response_status import ResponseStatus
from klyqa_ctl.account import AccountDevice
from klyqa_ctl.general.general import (
    TypeJson,
    format_uid,
    DeviceType,
    DeviceConfig,
    PRODUCT_URLS,
    RgbColor,
    Command,
)

from klyqa_ctl.general.message import (
    Message,
    MessageState,
)
from klyqa_ctl.devices.light.light import Light as KlyqaLight
from klyqa_ctl.devices.light.scenes import SCENES as BULB_SCENES
from klyqa_ctl.communication.cloud import RequestMethod


from homeassistant.components.group.light import LightGroup
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_TRANSITION,
    ENTITY_ID_FORMAT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.area_registry import AreaEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import slugify
import homeassistant.util.color as color_util
from homeassistant.util.color import (
    color_temperature_kelvin_to_mired,
    color_temperature_mired_to_kelvin,
)

from . import KlyqaAccount, KlyqaControl
from .const import DOMAIN, LOGGER

TIMEOUT_SEND = 30
SCAN_INTERVAL = timedelta(seconds=210)

SUPPORT_KLYQA = LightEntityFeature.TRANSITION


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Async_setup_entry."""

    acc: KlyqaAccount = hass.data[DOMAIN].entries[entry.entry_id]
    if acc:
        await async_setup_klyqa(
            hass, ConfigType(entry.data), async_add_entities, entry=entry, acc=acc
        )


async def async_setup_klyqa(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    acc: KlyqaAccount,
    discovery_info: DiscoveryInfoType | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set up the Klyqa Light platform."""

    klyqa_data: KlyqaControl = hass.data[DOMAIN]

    async def on_hass_stop(event: Event) -> None:
        """Stop push updates when hass stops."""
        # await klyqa.search_and_send_loop_task_stop()
        await hass.async_add_executor_job(acc.shutdown)

    if entry:
        listener = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
        entry.async_on_unload(listener)

    entity_registry: EntityRegistry = er.async_get(hass)

    async def add_new_light_group(device_settings: dict) -> None:

        entity: KlyqaLightGroupEntity = KlyqaLightGroupEntity(hass, device_settings)

        add_entities([entity], True)

    async def add_new_light(device_settings: dict) -> None:

        u_id: str = format_uid(device_settings["localDeviceId"])

        entity_id: str = ENTITY_ID_FORMAT.format(u_id)

        acc_device: AccountDevice = (
            acc.devices[u_id]
            if u_id in acc.devices
            else await acc.get_or_create_device(u_id)
        )

        # Clear status added from cloud when the bulb is not connected to the cloud so offline
        if not acc_device.device.cloud.connected:
            acc_device.device.status = None

        registered_entity_id: str | None = entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, u_id
        )

        if registered_entity_id and registered_entity_id != entity_id:
            entity_registry.async_remove(str(registered_entity_id))

        registered_entity_id = entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, u_id
        )

        LOGGER.info("Add entity %s (%s)", entity_id, device_settings.get("name"))

        new_entity: KlyqaLightEntity = KlyqaLightEntity(
            device_settings,
            acc_device,
            acc,
            entity_id,
            should_poll=acc.polling,
            config_entry=entry,
            hass=hass,
        )
        await new_entity.async_update_settings()
        new_entity.update_device_state(acc_device.device.status)
        if new_entity:
            add_entities([new_entity], True)

    acc.add_light_entity = add_new_light
    acc.add_light_group_entity = add_new_light_group

    await acc.update_account()

    return


class KlyqaLightGroupEntity(LightGroup):
    """Lightgroup."""

    # TDB:  light groups produces same entity ids again and takes name not uid as unique_id

    def __init__(self, hass: HomeAssistant, settings: dict[Any, Any]) -> None:
        """Lightgroup."""
        self.hass = hass
        self.settings = settings

        u_id = format_uid(settings["id"])

        self.entity_id = ENTITY_ID_FORMAT.format(slugify(settings["id"]))

        entity_ids: list[str] = []

        for device in settings["devices"]:
            uid = format_uid(device["localDeviceId"])

            entity_ids.append(ENTITY_ID_FORMAT.format(uid))

        super().__init__(slugify(u_id), settings["name"], entity_ids, mode=None)


class KlyqaLightEntity(RestoreEntity, LightEntity):
    """Representation of the Klyqa light."""

    _attr_supported_features = SUPPORT_KLYQA
    _attr_transition_time = 500

    _klyqa_account: KlyqaAccount
    _klyqa_device: KlyqaLight
    settings: dict[Any, Any] = {}
    config_entry: ConfigEntry | None = None
    entity_registry: EntityRegistry | None = None
    # entity added finished
    _added_klyqa: bool = False
    u_id: str
    send_event_cb: asyncio.Event
    hass: HomeAssistant

    def __init__(
        self,
        settings: dict[str, Any],
        acc_device: AccountDevice,
        acc: KlyqaAccount,
        entity_id: str,
        hass: HomeAssistant,
        should_poll: bool = True,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize a Klyqa Light Bulb."""
        self.hass = hass

        self._klyqa_account = acc
        self.u_id = format_uid(settings["localDeviceId"])
        self._attr_unique_id: str = slugify(self.u_id)
        self._acc_device: AccountDevice = acc_device
        self._klyqa_device = acc_device.device
        self.entity_id = entity_id

        self._attr_should_poll = should_poll
        self._attr_device_class = "light"
        self._attr_icon = "mdi:lightbulb"
        self._attr_supported_color_modes: set[ColorMode] = set()
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_effect_list = []
        self.config_entry = config_entry
        self.send_event_cb = asyncio.Event()

        self.device_config: DeviceConfig = {}
        self.settings = {}
        self.rooms: list[Any] = []

    async def set_device_capabilities(self) -> None:
        """Look up profile."""
        # if self.settings["productId"] in api.device_configs:
        if self._klyqa_device.device_config:
            self.device_config = (
                self._klyqa_device.device_config
            )  # api.device_configs[self.settings["productId"]]
        else:
            acc: KlyqaAccount = self._klyqa_account
            # response_object: TypeJson | None = await self.hass.async_add_executor_job(
            #     partial(
            #         acc.request,
            #         "/config/product/" + self.settings["productId"],
            #         timeout=30,
            #     )
            # )
            response_object: TypeJson | None = await acc.request_beared(
                RequestMethod.GET,
                "/config/product/" + self.settings["productId"],
                timeout=30,
            )
            if response_object is not None:
                self.device_config = response_object

        if not self.device_config:
            return

        if (
            self.device_config
            and "deviceTraits" in self.device_config
            and (device_traits := self.device_config["deviceTraits"])
        ):
            if [
                x
                for x in device_traits
                if "msg_key" in x and x["msg_key"] == "temperature"
            ]:
                self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
                self._attr_max_color_temp_kelvin = 6500
                self._attr_min_color_temp_kelvin = 2000

            if [x for x in device_traits if "msg_key" in x and x["msg_key"] == "color"]:
                self._attr_supported_color_modes.add(ColorMode.RGB)
                self._attr_supported_features |= LightEntityFeature.EFFECT  # type: ignore[assignment]
                self._attr_effect_list = [x["label"] for x in BULB_SCENES]
            else:
                self._attr_effect_list = [
                    x["label"] for x in BULB_SCENES if "cwww" in x
                ]

    async def async_update_settings(self) -> None:
        """Set device specific settings from the klyqa settings cloud."""

        if self._klyqa_account.settings is None:
            return

        devices_settings: Any | None = (
            self._klyqa_account.settings["devices"]
            if "devices" in self._klyqa_account.settings
            else None
        )

        if devices_settings is None:
            return

        device_result = [
            x
            for x in devices_settings
            if format_uid(str(x["localDeviceId"])) == self.u_id
        ]
        if len(device_result) < 1:
            return

        self.settings = device_result[0]
        await self.set_device_capabilities()

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
            and self.device_config["productId"] in PRODUCT_URLS
        ):
            self._attr_device_info["configuration_url"] = PRODUCT_URLS[
                self.device_config["productId"]
            ]

        entity_registry = er.async_get(self.hass)
        entity_id: str | None = entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, str(self.unique_id)
        )
        entity_registry_entry: RegistryEntry | None = None
        if entity_id:
            entity_registry_entry = entity_registry.async_get(str(entity_id))

        device_registry = dr.async_get(self.hass)

        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self._attr_unique_id)}
        )

        if entity_registry_entry:
            self._attr_device_info["suggested_area"] = entity_registry_entry.area_id

        device_entry: dr.DeviceEntry | None = None
        if self.config_entry:
            device_entry = device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                **self._attr_device_info,
            )

        self.rooms = []
        for room in self._klyqa_account.settings["rooms"]:
            for dev in room["devices"]:
                if dev and format_uid(dev["localDeviceId"]) == self.u_id:
                    self.rooms.append(room)

        if (
            entity_registry_entry
            and entity_registry_entry.area_id != ""
            and len(self.rooms) == 0
        ):
            entity_registry.async_update_entity(
                entity_id=entity_registry_entry.entity_id, area_id=""
            )

        if (
            device_entry is not None
            and device is not None
            and device.area_id != ""
            and len(self.rooms) == 0
        ):
            device_registry.async_update_device(device_entry.id, area_id="")

        elif len(self.rooms) > 0:
            room = self.rooms[0]["name"]
            area_reg = ar.async_get(self.hass)
            # only 1 room supported per device by ha
            area: AreaEntry | None = area_reg.async_get_area_by_name(room)

            if not area:
                self.hass.data[DOMAIN].entities_area_update.setdefault(room, set()).add(
                    self.entity_id
                )
                # new area first add
                LOGGER.info("Create new room %s", room)
                area = area_reg.async_get_or_create(room)
                LOGGER.info("Add bulb %s to new room %s", self.name, area.name)

            if area:
                if device_entry is not None and entity_registry_entry:
                    device_registry.async_update_device(
                        device_entry.id, area_id=entity_registry_entry.area_id
                    )

                if entity_registry_entry and entity_registry_entry.area_id != area.id:
                    LOGGER.info("Add bulb %s to room %s", self.name, area.name)
                    entity_registry.async_update_entity(
                        entity_id=entity_registry_entry.entity_id, area_id=area.id
                    )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self.hass.async_create_task(self._klyqa_account.update_account())

        # args: list[str] = []
        command: Command | None = None

        if ATTR_HS_COLOR in kwargs:
            self._attr_rgb_color = color_util.color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
            self._attr_hs_color = kwargs[ATTR_HS_COLOR]

        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        if self._attr_rgb_color and (
            self._attr_rgb_color and ATTR_RGB_COLOR in kwargs or ATTR_HS_COLOR in kwargs
        ):
            command = ColorCommand(color=RgbColor(*self._attr_rgb_color))
            # args.extend(
            #     ["--color", *([str(rgb) for rgb in self._attr_rgb_color])]  # type: ignore[union-attr]
            # )

        # if ATTR_RGBWW_COLOR in kwargs:
        #     self._attr_rgbww_color = kwargs[ATTR_RGBWW_COLOR]
        #     args.extend(
        #         [
        #             "--percent_color",
        #             *([str(rgb) for rgb in self._attr_rgbww_color]),  # type: ignore[union-attr]
        #         ]
        #     )

        if ATTR_EFFECT in kwargs:

            scene_result = [x for x in BULB_SCENES if x["label"] == kwargs[ATTR_EFFECT]]
            if len(scene_result) > 0:
                scene = scene_result[0]
                self._attr_effect = kwargs[ATTR_EFFECT]
                commands = scene["commands"]
                if len(commands.split(";")) > 2:
                    commands += "l 0;"

                # send_event_cb: asyncio.Event = asyncio.Event()

                # async def callback(msg: Message, uid: str) -> None:
                #     nonlocal args, self
                #     if msg.state in (
                #         MessageState.SENT,
                #         MessageState.ANSWERED,
                #     ):
                #         send_event_cb.set()
                #         args.extend(
                #             [
                #                 "--routine_id",
                #                 "0",
                #                 "--routine_start",
                #             ]
                #         )

                command = RoutinePutCommand(
                    commands=commands, id="0", scene=str(scene["id"])
                )
                # await self._klyqa_device.send_msg_local([command])
                await self.send(command)
                # await self.send_to_bulbs(
                #     [
                #         "--routine_id",
                #         "0",
                #         "--routine_scene",
                #         str(scene["id"]),
                #         "--routine_put",
                #         "--routine_command",
                #         commands,
                #     ],
                #     callback,
                # )

                # await send_event_cb.wait()

        if ATTR_COLOR_TEMP in kwargs:
            self._attr_color_temp = kwargs[ATTR_COLOR_TEMP]
            command = TemperatureCommand(
                temperature=(
                    color_temperature_mired_to_kelvin(self._attr_color_temp)
                    if self._attr_color_temp
                    else 0
                ),
            )
            # args.extend(
            #     [
            #         "--temperature",
            #         str(
            #             color_temperature_mired_to_kelvin(self._attr_color_temp)
            #             if self._attr_color_temp
            #             else 0
            #         ),
            #     ]
            # )

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = int(kwargs[ATTR_BRIGHTNESS])

            # args.extend(
            #     ["--brightness", str(round((self._attr_brightness / 255.0) * 100.0))]
            # )
            command = BrightnessCommand(
                brightness=(round((self._attr_brightness / 255.0) * 100.0))
            )

        if ATTR_BRIGHTNESS_PCT in kwargs:
            self._attr_brightness = int(
                round((kwargs[ATTR_BRIGHTNESS_PCT] / 100) * 255)
            )
            # args.extend(["--brightness", str(self._attr_brightness)])
            command = BrightnessCommand(brightness=self._attr_brightness)

        # separate power on+transition and other lamp attributes

        # if len(args) > 0:
        if command:

            if ATTR_TRANSITION in kwargs:
                self._attr_transition_time = kwargs[ATTR_TRANSITION]

            if self._attr_transition_time and isinstance(command, TransitionCommand):
                # args.extend(["--transitionTime", str(self._attr_transition_time)])
                command.transition_time = self._attr_transition_time

            LOGGER.info(
                "Send to bulb %s%s: %s",
                str(self.entity_id),
                " (" + self.name + ")" if self.name else "",
                command.msg_str(),
            )

            # await self.send_to_bulbs(args)
            # await self._klyqa_device.send_msg_local([command])
            await self.send(command)
            await asyncio.sleep(0.2)

        # args = ["--power", "on"]
        command = PowerCommand()
        # if ATTR_TRANSITION in kwargs:
        #     self._attr_transition_time = kwargs[ATTR_TRANSITION]

        # if self._attr_transition_time:
        #     # args.extend(["--transitionTime", str(self._attr_transition_time)])
        #     command.transition_time = self._attr_transition_time

        LOGGER.info(
            "Send to bulb %s%s: %s",
            self.entity_id,
            f" ({self.name})" if self.name else "",
            command.msg_str(),
        )
        await self.send(command)
        # await self._klyqa_device.send_msg_local([command])

        # if self.u_id in self._klyqa_account.devices:
        #     self.update_device_state(self._klyqa_device.status)
        #     if self._added_klyqa:
        #         self.schedule_update_ha_state()

        # await self.send_to_bulbs(args)

    async def send(self, command) -> None:
        await self._klyqa_device.send_msg_local([command])

        if self.u_id in self._klyqa_account.devices:
            self.update_device_state(self._klyqa_device.status)
            if self._added_klyqa:
                self.schedule_update_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""

        # args: list[str] = ["--power", "off"]

        # if self._attr_transition_time:
        #     args.extend(["--transitionTime", str(self._attr_transition_time)])
        command: Command = PowerCommand(status="off")

        LOGGER.info(
            "Send to bulb %s%s: %s",
            {self.entity_id},
            f" ({self.name})" if self.name else "",
            command.msg_str(),
        )
        # await self.send_to_bulbs(args)
        await self.send(command)
        # await self._klyqa_device.send_msg_local([command])

    async def async_update_klyqa(self) -> None:
        """Fetch settings from klyqa cloud account."""

        await self._klyqa_account.request_account_settings_eco()

        if self._added_klyqa:
            await self._klyqa_account.update_account()
        await self.async_update_settings()

    async def async_update(self) -> None:
        """Fetch new state data for this light. Called by HA."""

        name = f" ({self.name})" if self.name else ""
        LOGGER.info("Update bulb %s%s", self.entity_id, name)

        await self.async_update_klyqa()

        # if self._added_klyqa:
        # await self.send_to_bulbs(["--request"])
        # await self._klyqa_device.send_msg_local([RequestCommand()])
        await self.send(RequestCommand())

        # if self.u_id in self._klyqa_account.devices and self._klyqa_device.status:
        #     self.update_device_state(self._klyqa_device.status)

    # async def send_to_bulbs(
    #     self,
    #     args: list[Any],
    #     callback: Callable[[Any, str], Coroutine[Any, Any, None]] | None = None,
    # ) -> None:
    #     """Send_to_bulbs."""

    #     async def send_answer_cb(msg: Message, uid: str) -> None:
    #         nonlocal callback
    #         if callback is not None:
    #             await callback(msg, uid)

    #         LOGGER.debug("Send_answer_cb %s", str(uid))

    #         if uid != self.u_id:
    #             return

    #         if self.u_id in self._klyqa_account.devices:
    #             self.update_device_state(self._klyqa_account.devices[self.u_id].status)
    #             if self._added_klyqa:
    #                 self.schedule_update_ha_state()

    #     parser = api.get_description_parser()
    #     args.extend(["--debug", "--local", "--device_unitids", f"{self.u_id}"])

    #     args.insert(0, DeviceType.LIGHTING.name)
    #     add_config_args(parser=parser)
    #     add_command_args_bulb(parser=parser)

    #     args_parsed = parser.parse_args(args=args)

    #     new_task = asyncio.create_task(
    #         self._klyqa_account.send_to_devices(
    #             args_parsed,
    #             args,
    #             async_answer_callback=send_answer_cb,
    #             timeout_ms=TIMEOUT_SEND * 1000,
    #         )
    #     )

    #     try:
    #         await asyncio.wait([new_task], timeout=0.001)
    #     except asyncio.TimeoutError:
    #         pass

    async def async_added_to_hass(self) -> None:
        """Added to hass."""
        await super().async_added_to_hass()
        self._added_klyqa = True
        self.schedule_update_ha_state()

        await self.async_update_settings()

    def update_device_state(self, state_complete: ResponseStatus | None) -> None:
        """Process state request response from the bulb to the entity state."""
        self._attr_assumed_state = True

        if not state_complete or not isinstance(state_complete, ResponseStatus):
            self._attr_is_on = False
            self._attr_assumed_state = False
            return

        if state_complete.type == "error":
            LOGGER.error(state_complete.type)
            return

        state_type: str = state_complete.type
        if not state_type or state_type != "status":
            return

        self._klyqa_device.status = state_complete  # should be out

        self._attr_color_temp = (
            color_temperature_kelvin_to_mired(float(state_complete.temperature))
            if state_complete.temperature
            else 0
        )
        if isinstance(state_complete.color, RgbColor):
            self._attr_rgb_color = (
                int(state_complete.color.r),
                int(state_complete.color.g),
                int(state_complete.color.b),
            )
            self._attr_hs_color = color_util.color_RGB_to_hs(*self._attr_rgb_color)

        self._attr_brightness = (
            int((float(state_complete.brightness) / 100) * 255)
            if state_complete.brightness is not None
            else None
        )

        self._attr_is_on = (
            isinstance(state_complete.status, list) and state_complete.status[0] == "on"
        ) or (isinstance(state_complete.status, str) and state_complete.status == "on")

        self._attr_color_mode = (
            ColorMode.COLOR_TEMP
            if state_complete.mode == "cct"
            else "effect"
            if state_complete.mode == "cmd"
            else state_complete.mode
        )
        self._attr_effect = ""
        if state_complete.mode == "cmd":
            scene_result = [
                x for x in BULB_SCENES if str(x["id"]) == state_complete.active_scene
            ]
            if len(scene_result) > 0:
                self._attr_effect = scene_result[0]["label"]
        self._attr_assumed_state = False

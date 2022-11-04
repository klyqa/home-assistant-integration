"""Support for klyqa lights."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
import json
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from collections.abc import ValuesView

from typing import Any, cast

from homeassistant.util import slugify

from homeassistant.core import HomeAssistant, Event

from homeassistant.const import Platform


from homeassistant.util.color import (
    color_temperature_kelvin_to_mired,
    color_temperature_mired_to_kelvin,
)
import traceback
from collections.abc import Callable
import asyncio

from homeassistant.helpers.area_registry import SAVE_DELAY

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
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo, Entity, generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.color as color_util
from homeassistant.config_entries import ConfigEntry


from klyqa_ctl import klyqa_ctl as api
from . import datacoordinator as coord, KlyqaData
from .datacoordinator import HAKlyqaAccount

from .const import (
    DOMAIN,
    LOGGER,
    EVENT_KLYQA_NEW_LIGHT,
    EVENT_KLYQA_NEW_LIGHT_GROUP,
)

from datetime import timedelta
import functools as ft

from homeassistant.helpers.area_registry import (
    AreaEntry,
    AreaRegistry,
    EVENT_AREA_REGISTRY_UPDATED,
    SAVE_DELAY,
)
import homeassistant.helpers.area_registry as area_registry

TIMEOUT_SEND = 11
# PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=205)

SUPPORT_KLYQA = LightEntityFeature.TRANSITION


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Async_setup_entry."""

    klyqa = hass.data[DOMAIN].entries[entry.entry_id]
    if klyqa:
        await async_setup_klyqa(
            hass, ConfigType(entry.data), async_add_entities, entry=entry, klyqa=klyqa
        )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Async_setup_platform."""
    klyqa = None


class KlyqaLightGroup(LightGroup):
    """Lightgroup."""

    def __init__(self, hass: HomeAssistant, settings: dict[Any, Any]) -> None:
        """Lightgroup."""
        self.hass = hass
        self.settings = settings

        u_id = api.format_uid(settings["id"])

        entity_id = ENTITY_ID_FORMAT.format(u_id)

        entity_ids: list[str] = []

        for device in settings["devices"]:
            uid = api.format_uid(device["localDeviceId"])

            entity_ids.append(ENTITY_ID_FORMAT.format(uid))

        super().__init__(entity_id, settings["name"], entity_ids, mode=None)


async def async_setup_klyqa(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    klyqa: HAKlyqaAccount,
    discovery_info: DiscoveryInfoType | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set up the Klyqa Light platform."""

    klyqa_data: KlyqaData = hass.data[DOMAIN]

    async def on_hass_stop(event: Event) -> None:
        """Stop push updates when hass stops."""
        # await klyqa.search_and_send_loop_task_stop()
        await hass.async_add_executor_job(klyqa.shutdown)

    listener = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)

    if entry:
        entry.async_on_unload(listener)

    entity_registry = er.async_get(hass)

    async def add_new_light_group(event: Event) -> None:

        device_settings = event.data

        try:
            entity = KlyqaLightGroup(hass, device_settings)
        except Exception as e:
            LOGGER.warn(f"Couldn't add light group {device_settings['name']}")
            return

        add_entities([entity], True)

    async def add_new_entity(event: Event) -> None:

        device_settings = event.data

        u_id = api.format_uid(device_settings["localDeviceId"])

        entity_id = ENTITY_ID_FORMAT.format(u_id)

        light_state = klyqa.devices[u_id] if u_id in klyqa.devices else api.KlyqaBulb()

        # Clear status added from cloud when the bulb is not connected to the cloud so offline
        if not light_state.cloud.connected:
            light_state.status = None

        entity = entity_registry.async_get(entity_id)

        registered_entity_id = entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, u_id
        )

        if registered_entity_id and registered_entity_id != entity_id:
            entity_registry.async_remove(str(registered_entity_id))

        registered_entity_id = entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, u_id
        )

        LOGGER.info(f"Add entity {entity_id} ({device_settings.get('name')}).")
        new_entity = KlyqaLight(
            device_settings,
            light_state,
            klyqa,
            entity_id,
            should_poll=klyqa.polling,
            config_entry=entry,
            hass=hass,
        )
        await new_entity.async_update_settings()
        new_entity._update_state(light_state.status)
        if new_entity:
            add_entities([new_entity], True)

    klyqa_data.remove_listeners.append(
        hass.bus.async_listen(EVENT_KLYQA_NEW_LIGHT, add_new_entity)
    )

    klyqa_data.remove_listeners.append(
        hass.bus.async_listen(EVENT_KLYQA_NEW_LIGHT_GROUP, add_new_light_group)
    )

    async def add_entity_to_area(event: Event) -> None:
        """Event for having a new area added and now if we have entities for it they can be added to it."""
        # {"action": "update", "area_id": area_id}

        if not "area_id" in event.data:
            return

        area_reg = area_registry.async_get(hass)
        tries = 0
        while tries < 2:
            tries = tries + 1
            area: AreaEntry | None = area_reg.async_get_area(event.data["area_id"])
            if not area and tries <= 1:
                await asyncio.sleep(SAVE_DELAY)
            elif area and area.name in klyqa_data.entities_area_update:

                entity_registry = er.async_get(hass)
                for entity_id in klyqa_data.entities_area_update[area.name].copy():

                    # platform: EntityPlatform = async_get_current_platform()
                    # platform.entities
                    # light_entities = cast(
                    #     ValuesView[LightEntity], platform.entities.values()
                    # )
                    # return [
                    #     scene_entity.entity_id
                    #     for scene_entity in scene_entities
                    #     if entity_id in scene_entity.scene_config.states
                    # ]
                    # entity_registry.async_get(entity_id)
                    # entity_id: str | None = entity_registry.async_get_entity_id(
                    #     Platform.LIGHT, DOMAIN, str(self.unique_id)
                    # )

                    # entity_registry_entry: RegistryEntry | None = None
                    # if entity_id:
                    #     entity_registry_entry = entity_registry.async_get(
                    #         str(entity_id)
                    #     )

                    # if entity_registry_entry:
                    #     entity_registry.async_update_entity(
                    #         entity_id=entity_registry_entry.entity_id, area_id=area.id
                    #     )
                    entity_registry.async_update_entity(
                        entity_id=entity_id, area_id=area.id
                    )

                    klyqa_data.entities_area_update[area.name].remove(entity_id)

    klyqa_data.remove_listeners.append(
        hass.bus.async_listen(EVENT_AREA_REGISTRY_UPDATED, add_entity_to_area)
    )

    await klyqa.update_account()
    return


class KlyqaLight(LightEntity):
    """Representation of the Klyqa light."""

    _attr_supported_features = SUPPORT_KLYQA
    _attr_transition_time = 500

    _klyqa_api: HAKlyqaAccount
    _klyqa_device: api.KlyqaBulb
    settings: dict[Any, Any] = {}
    config_entry: ConfigEntry | None = None
    entity_registry: EntityRegistry | None = None
    """entity added finished"""
    _added_klyqa: bool = False
    u_id: str
    send_event_cb: asyncio.Event | None = None
    hass: HomeAssistant

    def __init__(
        self,
        settings: Any,
        device: api.KlyqaBulb,
        klyqa_api: Any,
        entity_id: Any,
        hass: HomeAssistant,
        should_poll: Any = True,
        config_entry: Any = None,
    ) -> None:
        """Initialize a Klyqa Light Bulb."""
        self.hass = hass

        self._klyqa_api = klyqa_api
        self.u_id = api.format_uid(settings["localDeviceId"])
        self._attr_unique_id: str = api.format_uid(self.u_id)
        self._klyqa_device = device
        self.entity_id = entity_id

        self._attr_should_poll = should_poll
        self._attr_device_class = "light"
        self._attr_icon = "mdi:lightbulb"
        self._attr_supported_color_modes: set[ColorMode] = set()
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_effect_list = []
        self.config_entry = config_entry
        self.send_event_cb: asyncio.Event = asyncio.Event()

        self.device_config: api.Device_config = {}
        self.settings = {}
        self.rooms: list[Any] = []
        pass

    async def set_device_capabilities(self) -> None:
        """Look up profile."""
        if self.settings["productId"] in api.device_configs:
            self.device_config = api.device_configs[self.settings["productId"]]
        else:
            try:
                response_object = await self.hass.async_add_executor_job(
                    partial(
                        self._klyqa_api.request,
                        "/config/product/" + self.settings["productId"],
                        timeout=30,
                    )
                )
                self.device_config = json.loads(response_object.text)
            except:  # noqa: E722 pylint: disable=bare-except
                LOGGER.error("Could not load device configuration profile")
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

            if [x for x in device_traits if "msg_key" in x and x["msg_key"] == "color"]:
                self._attr_supported_color_modes.add(ColorMode.RGB)
                self._attr_supported_features |= LightEntityFeature.EFFECT  # type: ignore[assignment]
                self._attr_effect_list = [x["label"] for x in api.BULB_SCENES]
            else:
                self._attr_effect_list = [
                    x["label"] for x in api.BULB_SCENES if "cwww" in x
                ]

    async def async_update_settings(self) -> None:
        """Set device specific settings from the klyqa settings cloud."""
        devices_settings = self._klyqa_api.acc_settings["devices"]

        device_result = [
            x
            for x in devices_settings
            if api.format_uid(str(x["localDeviceId"])) == self.u_id
        ]
        if len(device_result) < 1:
            return

        self.settings = device_result[0]
        await self.set_device_capabilities()

        self._attr_name = self.settings["name"]
        self._attr_unique_id = api.format_uid(self.settings["localDeviceId"])
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

        if self.config_entry:

            device_registry.async_get_or_create(
                **{
                    "config_entry_id": self.config_entry.entry_id,
                    **self._attr_device_info,
                }
            )

        if entity_registry_entry:
            self._attr_device_info["suggested_area"] = entity_registry_entry.area_id

        self.rooms = []
        for room in self._klyqa_api.acc_settings["rooms"]:
            for device in room["devices"]:
                if device and api.format_uid(device["localDeviceId"]) == self.u_id:  # type: ignore[index]
                    self.rooms.append(room)

        if (
            entity_registry_entry
            and entity_registry_entry.area_id
            and len(self.rooms) == 0
        ):
            entity_registry.async_update_entity(
                entity_id=entity_registry_entry.entity_id, area_id=""
            )

        if len(self.rooms) > 0:
            room = self.rooms[0]["name"]
            area_reg = ar.async_get(self.hass)
            # only 1 room supported per device by ha
            area: AreaEntry | None = area_reg.async_get_area_by_name(room)
            if not area:
                area = area_reg.async_get_or_create(room)
                self.hass.data[DOMAIN].entities_area_update.setdefault(room, set()).add(
                    self.entity_id
                )
                # print(f"{self.hass.data[DOMAIN].entities_area_update}")
                # try directly save the new area.
                # pylint: disable=protected-access
                # await area_reg._store.async_save(area_reg._data_to_save())
                # if not area_reg.async_get_area_by_name(self.rooms[0]["name"]):
                #     await asyncio.sleep(SAVE_DELAY)
                #     area = area_reg.async_get_or_create(self.rooms[0]["name"])

            if area:
                self._attr_device_info["suggested_area"] = area.name
                LOGGER.info("Add bulb %s to room %s", self.name, area.name)

                if entity_registry_entry and entity_registry_entry.area_id != area.id:
                    entity_registry.async_update_entity(
                        entity_id=entity_registry_entry.entity_id, area_id=area.id
                    )
                    # try directly save the changed entity area.
                    # pylint: disable=protected-access
                    await entity_registry._store.async_save(
                        entity_registry._data_to_save()
                    )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn off."""
        args = []

        if ATTR_HS_COLOR in kwargs:
            rgb = color_util.color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
            self._attr_rgb_color = (rgb[0], rgb[1], rgb[2])
            self._attr_hs_color = kwargs[ATTR_HS_COLOR]

        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        if self._attr_rgb_color and ATTR_RGB_COLOR in kwargs or ATTR_HS_COLOR in kwargs:
            args.extend(
                ["--color", *([str(rgb) for rgb in self._attr_rgb_color])]  # type: ignore[union-attr]
            )

        if ATTR_RGBWW_COLOR in kwargs:
            self._attr_rgbww_color = kwargs[ATTR_RGBWW_COLOR]
            args.extend(
                [
                    "--percent_color",
                    *([str(rgb) for rgb in self._attr_rgbww_color]),  # type: ignore[union-attr]
                ]
            )

        if ATTR_EFFECT in kwargs:
            scene_result = [
                x for x in api.BULB_SCENES if x["label"] == kwargs[ATTR_EFFECT]
            ]
            if len(scene_result) > 0:
                scene = scene_result[0]
                self._attr_effect = kwargs[ATTR_EFFECT]
                commands = scene["commands"]
                if len(commands.split(";")) > 2:
                    commands += "l 0;"

                send_event_cb: asyncio.Event = asyncio.Event()

                async def callback(msg: api.Message, uid: str) -> None:
                    nonlocal args, self
                    # if (
                    #     msg.state == api.Message_state.sent
                    #     or msg.state == api.Message_state.answered
                    # ):
                    if msg.state in (
                        api.Message_state.sent,
                        api.Message_state.answered,
                    ):
                        send_event_cb.set()
                        args.extend(
                            [
                                "--routine_id",
                                "0",
                                "--routine_start",
                            ]
                        )

                await self.send_to_bulbs(
                    [
                        "--routine_id",
                        "0",
                        "--routine_scene",
                        str(scene["id"]),
                        "--routine_put",
                        "--routine_command",
                        commands,
                    ],
                    callback,
                )

                await send_event_cb.wait()

        if ATTR_COLOR_TEMP in kwargs:
            self._attr_color_temp = kwargs[ATTR_COLOR_TEMP]
            args.extend(
                [
                    "--temperature",
                    str(
                        color_temperature_mired_to_kelvin(self._attr_color_temp)
                        if self._attr_color_temp
                        else 0
                    ),
                ]
            )

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = int(kwargs[ATTR_BRIGHTNESS])

            args.extend(
                ["--brightness", str(round((self._attr_brightness / 255.0) * 100.0))]
            )

        if ATTR_BRIGHTNESS_PCT in kwargs:
            self._attr_brightness = int(
                round((kwargs[ATTR_BRIGHTNESS_PCT] / 100) * 255)
            )
            args.extend(["--brightness", str(ATTR_BRIGHTNESS_PCT)])

        # separate power on+transition and other lamp attributes

        if len(args) > 0:

            if ATTR_TRANSITION in kwargs:
                self._attr_transition_time = kwargs[ATTR_TRANSITION]

            if self._attr_transition_time:
                args.extend(["--transitionTime", str(self._attr_transition_time)])

            LOGGER.info(
                "Send to bulb %s%s: %s",
                str(self.entity_id),
                " (" + self.name + ")" if self.name else "",
                " ".join(args),
            )

            await self.send_to_bulbs(args)
            await asyncio.sleep(0.2)

        args = ["--power", "on"]

        if ATTR_TRANSITION in kwargs:
            self._attr_transition_time = kwargs[ATTR_TRANSITION]

        if self._attr_transition_time:
            args.extend(["--transitionTime", str(self._attr_transition_time)])

        LOGGER.info(
            "Send to bulb %s%s: %s",
            self.entity_id,
            f" ({self.name})" if self.name else "",
            " ".join(args),
        )

        await self.send_to_bulbs(args)

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""

        args = ["--power", "off"]

        if self._attr_transition_time:
            args.extend(["--transitionTime", str(self._attr_transition_time)])

        LOGGER.info(
            f"Send to bulb {self.entity_id}%s: %s",
            f" ({self.name})" if self.name else "",
            " ".join(args),
        )
        await self.send_to_bulbs(args)

    async def async_update_klyqa(self) -> None:
        """Fetch settings from klyqa cloud account."""

        await self._klyqa_api.request_account_settings_eco()
        if self._added_klyqa:
            await self._klyqa_api.process_account_settings()
        await self.async_update_settings()

    async def async_update(self) -> None:
        """Fetch new state data for this light. Called by HA."""

        name = f" ({self.name})" if self.name else ""
        # LOGGER.info("Update bulb %s%s", self.entity_id, name)

        try:
            await self.async_update_klyqa()

        except (Exception,) as exception:  # pylint: disable=bare-except,broad-except
            LOGGER.error(str(exception))
            LOGGER.error("%s", traceback.format_exc())
            LOGGER.exception(exception)

        # if self._added_klyqa:
        await self.send_to_bulbs(["--request"])

        self._update_state(self._klyqa_api.devices[self.u_id].status)

    async def send_to_bulbs(
        self,
        args: list[Any],
        callback: Callable[[Any, str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Send_to_bulbs."""

        send_event_cb: asyncio.Event = asyncio.Event()

        async def send_answer_cb(msg: api.Message, uid: str) -> None:
            nonlocal callback, send_event_cb
            if callback is not None:
                await callback(msg, uid)
            try:
                LOGGER.debug("Send_answer_cb %s", str(uid))
                # ttl ended
                if uid != self.u_id:
                    return
                self._update_state(self._klyqa_api.devices[self.u_id].status)
                if self._added_klyqa:
                    self.schedule_update_ha_state()  # force_refresh=True)
                # self.async_schedule_update_ha_state(force_refresh=True)
            except:  # noqa: E722 pylint: disable=bare-except
                LOGGER.error(traceback.format_exc())
            finally:
                send_event_cb.set()

        parser = api.get_description_parser()
        args.extend(["--local", "--device_unitids", f"{self.u_id}"])
        # , "--debug"
        api.add_config_args(parser=parser)
        api.add_command_args(parser=parser)

        args_parsed = parser.parse_args(args=args)

        # LOGGER.info("Send start!")
        new_task = asyncio.create_task(
            self._klyqa_api._send_to_devices(
                args_parsed,
                args,
                async_answer_callback=send_answer_cb,
                timeout_ms=TIMEOUT_SEND * 1000,
            )
        )
        # LOGGER.info("Send started!")
        await send_event_cb.wait()

        # LOGGER.info("Send started wait ended!")
        try:
            await asyncio.wait([new_task], timeout=0.001)
        except asyncio.TimeoutError:
            LOGGER.error("Timeout send")
        pass

    async def async_added_to_hass(self) -> None:
        """Added to hass."""
        await super().async_added_to_hass()
        self._added_klyqa = True
        try:
            await self.async_update_settings()
        except Exception:  # pylint: disable=bare-except,broad-except
            LOGGER.error(traceback.format_exc())

    def _update_state(self, state_complete: api.KlyqaBulbResponseStatus) -> None:
        """Process state request response from the bulb to the entity state."""
        self._attr_assumed_state = True

        if not state_complete or not isinstance(
            state_complete, api.KlyqaBulbResponseStatus
        ):
            self._attr_is_on = False
            self._attr_assumed_state = False
            return

        if state_complete.type == "error":
            LOGGER.error(state_complete.type)
            return

        state_type = state_complete.type
        if not state_type or state_type != "status":
            return

        self._klyqa_device.status = state_complete

        self._attr_color_temp = (
            color_temperature_kelvin_to_mired(float(state_complete.temperature))
            if state_complete.temperature
            else 0
        )
        if isinstance(state_complete.color, api.RGBColor):
            self._attr_rgb_color = (
                int(state_complete.color.r),
                int(state_complete.color.g),
                int(state_complete.color.b),
            )
            self._attr_hs_color = color_util.color_RGB_to_hs(*self._attr_rgb_color)

        self._attr_brightness = int((float(state_complete.brightness) / 100) * 255)
        self._attr_is_on = state_complete.status == "on"

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
                x
                for x in api.BULB_SCENES
                if str(x["id"]) == state_complete.active_scene
            ]
            if len(scene_result) > 0:
                self._attr_effect = scene_result[0]["label"]
        self._attr_assumed_state = False

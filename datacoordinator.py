"""Klyqa datacoordinator."""
from __future__ import annotations
from homeassistant.core import HomeAssistant

from homeassistant.helpers import (
    entity_registry as ent_reg,
)

from homeassistant.const import Platform
from klyqa_ctl import klyqa_ctl as api
from .const import (
    DOMAIN,
    EVENT_KLYQA_NEW_LIGHT,
    EVENT_KLYQA_NEW_LIGHT_GROUP,
    EVENT_KLYQA_NEW_VC,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)

from homeassistant.components.light import ENTITY_ID_FORMAT as LIGHT_ENTITY_ID_FORMAT
from homeassistant.components.vacuum import ENTITY_ID_FORMAT as VACUUM_ENTITY_ID_FORMAT
from homeassistant.util import slugify


class HAKlyqaAccount(api.Klyqa_account):  # type: ignore[misc]
    """HAKlyqaAccount."""

    hass: HomeAssistant | None

    polling: bool

    def __init__(
        self,
        data_communicator: api.Data_communicator,
        username: str = "",
        password: str = "",
        hass: HomeAssistant | None = None,
        polling: bool = True,
    ):
        """HAKlyqaAccount."""
        super().__init__(data_communicator, username, password)
        self.hass = hass
        self.polling = polling

    async def login(self, print_onboarded_devices=False) -> bool:
        """Login."""
        ret = await super().login(print_onboarded_devices=False)
        if ret:
            await api.async_json_cache(
                {CONF_USERNAME: self.username, CONF_PASSWORD: self.password},
                "last.klyqa_integration_data.cache.json",
            )
        return ret

    async def update_account(self) -> bool:
        """Update_account."""

        await self.request_account_settings()
        await self.process_account_settings()

    async def process_account_settings(self) -> None:
        """Process_account_settings."""

        klyqa_new_light_registered = [
            key
            for key, _ in self.hass.bus.async_listeners().items()
            if key == EVENT_KLYQA_NEW_LIGHT or key == EVENT_KLYQA_NEW_LIGHT_GROUP
        ]
        if len(klyqa_new_light_registered) == 2:
            entity_registry = ent_reg.async_get(self.hass)

            for device in self.acc_settings["devices"]:
                # look if any onboarded device is not in the entity registry already
                u_id = api.format_uid(device["localDeviceId"])

                platform: str = ""
                entity_id: str = ""
                event: str = ""
                if device["productId"].startswith("@klyqa.lighting"):
                    platform = Platform.LIGHT
                    entity_id = LIGHT_ENTITY_ID_FORMAT.format(u_id)
                    event = EVENT_KLYQA_NEW_LIGHT
                elif device["productId"].startswith("@klyqa.cleaning"):
                    platform = Platform.VACUUM
                    entity_id = VACUUM_ENTITY_ID_FORMAT.format(u_id)
                    event = EVENT_KLYQA_NEW_VC
                else:
                    continue
                registered_entity_id = entity_registry.async_get_entity_id(
                    platform, DOMAIN, u_id
                )

                if not registered_entity_id or not self.hass.states.get(entity_id):
                    self.hass.bus.fire(event, device)
                    # if device["productId"].startswith("@klyqa.lighting"):
                    #     """found klyqa device not in the light entities"""
                    #     self.hass.bus.fire(EVENT_KLYQA_NEW_LIGHT, device)

                    # elif device["productId"].startswith("@klyqa.cleaning"):
                    #     """found klyqa device not in the light entities"""
                    #     self.hass.bus.fire(EVENT_KLYQA_NEW_VC, device)

            for group in self.acc_settings["deviceGroups"]:
                u_id = api.format_uid(group["id"])

                registered_entity_id = entity_registry.async_get_entity_id(
                    Platform.LIGHT, DOMAIN, u_id
                )

                if not registered_entity_id or not self.hass.states.get(
                    LIGHT_ENTITY_ID_FORMAT.format(slugify(group["name"]))
                ):
                    """found klyqa device not in the light entities"""
                    if (
                        len(group["devices"]) > 0
                        and "productId" in group["devices"][0]
                        and group["devices"][0]["productId"].startswith(
                            "@klyqa.lighting"
                        )
                    ):
                        self.hass.bus.fire(EVENT_KLYQA_NEW_LIGHT_GROUP, group)
        return True

"""Config flow for Klyqa."""
# import my_pypi_dependency

from typing import Any, cast
from numpy import integer

from requests.exceptions import ConnectTimeout, HTTPError
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_flow

from . import api

# from .api import Klyqa
from .datacoordinator import HAKlyqaAccount, KlyqaDataCoordinator

from .const import CONF_POLLING, DOMAIN, LOGGER, CONF_SYNC_ROOMS # DEFAULT_CACHEDB
import homeassistant.helpers.config_validation as cv

from homeassistant import config_entries
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    CONF_ROOM,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult

# user_step_data_schema = {
#     vol.Required(CONF_USERNAME, default=""): cv.string,
#     vol.Required(CONF_PASSWORD, default=""): cv.string,
#     vol.Required(CONF_SCAN_INTERVAL, default="60"): cv.string,
#     vol.Required(CONF_SYNC_ROOMS, default=True): cv.boolean,
#     vol.Required(CONF_HOST, default="http://localhost:3000"): cv.url,
# }


user_step_data_schema = {
    vol.Required(CONF_USERNAME, default=""): cv.string,
    vol.Required(CONF_PASSWORD, default=""): cv.string,
    vol.Required(CONF_SCAN_INTERVAL, default=60): int,
    vol.Required(CONF_SYNC_ROOMS, default=True, msg="sync r", description="sync R"): bool,
    vol.Required(CONF_HOST, default="https://app-api.prod.qconnex.io"): str,
}


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                user_step_data_schema
                # {
                #     vol.Required(
                #         "user",
                #         default=self.config_entry.options.get("show_things"),
                #     ): bool
                # }
            ),
        )


class KlyqaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Example config flow."""

    # The schema version of the entries that it creates
    # Home Assistant will call your migrate method if the version changes
    # (this is not implemented yet)
    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""

        self.username: str | None = None
        self.password: str | None = None
        self.cache: str | None = None
        self.scan_interval: int = 30
        self.host: str | None = None
        self.klyqa: HAKlyqaAccount = None
        pass

    def get_klyqa(self) -> HAKlyqaAccount:
        if self.klyqa and self.klyqa.KlyqaAccounts:
            return self.klyqa
        if not self.hass or not DOMAIN in self.hass.data or not self.hass.data.KlyqaAccounts:
            return None
        self.klyqa = self.hass.data[DOMAIN]
        return self.hass.data[DOMAIN]

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        """ already logged in from platform or other way """
        if self.get_klyqa():
            return self.async_abort(reason="single_instance_allowed")

            #  and self.klyqa.access_token:
            # self.username = self.klyqa.username
            # self.password = self.klyqa.password
            # self.host = self.klyqa.host
            # return await self._async_create_entry()
        login_failed = False

        if user_input is None or login_failed:
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema(user_step_data_schema)
            )

        self.username = str(user_input[CONF_USERNAME])
        self.password = str(user_input[CONF_PASSWORD])
        self.scan_interval = int(user_input[CONF_SCAN_INTERVAL])
        self.sync_rooms = user_input[CONF_SYNC_ROOMS]
        self.host = str(user_input[CONF_HOST])

        return await self._async_klyqa_login(step_id="user")

    async def _async_klyqa_login(self, step_id: str) -> FlowResult:
        """Handle login with Klyqa."""
        # self._cache = self.hass.config.path(DEFAULT_CACHEDB)
        errors = {}
        if DOMAIN in self.hass.data:
            self.klyqa = self.hass.data[DOMAIN]
            try:
                await self.hass.async_add_executor_job(self.klyqa.shutdown)
            except Exception as e:
                pass

        try:

            self.klyqa: HAKlyqaAccount = HAKlyqaAccount(
                None,
                None,
                self.username,
                self.password,
                self.host,
                self.hass,
                sync_rooms=self.sync_rooms,
            )
            if not await self.hass.async_run_job(
                self.klyqa.login,
            ):
                raise Exception("Unable to login")

            if self.klyqa:
                self.hass.data[DOMAIN] = self.klyqa

        except (ConnectTimeout, HTTPError):
            LOGGER.error("Unable to connect to Klyqa: %s", ex)
            errors = {"base": "cannot_connect"}

        except Exception as ex:

            LOGGER.error("Unable to connect to Klyqa: %s", ex)
            errors = {"base": "cannot_connect"}

        if not self.klyqa or not self.klyqa.access_token:
            errors = {"base": "cannot_connect"}

        if errors:
            return self.async_show_form(
                step_id=step_id,
                data_schema=vol.Schema(user_step_data_schema),
                errors=errors,
            )

        return await self._async_create_entry()

    async def _async_create_entry(self) -> FlowResult:
        """Create the config entry."""
        config_data = {
            CONF_USERNAME: self.username,
            CONF_PASSWORD: self.password,
            CONF_SCAN_INTERVAL: self.scan_interval,
            CONF_SYNC_ROOMS: self.sync_rooms,
            CONF_HOST: self.host,
        }
        existing_entry = await self.async_set_unique_id(self.username)

        if existing_entry:
            self.hass.config_entries.async_update_entry(
                existing_entry, data=config_data
            )
            # Reload the Klyqa config entry otherwise devices will remain unavailable
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(
            title=cast(str, self.username), data=config_data
        )
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_component import (
    EntityComponent,
    DEFAULT_SCAN_INTERVAL,
)

import asyncio
import socket

from .api import bulb_cli as api
from .const import DOMAIN, LOGGER, CONF_SYNC_ROOMS, EVENT_KLYQA_NEW_LIGHT, EVENT_KLYQA_NEW_LIGHT_GROUP
from datetime import timedelta
import logging


class HAKlyqaAccount(api.Klyqa_account):
    """HAKlyqaAccount"""

    hass: HomeAssistant

    udp: socket.socket
    tcp: socket.socket
    polling: bool
    sync_rooms: bool
    scan_interval_conf: float

    def __init__(self, udp, tcp, username="", password="", host="", hass=None, polling = True, sync_rooms = True, scan_interval = -1.0):
        super().__init__(username, password, host)
        self.hass = hass
        self.udp = udp
        self.tcp = tcp
        self.polling = polling
        self.sync_rooms = sync_rooms
        self.scan_interval_conf = scan_interval


    async def send_to_bulbs(self, args, args_in, async_answer_callback = None, timeout_ms=5000):
        """_send_to_bulbs"""
        ret = await super()._send_to_bulbs(
            args, args_in, self.udp, self.tcp, async_answer_callback = async_answer_callback, timeout_ms=timeout_ms,
        )
        # self.search_and_send_loop_task_stop()
        return ret

    async def update_account(self):
        """update_account"""

        await self.request_account_settings()
        if EVENT_KLYQA_NEW_LIGHT in self.hass.bus._listeners:
            # search and update light states.
            # asyncio.run(
            #     self.search_lights(broadcast_repetitions=2)
            # )  # , seconds_to_discover=2))
            ha_entities = self.hass.data["light"].entities

            for d in self.acc_settings["devices"]:
                # look if any onboarded device is not in the entity registry.
                u_id = api.format_uid(d["localDeviceId"])

                light = [
                    e for e in ha_entities if hasattr(e, "u_id") and e.u_id == u_id
                ]

                if len(light) == 0:
                    """found klyqa device not in the light entities"""
                    self.hass.bus.fire(EVENT_KLYQA_NEW_LIGHT, d)

            for d in self.acc_settings["deviceGroups"]:
                u_id = api.format_uid(d["id"])

                light = [
                    e for e in ha_entities if hasattr(e, "u_id") and e.u_id == u_id
                ]

                if len(light) == 0:
                    """found klyqa device not in the light entities"""
                    self.hass.bus.fire(EVENT_KLYQA_NEW_LIGHT_GROUP, d)
        return True

    # async def search_lights(self, broadcast_repetitions=2):


class KlyqaDataCoordinator(EntityComponent):
    """KlyqaDataCoordinator"""

    _instance = None
    KlyqaAccounts: dict[str, HAKlyqaAccount]
    udp: socket.socket
    tcp: socket.socket

    def __init__(self):
        raise RuntimeError("Call instance() instead")

    def get_ports(self):
        """__get_ports"""
        try:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_address = ("0.0.0.0", 2222)
            self.udp.bind(server_address)
            LOGGER.debug("Bound UDP port 2222")

        except:
            LOGGER.error(
                "Error on opening and binding the udp port 2222 on host for initiating the lamp communication."
            )
            return 1

        try:
            self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_address = ("0.0.0.0", 3333)
            self.tcp.bind(server_address)
            LOGGER.debug("Bound TCP port 3333")
            self.tcp.listen(1)

        except:
            LOGGER.error(
                "Error on opening and binding the tcp port 3333 on host for initiating the lamp communication."
            )
            return 1

    def init(
        self,
        logger: logging.Logger,
        domain: str,
        hass: HomeAssistant,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ):
        """__init"""
        print("Init new instance")
        super().__init__(logger, domain, hass, scan_interval)
        self.KlyqaAccounts = {}
        self.get_ports()

    @classmethod
    def instance(
        cls,
        logger: logging.Logger,
        domain: str,
        hass: HomeAssistant,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ):
        """instance"""
        if cls._instance is None:
            print("Creating new instance")
            cls._instance = cls.__new__(cls)
            # Put any initialization here.
            cls._instance.init(logger, domain, hass, scan_interval)
        return cls._instance

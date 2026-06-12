"""Component to embed Aqualink devices."""

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
import logging
from typing import Any, Concatenate

import httpx
from iaqualink.client import AqualinkClient
from iaqualink.device import (
    AqualinkBinarySensor,
    AqualinkClimate,
    AqualinkFan,
    AqualinkLight,
    AqualinkNumber,
    AqualinkSelect,
    AqualinkSensor,
    AqualinkSwitch,
    AqualinkVacuum,
)
from iaqualink.exception import (
    AqualinkServiceException,
    AqualinkServiceUnauthorizedException,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util.ssl import SSL_ALPN_HTTP11_HTTP2

from .const import DOMAIN
from .coordinator import AqualinkDataUpdateCoordinator
from .entity import AqualinkEntity

_LOGGER = logging.getLogger(__name__)

ATTR_CONFIG = "config"
PARALLEL_UPDATES = 0

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VACUUM,
]

type AqualinkConfigEntry = ConfigEntry[AqualinkRuntimeData]


@dataclass
class AqualinkRuntimeData:
    """Runtime data for Aqualink."""

    client: AqualinkClient
    coordinators: dict[str, AqualinkDataUpdateCoordinator]
    # These will contain the initialized devices
    binary_sensors: list[AqualinkBinarySensor]
    climates: list[AqualinkClimate]
    fans: list[AqualinkFan]
    lights: list[AqualinkLight]
    numbers: list[AqualinkNumber]
    selects: list[AqualinkSelect]
    sensors: list[AqualinkSensor]
    switches: list[AqualinkSwitch]
    vacuums: list[AqualinkVacuum]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version == 1 and entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry,
            minor_version=2,
        )

    _LOGGER.info(
        "Migration to configuration version %s.%s successful",
        entry.version,
        entry.minor_version,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: AqualinkConfigEntry) -> bool:
    """Set up Aqualink from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    aqualink = AqualinkClient(
        username,
        password,
        httpx_client=get_async_client(hass, alpn_protocols=SSL_ALPN_HTTP11_HTTP2),
    )
    try:
        await aqualink.login()
    except AqualinkServiceUnauthorizedException as auth_exception:
        await aqualink.close()
        raise ConfigEntryAuthFailed(
            "Invalid credentials for iAquaLink"
        ) from auth_exception
    except (AqualinkServiceException, TimeoutError, httpx.HTTPError) as aio_exception:
        await aqualink.close()
        raise ConfigEntryNotReady(
            f"Error while attempting login: {aio_exception}"
        ) from aio_exception

    account_id = aqualink.user_id
    if entry.unique_id != account_id:
        conflicting_entry = next(
            (
                existing_entry
                for existing_entry in hass.config_entries.async_entries(DOMAIN)
                if existing_entry.entry_id != entry.entry_id
                and existing_entry.unique_id == account_id
            ),
            None,
        )
        if conflicting_entry is not None:
            await aqualink.close()
            raise ConfigEntryError(
                "Another iAquaLink config entry already uses this account"
            )
        hass.config_entries.async_update_entry(entry, unique_id=account_id)

    try:
        systems = await aqualink.get_systems()
    except AqualinkServiceUnauthorizedException as auth_exception:
        await aqualink.close()
        raise ConfigEntryAuthFailed(
            "Invalid credentials for iAquaLink"
        ) from auth_exception
    except AqualinkServiceException as svc_exception:
        await aqualink.close()
        raise ConfigEntryNotReady(
            f"Error while attempting to retrieve systems list: {svc_exception}"
        ) from svc_exception

    systems_list = list(systems.values())
    if not systems_list:
        await aqualink.close()
        raise ConfigEntryError("No systems detected or supported")

    runtime_data = AqualinkRuntimeData(
        aqualink,
        coordinators={},
        binary_sensors=[],
        climates=[],
        fans=[],
        lights=[],
        numbers=[],
        selects=[],
        sensors=[],
        switches=[],
        vacuums=[],
    )
    for system in systems_list:
        if not system.supported:
            _LOGGER.warning(
                "Unsupported system type %s (serial %s), skipping",
                system.serial,
                system.serial,
            )
            continue

        coordinator = AqualinkDataUpdateCoordinator(hass, entry, system)
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            await aqualink.close()
            raise
        except ConfigEntryNotReady:
            _LOGGER.warning(
                "System %s is not available; skipping device enumeration",
                system.serial,
            )
            continue

        try:
            devices = await system.get_devices()
        except AqualinkServiceUnauthorizedException as auth_exception:
            await aqualink.close()
            raise ConfigEntryAuthFailed(
                "Invalid credentials for iAquaLink"
            ) from auth_exception
        except AqualinkServiceException as svc_exception:
            _LOGGER.warning(
                "Unable to retrieve devices for system %s: %s",
                system.serial,
                svc_exception,
            )
            continue

        runtime_data.coordinators[system.serial] = coordinator

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            name=system.name,
            identifiers={(DOMAIN, system.serial)},
            manufacturer="Jandy",
            serial_number=system.serial,
        )

        for dev in devices.values():
            if isinstance(dev, AqualinkVacuum):
                runtime_data.vacuums += [dev]
            elif isinstance(dev, AqualinkClimate):
                runtime_data.climates += [dev]
            elif isinstance(dev, AqualinkFan):
                runtime_data.fans += [dev]
            elif isinstance(dev, AqualinkLight):
                runtime_data.lights += [dev]
            elif isinstance(dev, AqualinkNumber):
                runtime_data.numbers += [dev]
            elif isinstance(dev, AqualinkSelect):
                runtime_data.selects += [dev]
            elif isinstance(dev, AqualinkSwitch):
                runtime_data.switches += [dev]
            elif isinstance(dev, AqualinkBinarySensor):
                runtime_data.binary_sensors += [dev]
            elif isinstance(dev, AqualinkSensor):
                runtime_data.sensors += [dev]

    _LOGGER.debug(
        "Got %s binary sensors: %s",
        len(runtime_data.binary_sensors),
        runtime_data.binary_sensors,
    )
    _LOGGER.debug(
        "Got %s climates: %s", len(runtime_data.climates), runtime_data.climates
    )
    _LOGGER.debug("Got %s fans: %s", len(runtime_data.fans), runtime_data.fans)
    _LOGGER.debug("Got %s lights: %s", len(runtime_data.lights), runtime_data.lights)
    _LOGGER.debug("Got %s numbers: %s", len(runtime_data.numbers), runtime_data.numbers)
    _LOGGER.debug("Got %s selects: %s", len(runtime_data.selects), runtime_data.selects)
    _LOGGER.debug("Got %s sensors: %s", len(runtime_data.sensors), runtime_data.sensors)
    _LOGGER.debug(
        "Got %s switches: %s", len(runtime_data.switches), runtime_data.switches
    )
    _LOGGER.debug("Got %s vacuums: %s", len(runtime_data.vacuums), runtime_data.vacuums)

    entry.runtime_data = runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AqualinkConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.client.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def refresh_system[_AqualinkEntityT: AqualinkEntity, **_P](
    func: Callable[Concatenate[_AqualinkEntityT, _P], Awaitable[Any]],
) -> Callable[Concatenate[_AqualinkEntityT, _P], Coroutine[Any, Any, None]]:
    """Force update all entities after state change."""

    @wraps(func)
    async def wrapper(
        self: _AqualinkEntityT, *args: _P.args, **kwargs: _P.kwargs
    ) -> None:
        """Call decorated function and send update signal to all entities."""
        await func(self, *args, **kwargs)
        self.coordinator.async_update_listeners()

    return wrapper

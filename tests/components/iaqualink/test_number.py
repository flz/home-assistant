"""Number platform tests for iAquaLink."""

from typing import override
from unittest.mock import AsyncMock

from iaqualink.client import AqualinkClient
from iaqualink.device import AqualinkNumber
from iaqualink.exception import AqualinkServiceException
from iaqualink.system import SystemStatus
from iaqualink.systems.iaqua.system import IaquaSystem
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import get_aqualink_device, get_aqualink_system, setup_entry

ENTITY_ID = "number.pool_speed"


class SpeedNumber(AqualinkNumber):
    """Writable numeric setting."""

    @property
    @override
    def name(self) -> str:
        return "speed"

    @property
    @override
    def label(self) -> str:
        return "Speed"

    @property
    @override
    def manufacturer(self) -> str:
        return "Jandy"

    @property
    @override
    def model(self) -> str:
        return "Number"

    @property
    @override
    def current_value(self) -> float | None:
        return self.data["value"]

    @property
    @override
    def min_value(self) -> float:
        return 10

    @property
    @override
    def max_value(self) -> float:
        return 50

    @property
    @override
    def unit_of_measurement(self) -> str | None:
        return "%"

    @override
    async def _set_value(self, value: float) -> None:
        self.data["value"] = value


async def _setup_number(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> SpeedNumber:
    """Set up the integration with a single number entity."""
    system = get_aqualink_system(client, cls=IaquaSystem)
    system._status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    number = get_aqualink_device(
        system, name="speed", cls=SpeedNumber, data={"value": 20}
    )
    system.get_devices = AsyncMock(return_value={number.name: number})

    await setup_entry(hass, config_entry, system)
    return number


async def test_number_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test the number entity exposes the device values."""
    await _setup_number(hass, config_entry, client)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "20"
    assert state.attributes["min"] == 10
    assert state.attributes["max"] == 50
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "%"


async def test_number_set_value(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test setting a value updates the state."""
    await _setup_number(hass, config_entry, client)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 35},
        blocking=True,
    )

    assert hass.states.get(ENTITY_ID).state == "35.0"


async def test_number_set_value_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test a library error is surfaced as a Home Assistant error."""
    number = await _setup_number(hass, config_entry, client)
    number.set_value = AsyncMock(side_effect=AqualinkServiceException("boom"))

    with pytest.raises(HomeAssistantError, match="boom"):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_VALUE: 35},
            blocking=True,
        )

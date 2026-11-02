"""Fan platform tests for iAquaLink."""

from typing import override
from unittest.mock import AsyncMock

from iaqualink.client import AqualinkClient
from iaqualink.device import AqualinkFan
from iaqualink.exception import AqualinkServiceException
from iaqualink.system import SystemStatus
from iaqualink.systems.iaqua.system import IaquaSystem
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    DOMAIN as FAN_DOMAIN,
    SERVICE_SET_PERCENTAGE,
    SERVICE_SET_PRESET_MODE,
    FanEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import get_aqualink_device, get_aqualink_system, setup_entry

ENTITY_ID = "fan.pool_pump"


class FullFan(AqualinkFan):
    """Fan supporting power, speed and presets."""

    @property
    @override
    def name(self) -> str:
        return "pump"

    @property
    @override
    def label(self) -> str:
        return "Pump"

    @property
    @override
    def manufacturer(self) -> str:
        return "Jandy"

    @property
    @override
    def model(self) -> str:
        return "Pump"

    @property
    @override
    def supports_turn_on(self) -> bool:
        return True

    @property
    @override
    def supports_turn_off(self) -> bool:
        return True

    @property
    @override
    def is_on(self) -> bool:
        return self.data["on"]

    @override
    async def turn_on(self) -> None:
        self.data["on"] = True

    @override
    async def turn_off(self) -> None:
        self.data["on"] = False

    @property
    @override
    def supports_presets(self) -> bool:
        return True

    @property
    @override
    def preset_modes(self) -> list[str]:
        return ["eco", "boost"]

    @property
    @override
    def preset_mode(self) -> str | None:
        return self.data["preset"]

    @override
    async def _set_preset_mode(self, preset_mode: str) -> None:
        self.data["preset"] = preset_mode

    @property
    @override
    def supports_percentage(self) -> bool:
        return True

    @property
    @override
    def percentage(self) -> int | None:
        return self.data["percentage"]

    @override
    async def _set_percentage(self, percentage: int) -> None:
        self.data["percentage"] = percentage


class OnOffFan(FullFan):
    """Fan supporting only power."""

    @property
    @override
    def supports_presets(self) -> bool:
        return False

    @property
    @override
    def supports_percentage(self) -> bool:
        return False

    @property
    @override
    def supports_turn_off(self) -> bool:
        return False

    @property
    @override
    def supports_turn_on(self) -> bool:
        return False


async def _setup_fan(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    cls: type[FullFan],
    data: dict,
) -> FullFan:
    """Set up the integration with a single fan entity."""
    system = get_aqualink_system(client, cls=IaquaSystem)
    system._status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    fan = get_aqualink_device(system, name="pump", cls=cls, data=data)
    system.get_devices = AsyncMock(return_value={fan.name: fan})

    await setup_entry(hass, config_entry, system)
    return fan


async def test_fan_state_and_features(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test a fully featured fan exposes its state and features."""
    await _setup_fan(
        hass,
        config_entry,
        client,
        FullFan,
        {"on": True, "preset": "eco", "percentage": 40},
    )

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 40
    assert state.attributes[ATTR_PRESET_MODE] == "eco"
    assert state.attributes["preset_modes"] == ["eco", "boost"]
    assert state.attributes["supported_features"] == (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )


async def test_fan_without_optional_features(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test a fan without speed or presets exposes neither."""
    await _setup_fan(hass, config_entry, client, OnOffFan, {"on": False})

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_OFF
    assert ATTR_PERCENTAGE not in state.attributes
    assert ATTR_PRESET_MODE not in state.attributes
    assert state.attributes["supported_features"] == 0


@pytest.mark.parametrize(
    ("service", "service_data", "expected_state", "expected_data"),
    [
        pytest.param(SERVICE_TURN_ON, {}, STATE_ON, {"on": True}, id="turn_on"),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_PERCENTAGE: 60},
            STATE_ON,
            {"percentage": 60},
            id="turn_on_percentage",
        ),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_PRESET_MODE: "boost"},
            STATE_ON,
            {"preset": "boost"},
            id="turn_on_preset",
        ),
        pytest.param(SERVICE_TURN_OFF, {}, STATE_OFF, {"on": False}, id="turn_off"),
        pytest.param(
            SERVICE_SET_PERCENTAGE,
            {ATTR_PERCENTAGE: 80},
            STATE_ON,
            {"percentage": 80},
            id="set_percentage",
        ),
        pytest.param(
            SERVICE_SET_PERCENTAGE,
            {ATTR_PERCENTAGE: 0},
            STATE_OFF,
            {"on": False},
            id="set_percentage_zero",
        ),
        pytest.param(
            SERVICE_SET_PRESET_MODE,
            {ATTR_PRESET_MODE: "boost"},
            STATE_ON,
            {"preset": "boost"},
            id="set_preset_mode",
        ),
    ],
)
async def test_fan_services(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    service: str,
    service_data: dict,
    expected_state: str,
    expected_data: dict,
) -> None:
    """Test fan services update the device and state."""
    fan = await _setup_fan(
        hass,
        config_entry,
        client,
        FullFan,
        {"on": True, "preset": "eco", "percentage": 40},
    )

    await hass.services.async_call(
        FAN_DOMAIN,
        service,
        {ATTR_ENTITY_ID: ENTITY_ID, **service_data},
        blocking=True,
    )

    assert hass.states.get(ENTITY_ID).state == expected_state
    assert expected_data.items() <= fan.data.items()


async def test_fan_service_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test a library error is surfaced as a Home Assistant error."""
    fan = await _setup_fan(
        hass,
        config_entry,
        client,
        FullFan,
        {"on": True, "preset": "eco", "percentage": 40},
    )
    fan.turn_off = AsyncMock(side_effect=AqualinkServiceException("boom"))

    with pytest.raises(HomeAssistantError, match="boom"):
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: ENTITY_ID},
            blocking=True,
        )

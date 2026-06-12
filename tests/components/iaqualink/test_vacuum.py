"""Vacuum platform tests for iAquaLink."""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock, patch

import httpx
from iaqualink.client import AqualinkClient
from iaqualink.device import AqualinkVacuum
from iaqualink.enums import AqualinkRobotActivity
from iaqualink.exception import (
    AqualinkServiceException,
    AqualinkServiceUnauthorizedException,
)
from iaqualink.systems.iaqua.system import IaquaSystem
import pytest

from homeassistant.components.vacuum import (
    ATTR_FAN_SPEED,
    DOMAIN as VACUUM_DOMAIN,
    SERVICE_CLEAN_SPOT,
    SERVICE_LOCATE,
    SERVICE_PAUSE,
    SERVICE_RETURN_TO_BASE,
    SERVICE_SET_FAN_SPEED,
    SERVICE_START,
    SERVICE_STOP,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from .conftest import get_aqualink_system, setup_entry

from tests.common import MockConfigEntry

ENTITY_ID = "vacuum.robot"


class _ConcreteVacuum(AqualinkVacuum):
    """Minimal concrete AqualinkVacuum for testing."""

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def label(self) -> str:
        return self.data.get("label", self.name.replace("_", " ").title())

    @property
    def manufacturer(self) -> str:
        return "Zodiac"

    @property
    def model(self) -> str:
        return "Robot Cleaner"

    @property
    def activity(self) -> AqualinkRobotActivity:
        return AqualinkRobotActivity(self.data.get("activity", "docked"))


async def _setup_vacuum(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    *,
    activity: str = "docked",
    supports_start: bool = True,
    supports_stop: bool = True,
    supports_pause: bool = False,
    supports_return: bool = True,
    supports_clean_spot: bool = False,
    supports_locate: bool = False,
    fan_speed_list: list[str] | None = None,
    fan_speed: str | None = None,
) -> tuple[IaquaSystem, _ConcreteVacuum, str]:
    """Set up the integration with a single vacuum entity."""
    system = get_aqualink_system(client, cls=IaquaSystem)
    system.online = True
    system.update = AsyncMock()
    system.refresh = AsyncMock()

    vacuum = _ConcreteVacuum(
        system=system,
        data={"name": "robot", "activity": activity, "label": "Robot"},
    )

    with (
        patch.object(
            type(vacuum), "supports_start", new_callable=PropertyMock
        ) as mock_start,
        patch.object(
            type(vacuum), "supports_stop", new_callable=PropertyMock
        ) as mock_stop,
        patch.object(
            type(vacuum), "supports_pause", new_callable=PropertyMock
        ) as mock_pause,
        patch.object(
            type(vacuum), "supports_return", new_callable=PropertyMock
        ) as mock_return,
        patch.object(
            type(vacuum), "supports_clean_spot", new_callable=PropertyMock
        ) as mock_clean_spot,
        patch.object(
            type(vacuum), "supports_locate", new_callable=PropertyMock
        ) as mock_locate,
        patch.object(
            type(vacuum), "supports_fan_speed", new_callable=PropertyMock
        ) as mock_supports_fan_speed,
        patch.object(
            type(vacuum), "fan_speed_list", new_callable=PropertyMock
        ) as mock_fan_speed_list,
        patch.object(
            type(vacuum), "fan_speed", new_callable=PropertyMock
        ) as mock_fan_speed,
    ):
        mock_start.return_value = supports_start
        mock_stop.return_value = supports_stop
        mock_pause.return_value = supports_pause
        mock_return.return_value = supports_return
        mock_clean_spot.return_value = supports_clean_spot
        mock_locate.return_value = supports_locate
        mock_supports_fan_speed.return_value = fan_speed_list is not None
        mock_fan_speed_list.return_value = fan_speed_list or []
        mock_fan_speed.return_value = fan_speed

        system.get_devices = AsyncMock(return_value={vacuum.name: vacuum})

        await setup_entry(hass, config_entry, system)

    entity_ids = hass.states.async_entity_ids(VACUUM_DOMAIN)
    assert len(entity_ids) == 1
    assert entity_ids[0] == ENTITY_ID

    return system, vacuum, ENTITY_ID


@pytest.mark.parametrize(
    ("activity", "expected_state"),
    [
        pytest.param("cleaning", VacuumActivity.CLEANING, id="cleaning"),
        pytest.param("docked", VacuumActivity.DOCKED, id="docked"),
        pytest.param("idle", VacuumActivity.IDLE, id="idle"),
        pytest.param("paused", VacuumActivity.PAUSED, id="paused"),
        pytest.param("returning", VacuumActivity.RETURNING, id="returning"),
        pytest.param("error", VacuumActivity.ERROR, id="error"),
    ],
)
async def test_vacuum_activity_states(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    activity: str,
    expected_state: VacuumActivity,
) -> None:
    """Test vacuum reports the correct activity state."""
    _, _, entity_id = await _setup_vacuum(hass, config_entry, client, activity=activity)

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.state == expected_state.value


async def test_vacuum_features_basic(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test vacuum exposes supported features from the device."""
    _, _, entity_id = await _setup_vacuum(
        hass,
        config_entry,
        client,
        supports_start=True,
        supports_stop=True,
        supports_pause=False,
        supports_return=True,
        supports_clean_spot=False,
        supports_locate=False,
    )

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    expected = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
    )
    assert entity_state.attributes["supported_features"] == expected


async def test_vacuum_features_all(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test vacuum with all features enabled."""
    _, _, entity_id = await _setup_vacuum(
        hass,
        config_entry,
        client,
        supports_start=True,
        supports_stop=True,
        supports_pause=True,
        supports_return=True,
        supports_clean_spot=True,
        supports_locate=True,
        fan_speed_list=["Floor", "Floor & Walls", "Waterline"],
        fan_speed="Floor",
    )

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    expected = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.CLEAN_SPOT
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
    )
    assert entity_state.attributes["supported_features"] == expected
    assert entity_state.attributes[ATTR_FAN_SPEED] == "Floor"
    assert entity_state.attributes["fan_speed_list"] == [
        "Floor",
        "Floor & Walls",
        "Waterline",
    ]


async def test_vacuum_features_none(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test vacuum with no features enabled."""
    _, _, entity_id = await _setup_vacuum(
        hass,
        config_entry,
        client,
        supports_start=False,
        supports_stop=False,
        supports_pause=False,
        supports_return=False,
        supports_clean_spot=False,
        supports_locate=False,
    )

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.attributes["supported_features"] == 0


@pytest.mark.parametrize(
    ("service", "device_method"),
    [
        pytest.param(SERVICE_START, "start", id="start"),
        pytest.param(SERVICE_STOP, "stop", id="stop"),
        pytest.param(SERVICE_PAUSE, "pause", id="pause"),
        pytest.param(SERVICE_RETURN_TO_BASE, "return_to_base", id="return"),
        pytest.param(SERVICE_CLEAN_SPOT, "clean_spot", id="clean-spot"),
        pytest.param(SERVICE_LOCATE, "locate", id="locate"),
    ],
)
async def test_vacuum_actions(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    service: str,
    device_method: str,
) -> None:
    """Test vacuum service calls delegate to the device."""
    _, vacuum, entity_id = await _setup_vacuum(
        hass,
        config_entry,
        client,
        activity="docked",
        supports_start=True,
        supports_stop=True,
        supports_pause=True,
        supports_return=True,
        supports_clean_spot=True,
        supports_locate=True,
    )

    mock_method = AsyncMock()
    with patch.object(vacuum, device_method, mock_method):
        await hass.services.async_call(
            VACUUM_DOMAIN,
            service,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

    mock_method.assert_called_once()


async def test_vacuum_set_fan_speed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test setting fan speed on the vacuum."""
    _, vacuum, entity_id = await _setup_vacuum(
        hass,
        config_entry,
        client,
        fan_speed_list=["Floor", "Floor & Walls", "Waterline"],
        fan_speed="Floor",
    )

    mock_set = AsyncMock()
    with patch.object(vacuum, "set_fan_speed", mock_set):
        await hass.services.async_call(
            VACUUM_DOMAIN,
            SERVICE_SET_FAN_SPEED,
            {ATTR_ENTITY_ID: entity_id, ATTR_FAN_SPEED: "Waterline"},
            blocking=True,
        )

    mock_set.assert_called_once_with("Waterline")


@pytest.mark.parametrize(
    ("raised_exception", "expected_exception", "match"),
    [
        pytest.param(
            AqualinkServiceException,
            HomeAssistantError,
            "Aqualink error: AqualinkServiceException",
            id="service",
        ),
        pytest.param(
            TimeoutError(),
            HomeAssistantError,
            "Aqualink error: TimeoutError",
            id="timeout",
        ),
        pytest.param(
            httpx.HTTPError("boom"),
            HomeAssistantError,
            "Aqualink error: boom",
            id="http",
        ),
        pytest.param(
            AqualinkServiceUnauthorizedException,
            ConfigEntryAuthFailed,
            "Invalid credentials for iAquaLink",
            id="unauthorized",
        ),
    ],
)
async def test_vacuum_start_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    raised_exception: Exception | type[Exception],
    expected_exception: type[Exception],
    match: str,
) -> None:
    """Test start errors are surfaced through the vacuum service call."""
    _, vacuum, entity_id = await _setup_vacuum(
        hass, config_entry, client, activity="docked"
    )

    with (
        patch.object(vacuum, "start", AsyncMock(side_effect=raised_exception)),
        pytest.raises(expected_exception, match=match),
    ):
        await hass.services.async_call(
            VACUUM_DOMAIN,
            SERVICE_START,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )


async def test_vacuum_assumed_state_when_offline(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test assumed_state is True when system is offline."""
    system, _, entity_id = await _setup_vacuum(
        hass, config_entry, client, activity="docked"
    )

    system.online = False

    vacuum_component = hass.data[VACUUM_DOMAIN]
    entity = vacuum_component.get_entity(entity_id)
    assert entity is not None
    assert entity.assumed_state is True

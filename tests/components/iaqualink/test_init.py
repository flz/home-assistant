"""Tests for iAquaLink integration."""

from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import httpx2
from iaqualink.client import AqualinkClient
from iaqualink.exception import (
    AqualinkServiceException,
    AqualinkServiceThrottledException,
    AqualinkServiceUnauthorizedException,
)
from iaqualink.system import UnsupportedSystem
from iaqualink.systems.iaqua.device import (
    IaquaAuxSwitch,
    IaquaBinarySensor,
    IaquaClimate,
    IaquaHeater,
    IaquaLightSwitch,
    IaquaSensor,
    IaquaSetPoint,
)
from iaqualink.systems.iaqua.system import IaquaSystem, SystemStatus
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.iaqualink import DOMAIN
from homeassistant.components.iaqualink.const import UPDATE_INTERVAL_BY_SYSTEM_TYPE
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import MOCK_DATA, MOCK_USER_ID, get_aqualink_device, get_aqualink_system


async def _advance_coordinator_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Advance time to trigger coordinator update interval."""
    freezer.tick(delta=UPDATE_INTERVAL_BY_SYSTEM_TYPE["iaqua"])
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    "raised_exception",
    [
        pytest.param(AqualinkServiceException, id="service"),
        pytest.param(TimeoutError, id="timeout"),
        pytest.param(httpx2.HTTPError("boom"), id="http"),
    ],
)
async def test_system_refresh_failure_marks_entities_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    freezer: FrozenDateTimeFactory,
    raised_exception: Exception | type[Exception],
) -> None:
    """Test a system refresh failure marks attached entities unavailable."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}
    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    devices = {light.name: light}
    system.get_devices = AsyncMock(return_value=devices)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids(LIGHT_DOMAIN)
    assert len(entity_ids) == 1
    entity_id = entity_ids[0]

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON

    async def fail_update() -> None:
        system.status = SystemStatus.DISCONNECTED
        raise raised_exception

    system.refresh = AsyncMock(side_effect=fail_update)

    await _advance_coordinator_time(hass, freezer)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_light_service_calls_update_entity_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test light service calls update entity state from device properties."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}
    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    devices = {light.name: light}
    system.get_devices = AsyncMock(return_value=devices)

    async def turn_off() -> None:
        light.data["state"] = "0"

    async def turn_on() -> None:
        light.data["state"] = "1"

    light.turn_off = AsyncMock(side_effect=turn_off)
    light.turn_on = AsyncMock(side_effect=turn_on)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids(LIGHT_DOMAIN)
    assert len(entity_ids) == 1
    entity_id = entity_ids[0]

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


@pytest.mark.parametrize(
    "raised_exception",
    [
        pytest.param(AqualinkServiceException, id="service"),
        pytest.param(TimeoutError, id="timeout"),
        pytest.param(httpx2.HTTPError("boom"), id="http"),
    ],
)
async def test_setup_login_retry_exceptions(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    raised_exception: Exception | type[Exception],
) -> None:
    """Test setup encountering a login exception."""
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.iaqualink.AqualinkClient.login",
        side_effect=raised_exception,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_login_unauthorized(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test setup encountering an unauthorized exception during login."""
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.iaqualink.AqualinkClient.login",
        side_effect=AqualinkServiceUnauthorizedException,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_setup_login_timeout(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test setup encountering a timeout while logging in."""
    config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.iaqualink.AqualinkClient.login",
        side_effect=TimeoutError,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    "raised_exception",
    [
        pytest.param(AqualinkServiceException, id="service"),
        pytest.param(TimeoutError, id="timeout"),
        pytest.param(httpx2.HTTPError("boom"), id="http"),
    ],
)
async def test_setup_systems_exception(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    raised_exception: Exception | type[Exception],
) -> None:
    """Test setup encountering an exception while retrieving systems."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            side_effect=raised_exception,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_systems_unauthorized(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test setup encountering an unauthorized exception while retrieving systems."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            side_effect=AqualinkServiceUnauthorizedException,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_setup_first_refresh_unauthorized_closes_client(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test setup closes the client when first refresh triggers reauthentication."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.refresh = AsyncMock(side_effect=AqualinkServiceUnauthorizedException)
    systems = {system.serial: system}

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_setup_no_systems_recognized(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test setup ending in no systems recognized."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value={},
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_unsupported_system_skipped(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that unsupported systems are skipped with a warning."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(
        client, cls=UnsupportedSystem, data={"device_type": "foo"}
    )
    systems = {system.serial: system}

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert "Unsupported system type" in caplog.text


@pytest.mark.parametrize(
    "raised_exception",
    [
        pytest.param(AqualinkServiceException, id="service"),
        pytest.param(TimeoutError, id="timeout"),
        pytest.param(httpx2.HTTPError("boom"), id="http"),
    ],
)
async def test_setup_devices_exception(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    raised_exception: Exception | type[Exception],
) -> None:
    """Test setup encountering an exception while retrieving devices."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
        patch.object(
            system,
            "get_devices",
        ) as mock_get_devices,
    ):
        mock_get_devices.side_effect = raised_exception
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED


async def test_setup_all_good_no_recognized_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test setup ending in no devices recognized."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}

    device = get_aqualink_device(system, name="dev_1")
    devices = {device.name: device}

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
        patch.object(
            system,
            "get_devices",
        ) as mock_get_devices,
    ):
        mock_get_devices.return_value = devices
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    assert len(hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)) == 0
    assert len(hass.states.async_entity_ids(CLIMATE_DOMAIN)) == 0
    assert len(hass.states.async_entity_ids(LIGHT_DOMAIN)) == 0
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0
    assert len(hass.states.async_entity_ids(SWITCH_DOMAIN)) == 0

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_all_good_all_device_types(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test setup ending in one device of each type recognized."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    system.temp_unit = "F"
    systems = {system.serial: system}

    devices = [
        get_aqualink_device(
            system, name="aux_1", cls=IaquaAuxSwitch, data={"state": "0"}
        ),
        get_aqualink_device(
            system, name="freeze_protection", cls=IaquaBinarySensor, data={"state": "0"}
        ),
        get_aqualink_device(
            system, name="aux_2", cls=IaquaLightSwitch, data={"state": "0"}
        ),
        get_aqualink_device(system, name="ph", cls=IaquaSensor, data={"state": "7.2"}),
        get_aqualink_device(
            system, name="pool_set_point", cls=IaquaSetPoint, data={"state": "84"}
        ),
        get_aqualink_device(system, name="pool_thermostat", cls=IaquaClimate),
    ]
    devices = {d.name: d for d in devices}

    pool_heater = get_aqualink_device(
        system, name="pool_heater", cls=IaquaHeater, data={"state": "0"}
    )
    pool_temp = get_aqualink_device(
        system, name="pool_temp", cls=IaquaSensor, data={"state": "72"}
    )
    system.devices = {
        **{d.name: d for d in devices.values()},
        pool_heater.name: pool_heater,
        pool_temp.name: pool_temp,
    }

    system.get_devices = AsyncMock(return_value=devices)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    assert len(hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)) == 1
    assert len(hass.states.async_entity_ids(CLIMATE_DOMAIN)) == 1
    assert len(hass.states.async_entity_ids(LIGHT_DOMAIN)) == 1
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 1
    assert len(hass.states.async_entity_ids(SWITCH_DOMAIN)) == 1

    for domain in (
        BINARY_SENSOR_DOMAIN,
        CLIMATE_DOMAIN,
        LIGHT_DOMAIN,
        SENSOR_DOMAIN,
        SWITCH_DOMAIN,
    ):
        for entity_id in hass.states.async_entity_ids(domain):
            entry = entity_registry.async_get(entity_id)
            assert entry is not None
            assert entry.has_entity_name is True

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_multiple_updates(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test all possible results of online status transition after update."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}

    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    devices = {light.name: light}

    system.get_devices = AsyncMock(return_value=devices)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    entity_ids = hass.states.async_entity_ids(LIGHT_DOMAIN)
    assert len(entity_ids) == 1
    entity_id = entity_ids[0]

    def assert_state(expected_state: str) -> None:
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == expected_state

    def set_online_to_true():
        system.status = SystemStatus.ONLINE

    def set_online_to_false():
        system.status = SystemStatus.OFFLINE

    async def fail_update() -> None:
        system.status = SystemStatus.DISCONNECTED
        raise AqualinkServiceException

    system.refresh = AsyncMock()

    # ONLINE -> ONLINE
    system.status = SystemStatus.ONLINE
    system.refresh.side_effect = set_online_to_true
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 1
    assert_state(STATE_ON)

    # ONLINE -> OFFLINE (coordinator succeeds, entity uses assumed state)
    system.status = SystemStatus.ONLINE
    system.refresh.side_effect = set_online_to_false
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 2
    assert_state(STATE_ON)

    # ONLINE -> ERROR / ServiceException (communication failure)
    system.status = SystemStatus.ONLINE
    system.refresh.side_effect = fail_update
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 3
    assert_state(STATE_UNAVAILABLE)

    # OFFLINE -> OFFLINE (coordinator succeeds, entity uses assumed state)
    system.status = SystemStatus.OFFLINE
    system.refresh.side_effect = set_online_to_false
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 4
    assert_state(STATE_ON)

    # OFFLINE -> ONLINE
    system.status = SystemStatus.OFFLINE
    system.refresh.side_effect = set_online_to_true
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 5
    assert_state(STATE_ON)

    # OFFLINE -> ERROR / ServiceException (communication failure)
    system.status = SystemStatus.OFFLINE
    system.refresh.side_effect = fail_update
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 6
    assert_state(STATE_UNAVAILABLE)

    # UNKNOWN -> ERROR / ServiceException (communication failure)
    system.status = SystemStatus.UNKNOWN
    system.refresh.side_effect = fail_update
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 7
    assert_state(STATE_UNAVAILABLE)

    # UNKNOWN -> ONLINE
    system.status = SystemStatus.UNKNOWN
    system.refresh.side_effect = set_online_to_true
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 8
    assert_state(STATE_ON)

    # UNKNOWN -> OFFLINE (coordinator succeeds, entity uses assumed state)
    system.status = SystemStatus.UNKNOWN
    system.refresh.side_effect = set_online_to_false
    await _advance_coordinator_time(hass, freezer)
    assert system.refresh.await_count == 9
    assert_state(STATE_ON)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_entity_assumed_and_available(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test assumed_state and_available properties for all values of status."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    systems = {system.serial: system}

    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    devices = {light.name: light}
    system.get_devices = AsyncMock(return_value=devices)
    system.refresh = AsyncMock()

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids(LIGHT_DOMAIN)
    assert len(entity_ids) == 1

    name = entity_ids[0]

    # UNKNOWN: coordinator succeeds, entity available with assumed state.
    light.system.status = SystemStatus.UNKNOWN
    await _advance_coordinator_time(hass, freezer)
    state = hass.states.get(name)
    assert state.state == STATE_ON
    assert state.attributes.get(ATTR_ASSUMED_STATE) is True

    # OFFLINE: coordinator succeeds, entity available with assumed state.
    light.system.status = SystemStatus.OFFLINE
    await _advance_coordinator_time(hass, freezer)
    state = hass.states.get(name)
    assert state.state == STATE_ON
    assert state.attributes.get(ATTR_ASSUMED_STATE) is True

    # ONLINE: entity available, no assumed state.
    light.system.status = SystemStatus.ONLINE
    await _advance_coordinator_time(hass, freezer)
    state = hass.states.get(name)
    assert state.state == STATE_ON
    assert state.attributes.get(ATTR_ASSUMED_STATE) is None


async def test_system_refresh_unauthorized_triggers_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an unauthorized refresh starts reauthentication."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    systems = {system.serial: system}

    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    system.get_devices = AsyncMock(return_value={light.name: light})

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value=systems,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    system.refresh = AsyncMock(side_effect=AqualinkServiceUnauthorizedException)

    await _advance_coordinator_time(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == config_entry.entry_id


async def _login_as_mock_user(client: AqualinkClient) -> None:
    """Simulate a login that resolves the account id."""
    client.user_id = MOCK_USER_ID


async def test_migrate_entry_minor_version(hass: HomeAssistant) -> None:
    """Test a version 1.1 config entry is migrated to the latest minor version."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_DATA, version=1, minor_version=1)
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.iaqualink.AqualinkClient.login",
        side_effect=AqualinkServiceException,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.minor_version == 3


async def test_migrate_entry_set_point_climate_entities(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Test pool/spa set point climate entities migrate, pool chill is removed."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_DATA, version=1, minor_version=2)
    entry.add_to_hass(hass)

    pool = entity_registry.async_get_or_create(
        CLIMATE_DOMAIN,
        DOMAIN,
        "SN00001_pool_set_point",
        config_entry=entry,
        suggested_object_id="pool_pool_set_point",
    )
    spa = entity_registry.async_get_or_create(
        CLIMATE_DOMAIN,
        DOMAIN,
        "SN00001_spa_set_point",
        config_entry=entry,
        suggested_object_id="pool_spa_set_point",
    )
    chill = entity_registry.async_get_or_create(
        CLIMATE_DOMAIN,
        DOMAIN,
        "SN00001_pool_chill_set_point",
        config_entry=entry,
        suggested_object_id="pool_pool_chill_set_point",
    )

    with patch(
        "homeassistant.components.iaqualink.AqualinkClient.login",
        side_effect=AqualinkServiceException,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.minor_version == 3
    assert (
        entity_registry.async_get(pool.entity_id).unique_id == "SN00001_pool_thermostat"
    )
    assert (
        entity_registry.async_get(spa.entity_id).unique_id == "SN00001_spa_thermostat"
    )
    assert entity_registry.async_get(chill.entity_id) is None


async def test_setup_duplicate_account_fails(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test setup fails when another entry already uses the same account."""
    MockConfigEntry(domain=DOMAIN, data=MOCK_DATA, unique_id=MOCK_USER_ID).add_to_hass(
        hass
    )
    config_entry.add_to_hass(hass)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            autospec=True,
            side_effect=_login_as_mock_user,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.close",
            new_callable=AsyncMock,
        ) as mock_close,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_close.assert_awaited_once()


async def test_setup_first_refresh_not_ready_skips_system(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test a system failing its first refresh is skipped."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.refresh = AsyncMock(side_effect=AqualinkServiceException)
    system.get_devices = AsyncMock()

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value={system.serial: system},
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    system.get_devices.assert_not_awaited()


async def test_setup_get_devices_unauthorized(
    hass: HomeAssistant, config_entry: MockConfigEntry, client: AqualinkClient
) -> None:
    """Test unauthorized device retrieval starts reauthentication."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    system.get_devices = AsyncMock(side_effect=AqualinkServiceUnauthorizedException)

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value={system.serial: system},
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_system_refresh_throttled_keeps_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a throttled refresh does not make entities unavailable."""
    config_entry.add_to_hass(hass)

    system = get_aqualink_system(client, cls=IaquaSystem)
    system.status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    light = get_aqualink_device(
        system, name="aux_1", cls=IaquaLightSwitch, data={"state": "1"}
    )
    system.get_devices = AsyncMock(return_value={light.name: light})

    with (
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.login",
            return_value=None,
        ),
        patch(
            "homeassistant.components.iaqualink.AqualinkClient.get_systems",
            return_value={system.serial: system},
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    system.refresh = AsyncMock(side_effect=AqualinkServiceThrottledException)
    await _advance_coordinator_time(hass, freezer)

    assert hass.states.get("light.pool_aux_1").state == STATE_ON

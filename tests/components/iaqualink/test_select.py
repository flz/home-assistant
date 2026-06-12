"""Select platform tests for iAquaLink."""

from __future__ import annotations

from unittest.mock import AsyncMock

from iaqualink.client import AqualinkClient
from iaqualink.exception import AqualinkServiceException
from iaqualink.system import SystemStatus
from iaqualink.systems.iaqua.device import IaquaHeatPumpMode
from iaqualink.systems.iaqua.system import IaquaSystem
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import (
    assert_platform_setup,
    get_aqualink_device,
    get_aqualink_system,
    setup_entry,
)

from tests.common import MockConfigEntry


async def test_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test all select entities are created correctly."""
    await assert_platform_setup(
        hass, config_entry, client, entity_registry, snapshot, SELECT_DOMAIN
    )


async def _setup_select(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
    *,
    state: str,
) -> tuple[IaquaSystem, IaquaHeatPumpMode, str]:
    """Set up the integration with a single select entity."""
    system = get_aqualink_system(client, cls=IaquaSystem)
    system._status = SystemStatus.ONLINE
    system.refresh = AsyncMock()
    select = get_aqualink_device(
        system,
        name="heatpump_mode",
        cls=IaquaHeatPumpMode,
        data={"state": state},
    )
    system.get_devices = AsyncMock(return_value={select.name: select})
    system.switch_hpm_mode = AsyncMock()

    await setup_entry(hass, config_entry, system)

    entity_ids = hass.states.async_entity_ids(SELECT_DOMAIN)
    assert len(entity_ids) == 1
    entity_id = entity_ids[0]
    return system, select, entity_id


async def test_select_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test select entity reflects the current option."""
    _, _, entity_id = await _setup_select(hass, config_entry, client, state="heat")

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.state == "heat"
    assert entity_state.attributes["options"] == ["heat", "chill"]


async def test_select_option(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test selecting an option calls the underlying device method."""
    system, select, entity_id = await _setup_select(
        hass, config_entry, client, state="heat"
    )

    async def switch_hpm_mode(option: str) -> None:
        select.data["state"] = option

    system.switch_hpm_mode = AsyncMock(side_effect=switch_hpm_mode)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "chill"},
        blocking=True,
    )

    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    assert entity_state.state == "chill"


async def test_select_option_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AqualinkClient,
) -> None:
    """Test that service exceptions are raised as HomeAssistantError."""
    system, _, entity_id = await _setup_select(hass, config_entry, client, state="heat")

    system.switch_hpm_mode = AsyncMock(side_effect=AqualinkServiceException)

    with pytest.raises(HomeAssistantError, match="Aqualink error"):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "chill"},
            blocking=True,
        )

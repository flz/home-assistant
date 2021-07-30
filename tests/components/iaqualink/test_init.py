"""Tests for iaqualink integration."""

import asyncio
from unittest.mock import AsyncMock, patch

from iaqualink.device import (
    AqualinkAuxToggle,
    AqualinkBinarySensor,
    AqualinkDevice,
    AqualinkLightToggle,
    AqualinkSensor,
    AqualinkThermostat,
)
import iaqualink.exception
from iaqualink.system import AqualinkSystem

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.iaqualink import DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState

async_noop = AsyncMock(return_value=None)


def _(cls, data=None):
    """Create an aqualink class instance with little syntactic overhead."""
    return cls(None, data if data else {})


MOCK_SYSTEMS = {"SERIAL": _(AqualinkSystem)}
MOCK_UNKNOWN_DEVICES = {"1": _(AqualinkDevice)}
MOCK_DEVICES = {
    "1": _(AqualinkAuxToggle),
    "2": _(AqualinkBinarySensor),
    "3": _(AqualinkLightToggle),
    "4": _(AqualinkSensor),
    "5": _(AqualinkThermostat),
}


async def test_setup_login_exception(hass, config_entry):
    """Test setup encountering a login exception."""
    config_entry.add_to_hass(hass)

    with patch(
        "iaqualink.client.AqualinkClient.login",
        side_effect=iaqualink.exception.AqualinkServiceException,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_login_timeout(hass, config_entry):
    """Test setup encountering a timeout while logging in."""
    config_entry.add_to_hass(hass)

    with patch(
        "iaqualink.client.AqualinkClient.login",
        side_effect=asyncio.TimeoutError,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_systems_exception(hass, config_entry):
    """Test setup encountering an exception while retrieving systems."""
    config_entry.add_to_hass(hass)

    with patch("iaqualink.client.AqualinkClient.login", return_value=None), patch(
        "iaqualink.client.AqualinkClient.get_systems",
        side_effect=iaqualink.exception.AqualinkServiceException,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_no_systems_recognized(hass, config_entry):
    """Test setup ending in no systems recognized."""
    config_entry.add_to_hass(hass)

    with patch("iaqualink.client.AqualinkClient.login", return_value=None), patch(
        "iaqualink.client.AqualinkClient.get_systems",
        return_value={},
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_devices_exception(hass, config_entry):
    """Test setup encountering an exception while retrieving devices."""
    config_entry.add_to_hass(hass)

    with patch("iaqualink.client.AqualinkClient.login", return_value=None), patch(
        "iaqualink.client.AqualinkClient.get_systems", return_value=MOCK_SYSTEMS
    ), patch(
        "iaqualink.system.AqualinkSystem.get_devices",
        side_effect=iaqualink.exception.AqualinkServiceException,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_all_good_no_recognized_devices(hass, config_entry):
    """Test setup ending in no devices recognized."""
    config_entry.add_to_hass(hass)

    with patch("iaqualink.client.AqualinkClient.login", return_value=None), patch(
        "iaqualink.client.AqualinkClient.get_systems", return_value=MOCK_SYSTEMS
    ), patch(
        "iaqualink.system.AqualinkSystem.get_devices", return_value=MOCK_UNKNOWN_DEVICES
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.LOADED

    assert hass.data[DOMAIN][BINARY_SENSOR_DOMAIN] == []
    assert hass.data[DOMAIN][CLIMATE_DOMAIN] == []
    assert hass.data[DOMAIN][LIGHT_DOMAIN] == []
    assert hass.data[DOMAIN][SENSOR_DOMAIN] == []
    assert hass.data[DOMAIN][SWITCH_DOMAIN] == []


async def test_setup_all_good_all_device_types(hass, config_entry):
    """Test setup ending in one device of each type recognized."""
    config_entry.add_to_hass(hass)

    with patch("iaqualink.client.AqualinkClient.login", return_value=None), patch(
        "iaqualink.client.AqualinkClient.get_systems", return_value=MOCK_SYSTEMS
    ), patch("iaqualink.system.AqualinkSystem.get_devices", return_value=MOCK_DEVICES):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.LOADED

    assert len(hass.data[DOMAIN][BINARY_SENSOR_DOMAIN]) == 1
    assert len(hass.data[DOMAIN][CLIMATE_DOMAIN]) == 1
    assert len(hass.data[DOMAIN][LIGHT_DOMAIN]) == 1
    assert len(hass.data[DOMAIN][SENSOR_DOMAIN]) == 1
    assert len(hass.data[DOMAIN][SWITCH_DOMAIN]) == 1

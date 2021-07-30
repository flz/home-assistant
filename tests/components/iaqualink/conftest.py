"""Configuration for iAqualink tests."""
import pytest

from homeassistant.components.iaqualink import DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from tests.common import MockConfigEntry

MOCK_DATA = {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "password"}


@pytest.fixture(name="config_data")
def config_data_fixture():
    """Create hass config fixture."""
    return MOCK_DATA


@pytest.fixture(name="config")
def config_fixture():
    """Create hass config fixture."""
    return {DOMAIN: MOCK_DATA}


@pytest.fixture(name="config_entry")
def config_entry_fixture():
    """Create a mock HEOS config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_DATA,
    )

"""Support for Aqualink select entities."""

from iaqualink.device import AqualinkSelect

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AqualinkConfigEntry, refresh_system
from .coordinator import AqualinkDataUpdateCoordinator
from .entity import AqualinkEntity
from .utils import await_or_reraise

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AqualinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up discovered select entities."""
    async_add_entities(
        HassAqualinkSelect(
            config_entry.runtime_data.coordinators[dev.system.serial], dev
        )
        for dev in config_entry.runtime_data.selects
    )


class HassAqualinkSelect(AqualinkEntity[AqualinkSelect], SelectEntity):
    """Representation of a select entity."""

    def __init__(
        self, coordinator: AqualinkDataUpdateCoordinator, dev: AqualinkSelect
    ) -> None:
        """Initialize AquaLink select."""
        super().__init__(coordinator, dev)
        self._attr_options = dev.options

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.dev.current_option

    @refresh_system
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.select_option(option)
        )

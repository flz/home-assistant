"""Support for Aqualink number entities."""

from iaqualink.device import AqualinkNumber

from homeassistant.components.number import NumberEntity
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
    """Set up discovered number entities."""
    async_add_entities(
        HassAqualinkNumber(
            config_entry.runtime_data.coordinators[dev.system.serial], dev
        )
        for dev in config_entry.runtime_data.numbers
    )


class HassAqualinkNumber(AqualinkEntity[AqualinkNumber], NumberEntity):
    """Representation of a number entity."""

    def __init__(
        self, coordinator: AqualinkDataUpdateCoordinator, dev: AqualinkNumber
    ) -> None:
        """Initialize AquaLink number."""
        super().__init__(coordinator, dev)
        self._attr_native_min_value = dev.min_value
        self._attr_native_max_value = dev.max_value
        self._attr_native_step = dev.step
        if dev.unit_of_measurement is not None:
            self._attr_native_unit_of_measurement = dev.unit_of_measurement

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.dev.current_value

    @refresh_system
    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        await await_or_reraise(self.dev.set_value(value))

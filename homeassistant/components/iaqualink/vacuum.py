"""Support for Aqualink pool cleaning robots."""

from typing import Any

from iaqualink.device import AqualinkVacuum

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
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
    """Set up discovered vacuum cleaners."""
    async_add_entities(
        HassAqualinkVacuum(
            config_entry.runtime_data.coordinators[dev.system.serial], dev
        )
        for dev in config_entry.runtime_data.vacuums
    )


class HassAqualinkVacuum(AqualinkEntity[AqualinkVacuum], StateVacuumEntity):
    """Representation of a pool cleaning robot."""

    def __init__(
        self, coordinator: AqualinkDataUpdateCoordinator, dev: AqualinkVacuum
    ) -> None:
        """Initialize AquaLink vacuum."""
        super().__init__(coordinator, dev)
        features = VacuumEntityFeature(0)
        if dev.supports_start:
            features |= VacuumEntityFeature.START
        if dev.supports_stop:
            features |= VacuumEntityFeature.STOP
        if dev.supports_pause:
            features |= VacuumEntityFeature.PAUSE
        if dev.supports_return:
            features |= VacuumEntityFeature.RETURN_HOME
        if dev.supports_clean_spot:
            features |= VacuumEntityFeature.CLEAN_SPOT
        if dev.supports_locate:
            features |= VacuumEntityFeature.LOCATE
        if dev.supports_fan_speed:
            features |= VacuumEntityFeature.FAN_SPEED
            self._attr_fan_speed_list = dev.fan_speed_list
        self._attr_supported_features = features

    @property
    def activity(self) -> VacuumActivity:
        """Return the current vacuum activity."""
        return VacuumActivity(self.dev.activity.value)

    @property
    def fan_speed(self) -> str | None:
        """Return the current fan speed."""
        return self.dev.fan_speed

    @refresh_system
    async def async_start(self, **kwargs: Any) -> None:
        """Start cleaning."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.start()
        )

    @refresh_system
    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.stop()
        )

    @refresh_system
    async def async_pause(self, **kwargs: Any) -> None:
        """Pause cleaning."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.pause()
        )

    @refresh_system
    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return to base."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.return_to_base()
        )

    @refresh_system
    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.clean_spot()
        )

    @refresh_system
    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the robot."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.locate()
        )

    @refresh_system
    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set the fan speed (cleaning mode)."""
        await await_or_reraise(
            self.hass,
            self.coordinator.config_entry,
            self.dev.set_fan_speed(fan_speed),
        )

"""Support for Aqualink pool pumps."""

from typing import Any, override

from iaqualink.device import AqualinkFan

from homeassistant.components.fan import FanEntity, FanEntityFeature
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
    """Set up discovered pumps as fan entities."""
    async_add_entities(
        HassAqualinkFan(config_entry.runtime_data.coordinators[dev.system.serial], dev)
        for dev in config_entry.runtime_data.fans
    )


class HassAqualinkFan(AqualinkEntity[AqualinkFan], FanEntity):
    """Representation of a pump as a fan entity."""

    def __init__(
        self, coordinator: AqualinkDataUpdateCoordinator, dev: AqualinkFan
    ) -> None:
        """Initialize AquaLink fan."""
        super().__init__(coordinator, dev)
        features = FanEntityFeature(0)
        if dev.supports_turn_on:
            features |= FanEntityFeature.TURN_ON
        if dev.supports_turn_off:
            features |= FanEntityFeature.TURN_OFF
        if dev.supports_percentage:
            features |= FanEntityFeature.SET_SPEED
        if dev.supports_presets:
            features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = dev.preset_modes
        self._attr_supported_features = features

    @property
    @override
    def is_on(self) -> bool:
        """Return whether the fan is on."""
        return self.dev.is_on

    @property
    @override
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        return self.dev.percentage

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self.dev.preset_mode

    @refresh_system
    @override
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if preset_mode is not None:
            await await_or_reraise(
                self.hass,
                self.coordinator.config_entry,
                self.dev.set_preset_mode(preset_mode),
            )
        elif percentage is not None:
            await await_or_reraise(
                self.hass,
                self.coordinator.config_entry,
                self.dev.set_percentage(percentage),
            )
        else:
            await await_or_reraise(
                self.hass, self.coordinator.config_entry, self.dev.turn_on()
            )

    @refresh_system
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await await_or_reraise(
            self.hass, self.coordinator.config_entry, self.dev.turn_off()
        )

    @refresh_system
    @override
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage."""
        if percentage == 0:
            await await_or_reraise(
                self.hass, self.coordinator.config_entry, self.dev.turn_off()
            )
        else:
            await await_or_reraise(
                self.hass,
                self.coordinator.config_entry,
                self.dev.set_percentage(percentage),
            )

    @refresh_system
    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        await await_or_reraise(
            self.hass,
            self.coordinator.config_entry,
            self.dev.set_preset_mode(preset_mode),
        )

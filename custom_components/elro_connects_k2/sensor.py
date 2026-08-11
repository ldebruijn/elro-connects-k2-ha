"""Sensor platform for the ELRO Connects K2 integration.

Battery % and RF signal bars are added to every sub-device via
UNIVERSAL_CAPABILITIES. CO2, temperature, and humidity entities are
added for devices whose DeviceProfile includes those capabilities.
"""

from __future__ import annotations

from typing import Any

from elro_connects_k2_protocol.device_profiles import UNIVERSAL_CAPABILITIES
from elro_connects_k2_protocol.models import DeviceCapability, SubDevice, ThermostatMode
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ElroK2Coordinator

_SENSOR_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "battery": SensorDeviceClass.BATTERY,
    # K2 signal is 1–4 bars with no real dBm mapping, so we use ENUM rather
    # than SIGNAL_STRENGTH (which HA requires to have a dB/dBm unit).
    "signal_strength": SensorDeviceClass.ENUM,
    "enum": SensorDeviceClass.ENUM,
    "carbon_dioxide": SensorDeviceClass.CO2,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
}

_SIGNAL_BARS_TO_STATE = {1: "poor", 2: "fair", 3: "good", 4: "excellent"}

# HA requires every ENUM sensor to declare the exact set of states it can
# report, so each enum capability needs its own option list.
_ENUM_OPTIONS: dict[str, list[str]] = {
    "signal": list(_SIGNAL_BARS_TO_STATE.values()),
    "mode": [m.name.lower() for m in ThermostatMode],
}

_DIAGNOSTIC_KEYS = {"battery", "signal"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ElroK2Coordinator = hass.data[DOMAIN][entry.entry_id]
    known_subs: set[int] = set()

    @callback
    def _add_new_entities() -> None:
        entities: list[SensorEntity] = []
        for sub_id, device in (coordinator.data or {}).items():
            if sub_id in known_subs:
                continue
            known_subs.add(sub_id)
            universal = [
                c for c in UNIVERSAL_CAPABILITIES
                if not (c.key == "battery" and device.profile.mains_powered)
            ]
            all_caps = list(device.profile.capabilities) + universal
            for cap in all_caps:
                if cap.entity_type == "sensor":
                    entities.append(ElroK2Sensor(coordinator, sub_id, cap))
        if entities:
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


def _device_info(gateway_name: str, sub_id: int, device: SubDevice) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{gateway_name}_{sub_id}")},
        name=f"{device.profile.name} {sub_id}",
        manufacturer="ELRO Connects",
        model=", ".join(device.profile.model_hints) or device.device_type,
        via_device=(DOMAIN, gateway_name),
    )


class ElroK2Sensor(CoordinatorEntity[ElroK2Coordinator], SensorEntity):
    """Sensor entity for a single numeric or enum capability."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ElroK2Coordinator,
        sub_id: int,
        cap: DeviceCapability,
    ) -> None:
        super().__init__(coordinator)
        self._sub_id = sub_id
        self._cap = cap
        gateway_name = coordinator.gateway.device_name
        self._attr_unique_id = f"{gateway_name}_{sub_id}_{cap.key}"
        self._attr_name = cap.label
        self._attr_device_class = _SENSOR_DEVICE_CLASS_MAP.get(cap.device_class)
        self._attr_device_info = _device_info(
            gateway_name, sub_id, coordinator.data[sub_id]
        )
        if cap.key in _DIAGNOSTIC_KEYS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Enum sensors must not have a unit or measurement state class.
        if self._attr_device_class == SensorDeviceClass.ENUM:
            self._attr_options = _ENUM_OPTIONS.get(cap.key, [])
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = cap.unit

    @property
    def native_value(self) -> int | float | str | None:
        device: SubDevice | None = (self.coordinator.data or {}).get(self._sub_id)
        if device is None:
            return None
        match self._cap.key:
            case "battery":
                return device.battery_pct
            case "signal":
                return _SIGNAL_BARS_TO_STATE.get(device.signal_bars)
            case "co2":
                return device.co2_ppm
            case "temperature":
                return device.temperature_c
            case "humidity":
                return device.humidity_pct
            case "setpoint":
                return device.temperature_setpoint
            case "mode":
                mode = device.thermostat_mode
                return mode.name.lower() if mode is not None else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._cap.key == "signal":
            device = (self.coordinator.data or {}).get(self._sub_id)
            return {"raw_signal_field": device.raw_status[0:2] if device else None}
        return {}

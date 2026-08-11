"""Binary sensor platform for the ELRO Connects K2 integration.

One entity is created per DeviceCapability with entity_type=="binary_sensor",
plus one unconditional fault entity per sub-device. Entity platforms never
branch on device type codes — all routing goes through DeviceProfile.
"""

from __future__ import annotations

from typing import Any

from elro_connects_k2_protocol.models import AlarmState, DeviceCapability, SubDevice
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ElroK2Coordinator

_DEVICE_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "smoke": BinarySensorDeviceClass.SMOKE,
    "carbon_monoxide": BinarySensorDeviceClass.CO,
    "gas": BinarySensorDeviceClass.GAS,
    "heat": BinarySensorDeviceClass.HEAT,
    "moisture": BinarySensorDeviceClass.MOISTURE,
    "motion": BinarySensorDeviceClass.MOTION,
    "door": BinarySensorDeviceClass.DOOR,
    "vibration": BinarySensorDeviceClass.VIBRATION,
    "opening": BinarySensorDeviceClass.OPENING,
    "window": BinarySensorDeviceClass.WINDOW,
    "problem": BinarySensorDeviceClass.PROBLEM,
}

# AlarmState values that represent a "triggered/open" condition.
# Includes standard ALARM plus the two alternate door-sensor open encodings
# seen on GS320 series hardware (A0 and 66).
_TRIGGERED_STATES = frozenset({
    AlarmState.ALARM,
    AlarmState.OPEN,
    AlarmState.OPEN_VARIANT,
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ElroK2Coordinator = hass.data[DOMAIN][entry.entry_id]
    known_subs: set[int] = set()

    @callback
    def _add_new_entities() -> None:
        entities: list[BinarySensorEntity] = []
        for sub_id, device in (coordinator.data or {}).items():
            if sub_id in known_subs:
                continue
            known_subs.add(sub_id)
            for cap in device.profile.capabilities:
                if cap.entity_type == "binary_sensor":
                    entities.append(ElroK2AlarmSensor(coordinator, sub_id, cap))
            # Fault sensor is unconditional — every device can report a fault
            entities.append(ElroK2FaultSensor(coordinator, sub_id))
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


class ElroK2AlarmSensor(CoordinatorEntity[ElroK2Coordinator], BinarySensorEntity):
    """Binary sensor for a single hazard capability (smoke, CO, gas, heat, water)."""

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
        self._attr_device_class = _DEVICE_CLASS_MAP.get(cap.device_class)
        self._attr_device_info = _device_info(
            gateway_name, sub_id, coordinator.data[sub_id]
        )

    @property
    def is_on(self) -> bool | None:
        device = (self.coordinator.data or {}).get(self._sub_id)
        if device is None:
            return None
        # Thermostat binary sensors read dedicated SubDevice fields rather than
        # alarm_state, because the GS361 repurposes the alarm byte for its own
        # status encoding (see decode_thermostat_status in parser.py).
        if self._cap.key == "valve":
            return device.valve_open
        if self._cap.key == "window":
            return device.window_open
        return device.alarm_state in _TRIGGERED_STATES

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = (self.coordinator.data or {}).get(self._sub_id)
        if device is None:
            return {}
        attrs: dict[str, Any] = {
            "alarm_state": device.alarm_state.name,
            "raw_status": device.raw_status,
        }
        if device.nickname is not None:
            attrs["nickname"] = device.nickname
        return attrs


class ElroK2FaultSensor(CoordinatorEntity[ElroK2Coordinator], BinarySensorEntity):
    """Binary sensor for the fault/tamper state — present on every sub-device."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Fault"

    def __init__(self, coordinator: ElroK2Coordinator, sub_id: int) -> None:
        super().__init__(coordinator)
        self._sub_id = sub_id
        gateway_name = coordinator.gateway.device_name
        self._attr_unique_id = f"{gateway_name}_{sub_id}_fault"
        self._attr_device_info = _device_info(
            gateway_name, sub_id, coordinator.data[sub_id]
        )

    @property
    def is_on(self) -> bool | None:
        device = (self.coordinator.data or {}).get(self._sub_id)
        if device is None:
            return None
        return device.alarm_state == AlarmState.FAULT

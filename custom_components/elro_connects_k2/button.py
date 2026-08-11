"""Button platform for the ELRO Connects K2 integration.

Creates two types of button entities:

  ElroK2SyncButton    — one per gateway, triggers an on-demand CMD_CODE 54 sync.

  ElroK2ActionButton  — one per (device, action): "Test" and "Mute" buttons for
                        every sub-device whose DeviceProfile includes those actions.
                        "Test" triggers the device's built-in alarm test; "Mute"
                        silences an active alarm.  Both call CMD_CODE 1 with the
                        payload stored in the DeviceProfile, so no type-code
                        branching is needed here.

Because HA button entities are services under the hood, both buttons are
also callable from automations via ``button.press``.
"""

from __future__ import annotations

from elro_connects_k2_protocol.models import SubDevice
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ElroK2Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ElroK2Coordinator = hass.data[DOMAIN][entry.entry_id]
    known_subs: set[int] = set()

    # Gateway-level sync button — created once, not per sub-device.
    async_add_entities([ElroK2SyncButton(coordinator)])

    @callback
    def _add_new_entities() -> None:
        entities: list[ButtonEntity] = []
        for sub_id, device in (coordinator.data or {}).items():
            if sub_id in known_subs:
                continue
            known_subs.add(sub_id)
            if device.profile.test_action:
                entities.append(
                    ElroK2ActionButton(coordinator, sub_id, device.profile.test_action, "Test")
                )
            if device.profile.mute_action:
                entities.append(
                    ElroK2ActionButton(coordinator, sub_id, device.profile.mute_action, "Mute")
                )
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


class ElroK2SyncButton(ButtonEntity):
    """Button that triggers an on-demand CMD_CODE 54 sync."""

    _attr_has_entity_name = True
    _attr_name = "Sync now"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ElroK2Coordinator) -> None:
        self._coordinator = coordinator
        gateway_name = coordinator.gateway.device_name
        self._attr_unique_id = f"{gateway_name}_sync_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, gateway_name)},
            name=f"ELRO Connects K2 Gateway ({gateway_name})",
            manufacturer="ELRO Connects",
            model="K2 (SF50GA)",
        )

    async def async_press(self) -> None:
        await self._coordinator.async_refresh()


class ElroK2ActionButton(CoordinatorEntity[ElroK2Coordinator], ButtonEntity):
    """Button that sends CMD_CODE 1 to a specific sub-device.

    The action payload (e.g. ``"BB000000"`` for test, ``"50000000"`` for mute)
    comes from the device's ``DeviceProfile`` and is passed in at construction
    time.  This class is payload-agnostic — it just sends whatever it was given.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ElroK2Coordinator,
        sub_id: int,
        action: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._sub_id = sub_id
        self._action = action
        gateway_name = coordinator.gateway.device_name
        self._attr_unique_id = f"{gateway_name}_{sub_id}_{label.lower()}"
        self._attr_name = label
        self._attr_device_info = _device_info(
            gateway_name, sub_id, coordinator.data[sub_id]
        )

    async def async_press(self) -> None:
        self.coordinator.gateway.send_device_action(self._sub_id, self._action)

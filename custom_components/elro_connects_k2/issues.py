"""Repairs issues explaining why a hub produced no devices.

What users report is always the same sentence — "the hub was added but no
entities appeared" — while the reason was only ever visible to someone willing
to turn on debug logging and read UDP frames. These issues put the conclusion
the log already draws in front of everyone else.

Deliberately short on detail: the cause is named in a sentence and the rest
lives in the README the card links to, so the wording here does not have to be
maintained as a second copy of the troubleshooting guide.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_DEVICE_NAME, DOMAIN

# The hub never acknowledged an activation ping, so it is dropping every command
# sent to it: unreachable, a device name that does not match, or stalled on its
# own blocked call home.
ISSUE_HUB_NOT_ARMED = "hub_not_armed"
# The hub acknowledges pings but answers no command, not even the one that does
# not touch its device table. It is reachable at the network level and not
# processing commands — a hub-side or network-side fault rather than anything
# misconfigured in Home Assistant.
ISSUE_HUB_NOT_ANSWERING = "hub_not_answering"
# The hub answered a command that does not depend on its device table, then
# listed no sub-devices. That is a believable "nothing is paired here".
ISSUE_HUB_NO_DEVICES = "hub_no_devices"

LEARN_MORE_URL = (
    "https://github.com/ldebruijn/elro-connects-k2-ha"
    "#no-devices-appear-in-home-assistant"
)


def _issue_id(entry: ConfigEntry) -> str:
    """Return the issue ID for a hub.

    One ID per hub whatever the cause, so a hub that moves between the two
    translation keys replaces its card instead of stacking a second one.
    """
    return f"hub_not_reporting_{entry.entry_id}"


def async_clear_hub_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Withdraw the issue for a hub that is reporting devices again."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


def async_report_hub_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    activated: bool,
    answering: bool,
) -> None:
    """Raise the issue for a hub that produced no devices.

    Two independent signals, because one is not enough. ``activated`` says the
    hub answered an activation ping, which happens at a layer below its command
    dispatcher — so it proves the hub is powered and reachable and nothing more.
    ``answering`` says it answered a gateway-info command, which does not read
    the device table, and so is the only evidence that it is processing commands
    at all.

    That second signal is what makes "no devices" trustworthy. A K2 has no
    "nothing to report" response — asked about a sub-device that does not exist,
    a healthy hub replies with nothing whatsoever — so an empty status sync
    looks exactly like a hub ignoring the request. Before gateway-info there was
    no way to tell those apart, and this issue told users their installation was
    empty when it might simply have been deaf.
    """
    if not activated:
        translation_key = ISSUE_HUB_NOT_ARMED
    elif not answering:
        translation_key = ISSUE_HUB_NOT_ANSWERING
    else:
        translation_key = ISSUE_HUB_NO_DEVICES

    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=translation_key,
        translation_placeholders={
            "host": entry.data[CONF_HOST],
            "device_name": entry.data[CONF_DEVICE_NAME],
        },
        learn_more_url=LEARN_MORE_URL,
    )

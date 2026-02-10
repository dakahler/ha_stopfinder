"""Sensor platform for Stopfinder."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import StopfinderCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Stopfinder sensors."""
    coordinator: StopfinderCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Wait for first data update
    await coordinator.async_config_entry_first_refresh()

    # Create sensors for each student
    students = coordinator.data.get("students", []) if coordinator.data else []
    for student in students:
        rider_id = student.get("rider_id", "")
        first_name = student.get("first_name", "")
        last_name = student.get("last_name", "")
        student_name = f"{first_name} {last_name}".strip() or rider_id

        entities.extend(
            [
                StopfinderNextPickupSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderNextDropoffSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderBusNumberSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderSchoolSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderPickupStopSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderDropoffStopSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
                StopfinderRouteStartSensor(
                    coordinator, entry, rider_id, student_name, student
                ),
            ]
        )

    async_add_entities(entities)


class StopfinderBaseSensor(CoordinatorEntity[StopfinderCoordinator], SensorEntity):
    """Base class for Stopfinder sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._rider_id = rider_id
        self._student_name = student_name
        self._student_data = student_data
        self._attr_unique_id = f"{entry.entry_id}_{rider_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{rider_id}")},
            name=student_name,
            manufacturer="Transfinder",
            model="Stopfinder",
            entry_type=DeviceEntryType.SERVICE,
        )

    @staticmethod
    def _parse_datetime(time_str: str | None) -> datetime | None:
        """Parse a datetime string and ensure it is timezone-aware."""
        if not time_str:
            return None
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt
        except (ValueError, AttributeError):
            return None

    def _get_student_data(self) -> dict[str, Any] | None:
        """Get current student data from coordinator."""
        if not self.coordinator.data:
            return None
        students = self.coordinator.data.get("students", [])
        for student in students:
            if student.get("rider_id") == self._rider_id:
                return student
        return None

    def _get_next_trip(self, to_school: bool | None = None) -> dict[str, Any] | None:
        """Get the next trip for this student."""
        student = self._get_student_data()
        if not student:
            return None

        now = dt_util.now()
        trips = student.get("trips", [])

        _LOGGER.debug(
            "%s: finding next trip (to_school=%s) from %d trips, now=%s",
            self._student_name, to_school, len(trips), now.isoformat(),
        )

        next_trip = None
        next_time = None

        for trip in trips:
            # Filter by direction if specified
            if to_school is not None and trip.get("to_school") != to_school:
                continue

            # Get the relevant time based on trip direction
            if to_school or (to_school is None and trip.get("to_school")):
                time_str = trip.get("pickup_time")
            else:
                time_str = trip.get("dropoff_time") or trip.get("pickup_time")

            trip_time = self._parse_datetime(time_str)
            if not trip_time:
                continue

            # Only consider future trips
            if trip_time > now:
                if next_time is None or trip_time < next_time:
                    next_time = trip_time
                    next_trip = trip

        if next_trip:
            _LOGGER.debug(
                "%s: selected trip %s on %s (pickup=%s, dropoff=%s, to_school=%s)",
                self._student_name,
                next_trip.get("name"),
                next_time.isoformat() if next_time else "?",
                next_trip.get("pickup_time"),
                next_trip.get("dropoff_time"),
                next_trip.get("to_school"),
            )
        else:
            _LOGGER.debug("%s: no future trip found for to_school=%s", self._student_name, to_school)

        return next_trip


class StopfinderNextPickupSensor(StopfinderBaseSensor):
    """Sensor for next pickup time."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="next_pickup",
                name="Next Pickup",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:bus-clock",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the next pickup time."""
        trip = self._get_next_trip(to_school=True)
        if not trip:
            return None
        raw = trip.get("pickup_time")
        parsed = self._parse_datetime(raw)
        _LOGGER.debug(
            "%s next_pickup: raw=%s parsed=%s (trip=%s)",
            self._student_name, raw, parsed, trip.get("name"),
        )
        return parsed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        trip = self._get_next_trip(to_school=True)
        if not trip:
            return {}
        return {
            "stop_name": trip.get("pickup_stop_name", ""),
            "bus_number": trip.get("bus_number", ""),
            "trip_name": trip.get("name", ""),
        }


class StopfinderNextDropoffSensor(StopfinderBaseSensor):
    """Sensor for next drop-off time."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="next_dropoff",
                name="Next Drop-off",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:bus-stop",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the next drop-off time."""
        trip = self._get_next_trip(to_school=False)
        if not trip:
            return None
        raw = trip.get("dropoff_time")
        parsed = self._parse_datetime(raw)
        _LOGGER.debug(
            "%s next_dropoff: raw=%s parsed=%s (trip=%s)",
            self._student_name, raw, parsed, trip.get("name"),
        )
        return parsed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        trip = self._get_next_trip(to_school=False)
        if not trip:
            return {}
        return {
            "stop_name": trip.get("dropoff_stop_name", ""),
            "bus_number": trip.get("bus_number", ""),
            "trip_name": trip.get("name", ""),
        }


class StopfinderBusNumberSensor(StopfinderBaseSensor):
    """Sensor for bus number."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="bus_number",
                name="Bus Number",
                icon="mdi:bus",
            ),
        )

    @property
    def native_value(self) -> str | None:
        """Return the bus number for the next trip."""
        trip = self._get_next_trip()
        if not trip:
            return None
        return trip.get("bus_number") or None


class StopfinderSchoolSensor(StopfinderBaseSensor):
    """Sensor for school name."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="school",
                name="School",
                icon="mdi:school",
            ),
        )

    @property
    def native_value(self) -> str | None:
        """Return the school name."""
        student = self._get_student_data()
        if not student:
            return None
        return student.get("school") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        student = self._get_student_data()
        if not student:
            return {}
        return {
            "grade": student.get("grade", ""),
        }


class StopfinderPickupStopSensor(StopfinderBaseSensor):
    """Sensor for next pickup stop name."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="pickup_stop",
                name="Pickup Stop",
                icon="mdi:map-marker",
            ),
        )

    @property
    def native_value(self) -> str | None:
        """Return the pickup stop name for the next trip."""
        trip = self._get_next_trip(to_school=True)
        if not trip:
            return None
        return trip.get("pickup_stop_name") or None


class StopfinderDropoffStopSensor(StopfinderBaseSensor):
    """Sensor for next drop-off stop name."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="dropoff_stop",
                name="Drop-off Stop",
                icon="mdi:map-marker-check",
            ),
        )

    @property
    def native_value(self) -> str | None:
        """Return the drop-off stop name for the next trip."""
        trip = self._get_next_trip(to_school=False)
        if not trip:
            return None
        return trip.get("dropoff_stop_name") or None


class StopfinderRouteStartSensor(StopfinderBaseSensor):
    """Sensor for when the bus route starts."""

    def __init__(
        self,
        coordinator: StopfinderCoordinator,
        entry: ConfigEntry,
        rider_id: str,
        student_name: str,
        student_data: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            rider_id,
            student_name,
            student_data,
            SensorEntityDescription(
                key="route_start",
                name="Route Start",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:bus-alert",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the start time of the next bus route."""
        trip = self._get_next_trip()
        if not trip:
            return None
        return self._parse_datetime(trip.get("start_time"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        trip = self._get_next_trip()
        if not trip:
            return {}
        return {
            "trip_name": trip.get("name", ""),
            "bus_number": trip.get("bus_number", ""),
        }

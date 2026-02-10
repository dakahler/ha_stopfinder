"""Stopfinder API client."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import API_VERSION, APP_VERSION, USER_AGENT

_LOGGER = logging.getLogger(__name__)


class StopfinderApiError(Exception):
    """Base exception for Stopfinder API errors."""


class StopfinderAuthError(StopfinderApiError):
    """Authentication error."""


class StopfinderConnectionError(StopfinderApiError):
    """Connection error."""


class StopfinderApiClient:
    """Stopfinder API client."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session = session
        self._token: str | None = None
        self._client_id: str | None = None
        self._api_base_url: str | None = None

    def _get_headers(self, include_token: bool = False) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "file://",
            "X-Requested-With": "com.transfinder.stopfinder",
            "X-StopfinderApp-Version": APP_VERSION,
        }
        if include_token and self._token:
            headers["Token"] = self._token
        return headers

    async def _get_stopfinder_base_url(self) -> str:
        """Get the Stopfinder API base URL from the Transfinder server."""
        url = f"{self._base_url}/$xcom/getStopfinder.asp?/email=test"
        _LOGGER.debug("Discovering API base URL from %s", url)
        try:
            async with self._session.get(
                url, headers=self._get_headers(), ssl=False
            ) as response:
                if response.status != 200:
                    raise StopfinderConnectionError(
                        f"Failed to get Stopfinder URL: {response.status}"
                    )
                data = await response.text()
                data = data.strip()
                if data.startswith("http"):
                    _LOGGER.debug("Discovered API base URL: %s", data)
                    return data
                raise StopfinderConnectionError("Invalid response from Stopfinder discovery")
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    async def _authenticate(self) -> None:
        """Authenticate with the Stopfinder API."""
        if not self._api_base_url:
            self._api_base_url = await self._get_stopfinder_base_url()

        device_id = secrets.token_hex(8)
        auth_data = {
            "grantType": "password",
            "Username": self._username,
            "Password": self._password,
            "deviceId": device_id,
            "rfApiVersion": API_VERSION,
        }

        url = f"{self._api_base_url}/tokens"
        _LOGGER.debug("Authenticating user %s at %s", self._username, url)
        try:
            async with self._session.post(
                url, json=auth_data, headers=self._get_headers(), ssl=False
            ) as response:
                if response.status in (400, 401):
                    _LOGGER.debug("Authentication rejected: status %s", response.status)
                    raise StopfinderAuthError("Invalid credentials")
                if response.status not in (200, 201):
                    _LOGGER.debug("Authentication failed: status %s", response.status)
                    raise StopfinderAuthError(
                        f"Authentication failed: {response.status}"
                    )
                data = await response.json()
                self._token = data.get("token")
                if not self._token:
                    raise StopfinderAuthError("No token in response")
                _LOGGER.debug("Authentication successful")
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    async def _get_client_id(self) -> str:
        """Get the client ID from API versions endpoint."""
        if not self._api_base_url:
            self._api_base_url = await self._get_stopfinder_base_url()

        url = f"{self._api_base_url}/systems/apiversions"
        _LOGGER.debug("Fetching client ID from %s", url)
        try:
            async with self._session.get(
                url, headers=self._get_headers(include_token=True), ssl=False
            ) as response:
                if response.status != 200:
                    raise StopfinderApiError(
                        f"Failed to get API versions: {response.status}"
                    )
                data = await response.json()
                if isinstance(data, list) and len(data) > 0:
                    self._client_id = data[0].get("clientId")
                    _LOGGER.debug("Got client ID: %s", self._client_id)
                    return self._client_id
                raise StopfinderApiError("Invalid API versions response")
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    async def authenticate(self) -> bool:
        """Authenticate and get client ID."""
        await self._authenticate()
        await self._get_client_id()
        return True

    async def get_schedules(
        self, date_start: datetime | None = None, date_end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Get student schedules."""
        if not self._token:
            _LOGGER.debug("No token, authenticating first")
            await self.authenticate()

        if not self._api_base_url:
            raise StopfinderApiError("API base URL not set")

        if date_start is None:
            date_start = datetime.now()
        if date_end is None:
            date_end = date_start + timedelta(days=7)

        start_str = date_start.strftime("%Y-%m-%d")
        end_str = date_end.strftime("%Y-%m-%d")

        url = f"{self._api_base_url}/students?dateStart={start_str}&dateEnd={end_str}"
        headers = self._get_headers(include_token=True)
        if self._client_id:
            headers["X-Client-Keys"] = self._client_id

        _LOGGER.debug("Fetching schedules from %s to %s", start_str, end_str)
        try:
            async with self._session.get(url, headers=headers, ssl=False) as response:
                if response.status == 200:
                    result = await self._parse_schedule_response(response)
                    _LOGGER.debug(
                        "Fetched schedules: %d students, %d total trips",
                        len(result),
                        sum(len(s.get("trips", [])) for s in result),
                    )
                    return result
                # Any non-200 might be a stale token; re-authenticate and retry
                _LOGGER.debug(
                    "Schedule request failed with status %s, re-authenticating",
                    response.status,
                )
                self._token = None
                await self.authenticate()
                headers = self._get_headers(include_token=True)
                if self._client_id:
                    headers["X-Client-Keys"] = self._client_id
                async with self._session.get(
                    url, headers=headers, ssl=False
                ) as retry_response:
                    if retry_response.status != 200:
                        _LOGGER.error(
                            "Schedule retry also failed with status %s",
                            retry_response.status,
                        )
                        raise StopfinderApiError(
                            f"Failed to get schedules: {retry_response.status}"
                        )
                    result = await self._parse_schedule_response(retry_response)
                    _LOGGER.debug(
                        "Fetched schedules after retry: %d students, %d total trips",
                        len(result),
                        sum(len(s.get("trips", [])) for s in result),
                    )
                    return result
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    @staticmethod
    def _fix_date(time_str: str | None, schedule_date: str) -> str | None:
        """Replace the date portion of a time string with the correct schedule date.

        The API returns times with an incorrect/static date; the real date
        comes from the parent schedule object.
        """
        if not time_str or len(schedule_date) < 10:
            return time_str
        # Replace the date part (first 10 chars) with the schedule date
        if len(time_str) >= 10 and "T" in time_str:
            return schedule_date + time_str[10:]
        return time_str

    @staticmethod
    def _adjust_time(time_str: str | None, adjust_minutes: int) -> str | None:
        """Apply adjustMinutes offset to a time string."""
        if not time_str or adjust_minutes == 0:
            return time_str
        try:
            dt = datetime.fromisoformat(time_str)
            dt += timedelta(minutes=adjust_minutes)
            return dt.isoformat()
        except (ValueError, AttributeError):
            return time_str

    async def _parse_schedule_response(
        self, response: aiohttp.ClientResponse
    ) -> list[dict[str, Any]]:
        """Parse the schedule response."""
        data = await response.json()
        students_by_id: dict[str, dict[str, Any]] = {}

        if isinstance(data, list):
            _LOGGER.debug("Parsing %d day(s) of schedule data", len(data))
            for schedule_data in data:
                schedule_date = schedule_data.get("date", "?")[:10]
                student_schedules = schedule_data.get("studentSchedules", [])
                for student in student_schedules:
                    rider_id = student.get("riderId", "")
                    if rider_id not in students_by_id:
                        students_by_id[rider_id] = {
                            "first_name": student.get("firstName", ""),
                            "last_name": student.get("lastName", ""),
                            "grade": student.get("grade", ""),
                            "school": student.get("school", ""),
                            "rider_id": rider_id,
                            "trips": [],
                        }
                    for trip in student.get("trips", []):
                        adjust = trip.get("adjustMinutes", 0)
                        # Fix dates: API returns wrong date in times,
                        # real date comes from the schedule day object
                        raw_pickup = self._fix_date(
                            trip.get("pickUpTime"), schedule_date
                        )
                        raw_dropoff = self._fix_date(
                            trip.get("dropOffTime"), schedule_date
                        )
                        raw_start = self._fix_date(
                            trip.get("startTime"), schedule_date
                        )
                        raw_finish = self._fix_date(
                            trip.get("finishTime"), schedule_date
                        )
                        adj_pickup = self._adjust_time(raw_pickup, adjust)
                        adj_dropoff = self._adjust_time(raw_dropoff, adjust)
                        _LOGGER.debug(
                            "%s %s: %s toSchool=%s adjust=%d | "
                            "pickup: %s -> %s | dropoff: %s -> %s",
                            schedule_date,
                            student.get("firstName", ""),
                            trip.get("name", ""),
                            trip.get("toSchool"),
                            adjust,
                            raw_pickup,
                            adj_pickup,
                            raw_dropoff,
                            adj_dropoff,
                        )
                        students_by_id[rider_id]["trips"].append(
                            {
                                "name": trip.get("name", ""),
                                "bus_number": trip.get("busNumber", ""),
                                "pickup_time": adj_pickup,
                                "pickup_stop_name": trip.get("pickUpStopName", ""),
                                "dropoff_time": adj_dropoff,
                                "dropoff_stop_name": trip.get("dropOffStopName", ""),
                                "to_school": trip.get("toSchool", False),
                                "vehicle_id": trip.get("vehicleId", ""),
                                "start_time": self._adjust_time(
                                    raw_start, adjust
                                ),
                                "finish_time": self._adjust_time(
                                    raw_finish, adjust
                                ),
                            }
                        )
        return list(students_by_id.values())

    async def test_connection(self) -> bool:
        """Test the connection to the API."""
        try:
            await self.authenticate()
            return True
        except StopfinderApiError:
            return False

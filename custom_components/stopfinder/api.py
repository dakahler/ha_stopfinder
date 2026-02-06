"""Stopfinder API client."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import API_VERSION, APP_VERSION, USER_AGENT


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
        url = f"{self._base_url}/getStopfinder.asp?/email=test"
        try:
            async with self._session.get(
                url, headers=self._get_headers(), ssl=False
            ) as response:
                if response.status != 200:
                    raise StopfinderConnectionError(
                        f"Failed to get Stopfinder URL: {response.status}"
                    )
                data = await response.json()
                if isinstance(data, dict) and "sfApiUri" in data:
                    return data["sfApiUri"]
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
        try:
            async with self._session.post(
                url, json=auth_data, headers=self._get_headers(), ssl=False
            ) as response:
                if response.status == 401:
                    raise StopfinderAuthError("Invalid credentials")
                if response.status != 200:
                    raise StopfinderAuthError(
                        f"Authentication failed: {response.status}"
                    )
                data = await response.json()
                self._token = data.get("token")
                if not self._token:
                    raise StopfinderAuthError("No token in response")
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    async def _get_client_id(self) -> str:
        """Get the client ID from API versions endpoint."""
        if not self._api_base_url:
            self._api_base_url = await self._get_stopfinder_base_url()

        url = f"{self._api_base_url}/systems/apiversions"
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

        try:
            async with self._session.get(url, headers=headers, ssl=False) as response:
                if response.status == 401:
                    # Token expired, re-authenticate
                    await self.authenticate()
                    headers = self._get_headers(include_token=True)
                    if self._client_id:
                        headers["X-Client-Keys"] = self._client_id
                    async with self._session.get(
                        url, headers=headers, ssl=False
                    ) as retry_response:
                        if retry_response.status != 200:
                            raise StopfinderApiError(
                                f"Failed to get schedules: {retry_response.status}"
                            )
                        return await self._parse_schedule_response(retry_response)
                if response.status != 200:
                    raise StopfinderApiError(
                        f"Failed to get schedules: {response.status}"
                    )
                return await self._parse_schedule_response(response)
        except aiohttp.ClientError as err:
            raise StopfinderConnectionError(f"Connection error: {err}") from err

    async def _parse_schedule_response(
        self, response: aiohttp.ClientResponse
    ) -> list[dict[str, Any]]:
        """Parse the schedule response."""
        data = await response.json()
        schedules = []

        if isinstance(data, list):
            for schedule_data in data:
                student_schedules = schedule_data.get("studentSchedules", [])
                for student in student_schedules:
                    schedule = {
                        "first_name": student.get("firstName", ""),
                        "last_name": student.get("lastName", ""),
                        "grade": student.get("grade", ""),
                        "school": student.get("school", ""),
                        "rider_id": student.get("riderId", ""),
                        "trips": [],
                    }
                    for trip in student.get("trips", []):
                        schedule["trips"].append(
                            {
                                "name": trip.get("name", ""),
                                "bus_number": trip.get("busNumber", ""),
                                "pickup_time": trip.get("pickUpTime"),
                                "pickup_stop_name": trip.get("pickUpStopName", ""),
                                "dropoff_time": trip.get("dropOffTime"),
                                "dropoff_stop_name": trip.get("dropOffStopName", ""),
                                "to_school": trip.get("toSchool", False),
                                "vehicle_id": trip.get("vehicleId", ""),
                            }
                        )
                    schedules.append(schedule)
        return schedules

    async def test_connection(self) -> bool:
        """Test the connection to the API."""
        try:
            await self.authenticate()
            return True
        except StopfinderApiError:
            return False

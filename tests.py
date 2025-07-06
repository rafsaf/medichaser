# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# Copyright: (c) 2025, rafsaf - https://github.com/rafsaf/medichaser
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import datetime
import json
import typing
from argparse import Namespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
import requests
from notifiers.exceptions import BadArguments

from medichaser import (
    AppointmentFinder,
    Authenticator,
    InvalidGrantError,
    MFAError,
    NextRun,
    Notifier,
    display_appointments,
    json_date_serializer,
    main,
)
from notifications import (
    gotify_notify,
    pushbullet_notify,
    pushover_notify,
    telegram_notify,
    xmpp_notify,
)


@pytest.fixture(autouse=True)
def fixture_overwrite_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture to overwrite time.sleep to avoid actual delays during tests."""
    monkeypatch.setattr("time.sleep", lambda x: None)


class TestAuthenticator:
    """Test cases for the Authenticator class."""

    def test_init(self) -> None:
        """Test Authenticator initialization."""
        auth = Authenticator("test_user", "test_pass")
        assert auth.username == "test_user"
        assert auth.password == "test_pass"
        assert auth.tokenA is None
        assert auth.tokenR is None
        assert auth.expires_at is None
        assert auth.driver is None
        assert auth.session is not None
        assert "Accept" in auth.headers

    def test_quit_driver_when_none(self) -> None:
        """Test _quit_driver when driver is None."""
        auth = Authenticator("test_user", "test_pass")
        auth._quit_driver()  # Should not raise any exception
        assert auth.driver is None

    def test_quit_driver_when_exists(self) -> None:
        """Test _quit_driver when driver exists."""
        auth = Authenticator("test_user", "test_pass")
        mock_driver = Mock()
        auth.driver = mock_driver
        auth._quit_driver()
        mock_driver.quit.assert_called_once()
        assert auth.driver is None

    def test_refresh_token_no_refresh_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test refresh_token when no refresh token is available."""
        mock_log = Mock()
        monkeypatch.setattr("medichaser.log", mock_log)

        auth = Authenticator("test_user", "test_pass")
        auth.tokenR = None

        auth.refresh_token()
        mock_log.warning.assert_called_once_with(
            "No refresh token available, cannot refresh access token."
        )

    def test_refresh_token_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful token refresh."""
        mock_log = Mock()
        mock_token_path = Mock()
        mock_session = Mock()

        monkeypatch.setattr("medichaser.log", mock_log)
        monkeypatch.setattr("medichaser.time.time", lambda: 1000)
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("test_user", "test_pass")
        auth.tokenR = "test_refresh_token"
        auth.session = mock_session

        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }
        mock_session.post.return_value = mock_response

        # Mock file operations
        mock_token_path.parent.mkdir = Mock()
        mock_token_path.write_text = Mock()

        auth.refresh_token()

        assert auth.tokenA == "new_access_token"
        assert auth.tokenR == "new_refresh_token"
        assert auth.expires_at == 4600  # 1000 + 3600
        assert auth.headers["Authorization"] == "Bearer new_access_token"

    def test_refresh_token_invalid_grant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test refresh_token with invalid grant error."""
        mock_log = Mock()
        mock_token_path = Mock()
        mock_session = Mock()

        monkeypatch.setattr("medichaser.log", mock_log)
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("test_user", "test_pass")
        auth.tokenR = "invalid_refresh_token"
        auth.session = mock_session

        # Mock error response
        mock_response = Mock()
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_session.post.return_value = mock_response

        mock_token_path.exists.return_value = True
        mock_token_path.unlink = Mock()

        with pytest.raises(InvalidGrantError, match="Invalid grant"):
            auth.refresh_token()

        mock_token_path.unlink.assert_called_once()

    def test_init_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test the _init_driver method."""
        mock_chrome = MagicMock()
        monkeypatch.setattr("selenium.webdriver.Chrome", mock_chrome)
        mock_stealth = MagicMock()
        monkeypatch.setattr("medichaser.stealth", mock_stealth)

        auth = Authenticator("user", "pass")
        driver = auth._init_driver()

        mock_chrome.assert_called_once()
        mock_stealth.assert_called_once()
        assert driver is not None
        assert "User-Agent" in auth.headers

    def test_get_or_create_device_id_no_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _get_or_create_device_id when no file exists."""
        mock_device_id_path = Mock()
        mock_device_id_path.exists.return_value = False
        mock_device_id_path.write_text = Mock()
        monkeypatch.setattr("medichaser.DEVICE_ID_PATH", mock_device_id_path)
        mock_uuid = Mock()
        mock_uuid.uuid4.return_value = "new-device-id"
        monkeypatch.setattr("medichaser.uuid", mock_uuid)

        # We need to call __init__ after patching
        auth = Authenticator("user", "pass")

        assert auth.device_id == "new-device-id"
        mock_device_id_path.write_text.assert_called_once()

    def test_get_or_create_device_id_file_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _get_or_create_device_id when file exists."""
        mock_device_id_path = Mock()
        mock_device_id_path.exists.return_value = True
        mock_device_id_path.read_text.return_value = (
            '{"device_id": "existing-device-id"}'
        )
        monkeypatch.setattr("medichaser.DEVICE_ID_PATH", mock_device_id_path)

        auth = Authenticator("user", "pass")

        assert auth.device_id == "existing-device-id"

    def test_get_or_create_device_id_corrupted_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _get_or_create_device_id with a corrupted file."""
        mock_log = Mock()
        mock_device_id_path = Mock()
        mock_device_id_path.exists.return_value = True
        mock_device_id_path.read_text.return_value = "not a json"
        mock_device_id_path.write_text = Mock()
        monkeypatch.setattr("medichaser.DEVICE_ID_PATH", mock_device_id_path)
        monkeypatch.setattr("medichaser.log", mock_log)
        mock_uuid = Mock()
        mock_uuid.uuid4.return_value = "new-device-id-after-corruption"
        monkeypatch.setattr("medichaser.uuid", mock_uuid)

        auth = Authenticator("user", "pass")

        assert auth.device_id == "new-device-id-after-corruption"
        mock_log.warning.assert_called()
        mock_device_id_path.write_text.assert_called_once()

    def test_load_token_from_storage_no_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _load_token_from_storage when no token file exists."""
        mock_token_path = Mock()
        mock_token_path.exists.return_value = False
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("user", "pass")
        assert not auth._load_token_from_storage()

    def test_load_token_from_storage_valid_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _load_token_from_storage with a valid, non-expired token."""
        mock_token_path = Mock()
        mock_token_path.exists.return_value = True
        token_data = {
            "access_token": "valid_access",
            "refresh_token": "valid_refresh",
            "expires_at": 9999999999,  # Far in the future
        }
        mock_token_path.read_text.return_value = json.dumps(token_data)
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("user", "pass")
        assert auth._load_token_from_storage()
        assert auth.tokenA == "valid_access"
        assert auth.tokenR == "valid_refresh"
        assert auth.headers["Authorization"] == "Bearer valid_access"

    def test_load_token_from_storage_expired_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _load_token_from_storage with an expired token."""
        mock_token_path = Mock()
        mock_token_path.exists.return_value = True
        token_data = {
            "access_token": "expired_access",
            "refresh_token": "expired_refresh",
            "expires_at": 1000,  # In the past
        }
        mock_token_path.read_text.return_value = json.dumps(token_data)
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)
        monkeypatch.setattr("medichaser.time.time", lambda: 2000)

        auth = Authenticator("user", "pass")
        assert not auth._load_token_from_storage()

    def test_load_token_from_storage_corrupted_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _load_token_from_storage with a corrupted JSON file."""
        mock_token_path = Mock()
        mock_token_path.exists.return_value = True
        mock_token_path.read_text.return_value = "invalid json"
        mock_token_path.unlink = Mock()
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("user", "pass")
        assert not auth._load_token_from_storage()
        mock_token_path.unlink.assert_called_once()

    def test_load_token_from_storage_incomplete_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test _load_token_from_storage with incomplete token data."""
        mock_token_path = Mock()
        mock_token_path.exists.return_value = True
        token_data = {"access_token": "only_access"}  # Missing other keys
        mock_token_path.read_text.return_value = json.dumps(token_data)
        mock_token_path.unlink = Mock()
        monkeypatch.setattr("medichaser.TOKEN_PATH", mock_token_path)

        auth = Authenticator("user", "pass")
        assert not auth._load_token_from_storage()
        mock_token_path.unlink.assert_called_once()

    def test_login_with_valid_stored_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test the main login orchestrator with a valid stored token."""
        auth = Authenticator("user", "pass")
        mock_load_token = Mock(return_value=True)
        monkeypatch.setattr(auth, "_load_token_from_storage", mock_load_token)

        auth.login()
        mock_load_token.assert_called_once()

    def test_login_with_refresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test the main login orchestrator with a successful token refresh."""
        auth = Authenticator("user", "pass")
        # First call to load is False, second is True after refresh
        mock_load_token = Mock(side_effect=[False, True])
        mock_refresh = Mock()
        monkeypatch.setattr(auth, "_load_token_from_storage", mock_load_token)
        monkeypatch.setattr(auth, "refresh_token", mock_refresh)

        auth.login()
        assert mock_load_token.call_count == 2
        mock_refresh.assert_called_once()

    def test_login_fallback_to_selenium_no_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test login falls back to Selenium when requests login fails."""
        auth = Authenticator("user", "pass")
        mock_load_token = Mock(return_value=False)
        mock_refresh = Mock()
        mock_login_requests = Mock(side_effect=Exception("requests failed"))
        mock_login_selenium = Mock()

        monkeypatch.setattr(auth, "_load_token_from_storage", mock_load_token)
        monkeypatch.setattr(auth, "refresh_token", mock_refresh)
        monkeypatch.setattr(auth, "login_requests", mock_login_requests)
        monkeypatch.setattr(auth, "login_selenium", mock_login_selenium)
        monkeypatch.setenv("EXPERIMENTAL_SELENIUM_LOGIN", "1")

        auth.login()

        mock_load_token.assert_called_once()
        mock_refresh.assert_not_called()
        mock_login_requests.assert_not_called()
        mock_login_selenium.assert_called_once()

    def test_login_fallback_to_selenium_invalid_grant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test login falls back to Selenium when requests login fails."""
        auth = Authenticator("user", "pass")
        mock_load_token = Mock(return_value=True)
        mock_refresh = Mock(side_effect=InvalidGrantError)
        mock_login_requests = Mock(side_effect=Exception("requests failed"))
        mock_login_selenium = Mock()

        monkeypatch.setattr(auth, "_load_token_from_storage", mock_load_token)
        monkeypatch.setattr(auth, "refresh_token", mock_refresh)
        monkeypatch.setattr(auth, "login_requests", mock_login_requests)
        monkeypatch.setattr(auth, "login_selenium", mock_login_selenium)
        monkeypatch.setenv("EXPERIMENTAL_SELENIUM_LOGIN", "1")

        auth.login()

        mock_load_token.assert_called_once()
        mock_refresh.assert_called_once()
        mock_login_requests.assert_not_called()
        mock_login_selenium.assert_called_once()

    def test_login_method_selenium(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that login uses Selenium when specified."""
        auth = Authenticator("user", "pass")
        monkeypatch.setenv("EXPERIMENTAL_SELENIUM_LOGIN", "1")

        mock_load_token = Mock(return_value=False)
        mock_refresh = Mock(side_effect=InvalidGrantError)
        mock_login_selenium = Mock()

        monkeypatch.setattr(auth, "_load_token_from_storage", mock_load_token)
        monkeypatch.setattr(auth, "refresh_token", mock_refresh)
        monkeypatch.setattr(auth, "login_selenium", mock_login_selenium)

        auth.login()

        mock_login_selenium.assert_called_once()


class TestAppointmentFinder:
    """Test cases for the AppointmentFinder class."""

    def test_init(self) -> None:
        """Test AppointmentFinder initialization."""
        mock_session = Mock()
        headers: dict[str, str] = {"Authorization": "Bearer test_token"}

        finder = AppointmentFinder(mock_session, headers)
        assert finder.session == mock_session
        assert finder.headers == headers

    def test_http_get_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful HTTP GET request."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test_data"}
        mock_session.get.return_value = mock_response

        finder = AppointmentFinder(mock_session, {"test": "header"})
        result = finder.http_get("http://test.com", {"param": "value"})

        assert result == {"data": "test_data"}
        mock_session.get.assert_called_once_with(
            "http://test.com", headers={"test": "header"}, params={"param": "value"}
        )

    def test_http_get_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test HTTP GET request with error response."""
        mock_log = Mock()
        monkeypatch.setattr("medichaser.log", mock_log)

        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.get.return_value = mock_response

        finder = AppointmentFinder(mock_session, {"test": "header"})
        result = finder.http_get("http://test.com", {"param": "value"})

        assert result == {}
        mock_log.error.assert_called_once_with("Error 500: Internal Server Error")

    def test_find_appointments_basic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test basic appointment finding."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})
        mock_http_get = Mock(return_value={"items": [{"id": 1}, {"id": 2}]})
        monkeypatch.setattr(finder, "http_get", mock_http_get)

        start_date = datetime.date(2025, 1, 1)
        result = finder.find_appointments(
            region=1,
            specialty=[2],
            clinic=3,
            start_date=start_date,
            end_date=None,
            language=None,
            doctor=None,
        )

        assert result == [{"id": 1}, {"id": 2}]
        mock_http_get.assert_called_once()

    def test_find_appointments_with_filters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test appointment finding with all filters."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})
        mock_http_get = Mock(return_value={"items": [{"id": 1}]})
        monkeypatch.setattr(finder, "http_get", mock_http_get)

        start_date = datetime.date(2025, 1, 1)
        result = finder.find_appointments(
            region=1,
            specialty=[2],
            clinic=3,
            start_date=start_date,
            end_date=None,
            language=4,
            doctor=5,
        )

        assert result == [{"id": 1}]
        # Verify that the correct parameters were passed
        call_args = mock_http_get.call_args
        assert call_args is not None
        params: dict[str, Any] = call_args.args[1]
        assert "DoctorLanguageIds" in params
        assert "DoctorIds" in params

    def test_find_appointments_with_end_date_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test appointment finding with end date filtering."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})

        # Mock appointments with different dates
        mock_appointments: list[dict[str, Any]] = [
            {"id": 1, "appointmentDate": "2025-01-01T10:00:00"},
            {"id": 2, "appointmentDate": "2025-01-15T10:00:00"},
            {"id": 3, "appointmentDate": "2025-02-01T10:00:00"},
        ]
        mock_http_get = Mock(return_value={"items": mock_appointments})
        monkeypatch.setattr(finder, "http_get", mock_http_get)

        start_date = datetime.date(2025, 1, 1)
        end_date = datetime.date(2025, 1, 20)

        result = finder.find_appointments(
            region=1,
            specialty=[2],
            clinic=3,
            start_date=start_date,
            end_date=end_date,
            language=None,
            doctor=None,
        )

        # Should only return appointments within the date range
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_find_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test finding filters."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})
        mock_http_get = Mock(return_value={"regions": [{"id": 1}]})
        monkeypatch.setattr(finder, "http_get", mock_http_get)

        result = finder.find_filters(region=1, specialty=[2])

        assert result == {"regions": [{"id": 1}]}
        mock_http_get.assert_called_once()


class TestNotifier:
    """Test cases for the Notifier class."""

    def test_format_appointments_empty(self) -> None:
        """Test formatting empty appointments list."""
        result = Notifier.format_appointments([])
        assert result == "No appointments found."

    def test_format_appointments_single(self) -> None:
        """Test formatting single appointment."""
        appointments: list[dict[str, Any]] = [
            {
                "appointmentDate": "2025-01-01T10:00:00",
                "clinic": {"name": "Test Clinic"},
                "doctor": {"name": "Dr. Test"},
                "specialty": {"name": "Cardiology"},
                "doctorLanguages": [{"name": "English"}, {"name": "Polish"}],
            }
        ]

        result = Notifier.format_appointments(appointments)

        assert "Date: 2025-01-01T10:00:00" in result
        assert "Clinic: Test Clinic" in result
        assert "Doctor: Dr. Test" in result
        assert "Specialty: Cardiology" in result
        assert "Languages: English, Polish" in result

    def test_format_appointments_multiple(self) -> None:
        """Test formatting multiple appointments."""
        appointments: list[dict[str, Any]] = [
            {
                "appointmentDate": "2025-01-01T10:00:00",
                "clinic": {"name": "Clinic 1"},
                "doctor": {"name": "Dr. One"},
                "specialty": {"name": "Cardiology"},
                "doctorLanguages": [],
            },
            {
                "appointmentDate": "2025-01-02T11:00:00",
                "clinic": {"name": "Clinic 2"},
                "doctor": {"name": "Dr. Two"},
                "specialty": {"name": "Neurology"},
                "doctorLanguages": [{"name": "Polish"}],
            },
        ]

        result = Notifier.format_appointments(appointments)

        assert "Clinic 1" in result
        assert "Clinic 2" in result
        assert "Dr. One" in result
        assert "Dr. Two" in result
        assert "Languages: N/A" in result  # First appointment has no languages
        assert "Languages: Polish" in result  # Second appointment has Polish

    def test_send_notification_pushbullet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test sending notification via pushbullet."""
        mock_pushbullet = Mock()
        monkeypatch.setattr("medichaser.pushbullet_notify", mock_pushbullet)

        appointments: list[dict[str, Any]] = [
            {"appointmentDate": "2025-01-01T10:00:00"}
        ]
        Notifier.send_notification(appointments, "pushbullet", "Test Title")

        mock_pushbullet.assert_called_once()
        args, kwargs = mock_pushbullet.call_args
        assert "Test Title" in kwargs or "Test Title" in args

    def test_send_notification_telegram(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sending notification via telegram."""
        mock_telegram = Mock()
        monkeypatch.setattr("medichaser.telegram_notify", mock_telegram)

        appointments: list[dict[str, Any]] = [
            {"appointmentDate": "2025-01-01T10:00:00"}
        ]
        Notifier.send_notification(appointments, "telegram", "Test Title")

        mock_telegram.assert_called_once()


class TestNextRun:
    """Test cases for the NextRun class."""

    def test_init_default(self) -> None:
        """Test NextRun initialization with default interval."""
        next_run = NextRun()
        assert next_run.interval_minutes == 60
        assert isinstance(next_run.next_run, datetime.datetime)

    def test_init_custom_interval(self) -> None:
        """Test NextRun initialization with custom interval."""
        next_run = NextRun(30)
        assert next_run.interval_minutes == 30

    def test_init_none_interval(self) -> None:
        """Test NextRun initialization with None interval."""
        next_run = NextRun(None)
        assert next_run.interval_minutes is None

    def test_is_time_to_run_none_interval(self) -> None:
        """Test is_time_to_run with None interval."""
        next_run = NextRun(None)
        assert next_run.is_time_to_run() is True

    def test_is_time_to_run_future(self) -> None:
        """Test is_time_to_run when next run is in future."""
        next_run = NextRun(60)
        next_run.next_run = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
            minutes=30
        )
        assert next_run.is_time_to_run() is False

    def test_is_time_to_run_past(self) -> None:
        """Test is_time_to_run when next run is in past."""
        next_run = NextRun(60)
        next_run.next_run = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
            minutes=30
        )
        assert next_run.is_time_to_run() is True

    def test_set_next_run_none_interval(self) -> None:
        """Test set_next_run with None interval."""
        next_run = NextRun(None)
        original_next_run = next_run.next_run
        next_run.set_next_run()
        assert next_run.next_run == original_next_run

    def test_set_next_run_with_interval(self) -> None:
        """Test set_next_run with interval."""
        next_run = NextRun(30)
        old_next_run = next_run.next_run
        next_run.set_next_run()
        assert next_run.next_run > old_next_run


class TestUtilityFunctions:
    """Test cases for utility functions."""

    def test_json_date_serializer_date(self) -> None:
        """Test JSON serializer with date object."""
        test_date = datetime.date(2025, 1, 1)
        result = json_date_serializer(test_date)
        assert result == "2025-01-01"

    def test_json_date_serializer_datetime(self) -> None:
        """Test JSON serializer with datetime object."""
        test_datetime = datetime.datetime(2025, 1, 1, 12, 30, 45)
        result = json_date_serializer(test_datetime)
        assert result == "2025-01-01T12:30:45"

    def test_json_date_serializer_invalid_type(self) -> None:
        """Test JSON serializer with invalid type."""
        with pytest.raises(TypeError, match="not JSON serializable"):
            json_date_serializer("not a date")

    def test_display_appointments_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test display_appointments with empty list."""
        mock_log = Mock()
        monkeypatch.setattr("medichaser.log", mock_log)

        display_appointments([])

        mock_log.info.assert_any_call("No new appointments found.")

    def test_display_appointments_with_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test display_appointments with appointment data."""
        mock_log = Mock()
        monkeypatch.setattr("medichaser.log", mock_log)

        appointments: list[dict[str, Any]] = [
            {
                "appointmentDate": "2025-01-01T10:00:00",
                "clinic": {"name": "Test Clinic"},
                "doctor": {"name": "Dr. Test"},
                "specialty": {"name": "Cardiology"},
                "doctorLanguages": [{"name": "English"}],
            }
        ]

        display_appointments(appointments)

        mock_log.info.assert_any_call("New appointments found:")
        mock_log.info.assert_any_call("Date: 2025-01-01T10:00:00")


class TestNotificationFunctions:
    """Test cases for notification functions."""

    def test_pushbullet_notify_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful pushbullet notification."""
        mock_pushbullet = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_pushbullet.notify.return_value = mock_result

        monkeypatch.setattr("notifications.pushbullet", mock_pushbullet)

        pushbullet_notify("Test message", "Test title")

        mock_pushbullet.notify.assert_called_once_with(
            message="Test message", title="Test title"
        )

    def test_pushbullet_notify_no_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pushbullet notification without title."""
        mock_pushbullet = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_pushbullet.notify.return_value = mock_result

        monkeypatch.setattr("notifications.pushbullet", mock_pushbullet)

        pushbullet_notify("Test message")

        mock_pushbullet.notify.assert_called_once_with(message="Test message")

    def test_pushbullet_notify_bad_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test pushbullet notification with bad arguments."""
        mock_pushbullet = Mock()
        mock_pushbullet.notify.side_effect = BadArguments("Invalid token")
        mock_print = Mock()

        monkeypatch.setattr("notifications.pushbullet", mock_pushbullet)
        monkeypatch.setattr("builtins.print", mock_print)

        pushbullet_notify("Test message")

        mock_print.assert_called_once()
        assert "Pushbullet failed" in mock_print.call_args[0][0]

    def test_pushbullet_notify_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pushbullet notification failure."""
        mock_pushbullet = Mock()
        mock_result = Mock()
        mock_result.status = "Failed"
        mock_result.errors = ["Error message"]
        mock_pushbullet.notify.return_value = mock_result
        mock_print = Mock()

        monkeypatch.setattr("notifications.pushbullet", mock_pushbullet)
        monkeypatch.setattr("builtins.print", mock_print)

        pushbullet_notify("Test message")

        mock_print.assert_called_once()
        assert "Pushbullet notification failed" in mock_print.call_args[0][0]

    def test_pushover_notify_no_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pushover notification without title."""
        mock_pushover = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_pushover.notify.return_value = mock_result

        monkeypatch.setattr("notifications.pushover", mock_pushover)

        pushover_notify("Test message")

        mock_pushover.notify.assert_called_once_with(message="Test message")

    def test_pushover_notify_bad_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test pushover notification with bad arguments."""
        mock_pushover = Mock()
        mock_pushover.notify.side_effect = BadArguments("Invalid token")
        mock_print = Mock()

        monkeypatch.setattr("notifications.pushover", mock_pushover)
        monkeypatch.setattr("builtins.print", mock_print)

        pushover_notify("Test message")

        mock_print.assert_called_once()
        assert "Pushover failed" in mock_print.call_args[0][0]

    def test_pushover_notify_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pushover notification failure."""
        mock_pushover = Mock()
        mock_result = Mock()
        mock_result.status = "Failed"
        mock_result.errors = ["Error message"]
        mock_pushover.notify.return_value = mock_result
        mock_print = Mock()

        monkeypatch.setattr("notifications.pushover", mock_pushover)
        monkeypatch.setattr("builtins.print", mock_print)

        pushover_notify("Test message")

        mock_print.assert_called_once()
        assert "Pushover notification failed" in mock_print.call_args[0][0]

    def test_telegram_notify_bad_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test telegram notification with bad arguments."""
        mock_telegram = Mock()
        mock_telegram.notify.side_effect = BadArguments("Invalid chat id")
        mock_print = Mock()

        monkeypatch.setattr("notifications.telegram", mock_telegram)
        monkeypatch.setattr("builtins.print", mock_print)

        telegram_notify("Test message")

        mock_print.assert_called_once()
        assert "Telegram notifications require" in mock_print.call_args[0][0]

    def test_telegram_notify_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test telegram notification failure."""
        mock_telegram = Mock()
        mock_result = Mock()
        mock_result.status = "Failed"
        mock_result.errors = ["Error message"]
        mock_telegram.notify.return_value = mock_result
        mock_print = Mock()

        monkeypatch.setattr("notifications.telegram", mock_telegram)
        monkeypatch.setattr("builtins.print", mock_print)

        telegram_notify("Test message")

        mock_print.assert_called_once()
        assert "Telegram notification failed" in mock_print.call_args[0][0]

    def test_xmpp_notify_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test XMPP notification with send failure."""
        mock_environ: dict[str, str] = {
            "NOTIFIERS_XMPP_JID": "user@example.com",
            "NOTIFIERS_XMPP_PASSWORD": "password",
            "NOTIFIERS_XMPP_RECEIVER": "receiver@example.com",
        }
        mock_xmpp = Mock()
        mock_jid = Mock()
        mock_jid.getDomain.return_value = "example.com"
        mock_jid.getNode.return_value = "user"
        mock_jid.getResource.return_value = "resource"
        mock_xmpp.protocol.JID.return_value = mock_jid

        mock_client = Mock()
        mock_client.connect.return_value = True
        mock_client.auth.return_value = True
        mock_client.send.return_value = False  # Simulate send failure
        mock_xmpp.Client.return_value = mock_client
        mock_print = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("notifications.xmpp", mock_xmpp)
        monkeypatch.setattr("builtins.print", mock_print)

        xmpp_notify("Test message")

        mock_client.connect.assert_called_once()
        mock_client.auth.assert_called_once()
        mock_client.send.assert_called_once()
        mock_print.assert_called_once_with("XMPP notification failed")

    def test_pushover_notify_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful pushover notification."""
        mock_pushover = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_pushover.notify.return_value = mock_result

        monkeypatch.setattr("notifications.pushover", mock_pushover)

        pushover_notify("Test message", "Test title")

        mock_pushover.notify.assert_called_once_with(
            message="Test message", title="Test title"
        )

    def test_telegram_notify_with_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test telegram notification with title."""
        mock_telegram = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_telegram.notify.return_value = mock_result

        monkeypatch.setattr("notifications.telegram", mock_telegram)

        telegram_notify("Test message", "Test title")

        mock_telegram.notify.assert_called_once_with(
            message="<b>Test title</b>\nTest message", parse_mode="html"
        )

    def test_telegram_notify_without_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test telegram notification without title."""
        mock_telegram = Mock()
        mock_result = Mock()
        mock_result.status = "Success"
        mock_telegram.notify.return_value = mock_result

        monkeypatch.setattr("notifications.telegram", mock_telegram)

        telegram_notify("Test message")

        mock_telegram.notify.assert_called_once_with(
            message="Test message", parse_mode="html"
        )

    def test_xmpp_notify_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful XMPP notification."""
        mock_environ: dict[str, str] = {
            "NOTIFIERS_XMPP_JID": "user@example.com",
            "NOTIFIERS_XMPP_PASSWORD": "password",
            "NOTIFIERS_XMPP_RECEIVER": "receiver@example.com",
        }
        mock_xmpp = Mock()
        mock_jid = Mock()
        mock_jid.getDomain.return_value = "example.com"
        mock_jid.getNode.return_value = "user"
        mock_jid.getResource.return_value = "resource"
        mock_xmpp.protocol.JID.return_value = mock_jid

        mock_client = Mock()
        mock_client.connect.return_value = True
        mock_client.auth.return_value = True
        mock_client.send.return_value = True
        mock_xmpp.Client.return_value = mock_client

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("notifications.xmpp", mock_xmpp)

        xmpp_notify("Test message")

        mock_client.connect.assert_called_once()
        mock_client.auth.assert_called_once()
        mock_client.send.assert_called_once()

    def test_xmpp_notify_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test XMPP notification with missing environment variables."""
        mock_environ: dict[str, str] = {}
        mock_print = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("builtins.print", mock_print)

        xmpp_notify("Test message")

        mock_print.assert_called_once()
        assert "XMPP notifications require" in mock_print.call_args[0][0]

    def test_gotify_notify_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful Gotify notification."""
        mock_environ: dict[str, str] = {
            "GOTIFY_HOST": "http://localhost:8080",
            "GOTIFY_TOKEN": "test_token",
            "GOTIFY_PRIORITY": "5",
        }
        mock_requests = Mock()
        mock_requests.post.return_value = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("notifications.requests", mock_requests)

        gotify_notify("Test message", "Test title")

        mock_requests.post.assert_called_once_with(
            "http://localhost:8080/message?token=test_token",
            json={"message": "Test message", "priority": 5, "title": "Test title"},
        )

    def test_gotify_notify_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Gotify notification with missing environment variables."""
        mock_environ: dict[str, str] = {}
        mock_print = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("builtins.print", mock_print)

        gotify_notify("Test message")

        mock_print.assert_called_once()
        assert "GOTIFY notifications require" in mock_print.call_args[0][0]

    def test_gotify_notify_default_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Gotify notification with default priority."""
        mock_environ: dict[str, str] = {
            "GOTIFY_HOST": "http://localhost:8080",
            "GOTIFY_TOKEN": "test_token",
        }
        mock_requests = Mock()
        mock_requests.post.return_value = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("notifications.requests", mock_requests)

        gotify_notify("Test message")

        mock_requests.post.assert_called_once_with(
            "http://localhost:8080/message?token=test_token",
            json={"message": "Test message", "priority": 5, "title": "medihunter"},
        )

    def test_gotify_notify_request_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Gotify notification with request exception."""
        mock_environ = {
            "GOTIFY_HOST": "http://localhost:8080",
            "GOTIFY_TOKEN": "test_token",
        }
        mock_requests = Mock()
        mock_requests.post.side_effect = requests.exceptions.RequestException(
            "Connection error"
        )
        mock_requests.exceptions = requests.exceptions
        mock_print = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("notifications.requests", mock_requests)
        monkeypatch.setattr("builtins.print", mock_print)

        gotify_notify("Test message")

        mock_print.assert_called_once()
        assert "GOTIFY notification failed" in mock_print.call_args[0][0]


class TestExceptions:
    """Test cases for custom exceptions."""

    def test_invalid_grant_error(self) -> None:
        """Test InvalidGrantError exception."""
        with pytest.raises(InvalidGrantError, match="Test error"):
            raise InvalidGrantError("Test error")

    def test_mfa_error(self) -> None:
        """Test MFAError exception."""
        with pytest.raises(MFAError, match="Test MFA Error"):
            raise MFAError("Test MFA Error")


def test_main_find_appointment_single_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main function for a single run of find-appointment."""
    mock_args = Namespace(
        command="find-appointment",
        region=1,
        specialty=[2],
        clinic=3,
        doctor=4,
        language=6,
        date=datetime.date(2025, 1, 1),
        enddate=datetime.date(2025, 1, 31),
        interval=None,
        notification="pushbullet",
        title="Test",
    )

    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = mock_args
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)

    monkeypatch.setattr(
        "os.environ", {"MEDICOVER_USER": "user", "MEDICOVER_PASS": "pass"}
    )

    mock_auth_instance = MagicMock()
    monkeypatch.setattr("medichaser.Authenticator", lambda u, p: mock_auth_instance)

    mock_finder_instance = MagicMock()
    mock_finder_instance.find_appointments.return_value = [
        {"id": 1, "name": "Appointment"}
    ]
    monkeypatch.setattr(
        "medichaser.AppointmentFinder", lambda s, h: mock_finder_instance
    )

    mock_notifier = MagicMock()
    monkeypatch.setattr("medichaser.Notifier.send_notification", mock_notifier)

    mock_display = MagicMock()
    monkeypatch.setattr("medichaser.display_appointments", mock_display)

    monkeypatch.setattr("time.sleep", lambda t: None)

    main()

    mock_auth_instance.login.assert_called_once()
    mock_auth_instance.refresh_token.assert_called_once()
    mock_finder_instance.find_appointments.assert_called_once_with(
        1, [2], 3, datetime.date(2025, 1, 1), datetime.date(2025, 1, 31), 6, 4
    )
    mock_display.assert_called_once_with([{"id": 1, "name": "Appointment"}])
    mock_notifier.assert_called_once_with(
        [{"id": 1, "name": "Appointment"}], "pushbullet", "Test"
    )


def test_main_list_filters_regions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main function for list-filters regions."""
    mock_args = Namespace(
        command="list-filters",
        filter_type="regions",
        region=None,
        specialty=None,
        notification=None,
    )

    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = mock_args
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)

    monkeypatch.setattr(
        "os.environ", {"MEDICOVER_USER": "user", "MEDICOVER_PASS": "pass"}
    )

    mock_auth_instance = MagicMock()
    monkeypatch.setattr("medichaser.Authenticator", lambda u, p: mock_auth_instance)

    mock_finder_instance = MagicMock()
    mock_finder_instance.find_filters.return_value = {
        "regions": [{"id": 1, "value": "Region 1"}]
    }
    monkeypatch.setattr(
        "medichaser.AppointmentFinder", lambda s, h: mock_finder_instance
    )

    mock_log = MagicMock()
    monkeypatch.setattr("medichaser.log", mock_log)
    monkeypatch.setattr("time.sleep", lambda t: None)

    main()

    mock_auth_instance.login.assert_called_once()
    mock_auth_instance.refresh_token.assert_called_once()
    mock_finder_instance.find_filters.assert_called_once_with()
    mock_log.info.assert_called_with("1 - Region 1")


def test_main_list_filters_doctors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main function for list-filters doctors."""
    mock_args = Namespace(
        command="list-filters",
        filter_type="doctors",
        region=1,
        specialty=2,
        notification=None,
    )

    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = mock_args
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)

    monkeypatch.setattr(
        "os.environ", {"MEDICOVER_USER": "user", "MEDICOVER_PASS": "pass"}
    )

    mock_auth_instance = MagicMock()
    monkeypatch.setattr("medichaser.Authenticator", lambda u, p: mock_auth_instance)

    mock_finder_instance = MagicMock()
    mock_finder_instance.find_filters.return_value = {
        "doctors": [{"id": 1, "value": "Doctor 1"}]
    }
    monkeypatch.setattr(
        "medichaser.AppointmentFinder", lambda s, h: mock_finder_instance
    )

    mock_log = MagicMock()
    monkeypatch.setattr("medichaser.log", mock_log)
    monkeypatch.setattr("time.sleep", lambda t: None)

    main()

    mock_auth_instance.login.assert_called_once()
    mock_auth_instance.refresh_token.assert_called_once()
    mock_finder_instance.find_filters.assert_called_once_with(1, 2)
    mock_log.info.assert_called_with("1 - Doctor 1")


def test_main_missing_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main function with missing environment variables."""
    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = Namespace(command="find-appointment")
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)
    monkeypatch.setattr("os.environ", {})
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1


def test_main_find_appointment_interval_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main function for an interval run of find-appointment."""
    mock_args = Namespace(
        command="find-appointment",
        region=1,
        specialty=[2],
        clinic=3,
        doctor=4,
        language=6,
        date=datetime.date(2025, 1, 1),
        enddate=datetime.date(2025, 1, 31),
        interval=10,
        notification="pushover",
        title="Interval Test",
    )

    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = mock_args
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)

    monkeypatch.setattr(
        "os.environ", {"MEDICOVER_USER": "user", "MEDICOVER_PASS": "pass"}
    )

    mock_auth_instance = MagicMock()
    mock_auth_instance.refresh_token.side_effect = [InvalidGrantError, None, None, None]
    monkeypatch.setattr("medichaser.Authenticator", lambda u, p: mock_auth_instance)

    mock_finder_instance = MagicMock()
    mock_finder_instance.find_appointments.side_effect = [
        [{"id": 1, "name": "Appointment 1"}],
        [
            {"id": 1, "name": "Appointment 1"},
            {"id": 2, "name": "Appointment 2"},
        ],
    ]
    monkeypatch.setattr(
        "medichaser.AppointmentFinder", lambda s, h: mock_finder_instance
    )

    mock_notifier = MagicMock()
    monkeypatch.setattr("medichaser.Notifier.send_notification", mock_notifier)

    mock_display = MagicMock()
    monkeypatch.setattr("medichaser.display_appointments", mock_display)

    run_count = 0

    def mock_is_time_to_run() -> typing.Literal[True]:
        nonlocal run_count
        run_count += 1
        if run_count > 2:
            raise StopIteration  # End the test
        return True

    mock_next_run_instance = MagicMock()
    mock_next_run_instance.is_time_to_run.side_effect = mock_is_time_to_run
    monkeypatch.setattr("medichaser.NextRun", lambda i: mock_next_run_instance)

    monkeypatch.setattr("time.sleep", lambda t: None)

    with pytest.raises(StopIteration):
        main()

    assert mock_auth_instance.login.call_count == 2
    assert mock_auth_instance.refresh_token.call_count == 4
    assert mock_finder_instance.find_appointments.call_count == 2

    mock_display.assert_any_call([{"id": 1, "name": "Appointment 1"}])
    mock_notifier.assert_any_call(
        [{"id": 1, "name": "Appointment 1"}], "pushover", "Interval Test"
    )

    mock_display.assert_any_call([{"id": 2, "name": "Appointment 2"}])
    mock_notifier.assert_any_call(
        [{"id": 2, "name": "Appointment 2"}], "pushover", "Interval Test"
    )


def test_main_list_filters_clinics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the main function for list-filters clinics."""
    mock_args = Namespace(
        command="list-filters",
        filter_type="clinics",
        region=1,
        specialty=[2, 3],
        notification=None,
    )

    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = mock_args
    monkeypatch.setattr("argparse.ArgumentParser", lambda **kwargs: mock_parser)

    monkeypatch.setattr(
        "os.environ", {"MEDICOVER_USER": "user", "MEDICOVER_PASS": "pass"}
    )

    mock_auth_instance = MagicMock()
    monkeypatch.setattr("medichaser.Authenticator", lambda u, p: mock_auth_instance)

    mock_finder_instance = MagicMock()
    mock_finder_instance.find_filters.return_value = {
        "clinics": [{"id": 1, "value": "Clinic 1"}]
    }
    monkeypatch.setattr(
        "medichaser.AppointmentFinder", lambda s, h: mock_finder_instance
    )

    mock_log = MagicMock()
    monkeypatch.setattr("medichaser.log", mock_log)
    monkeypatch.setattr("time.sleep", lambda t: None)

    main()

    mock_auth_instance.login.assert_called_once()
    mock_auth_instance.refresh_token.assert_called_once()
    mock_finder_instance.find_filters.assert_called_once_with(1, [2, 3])
    mock_log.info.assert_called_with("1 - Clinic 1")

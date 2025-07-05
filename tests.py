import datetime
from unittest.mock import Mock

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
)
from notifications import (
    gotify_notify,
    pushbullet_notify,
    pushover_notify,
    telegram_notify,
    xmpp_notify,
)


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


class TestAppointmentFinder:
    """Test cases for the AppointmentFinder class."""

    def test_init(self) -> None:
        """Test AppointmentFinder initialization."""
        mock_session = Mock()
        headers = {"Authorization": "Bearer test_token"}

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

    def test_find_appointments_basic(self) -> None:
        """Test basic appointment finding."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})

        # Mock the http_get method
        finder.http_get = Mock(return_value={"items": [{"id": 1}, {"id": 2}]})

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
        finder.http_get.assert_called_once()

    def test_find_appointments_with_filters(self) -> None:
        """Test appointment finding with all filters."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})

        # Mock the http_get method
        finder.http_get = Mock(return_value={"items": [{"id": 1}]})

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
        call_args = finder.http_get.call_args
        assert call_args is not None
        params = call_args.args[1]
        assert "DoctorLanguageIds" in params
        assert "DoctorIds" in params

    def test_find_appointments_with_end_date_filter(self) -> None:
        """Test appointment finding with end date filtering."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})

        # Mock appointments with different dates
        mock_appointments = [
            {"id": 1, "appointmentDate": "2025-01-01T10:00:00"},
            {"id": 2, "appointmentDate": "2025-01-15T10:00:00"},
            {"id": 3, "appointmentDate": "2025-02-01T10:00:00"},
        ]
        finder.http_get = Mock(return_value={"items": mock_appointments})

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

    def test_find_filters(self) -> None:
        """Test finding filters."""
        mock_session = Mock()
        finder = AppointmentFinder(mock_session, {})

        finder.http_get = Mock(return_value={"regions": [{"id": 1}]})

        result = finder.find_filters(region=1, specialty=2)

        assert result == {"regions": [{"id": 1}]}
        finder.http_get.assert_called_once()


class TestNotifier:
    """Test cases for the Notifier class."""

    def test_format_appointments_empty(self) -> None:
        """Test formatting empty appointments list."""
        result = Notifier.format_appointments([])
        assert result == "No appointments found."

    def test_format_appointments_single(self) -> None:
        """Test formatting single appointment."""
        appointments = [
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
        appointments = [
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

        appointments = [{"appointmentDate": "2025-01-01T10:00:00"}]
        Notifier.send_notification(appointments, "pushbullet", "Test Title")

        mock_pushbullet.assert_called_once()
        args, kwargs = mock_pushbullet.call_args
        assert "Test Title" in kwargs or "Test Title" in args

    def test_send_notification_telegram(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sending notification via telegram."""
        mock_telegram = Mock()
        monkeypatch.setattr("medichaser.telegram_notify", mock_telegram)

        appointments = [{"appointmentDate": "2025-01-01T10:00:00"}]
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

        appointments = [
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
        mock_environ = {
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
        mock_environ = {}
        mock_print = Mock()

        monkeypatch.setattr("notifications.environ", mock_environ)
        monkeypatch.setattr("builtins.print", mock_print)

        xmpp_notify("Test message")

        mock_print.assert_called_once()
        assert "XMPP notifications require" in mock_print.call_args[0][0]

    def test_gotify_notify_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful Gotify notification."""
        mock_environ = {
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
        mock_environ = {}
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
        mock_environ = {
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
        with pytest.raises(MFAError, match="Test MFA error"):
            raise MFAError("Test MFA error")

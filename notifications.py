# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# Copyright: (c) 2018, apqlzm - https://github.com/apqlzm/medihunter
# Copyright: (c) 2025, SteveSteve24 - https://github.com/SteveSteve24/MediCzuwacz
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

from os import environ

from apprise import Apprise, AppriseConfig

apprise = Apprise()


def notification_setup(concatenated_urls: str | None = None) -> None:
    try:
        if concatenated_urls is None:
            concatenated_urls = environ["NOTIFIER_APPRISE_URLS"]

        config_path = environ.get("NOTIFIER_APPRISE_CONFIG")
        if config_path:
            config = AppriseConfig()
            config.add(config_path)
            apprise.add(config)

        url_list = concatenated_urls.split(";")

        for url in url_list:
            apprise.add(url)
    except KeyError as e:
        print(
            f"notifications require NOTIFIER_APPRISE_URLS to be exported. "
            f"Detailed exception:\n{e}"
        )


def notify(message: str, title: str | None = None) -> bool | None:
    if title is None:
        title = "medichaser"

    return apprise.notify(body=message, title=title)


def legacy_prowl_setup() -> None:
    try:
        api_key = environ["NOTIFIERS_PROWL_API_KEY"]

        notification_setup(f"prowl://{api_key}")
    except KeyError as e:
        print(
            f"Prowl notifications require NOTIFIERS_PROWL_API_KEY to be exported. "
            f"Detailed exception:\n{e}"
        )


def legacy_pushbullet_setup() -> None:
    try:
        token = environ["NOTIFIERS_PUSHBULLET_TOKEN"]

        notification_setup(f"pbul://{token}")
    except KeyError as e:
        print(
            f"Pushbullet notifications require NOTIFIERS_PUSHBULLET_TOKEN to be exported. "
            f"Detailed exception:\n{e}"
        )


def legacy_pushover_setup() -> None:
    try:
        user = environ["NOTIFIERS_PUSHOVER_USER"]
        token = environ["NOTIFIERS_PUSHOVER_TOKEN"]

        notification_setup(f"pover://{user}@{token}")
    except KeyError as e:
        print(
            f"Pushover notifications require NOTIFIERS_PUSHOVER_USER and NOTIFIERS_PUSHOVER_TOKEN"
            f" to be exported. Detailed exception:\n{e}"
        )


def legacy_telegram_setup() -> None:
    try:
        token = environ["NOTIFIERS_TELEGRAM_TOKEN"]
        chat_id = environ["NOTIFIERS_TELEGRAM_CHAT_ID"]

        notification_setup(f"tgram://{token}/{chat_id}")
    except KeyError as e:
        print(
            f"Telegram notifications require NOTIFIERS_TELEGRAM_TOKEN and NOTIFIERS_TELEGRAM_CHAT_ID"
            f" to be exported. Detailed exception:\n{e}"
        )


def legacy_xmpp_setup() -> None:
    try:
        jid = environ["NOTIFIERS_XMPP_JID"]
        jid_elements = jid.split("@")
        user = jid_elements[0]
        host = jid_elements[1]
        password = environ["NOTIFIERS_XMPP_PASSWORD"]
        receiver = environ["NOTIFIERS_XMPP_RECEIVER"]

        notification_setup(f"xmpp://{user}:{password}@{host}/{jid}/{receiver}")
    except KeyError as e:
        print(
            f"XMPP notifications require NOTIFIERS_XMPP_JID, NOTIFIERS_XMPP_PASSWORD"
            f" and NOTIFIERS_XMPP_RECEIVER to be exported. Detailed exception:\n{e}"
        )
    except IndexError as e:
        print(
            f"NOTIFIERS_XMPP_JID environment variable contains invalid jid={jid}. Detailed exception:\n{e}"
        )


def legacy_gotify_setup() -> None:
    try:
        host = environ["GOTIFY_HOST"]
        token = environ["GOTIFY_TOKEN"]
    except KeyError as e:
        print(
            f"Gotify notifications require GOTIFY_HOST (base url with port),"
            f" GOTIFY_TOKEN to be exported. Detailed exception:\n{e}"
        )
        return

    try:
        prio = int(environ["GOTIFY_PRIORITY"])
    except (KeyError, ValueError):
        prio = 5

    match prio:
        case 1 | 2:
            str_prio = "low"
        case 3 | 4:
            str_prio = "moderate"
        case 5 | 6:
            str_prio = "normal"
        case _:
            str_prio = "high"

    notification_setup(f"gotifys://{host}/{token}?priority={str_prio}")

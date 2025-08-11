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

import requests
from notifiers import get_notifier
from notifiers.exceptions import BadArguments
from xmpp import xmpp

pushbullet = get_notifier("pushbullet")
pushover = get_notifier("pushover")
telegram = get_notifier("telegram")


def prowl_notify(message: str, title: str | None = None) -> None:
    if not environ.get("NOTIFIERS_PROWL_API_KEY"):
        print(
            "Prowl notifications require NOTIFIERS_PROWL_API_KEY environment to be exported.",
        )
        return

    url = "https://api.prowlapp.com/publicapi/add"
    payload = {
        "apikey": environ.get("NOTIFIERS_PROWL_API_KEY", ""),
        "priority": -1,
        "application": title or "MediChaser",
        "event": "Alert",
        "description": message,
    }
    try:
        response = requests.post(url=url, data=payload, timeout=3)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Prowl notification failed:\n{e}")


def pushbullet_notify(message: str, title: str | None = None) -> None:
    try:
        if title is None:
            r = pushbullet.notify(message=message)
        else:
            r = pushbullet.notify(message=message, title=title)
    except BadArguments as e:
        print(f"Pushbullet failed\n{e}")
        return

    if r.status != "Success":
        print(f"Pushbullet notification failed:\n{r.errors}")


def pushover_notify(message: str, title: str | None = None) -> None:
    try:
        if title is None:
            r = pushover.notify(message=message)
        else:
            r = pushover.notify(message=message, title=title)
    except BadArguments as e:
        print(f"Pushover failed\n{e}")
        return

    if r.status != "Success":
        print(f"Pushover notification failed:\n{r.errors}")


def telegram_notify(message: str, title: str | None = None) -> None:
    try:
        if title:
            message = f"<b>{title}</b>\n{message}"

        r = telegram.notify(message=message, parse_mode="html")
    except BadArguments as e:
        print(
            f"Telegram notifications require NOTIFIERS_TELEGRAM_CHAT_ID"
            f" and NOTIFIERS_TELEGRAM_TOKEN environments to be exported. Detailed exception:\n{e}"
        )
        return

    if r.status != "Success":
        print(f"Telegram notification failed\n{r.errors}")


def xmpp_notify(message: str) -> None:
    try:
        jid = environ["NOTIFIERS_XMPP_JID"]
        password = environ["NOTIFIERS_XMPP_PASSWORD"]
        receiver = environ["NOTIFIERS_XMPP_RECEIVER"]

        r = xmpp.protocol.JID(jid)
        conn = xmpp.Client(server=r.getDomain(), debug=False)
        if (
            (not conn.connect())
            or (
                not conn.auth(
                    user=r.getNode(), password=password, resource=r.getResource()
                )
            )
            or (not conn.send(xmpp.protocol.Message(to=receiver, body=message)))  # pyright: ignore[reportAttributeAccessIssue]
        ):
            print("XMPP notification failed")
    except KeyError as e:
        print(
            f"XMPP notifications require NOTIFIERS_XMPP_JID, NOTIFIERS_XMPP_PASSWORD"
            f" and NOTIFIERS_XMPP_RECEIVER to be exported. Detailed exception:\n{e}"
        )


def gotify_notify(message: str, title: str | None = None) -> None:
    try:
        host = environ["GOTIFY_HOST"]
        token = environ["GOTIFY_TOKEN"]
    except KeyError as e:
        print(
            f"GOTIFY notifications require GOTIFY_HOST (base url with port),"
            f" GOTIFY_TOKEN to be exported. Detailed exception:\n{e}"
        )
        return

    try:
        prio = int(environ["GOTIFY_PRIORITY"])
    except (KeyError, ValueError):
        prio = 5

    if title is None:
        title = "medihunter"

    try:
        requests.post(
            host + "/message?token=" + token,
            json={"message": message, "priority": int(prio), "title": title},
        )

    except requests.exceptions.RequestException as e:
        print(f"GOTIFY notification failed:\n{e}")

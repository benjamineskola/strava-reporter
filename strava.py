#!/usr/bin/env python

import functools
import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from random import randrange

import requests


def _fix_single_date(item):
    if "start_date" in item and "start_date_local" in item:
        if "utc_offset" in item:
            if item["utc_offset"] >= 0:
                item["start_date_local"] = item["start_date_local"].replace(
                    "Z", f"+{item['utc_offset'] / 3600 * 100:04.0f}"
                )
            else:
                item["start_date_local"] = item["start_date_local"].replace(
                    "Z", f"{item['utc_offset'] / 3600 * 100:05.0f}"
                )
        item["start_date"] = datetime.strptime(
            item["start_date_local"], "%Y-%m-%dT%H:%M:%S%z"
        )
        del item["start_date_local"]
    return item


def _fix_dates(func):
    @functools.wraps(func)
    def decorated_func(*args, **kwargs):
        data = func(*args, **kwargs)
        if type(data).__name__ == "list":
            return [_fix_single_date(item) for item in data]
        else:
            return _fix_single_date(data)

    return decorated_func


class Strava:
    class OneOffHTTPRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

            path, params_str = self.path.split("?", 1)
            params = dict(
                [tuple(param.split("=", 1)) for param in params_str.split("&")]
            )

            self.server.result = params
            self.server.shutdown()
            return

    def _try_port(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return True
            except:
                return False

    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = {}

        self._token_file = Path(os.environ["XDG_CACHE_HOME"]) / "strava_token"
        if self._token_file.exists():
            self.token = json.loads(self._token_file.read_text())
            if self.token["expires_at"] < datetime.now().timestamp():
                self.token = requests.post(
                    "https://www.strava.com/api/v3/oauth/token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.token["refresh_token"],
                        "grant_type": "refresh_token",
                    },
                ).json()
                if "access_token" in self.token:
                    self._token_file.write_text(json.dumps(self.token))
                else:
                    print(self.token)
                    sys.exit(1)
        else:
            port = randrange(49152, 65535)
            while not self._try_port(port):
                port = randrange(49152, 65535)

            auth_url = f"http://www.strava.com/oauth/authorize?client_id={self.client_id}&response_type=code&redirect_uri=http://127.0.0.1:{port}&approval_prompt=auto&scope=read_all,activity:read_all"
            subprocess.run(["open", auth_url])

            server_address = ("", port)
            httpd = ThreadingHTTPServer(server_address, Strava.OneOffHTTPRequestHandler)
            httpd.serve_forever()
            auth_params = httpd.result

            self.token = requests.post(
                "https://www.strava.com/api/v3/oauth/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": auth_params["code"],
                    "grant_type": "authorization_code",
                },
            ).json()
            if "access_token" in self.token:
                self._token_file.write_text(json.dumps(self.token))
            else:
                print(self.token)
                sys.exit(1)

    @_fix_dates
    def get(self, url, *args, **kwargs):
        """Fetch API endpoint response

        Wraps requests.get to handle authentication etc"""

        auth_header = {"Authorization": f"Bearer {self.token['access_token']}"}
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"].update(auth_header)
        return requests.get(
            f"https://www.strava.com/api/v3{url}", *args, **kwargs
        ).json()

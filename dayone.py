#!/usr/bin/env python

import os
import pickle
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from geopy.geocoders import MapBox

from strava import Strava

load_dotenv()


class LocationCache(dict):
    def __init__(self, *args, **kwargs):
        self._geolocator = MapBox(api_key=os.environ["MAPBOX_API_KEY"])

        super(LocationCache, self).__init__(*args, **kwargs)

    def __getitem__(self, key):
        if key not in self:
            location = self._geolocator.reverse(key)
            if not location:
                return
            self[key] = ", ".join(
                [
                    l["text"]
                    for l in location.raw["context"]
                    if l["id"].startswith("place.")
                    or l["id"].startswith("neighbourhood.")
                    or l["id"].startswith("locality.")
                ]
            )

        return super().__getitem__(key)


locations = LocationCache()


def seconds_to_minutes(seconds):
    return str(timedelta(seconds=int(seconds))).removeprefix("0:")


def link(text, target):
    return f"\033]8;;{target}\033\\{text}\033]8;;\033\\"


best = {"overall": None, "km": None, "consistency": None}
best_efforts = {}

client = Strava(os.environ["STRAVA_CLIENT_ID"], os.environ["STRAVA_CLIENT_SECRET"])

activity_type = "Run" if len(sys.argv) == 1 else sys.argv[1].capitalize()

cache_path = Path(os.environ["XDG_CACHE_HOME"]) / (
    "strava.cache"
    if activity_type == "Run"
    else f"strava.{activity_type.lower()}.cache"
)

dayone_cache_path = Path(os.environ["XDG_CACHE_HOME"]) / "strava2dayone.cache"

activity_cache = {}
if cache_path.exists():
    activity_cache = pickle.loads(cache_path.read_bytes())

dayone_cache = []
if dayone_cache_path.exists():
    dayone_cache = pickle.loads(dayone_cache_path.read_bytes())


if __name__ == "__main__":
    page = 1
    while activities := client.get(
        "/athlete/activities",
        params={
            # "after": int(datetime(2021, 4, 1).timestamp()),
            "after": int(datetime(2022, 10, 1).timestamp()),
            # "after": int(datetime(2018, 5, 24).timestamp()),
            # "before": int(datetime(2018, 6, 26).timestamp()),
            "page": page,
        },
    ):
        page += 1

        if "errors" in activities:
            print(activities)
            sys.exit(1)

        for activity in activities:
            if activity["type"] != activity_type:
                continue

            if activity["id"] in [49385397, 49451690, 294364499]:
                continue

            if activity["id"] in dayone_cache:
                continue

            if activity["id"] in activity_cache:
                activity = activity_cache[activity["id"]]
            else:
                activity = client.get(f"/activities/{activity['id']}")
                activity_cache[activity["id"]] = activity

            average_speed = activity["distance"] / activity["elapsed_time"]
            average_pace = seconds_to_minutes(1 / (average_speed / 1000))

            if activity["distance"] > 900:
                if (
                    not best["overall"]
                    or best["overall"]["average_speed"] < average_speed
                ):
                    best["overall"] = {
                        "average_speed": average_speed,
                        "pace": average_pace,
                        "start_date": activity["start_date"],
                        "activity": activity,
                    }

            location = locations[tuple([round(i, 2) for i in activity["start_latlng"]])]

            if "best_efforts" in activity:
                for effort in activity["best_efforts"]:
                    if effort["name"] not in best_efforts:
                        best_efforts[effort["name"]] = []
                    effort["start_date"] = activity["start_date"]
                    effort["activity"] = activity
                    best_efforts[effort["name"]].append(effort)

            newline = "\n"

            body = f"""# {activity["name"]}
{activity["description"].strip() + newline if activity["description"] else ""}
Distance: {activity["distance"]/1000:.2f}km
Elapsed time: {seconds_to_minutes(activity["elapsed_time"])}
Elapsed time (seconds): {activity["elapsed_time"]}
Pace: {average_pace}/km
"""
            if activity["type"] == "Ride":
                body += f"Speed: {activity['average_speed'] / 1000 * 3600:.2f} km/h\n"

            body += f"Link to activity: https://www.strava.com/activities/{activity['id']}\n"

            for effort_type, efforts in best_efforts.items():
                efforts.sort(
                    key=lambda d: (d["elapsed_time"], -d["start_date"].timestamp())
                )
                index = [effort["activity"] for effort in efforts].index(activity)
                if index < 5:
                    body += (
                        "\n- "
                        + {
                            0: "Best",
                            1: "2nd best",
                            2: "3rd best",
                            3: "4th best",
                            4: "5th best",
                        }.get(index)
                        + f" {effort_type} time"
                    )

            cmd = [
                "dayone2",
                "--journal",
                "Fitness",
                "--isoDate",
                activity["start_date"]
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
                .isoformat(),
                "--time-zone",
                f"GMT{activity['start_date'].strftime('%z')}",
                "--tags",
                activity["type"],
                "strava",
            ]
            if activity["start_latlng"] and len(activity["start_latlng"]) == 2:
                cmd += ["--coordinate"] + [str(i) for i in activity["start_latlng"]]
            # print(cmd)
            cmd += ["--", "new", body]
            subprocess.run(cmd)
            dayone_cache.append(activity["id"])

    cache_path.write_bytes(pickle.dumps(activity_cache))
    dayone_cache_path.write_bytes(pickle.dumps(dayone_cache))

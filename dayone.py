#!/usr/bin/env python

import os
import pickle
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from strava import Strava

load_dotenv()
downloaddir = Path(os.environ["HOME"]) / "Downloads"


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
            "after": int(datetime(2014, 9, 1).timestamp()),
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

            if activity['distance'] == 0:
                desc = activity['description'].strip()
                if desc.endswith('km'):
                    activity['distance'] = float(desc.removesuffix('km')) * 1000
                    del activity['description']
                    activity['description'] = 'Indoor ride'
                    activity_cache[activity["id"]] = activity


            average_speed = activity["distance"] / activity["elapsed_time"]
            average_pace = seconds_to_minutes(1 / (average_speed / 1000))

            if activity['average_speed'] == 0:
                activity['average_speed'] = average_speed

            newline = "\n"

            body = f"""# {activity["name"]}\n"""

            attachment = None
            if (
                "map" in activity
                and "polyline" in activity["map"]
                and activity["map"]["polyline"]
            ):
                attachment = f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&maptype=da&scale=2&path=color:0xff481eff|weight:2|enc:{activity['map']['polyline']}&key={os.environ['GOOGLE_API_KEY']}&style=feature:road.highway|element:geometry|color:0xFFFFFF&style=feature:transit.station.airport|element:labels.icon|visibility:off&style=feature:poi|element:labels.icon|visibility:off&style=feature:road.highway|element:geometry.stroke|color:0xDDDDDD"

                if activity["type"] != "Ride":
                    attachment += (
                        "&style=feature:road|element:labels.icon|visibility:off"
                    )

                localname = (
                    downloaddir
                    / f"{re.sub('[/:]', '_', str(activity['start_date']))}_map.jpg"
                )
                body += "[{attachment}]\n"
                subprocess.run(["curl", "-gkLsS", "-o", str(localname), attachment])

            body += f"""{activity["description"].strip() + newline if activity["description"] else ""}
Distance: {activity["distance"]/1000:.2f}km
Elapsed time: {seconds_to_minutes(activity["elapsed_time"])}
Elapsed time (seconds): {activity["elapsed_time"]}
Pace: {average_pace}/km
"""
            if activity["type"] == "Ride":
                body += f"Speed: {activity['average_speed'] / 1000 * 3600:.2f} km/h\n"

            body += f"Link to activity: https://www.strava.com/activities/{activity['id']}\n"

            if "best_efforts" in activity:
                for effort in activity["best_efforts"]:
                    if effort["name"] not in best_efforts:
                        best_efforts[effort["name"]] = []
                    effort["start_date"] = activity["start_date"]
                    effort["activity"] = activity
                    best_efforts[effort["name"]].append(effort)

                for effort_type, efforts in best_efforts.items():
                    efforts.sort(
                        key=lambda d: (d["elapsed_time"], -d["start_date"].timestamp())
                    )
                    try:
                        index = [effort["activity"] for effort in efforts].index(
                            activity
                        )
                    except ValueError:
                        continue
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
                            + f" {effort_type} time ({seconds_to_minutes(efforts[index]['elapsed_time'])})"
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

            if attachment:
                cmd += ["--attachments", localname]

            if activity["start_latlng"] and len(activity["start_latlng"]) == 2:
                cmd += ["--coordinate"] + [str(i) for i in activity["start_latlng"]]
            cmd += ["--", "new", body]
            subprocess.run(cmd)
            if attachment:
                os.unlink(localname)
            dayone_cache.append(activity["id"])
            dayone_cache_path.write_bytes(pickle.dumps(dayone_cache))

    cache_path.write_bytes(pickle.dumps(activity_cache))

#!/usr/bin/env python

import os
import pickle
import sys
from datetime import datetime
from math import sqrt
from pathlib import Path

import yaml
from geopy.geocoders import MapBox

from strava import Strava


class LocationCache(dict):
    def __init__(self, *args, **kwargs):
        self._geolocator = MapBox(api_key="")

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
    return f"{int(seconds / 60)}:{int(seconds % 60):02d}"


def link(text, target):
    return f"\033]8;;{target}\033\\{text}\033]8;;\033\\"


best = {"overall": None, "km": None, "consistency": None}
best_efforts = {}

config = yaml.safe_load(
    (Path(os.environ["XDG_CONFIG_HOME"]) / "strava.yml").read_text()
)
client = Strava(config["client_id"], config["client_secret"])

cache_path = Path(os.environ["XDG_CACHE_HOME"]) / "strava.cache"
activity_cache = {}
if cache_path.exists():
    activity_cache = pickle.loads(cache_path.read_bytes())

page = 1
while activities := client.get(
    "/athlete/activities",
    params={
        # "after": int(datetime(2021, 4, 1).timestamp()),
        "after": int(datetime(2014, 9, 1).timestamp()),
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
        if activity["type"] != "Run":
            continue

        if activity["id"] in activity_cache:
            activity = activity_cache[activity["id"]]
        else:
            activity = client.get(f"/activities/{activity['id']}")
            activity_cache[activity["id"]] = activity

        average_speed = activity["distance"] / activity["elapsed_time"]
        average_pace = seconds_to_minutes(1 / (average_speed / 1000))

        if activity["distance"] > 900:
            if not best["overall"] or best["overall"]["average_speed"] < average_speed:
                best["overall"] = {
                    "average_speed": average_speed,
                    "pace": average_pace,
                    "start_date": activity["start_date"],
                    "activity": activity,
                }

        location = locations[tuple([round(i, 2) for i in activity["start_latlng"]])]

        for effort in activity["best_efforts"]:
            if effort["name"] not in best_efforts:
                best_efforts[effort["name"]] = []
            effort["start_date"] = activity["start_date"]
            effort["activity"] = activity
            best_efforts[effort["name"]].append(effort)

        print(
            f"""{link(activity['start_date'].strftime("%a, %b %d, %Y"), 'https://www.strava.com/activities/'+str(activity['id']))} {activity["distance"]/1000:.2f}km in {seconds_to_minutes(activity["elapsed_time"])} ({average_pace}/km, 5k in {seconds_to_minutes(5000/activity["average_speed"])}){" ??? " + location if location else ""}{" ??? " + activity["description"] if activity["description"] else ""}"""
        )

        if "splits_metric" in activity and len(activity["splits_metric"]) > 1:
            print(
                "\tsplits",
                ", ".join(
                    [
                        seconds_to_minutes(1 / (split["average_speed"] / 1000))
                        for split in activity["splits_metric"]
                        if split["distance"] >= 900
                    ]
                ),
            )

            splits = [
                split
                for split in activity["splits_metric"]
                if split["distance"] >= 900
                and (split["distance"] / split["elapsed_time"]) <= 4
            ]
            for split in splits:
                split_average_speed = split["distance"] / split["elapsed_time"]
                if not best["km"] or best["km"]["average_speed"] < split_average_speed:
                    best["km"] = {
                        "activity": activity,
                        "average_speed": split_average_speed,
                        "start_date": activity["start_date"],
                        "pace": 1 / (split_average_speed / 1000),
                    }

            if len(splits) < 3:
                continue
            normalised_times = [1000 / (split["average_speed"]) for split in splits]
            mean_split_time = sum(normalised_times) / len(normalised_times)
            variance = sum([pow(x - mean_split_time, 2) for x in normalised_times]) / (
                len(normalised_times) - 1
            )
            plus_minus = (
                (max(normalised_times) - mean_split_time)
                + (mean_split_time - min(normalised_times))
            ) / 2

            print(
                f"\t\tfastest: {seconds_to_minutes(min(normalised_times))}, slowest: {seconds_to_minutes(max(normalised_times))}, average: {seconds_to_minutes(mean_split_time)}??{seconds_to_minutes(plus_minus)} (??{seconds_to_minutes(sqrt(variance))})"
            )

            if not best["consistency"] or best["consistency"]["variance"] > variance:
                best["consistency"] = {
                    "activity": activity,
                    "variance": variance,
                    "stddev": seconds_to_minutes(sqrt(variance)),
                    "start_date": activity["start_date"],
                    "pace": average_pace,
                    "splits": normalised_times,
                    "min": seconds_to_minutes(min(normalised_times)),
                    "max": seconds_to_minutes(max(normalised_times)),
                    "diff": seconds_to_minutes(
                        max(normalised_times) - min(normalised_times)
                    ),
                    "average": seconds_to_minutes(mean_split_time),
                    "plus_minus": seconds_to_minutes(plus_minus),
                }

        print()

print(
    f"""Best split: {seconds_to_minutes(best['km']['pace'])}/km on {link(best['km']['start_date'].strftime('%a, %b %d, %Y'), "https://www.strava.com/activities/"+str(best['km']['activity']['id']))}"""
)
print(
    f"""Best overall: {best['overall']['pace']}/km ({best['overall']['activity']['distance']/1000:.1f}km in {seconds_to_minutes(best['overall']['activity']['elapsed_time'])}) on {link(best['overall']['start_date'].strftime('%a, %b %d, %Y'), "https://www.strava.com/activities/"+str(best["overall"]["activity"]["id"]))}"""
)
print(
    f"""Most consistent: {best['consistency']['pace']}/km ({best['consistency']['activity']['distance']/1000:.1f}km in {seconds_to_minutes(best['consistency']['activity']['elapsed_time'])}) on {link(best['consistency']['start_date'].strftime('%a, %b %d, %Y'), "https://www.strava.com/activities/"+str(best["consistency"]["activity"]["id"]))}\n\tsplits: {', '.join([seconds_to_minutes(split) for split in best['consistency']['splits']])}; fastest: {best['consistency']['min']}, slowest: {best['consistency']['max']}, average: {best["consistency"]["average"]}??{best["consistency"]["plus_minus"]} (??{best["consistency"]["stddev"]})"""
)

print("Best efforts:")
for effort_type, efforts in best_efforts.items():
    efforts.sort(key=lambda d: (d["elapsed_time"], -d["start_date"].timestamp()))
    delimiter = "\n\t\t"
    print(
        f"""\t{effort_type}:{delimiter}{delimiter.join([seconds_to_minutes(effort["elapsed_time"]) + " on " + link(effort['start_date'].strftime("%a, %b %d, %Y"), "https://www.strava.com/activities/"+str(effort["activity"]["id"])) for effort in efforts[0:5]  ])}"""
    )

cache_path.write_bytes(pickle.dumps(activity_cache))

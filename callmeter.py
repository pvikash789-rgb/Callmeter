"""
callmeter.py - spike version.

Reads two things from a ServiceNow instance through the standard Table API:
  1. flow runs        (sys_flow_context)
  2. outbound calls   (sys_outbound_http_log, only calls made by flow steps)

Then links each call to the flow run that made it, by time, and prints
a summary per flow: runs, calls, failed calls, and runs that made a call
but ended "Complete" anyway.

Credentials come from environment variables, never from this file:
  CALLMETER_INSTANCE   instance name, e.g. dev123456 for dev123456.service-now.com
  CALLMETER_USER       a read-only account (see README)
  CALLMETER_PASSWORD   set with:  read -s CALLMETER_PASSWORD && export CALLMETER_PASSWORD

Read-only. Nothing is written to the instance. Results are printed and
saved to a local CSV that must never be committed.
"""

import csv
import os
import sys
from datetime import datetime, timedelta

import requests

FLOW_PREFIX = os.environ.get("CALLMETER_FLOW_PREFIX", "IH")
SLACK_SECONDS = 3  # allowed gap between a run ending and its call being logged


def env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing {name}. See the comments at the top of this file.")
    return value


def get_table(session, base, table, query, fields):
    rows, offset, page = [], 0, 1000
    while True:
        r = session.get(
            f"{base}/api/now/table/{table}",
            params={
                "sysparm_query": query,
                "sysparm_fields": ",".join(fields),
                "sysparm_limit": page,
                "sysparm_offset": offset,
                "sysparm_display_value": "false",
                "sysparm_exclude_reference_link": "true",
            },
            headers={"Accept": "application/json"},
            timeout=60,
        )
        if r.status_code == 401:
            sys.exit("401 from the instance: user or password is wrong, or this account is not allowed to use basic auth for the API (see README).")
        if r.status_code == 403:
            sys.exit(f"403 reading {table}: this user can't read that table.")
        r.raise_for_status()
        batch = r.json().get("result", [])
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def ts(value):
    # Table API returns UTC as "YYYY-MM-DD HH:MM:SS" when display_value=false
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def main():
    instance = env("CALLMETER_INSTANCE")
    base = f"https://{instance}.service-now.com"
    session = requests.Session()
    session.auth = (env("CALLMETER_USER"), env("CALLMETER_PASSWORD"))

    runs = get_table(
        session, base, "sys_flow_context",
        f"nameSTARTSWITH{FLOW_PREFIX}^ORDERBYsys_created_on",
        ["sys_id", "name", "state", "sys_created_on", "sys_updated_on"],
    )
    if not runs:
        sys.exit(f"No flow runs found with names starting '{FLOW_PREFIX}'.")

    first = min(ts(r["sys_created_on"]) for r in runs) - timedelta(minutes=1)
    calls = get_table(
        session, base, "sys_outbound_http_log",
        f"source_table=sys_hub_step_instance^sys_created_on>={first:%Y-%m-%d %H:%M:%S}^ORDERBYsys_created_on",
        ["sys_id", "sys_created_on", "hostname", "url", "response_status", "response_time", "source_record_id"],
    )

    # Each run covers [created, last updated + slack]. A run's record is last
    # updated when it finishes, so this is its real time window.
    windows = []
    for r in runs:
        start = ts(r["sys_created_on"])
        finished = ts(r.get("sys_updated_on") or r["sys_created_on"])
        end = max(finished, start) + timedelta(seconds=SLACK_SECONDS)
        windows.append((start, end, r))

    linked, unlinked, ambiguous = [], [], 0
    for c in calls:
        t = ts(c["sys_created_on"])
        matches = [w for w in windows if w[0] <= t <= w[1]]
        if not matches:
            unlinked.append(c)
            continue
        if len(matches) > 1:
            ambiguous += 1
        run = max(matches, key=lambda w: w[0])[2]  # latest run that started before the call
        linked.append((c, run))

    # Summary per flow
    summary = {}
    for r in runs:
        s = summary.setdefault(r["name"], {"runs": 0, "calls": 0, "failed": 0, "failed_but_complete": 0, "_runs_with_fail": set()})
        s["runs"] += 1
    for c, run in linked:
        s = summary[run["name"]]
        s["calls"] += 1
        status = to_int(c["response_status"], -1)
        if not (200 <= status < 300):
            s["failed"] += 1
            if (run.get("state") or "").lower() == "complete":
                s["_runs_with_fail"].add(run["sys_id"])
    for s in summary.values():
        s["failed_but_complete"] = len(s.pop("_runs_with_fail"))

    print()
    print(f"Instance: {instance}   flows starting '{FLOW_PREFIX}'")
    print(f"Flow runs: {len(runs)}   outbound calls from flow steps: {len(calls)}   linked: {len(linked)}   unlinked: {len(unlinked)}   ambiguous: {ambiguous}")
    print()
    header = f"{'Flow':<28}{'Runs':>6}{'Calls':>7}{'Failed':>8}{'Failed but Complete':>22}"
    print(header)
    print("-" * len(header))
    for name in sorted(summary):
        s = summary[name]
        print(f"{name:<28}{s['runs']:>6}{s['calls']:>7}{s['failed']:>8}{s['failed_but_complete']:>22}")
    total_calls = sum(s["calls"] for s in summary.values())
    print("-" * len(header))
    print(f"{'Total':<28}{len(runs):>6}{total_calls:>7}")
    print()
    print("Each call:")
    for c, run in linked:
        print(f"  {c['sys_created_on']} UTC  {c['response_status']:>4}  {c['hostname']:<32} -> {run['name']} (run started {run['sys_created_on']})")
    for c in unlinked:
        print(f"  {c['sys_created_on']} UTC  {c['response_status']:>4}  {c['hostname']:<32} -> NOT LINKED")

    out = "callmeter_calls.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["call_time_utc", "status", "hostname", "flow", "run_started_utc", "run_state", "run_sys_id"])
        for c, run in linked:
            w.writerow([c["sys_created_on"], c["response_status"], c["hostname"], run["name"], run["sys_created_on"], run.get("state", ""), run["sys_id"]])
        for c in unlinked:
            w.writerow([c["sys_created_on"], c["response_status"], c["hostname"], "", "", "", ""])
    print()
    print(f"Saved {out} (local only, don't commit it).")


if __name__ == "__main__":
    main()

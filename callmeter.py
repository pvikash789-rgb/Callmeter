"""
callmeter.py - spike version.

Reads two things from a ServiceNow instance through the standard Table API:
  1. flow runs        (sys_flow_context)
  2. outbound calls   (sys_outbound_http_log, only calls made by flow steps)

Then links each call to the flow run that made it, by time, and checks
the record history (sys_audit) for whether the run changed anything.
Prints per flow: runs, calls, failed calls, calls on runs that changed
nothing, and the total of calls that bought nothing.

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
        ["sys_id", "name", "state", "sys_created_on", "sys_updated_on", "source_table", "source_record"],
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

    # Did each run change anything? Look for record changes made by the
    # flow's account (System user by default) inside the run's window.
    run_user = os.environ.get("CALLMETER_RUN_AS", "system")
    tables = sorted({r.get("source_table") or "incident" for r in runs})
    audits = get_table(
        session, base, "sys_audit",
        f"tablenameIN{','.join(tables)}^user={run_user}^sys_created_on>={first:%Y-%m-%d %H:%M:%S}",
        ["sys_created_on", "tablename", "documentkey", "fieldname"],
    )
    has_source = any(r.get("source_record") for r in runs)
    effect = {}
    for start, end, r in windows:
        if has_source and not r.get("source_record"):
            # Scheduled or manual run: no trigger record, so nothing to check
            # changes against. Counted as no visible effect.
            effect[r["sys_id"]] = []
            continue
        hits = [a for a in audits if start <= ts(a["sys_created_on"]) <= end
                and (not has_source or a["documentkey"] == r.get("source_record"))]
        effect[r["sys_id"]] = sorted({a["fieldname"] for a in hits})

    calls_by_run = {}
    for c, run in linked:
        calls_by_run.setdefault(run["sys_id"], []).append(c)

    def ok(c):
        return 200 <= to_int(c["response_status"], -1) < 300

    summary = {}
    for r in runs:
        s = summary.setdefault(r["name"], {"runs": 0, "calls": 0, "failed": 0, "no_effect": 0, "wasted": 0})
        s["runs"] += 1
        rc = calls_by_run.get(r["sys_id"], [])
        s["calls"] += len(rc)
        failed = [c for c in rc if not ok(c)]
        s["failed"] += len(failed)
        if rc and not effect[r["sys_id"]]:
            s["no_effect"] += len(rc) - len(failed)
            s["wasted"] += len(rc)
        else:
            s["wasted"] += len(failed)

    print()
    print(f"Instance: {instance}   flows starting '{FLOW_PREFIX}'")
    print(f"Flow runs: {len(runs)}   outbound calls from flow steps: {len(calls)}   linked: {len(linked)}   unlinked: {len(unlinked)}   ambiguous: {ambiguous}")
    print(f"Run-to-record link: {'source record on each run' if has_source else 'time window only (no source record on runs)'}")
    print()
    header = f"{'Flow':<28}{'Runs':>6}{'Calls':>7}{'Failed':>8}{'No effect':>11}{'Bought nothing':>16}"
    print(header)
    print("-" * len(header))
    for name in sorted(summary):
        x = summary[name]
        print(f"{name:<28}{x['runs']:>6}{x['calls']:>7}{x['failed']:>8}{x['no_effect']:>11}{x['wasted']:>16}")
    tc = sum(x["calls"] for x in summary.values())
    tw = sum(x["wasted"] for x in summary.values())
    print("-" * len(header))
    print(f"{'Total':<28}{len(runs):>6}{tc:>7}{'':>8}{'':>11}{tw:>16}")
    # Scheduled flows: project calls to 30 days from the observed interval
    proj = []
    for name in sorted(summary):
        fr = sorted((ts(r["sys_created_on"]) for r in runs if r["name"] == name and not r.get("source_record")))
        if len(fr) < 3 or len(fr) != summary[name]["runs"]:
            continue
        gaps = sorted((b - a).total_seconds() for a, b in zip(fr, fr[1:]))
        interval = gaps[len(gaps) // 2]
        if interval <= 0:
            continue
        per_run = summary[name]["calls"] / summary[name]["runs"]
        monthly = 30 * 24 * 3600 / interval * per_run
        proj.append((name, interval, per_run, monthly))
    if proj:
        print()
        print("Scheduled flows, projected to 30 days at the observed interval:")
        for name, interval, per_run, monthly in proj:
            print(f"  {name:<28} every {interval/60:.1f} min, {per_run:.1f} calls per run -> about {monthly:,.0f} calls per 30 days ({monthly*365/30:,.0f} per year)")

    print()
    print("Each run:")
    for start, end, r in windows:
        rc = calls_by_run.get(r["sys_id"], [])
        codes = ",".join(c["response_status"] for c in rc) or "-"
        changed = ",".join(effect[r["sys_id"]]) or "nothing"
        if not r.get("source_record") and has_source:
            changed = "no trigger record"
        print(f"  {r['sys_created_on']} UTC  {r['name']:<26} state={r.get('state','')}  calls={codes:<8} changed={changed}")
    for c in unlinked:
        print(f"  {c['sys_created_on']} UTC  call {c['response_status']} {c['hostname']} NOT LINKED to any run")

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

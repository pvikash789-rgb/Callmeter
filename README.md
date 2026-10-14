# Callmeter

Callmeter, for use with ServiceNow® Integration Hub, traces each Integration Hub transaction back to the flow that made it, and flags the transactions that bought nothing: calls that failed, and runs that paid for a call and then changed nothing.

**Status:** spike passed, prototype in progress. Build journal: https://pvikash789-rgb.github.io/Callmeter/

## Why

The Integration Hub Usage Dashboard counts transactions by spoke, action, protocol and calling app scope, per month. It doesn't show which flow spent them, whether each call worked, or whether the run did anything useful. On a test instance, 8 of 8 predicted transactions matched the platform's own usage ledger, failed calls were billed, and the ledger lumped two flows together because they shared an action. See [lab/](lab/).

## What it does today

`callmeter.py` reads two tables through the REST Table API, read-only:

- `sys_flow_context` (flow runs)
- `sys_outbound_http_log` (outbound calls made by flow steps)

- `sys_audit` (record history, to see whether each run changed anything)

It links each call to the flow run whose time window contains it, checks whether that run changed anything on its record, and prints per flow: runs, calls, failed calls, calls on runs with no effect, and the total that bought nothing. A per-call CSV is written locally and is git-ignored.

On the test lab: 8 transactions, 2 failed, 5 on runs that changed nothing, 1 useful.

## Run it

Python 3.10 or later.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install requests
export CALLMETER_INSTANCE=dev123456        # the part before .service-now.com
export CALLMETER_USER=callmeter.reader
read -s CALLMETER_PASSWORD && export CALLMETER_PASSWORD
python callmeter.py
```

`CALLMETER_FLOW_PREFIX` (default `IH`) limits the report to flows whose names start with it.

## Access and trust

- Read-only. It never writes to the instance.
- Use a dedicated account, not an admin login: set it to Web Service Access Only, give it read access to the three tables above, and nothing else.
- Since the 2026 Basic Auth restriction, accounts using basic authentication for the API need the `snc_basic_auth_api_access` role or Web Service Access Only. Without it the script gets HTTP 401.
- Credentials come from environment variables. Never commit them, and never commit anything read from an instance.

## Limits

- Calls are linked to runs by time. Two runs of different flows calling out in the same second could be ambiguous; the script reports how many were.
- "Changed nothing" means no change on the run's own record by the flow's account (`CALLMETER_RUN_AS`, default `system`). A flow that updates another record, sends an email or only reads data will show as no visible effect.
- Tested on one developer instance (Australia release).

## Site

The build journal and decision log in `docs/` are built from `tools/site/`. See [tools/site/README.md](tools/site/README.md).

---

Callmeter is an independent open-source project. It is not affiliated with, sponsored by or endorsed by ServiceNow, Inc. ServiceNow, the ServiceNow logo, Now, and other ServiceNow marks are trademarks and/or registered trademarks of ServiceNow, Inc., in the United States and/or other countries. Other company and product names may be trademarks of the respective companies with which they are associated.

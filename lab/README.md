# Test lab

Four flows on a free Personal Developer Instance (Australia release), each built to show one pattern.
All are triggered when an incident is created with a short description starting with the flow's code.

| Flow | What it does | Incidents | Predicted transactions | Ledger | Result |
|---|---|---|---|---|---|
| IH-00 no call | Adds a work note. No outside call. | 2 | 0 | 0 | Match |
| IH-01 one call | One REST GET to `jsonplaceholder.typicode.com/todos/1` | 3 | 3 | 6 for the shared GET action (IH-01 + IH-02) | Match |
| IH-02 call before check | Same REST GET first, then adds a work note only if priority is 1 | 3 (one at priority 1) | 3, of which 2 wasted | see above | Match (waste detection not built yet) |
| IH-03 failing call | REST GET to `httpbin.org/status/500` | 2 | 2 (hedged: failed calls might not count) | 2 for the failing action | Match: failed calls are billed |
| IH-04 call used | Same REST GET, then writes the response body into work notes | 2 | 2, of which 0 wasted | not yet re-checked | Match on the tracer |
| **Total (spike, IH-00 to IH-03)** | | **10** | **8** | **8** | **8 of 8** |

## Actions

- `IH Spike GET todo`: one REST step, base URL `https://jsonplaceholder.typicode.com`, path `/todos/1`, GET. Used by IH-01, IH-02 and IH-04. A `Response Body` output was added on day 3 so IH-04 can use the response.
- `IH Spike GET fail`: one REST step, base URL `https://httpbin.org`, path `/status/500`, GET. Used by IH-03.

## Setup notes

- The REST step is locked on a new developer instance until the "ServiceNow IntegrationHub Installer" plugin is activated from the developer site.
- Flow reporting was set to "All configuration and runtime values" (Flow Administration > Properties) for the test runs.
- The ledger is the `ua_ih_usage` table (one row per action per month). It updates in a batch, not live.
- The per-call record is `sys_outbound_http_log`. Source table is Step Instance; Source record ID is empty at the default Basic log level.
- All 10 runs were marked Complete, including both IH-03 runs where the call returned HTTP 500.

## Tracer result (day 3)

12 runs, 10 calls, 10 linked (1 call fitted two runs' windows and was given to the later run, which was correct). Bought nothing: IH-01 3 (response never used), IH-02 2 (stopped at the check), IH-03 2 (failed). Useful: IH-02 1, IH-04 2.

No data from the instance is stored in this repository. The table above is typed from what the instance showed.

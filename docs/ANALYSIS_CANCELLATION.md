# Analysis page departure

The analysis form owns a lifecycle for each submission. Leaving the page sends a
small, same-origin `fetch` request with `keepalive: true` to the existing
`/api/analysis/cancel/<task_id>` endpoint when the server has acknowledged a task
ID. The request retains the existing CSRF header and session credentials.
Repeated departure events do not send duplicate cancellation requests.

The page also aborts its own fetches and stops its event stream, polling,
autosave timers and pending redirects. Late responses cannot revive a departed
run. A restored page receives usable controls and can start a fresh run;
completed runs do not send a cancellation request during their normal redirect.
Explicit cancellation reports failure and allows retry if the endpoint rejects
it, rather than displaying a false success.

Cancellation is cooperative. It does not guarantee interruption or refund of an
already running provider call. If the page unloads before receiving a task ID,
the browser cannot reliably cancel work already queued by the server. A server
pre-dispatch cancellation token would be needed to close that gap. Browser
shutdown and network loss can also prevent the best-effort keepalive request.

Run the portable lifecycle regressions with Node.js 18 or later:

```sh
node --test tests/js/analysis_lifecycle.test.mjs
```

The normal pytest suite includes a wrapper for these tests when Node is
available. The focused unit wrapper can run independently of Flask fixtures:

```sh
python -m pytest --noconftest tests/test_analysis_departure_lifecycle.py --no-cov -q
```

These unit tests do not replace application integration tests of authenticated
cancellation. Any application startup or fixture failure must be resolved before
claiming full application validation.

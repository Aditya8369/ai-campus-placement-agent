/** One analysis view's client requests and cooperative server cancellation. */
export function createAnalysisRun() {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let departed = false;
  let finished = false;
  let taskId = null;
  let cancellationSent = false;

  function cancelAcknowledgedTask() {
    if (finished || !taskId || cancellationSent) return;
    cancellationSent = true;
    const csrf = globalThis.document?.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
    try {
      Promise.resolve(fetch(`/api/analysis/cancel/${encodeURIComponent(taskId)}`, {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": csrf } : {}) },
        body: JSON.stringify({ task_id: taskId }),
      })).catch(() => {});
    } catch {
      // Unload cancellation is best effort; never block navigation.
    }
  }

  return {
    get signal() { return controller?.signal; },
    get departed() { return departed; },
    get stopped() { return departed || finished; },
    acknowledgeTask(id) {
      if (typeof id !== "string" || !id) return;
      taskId = id;
      if (departed) cancelAcknowledgedTask();
    },
    finish() { finished = true; controller?.abort(); },
    // shortcut: a fully unloaded page needs a server pre-dispatch token to cancel an unacknowledged task.
    leave() {
      if (departed) return;
      departed = true;
      cancelAcknowledgedTask();
      controller?.abort();
    },
  };
}

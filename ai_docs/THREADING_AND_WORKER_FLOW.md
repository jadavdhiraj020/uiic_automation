# Threading And Worker Flow

## Purpose

This document explains how Qt threading and asyncio are combined safely.

## Why A Worker Thread Exists

PyQt UI must remain responsive while Playwright runs async browser automation. The project uses a `QThread` with a QObject worker. The worker creates its own asyncio loop and runs the engine there.

## Flow

```text
MainWindow._start_automation()
  -> self._worker = AutomationWorker(...)
  -> self._thread = QThread()
  -> worker.moveToThread(thread)
  -> thread.started.connect(worker.run)
  -> worker signals connected to UI slots
  -> thread.start()
```

`AutomationWorker.run()`:

```text
new_event_loop()
set_event_loop(loop)
AutomationEngine(...)
loop.run_until_complete(engine.run(...))
emit done_signal
shutdown_asyncgens
close loop
```

## Signals

`AutomationWorker` emits:

- `log_signal(str)` -> `MainWindow._append_log`
- `step_signal(int, str)` -> progress page step/progress update
- `done_signal(bool, str)` -> `MainWindow._on_done`

UI widgets are updated only through Qt slots/signals.

## Stop Flow

```text
Stop button
  -> MainWindow._stop_automation()
  -> AutomationWorker.stop()
  -> AutomationEngine.request_stop()
  -> engine checks _stop_requested between actions
```

This is cooperative cancellation.

## Cleanup

`MainWindow._on_done()`:

- Re-enables start button.
- Disables stop button.
- Logs final message.
- Updates status/progress.
- Calls `thread.quit()`.
- Waits up to 2 seconds.
- Calls `deleteLater()` on thread/worker.

## Important Warnings

- Do not call PyQt widget methods directly from Playwright coroutines.
- Do not reuse the main Qt event loop for Playwright.
- Do not close the browser aggressively in `finally`; engine deliberately relies on Playwright context cleanup and manual review.
- Do not make stop destructive. Stop should request safe shutdown, not kill mid-upload.
- Avoid blocking calls in UI slots.


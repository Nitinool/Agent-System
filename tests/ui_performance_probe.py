"""Manual Tk timing probe: python -m tests.ui_performance_probe.

Uses disposable data (1,500 tasks / 150 Today rows), no credentials or capture.
Times include cProfile overhead and idle layout; they are not CI thresholds.
"""

import cProfile
from datetime import date
import io
from pathlib import Path
import pstats
import tempfile
import time
import tkinter as tk

from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.ui.app import LoggerApp
from tests.ui_smoke import FixtureReader


def main():
    with tempfile.TemporaryDirectory() as directory:
        service = ActivityService(Store(Path(directory) / 'probe.sqlite3'), FixtureReader())
        day = date(2026, 10, 13)
        service.tasks.today = lambda: day
        with service.store.db:
            service.store.db.executemany('INSERT INTO tasks(title, planned_on) VALUES (?, ?)',
                                        ((f'测试事项 {n}', day.isoformat()) for n in range(1500)))
            service.store.db.executemany('INSERT INTO task_day_entries(task_id,day) VALUES(?,?)',
                                        ((n, day.isoformat()) for n in range(1, 151)))
        root = tk.Tk()
        root.withdraw()
        app = None
        profile = cProfile.Profile()
        try:
            profile.enable()
            start = time.perf_counter()
            app = LoggerApp(root, service)
            root.update_idletasks()
            print('startup_ms', round((time.perf_counter() - start) * 1000, 1))
            for page in ('home', 'tasks', 'home', 'projects', 'home'):
                start = time.perf_counter()
                app.select_page(page)
                root.update_idletasks()
                print('page', page, 'ms', round((time.perf_counter() - start) * 1000, 1))
            start = time.perf_counter()
            app.home_panel.complete_task(1, True)
            root.update_idletasks()
            print('complete_task_ms', round((time.perf_counter() - start) * 1000, 1))
            root.after_cancel(app.sync_controller.status_timer)
            start = time.perf_counter()
            app.sync_controller._watch_status()
            print('sync_watch_ms', round((time.perf_counter() - start) * 1000, 1))
            profile.disable()
            output = io.StringIO()
            pstats.Stats(profile, stream=output).strip_dirs().sort_stats('cumtime').print_stats(18)
            print(output.getvalue())
        finally:
            if app is not None:
                app.close()
            else:
                service.close()
                root.destroy()


if __name__ == '__main__':
    main()

"""Exercise history suggestions in real editors with temporary data only."""

from pathlib import Path
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activitylog.finance import FinanceDraft
from activitylog.finance_service import FinanceService
from activitylog.finance_store import FinanceRepository
from activitylog.job_service import JobService
from activitylog.job_store import JobRepository
from activitylog.jobs import ApplicationDraft
from activitylog.storage import Store
from activitylog.ui.jobs import ApplicationDialog
from activitylog.ui.finance import FinanceDialog


def settle(root):
    done = tk.BooleanVar(root)
    root.after(170, lambda: done.set(True))
    root.wait_variable(done)
    root.update()


def main():
    with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / 'test.sqlite3') as store:
        jobs = JobService(JobRepository(store.db))
        jobs.save_application('华润电力', ApplicationDraft('AI Agent开发', '2026-10-01'))
        jobs.save_application('中国能源建设集团', ApplicationDraft('Python 开发', '2026-10-01'))
        root = tk.Tk()
        root.withdraw()
        root.attributes('-alpha', 0)
        root.geometry('700x480')
        root.deiconify()
        callbacks = []
        failures = []
        root.report_callback_exception = lambda kind, error, traceback: failures.append(error)
        try:
            dialog = ApplicationDialog(root, jobs, callbacks.append)
            dialog.attributes('-alpha', 0)
            root.update()
            combo = dialog.company_combo
            combo.focus_force()
            dialog.company_var.set('电力')
            settle(root)
            assert combo._visible() and combo.matches == ('华润电力',)
            assert dialog.focus_get() == combo and root.grab_current() == dialog
            assert dialog.company_var.get() == '电力'
            combo.event_generate('<Down>')
            combo.event_generate('<Return>')
            assert dialog.company_var.get() == '华润电力'
            assert not combo._visible() and dialog.winfo_exists()
            dialog.title_combo.focus_force()
            dialog.title_var.set('agent')
            settle(root)
            assert dialog.title_combo.matches == ('AI Agent开发',)
            dialog.title_combo.listbox.event_generate('<ButtonPress-1>', x=8, y=5)
            assert dialog.title_var.get() == 'AI Agent开发'
            assert dialog.focus_get() == dialog.title_combo
            combo.focus_force()
            dialog.company_var.set('中国')
            settle(root)
            assert combo._visible()
            combo.event_generate('<Escape>')
            assert dialog.winfo_exists() and not combo._visible()
            dialog.company_var.set('全新公司')
            settle(root)
            assert not combo._visible() and dialog.company_var.get() == '全新公司'
            dialog.title_var.set('全新岗位')
            dialog.submit()
            assert callbacks and jobs.snapshot().summary.applications == 3
            dialog = ApplicationDialog(root, jobs, callbacks.append)
            dialog.attributes('-alpha', 0)
            root.update()
            assert '全新公司' in dialog.company_combo['values']
            combo = dialog.company_combo
            combo.focus_force()
            dialog.company_var.set('全新')
            settle(root)
            assert combo._visible()
            dialog.title_combo.focus_force()
            root.update()
            assert not combo._visible()
            # Closing while a debounce is pending must release the trace and timer.
            dialog.title_var.set('全新')
            tracked_var = dialog.title_var
            assert tracked_var.trace_info()
            dialog.destroy()
            assert not tracked_var.trace_info()
            tracked_var.set('窗口已关闭')
            settle(root)
            finance = FinanceService(FinanceRepository(store.db))
            finance.save(FinanceDraft('收入', '100', '2026-10-01', category='副业收入',
                                      side_source='二手交易', status='待结算'))
            dialog = FinanceDialog(root, finance, callbacks.append, pending=True)
            dialog.attributes('-alpha', 0)
            root.update()
            dialog.source_combo.focus_force()
            dialog.source_var.set('交易')
            settle(root)
            assert dialog.source_combo._visible() and dialog.source_combo.matches == ('二手交易',)
            dialog.source_combo.event_generate('<Down>')
            dialog.source_combo.event_generate('<Return>')
            assert dialog.source_var.get() == '二手交易'
            dialog.category_combo.focus_force()
            dialog.category_var.set('收入')
            settle(root)
            assert dialog.category_combo._visible() and '副业收入' in dialog.category_combo.matches
            dialog.category_combo.event_generate('<Escape>')
            assert dialog.winfo_exists()
            assert str(dialog.direction_combo['state']) == 'readonly'
            assert str(dialog.status_combo['state']) == 'readonly'
            dialog.destroy()
            settle(root)
            assert not failures, failures
        finally:
            root.destroy()
    print('Autocomplete UI smoke OK: automatic suggestions, typing focus, click/keys, free input, history, modal grab, cleanup, finance.')


if __name__ == '__main__':
    main()

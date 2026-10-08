"""Home flows and visible layout with disposable records and a fixed reader."""

from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.finance import FinanceDraft
from activitylog.models import Activity
from activitylog.projects import MilestoneDraft, ProjectDraft
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.tasks import TaskDraft
from activitylog.ui.app import LoggerApp
from activitylog.ui.app_time import app_color
from tests.ui_smoke import FixtureReader


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        failures = []
        root.report_callback_exception = lambda kind, error, trace: failures.append(error)
        service = ActivityService(Store(Path(directory) / 'home.sqlite3'), FixtureReader())
        day = [date(2026, 10, 8)]
        service.tasks.today = lambda: day[0]
        app = LoggerApp(root, service)
        home = app.home_panel
        try:
            assert app.current_page == 'home' and not app.running
            assert not hasattr(app.tasks_panel, 'today_list')
            assert not hasattr(app.tasks_panel, 'quick_title')
            assert not home.time_chart.pie.find_withtag('slice')
            assert home.time_chart.pie.find_withtag('empty')
            project = service.projects.save(ProjectDraft('主页验证项目', priority='高'))
            milestone = service.projects.save_milestone(project, MilestoneDraft('搭建首页'))
            task = service.tasks.save(TaskDraft('共享阶段事项', '2026-10-08', project_id=project,
                                       milestone_id=milestone, range_start='2026-10-08', range_end='2026-10-10'), in_today=None)
            service.finance.save(FinanceDraft('收入', '230.10', '2026-10-01', status='已到账'))
            service.finance.save(FinanceDraft('支出', '68.50', '2026-10-01'))
            service.finance.save(FinanceDraft('收入', '800', '2026-10-01', status='待结算', side_source='二手交易'))
            begin = datetime(2026, 10, 8, 10).astimezone()
            for process, seconds in (('chrome.exe', 180), ('msedge.exe', 60)):
                identifier = service.store.begin(Activity(process, '固定测试标题'), begin)
                service.store.finish(identifier, begin + timedelta(seconds=seconds), seconds)
            home.refresh()
            root.update_idletasks()
            assert home.income.get() == '¥230.10' and home.expense.get() == '¥68.50'
            assert len(home.today_list.checks) == 1
            assert home.today_list.checks[task][1]['text'].startswith('[' + service.projects.get(project).code + ']')
            assert len(home.time_chart.pie.find_withtag('slice')) == 2
            assert home.time_chart.total == 240
            assert len(home.time_chart.table.get_children()) == 2
            assert app_color('浏览器 · Chrome') == app_color('浏览器 · Chrome')
            home.time_chart.choose('app-0')
            assert '75.0%' in home.time_chart.detail.get()
            assert 'Chrome' in home.time_chart.detail.get()

            # Recording filters / another viewed date never change today's pie.
            app.date_text.set('2026-10-07')
            app.apply_date()
            app.filter_keyword.set('不会匹配')
            app.refresh()
            assert home.time_chart.total == 240
            home.today_list.checks[task][1].invoke()
            assert service.tasks.get(task).completed and task not in home.today_list.checks
            assert home.project_rows[project]['label']['text'].startswith('100%')
            service.tasks.complete(task, False)
            home.refresh()
            with patch.object(service.tasks, 'complete', side_effect=sqlite3.OperationalError('写入失败')):
                home.today_list.checks[task][1].invoke()
            assert not home.today_list.checks[task][0].get()
            assert home.error.get() == '写入失败'
            home.remove_today(task)
            assert task not in home.today_list.checks and service.tasks.get(task).title == '共享阶段事项'

            picker = home.choose_task()
            assert root.grab_current() == picker
            picker.keyword.set('共享阶段')
            assert picker.table.get_children() == (str(task),)
            picker.table.selection_set(str(task))
            picker.submit()
            assert service.tasks.is_in_today(task) and task in home.today_list.checks
            assert len(service.projects.completion_records(project)) == 1
            dialog = home.edit_task(task)
            dialog.notes.insert('1.0', '主页编辑的备注')
            dialog.submit()
            assert service.tasks.get(task).notes == '主页编辑的备注'
            assert service.tasks.get(task).milestone_id == milestone
            home.quick_title.set('新增今日事项')
            home.quick_button.invoke()
            added = next(t for t in home.snapshot.tasks if t.title == '新增今日事项')
            assert home.quick_title.get() == ''
            home.today_list.checks[added.id][1].invoke()
            home.hide_completed.set(True)
            home._display_today()
            assert added.id not in home.today_list.checks and '已完成 1 / 2' in home.today_count.get()
            home.hide_completed.set(False)
            home._display_today()
            assert added.id in home.today_list.checks

            for index in range(30):
                service.tasks.add_today(f'多条待办 {index}')
            home.refresh()
            root.attributes('-topmost', True)
            root.deiconify()
            root.lift()
            for geometry in ('1440x880', '1100x700'):
                root.geometry(geometry + '+30+30')
                app.select_page('home')
                root.update()
                root.update_idletasks()
                assert home.records_panel.winfo_width() == home.content.winfo_width()
                assert home.records_panel.winfo_y() >= home.todo_panel.winfo_y() + home.todo_panel.winfo_height()
                assert home.records_panel.winfo_y() >= home.projects_panel.winfo_y() + home.projects_panel.winfo_height()
                assert home.records_panel.winfo_y() + home.records_panel.winfo_height() <= home.content.winfo_height()
                assert home.today_list.canvas.winfo_height() >= 150
                assert home.today_list.body.winfo_height() > home.today_list.canvas.winfo_height()
                assert home.time_chart.table.winfo_width() >= 400
                if '--screenshots' in sys.argv:
                    from PIL import ImageGrab
                    destination = Path('data') / f'home-preview-{geometry}.png'
                    root.lift()
                    root.attributes('-topmost', True)
                    root.update()
                    desktop = ImageGrab.grab()
                    scale_x = desktop.width / root.winfo_screenwidth()
                    scale_y = desktop.height / root.winfo_screenheight()
                    bounds = (round(root.winfo_rootx() * scale_x), round(root.winfo_rooty() * scale_y),
                              round((root.winfo_rootx() + root.winfo_width()) * scale_x),
                              round((root.winfo_rooty() + root.winfo_height()) * scale_y))
                    desktop.crop(bounds).save(destination)
                for widget in (home.quick_button, home.time_chart.table):
                    x = widget.winfo_rootx() + widget.winfo_width() // 2
                    y = widget.winfo_rooty() + widget.winfo_height() // 2
                    assert root.winfo_containing(x, y) == widget, (geometry, str(widget), x, y,
                                                                  root.geometry(), root.winfo_screenwidth(), root.winfo_screenheight())

            # A single app draws a full disk; zero data draws an empty state.
            service.tasks.today = lambda: date(2026, 10, 9)
            begin = datetime(2026, 10, 9, 12).astimezone()
            identifier = service.store.begin(Activity('code.exe', '唯一应用'), begin)
            service.store.finish(identifier, begin + timedelta(seconds=12), 12)
            home.refresh()
            assert len(home.time_chart.pie.find_withtag('slice')) == 1
            assert home.time_chart.pie.type(home.time_chart.pie.find_withtag('slice')[0]) == 'oval'
            assert task in home.today_list.checks  # Day-only exclusion does not extend.
            service.tasks.today = lambda: date(2026, 11, 1)
            home.after_cancel(home.day_timer)
            home.day_timer = None
            home._check_day()
            assert home.snapshot.day == date(2026, 11, 1)
            assert home.finance_title.get() == '2026 年 11 月'
            assert not home.today_list.checks and home.time_chart.total == 0
            assert home.income.get() == home.expense.get() == '¥0.00'
            assert not failures, failures
            app.select_page('records')
            home.record_button.invoke()
            timer = app.timer
            app.select_page('home')
            assert app.running and app.timer == timer
            assert home.record_button['text'] == app.toggle_button['text'] == '暂停记录'
            home.record_button.invoke()
            assert not app.running and home.record_button['text'] == app.toggle_button['text'] == '开始记录'
        finally:
            app.close()
        assert home.day_timer is None
    print('Dashboard UI smoke passed: default Home, shared Today, monthly totals, pie, dates, layout and cleanup.')


if __name__ == '__main__':
    main()

"""Hidden ledger and settlement workflow using temporary data and fixed readers."""

from datetime import date
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from activitylog.service import ActivityService
from activitylog.storage import Store
from activitylog.ui.app import LoggerApp
from tests.ui_smoke import FixtureReader


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        root.withdraw()
        path = Path(directory) / "finance.sqlite3"
        app = LoggerApp(root, ActivityService(Store(path), FixtureReader()))
        try:
            app.toggle()
            app.select_page("finance")
            assert app.running
            panel = app.finance_panel
            dialog = panel.add_pending()
            dialog.amount_var.set("100.125")
            dialog.source_var.set("二手交易")
            dialog.submit()
            assert dialog.winfo_exists() and dialog.error.get()
            dialog.amount_var.set("1500.50")
            dialog.date_var.set("2026-09-30")
            dialog.title_var.set("卖出耳机")
            dialog.notes.insert("1.0", "等待平台打款")
            assert str(dialog.settled_entry["state"]) == "disabled"
            dialog.submit()
            assert len(panel.pending_table.get_children()) == 1
            assert "到账收入 ¥0.00" in panel.summary.get()
            assert "¥1,500.50" in panel.summary.get()
            identifier = app.service.finance.repository.entries()[0].id
            panel.this_month()
            assert len(panel.pending_table.get_children()) == 1
            panel.notebook.select(panel.pending_tab)
            panel.pending_table.selection_set(f"finance-{identifier}")
            panel._selection_changed()
            assert str(panel.settle_button["state"]) == "normal"
            dialog = panel.settle_entry()
            dialog.amount_var.set("1450.25")
            dialog.settled_var.set("2026-10-05")
            dialog.submit()
            assert len(panel.pending_table.get_children()) == 0
            assert app.service.finance.get(identifier).occurred_on == date(2026, 9, 30)
            assert "到账收入 ¥1,450.25" in panel.summary.get()
            assert len(app.service.finance.repository.entries()) == 1
            dialog = panel.add_entry("支出")
            dialog.amount_var.set("100.10")
            dialog.date_var.set("2026-10-05")
            dialog.settled_var.set("2026-10-05")
            dialog.source_var.set("二手交易")
            dialog.title_var.set("运费与工具")
            dialog.category_var.set("副业成本")
            dialog.submit()
            assert "收支结余 ¥1,350.15" in panel.summary.get()
            assert panel.side_table.item("source-0", "values")[3] == "¥1,350.15"
            panel.keyword.set("不存在的内容")
            panel.refresh()
            assert len(panel.table.get_children()) == 0
            assert "收支结余 ¥1,350.15" in panel.summary.get()
            panel.clear_filters()
            panel.month_var.set("2026-09")
            panel.refresh()
            assert "到账收入 ¥0.00" in panel.summary.get()
            panel.move_month(1)
            assert panel.month_var.get() == "2026-10"
            panel.table.selection_set(f"finance-{identifier}")
            panel._selection_changed()
            dialog = panel.edit_entry()
            dialog.title_var.set("确认耳机款")
            dialog.submit()
            assert app.service.finance.get(identifier).title == "确认耳机款"
            with patch("activitylog.ui.finance.messagebox.askyesno", return_value=False):
                panel.delete_entry()
            assert len(app.service.finance.repository.entries()) == 2
            assert app.running
        finally:
            app.close()
        root = tk.Tk()
        root.withdraw()
        app = LoggerApp(root, ActivityService(Store(path), FixtureReader()))
        try:
            app.select_page("finance")
            panel = app.finance_panel
            panel.all_months()
            assert len(panel.table.get_children()) == 2
            panel.table.selection_set(f"finance-{identifier}")
            panel._selection_changed()
            with patch("activitylog.ui.finance.messagebox.askyesno", return_value=True):
                panel.delete_entry()
            assert len(panel.table.get_children()) == 1
            panel.move_month(1)
            panel.month_var.set("2026-13")
            panel.refresh()
            assert panel.error.get()
        finally:
            app.close()
    print("Finance UI smoke passed: ledger, pending income, actual settlement dates and amounts, source costs, filters, deletion, persistence and continued capture.")


if __name__ == "__main__":
    main()

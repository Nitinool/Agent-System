"""One priority palette shared by tables, the calendar and today's list."""

import tkinter as tk
from tkinter import ttk

PRIORITY_COLORS = {
    "紧急": ("#d92d20", "#e5aaa6"),
    "高": ("#e58b16", "#e8c49a"),
    "普通": ("#2e62b8", "#a7bfdf"),
    "低": ("#858e9a", "#bec5cd"),
}


def priority_color(priority, completed=False):
    return PRIORITY_COLORS[priority][int(completed)]


class PriorityDots:
    """Treeview images retain their Tk references for the life of the table."""

    def __init__(self, master):
        style = ttk.Style(master)
        # Remove reserved expand-arrow space so the small dot fits its column.
        style.layout("Priority.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"side": "left", "sticky": ""}),
        ]})])
        style.configure("Priority.Treeview", rowheight=29)
        self.images = {}
        for priority in PRIORITY_COLORS:
            for completed in (False, True):
                image = tk.PhotoImage(master=master, width=12, height=12)
                color = priority_color(priority, completed)
                for y in range(12):
                    for x in range(12):
                        if (x - 5.5) ** 2 + (y - 5.5) ** 2 <= 20:
                            image.put(color, (x, y))
                self.images[priority, completed] = image

    def for_task(self, task):
        return self.images[task.priority, task.completed]

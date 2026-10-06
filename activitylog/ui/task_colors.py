"""Stable local item colors, unrelated to task priority."""
import tkinter as tk
from .priority import PriorityDots

TASK_COLORS = ('#2563eb', '#d97706', '#7c3aed', '#059669', '#db2777', '#0891b2',
               '#dc2626', '#4f46e5', '#65a30d', '#c026d3', '#0d9488', '#9333ea')


def task_color(task):
    color = TASK_COLORS[(task.id - 1) % len(TASK_COLORS)]
    if task.completed:
        channels = (int(color[i:i+2], 16) for i in (1, 3, 5))
        return '#' + ''.join(f'{round(channel * .4 + 255 * .6):02x}' for channel in channels)
    return color


class TaskDots(PriorityDots):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.task_images = {}

    def for_task(self, task):
        color = task_color(task)
        if color not in self.task_images:
            image = tk.PhotoImage(master=self.master, width=12, height=12)
            for y in range(12):
                for x in range(12):
                    if (x - 5.5) ** 2 + (y - 5.5) ** 2 <= 20:
                        image.put(color, (x, y))
            self.task_images[color] = image
        return self.task_images[color]

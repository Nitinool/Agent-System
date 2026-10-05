"""Editable history suggestions that keep typing and IME focus in the entry."""

import tkinter as tk
from tkinter import ttk


def matching_history(values, query):
    """Keep history order within prefix/substring matches, deduplicated."""
    query = query.strip().casefold()
    unique, seen = [], set()
    for value in values:
        value = str(value).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    prefix = [value for value in unique if value.casefold().startswith(query)]
    contains = [value for value in unique if query in value.casefold() and not value.casefold().startswith(query)]
    return tuple(prefix + contains)


class HistoryCombobox(ttk.Combobox):
    """The native arrow retains all history; typing shows a filtered overlay."""

    def __init__(self, master, *, textvariable=None, values=(), **options):
        self.variable = textvariable if textvariable is not None else tk.StringVar(master)
        super().__init__(master, textvariable=self.variable, values=values, state="normal", **options)
        self.matches = ()
        self.popup = None
        self.listbox = None
        self.timer = None
        self.closed = False
        self.trace = self.variable.trace_add("write", self._changed)
        self.bind("<Down>", lambda event: self._move(1))
        self.bind("<Up>", lambda event: self._move(-1))
        self.bind("<Return>", self._enter)
        self.bind("<Escape>", self._escape)
        self.bind("<Tab>", lambda event: self.hide_suggestions())
        self.bind("<FocusOut>", lambda event: self.hide_suggestions())
        self.bind("<Button-1>", lambda event: self.hide_suggestions())
        self.bind("<<ComboboxSelected>>", lambda event: self.hide_suggestions())
        self.bind("<Unmap>", lambda event: self.hide_suggestions())
        self.bind("<Destroy>", self._destroyed)

    def _cancel_timer(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def _changed(self, *_):
        self._cancel_timer()
        if not self.closed:
            self.timer = self.after(120, self._suggest)

    def _suggest(self):
        self.timer = None
        if self.closed or self.focus_get() != self or not self.variable.get().strip():
            self.hide_suggestions()
            return
        self.show_suggestions()

    def show_suggestions(self):
        self._cancel_timer()
        if self.closed or not self.winfo_viewable() or str(self["state"]) != "normal":
            return
        self.matches = matching_history(self["values"], self.variable.get())
        if not self.matches:
            self.hide_suggestions()
            return
        parent = self.winfo_toplevel()
        if self.popup is None:
            # An overlay inside the editor avoids activating another window or
            # taking a grab while a Chinese IME is composing text.
            self.popup = ttk.Frame(parent, relief="solid", borderwidth=1)
            self.listbox = tk.Listbox(self.popup, exportselection=False, takefocus=False,
                                      font=self.cget("font"), borderwidth=0, highlightthickness=0,
                                      activestyle="dotbox")
            scrollbar = ttk.Scrollbar(self.popup, command=self.listbox.yview, takefocus=False)
            self.listbox.configure(yscrollcommand=scrollbar.set)
            self.listbox.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.listbox.bind("<ButtonPress-1>", self._clicked)
        self.listbox.delete(0, "end")
        for value in self.matches:
            self.listbox.insert("end", value)
        self.listbox.configure(height=min(6, len(self.matches)))
        self.popup.update_idletasks()
        x = self.winfo_rootx() - parent.winfo_rootx()
        top = self.winfo_rooty() - parent.winfo_rooty()
        bottom = top + self.winfo_height()
        height = self.popup.winfo_reqheight()
        below = parent.winfo_height() - bottom
        if height <= below:
            y = bottom
        elif height <= top:
            y = top - height
        else:
            height = min(height, max(top, below))
            y = bottom if below >= top else top - height
        self.popup.place(x=x, y=y, width=self.winfo_width(), height=height)
        self.popup.lift()

    def hide_suggestions(self):
        self._cancel_timer()
        if self.popup is not None:
            self.popup.place_forget()

    def _visible(self):
        return self.popup is not None and bool(self.popup.place_info())

    def _move(self, step):
        if not self._visible():
            self.show_suggestions()
            if not self._visible():
                return "break"
            index = 0 if step > 0 else len(self.matches) - 1
        else:
            selection = self.listbox.curselection()
            index = ((selection[0] + step) % len(self.matches)) if selection else (0 if step > 0 else len(self.matches) - 1)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)
        return "break"

    def _accept(self, index):
        self.variable.set(self.matches[index])
        self.icursor("end")
        self.hide_suggestions()
        self.event_generate("<<ComboboxSelected>>")

    def _enter(self, event):
        if not event.state & 4 and self._visible():
            selection = self.listbox.curselection()
            if selection:
                self._accept(selection[0])
            else:
                self.hide_suggestions()
            return "break"

    def _escape(self, event):
        if self._visible() or self.timer is not None:
            self.hide_suggestions()
            return "break"

    def _clicked(self, event):
        if self.matches:
            self._accept(self.listbox.nearest(event.y))
        return "break"

    def _destroyed(self, event):
        if event.widget == self and not self.closed:
            self.closed = True
            self._cancel_timer()
            self.variable.trace_remove("write", self.trace)
            if self.popup is not None:
                self.popup.destroy()

"""Native wxWidgets controls for the game's small view interface.

This is not a Tk host: every interactive widget is a real Windows control.
The narrow view methods keep game/network logic independent of GUI APIs.
"""
from __future__ import annotations

from types import SimpleNamespace
import wx


class UIError(RuntimeError):
    pass


class Value:
    def __init__(self, value=None):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        if value != self.value:
            self.value = value
            for callback in list(self.callbacks):
                callback(None, None, 'write')

    def trace_add(self, mode, callback):
        self.callbacks.append(callback)


def BooleanVar(value=False):
    return Value(bool(value))


def StringVar(value=''):
    return Value(str(value))


class AlertAccessible(wx.Accessible):
    def GetName(self, childId):
        return (wx.ACC_OK, self.GetWindow().GetLabel()) if childId == 0 else (wx.ACC_NOT_IMPLEMENTED, '')

    def GetRole(self, childId):
        return (wx.ACC_OK, wx.ROLE_SYSTEM_ALERT) if childId == 0 else (wx.ACC_NOT_IMPLEMENTED, 0)


def key_name(event):
    code = event.GetKeyCode()
    named = {wx.WXK_UP: 'Up', wx.WXK_DOWN: 'Down', wx.WXK_LEFT: 'Left', wx.WXK_RIGHT: 'Right',
             wx.WXK_ESCAPE: 'Escape', wx.WXK_RETURN: 'Return', wx.WXK_NUMPAD_ENTER: 'Return',
             wx.WXK_SPACE: 'space', wx.WXK_PAGEUP: 'Prior', wx.WXK_PAGEDOWN: 'Next', wx.WXK_F6: 'F6'}
    if code in named:
        return named[code]
    return chr(code).lower() if 32 <= code < 127 else ''


class Window:
    def __init__(self):
        self.app = wx.GetApp() or wx.App(False)
        self.native = wx.Frame(None, title='DragonPong')
        self.native._dragon_view = self
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.native.SetSizer(self.sizer)
        self.children = []
        self.bottom = 0
        self.destroyed = False
        self.timers = []
        self.callbacks = {}
        self.desired_focus = None
        self.last_announcement = ''
        self.callback_errors = []
        self.hidden = False
        self.notice = wx.StaticText(self.native, label='', name='Oyun bildirimleri')
        self.alert_accessible = AlertAccessible(self.notice)
        self.notice.SetAccessible(self.alert_accessible)
        self.sizer.Add(self.notice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.bottom = 1
        self.native.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.native.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.native.Bind(wx.EVT_SET_FOCUS, self._on_frame_focus)

    def _on_activate(self, event):
        if event.GetActive():
            self.after_idle(self._restore_focus)
        event.Skip()

    def _on_frame_focus(self, event):
        # Windows can focus the frame after its activation notification.
        self.after_idle(self._restore_focus)
        event.Skip()

    def _restore_focus(self):
        if self.destroyed or not self.native.IsActive():
            return
        focused = wx.Window.FindFocus()
        view = getattr(focused, '_dragon_view', None)
        if (focused and focused is not self.native and not isinstance(view, Panel)
                and focused.GetTopLevelParent() is self.native):
            return
        if self.desired_focus and self.desired_focus.winfo_exists():
            self.desired_focus.focus_set()

    def title(self, text=None):
        if text is None:
            return self.native.GetTitle()
        self.native.SetTitle(text)

    def geometry(self, value):
        self.native.SetClientSize(tuple(int(v) for v in value.split('x')))

    def minsize(self, width, height):
        self.native.SetMinSize((width, height))

    def protocol(self, name, callback):
        self.native.Bind(wx.EVT_CLOSE, lambda event: callback())

    def announce(self, text):
        self.last_announcement = str(text)
        self.notice.SetLabel(str(text))
        self.notice.Wrap(max(200, self.native.GetClientSize().width - 24))
        self.native.Layout()
        wx.Accessible.NotifyEvent(wx.ACC_EVENT_SYSTEM_ALERT, self.notice, wx.OBJID_CLIENT, 0)

    def clear_announcement(self):
        self.last_announcement = ''
        if self.notice.GetLabel():
            self.notice.SetLabel('')
            self.native.Layout()

    def _on_key(self, event):
        focused = wx.Window.FindFocus()
        widget = getattr(focused, '_dragon_view', None)
        # A frame can briefly own focus while returning from another app.
        # Its view is a Window, which has no per-widget event callbacks.
        if not isinstance(widget, Widget):
            widget = None
        if isinstance(widget, Canvas) and event.GetKeyCode() == wx.WXK_TAB:
            focused.Navigate(wx.NavigationKeyEvent.IsBackward if event.ShiftDown()
                             else wx.NavigationKeyEvent.IsForward)
            return
        key = key_name(event)
        wrapped = SimpleNamespace(keysym=key, widget=widget)
        if widget and widget.emit('<' + key + '>', wrapped) == 'break':
            return
        # Native buttons retain their own Space action.
        if widget and isinstance(widget, Button) and key == 'space':
            event.Skip()
            return
        result = self.callbacks.get('<KeyPress>', lambda e: None)(wrapped)
        if result == 'break':
            return
        if isinstance(widget, Canvas) and key.lower() in ('up', 'space', 'left', 'right', 'a', 'd', 'prior', 'next'):
            return
        event.Skip()

    def bind_all(self, name, callback):
        self.callbacks[name] = callback

    def after(self, delay, callback):
        if self.destroyed:
            return None
        def guarded():
            if not self.destroyed:
                try:
                    callback()
                except Exception as exc:
                    self.callback_errors.append(f'{type(exc).__name__}: {exc}')
                    raise
        timer = wx.CallLater(delay, guarded)
        self.timers = [t for t in self.timers if t.IsRunning()]
        self.timers.append(timer)
        return timer

    def after_idle(self, callback):
        wx.CallAfter(lambda: callback() if not self.destroyed else None)

    def focus_displayof(self):
        return wx.Window.FindFocus() if self.native.IsActive() else None

    def withdraw(self):
        self.hidden = True
        self.native.Hide()

    def bell(self):
        wx.Bell()

    def mainloop(self):
        self.native.Layout()
        if not self.hidden:
            self.native.Show()
        if self.desired_focus and not self.hidden:
            self.after_idle(self.desired_focus.focus_set)
        self.app.MainLoop()

    def destroy(self):
        if self.destroyed:
            return
        self.destroyed = True
        for timer in self.timers:
            if timer.IsRunning():
                timer.Stop()
        for child in list(self.children):
            child.destroy()
        self.native.Destroy()
        self.app.ProcessPendingEvents()
        self.app.Yield(True)


class Widget:
    kind = 'Widget'

    def __init__(self, parent, native):
        self.parent, self.native = parent, native
        self.root = parent if isinstance(parent, Window) else parent.root
        self.native._dragon_view = self
        self.children = []
        self.callbacks = {}
        self.destroyed = False
        self.bottom = 0
        self.packed_bottom = False
        parent.children.append(self)
        self.native.Bind(wx.EVT_KEY_UP, self._key_up)
        self.native.Bind(wx.EVT_SET_FOCUS, self._remember_focus)

    def _remember_focus(self, event):
        if self.kind != 'Panel':
            self.root.desired_focus = self
        event.Skip()

    def _key_up(self, event):
        callback = self.root.callbacks.get('<KeyRelease>')
        if callback:
            callback(SimpleNamespace(keysym=key_name(event), widget=self))
        event.Skip()

    def emit(self, name, event=None):
        result = None
        for callback in self.callbacks.get(name, []):
            result = callback(event or SimpleNamespace(widget=self))
            if result == 'break':
                break
        return result

    def bind(self, name, callback=None, add=None):
        if callback is None:
            return bool(self.callbacks.get(name))
        self.callbacks.setdefault(name, [])
        if not add:
            self.callbacks[name] = []
        self.callbacks[name].append(callback)
        native_events = {'<FocusOut>': wx.EVT_KILL_FOCUS, '<FocusIn>': wx.EVT_SET_FOCUS,
                         '<Button-1>': wx.EVT_LEFT_DOWN, '<MouseWheel>': wx.EVT_MOUSEWHEEL}
        if len(self.callbacks[name]) == 1 and name in native_events:
            def on_event(event):
                wrapped = SimpleNamespace(widget=self, delta=event.GetWheelRotation() if name == '<MouseWheel>' else 0)
                self.emit(name, wrapped)
                event.Skip()
            self.native.Bind(native_events[name], on_event)

    def pack(self, fill=None, expand=False, pady=0, side='top', anchor=None):
        border = int(pady) if isinstance(pady, (int, float)) else int(pady[0])
        flags = wx.TOP | wx.BOTTOM
        if fill in ('x', 'both'):
            flags |= wx.EXPAND
        else:
            flags |= wx.ALIGN_LEFT
        sizer = self.parent.sizer
        if side == 'bottom':
            sizer.Add(self.native, 0, flags, border)
            self.parent.bottom += 1
            self.packed_bottom = True
        else:
            sizer.Insert(max(0, sizer.GetItemCount() - self.parent.bottom), self.native,
                         1 if expand else 0, flags, border)
        self.parent.native.Layout()

    def focus_set(self):
        if not self.destroyed:
            self.root.desired_focus = self
            self.native.SetFocus()

    def winfo_exists(self):
        return not self.destroyed

    def winfo_children(self):
        return list(self.children)

    def winfo_class(self):
        return self.kind

    def destroy(self):
        if self.destroyed:
            return
        for child in list(self.children):
            child.destroy()
        self.destroyed = True
        self.parent.sizer.Detach(self.native)
        if self.packed_bottom:
            self.parent.bottom -= 1
        if self in self.parent.children:
            self.parent.children.remove(self)
        self.native.Destroy()

    def keys(self):
        return ['text']

    def cget(self, name):
        if name == 'text':
            return self.native.GetLabelText()
        raise KeyError(name)

    def config(self, **values):
        if 'text' in values and self.native.GetLabel() != str(values['text']):
            self.native.SetLabel(str(values['text']))
            self.parent.native.Layout()


class Panel(Widget):
    kind = 'Panel'

    def __init__(self, parent, padding=0):
        super().__init__(parent, wx.Panel(parent.native, name='DragonPong ekranı'))
        outer = wx.BoxSizer(wx.VERTICAL)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.sizer, 1, wx.EXPAND | wx.ALL, padding)
        self.native.SetSizer(outer)


class Label(Widget):
    kind = 'Label'

    def __init__(self, parent, text='', font=None, foreground=None, wraplength=None):
        super().__init__(parent, wx.StaticText(parent.native, label=text))
        if font:
            self.native.SetFont(wx.Font(wx.FontInfo(font[1]).FaceName(font[0])))
        if foreground:
            self.native.SetForegroundColour(foreground)
        if wraplength:
            self.native.Wrap(wraplength)


class Button(Widget):
    kind = 'Button'

    def __init__(self, parent, text, command):
        super().__init__(parent, wx.Button(parent.native, label=text))
        self.command = command
        self.native.Bind(wx.EVT_BUTTON, lambda event: self.invoke())

    def invoke(self):
        return self.command()


class Entry(Widget):
    kind = 'Entry'

    def __init__(self, parent, name=''):
        super().__init__(parent, wx.TextCtrl(parent.native, name=name))

    def get(self):
        if self.destroyed:
            raise UIError('Entry is closed')
        return self.native.GetValue()

    def delete(self, first, last=None):
        self.native.ChangeValue('')

    def insert(self, index, value):
        self.native.ChangeValue(str(value))


class ComboBox(Widget):
    kind = 'ComboBox'

    def __init__(self, parent, values, state='readonly', name=''):
        super().__init__(parent, wx.Choice(parent.native, choices=list(values), name=name))
        self.native.Bind(wx.EVT_CHOICE, lambda event: self.emit('<<ComboboxSelected>>'))

    def current(self, index=None):
        if index is None:
            return self.native.GetSelection()
        self.native.SetSelection(index)

    def get(self):
        return self.native.GetStringSelection()

    def set(self, value):
        self.native.SetStringSelection(str(value))

    def __getitem__(self, key):
        if key == 'values':
            return self.native.GetItems()
        raise KeyError(key)


class CheckBox(Widget):
    kind = 'CheckBox'

    def __init__(self, parent, textvariable, variable):
        super().__init__(parent, wx.CheckBox(parent.native, label=textvariable.get()))
        self.variable, self.textvariable = variable, textvariable
        self.native.SetValue(variable.get())
        self.native.Bind(wx.EVT_CHECKBOX, lambda event: variable.set(self.native.GetValue()))
        variable.trace_add('write', lambda *_: self.native.SetValue(variable.get()) if not self.destroyed else None)
        textvariable.trace_add('write', lambda *_: self.config(text=textvariable.get()) if not self.destroyed else None)

    def invoke(self):
        self.variable.set(not self.variable.get())


class ListBox(Widget):
    kind = 'ListBox'

    def __init__(self, parent, height=12, name='Odalar'):
        super().__init__(parent, wx.ListBox(parent.native, name=name))
        self.native.SetMinSize((-1, height * 18))
        self.native.Bind(wx.EVT_LISTBOX, lambda event: self.emit('<<ListboxSelect>>'))

    def curselection(self):
        selected = self.native.GetSelection()
        return () if selected == wx.NOT_FOUND else (selected,)

    def selection_set(self, index):
        self.native.SetSelection(index)

    def selection_clear(self, first, last=None):
        self.native.SetSelection(wx.NOT_FOUND)

    def delete(self, first, last=None):
        self.native.Clear()

    def insert(self, index, text):
        self.native.Append(str(text))

    def get(self, index):
        return self.native.GetString(index)


class Canvas(Widget):
    kind = 'Canvas'

    def __init__(self, parent, background, highlightthickness=0):
        super().__init__(parent, wx.Panel(parent.native, style=wx.WANTS_CHARS,
                                         name='Oyun sahası: oklarla hareket, boşlukla vuruş'))
        self.background = background
        self.commands = []
        self.native.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.native.SetMinSize((200, 200))
        self.native.Bind(wx.EVT_PAINT, self._paint)

    def winfo_width(self):
        return self.native.GetClientSize().width

    def winfo_height(self):
        return self.native.GetClientSize().height

    def delete(self, what):
        self.commands = []

    def create_rectangle(self, *coords, **style):
        self.commands.append(('rectangle', coords, style))

    def create_line(self, *coords, **style):
        self.commands.append(('line', coords, style))

    def create_oval(self, *coords, **style):
        self.commands.append(('oval', coords, style))
        self.native.Refresh(False)

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self.native)
        dc.SetBackground(wx.Brush(self.background))
        dc.Clear()
        for kind, coords, style in self.commands:
            x1, y1, x2, y2 = (round(value) for value in coords)
            colour = style.get('fill') if kind == 'line' else style.get('outline')
            dc.SetPen(wx.Pen(colour or self.background, style.get('width', 1),
                             wx.PENSTYLE_SHORT_DASH if style.get('dash') else wx.PENSTYLE_SOLID))
            dc.SetBrush(wx.Brush(style['fill']) if kind != 'line' and style.get('fill') else wx.TRANSPARENT_BRUSH)
            if kind == 'line':
                dc.DrawLine(x1, y1, x2, y2)
            elif kind == 'oval':
                dc.DrawEllipse(x1, y1, x2 - x1, y2 - y1)
            else:
                dc.DrawRectangle(x1, y1, x2 - x1, y2 - y1)

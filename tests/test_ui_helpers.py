from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import app


class RecordingImage:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.put_calls: list[tuple[str, tuple[int, int, int, int]]] = []

    def put(self, color, *, to):
        self.put_calls.append((color, to))


class BindingWidget:
    def __init__(self):
        self.bindings = {}

    def bind(self, event, callback, add=None):
        self.bindings[event] = (callback, add)

    def winfo_rootx(self):
        return 30

    def winfo_rooty(self):
        return 40

    def winfo_height(self):
        return 20


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "expected_calls"),
    [
        ("pause", 2),
        ("resume", 6),
        ("stop", 1),
        ("load", 3),
        ("generate", 4),
        ("options", 6),
        ("unknown", 0),
    ],
)
def test_make_playback_icon_draws_the_expected_control_shape(kind, expected_calls):
    with patch("app.PhotoImage", RecordingImage):
        image = app.make_playback_icon("root", kind)

    assert image.kwargs == {"master": "root", "width": 16, "height": 16}
    assert len(image.put_calls) == expected_calls
    assert all(color in {app.ACCENT, app.TEXT_BG} for color, _ in image.put_calls)


@pytest.mark.unit
def test_tooltip_shows_only_once_and_is_destroyed_on_leave():
    widget = BindingWidget()
    popup = MagicMock()
    label = MagicMock()
    with patch("app.Toplevel", return_value=popup) as top_level, patch("app.ttk.Label", return_value=label) as label_factory:
        app.add_tooltip(widget, "Load a text file")
        enter, add = widget.bindings["<Enter>"]
        leave, leave_add = widget.bindings["<Leave>"]

        enter()
        enter()
        leave()

    assert add == leave_add == "+"
    top_level.assert_called_once_with(widget)
    popup.wm_overrideredirect.assert_called_once_with(True)
    popup.geometry.assert_called_once_with("+30+64")
    label_factory.assert_called_once_with(popup, text="Load a text file", padding=(6, 3))
    label.pack.assert_called_once_with()
    popup.destroy.assert_called_once_with()


@pytest.mark.unit
def test_message_helpers_restore_owner_topmost_state():
    parent = MagicMock()
    with (
        patch("app.messagebox.showerror", return_value="error") as show_error,
        patch("app.messagebox.askyesno", return_value=1) as ask_yes_no,
    ):
        assert app.show_error(parent, "Failure", "Details") == "error"
        assert app.ask_yes_no(parent, "Continue?", "Proceed") is True

    parent.deiconify.assert_called()
    parent.lift.assert_called()
    parent.update_idletasks.assert_called()
    assert parent.attributes.call_args_list[-1].args == ("-topmost", False)
    show_error.assert_called_once_with("Failure", "Details", parent=parent)
    ask_yes_no.assert_called_once_with("Continue?", "Proceed", parent=parent)


@pytest.mark.unit
def test_resolve_system_theme_uses_gtk_and_safe_fallback(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setenv("GTK_THEME", "Adwaita-dark")
    assert app.resolve_theme("system") == "dark"

    monkeypatch.delenv("GTK_THEME")
    assert app.resolve_theme("system") == "light"
    assert app.resolve_theme("high_contrast") == "high_contrast"

    monkeypatch.setattr(app.os, "environ", MagicMock(get=MagicMock(side_effect=OSError("unavailable"))))
    assert app.resolve_theme("system") == "light"


@pytest.mark.unit
def test_context_menu_and_validated_entry_wire_interactions():
    widget = BindingWidget()
    menu = MagicMock()
    with patch("app.Menu", return_value=menu):
        app.add_context_menu(widget)

    assert menu.add_command.call_count == 4
    menu.add_separator.assert_called_once_with()
    show_menu, _ = widget.bindings["<Button-3>"]
    event = MagicMock(x_root=7, y_root=11)
    show_menu(event)
    menu.tk_popup.assert_called_once_with(7, 11)
    menu.grab_release.assert_called_once_with()

    parent = MagicMock()
    entry = MagicMock()
    with patch("app.ttk.Entry", return_value=entry), patch("app.add_context_menu") as add_menu:
        assert app.make_validated_entry(parent, "value", validator="int") is entry
        assert app.make_validated_entry(parent, "value", validator="float") is entry
        assert app.make_validated_entry(parent, "value", validator="none") is entry

    assert parent.register.call_count == 2
    assert add_menu.call_count == 3


@pytest.mark.unit
def test_apply_theme_updates_an_existing_root_and_sentence_split_preserves_sentences():
    root = MagicMock()
    with patch("app.ttk.Style", return_value=MagicMock()):
        app.apply_theme("light", root)

    root.configure.assert_called_once_with(bg=app.THEMES["light"]["surface_bg"])
    root.update_idletasks.assert_called_once_with()
    assert app.sentence_split("First sentence.\n\nSecond sentence!") == ["First sentence.", "Second sentence!"]


@pytest.mark.unit
def test_main_creates_the_root_builds_the_app_and_starts_the_event_loop():
    root = MagicMock()
    with patch("app.Tk", return_value=root) as create_root, patch("app.App") as create_app:
        app.main()

    create_root.assert_called_once_with()
    create_app.assert_called_once_with(root)
    root.mainloop.assert_called_once_with()

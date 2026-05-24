"""Tests for Phase 8: Feature flags, audit logging, background tasks, SDUI."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest


# -----------------------------------------------------------------------
# 8.1 Feature flags
# -----------------------------------------------------------------------


class TestFeatureFlags:
    def test_defaults_only(self):
        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"terminal": False, "monitoring": True})
        assert ff.enabled("terminal") is False
        assert ff.enabled("monitoring") is True

    def test_unknown_flag_defaults_false(self):
        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"a": True})
        assert ff.enabled("nonexistent") is False

    def test_all_flags(self):
        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"a": True, "b": False})
        assert ff.all_flags() == {"a": True, "b": False}

    def test_override_from_file(self, tmp_path: Path):
        overrides_file = tmp_path / "overrides.json"
        overrides_file.write_text(json.dumps({"terminal": True}))

        from wesktop.features import FeatureFlags

        ff = FeatureFlags(
            {"terminal": False, "monitoring": True},
            overrides_path=overrides_file,
        )
        assert ff.enabled("terminal") is True
        assert ff.enabled("monitoring") is True

    def test_set_override_persists(self, tmp_path: Path):
        overrides_file = tmp_path / "overrides.json"

        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"x": False}, overrides_path=overrides_file)
        ff.set_override("x", True)

        assert ff.enabled("x") is True
        data = json.loads(overrides_file.read_text())
        assert data["x"] is True

    def test_set_override_without_path_raises(self):
        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"x": False})
        with pytest.raises(RuntimeError, match="no overrides_path"):
            ff.set_override("x", True)

    def test_reload(self, tmp_path: Path):
        overrides_file = tmp_path / "overrides.json"
        overrides_file.write_text(json.dumps({"y": True}))

        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"y": False}, overrides_path=overrides_file)
        assert ff.enabled("y") is True

        # Delete the file and reload
        overrides_file.unlink()
        ff.reload()
        assert ff.enabled("y") is False

    def test_malformed_file_uses_defaults(self, tmp_path: Path):
        overrides_file = tmp_path / "overrides.json"
        overrides_file.write_text("not valid json!!!")

        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"z": True}, overrides_path=overrides_file)
        assert ff.enabled("z") is True

    def test_all_flags_with_override(self, tmp_path: Path):
        overrides_file = tmp_path / "overrides.json"
        overrides_file.write_text(json.dumps({"a": False}))

        from wesktop.features import FeatureFlags

        ff = FeatureFlags({"a": True, "b": True}, overrides_path=overrides_file)
        assert ff.all_flags() == {"a": False, "b": True}


# -----------------------------------------------------------------------
# 8.2 Audit logging
# -----------------------------------------------------------------------


class TestAuditLog:
    def test_log_creates_file(self, tmp_path: Path):
        from wesktop.audit import AuditLog

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLog(log_file)
        audit.log("test_event", {"key": "value"})

        assert log_file.exists()

    def test_log_appends_entries(self, tmp_path: Path):
        from wesktop.audit import AuditLog

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLog(log_file)
        audit.log("event_a", {"n": 1})
        audit.log("event_b", {"n": 2})
        audit.log("event_c")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3

        entries = [json.loads(line) for line in lines]
        assert entries[0]["event_type"] == "event_a"
        assert entries[0]["payload"] == {"n": 1}
        assert entries[1]["event_type"] == "event_b"
        assert entries[2]["event_type"] == "event_c"
        assert "payload" not in entries[2]

    def test_entries_have_iso_timestamp(self, tmp_path: Path):
        from wesktop.audit import AuditLog

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLog(log_file)
        audit.log("ts_test")

        entry = json.loads(log_file.read_text().strip())
        # ISO 8601 format check
        assert "T" in entry["timestamp"]
        assert entry["timestamp"].endswith("+00:00")

    def test_thread_safety(self, tmp_path: Path):
        from wesktop.audit import AuditLog

        log_file = tmp_path / "audit.jsonl"
        audit = AuditLog(log_file)
        n_threads = 10
        n_events = 50

        def writer(tid: int) -> None:
            for i in range(n_events):
                audit.log("thread_event", {"tid": tid, "i": i})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == n_threads * n_events

    def test_nested_directory_created(self, tmp_path: Path):
        from wesktop.audit import AuditLog

        log_file = tmp_path / "deep" / "nested" / "audit.jsonl"
        audit = AuditLog(log_file)
        audit.log("deep_event")

        assert log_file.exists()


# -----------------------------------------------------------------------
# 8.3 Background task registry
# -----------------------------------------------------------------------


class _DummyTask:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class TestTaskRegistry:
    def test_register_and_start_all(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        instances: list[_DummyTask] = []

        def factory() -> _DummyTask:
            t = _DummyTask()
            instances.append(t)
            return t

        registry.register("task_a", factory)
        registry.register("task_b", factory)
        registry.start_all()

        assert len(instances) == 2
        assert all(t.started for t in instances)

    def test_stop_all(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        instances: list[_DummyTask] = []

        def factory() -> _DummyTask:
            t = _DummyTask()
            instances.append(t)
            return t

        registry.register("task_a", factory)
        registry.start_all()
        registry.stop_all()

        assert instances[0].stopped is True

    def test_duplicate_name_raises(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        registry.register("dup", _DummyTask)
        with pytest.raises(ValueError, match="already registered"):
            registry.register("dup", _DummyTask)

    def test_feature_gated_task_skipped(self):
        from wesktop.features import FeatureFlags
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        instances: list[_DummyTask] = []

        def factory() -> _DummyTask:
            t = _DummyTask()
            instances.append(t)
            return t

        registry.register("gated", factory, feature="terminal")
        ff = FeatureFlags({"terminal": False})
        registry.start_all(features=ff)

        assert len(instances) == 0

    def test_feature_gated_task_started_when_enabled(self):
        from wesktop.features import FeatureFlags
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        instances: list[_DummyTask] = []

        def factory() -> _DummyTask:
            t = _DummyTask()
            instances.append(t)
            return t

        registry.register("gated", factory, feature="terminal")
        ff = FeatureFlags({"terminal": True})
        registry.start_all(features=ff)

        assert len(instances) == 1
        assert instances[0].started is True

    def test_list_tasks(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        registry.register("a", _DummyTask, feature="x")
        registry.register("b", _DummyTask)

        tasks = registry.list_tasks()
        assert len(tasks) == 2
        assert tasks[0]["name"] == "a"
        assert tasks[0]["feature"] == "x"
        assert tasks[0]["running"] is False

    def test_get_task(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        registry.register("my_task", _DummyTask)
        registry.start_all()

        task = registry.get_task("my_task")
        assert task is not None
        assert task.started is True
        assert registry.get_task("nonexistent") is None

    def test_feature_gated_skipped_when_no_features_provided(self):
        from wesktop.tasks import TaskRegistry

        registry = TaskRegistry()
        instances: list[_DummyTask] = []

        def factory() -> _DummyTask:
            t = _DummyTask()
            instances.append(t)
            return t

        registry.register("gated", factory, feature="some_feature")
        # No FeatureFlags passed at all
        registry.start_all()

        assert len(instances) == 0

    def test_conforms_to_protocol(self):
        from wesktop.tasks import BackgroundTask

        assert isinstance(_DummyTask(), BackgroundTask)


# -----------------------------------------------------------------------
# 8.4 SDUI primitives
# -----------------------------------------------------------------------


class TestSDUINode:
    def test_basic_node(self):
        from wesktop.sdui import SDUINode

        n = SDUINode(type="heading", props={"content": "Hello", "level": 2})
        assert n.type == "heading"
        assert n.props["content"] == "Hello"
        assert n.children == []

    def test_node_with_children(self):
        from wesktop.sdui import SDUINode

        child = SDUINode(type="text", props={"content": "world"})
        parent = SDUINode(type="column", children=[child])
        assert len(parent.children) == 1
        assert parent.children[0].type == "text"

    def test_if_condition(self):
        from wesktop.sdui import SDUINode

        n = SDUINode(type="text", **{"if": "${state.visible}"})
        assert n.if_condition == "${state.visible}"


class TestNodeHelper:
    def test_simple_node(self):
        from wesktop.sdui import node

        result = node("heading", content="Hello", level=2)
        assert result == {"type": "heading", "props": {"content": "Hello", "level": 2}}

    def test_node_with_children(self):
        from wesktop.sdui import node

        child = node("text", content="A")
        parent = node("column", [child], gap=8)
        assert parent["type"] == "column"
        assert parent["props"] == {"gap": 8}
        assert parent["children"] == [child]

    def test_node_no_children_key_when_none(self):
        from wesktop.sdui import node

        result = node("spacer")
        assert "children" not in result


class TestLayoutPrimitives:
    def test_stack_column(self):
        from wesktop.sdui import Stack

        s = Stack(gap=8)
        n = s.to_node()
        assert n["type"] == "column"
        assert n["props"]["gap"] == 8
        assert "direction" not in n["props"]

    def test_stack_row(self):
        from wesktop.sdui import Stack

        s = Stack(direction="row", justify="center")
        n = s.to_node()
        assert n["type"] == "row"
        assert n["props"]["justify"] == "center"

    def test_zstack(self):
        from wesktop.sdui import ZStack

        z = ZStack(width=100, height=200)
        n = z.to_node()
        assert n["type"] == "stack"
        assert n["props"]["width"] == 100

    def test_spacer(self):
        from wesktop.sdui import Spacer

        assert Spacer().to_node()["type"] == "spacer"
        assert Spacer(size=16).to_node()["props"]["size"] == 16

    def test_divider(self):
        from wesktop.sdui import Divider

        assert Divider().to_node()["type"] == "divider"

    def test_grid(self):
        from wesktop.sdui import Grid

        assert Grid(columns=3, gap=8).to_node()["props"]["columns"] == 3

    def test_card(self):
        from wesktop.sdui import Card

        c = Card(title="My Card", elevated=True)
        n = c.to_node()
        assert n["type"] == "card"
        assert n["props"]["title"] == "My Card"

    def test_tabs(self):
        from wesktop.sdui import TabItem, Tabs

        t = Tabs(items=[TabItem(label="A", value="a")], active="a")
        n = t.to_node()
        assert n["type"] == "tabs"
        assert len(n["props"]["items"]) == 1

    def test_breadcrumb(self):
        from wesktop.sdui import Breadcrumb, BreadcrumbItem

        b = Breadcrumb(items=[BreadcrumbItem(label="Home", href="/")])
        assert b.to_node()["type"] == "breadcrumb"

    def test_empty(self):
        from wesktop.sdui import Empty

        assert Empty(message="Nothing here").to_node()["type"] == "empty"


class TestDisplayPrimitives:
    def test_heading(self):
        from wesktop.sdui import Heading

        h = Heading(content="Title", level=1)
        n = h.to_node()
        assert n["type"] == "heading"
        assert n["props"]["content"] == "Title"
        assert n["props"]["level"] == 1

    def test_text(self):
        from wesktop.sdui import Text

        t = Text(content="Hello", size="lg", weight="bold")
        n = t.to_node()
        assert n["type"] == "text"
        assert n["props"]["size"] == "lg"

    def test_code(self):
        from wesktop.sdui import Code

        c = Code(content="print('hi')", language="python")
        n = c.to_node()
        assert n["type"] == "code-block"

    def test_status(self):
        from wesktop.sdui import Status

        s = Status(label="Running", variant="success")
        assert s.to_node()["type"] == "status"

    def test_badge(self):
        from wesktop.sdui import Badge

        assert Badge(content="v2", color="green").to_node()["type"] == "badge"

    def test_progress_bar(self):
        from wesktop.sdui import ProgressBar

        p = ProgressBar(value=75, label="75%")
        n = p.to_node()
        assert n["type"] == "progress-bar"
        assert n["props"]["value"] == 75

    def test_spinner(self):
        from wesktop.sdui import Spinner

        assert Spinner(size="lg").to_node()["type"] == "spinner"

    def test_timeline(self):
        from wesktop.sdui import Timeline, TimelineItem

        t = Timeline(items=[TimelineItem(label="Start", time="10:00")])
        assert t.to_node()["type"] == "timeline"

    def test_diff(self):
        from wesktop.sdui import Diff

        d = Diff(old_text="a", new_text="b")
        assert d.to_node()["type"] == "diff"

    def test_markdown(self):
        from wesktop.sdui import Markdown

        assert Markdown(content="# Hi").to_node()["type"] == "markdown"


class TestDataPrimitives:
    def test_table(self):
        from wesktop.sdui import ColumnDef, Table

        t = Table(columns=[ColumnDef(key="name", label="Name")])
        n = t.to_node()
        assert n["type"] == "table"
        assert len(n["props"]["columns"]) == 1

    def test_list(self):
        from wesktop.sdui import List

        assert List(items_key="data").to_node()["type"] == "list"

    def test_key_value(self):
        from wesktop.sdui import KVEntry, KeyValue

        kv = KeyValue(entries=[KVEntry(key="host", value="localhost")])
        assert kv.to_node()["type"] == "key-value"

    def test_json_view(self):
        from wesktop.sdui import JsonView

        assert JsonView(data_key="resp").to_node()["type"] == "json-view"

    def test_tree(self):
        from wesktop.sdui import Tree

        assert Tree(items_key="nodes").to_node()["type"] == "tree"


class TestInputPrimitives:
    def test_button(self):
        from wesktop.sdui import Button

        b = Button(label="Click", variant="primary", command="do_it")
        n = b.to_node()
        assert n["type"] == "button"
        assert n["props"]["label"] == "Click"
        assert n["props"]["command"] == "do_it"

    def test_input(self):
        from wesktop.sdui import Input

        i = Input(name="email", placeholder="you@example.com")
        assert i.to_node()["type"] == "input"

    def test_textarea(self):
        from wesktop.sdui import TextArea

        assert TextArea(name="body", rows=5).to_node()["type"] == "textarea"

    def test_select(self):
        from wesktop.sdui import OptionItem, Select

        s = Select(name="role", options=[OptionItem(label="Admin", value="admin")])
        assert s.to_node()["type"] == "select"

    def test_checkbox(self):
        from wesktop.sdui import Checkbox

        assert Checkbox(name="agree", checked=True).to_node()["type"] == "checkbox"

    def test_switch(self):
        from wesktop.sdui import Switch

        assert Switch(name="dark", label="Dark mode").to_node()["type"] == "switch"

    def test_radio(self):
        from wesktop.sdui import Radio

        assert Radio(name="plan").to_node()["type"] == "radio"

    def test_slider(self):
        from wesktop.sdui import Slider

        s = Slider(name="volume", min=0, max=100, step=5, value=50)
        n = s.to_node()
        assert n["type"] == "slider"
        assert n["props"]["value"] == 50


class TestFeedbackPrimitives:
    def test_alert(self):
        from wesktop.sdui import Alert

        a = Alert(severity="warning", title="Heads up", message="Something happened")
        n = a.to_node()
        assert n["type"] == "alert"
        assert n["props"]["severity"] == "warning"

    def test_toast(self):
        from wesktop.sdui import Toast

        assert Toast(message="Saved!", variant="success").to_node()["type"] == "toast"

    def test_logs(self):
        from wesktop.sdui import Logs

        assert Logs(max_lines=100).to_node()["type"] == "logs"


class TestOverlayPrimitives:
    def test_modal(self):
        from wesktop.sdui import Modal

        assert Modal(title="Confirm").to_node()["type"] == "modal"

    def test_drawer(self):
        from wesktop.sdui import Drawer

        d = Drawer(title="Settings", position="left", width="400px")
        n = d.to_node()
        assert n["type"] == "drawer"
        assert n["props"]["position"] == "left"

    def test_popover(self):
        from wesktop.sdui import Popover

        assert Popover(placement="top").to_node()["type"] == "popover"

    def test_confirm(self):
        from wesktop.sdui import Confirm

        c = Confirm(title="Delete?", message="Are you sure?", action="delete")
        n = c.to_node()
        assert n["type"] == "confirm"
        assert n["props"]["action"] == "delete"


class TestIfCondition:
    def test_if_condition_on_primitive(self):
        from wesktop.sdui import Button

        b = Button(label="X", if_condition="${state.show}")
        n = b.to_node()
        assert n["if"] == "${state.show}"
        assert "if_condition" not in n["props"]

    def test_no_if_when_none(self):
        from wesktop.sdui import Text

        n = Text(content="hi").to_node()
        assert "if" not in n


class TestDataGrid:
    def test_data_grid(self):
        from wesktop.sdui import DataGrid, DataGridColumnDef

        dg = DataGrid(
            columns=[DataGridColumnDef(key="name", label="Name")],
            data=[{"name": "Alice"}],
            page_size=10,
        )
        n = dg.to_node()
        assert n["type"] == "data-grid"
        assert n["props"]["page_size"] == 10


# -----------------------------------------------------------------------
# 8.4 SDUI provider registry
# -----------------------------------------------------------------------


class TestSDUIProviderRegistry:
    def test_register_and_get(self):
        from wesktop.sdui import (
            _SDUI_PROVIDERS,
            get_sdui_provider,
            register_sdui_provider,
        )

        # Clean up for test isolation
        _SDUI_PROVIDERS.clear()

        async def my_provider():
            return ({"type": "column", "props": {}}, {"loaded": True})

        register_sdui_provider("test_panel", my_provider)
        assert get_sdui_provider("test_panel") is my_provider

    def test_get_nonexistent_returns_none(self):
        from wesktop.sdui import _SDUI_PROVIDERS, get_sdui_provider

        _SDUI_PROVIDERS.clear()
        assert get_sdui_provider("nope") is None

    def test_list_providers(self):
        from wesktop.sdui import (
            _SDUI_PROVIDERS,
            list_sdui_providers,
            register_sdui_provider,
        )

        _SDUI_PROVIDERS.clear()

        async def p1():
            return ({}, {})

        async def p2():
            return ({}, {})

        register_sdui_provider("panel_a", p1)
        register_sdui_provider("panel_b", p2)
        names = list_sdui_providers()
        assert "panel_a" in names
        assert "panel_b" in names

    def test_provider_returns_tuple(self):
        from wesktop.sdui import (
            _SDUI_PROVIDERS,
            get_sdui_provider,
            register_sdui_provider,
        )

        _SDUI_PROVIDERS.clear()

        async def my_provider():
            return (
                {"type": "column", "props": {}, "children": []},
                {"count": 42},
            )

        register_sdui_provider("data_panel", my_provider)
        provider = get_sdui_provider("data_panel")
        tree, state = asyncio.run(provider())
        assert tree["type"] == "column"
        assert state["count"] == 42

---
title: SDUI Primitive Reference
description: "Complete reference for wesktop's 40 Server-Driven UI primitives: fields, types, defaults, output examples, and usage guidance organized by category."
date: 2026-07-29
---

# SDUI Primitive Reference

wesktop ships 40 Server-Driven UI primitives as Pydantic models in `wesktop.sdui`. Each model validates its props and serializes to the dict shape that the dashboard's `SDUIRenderer` expects: `{"type": ..., "props": {...}}` with an optional `"if"` key for conditional rendering.

All primitives inherit from `_PrimitiveBase` and expose a `.to_node()` method that produces the output dict. Every primitive also accepts an optional `if_condition` parameter (excluded from serialized props, lifted to a top-level `"if"` key on the node).

For untyped dict construction without validation, use the `node()` helper:

```python
from wesktop.sdui import node

node("heading", content="Hello", level=2)
# {"type": "heading", "props": {"content": "Hello", "level": 2}}
```

## Prop Sub-Models

Several primitives use shared sub-models for structured data. These are not SDUI nodes themselves -- they describe items within a primitive's fields.

### TabItem

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | required | Display text for the tab |
| `value` | `str` | required | Programmatic identifier |

### BreadcrumbItem

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | required | Display text for the segment |
| `href` | `str \| None` | `None` | Navigation target URL |

### TimelineItem

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | required | Event description |
| `time` | `str \| None` | `None` | Timestamp string |
| `status` | `str \| None` | `None` | Event status |
| `detail` | `str \| None` | `None` | Additional detail text |

### ColumnDef

Used by `Table`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `key` | `str` | required | Row data key to display in this column |
| `label` | `str \| None` | `None` | Column header text (falls back to `key`) |
| `width` | `str \| None` | `None` | CSS width value |

### DataGridColumnDef

Used by `DataGrid`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `key` | `str` | required | Row data key |
| `label` | `str` | required | Column header text |
| `sortable` | `bool` | `True` | Whether the column supports sorting |
| `filterable` | `bool` | `True` | Whether the column supports filtering |
| `width` | `int \| None` | `None` | Column width in pixels |

### KVEntry

Used by `KeyValue`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `key` | `str \| None` | `None` | Programmatic key |
| `label` | `str \| None` | `None` | Display label |
| `value` | `str \| None` | `None` | Display value |

### OptionItem

Used by `Select` and `Radio`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | required | Display text |
| `value` | `str` | required | Programmatic value |

---

## Layout (9 primitives)

Structural containers that control how children are arranged.

### Stack

Flex container that arranges children in a column or row. The `direction` field determines the serialized node type (`"column"` or `"row"`) and is excluded from props.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `direction` | `"column" \| "row"` | `"column"` | Flex direction (becomes the node type) |
| `gap` | `int \| None` | `None` | Gap between children in pixels |
| `align` | `str \| None` | `None` | Cross-axis alignment |
| `justify` | `str \| None` | `None` | Main-axis justification |
| `wrap` | `bool \| None` | `None` | Whether children wrap |

```python
Stack(direction="row", gap=8, align="center").to_node()
# {"type": "row", "props": {"gap": 8, "align": "center"}}

Stack(gap=16).to_node()
# {"type": "column", "props": {"gap": 16}}
```

Use Stack for any linear arrangement of children. Use `direction="column"` (default) for vertical stacking, `direction="row"` for horizontal.

### ZStack

Overlay container where children are positioned on the z-axis (position-absolute). Serializes as node type `"stack"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `width` | `int \| None` | `None` | Container width in pixels |
| `height` | `int \| None` | `None` | Container height in pixels |

```python
ZStack(width=200, height=200).to_node()
# {"type": "stack", "props": {"width": 200, "height": 200}}
```

Use ZStack when children need to overlap (badges on avatars, loading overlays on content).

### Spacer

Empty space between elements. Inserts a gap of optional fixed size.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `size` | `int \| None` | `None` | Fixed height in pixels |

```python
Spacer(size=24).to_node()
# {"type": "spacer", "props": {"size": 24}}

Spacer().to_node()
# {"type": "spacer", "props": {}}
```

Use Spacer for explicit whitespace that is not covered by a parent's `gap` property.

### Divider

Horizontal line separator. Has no configurable fields beyond `if_condition`.

```python
Divider().to_node()
# {"type": "divider", "props": {}}
```

Use Divider to visually separate sections within a layout.

### Grid

CSS-grid layout container.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `columns` | `int \| str \| None` | `None` | Number of columns (int) or CSS grid-template-columns value (str) |
| `gap` | `int \| None` | `None` | Gap between grid cells in pixels |
| `min_width` | `str \| None` | `None` | Minimum column width for auto-fit layouts |

```python
Grid(columns=3, gap=16).to_node()
# {"type": "grid", "props": {"columns": 3, "gap": 16}}

Grid(columns="1fr 2fr 1fr", gap=8).to_node()
# {"type": "grid", "props": {"columns": "1fr 2fr 1fr", "gap": 8}}
```

Use Grid for two-dimensional layouts (dashboards, card grids, form layouts).

### Card

Elevated card container with optional title and subtitle.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str \| None` | `None` | Card title |
| `subtitle` | `str \| None` | `None` | Subtitle text below the title |
| `padding` | `int \| str \| None` | `None` | Internal padding (pixels or CSS value) |
| `elevated` | `bool \| None` | `None` | Whether the card has a shadow |

```python
Card(title="Deployment", subtitle="Production", elevated=True).to_node()
# {"type": "card", "props": {"title": "Deployment", "subtitle": "Production", "elevated": true}}
```

Use Card to group related content into a visually distinct container.

### Tabs

Tab switcher that selects among content panels.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `items` | `list[TabItem]` | `[]` | Tab definitions |
| `active` | `str \| None` | `None` | Value of the currently active tab |

```python
Tabs(items=[TabItem(label="Overview", value="overview"),
            TabItem(label="Logs", value="logs")],
     active="overview").to_node()
# {"type": "tabs", "props": {"items": [{"label": "Overview", "value": "overview"},
#                                       {"label": "Logs", "value": "logs"}],
#                              "active": "overview"}}
```

Use Tabs when the user needs to switch between distinct views within the same context.

### Breadcrumb

Navigation breadcrumb trail showing the current location in a hierarchy.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `items` | `list[BreadcrumbItem]` | `[]` | Breadcrumb segments, in order from root to current |

```python
Breadcrumb(items=[BreadcrumbItem(label="Home", href="/"),
                  BreadcrumbItem(label="Settings")]).to_node()
# {"type": "breadcrumb", "props": {"items": [{"label": "Home", "href": "/"},
#                                              {"label": "Settings"}]}}
```

Use Breadcrumb for hierarchical navigation where the user needs to see and traverse the path to the current page.

### Empty

Empty-state placeholder shown when a section has no content.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | `str \| None` | `None` | Message to display |
| `icon` | `str \| None` | `None` | Icon identifier |

```python
Empty(message="No deployments yet", icon="rocket").to_node()
# {"type": "empty", "props": {"message": "No deployments yet", "icon": "rocket"}}
```

Use Empty to provide a helpful message when a list, table, or section has no data.

---

## Display (10 primitives)

Read-only content rendering: text, headings, code, status indicators, and rich content.

### Heading

Section heading (h1 through h6).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | `""` | Heading text |
| `level` | `int` | `2` | Heading level (1-6, validated) |

```python
Heading(content="Server Status", level=1).to_node()
# {"type": "heading", "props": {"content": "Server Status", "level": 1}}
```

Use Heading for section titles and page structure.

### Text

Inline text span with optional styling.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | `""` | Text content |
| `size` | `"xs" \| "sm" \| "md" \| "lg" \| "xl" \| None` | `None` | Font size |
| `weight` | `"normal" \| "medium" \| "semibold" \| "bold" \| None` | `None` | Font weight |
| `color` | `str \| None` | `None` | Text color |
| `truncate` | `bool \| None` | `None` | Whether to truncate with ellipsis |

```python
Text(content="Running", size="sm", weight="bold", color="green").to_node()
# {"type": "text", "props": {"content": "Running", "size": "sm",
#                              "weight": "bold", "color": "green"}}
```

Use Text for any inline text that needs styling beyond what Heading or Markdown provides.

### Code

Syntax-highlighted code block. Serializes as node type `"code-block"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | `""` | Code content |
| `language` | `str \| None` | `None` | Language for syntax highlighting |

```python
Code(content="print('hello')", language="python").to_node()
# {"type": "code-block", "props": {"content": "print('hello')", "language": "python"}}
```

Use Code for displaying source code, configuration files, or command output.

### Status

Status badge with semantic coloring.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | `""` | Status text |
| `variant` | `"success" \| "error" \| "warning" \| "info" \| "neutral"` | `"neutral"` | Semantic color variant |

```python
Status(label="Healthy", variant="success").to_node()
# {"type": "status", "props": {"label": "Healthy", "variant": "success"}}
```

Use Status for indicating the state of services, deployments, or processes.

### Badge

Small rounded pill label or tag.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | `""` | Badge text |
| `color` | `str \| None` | `None` | Badge color |

```python
Badge(content="v2.1.0", color="blue").to_node()
# {"type": "badge", "props": {"content": "v2.1.0", "color": "blue"}}
```

Use Badge for labels, tags, version numbers, or counts.

### ProgressBar

Horizontal progress bar. Serializes as node type `"progress-bar"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | `float` | `0` | Progress percentage (0-100, validated) |
| `color` | `str \| None` | `None` | Bar color |
| `label` | `str \| None` | `None` | Label text |

```python
ProgressBar(value=73.5, label="Upload", color="blue").to_node()
# {"type": "progress-bar", "props": {"value": 73.5, "label": "Upload", "color": "blue"}}
```

Use ProgressBar for showing completion of uploads, builds, or any bounded operation.

### Spinner

Loading spinner indicator.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `size` | `"sm" \| "md" \| "lg"` | `"md"` | Spinner size |

```python
Spinner(size="lg").to_node()
# {"type": "spinner", "props": {"size": "lg"}}
```

Use Spinner for indicating that data is loading or an operation is in progress.

### Timeline

Vertical timeline of events.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `items` | `list[TimelineItem]` | `[]` | Timeline entries |

```python
Timeline(items=[
    TimelineItem(label="Deployed", time="14:32", status="success"),
    TimelineItem(label="Tests passed", time="14:30"),
]).to_node()
# {"type": "timeline", "props": {"items": [
#     {"label": "Deployed", "time": "14:32", "status": "success"},
#     {"label": "Tests passed", "time": "14:30"}
# ]}}
```

Use Timeline for displaying a chronological sequence of events (deployment history, audit trail, build steps).

### Diff

Side-by-side or unified diff view.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `old_text` | `str` | `""` | Original text |
| `new_text` | `str` | `""` | Modified text |
| `language` | `str \| None` | `None` | Language for syntax highlighting |

```python
Diff(old_text="port = 8080", new_text="port = 9090", language="toml").to_node()
# {"type": "diff", "props": {"old_text": "port = 8080",
#                              "new_text": "port = 9090", "language": "toml"}}
```

Use Diff for code review, configuration change review, or any before/after comparison.

### Markdown

Rendered Markdown content.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | `""` | Markdown source text |

```python
Markdown(content="## Notes\n\nDeploy to **production** after review.").to_node()
# {"type": "markdown", "props": {"content": "## Notes\n\nDeploy to **production** after review."}}
```

Use Markdown for rich formatted content where the source is already in Markdown format (README sections, documentation excerpts, user-authored notes).

---

## Data (6 primitives)

Structured data display: tables, grids, lists, key-value pairs, JSON trees, and hierarchical trees.

### Table

Data table with typed column definitions.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `columns` | `list[ColumnDef]` | `[]` | Column definitions |
| `rows_key` | `str \| None` | `None` | State key that holds the row data array |

```python
Table(columns=[ColumnDef(key="name", label="Service"),
               ColumnDef(key="status", label="Status", width="100px")],
      rows_key="services").to_node()
# {"type": "table", "props": {"columns": [{"key": "name", "label": "Service"},
#                                           {"key": "status", "label": "Status",
#                                            "width": "100px"}],
#                               "rows_key": "services"}}
```

Use Table for displaying tabular data with defined column structure. Row data is provided via state using `rows_key`.

### DataGrid

Interactive data grid with sorting, filtering, and pagination. Serializes as node type `"data-grid"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `columns` | `list[DataGridColumnDef]` | `[]` | Column definitions with sort/filter config |
| `data` | `list[dict]` | `[]` | Row data (inline, not state-driven) |
| `page_size` | `int` | `25` | Rows per page |
| `total_rows` | `int \| None` | `None` | Total row count for server-side pagination |
| `sortable` | `bool` | `True` | Whether sorting is enabled globally |
| `filterable` | `bool` | `True` | Whether filtering is enabled globally |

```python
DataGrid(
    columns=[DataGridColumnDef(key="name", label="Name"),
             DataGridColumnDef(key="cpu", label="CPU %", sortable=True, filterable=False)],
    data=[{"name": "web-1", "cpu": 45.2}],
    page_size=50,
).to_node()
# {"type": "data-grid", "props": {"columns": [...], "data": [...],
#                                   "page_size": 50, "sortable": true, "filterable": true}}
```

Use DataGrid for large datasets that need interactive sorting, filtering, and pagination. Unlike Table, DataGrid carries its data inline rather than referencing state.

### List

Iterable list whose children are stamped per item.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `items_key` | `str \| None` | `None` | State key that holds the items array |

```python
List(items_key="notifications").to_node()
# {"type": "list", "props": {"items_key": "notifications"}}
```

Use List for rendering a repeated template over an array from state (notifications, log entries, search results).

### KeyValue

Key-value display rendered as a definition list. Serializes as node type `"key-value"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entries` | `list[KVEntry]` | `[]` | Key-value entries |

```python
KeyValue(entries=[KVEntry(label="Host", value="prod-1.example.com"),
                  KVEntry(label="Uptime", value="14d 3h")]).to_node()
# {"type": "key-value", "props": {"entries": [{"label": "Host", "value": "prod-1.example.com"},
#                                               {"label": "Uptime", "value": "14d 3h"}]}}
```

Use KeyValue for displaying metadata, configuration summaries, or any labeled property list.

### JsonView

Interactive collapsible JSON tree viewer. Serializes as node type `"json-view"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `data_key` | `str \| None` | `None` | State key that holds the JSON data |

```python
JsonView(data_key="response_body").to_node()
# {"type": "json-view", "props": {"data_key": "response_body"}}
```

Use JsonView for inspecting API responses, configuration objects, or any nested JSON structure.

### Tree

Hierarchical tree view with expandable nodes.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `items_key` | `str \| None` | `None` | State key for the tree data |
| `label_key` | `str \| None` | `None` | Property name for node labels |
| `children_key` | `str \| None` | `None` | Property name for child arrays |

```python
Tree(items_key="filesystem", label_key="name", children_key="children").to_node()
# {"type": "tree", "props": {"items_key": "filesystem", "label_key": "name",
#                              "children_key": "children"}}
```

Use Tree for displaying hierarchical data (file systems, org charts, nested categories).

---

## Input (8 primitives)

Interactive controls that accept user input or dispatch commands.

### Button

Clickable button that dispatches a command.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | `str` | `""` | Button text |
| `variant` | `"primary" \| "danger" \| "ghost" \| "outline"` | `"primary"` | Visual style |
| `command` | `str \| None` | `None` | Command to dispatch on click |
| `confirm` | `str \| None` | `None` | Confirmation message shown before executing |
| `disabled` | `bool \| str \| None` | `None` | Disabled state (bool) or state expression (str) |
| `size` | `"sm" \| "md" \| None` | `None` | Button size |

```python
Button(label="Deploy", variant="primary", command="deploy",
       confirm="Deploy to production?").to_node()
# {"type": "button", "props": {"label": "Deploy", "variant": "primary",
#                                "command": "deploy",
#                                "confirm": "Deploy to production?"}}

Button(label="Delete", variant="danger", command="delete", disabled=True).to_node()
# {"type": "button", "props": {"label": "Delete", "variant": "danger",
#                                "command": "delete", "disabled": true}}
```

Use Button for any user-triggered action. Use `confirm` for destructive operations, `disabled` to prevent interaction based on state.

### Input

Single-line text input field.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `placeholder` | `str \| None` | `None` | Placeholder text |
| `input_type` | `"text" \| "number" \| "email" \| "password"` | `"text"` | HTML input type (serialized as `"type"`) |

```python
Input(name="email", label="Email", placeholder="user@example.com",
      input_type="email").to_node()
# {"type": "input", "props": {"name": "email", "label": "Email",
#                               "placeholder": "user@example.com", "type": "email"}}
```

Use Input for single-line text entry (names, emails, numbers, passwords). The `input_type` field serializes as `"type"` in the output props via Pydantic alias.

### TextArea

Multi-line text input.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `placeholder` | `str \| None` | `None` | Placeholder text |
| `rows` | `int \| None` | `None` | Number of visible text rows |

```python
TextArea(name="notes", label="Release Notes", rows=6).to_node()
# {"type": "textarea", "props": {"name": "notes", "label": "Release Notes", "rows": 6}}
```

Use TextArea for multi-line text entry (descriptions, notes, code snippets, comments).

### Select

Dropdown select control.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `options` | `list[OptionItem]` | `[]` | Available options |
| `placeholder` | `str \| None` | `None` | Placeholder text when nothing is selected |

```python
Select(name="env", label="Environment",
       options=[OptionItem(label="Staging", value="staging"),
                OptionItem(label="Production", value="prod")],
       placeholder="Choose...").to_node()
# {"type": "select", "props": {"name": "env", "label": "Environment",
#                                "options": [{"label": "Staging", "value": "staging"},
#                                             {"label": "Production", "value": "prod"}],
#                                "placeholder": "Choose..."}}
```

Use Select for choosing one option from a predefined list.

### Checkbox

Boolean checkbox.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `checked` | `bool` | `False` | Initial checked state |

```python
Checkbox(name="dry_run", label="Dry run", checked=True).to_node()
# {"type": "checkbox", "props": {"name": "dry_run", "label": "Dry run", "checked": true}}
```

Use Checkbox for boolean options in forms.

### Switch

Toggle switch (visually distinct from Checkbox but functionally similar).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `checked` | `bool` | `False` | Initial toggle state |

```python
Switch(name="auto_deploy", label="Auto-deploy on merge").to_node()
# {"type": "switch", "props": {"name": "auto_deploy", "label": "Auto-deploy on merge",
#                                "checked": false}}
```

Use Switch for on/off settings where the visual emphasis on the binary state matters (feature flags, toggleable behaviors).

### Radio

Radio button group for selecting one option from a set.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name (shared by all options in the group) |
| `label` | `str \| None` | `None` | Group label text |
| `options` | `list[OptionItem]` | `[]` | Available options |

```python
Radio(name="region", label="Region",
      options=[OptionItem(label="US East", value="us-east-1"),
               OptionItem(label="EU West", value="eu-west-1")]).to_node()
# {"type": "radio", "props": {"name": "region", "label": "Region",
#                               "options": [{"label": "US East", "value": "us-east-1"},
#                                            {"label": "EU West", "value": "eu-west-1"}]}}
```

Use Radio when all options should be visible simultaneously and the user must pick exactly one.

### Slider

Numeric slider for selecting a value within a range.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Form field name |
| `label` | `str \| None` | `None` | Label text |
| `min` | `float` | `0` | Minimum value |
| `max` | `float` | `100` | Maximum value |
| `step` | `float` | `1` | Step increment |
| `value` | `float \| None` | `None` | Initial value |

```python
Slider(name="replicas", label="Replicas", min=1, max=10, step=1, value=3).to_node()
# {"type": "slider", "props": {"name": "replicas", "label": "Replicas",
#                                "min": 1, "max": 10, "step": 1, "value": 3}}
```

Use Slider for numeric input where the valid range is bounded and continuous (replica counts, timeout values, thresholds).

---

## Feedback (3 primitives)

User-facing notifications, alerts, and log streams.

### Alert

Inline alert banner with semantic severity.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `severity` | `"info" \| "success" \| "warning" \| "error"` | `"info"` | Alert severity level |
| `title` | `str \| None` | `None` | Alert title |
| `message` | `str` | `""` | Alert body text |

```python
Alert(severity="error", title="Deploy Failed",
      message="Container health check timed out.").to_node()
# {"type": "alert", "props": {"severity": "error", "title": "Deploy Failed",
#                               "message": "Container health check timed out."}}
```

Use Alert for persistent in-page notifications that require user attention (errors, warnings, success confirmations).

### Toast

Ephemeral toast notification that auto-dismisses.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | `str` | `""` | Notification text |
| `variant` | `"info" \| "success" \| "warning" \| "error"` | `"info"` | Semantic variant |
| `duration_ms` | `int` | `3000` | Auto-dismiss time in milliseconds |

```python
Toast(message="Settings saved", variant="success", duration_ms=2000).to_node()
# {"type": "toast", "props": {"message": "Settings saved", "variant": "success",
#                               "duration_ms": 2000}}
```

Use Toast for transient confirmations that do not need persistent visibility (save confirmations, clipboard copies, background task completions).

### Logs

Streaming log viewer with auto-scroll.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_event` | `str \| None` | `None` | SSE event name to stream from |
| `max_lines` | `int` | `200` | Maximum number of lines to retain |
| `auto_scroll` | `bool` | `True` | Whether to auto-scroll to the latest line |

```python
Logs(source_event="build-output", max_lines=500).to_node()
# {"type": "logs", "props": {"source_event": "build-output", "max_lines": 500,
#                              "auto_scroll": true}}
```

Use Logs for streaming real-time output (build logs, server logs, process output) via SSE.

---

## Overlay (4 primitives)

Modal dialogs, drawers, popovers, and confirmation prompts that layer above the main content.

### Modal

Overlay modal dialog.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str \| None` | `None` | Dialog title |
| `open_event` | `str \| None` | `None` | Event name that opens the modal |
| `close_event` | `str \| None` | `None` | Event name that closes the modal |

```python
Modal(title="Create Service", open_event="show-create-modal",
      close_event="hide-create-modal").to_node()
# {"type": "modal", "props": {"title": "Create Service",
#                               "open_event": "show-create-modal",
#                               "close_event": "hide-create-modal"}}
```

Use Modal for focused interactions that require the user's full attention (forms, confirmations, detail views).

### Drawer

Slide-in side panel.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str \| None` | `None` | Panel title |
| `position` | `"left" \| "right"` | `"right"` | Which side the drawer slides in from |
| `width` | `str \| None` | `None` | Panel width (CSS value) |

```python
Drawer(title="Settings", position="right", width="400px").to_node()
# {"type": "drawer", "props": {"title": "Settings", "position": "right", "width": "400px"}}
```

Use Drawer for secondary content or settings that the user can access without leaving the current page.

### Popover

Popover tooltip or flyout anchored to a trigger element.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trigger` | `str \| None` | `None` | Element identifier that triggers the popover |
| `placement` | `"top" \| "bottom" \| "left" \| "right"` | `"bottom"` | Position relative to the trigger |

```python
Popover(trigger="info-icon", placement="top").to_node()
# {"type": "popover", "props": {"trigger": "info-icon", "placement": "top"}}
```

Use Popover for contextual help, tooltips, or small menus attached to a specific element.

### Confirm

Confirmation dialog for guarding destructive actions.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str \| None` | `None` | Dialog title |
| `message` | `str` | `""` | Confirmation question |
| `confirm_label` | `str` | `"Confirm"` | Text on the confirm button |
| `cancel_label` | `str` | `"Cancel"` | Text on the cancel button |
| `action` | `str \| None` | `None` | Command dispatched on confirmation |

```python
Confirm(title="Delete Service",
        message="This will permanently delete the service and all its data.",
        confirm_label="Delete", cancel_label="Keep",
        action="delete-service").to_node()
# {"type": "confirm", "props": {"title": "Delete Service",
#                                 "message": "This will permanently delete...",
#                                 "confirm_label": "Delete", "cancel_label": "Keep",
#                                 "action": "delete-service"}}
```

Use Confirm when an action is destructive or irreversible and the user should explicitly approve before proceeding.

---

## Conditional Rendering

All primitives accept an optional `if_condition` parameter. When set, the serialized node includes an `"if"` key at the top level (not inside `props`). The renderer evaluates the condition against the current state to decide whether to render the node.

```python
Button(label="Rollback", command="rollback",
       if_condition="deployment.status == 'failed'").to_node()
# {"type": "button",
#  "props": {"label": "Rollback", "variant": "primary", "command": "rollback"},
#  "if": "deployment.status == 'failed'"}
```

---

## Provider Registry

SDUI providers are async callables that return `(ui_tree, initial_state)`. Three functions manage the registry:

- `register_sdui_provider(name, provider)` -- register a provider by name
- `get_sdui_provider(name)` -- look up a provider (returns `None` if not found)
- `list_sdui_providers()` -- list all registered provider names

```python
from wesktop.sdui import register_sdui_provider, node

async def dashboard_provider():
    ui_tree = node("column", [
        node("heading", content="Dashboard", level=1),
        node("text", content="Welcome"),
    ], gap=16)
    initial_state = {"user": "admin"}
    return ui_tree, initial_state

register_sdui_provider("dashboard", dashboard_provider)
```

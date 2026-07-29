"""selfdoc custom directive: render SDUI primitive grouping table from sdui.py.

Registered in selfdoc.json as ``"table-sdui"``. selfdoc loads this file
and calls ``resolve(attrs, config, body) -> str``; the returned markdown
replaces the ``:-: table-sdui`` directive line.

The source of truth is ``src/wesktop/sdui.py``. This directive parses
the category section headers and _PrimitiveBase subclasses so the
generated table can never drift from the code.
"""

from __future__ import annotations

import os
import re


def _parse_primitives(source: str) -> list[tuple[str, list[str]]]:
    """Parse category headers and their _PrimitiveBase subclasses from sdui.py.

    Returns a list of (category_name, [class_names]) tuples in source order.
    Category headers look like::

        # Layout (9)
        # Display (10)

    Subclasses look like::

        class Stack(_PrimitiveBase):
    """
    # Match section headers like: # Layout (9)
    header_re = re.compile(r"^# -+\n# (\w+) \(\d+\)\n# -+", re.MULTILINE)
    # Match class definitions inheriting from _PrimitiveBase
    class_re = re.compile(r"^class (\w+)\(_PrimitiveBase\):", re.MULTILINE)

    headers = list(header_re.finditer(source))
    if not headers:
        raise RuntimeError("no category headers found in sdui.py")

    categories: list[tuple[str, list[str]]] = []
    for i, header in enumerate(headers):
        category = header.group(1)
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(source)
        section = source[start:end]
        classes = class_re.findall(section)
        categories.append((category, classes))

    return categories


def resolve(attrs: dict, config: dict, body: list[str]) -> str:
    """Return a markdown table of SDUI primitives grouped by category."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sdui_path = os.path.join(repo_root, "src", "wesktop", "sdui.py")

    with open(sdui_path) as f:
        source = f.read()

    categories = _parse_primitives(source)
    if not categories:
        raise RuntimeError(f"no primitives found in {sdui_path}")

    total = sum(len(classes) for _, classes in categories)

    lines = [
        "| Category | Count | Nodes |",
        "|----------|-------|-------|",
    ]
    for category, classes in categories:
        names = ", ".join(classes)
        lines.append(f"| {category} | {len(classes)} | {names} |")
    lines.append(f"| **Total** | **{total}** | |")

    return "\n".join(lines)

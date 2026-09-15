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


def _repo_root() -> str:
    """Walk up from this file until a directory holding selfdoc.json is found.

    The docs tree moved under ``.stricttools/``, so a fixed number of parents
    is wrong by construction; the project marker is what locates the root.
    """
    here = os.path.abspath(__file__)
    directory = os.path.dirname(here)
    while True:
        if os.path.isfile(os.path.join(directory, "selfdoc.json")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            raise RuntimeError(f"no selfdoc.json in any parent of {here}")
        directory = parent


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
    sdui_path = os.path.join(_repo_root(), "src", "wesktop", "sdui.py")

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

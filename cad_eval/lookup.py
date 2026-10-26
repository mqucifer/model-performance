"""Look up CadQuery's names, inside the CAD-code evaluation's container only.

    python -I - '<query>'   (this file on stdin)

The skill arm's `lookup` tool (mqucifer/model-performance#21). A name or a fragment
of one goes in, and out come the names in the installed CadQuery that contain it, each
with its signature and its docstring's first paragraph: from the library the session's
scripts run against, never from anyone's memory of it. OCP, CadQuery's binding of the
OCCT kernel, is too large to list whole, so a query that names it (`OCP.`) gets its
modules' class names only.

It runs as `measure.py` does: never written into the part's directory, and `-I` keeps
a module the model wrote from shadowing an import. It prints one line, `MARK` then JSON.
Standard library and CadQuery: what the image holds.
"""

from __future__ import annotations

import inspect
import json
import sys

MARK = "CAD_EVAL_LOOKUP "
LIMIT = 20
# Aliases a name is never listed under: `cq.CQ` is `cq.Workplane`.
ALIASES = {"CQ"}
# Where CadQuery's names live: the classes a script uses, and the modules they come from.
ROOTS = (
    "cadquery",
    "cadquery.occ_impl.shapes",
    "cadquery.occ_impl.geom",
    "cadquery.occ_impl.exporters",
    "cadquery.occ_impl.importers",
    "cadquery.selectors",
    "cadquery.sketch",
    "cadquery.assembly",
)
OCP_MODULES = (
    "BRep",
    "BRepAlgoAPI",
    "BRepBuilderAPI",
    "BRepOffsetAPI",
    "BRepPrimAPI",
    "GC",
    "Geom",
    "gp",
    "TopoDS",
)


def first_paragraph(doc: str | None) -> str:
    text = inspect.cleandoc(doc or "")
    return text.split("\n\n", 1)[0].strip()[:400]


def signature(obj: object) -> str:
    try:
        return str(inspect.signature(obj))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def names() -> dict[str, object]:
    """Every public name in CadQuery's own modules, and each class's methods."""
    import importlib  # noqa: PLC0415

    found: dict[str, object] = {}
    # A class re-exported by several modules is listed once, by its first, shortest name.
    seen: set[int] = set()
    for root in ROOTS:
        module = importlib.import_module(root)
        for name, obj in vars(module).items():
            if name.startswith("_") or name in ALIASES or id(obj) in seen:
                continue
            owner = getattr(obj, "__module__", "") or ""
            if not owner.startswith("cadquery"):
                continue
            seen.add(id(obj))
            qualified = f"cq.{name}" if root == "cadquery" else f"{root}.{name}"
            found.setdefault(qualified, obj)
            if inspect.isclass(obj):
                for attr, member in vars(obj).items():
                    if not attr.startswith("_"):
                        found.setdefault(f"{qualified}.{attr}", member)
    return found


def ocp(query: str) -> list[dict]:
    import importlib  # noqa: PLC0415

    fragment = query.removeprefix("OCP.").lower()
    found = []
    for module_name in OCP_MODULES:
        module = importlib.import_module(f"OCP.{module_name}")
        for name in dir(module):
            qualified = f"OCP.{module_name}.{name}"
            if not name.startswith("_") and fragment in qualified.lower():
                found.append({"name": qualified, "signature": "", "doc": ""})
    return found


def lookup(query: str) -> dict:
    query = query.strip()
    if not query:
        return {"query": query, "error": "name a function, a class or a fragment of one"}
    if query.startswith("OCP"):
        found = ocp(query)
    else:
        fragment = query.removeprefix("cadquery.").removeprefix("cq.").lower()
        found = []
        for qualified, obj in sorted(names().items()):
            if fragment in qualified.lower():
                member = obj.fget if isinstance(obj, property) else obj
                member = getattr(member, "__func__", member)
                found.append(
                    {
                        "name": qualified,
                        "signature": signature(member) if callable(member) else "",
                        "doc": first_paragraph(getattr(member, "__doc__", None)),
                    }
                )
        # Exact and shorter names first: `makeHelix` before every name that holds it.
        found.sort(key=lambda f: (not f["name"].lower().endswith(fragment), len(f["name"])))
    return {"query": query, "matches": len(found), "found": found[:LIMIT]}


def main() -> None:
    print(MARK + json.dumps(lookup(sys.argv[1] if len(sys.argv) > 1 else "")))


if __name__ == "__main__":
    main()

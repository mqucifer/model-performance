"""The lookup index's builder (mqucifer/model-performance#40, A2): every public name in
the installed library, inherited members included, each function listed once with
every class it's on. Built at the image's build; tested here on a small stand-in."""

from __future__ import annotations

import types

from cad_eval.image import lookup_index


def stand_in() -> types.ModuleType:
    module = types.ModuleType("fakecq.shapes")

    class Shape:
        """A shape.

        More words."""

        def fuse(self, *others: object, glue: bool = False) -> Shape:
            """Fuse shapes."""
            return self

        def isValid(self) -> bool:  # noqa: N802
            return True

        def _private(self) -> None:
            pass

    class Solid(Shape):
        def extrudeLinear(self, face: object, vec: object) -> Solid:  # noqa: N802
            """Extrude a face."""
            return self

    class Compound(Shape):
        pass

    def free(shape: object, distance: float) -> object:
        """A free function."""
        return shape

    for obj in (Shape, Solid, Compound, free):
        obj.__module__ = "fakecq.shapes"
        setattr(module, obj.__name__, obj)
    return module


def entries() -> dict[str, dict]:
    found = lookup_index.library([("fq", stand_in())], prefix="fakecq")
    return {e["name"]: e for e in found}


def test_an_inherited_method_is_listed_once_with_every_class_its_on() -> None:
    found = entries()
    fuse = found["fq.Shape.fuse"]
    assert fuse["on"] == ["fq.Compound", "fq.Shape", "fq.Solid"]
    assert fuse["signature"] == "(self, *others: 'object', glue: 'bool' = False) -> 'Shape'"
    assert fuse["doc"] == "Fuse shapes."
    # Not again as Solid's or Compound's own.
    assert "fq.Solid.fuse" not in found and "fq.Compound.fuse" not in found


def test_a_method_a_class_defines_itself_is_its_own() -> None:
    found = entries()
    assert found["fq.Solid.extrudeLinear"]["on"] == ["fq.Solid"]
    assert found["fq.Shape.isValid"]["on"] == ["fq.Compound", "fq.Shape", "fq.Solid"]


def test_classes_and_free_functions_are_listed_and_private_names_arent() -> None:
    found = entries()
    assert found["fq.Shape"]["kind"] == "class"
    assert found["fq.Shape"]["doc"] == "A shape."
    assert found["fq.free"]["kind"] == "function"
    assert not any("_private" in name for name in found)


def test_a_signature_from_a_docstrings_overloads() -> None:
    """pybind11 (OCP) gives no `inspect.signature`: its overloads are in the docstring."""
    doc = "Value(self: OCP.BRepExtrema.BRepExtrema_DistShapeShape) -> float\n\nReturns it."
    assert lookup_index.overloads(doc) == [
        "Value(self: OCP.BRepExtrema.BRepExtrema_DistShapeShape) -> float"
    ]
    two = "1. f(x: int) -> None\n\n2. f(x: float) -> None\n\nDoes f."
    assert lookup_index.overloads(two) == ["f(x: int) -> None", "f(x: float) -> None"]

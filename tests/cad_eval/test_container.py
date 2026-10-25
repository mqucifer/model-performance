from pathlib import Path

from cad_eval import container


def test_a_part_is_held_by_crews_sandbox_with_cadquerys_image(tmp_path: Path) -> None:
    held = container.held(tmp_path, "spacer-1")
    argv = held.sandbox.command(tmp_path, ["true"], network=False, held=held.name)
    assert held.sandbox.image == container.IMAGE
    assert held.declared.services == []
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert "ALL" in argv[argv.index("--cap-drop") :]


def test_an_image_that_isnt_built_has_no_id() -> None:
    assert container.image_id("model-performance/not-built:0") is None


def test_no_engine_means_no_image(tmp_path: Path) -> None:
    assert container.image_id(engine=str(tmp_path / "no-docker")) is None

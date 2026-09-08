import pytest

from mesh.scene import Scene, new_primitive


@pytest.fixture
def viewport(qapp, close_qt_widget):
    from mesh.viewport import Viewport

    return close_qt_widget(Viewport())


def test_viewport_constructs(viewport):
    assert viewport is not None


def test_refresh_creates_one_actor_per_shape(viewport):
    scene = Scene()
    scene.add(new_primitive("cube"))
    scene.add(new_primitive("sphere"))
    viewport.set_scene(scene)
    viewport.refresh()
    assert all(viewport.actor_for(s.id) is not None for s in scene.shapes)


def test_refresh_drops_actors_for_removed_shapes(viewport):
    scene = Scene()
    shape = new_primitive("cube")
    scene.add(shape)
    viewport.set_scene(scene)
    viewport.refresh()
    scene.remove([shape.id])
    viewport.refresh()
    assert viewport.actor_for(shape.id) is None


def test_hidden_shapes_get_no_actor(viewport):
    scene = Scene()
    shape = new_primitive("cube")
    shape.visible = False
    scene.add(shape)
    viewport.set_scene(scene)
    viewport.refresh()
    assert viewport.actor_for(shape.id) is None


def test_holes_render_translucent(viewport):
    scene = Scene()
    solid, hole = new_primitive("cube"), new_primitive("sphere")
    hole.is_hole = True
    scene.add(solid)
    scene.add(hole)
    viewport.set_scene(scene)
    viewport.refresh()
    assert viewport.actor_for(hole.id).GetProperty().GetOpacity() < 1.0
    assert viewport.actor_for(solid.id).GetProperty().GetOpacity() == 1.0


@pytest.mark.parametrize("preset", ["home", "top", "front", "right"])
def test_every_view_preset_runs(viewport, preset):
    viewport.set_scene(Scene())
    viewport.view_preset(preset)


def test_unknown_view_preset_raises(viewport):
    with pytest.raises(ValueError):
        viewport.view_preset("sideways")


def test_frame_selection_with_nothing_selected_is_safe(viewport):
    viewport.set_scene(Scene())
    viewport.frame_selection()

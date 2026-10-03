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


def test_measure_line_is_drawn_on_top_of_the_parts(viewport):
    # The line's two points sit on a part's surface, so in the parts' own
    # layer it was hidden inside the part or shrank to a 1 px sliver. It is
    # drawn in a layer above them that shares their camera.
    viewport.set_measure_line((-10.0, 0.0, 20.0), (10.0, 0.0, 20.0))
    actor = viewport.measure_actor
    assert viewport.overlay.HasViewProp(actor)
    assert not viewport.renderer.HasViewProp(actor)
    assert viewport.overlay.GetLayer() > viewport.renderer.GetLayer()
    assert viewport.overlay.GetActiveCamera() is viewport.renderer.GetActiveCamera()
    assert not viewport.overlay.GetInteractive()
    assert viewport.overlay.GetRenderWindow().GetNumberOfLayers() >= 2


def test_measure_line_is_a_few_pixels_thick(viewport):
    viewport.set_measure_line((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
    prop = viewport.measure_actor.GetProperty()
    assert prop.GetLineWidth() >= 4.0
    assert prop.GetRenderLinesAsTubes()


def test_clearing_the_measure_line_removes_it_from_the_top_layer(viewport):
    viewport.set_measure_line((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
    actor = viewport.measure_actor
    viewport.clear_measure_line()
    assert viewport.measure_actor is None
    assert not viewport.overlay.HasViewProp(actor)

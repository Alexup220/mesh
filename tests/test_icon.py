from mesh.app import ICON_DIR, ICON_SIZES, app_icon


def test_icon_files_ship_with_mesh():
    assert (ICON_DIR / "mesh.svg").is_file()
    for size in ICON_SIZES:
        assert (ICON_DIR / f"mesh-{size}.png").is_file()


def test_app_icon_has_every_size(qapp):
    icon = app_icon()
    assert not icon.isNull()
    sizes = {s.width() for s in icon.availableSizes()}
    assert sizes == set(ICON_SIZES)

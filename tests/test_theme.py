def test_apply_theme_sets_a_stylesheet(qapp):
    from mesh.theme import apply_theme

    apply_theme(qapp)
    assert len(qapp.styleSheet()) > 100


def test_apply_theme_is_idempotent(qapp):
    from mesh.theme import apply_theme

    apply_theme(qapp)
    first = qapp.styleSheet()
    apply_theme(qapp)
    assert qapp.styleSheet() == first

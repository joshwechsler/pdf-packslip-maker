from packslip import help_text, password


def test_every_spot_has_starter_text_until_it_is_edited():
    s = {}
    for key, label, _ in help_text.SPOTS:
        assert help_text.get(s, key), key
    help_text.set_all(s, {"orders": "Export from the store.", "drivers": ""})
    assert help_text.get(s, "orders") == "Export from the store."
    assert help_text.get(s, "drivers") == ""                       # blank: the ? is hidden
    assert help_text.get(s, "meals") == help_text.DEFAULTS["meals"]


def test_text_is_trimmed_but_line_breaks_kept():
    s = {}
    help_text.set_all(s, {"orders": "  1. Export\n2. Drop it here \n\n"})
    assert help_text.get(s, "orders") == "1. Export\n2. Drop it here"


def test_password_is_stored_hashed_and_checked():
    s = {}
    assert not password.is_set(s) and password.check(s, "anything")   # no password yet: open
    password.set_password(s, "Honey123")
    assert password.is_set(s) and "Honey123" not in str(s)
    assert password.check(s, "Honey123") and not password.check(s, "honey123") and not password.check(s, "")
    password.set_password(s, "")                                       # cleared: open again
    assert not password.is_set(s)

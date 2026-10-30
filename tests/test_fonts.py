import shutil
import struct
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from packslip import fonts
from packslip.layout import fit_text, pdf_font

BUNDLED = Path(fonts.__file__).parent / "assets" / "fonts"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKSLIP_DATA_DIR", str(tmp_path / "data"))
    fonts.reset()
    yield
    fonts.reset()


def test_starter_fonts_are_listed_after_the_basic_three():
    names = fonts.families()
    assert names[:3] == ["Helvetica", "Times", "Courier"]
    for fam in ("Lato", "Montserrat", "Oswald", "Playfair Display", "Roboto Condensed"):
        assert fam in names


def test_starter_fonts_print_in_a_pdf_with_bold_and_italic(tmp_path):
    faces = {pdf_font("Montserrat", b, i) for b in (False, True) for i in (False, True)}
    assert len(faces) == 4 and "Helvetica" not in faces
    c = Canvas(str(tmp_path / "t.pdf"))
    for face in faces:
        c.setFont(face, 12)
        c.drawString(10, 10, "Kara Anglim — Bag: 2/4")
    c.save()
    assert b"Montserrat" in (tmp_path / "t.pdf").read_bytes()
    assert fit_text("Long customer name here", "Oswald", True, False, 20, 60, 100).font != "Helvetica-Bold"


def test_a_missing_style_uses_the_same_font_not_helvetica():
    # Oswald has no italic: italic falls back to Oswald, keeping the look.
    assert pdf_font("Oswald", False, True) == pdf_font("Oswald", False, False)
    assert pdf_font("Oswald", True, True) == pdf_font("Oswald", True, False)


def test_unknown_font_prints_in_helvetica_and_is_reported():
    assert pdf_font("Brand Sans", True, False) == "Helvetica-Bold"
    assert not fonts.available("Brand Sans") and fonts.available("Lato") and fonts.available("Times")


def test_added_font_is_kept_and_listed(tmp_path):
    src = tmp_path / "MyBrand.ttf"
    shutil.copy(BUNDLED / "Lato" / "Lato-Regular.ttf", src)   # stands in for a font file from the Mac
    added = fonts.add_font_files([src])
    assert added == ["Lato"]
    assert (fonts.user_dir() / "MyBrand.ttf").exists()
    fonts.reset()
    assert "Lato" in fonts.families()


def _fake_font(path: Path, version: bytes, tag: bytes) -> Path:
    path.write_bytes(version + struct.pack(">HHHH", 1, 16, 0, 0) + tag + b"\0" * 12)
    return path


def test_fonts_a_pdf_cant_use_are_refused_with_a_reason(tmp_path):
    with pytest.raises(fonts.FontError, match="static"):
        fonts.add_font_files([_fake_font(tmp_path / "Var.ttf", b"\0\1\0\0", b"fvar")])
    with pytest.raises(fonts.FontError, match=".ttf"):
        fonts.add_font_files([_fake_font(tmp_path / "Cff.otf", b"OTTO", b"CFF ")])
    with pytest.raises(fonts.FontError, match=".ttf"):
        fonts.add_font_files([_fake_font(tmp_path / "Pack.ttc", b"ttcf", b"head")])
    (tmp_path / "junk.ttf").write_bytes(b"not a font")
    with pytest.raises(fonts.FontError):
        fonts.add_font_files([tmp_path / "junk.ttf"])
    assert not fonts.user_dir().exists() or not any(fonts.user_dir().iterdir())


def test_layout_keeps_a_font_that_isnt_installed():
    from packslip.template import normalize_element
    el = normalize_element({"type": "text", "text": "Hi", "font": "Brand Sans"})
    assert el["font"] == "Brand Sans"


def test_generating_warns_about_fonts_this_mac_doesnt_have():
    from packslip import template as T
    from packslip.pdfgen import font_warnings
    tpl = T.default_template()
    assert font_warnings(tpl) == []
    tpl.elements[0]["font"] = "Brand Sans"
    tpl.elements[1]["font"] = "Brand Sans"
    (w,) = font_warnings(tpl, T.default_template())
    assert "Brand Sans" in w and "Helvetica" in w and "Add Font" in w

"""
Unit tests for PDF structure preservation in bank_statement_anonymiser.

This module tests that anonymise_pdf() leaves the PDF skeleton intact:
- Page count unchanged
- MediaBox dimensions unchanged per page
- Font resources still present (by name) on each page
- Image/XObject resources still present after anonymisation
- Output is a valid, openable PDF
- Content streams remain parseable
- Default output path naming convention (anonymised_ prefix)
- Custom output path honoured
- Missing parent directory created automatically
- Return value is a Path pointing to the written file
"""

from __future__ import annotations

import struct
from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf

# ---------------------------------------------------------------------------
# Helpers: build synthetic PDF fixtures inline
# ---------------------------------------------------------------------------

_SIMPLE_CONTENT = b"""
BT
/F1 12 Tf
50 750 Td
(Statement Date: 01 Jan 25) Tj
0 -20 Td
(John Smith) Tj
0 -20 Td
(40-37-28) Tj
ET
"""


def _make_simple_pdf(tmp_path: Path, filename: str = "test.pdf") -> Path:
    """One-page PDF with a single Latin-1 font (F1 = Helvetica)."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, _SIMPLE_CONTENT)
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
            )
        )
    )
    out = tmp_path / filename
    pdf.save(str(out))
    return out


def _make_multipage_pdf(tmp_path: Path, n_pages: int = 3) -> Path:
    """Multi-page PDF; each page has the same simple content."""
    pdf = pikepdf.Pdf.new()
    for _ in range(n_pages):
        page = pdf.add_blank_page(page_size=(595, 842))
        page.Contents = pikepdf.Stream(pdf, _SIMPLE_CONTENT)
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                F1=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font,
                    Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica,
                )
            )
        )
    out = tmp_path / "multi.pdf"
    pdf.save(str(out))
    return out


def _make_pdf_with_image(tmp_path: Path) -> Path:
    """One-page PDF that contains a 2×2 black-and-white image XObject."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, _SIMPLE_CONTENT)

    # Minimal 1-bit 2×2 image: two bytes = 4 pixels
    raw_image_bytes = bytes([0b11001100, 0b10101010])
    image_stream = pikepdf.Stream(pdf, raw_image_bytes)
    image_stream.stream_dict = pikepdf.Dictionary(
        Type=pikepdf.Name.XObject,
        Subtype=pikepdf.Name.Image,
        Width=2,
        Height=2,
        ColorSpace=pikepdf.Name.DeviceGray,
        BitsPerComponent=1,
    )

    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
            )
        ),
        XObject=pikepdf.Dictionary(Im0=image_stream),
    )
    out = tmp_path / "with_image.pdf"
    pdf.save(str(out))
    return out


def _make_pdf_with_custom_mediabox(tmp_path: Path) -> Path:
    """One-page PDF with a non-standard MediaBox (200×300 points)."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 300))
    page.Contents = pikepdf.Stream(pdf, _SIMPLE_CONTENT)
    page.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
            )
        )
    )
    out = tmp_path / "custom_box.pdf"
    pdf.save(str(out))
    return out


def _get_mediabox(page_obj: pikepdf.Object) -> tuple[float, float, float, float]:
    """Return the four MediaBox values as floats."""
    mb = page_obj["/MediaBox"]
    return tuple(float(v) for v in mb)  # type: ignore[return-value]


def _get_font_names(page_obj: pikepdf.Object) -> set[str]:
    """Return the set of font resource names (e.g. {'/F1'}) on a page."""
    try:
        res = page_obj.get("/Resources", pikepdf.Dictionary())
        font_dict = res.get("/Font", pikepdf.Dictionary())
        return {str(k) for k in font_dict}
    except Exception:
        return set()


def _get_xobject_names(page_obj: pikepdf.Object) -> set[str]:
    """Return the set of XObject resource names on a page."""
    try:
        res = page_obj.get("/Resources", pikepdf.Dictionary())
        xobj = res.get("/XObject", pikepdf.Dictionary())
        return {str(k) for k in xobj}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Module 6: Output path handling
# ---------------------------------------------------------------------------


class TestOutputPathHandling:
    """Tests for output path logic in anonymise_pdf()."""

    @pytest.mark.unit
    def test_returns_path_object(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        result = anonymise_pdf(src, output_path=tmp_path / "out.pdf")
        assert isinstance(result, Path)

    @pytest.mark.unit
    def test_returned_path_exists(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_custom_output_path_used(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "custom_name.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result == out
        assert out.exists()

    @pytest.mark.unit
    def test_default_output_path_has_anonymised_prefix(self, tmp_path):
        src = _make_simple_pdf(tmp_path, filename="statement.pdf")
        result = anonymise_pdf(src)
        assert result.name == "anonymised_statement.pdf"

    @pytest.mark.unit
    def test_default_output_path_same_directory(self, tmp_path):
        src = _make_simple_pdf(tmp_path, filename="statement.pdf")
        result = anonymise_pdf(src)
        assert result.parent == tmp_path

    @pytest.mark.unit
    def test_missing_parent_directory_created(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        nested_out = tmp_path / "deeply" / "nested" / "out.pdf"
        assert not nested_out.parent.exists()
        result = anonymise_pdf(src, output_path=nested_out)
        assert result.exists()
        assert nested_out.parent.exists()

    @pytest.mark.unit
    def test_output_is_nonempty_file(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Module 6: Page count preserved
# ---------------------------------------------------------------------------


class TestPageCountPreserved:
    """Anonymisation must not add or remove pages."""

    @pytest.mark.unit
    def test_single_page_count_preserved(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            assert len(result_pdf.pages) == 1

    @pytest.mark.unit
    def test_multipage_count_preserved(self, tmp_path):
        src = _make_multipage_pdf(tmp_path, n_pages=3)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            assert len(result_pdf.pages) == 3

    @pytest.mark.unit
    def test_two_page_count_preserved(self, tmp_path):
        src = _make_multipage_pdf(tmp_path, n_pages=2)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            assert len(result_pdf.pages) == 2


# ---------------------------------------------------------------------------
# Module 6: MediaBox dimensions preserved
# ---------------------------------------------------------------------------


class TestMediaBoxPreserved:
    """Page dimensions (MediaBox) must be identical before and after anonymisation."""

    @pytest.mark.unit
    def test_a4_mediabox_preserved(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            before = _get_mediabox(orig.pages[0].obj)
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            after = _get_mediabox(result_pdf.pages[0].obj)
        assert before == after

    @pytest.mark.unit
    def test_custom_mediabox_preserved(self, tmp_path):
        src = _make_pdf_with_custom_mediabox(tmp_path)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            before = _get_mediabox(orig.pages[0].obj)
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            after = _get_mediabox(result_pdf.pages[0].obj)
        assert before == after

    @pytest.mark.unit
    def test_mediabox_width_preserved(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(src)) as orig, pikepdf.open(str(out)) as result_pdf:
            orig_mb = _get_mediabox(orig.pages[0].obj)
            out_mb = _get_mediabox(result_pdf.pages[0].obj)
        assert orig_mb[2] == out_mb[2]  # width = x2

    @pytest.mark.unit
    def test_mediabox_height_preserved(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(src)) as orig, pikepdf.open(str(out)) as result_pdf:
            orig_mb = _get_mediabox(orig.pages[0].obj)
            out_mb = _get_mediabox(result_pdf.pages[0].obj)
        assert orig_mb[3] == out_mb[3]  # height = y2

    @pytest.mark.unit
    def test_multipage_all_mediaboxes_preserved(self, tmp_path):
        src = _make_multipage_pdf(tmp_path, n_pages=3)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            before = [_get_mediabox(p.obj) for p in orig.pages]
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            after = [_get_mediabox(p.obj) for p in result_pdf.pages]
        assert before == after


# ---------------------------------------------------------------------------
# Module 6: Font resources preserved
# ---------------------------------------------------------------------------


class TestFontResourcesPreserved:
    """Font resource dictionaries must survive unchanged through anonymisation."""

    @pytest.mark.unit
    def test_font_resource_present_after_anonymisation(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            names = _get_font_names(result_pdf.pages[0].obj)
        assert "/F1" in names

    @pytest.mark.unit
    def test_font_resource_names_unchanged(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            before = _get_font_names(orig.pages[0].obj)
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            after = _get_font_names(result_pdf.pages[0].obj)
        assert before == after

    @pytest.mark.unit
    def test_font_basefont_unchanged(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            res = result_pdf.pages[0].obj.get("/Resources", pikepdf.Dictionary())
            font_obj = res["/Font"]["/F1"]
            base_font = str(font_obj.get("/BaseFont", ""))
        assert "Helvetica" in base_font

    @pytest.mark.unit
    def test_resources_dict_present(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            page_obj = result_pdf.pages[0].obj
            res = page_obj.get("/Resources", None)
        assert res is not None


# ---------------------------------------------------------------------------
# Module 6: Image/XObject resources preserved
# ---------------------------------------------------------------------------


class TestImageResourcesPreserved:
    """XObject resources (images) must be present and unchanged after anonymisation."""

    @pytest.mark.unit
    def test_xobject_names_preserved(self, tmp_path):
        src = _make_pdf_with_image(tmp_path)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            before = _get_xobject_names(orig.pages[0].obj)
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            after = _get_xobject_names(result_pdf.pages[0].obj)
        assert before == after

    @pytest.mark.unit
    def test_image_subtype_preserved(self, tmp_path):
        src = _make_pdf_with_image(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            res = result_pdf.pages[0].obj.get("/Resources", pikepdf.Dictionary())
            xobj = res.get("/XObject", pikepdf.Dictionary())
            im = xobj["/Im0"]
            subtype = str(im.get("/Subtype", ""))
        assert subtype == "/Image"

    @pytest.mark.unit
    def test_image_dimensions_preserved(self, tmp_path):
        src = _make_pdf_with_image(tmp_path)
        out = tmp_path / "out.pdf"
        with pikepdf.open(str(src)) as orig:
            res_orig = orig.pages[0].obj["/Resources"]["/XObject"]["/Im0"]
            w_before = int(res_orig["/Width"])
            h_before = int(res_orig["/Height"])
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            res_out = result_pdf.pages[0].obj["/Resources"]["/XObject"]["/Im0"]
            w_after = int(res_out["/Width"])
            h_after = int(res_out["/Height"])
        assert (w_before, h_before) == (w_after, h_after)


# ---------------------------------------------------------------------------
# Module 6: Output is a valid, parseable PDF
# ---------------------------------------------------------------------------


class TestOutputIsValidPdf:
    """The output must be a well-formed PDF that can be opened and parsed."""

    @pytest.mark.unit
    def test_output_opens_with_pikepdf(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        # Should not raise
        with pikepdf.open(str(out)) as result_pdf:
            assert result_pdf is not None

    @pytest.mark.unit
    def test_output_content_streams_parseable(self, tmp_path):
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            for page in result_pdf.pages:
                # parse_content_stream must not raise
                instructions = list(pikepdf.parse_content_stream(page))
                assert len(instructions) > 0

    @pytest.mark.unit
    def test_output_pdf_version_present(self, tmp_path):
        """The output PDF must have a recognisable header (starts with %PDF-)."""
        src = _make_simple_pdf(tmp_path)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        header = out.read_bytes()[:8]
        assert header.startswith(b"%PDF-")

    @pytest.mark.unit
    def test_multipage_all_streams_parseable(self, tmp_path):
        src = _make_multipage_pdf(tmp_path, n_pages=3)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        with pikepdf.open(str(out)) as result_pdf:
            for page in result_pdf.pages:
                instructions = list(pikepdf.parse_content_stream(page))
                assert len(instructions) > 0

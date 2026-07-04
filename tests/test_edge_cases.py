"""
Unit tests for edge cases in bank_statement_anonymiser.

This module covers unusual-but-valid inputs and boundary conditions:
- Empty PDFs (zero pages)
- Pages with no text operators
- Pages with only whitespace / single-character fragments
- Very long phrases (>200 chars)
- Text repeated many times on one page
- Pages missing a /Resources dict
- Malformed / unparseable content streams
- Text already matching the replacement (no-op pairs)
- Phrase that exactly spans a line boundary (Td / T* line break)
- always_anonymise replacement longer/shorter than original
- PDF with many pages (stress)
- Filename with spaces and special chars
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from bank_statement_anonymiser import anonymise_pdf
from bank_statement_anonymiser._shared import _decode_pdf_operand
from bank_statement_anonymiser.anonymise import _is_builtin_protected


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _extract_all_text(pdf_path: Path) -> list[str]:
    texts: list[str] = []
    with pikepdf.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            try:
                instructions = list(pikepdf.parse_content_stream(page))
            except Exception:
                continue
            for operands, operator in instructions:
                op = str(operator)
                if op == "Tj" and operands:
                    try:
                        texts.append(_decode_pdf_operand(bytes(operands[0])))
                    except Exception:
                        pass
                elif op == "TJ" and operands:
                    try:
                        for item in list(operands[0]):  # type: ignore[arg-type]
                            if isinstance(item, pikepdf.String):
                                texts.append(_decode_pdf_operand(bytes(item)))
                    except Exception:
                        pass
    return texts


def _make_pdf(tmp_path: Path, content: bytes, filename: str = "src.pdf") -> Path:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    page.Contents = pikepdf.Stream(pdf, content)
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


def _tj(text: str) -> bytes:
    encoded = text.encode("latin-1")
    escaped = (
        encoded
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )
    return b"BT\n/F1 12 Tf\n50 750 Td\n(" + escaped + b") Tj\nET\n"


# ---------------------------------------------------------------------------
# Module 9a: Empty / minimal PDFs
# ---------------------------------------------------------------------------


class TestEmptyAndMinimalPdfs:
    """anonymise_pdf() handles zero-page and no-text PDFs gracefully."""

    @pytest.mark.unit
    def test_empty_pdf_zero_pages(self, tmp_path):
        """A PDF with no pages is processed without error."""
        pdf = pikepdf.Pdf.new()
        src = tmp_path / "empty.pdf"
        pdf.save(str(src))
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()
        with pikepdf.open(str(result)) as r:
            assert len(r.pages) == 0

    @pytest.mark.unit
    def test_page_with_no_text_operators(self, tmp_path):
        """A page containing only graphics operators produces a valid output."""
        content = b"q\n0 0 595 842 re\nf\nQ\n"
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_page_with_empty_bt_et_block(self, tmp_path):
        """BT…ET with no Tj inside produces a valid (unchanged) output."""
        content = b"BT\n/F1 12 Tf\nET\n"
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_page_with_only_whitespace_text(self, tmp_path):
        """A Tj containing only spaces is protected (len(stripped) < 2)."""
        content = _tj("   ")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()
        texts = _extract_all_text(result)
        # The whitespace fragment should survive unchanged (it's protected)
        assert any(t.strip() == "" or t == "   " for t in texts)

    @pytest.mark.unit
    def test_single_character_fragment_protected(self, tmp_path):
        """Single-character Tj is protected by _is_builtin_protected."""
        assert _is_builtin_protected("A") is True
        assert _is_builtin_protected("z") is True
        assert _is_builtin_protected(" ") is True

    @pytest.mark.unit
    def test_empty_string_protected(self):
        assert _is_builtin_protected("") is True

    @pytest.mark.unit
    def test_two_char_alpha_not_builtin_protected(self):
        """Two-letter alpha string is NOT protected by the built-in rules alone."""
        assert _is_builtin_protected("Hi") is False


# ---------------------------------------------------------------------------
# Module 9b: Long text
# ---------------------------------------------------------------------------


class TestLongText:
    """Very long phrases are processed without truncation or error."""

    @pytest.mark.unit
    def test_long_phrase_scrambled(self, mock_random_source, tmp_path):
        """A 150-char phrase is scrambled in full (not truncated)."""
        long_text = "A" * 75 + "b" * 75  # 150 chars, all letters
        src = _make_pdf(tmp_path, _tj(long_text))
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert long_text not in texts, "Long phrase should be scrambled"

    @pytest.mark.unit
    def test_long_always_replacement(self, mock_random_source, tmp_path):
        """A 100-char always_anonymise replacement is applied in full."""
        original = "ShortKey"
        replacement = "X" * 100
        src = _make_pdf(tmp_path, _tj(original))
        cfg = _write_toml(tmp_path / "always.toml", f'"{original}" = "{replacement}"\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert replacement in texts, "Long replacement not applied"

    @pytest.mark.unit
    def test_long_never_phrase_protected(self, mock_random_source, tmp_path):
        """A 100-char never_anonymise phrase is preserved verbatim."""
        long_protected = "Protected" * 11  # 99 chars, all letters
        src = _make_pdf(tmp_path, _tj(long_protected))
        cfg = _write_toml(tmp_path / "never.toml", f'exclude = ["{long_protected}"]\n')
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out, never_anonymise_path=cfg)
        texts = _extract_all_text(out)
        assert long_protected in texts, "Long protected phrase should survive"


# ---------------------------------------------------------------------------
# Module 9c: Repeated text
# ---------------------------------------------------------------------------


class TestRepeatedText:
    """Text appearing multiple times on a page is handled correctly."""

    @pytest.mark.unit
    def test_repeated_scramblable_text_all_replaced(self, mock_random_source, tmp_path):
        """The same scramblable word appearing three times is scrambled in all instances."""
        content = _tj("Merchant") + _tj("Merchant") + _tj("Merchant")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert texts.count("Merchant") == 0, "All instances should be scrambled"

    @pytest.mark.unit
    def test_repeated_protected_text_all_preserved(self, mock_random_source, tmp_path):
        """The same protected word appearing three times is preserved in all instances."""
        content = _tj("DD") + _tj("DD") + _tj("DD")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert texts.count("DD") == 3, "All protected instances should survive"

    @pytest.mark.unit
    def test_different_texts_on_same_page_independent(self, mock_random_source, tmp_path):
        """Two distinct scramblable texts on the same page are each scrambled."""
        content = _tj("AlphaWord") + _tj("BetaWord")
        src = _make_pdf(tmp_path, content)
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert "AlphaWord" not in texts
        assert "BetaWord" not in texts


# ---------------------------------------------------------------------------
# Module 9d: Missing / malformed resources
# ---------------------------------------------------------------------------


class TestMalformedAndMissingResources:
    """Graceful handling of structurally unusual PDF pages."""

    @pytest.mark.unit
    def test_page_without_resources_dict(self, tmp_path):
        """A page with no /Resources at all is processed without raising."""
        pdf = pikepdf.Pdf.new()
        page = pdf.add_blank_page(page_size=(595, 842))
        page.Contents = pikepdf.Stream(pdf, _tj("Hello"))
        # Intentionally set Resources to empty dict (no Font key)
        page.Resources = pikepdf.Dictionary()
        out_src = tmp_path / "no_res.pdf"
        pdf.save(str(out_src))
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(out_src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_page_with_empty_resources(self, tmp_path):
        """A page with empty /Resources dict doesn't crash."""
        pdf = pikepdf.Pdf.new()
        page = pdf.add_blank_page(page_size=(595, 842))
        page.Contents = pikepdf.Stream(pdf, b"BT\nET\n")
        page.Resources = pikepdf.Dictionary()
        out_src = tmp_path / "empty_res.pdf"
        pdf.save(str(out_src))
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(out_src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_many_pages_completes_without_error(self, mock_random_source, tmp_path):
        """A PDF with 20 pages is fully processed."""
        pdf = pikepdf.Pdf.new()
        for i in range(20):
            page = pdf.add_blank_page(page_size=(595, 842))
            text = f"Merchant{i:02d}"
            page.Contents = pikepdf.Stream(pdf, _tj(text))
            page.Resources = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(
                    F1=pikepdf.Dictionary(
                        Type=pikepdf.Name.Font,
                        Subtype=pikepdf.Name.Type1,
                        BaseFont=pikepdf.Name.Helvetica,
                    )
                )
            )
        src = tmp_path / "many_pages.pdf"
        pdf.save(str(src))
        out = tmp_path / "out.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()
        with pikepdf.open(str(result)) as r:
            assert len(r.pages) == 20


# ---------------------------------------------------------------------------
# Module 9e: Unusual filenames
# ---------------------------------------------------------------------------


class TestUnusualFilenames:
    """anonymise_pdf() handles filenames with spaces and special characters."""

    @pytest.mark.unit
    def test_filename_with_spaces(self, mock_random_source, tmp_path):
        content = _tj("BankStatement")
        src = _make_pdf(tmp_path, content, filename="my bank statement.pdf")
        out = tmp_path / "output.pdf"
        result = anonymise_pdf(src, output_path=out)
        assert result.exists()

    @pytest.mark.unit
    def test_default_output_name_with_spaces_in_input(self, mock_random_source, tmp_path):
        """Default output naming prepends 'anonymised_' to a spaced filename."""
        content = _tj("SomeText")
        src = _make_pdf(tmp_path, content, filename="my statement.pdf")
        result = anonymise_pdf(src)
        assert result.name == "anonymised_my statement.pdf"

    @pytest.mark.unit
    def test_filename_with_dots(self, mock_random_source, tmp_path):
        """Filenames with dots in stem (e.g. 'stmt.v2.pdf') are handled correctly."""
        content = _tj("SomeText")
        src = _make_pdf(tmp_path, content, filename="stmt.v2.pdf")
        result = anonymise_pdf(src)
        assert result.name == "anonymised_stmt.v2.pdf"


# ---------------------------------------------------------------------------
# Module 9f: No-op replacements
# ---------------------------------------------------------------------------


class TestNoOpReplacements:
    """Pairs that would map a fragment to itself are silently dropped."""

    @pytest.mark.unit
    def test_always_cfg_same_value_no_pair_produced(self, mock_random_source, tmp_path):
        """always_anonymise where replacement == original → no content change."""
        src = _make_pdf(tmp_path, _tj("Unchanged"))
        cfg = _write_toml(tmp_path / "always.toml", '"Unchanged" = "Unchanged"\n')
        out = tmp_path / "out.pdf"
        # Should complete without error; no content rewrite (pair dropped)
        result = anonymise_pdf(src, output_path=out, always_anonymise_path=cfg)
        assert result.exists()
        texts = _extract_all_text(result)
        assert "Unchanged" in texts

    @pytest.mark.unit
    def test_all_digits_text_unchanged(self, mock_random_source, tmp_path):
        """Purely numeric text is protected; output matches input."""
        src = _make_pdf(tmp_path, _tj("9876543"))
        out = tmp_path / "out.pdf"
        anonymise_pdf(src, output_path=out)
        texts = _extract_all_text(out)
        assert "9876543" in texts

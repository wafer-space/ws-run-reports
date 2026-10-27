"""Densities on the pages carry their unit, /mm², on the figure itself."""

from ws_run_reports.site import _per_mm2, template_environment


def test_per_mm2_rounds_to_thousands_and_adds_the_unit():
    assert str(_per_mm2(21800)) == '<span class="run-per">22k<span class="run-unit">/mm²</span></span>'


def test_per_mm2_full_keeps_every_digit():
    assert str(_per_mm2(21834.4, full=True)) == '<span class="run-per">21,834<span class="run-unit">/mm²</span></span>'


def test_per_mm2_escapes_the_figure():
    # Under 500 the figure reads "<1k", which must reach the page as text, not markup.
    assert str(_per_mm2(400)).startswith('<span class="run-per">&lt;1k<span')


def test_per_mm2_is_a_template_filter_whose_markup_is_not_escaped_again():
    env = template_environment()
    html = env.from_string("{{ v | per_mm2 }} {{ v | per_mm2(full=true) }}").render(v=114000)
    assert html == ('<span class="run-per">114k<span class="run-unit">/mm²</span></span> '
                    '<span class="run-per">114,000<span class="run-unit">/mm²</span></span>')

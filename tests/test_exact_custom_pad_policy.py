"""Controlled source/parser/site contract; no native geometry authority."""
import copy
from types import SimpleNamespace

import pytest

from kicad_parser import exact_custom_polygons
from seed_site_policy import SitePolicyRefusal, conventional_site_filter

SOURCE = """(pad "1" smd custom (at 0 0 270) (size .3 .3)
(layers "F.Cu" "F.Mask") (options (clearance outline) (anchor rect))
(primitives (gr_poly (pts (xy 1 0) (xy .5 .75) (xy -.5 .75)
(xy -.5 -.75) (xy .5 -.75)) (width 0) (fill yes))))"""


def pad(source=SOURCE):
    return SimpleNamespace(shape='custom', global_x=0., global_y=0.,
        size_x=1.5, size_y=1.5, rect_rotation=0., layers=['F.Cu', 'F.Mask'],
        anchor_size=(.3, .3), geometry_approximations=(),
        exact_custom_source=(source, 270.),
        polygons=exact_custom_polygons(source, 0., 0., 270.))


def filter_for(value):
    board = SimpleNamespace(footprints={'JP1': SimpleNamespace(pads=[value])},
        paste_apertures=[], board_info=SimpleNamespace(copper_layers=['F.Cu', 'B.Cu']))
    return conventional_site_filter(board, .6, ['F.Cu', 'B.Cu'])


def test_actual_straight_source_accepts_only_separated_site():
    allowed = filter_for(pad())
    assert not allowed(0., 0.)
    assert allowed(1.4, 0.)


@pytest.mark.parametrize('old,new', [('width 0', 'width .01'),
    ('fill yes', 'fill no'), ('xy 1 0', 'xy nan 0'),
    ('gr_poly', 'gr_arc'), ('xy .5 .75', 'arc (start .5 .75)')])
def test_unsupported_primitive_refuses(old, new):
    with pytest.raises((ValueError, TypeError)):
        exact_custom_polygons(SOURCE.replace(old, new), 0., 0., 270.)


@pytest.mark.parametrize('field,value', [('exact_custom_source', None),
    ('anchor_size', (.1, .1)), ('geometry_approximations', ('flattened',)),
    ('polygons', [[(0., 0.), (1., 0.), (0., 1.)]])])
def test_missing_or_substituted_provenance_refuses(field, value):
    changed = copy.deepcopy(pad())
    setattr(changed, field, value)
    with pytest.raises(SitePolicyRefusal):
        filter_for(changed)


def test_anchor_disk_is_checked_independently_of_off_anchor_polygon():
    source = SOURCE.replace('(xy 1 0) (xy .5 .75) (xy -.5 .75)\n(xy -.5 -.75) (xy .5 -.75)',
        '(xy 2 2) (xy 3 2) (xy 3 3) (xy 2 3)')
    allowed = filter_for(pad(source))
    assert not allowed(0., 0.)
    assert not allowed(.3 + (.3 ** 2 + .3 ** 2) ** .5 / 2, 0.)


@pytest.mark.parametrize('rotation', [0., 90., 270., -90.])
def test_exact_transform_and_layer_policy(rotation):
    value = pad()
    value.global_x, value.global_y = 12., -4.
    value.exact_custom_source = (SOURCE, rotation)
    value.polygons = exact_custom_polygons(SOURCE, 12., -4., rotation)
    value.layers = ['B.Cu', 'B.Mask']
    allowed = filter_for(value)
    assert not allowed(12., -4.)
    assert allowed(15., -4.)


@pytest.mark.parametrize('replacement', [
    '(xy 1e308 1e308)', '(xy 1 0) (xy 1 0)'])
def test_degenerate_or_overflowing_source_refuses(replacement):
    source = SOURCE.replace('(xy 1 0)', replacement)
    value = pad()
    value.exact_custom_source = (source, 45.)
    with pytest.raises((ValueError, SitePolicyRefusal)):
        value.polygons = exact_custom_polygons(source, 0., 0., 45.)
        filter_for(value)


def test_native_custom_without_text_provenance_refuses():
    value = pad()
    value.exact_custom_source = None
    with pytest.raises(SitePolicyRefusal):
        filter_for(value)


def test_padstack_source_refuses_even_with_retained_polygons():
    value = pad()
    value.exact_custom_source = (SOURCE[:-1] + '(padstack (mode normal)))', 270.)
    with pytest.raises(SitePolicyRefusal):
        filter_for(value)


@pytest.mark.parametrize('delta,expected', [(0., False), (1e-6, True), (-1e-6, False)])
def test_polygon_edge_strict_contact(delta, expected):
    # Left-facing edge of this unrotated polygon is x=-.5 at y=.4;
    # its anchor disk is far enough away to isolate polygon contact.
    value = pad()
    value.exact_custom_source = (SOURCE, 0.)
    value.polygons = exact_custom_polygons(SOURCE, 0., 0., 0.)
    assert filter_for(value)(-.8 - delta, .4) is expected


def test_portable_original_jp1_parser_to_policy():
    from pathlib import Path
    from kicad_parser import parse_kicad_pcb
    source = Path(__file__).with_name('jp1-exact-polygons.kicad_pcb')
    parsed = parse_kicad_pcb(str(source))
    actual = [p for p in parsed.footprints['JP1'].pads if p.pad_number in ('1', '2')]
    assert len(actual) == 2
    allowed = conventional_site_filter(parsed, 1.6, ['F.Cu', 'B.Cu'])
    for value in actual:
        assert value.exact_custom_source is not None
        assert value.anchor_size == (.3, .3)
        assert exact_custom_polygons(value.exact_custom_source[0], value.global_x,
            value.global_y, value.exact_custom_source[1]) == value.polygons
        assert not allowed(value.global_x, value.global_y)


@pytest.mark.parametrize('size', ['100000000 100000000', '1' + '0' * 307 + ' ' + '1' + '0' * 307])
def test_extreme_finite_circle_anchor_refuses_before_tessellation(size):
    source = SOURCE.replace('(anchor rect)', '(anchor circle)').replace('(size .3 .3)', '(size ' + size + ')')
    with pytest.raises(ValueError, match='custom_polygon_anchor_unproved'):
        exact_custom_polygons(source, 0., 0., 270.)


from pathlib import Path
import pytest
from kicad_parser import parse_kicad_pcb

@pytest.mark.parametrize("size", ["100000000 100000000", "1" + "0" * 307 + " " + "1" + "0" * 307])
def test_actual_parser_refuses_extreme_circle_anchor(tmp_path, size):
    source = Path(__file__).with_name("jp1-exact-polygons.kicad_pcb").read_text()
    source = source.replace("(anchor rect)", "(anchor circle)")
    import re
    source, count = re.subn(r"\(size\s+0?\.3\s+0?\.3\)", "(size " + size + ")", source)
    assert count == 2
    path = tmp_path / "extreme.kicad_pcb"
    path.write_text(source)
    with pytest.raises(ValueError, match="custom_polygon_anchor_unproved"):
        parse_kicad_pcb(str(path))

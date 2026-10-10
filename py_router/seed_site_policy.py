"""Conventional seed sites; original fabrication permission is never synthesized."""
import hashlib
import math
from pathlib import Path

class SitePolicyRefusal(ValueError):
    pass

def captured_original(record):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256', 'custody_sha256'}:
        raise SitePolicyRefusal('original_fabrication_source_unproved')
    path, expected = record['path'], record['sha256']
    if not isinstance(path, str) or not isinstance(expected, str):
        raise SitePolicyRefusal('original_fabrication_source_unproved')
    custody = record['custody_sha256']
    if not isinstance(custody, str) or len(custody) != 64 or any(c not in '0123456789abcdef' for c in custody):
        raise SitePolicyRefusal('original_fabrication_custody_unproved')
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SitePolicyRefusal('original_fabrication_source_changed')
    from kicad_parser import extract_board_setup_paste_and_protection
    _, _, setup = extract_board_setup_paste_and_protection(raw.decode('utf-8'))
    # A positive process permission codec is intentionally unsupported here.
    # Even yes/yes cannot be credited without the complete original fab contract.
    return {'source': dict(record), 'setup': setup, 'authorization': 'unproved',
            'selection': 'conventional_only'}

def conventional_site_filter(pcb_data, via_size, layers):
    from check_drc import point_to_pad_distance
    from paste_apertures import pad_on_copper_side, via_paste_penetration
    if not hasattr(pcb_data, 'footprints') or not hasattr(pcb_data, 'paste_apertures'):
        raise SitePolicyRefusal('seed_fabrication_domain_unproved')
    if type(via_size) not in (int, float) or not math.isfinite(via_size) or via_size <= 0:
        raise SitePolicyRefusal('seed_fabrication_radius_unproved')
    if not isinstance(layers, (tuple, list)) or not layers or any(not isinstance(x, str) for x in layers):
        raise SitePolicyRefusal('seed_fabrication_layers_unproved')
    copper = getattr(getattr(pcb_data, 'board_info', None), 'copper_layers', None)
    if (not isinstance(copper, (list, tuple)) or not copper
            or len(set(layers)) != len(layers) or any(x not in copper for x in layers)
            or list(layers) != sorted(layers, key=copper.index)):
        raise SitePolicyRefusal('seed_fabrication_layers_unproved')
    sides = set(layers) & {'F.Cu', 'B.Cu'}
    pads = [p for fp in pcb_data.footprints.values() for p in fp.pads]
    relevant = [p for p in pads if any(pad_on_copper_side(p, s) for s in sides)]
    custom_anchors = []
    for pad in relevant:
        for field in ('global_x', 'global_y', 'size_x', 'size_y', 'rect_rotation'):
            value = getattr(pad, field, None)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SitePolicyRefusal('seed_fabrication_pad_geometry_unproved')
        if pad.size_x <= 0 or pad.size_y <= 0:
            raise SitePolicyRefusal('seed_fabrication_pad_geometry_unproved')
        if pad.shape == 'roundrect':
            ratio = getattr(pad, 'roundrect_rratio', None)
            if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= .5:
                raise SitePolicyRefusal('seed_fabrication_pad_geometry_unproved')
        if pad.shape == 'custom':
            from kicad_parser import exact_custom_polygons
            source = getattr(pad, 'exact_custom_source', None)
            anchor = getattr(pad, 'anchor_size', None)
            if (not isinstance(source, tuple) or len(source) != 2
                    or not isinstance(source[0], str)
                    or type(source[1]) not in (int, float)
                    or not math.isfinite(source[1])
                    or getattr(pad, 'geometry_approximations', ())
                    or not isinstance(anchor, (tuple, list)) or len(anchor) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           or v <= 0 for v in anchor)):
                raise SitePolicyRefusal('seed_fabrication_pad_shape_unproved')
            try:
                import re
                size = re.search(r'\(size\s+([^\s()]+)\s+([^\s()]+)\)', source[0])
                if (size is None or tuple(float(v) for v in size.groups()) != tuple(anchor)
                        or re.match(r'\(pad\s+(?:"[^"]*"|[^\s()]+)\s+smd\s+custom\b', source[0]) is None):
                    raise ValueError('custom_polygon_anchor_unproved')
                polygons = exact_custom_polygons(
                    source[0], pad.global_x, pad.global_y, source[1])
                if (polygons != pad.polygons or any(
                        not isinstance(ring, (tuple, list)) or len(ring) < 3
                        or any(not isinstance(point, (tuple, list)) or len(point) != 2
                               or any(type(v) not in (int, float) or not math.isfinite(v)
                                      for v in point) for point in ring)
                        for ring in polygons) or any(
                        len({tuple(point) for point in ring}) != len(ring)
                        for ring in polygons)):
                    raise ValueError('custom_polygon_geometry_unproved')
                from shapely.geometry import Polygon
                from shapely.errors import ShapelyError
                try:
                    for ring in polygons:
                        shape = Polygon(ring)
                        if not shape.is_valid or not math.isfinite(shape.area) or shape.area <= 0:
                            raise ValueError('custom_polygon_geometry_unproved')
                except ShapelyError as exc:
                    raise ValueError('custom_polygon_geometry_unproved') from exc
            except (ValueError, TypeError, OverflowError) as exc:
                raise SitePolicyRefusal('seed_fabrication_pad_shape_unproved') from exc
            # Circumscribed anchor disk conservatively covers either supported
            # anchor kind at every rotation; it cannot create a permissive site.
            custom_anchors.append((pad.global_x, pad.global_y,
                                   math.hypot(*anchor) / 2))
        elif getattr(pad, 'polygons', None):
            raise SitePolicyRefusal('seed_fabrication_pad_shape_unproved')
        elif pad.shape not in ('rect', 'circle', 'oval', 'roundrect'):
            raise SitePolicyRefusal('seed_fabrication_pad_shape_unproved')
    if any(a.layer not in ('F.Paste', 'B.Paste') for a in pcb_data.paste_apertures):
        raise SitePolicyRefusal('seed_fabrication_paste_layer_unproved')
    apertures = [a for a in pcb_data.paste_apertures
                 if ('F.Cu' if a.layer == 'F.Paste' else 'B.Cu') in sides]
    if any(a.layer not in ('F.Paste', 'B.Paste') or a.approximations for a in apertures):
        raise SitePolicyRefusal('seed_fabrication_paste_shape_unproved')
    for aperture in apertures:
        if aperture.shape_pad is not None:
            shape = aperture.shape_pad
            if shape.shape not in ('rect', 'circle', 'oval', 'roundrect'):
                raise SitePolicyRefusal('seed_fabrication_paste_shape_unproved')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (shape.size_x, shape.size_y)) or shape.size_x <= 0 or shape.size_y <= 0:
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            if shape.shape == 'roundrect':
                ratio = getattr(shape, 'roundrect_rratio', None)
                if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= .5:
                    raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            values = [shape.global_x, shape.global_y, shape.size_x, shape.size_y,
                      shape.rect_rotation]
        elif aperture.circle is not None:
            if not isinstance(aperture.circle, (tuple, list)) or len(aperture.circle) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in aperture.circle) or aperture.circle[2] <= 0:
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            values = list(aperture.circle)
        elif aperture.rings and aperture.closed:
            if not isinstance(aperture.rings, (list, tuple)) or any(not isinstance(ring, (list, tuple)) or len(ring) < 3 for ring in aperture.rings):
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            from shapely.geometry import Polygon
            if any(any(not isinstance(point, (tuple, list)) or len(point) != 2 for point in ring) for ring in aperture.rings):
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            if any(any(type(v) not in (int, float) or not math.isfinite(v) for point in ring for v in point) for ring in aperture.rings):
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            if any(not Polygon(ring).is_valid or Polygon(ring).area <= 0 for ring in aperture.rings):
                raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
            values = [coordinate for ring in aperture.rings for point in ring
                      for coordinate in point]
        else:
            raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
        if type(aperture.width) not in (int, float) or aperture.width < 0:
            raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
        values.append(aperture.width)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise SitePolicyRefusal('seed_fabrication_paste_geometry_unproved')
    def allowed(x, y):
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (x, y)):
            raise SitePolicyRefusal('seed_fabrication_site_geometry_unproved')
        # Existing fab_notes uses radius-1e-6 to distinguish contact from overlap.
        # Restrict to strictly separated sites instead: boundary contact is refused.
        if any(point_to_pad_distance(x, y, p) <= via_size / 2 + 1e-9 for p in relevant):
            return False
        if any(math.hypot(x - px, y - py) <= radius + via_size / 2 + 1e-9
               for px, py, radius in custom_anchors):
            return False
        return not any(via_paste_penetration(x, y, via_size, a) >= -1e-9
                       for a in apertures)
    return allowed

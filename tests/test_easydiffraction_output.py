"""re/20a (KI-04): what the easydiffraction runner hands to powderline.roundtrip — engine-free, on a fake Build."""
import pytest

from powderline.exceptions import StructuredWarning
from powderline.gateways.easydiffraction import native_run
from powderline.gateways.easydiffraction.native_builder import Build, FreeParameter

pytestmark = pytest.mark.core


class _P:
    def __init__(self, value, uncertainty=None):
        self.value, self.uncertainty = value, uncertainty


def _free(name, path, value, esd=None, offset=0.0, **kw):
    return FreeParameter(_P(value, esd), name, path, descriptive=name, category="c", report_offset=offset, **kw)


def test_output_inputs_paths_values_offsets_and_chebyshev_index():
    build = Build(project=None, experiment=None, structures={}, free=[
        _free("cell_a", "payload.phases.LaB6.unit_cell.a", 4.157, 1e-4),
        _free("x_B", "payload.phases.LaB6.atoms.B.x", 0.199, 2e-4, offset=1.0),   # held translated (A176)
        _free("background_coefficient_2", "payload.background.chebyshev", 1.5, 0.1),
        _free("scale", "payload.phases.LaB6.scale", 0.02, None),
    ])
    warnings = [StructuredWarning(code="easydiffraction_parameter_at_limit", message="m", field_path="payload.phases.LaB6.scale")]
    refined, not_varied, at_limit = native_run._output_inputs(build, warnings, fewer_varied=True)
    assert refined["payload.phases.LaB6.unit_cell.a"] == (4.157, 1e-4)
    assert refined["payload.phases.LaB6.atoms.B.x"] == (pytest.approx(1.199), 2e-4)
    assert refined["payload.background.chebyshev.coefficients.2"] == (1.5, 0.1)
    assert not_varied == {"payload.phases.LaB6.scale"} and at_limit == {"payload.phases.LaB6.scale"}
    _, not_varied_all, _ = native_run._output_inputs(build, warnings, fewer_varied=False)
    assert not_varied_all == set()

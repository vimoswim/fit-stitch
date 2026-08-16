"""TCX export structure and privacy checks."""

import xml.etree.ElementTree as ET

from fit_stitch.merge import merge_files
from fit_stitch.tcx import export_tcx

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
EXT_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"


def test_tcx_export(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    tcx = tmp_path / "merged.tcx"
    n = export_tcx(out, tcx)
    assert n == 120

    root = ET.parse(tcx).getroot()
    assert root.tag == f"{{{TCX_NS}}}TrainingCenterDatabase"
    activity = root.find(f"{{{TCX_NS}}}Activities/{{{TCX_NS}}}Activity")
    assert activity.get("Sport") == "Biking"

    points = activity.findall(f".//{{{TCX_NS}}}Trackpoint")
    assert len(points) == 120
    dists = [float(tp.find(f"{{{TCX_NS}}}DistanceMeters").text) for tp in points]
    assert dists[0] == 8.0
    assert dists[-1] == 960.0
    assert dists == sorted(dists)

    watts = points[0].find(f".//{{{EXT_NS}}}Watts")
    assert watts is not None and watts.text == "200"

    # Creator must reflect the (synthetic) source file_id, not any hardcoded device
    creator = activity.find(f"{{{TCX_NS}}}Creator")
    assert creator is not None
    assert creator.find(f"{{{TCX_NS}}}UnitId").text == "987654321"

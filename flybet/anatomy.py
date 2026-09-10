"""Verified cell-body coordinates for display, independent of neural dynamics."""

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

from .data import SOURCES
from .paths import sha256

POPULATIONS = [
    ("Other brain", "#b5c5bf"),
    ("Optic lobes", "#79bdd9"),
    ("Mushroom body", "#d2ff65"),
    ("Central complex", "#bc9cf0"),
    ("Antennal circuits", "#71d6ad"),
    ("Descending neurons", "#e6c483"),
    ("Ventral nerve cord", "#a2b6d5"),
    ("Dopamine neurons", "#ffa568"),
]
# One record per measured soma, in simulator-index order. All floats are micrometers.
POINT_DTYPE = np.dtype(
    [
        ("index", "<u4"),
        ("xyz", "<f4", (3,)),
        ("population", "u1"),
        ("group", "u1"),
        ("part", "u1"),
        ("padding", "u1"),
    ]
)


def populations(nodes):
    """Disjoint display families from release annotations, not neuropil volumes."""
    superclass = nodes.superclass.fillna("")
    cell_class = nodes["class"].fillna("")
    neuromere = nodes.somaNeuromere.fillna("")
    result = np.zeros(len(nodes), np.uint8)
    result[superclass.str.startswith("ol_")] = 1
    result[cell_class.isin(["Kenyon_Cell", "MBON"])] = 2
    result[cell_class.eq("CX")] = 3
    result[cell_class.isin(["ALPN", "ALLN", "ALIN", "ALON"])] = 4
    result[superclass.str.startswith("descending_neuron")] = 5
    result[
        superclass.str.startswith("vnc_")
        | superclass.isin(["ascending_neuron", "efferent_ascending"])
        | neuromere.str.fullmatch(r"T[123]|A\d+")
    ] = 6
    result[cell_class.eq("DAN")] = 7
    return result


def pack_points(nodes, groups):
    """Do not invent positions for unlocated neurons or use root/skeleton proxies."""
    indices, xyz = [], []
    for index, location in enumerate(nodes.somaLocation):
        if location is None or not isinstance(location, (list, tuple, np.ndarray)):
            continue
        position = np.asarray(location, dtype=np.float64)
        if position.shape != (3,) or not np.isfinite(position).all() or np.any(position <= 0):
            raise ValueError(f"Invalid released soma coordinate at neuron index {index}")
        indices.append(index)
        xyz.append(position * 0.008)  # Official MaleCNS 8 nm voxel coordinates → μm.
    points = np.zeros(len(indices), POINT_DTYPE)
    points["index"] = indices
    points["xyz"] = np.asarray(xyz).reshape(-1, 3)
    points["population"] = populations(nodes)[indices]
    points["group"] = np.asarray(groups)[indices]
    # A camera crop only, not a claim about a neuron's projection territory.
    points["part"] = points["xyz"][:, 2] >= 400  # z = 50,000 source voxels.
    return points


class Anatomy:
    def __init__(self, nodes, groups, ids_hash, annotations_hash):
        self.nodes = nodes
        self.points = pack_points(nodes, groups)
        self.binary = self.points.tobytes()
        self.population = populations(nodes)
        located = np.bincount(self.points["population"], minlength=len(POPULATIONS))
        total = np.bincount(self.population, minlength=len(POPULATIONS))
        bounds = {}
        for name, selected in [
            ("cns", np.ones(len(self.points), bool)),
            ("brain", self.points["part"] == 0),
            ("vnc", self.points["part"] == 1),
        ]:
            xyz = self.points["xyz"][selected]
            bounds[name] = (
                [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()] if len(xyz) else None
            )
        self.metadata = {
            "format": 1,
            "dataset": "MaleCNS v1.0",
            "total_neurons": len(nodes),
            "located_neurons": len(self.points),
            "unlocated_neurons": len(nodes) - len(self.points),
            "source": "somaLocation in official body annotations",
            "units": "micrometers",
            "source_voxel_nm": 8,
            "ids_sha256": ids_hash,
            "annotations_sha256": annotations_hash,
            "points_sha256": hashlib.sha256(self.binary).hexdigest(),
            "stride_bytes": POINT_DTYPE.itemsize,
            "bounds": bounds,
            "populations": [
                {"name": name, "color": color, "located": int(located[i]), "total": int(total[i])}
                for i, (name, color) in enumerate(POPULATIONS)
            ],
            "activity": {"tau_ms": 100, "display_max_hz": 200, "encoding": "uint8 / 255 * 200"},
            "note": "Cell-body locations and annotated cell families, not neuropil boundaries.",
        }

    def neuron(self, index):
        if not 0 <= index < len(self.nodes):
            raise IndexError("Neuron index outside retained graph")
        row = self.nodes.iloc[index]
        return {
            "index": index,
            "body_id": str(row.bodyId),
            "type": str(row.type) if isinstance(row.type, str) else "Unassigned type",
            "superclass": str(row.superclass),
            "population": POPULATIONS[self.population[index]][0],
            "soma_side": row.somaSide if isinstance(row.somaSide, str) else "Unassigned",
            "soma_um": (np.asarray(row.somaLocation) * 0.008).tolist()
            if isinstance(row.somaLocation, (list, tuple, np.ndarray))
            else None,
        }


@lru_cache(maxsize=4)
def load_anatomy(root):
    """Source and index hashes bind the static display to the simulated graph."""
    import json

    root = Path(root)
    lock = json.loads(Path(__file__).with_name("graph.lock.json").read_text())
    for name in ["ids", "group"]:
        if sha256(root / "compiled" / f"{name}.npy") != lock[name]:
            raise ValueError(f"Anatomy graph index checksum mismatch: {name}")
    annotations_hash = SOURCES["annotations.feather"]["sha256"]
    if sha256(root / "annotations.feather") != annotations_hash:
        raise ValueError("Anatomy annotation checksum mismatch")
    ids = np.load(root / "compiled/ids.npy", allow_pickle=False)
    groups = np.load(root / "compiled/group.npy", allow_pickle=False)
    annotations = feather.read_table(root / "annotations.feather").to_pandas()
    if not annotations.bodyId.is_unique:
        raise ValueError("Duplicate annotation IDs")
    nodes = annotations.set_index("bodyId").loc[ids].reset_index()
    return Anatomy(nodes, groups, lock["ids"], annotations_hash)

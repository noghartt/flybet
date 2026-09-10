"""Import the official MaleCNS release without pruning the retained neural graph."""

import json
import urllib.request
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc

from .paths import atomic_json, data_root, sha256

SOURCES = json.loads(Path(__file__).with_name("sources.lock.json").read_text())
EXPECTED = {"neurons": 166700, "edges": 25582938, "contacts": 124177617}
GROUP_NAMES = [
    "R1–R6",
    "R8",
    "Lamina",
    "Kenyon cells",
    "PAM11",
    "PPL101",
    "MBON07",
    "MBON11",
    "DNp20 L",
    "DNp20 R",
    "DNpe017",
    "Other",
]


def download(root=None):
    root = Path(root or data_root())
    root.mkdir(parents=True, exist_ok=True)
    for name, source in SOURCES.items():
        path = root / name
        if path.exists() and sha256(path) == source["sha256"]:
            print(f"Verified {name}", flush=True)
            continue
        tmp = path.with_suffix(".partial")
        print(f"Downloading {name} ({source['bytes'] / 1e6:.0f} MB)", flush=True)
        with urllib.request.urlopen(source["url"], timeout=120) as response, tmp.open("wb") as out:
            while chunk := response.read(8 * 1024 * 1024):
                out.write(chunk)
        if tmp.stat().st_size != source["bytes"] or sha256(tmp) != source["sha256"]:
            raise ValueError(f"Official source checksum mismatch: {name}")
        tmp.replace(path)


def retain_nodes(a, nt):
    keep = a.superclass.notna() & a.superclass.astype(str).ne("") & a.status.ne("Glia")
    nodes = a.loc[keep].sort_values("bodyId").copy().reset_index(drop=True)
    if nodes.bodyId.dtype.kind not in "iu" or not nodes.bodyId.is_unique:
        raise ValueError("Neuron IDs must be unique integers")
    nodes["nt"] = nodes.bodyId.map(nt.set_index("body").consensus_nt).fillna("")
    return nodes


def edge_indices(ids, pre, post, weight):
    if pre.dtype.kind not in "iu" or post.dtype.kind not in "iu":
        raise ValueError("Edge IDs must be integers")
    i, j = np.searchsorted(ids, pre), np.searchsorted(ids, post)
    keep = (i < len(ids)) & (j < len(ids))
    keep &= ids[np.minimum(i, len(ids) - 1)] == pre
    keep &= ids[np.minimum(j, len(ids) - 1)] == post
    if np.any(weight < 1) or np.any(weight != np.floor(weight)):
        raise ValueError("Invalid released contact count")
    return i[keep].astype(np.int32), j[keep].astype(np.int32), weight[keep].astype(np.uint32)


def signs(values):
    result, uncertain = [], 0
    for value in values:
        tokens = set(str(value).lower().split(","))
        fast = ({1} if "acetylcholine" in tokens else set()) | (
            {-1} if tokens & {"gaba", "glutamate", "histamine"} else set()
        )
        uncertain += len(fast) != 1
        result.append(next(iter(fast)) if len(fast) == 1 else 1)
    return np.asarray(result, np.float32), uncertain


def visual_projection(nodes, pre, post, contacts):
    """Modal anatomical column, then an explicit overlapping display projection."""
    types = nodes.type.fillna("").to_numpy()
    is_r16 = types == "R1-R6"
    is_r8 = np.isin(types, ["R8p", "R8y"])
    has_column = nodes.assignedOlHex1.notna().to_numpy() & nodes.assignedOlHex2.notna().to_numpy()
    anchors = np.isin(types, ["L1", "L2", "L3"]) & has_column
    selected = (is_r16[pre] & anchors[post]) | (is_r8[pre] & has_column[post])
    hex1 = nodes.assignedOlHex1.to_numpy()
    hex2 = nodes.assignedOlHex2.to_numpy()
    votes = {}
    for i, j, count in zip(pre[selected], post[selected], contacts[selected], strict=True):
        h = (float(hex1[j]), float(hex2[j]))
        v = votes.setdefault(int(i), {})
        v[h] = v.get(h, 0) + int(count)
    retina = np.array(sorted(votes), np.int32)
    hexes = np.array([max(votes[i], key=votes[i].get) for i in retina])
    confidence = np.array([max(votes[i].values()) / sum(votes[i].values()) for i in retina])
    xy = np.c_[hexes[:, 0] - 0.5 * hexes[:, 1], np.sqrt(3) / 2 * hexes[:, 1]]
    sides = nodes.rootSide.to_numpy()[retina]
    if not np.isin(sides, ["L", "R"]).all():
        raise ValueError("Unresolved eye side")
    uv = np.empty_like(xy)
    for side in ["L", "R"]:
        select = sides == side
        reference = xy[select & is_r16[retina]]
        z = (xy[select] - reference.min(axis=0)) / np.ptp(reference, axis=0)
        uv[select, 0] = 0.6 * z[:, 0] if side == "L" else 0.4 + 0.6 * (1 - z[:, 0])
        uv[select, 1] = 1 - z[:, 1]
    channels = np.where(types[retina] == "R8p", 2, np.where(types[retina] == "R8y", 1, 0))
    return retina, np.clip(uv, 0, 1).astype(np.float32), channels.astype(np.int32), confidence


def prepare(root=None):
    root = Path(root or data_root())
    download(root)
    print("Importing all retained neurons and connections…", flush=True)
    nodes = retain_nodes(
        feather.read_table(root / "annotations.feather").to_pandas(),
        feather.read_table(root / "neurotransmitters.feather").to_pandas(),
    )
    ids = nodes.bodyId.to_numpy(dtype=np.int64)
    columns = [[], [], []]
    source_edges = source_contacts = 0
    reader = ipc.open_file(pa.memory_map(str(root / "edges.feather"), "r"))
    for number in range(reader.num_record_batches):
        batch = reader.get_batch(number)
        values = [
            batch.column(batch.schema.get_field_index(k)).to_numpy()
            for k in ["body_pre", "body_post", "weight"]
        ]
        source_edges += len(values[0])
        source_contacts += int(values[2].sum(dtype=np.uint64))
        for output, chunk in zip(columns, edge_indices(ids, *values), strict=True):
            output.append(chunk)
    pre, post, contacts = [np.concatenate(parts) for parts in columns]
    del columns
    counts = {
        "neurons": len(ids),
        "edges": len(pre),
        "contacts": int(contacts.sum(dtype=np.uint64)),
    }
    if counts != EXPECTED:
        raise ValueError(f"Unexpected retained MaleCNS graph: {counts}")
    order = np.argsort(pre, kind="stable")
    pre, post, contacts = pre[order], post[order], contacts[order]
    del order
    ptr = np.r_[0, np.cumsum(np.bincount(pre, minlength=len(ids)))].astype(np.int64)
    polarity, uncertain = signs(nodes.nt)
    weight = (contacts * polarity[pre] * 0.275).astype(np.float32)
    types = nodes.type.fillna("").to_numpy(dtype="U64")
    side = nodes.somaSide.fillna("").to_numpy(dtype="U8")
    # Documented target-specific net excitation assumption, topology unchanged.
    corrected = np.isin(types[pre], ["R8p", "R8y"]) & (types[post] == "aMe12")
    weight[corrected] = np.abs(weight[corrected])
    retina, uv, channels, confidence = visual_projection(nodes, pre, post, contacts)
    kc = np.array([t.startswith("KC") for t in types], np.uint8)
    mod_kind = np.where(nodes.nt.isin(["dopamine", "serotonin", "octopamine"]), 3, 0).astype(
        np.uint8
    )
    mod_kind[types == "PAM11"] = 1
    mod_kind[types == "PPL101"] = 2
    group = np.full(len(ids), 11, np.int32)
    masks = [
        types == "R1-R6",
        np.isin(types, ["R8p", "R8y"]),
        np.isin(types, ["L1", "L2", "L3", "L5"]),
        kc.astype(bool),
        types == "PAM11",
        types == "PPL101",
        types == "MBON07",
        types == "MBON11",
        (types == "DNp20") & (side == "L"),
        (types == "DNp20") & (side == "R"),
        types == "DNpe017",
    ]
    for g, mask in enumerate(masks):
        group[mask] = g
    anatomy = (
        np.bincount(group[pre] * 12 + group[post], weights=contacts, minlength=144)
        .reshape(12, 12)
        .astype(np.int64)
    )
    plastic = np.flatnonzero(kc[pre] & np.isin(types[post], ["MBON07", "MBON11"])).astype(np.int64)
    arrays = dict(
        ids=ids,
        ptr=ptr,
        post=post,
        weight=weight,
        types=types,
        side=side,
        retina=retina,
        uv=uv,
        channels=channels,
        kc=kc,
        mod_kind=mod_kind,
        group=group,
        anatomy=anatomy,
        plastic=plastic,
        plastic_pre=pre[plastic],
    )
    target = root / "compiled"
    target.mkdir(exist_ok=True)
    hashes = {}
    for key, value in arrays.items():
        path = target / f"{key}.npy"
        with path.with_suffix(".partial").open("wb") as f:
            np.save(f, value, allow_pickle=False)
        path.with_suffix(".partial").replace(path)
        hashes[key] = sha256(path)
    manifest = {
        "format": 1,
        "dataset": "MaleCNS v1.0",
        **counts,
        "source_edges": source_edges,
        "source_contacts": source_contacts,
        "excluded_edges": source_edges - len(pre),
        "self_edges": int((pre == post).sum()),
        "weak_edges": int((contacts == 1).sum()),
        "uncertain_signs": uncertain,
        "retina_brightness": int((channels == 0).sum()),
        "retina_color": int((channels != 0).sum()),
        "retina_confidence_median": float(np.median(confidence)),
        "plastic_edges": len(plastic),
        "r8_sign_corrections": int(corrected.sum()),
        "sources": SOURCES,
        "arrays": hashes,
        "groups": GROUP_NAMES,
        "group_sizes": np.bincount(group, minlength=12).tolist(),
    }
    atomic_json(target / "manifest.json", manifest)
    print(
        json.dumps({k: v for k, v in manifest.items() if k not in ["sources", "arrays"]}),
        flush=True,
    )
    return manifest


def verify(root=None):
    root = Path(root or data_root()) / "compiled"
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("format") != 1 or any(manifest[k] != v for k, v in EXPECTED.items()):
        raise ValueError("Unsupported or incomplete MaleCNS graph")
    if manifest["sources"] != SOURCES:
        raise ValueError("Dataset provenance mismatch")
    expected_arrays = json.loads(Path(__file__).with_name("graph.lock.json").read_text())
    if manifest["arrays"] != expected_arrays:
        raise ValueError("Compiled graph differs from the committed graph lock")
    for name, digest in manifest["arrays"].items():
        if sha256(root / f"{name}.npy") != digest:
            raise ValueError(f"Compiled array checksum mismatch: {name}")
    return manifest

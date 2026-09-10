import numpy as np
import pandas as pd
import pytest

from flybet.data import edge_indices, retain_nodes, signs


def test_retention_keeps_uncertain_classes_and_exact_large_ids():
    a = pd.DataFrame(
        {
            "bodyId": np.array([2**53 + 1, 9, 10, 11], np.int64),
            "superclass": ["tbc", "central", None, "glial"],
            "status": ["", "", "", "Glia"],
        }
    )
    nt = pd.DataFrame({"body": a.bodyId, "consensus_nt": ["acetylcholine"] * 4})
    nodes = retain_nodes(a, nt)
    assert nodes.bodyId.tolist() == [9, 2**53 + 1]


def test_edges_keep_weak_and_self_connections_and_exclude_other_objects():
    ids = np.array([9, 2**53 + 1], np.int64)
    pre = np.array([9, 9, 2**53 + 1, 10], np.int64)
    post = np.array([9, 2**53 + 1, 9, 9], np.int64)
    i, j, count = edge_indices(ids, pre, post, np.array([1, 7, 3, 5]))
    assert i.tolist() == [0, 0, 1] and j.tolist() == [0, 1, 0]
    assert count.tolist() == [1, 7, 3]
    with pytest.raises(ValueError):
        edge_indices(ids, pre.astype(float), post, np.ones(4))


def test_transmitter_proxy_and_uncertainty():
    polarity, uncertain = signs(
        ["acetylcholine", "gaba", "glutamate", "histamine", "", "dopamine", "gaba,acetylcholine"]
    )
    assert polarity.tolist() == [1, -1, -1, -1, 1, 1, 1]
    assert uncertain == 3

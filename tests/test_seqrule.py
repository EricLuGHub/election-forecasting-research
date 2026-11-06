"""Item-85 sequential-rule tests (synthetic only, no network)."""
from research.seqrule import clustered_ci, decide_maker, decide_structural


def test_dependence_deflates():
    # 500 fills, all from 2 races, all +1: naive says certain, clustered
    # says keep-testing (only 2 clusters).
    vals = [1.0] * 500
    clus = ['a'] * 250 + ['b'] * 250
    d, det = decide_maker(vals, clus)
    assert d == 'keep-testing' and 'only 2 clusters' in det['reason']


def test_enough_clusters_promotes():
    vals, clus = [], []
    for i in range(10):
        vals += [1.0] * 50
        clus += ['r%d' % i] * 50
    d, det = decide_maker(vals, clus)
    assert d == 'promote' and det['ci']['lo'] > 0


def test_single_cluster_refuses():
    assert clustered_ci([1.0] * 500, ['a'] * 500) is None
    assert decide_maker([1.0], ['a'])[0] == 'keep-testing'


def test_structural_counts_and_resets():
    assert decide_structural(2, [])[0] == 'keep-testing'
    assert decide_structural(3, [])[0] == 'promote'
    d, det = decide_structural(5, ['orphan'])
    assert d == 'stop' and 'reset' in det['reason']

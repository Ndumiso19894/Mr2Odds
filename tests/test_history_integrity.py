import pandas as pd
import history_integrity as integrity


def event(eid='42', div='LS:japan/j-league', **changes):
    row=dict(eid=eid,country='Japan',league='J1 League',div=div,date=pd.Timestamp('2026-10-01'),
             home='A',away='B',home_id='1',away_id='2',hg=2,ag=1,hc=4,ac=5,hst=3)
    row.update(changes)
    return row


def test_same_id_dedup_preserves_provenance_and_fills_agreeing_values():
    original=pd.DataFrame([event(div='LS:japan/j-league-2025',hc=None), event()])
    copy=original.copy(deep=True)
    out, report=integrity.reconcile_livescore_ids(original)
    pd.testing.assert_frame_equal(original,copy)
    assert len(out)==1 and out.iloc[0].hc==4
    assert out.iloc[0]['div']=='LS:japan/j-league'
    assert set(out.iloc[0]._history_sources)==set(original['div'])
    assert report['rows_removed']==1 and report['duplicate_groups']==1


def test_stat_conflicts_become_missing_and_score_conflicts_quarantined():
    df=pd.DataFrame([event(),event(div='LS:japan/j-league-2025',hc=9),
                     event(eid='bad'),event(eid='bad',hg=3)])
    out, report=integrity.reconcile_livescore_ids(df)
    assert len(out)==1 and pd.isna(out.iloc[0].hc)
    assert out.iloc[0]._history_conflicts==('hc',)
    assert report['stat_conflicts']==1 and report['quarantined_groups']==1
    assert report['rows_removed']==3


def test_cross_provider_rows_and_idless_matches_are_not_guessed():
    df=pd.DataFrame([event(),event(div='E0',eid=None), event(eid=None)])
    out, report=integrity.reconcile_livescore_ids(df)
    assert len(out)==3 and report['unmerged_cross_provider']

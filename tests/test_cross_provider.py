"""Review-gated identity and unique-event model-view regression tests."""
from datetime import datetime
import json
import pandas as pd
import pytest
import cross_provider as cp
import scanner, markets, quality, trends

NOW=datetime(2026,11,4,12)


def pair(**ls_changes):
    base=dict(country='England',league='Premier League',date=pd.Timestamp('2026-10-01'),
              home='A',away='B',hg=2,ag=1,hc=5,ac=3,hst=4,ast=2,
              hxg=float('nan'),axg=float('nan'),hs=10,**{'as':7},
              hy=1,ay=2,hr=0,ar=0,hth=1,hta=0,referee='Ref')
    fd=dict(base,div='E0',eid=None,home_id=None,away_id=None,_source_ref='fd/file')
    ls=dict(base,div='LS:eng/epl',eid='42',home_id='1',away_id='2',_source_ref='ls/stage')
    ls.update(ls_changes)
    return pd.DataFrame([fd,ls])


def approve(df):
    item=next(cp.candidates(df))[0]
    assert item['status']=='needs_review'
    return {item['candidate_id']:{'reviewed_by':'reviewer','rationale':'independent identity review','evidence':'reference event records'}}


def test_no_unreviewed_merge_even_if_exact():
    df=pair()
    out, audit, detail=cp.reconcile(df,{},True)
    pd.testing.assert_frame_equal(out,df)
    assert audit['needs_review']==1 and audit['rows_removed']==0
    assert detail[0]['kickoff_comparison']=='unavailable'


def test_reviewed_merge_masks_conflicts_preserves_identity_and_provenance():
    df=pair(hc=6,hst=None,asoff=7)
    before=df.copy(deep=True); permissions=approve(df)
    out, audit, detail=cp.reconcile(df,permissions,True)
    pd.testing.assert_frame_equal(df,before)
    assert len(out)==1 and audit['rows_removed']==1
    row=out.iloc[0]
    assert row['div']=='E0' and row['eid']=='42' and row['home_id']=='1'
    assert set(row['_history_divs'])=={'E0','LS:eng/epl'}
    assert pd.isna(row['hc']) and row['hst']==4 and row['asoff']==7
    assert row['_history_conflicts']==('hc',)
    assert row['_history_records'][0]['hc']==5 and row['_history_records'][1]['hc']==6
    assert row['_history_review']['reviewed_by']=='reviewer'
    assert detail[0]['status']=='merged_reviewed'


def test_unique_global_and_team_samples_and_both_competition_priors():
    df=pair(); out,_,_=cp.reconcile(df,approve(df))
    views=cp.division_view(out)
    assert len(out)==1 and set(views['div'])=={'E0','LS:eng/epl'}
    avgs=scanner.compute_div_avgs(out,NOW)
    assert avgs['__global__'].n_eff==pytest.approx(avgs['E0'].n_eff)
    assert avgs['E0'].n_eff==pytest.approx(avgs['LS:eng/epl'].n_eff)
    assert avgs['E0'].mu_h==pytest.approx(avgs['LS:eng/epl'].mu_h)
    long=scanner.make_long(out,avgs)
    scanner.TEAM_HIST_CACHE.clear();scanner.H2H_CACHE.clear();scanner.build_long_index(long);scanner.build_h2h_index(out)
    assert len(scanner.team_history(long,'England','A'))==1
    assert len(scanner.team_history(long,'England','A','1'))==1
    assert len(scanner.head_to_head(out,'England','A','B',home_id='1',away_id='2'))==1
    trends.clear_caches(); assert len(trends.team_rows(trends._long(out),'England','A','1'))==1
    p=scanner.build_profile(long,'England','A','H',NOW,'1')
    assert quality.team_evidence(p,'LS:eng/epl',NOW)['composition']['own_competition_share']==1
    cm=markets.CountModel(out,'hc','ac',NOW,markets.CORNERS)
    assert len(cm.team[('England','A')])==1
    assert cm.div_avg['E0']==pytest.approx(cm.div_avg['LS:eng/epl'])


@pytest.mark.parametrize('changes,reason',[
    ({'hg':3},'score_conflict_or_missing'),
    ({'league':'League Cup'},'competition_alias_unverified'),
    ({'home':'a'},'identity_alias_unverified'),
    ({'home_id':None},'missing_livescore_ids'),
])
def test_conflicts_block_review_and_never_merge(changes,reason):
    df=pair(**changes); entry=next(cp.candidates(df))[0]
    assert entry['status']=='blocked' and reason in entry['reasons']
    out, report, _=cp.reconcile(df,{entry['candidate_id']:{'reviewed_by':'x','rationale':'x'}})
    assert len(out)==2 and report['unmatched_or_ineligible_approvals']==1


def test_ambiguous_pairs_and_kickoff_conflicts_never_merge():
    df=pair(_history_kickoff='12:00',_history_kickoff_tz='UTC');df.loc[0,'_history_kickoff']='13:00';df.loc[0,'_history_kickoff_tz']='UTC'
    entry=next(cp.candidates(df))[0]
    assert 'kickoff_conflict' in entry['reasons']
    many=pd.concat([pair(),pair().iloc[[0]]],ignore_index=True)
    entry=next(cp.candidates(many))[0]
    assert entry['status']=='ambiguous_multiplicity'
    out, report,_=cp.reconcile(many,{'irrelevant':{}},True)
    assert len(out)==3 and report['ambiguous_multiplicity']==1


def test_approval_tied_to_identity_and_fail_closed_file(tmp_path):
    df=pair(); approved=approve(df)
    changed=pair(hg=3)
    out,report,_=cp.reconcile(changed,approved)
    assert len(out)==2 and report['unmatched_or_ineligible_approvals']==1
    path=tmp_path/'approvals.json';path.write_text('{broken')
    with pytest.raises(ValueError):cp.load_approvals(path)
    key=next(iter(approved))
    path.write_text(json.dumps({'version':1,'approvals':[{'candidate_id':key,'reviewed_by':'','rationale':'x'}]}))
    with pytest.raises(ValueError):cp.load_approvals(path)
    path.write_text(json.dumps({'version':1,'approvals':[{'candidate_id':key,'reviewed_by':'human','rationale':'reviewed','evidence':'event record URL or reference'}]}))
    assert key in cp.load_approvals(path)


def test_card_conflict_is_missing_in_every_view_not_zero():
    import teamstats
    df=pair(hy=4)
    out,_,_=cp.reconcile(df,approve(df))
    assert pd.isna(out.iloc[0]['hy'])
    long=scanner.make_long(out,scanner.compute_div_avgs(out,NOW))
    assert pd.isna(long[long.team=='A'].iloc[0]['k_for'])
    assert pd.isna(trends._long(out).query("team == 'A'").iloc[0]['kf'])
    assert pd.isna(teamstats._long(out).query("team == 'A'").iloc[0]['kf'])


def test_timezones_are_required_before_comparing_kickoff():
    df=pair(_history_kickoff='14:00');df.loc[0,'_history_kickoff']='12:00'
    entry=next(cp.candidates(df))[0]
    assert entry['status']=='needs_review' and entry['kickoff_comparison']=='unverified_timezone'
    df.loc[0,'_history_kickoff_tz']='UTC';df.loc[1,'_history_kickoff_tz']='Africa/Johannesburg'
    entry=next(cp.candidates(df))[0]
    assert entry['kickoff_comparison']=='matched' and entry['status']=='needs_review'
    df.loc[1,'_history_kickoff_tz']='Not/AZone'
    entry=next(cp.candidates(df))[0]
    assert entry['status']=='blocked' and 'kickoff_timezone_invalid' in entry['reasons']


def test_conflict_from_duplicate_livescore_stages_stays_missing_after_review():
    df=pair(hst=None,_history_conflicts=('hst',))
    out,_,_=cp.reconcile(df,approve(df))
    assert pd.isna(out.iloc[0]['hst']) and out.iloc[0]['_history_conflicts']==('hst',)


def test_conflict_metadata_is_exposed_and_partial_statistics_stay_na():
    df=pair(hc=6,ay=4)
    out,_,_=cp.reconcile(df,approve(df))
    scanner.TEAM_HIST_CACHE.clear();scanner.build_long_index(scanner.make_long(out,scanner.compute_div_avgs(out,NOW)))
    lg=scanner.make_long(out,scanner.compute_div_avgs(out,NOW))
    scanner.TEAM_HIST_CACHE.clear();scanner.build_long_index(lg)
    p=scanner.build_profile(lg,'England','A','H',NOW,'1')
    match=p.matches[0]
    assert set(match['history_sources'])=={'fd/file','ls/stage'}
    assert set(match['history_conflicts'])=={'hc','ay'}
    split=quality.split_stats(p.matches)
    assert split['corners_n']==0 and split['corners_for'] is None and split['corners_against'] is None
    assert split['cards_n']==0


def test_reviewed_event_appears_in_both_division_pages_without_double_team_history(tmp_path):
    import teamstats
    out,_,_=cp.reconcile(pair(),approve(pair()))
    slugs=teamstats.export(out,NOW,tmp_path)
    assert set(slugs)=={'E0','LS_eng_epl'}
    main=json.loads((tmp_path/'E0.json').read_text()); world=json.loads((tmp_path/'LS_eng_epl.json').read_text())
    assert main['teams']['A']['all']['p']==1
    assert world['teams']['A']['all']['p']==1
    assert len(main['teams']['A']['last'])==1 and len(world['teams']['A']['last'])==1


def test_candidate_id_is_order_independent_and_stat_changes_rechecked():
    df=pair(); rev=df.iloc[::-1].reset_index(drop=True)
    assert next(cp.candidates(df))[0]['candidate_id']==next(cp.candidates(rev))[0]['candidate_id']
    approved=approve(df)
    revised=pair(hst=9)
    out,summary,details=cp.reconcile(revised,approved,True)
    assert summary['merged']==1 and pd.isna(out.iloc[0]['hst'])
    assert details[0]['stat_conflicts']['hst']=={'football_data':4,'livescore':9}

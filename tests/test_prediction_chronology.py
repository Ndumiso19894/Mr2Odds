"""All prediction inputs share one conservative as-of history; settlement is separate."""
from datetime import datetime
import pandas as pd
import pytest
import scanner, markets, model_signals, trends


def _row(date, home, away, hg, ag, hc, ac, eid):
    d = dict(country='England',div='E0',league='Premier League',date=pd.Timestamp(date),
             home=home,away=away,home_id=None,away_id=None,hg=hg,ag=ag,referee='',eid=eid)
    d.update({key:float('nan') for key in scanner.NUM_RESULT_COLS if key not in d})
    d.update(hc=hc,ac=ac,hst=4,ast=3)
    return d


def test_asof_filters_future_and_whole_same_day_for_all_inputs():
    now=datetime(2026,11,4,12)
    base=pd.DataFrame([_row(f'2026-10-{i:02}', 'A', 'B', i % 3, 1, 5, 4, str(i)) for i in range(1,21)])
    contaminated=pd.concat([base,pd.DataFrame([_row('2026-11-04','A','B',50,50,80,70,'same'),
                                               _row('2027-03-06','A','B',99,99,90,90,'future')])],ignore_index=True)
    clean=scanner.prediction_history_as_of(base,now)
    cut=scanner.prediction_history_as_of(contaminated,now)
    pd.testing.assert_frame_equal(clean.reset_index(drop=True),cut.reset_index(drop=True),check_dtype=False)
    for source in (clean,cut):
        scanner.TEAM_HIST_CACHE.clear();scanner.PROFILE_CACHE.clear();scanner.H2H_CACHE.clear();trends.clear_caches()
        avgs=scanner.compute_div_avgs(source,now); long=scanner.make_long(source,avgs)
        scanner.build_long_index(long); scanner.build_h2h_index(source)
        h2h=scanner.head_to_head(source,'England','A','B')
        assert all(x['date']<pd.Timestamp(now.date()) for x in h2h)
        assert all(d < pd.Timestamp(now.date()) for d in trends.team_rows(trends._long(source),'England','A').date)
        assert len(source)==20
    # Historical evidence cannot alter goal, SOT or count baselines after the shared cutoff.
    assert scanner.compute_div_avgs(clean,now)['E0'].mu_h==pytest.approx(scanner.compute_div_avgs(cut,now)['E0'].mu_h)
    assert model_signals.sot_baselines(clean)==model_signals.sot_baselines(cut)
    c1=markets.CountModel(clean,'hc','ac',now,markets.CORNERS).expect('England','A','B','E0')
    c2=markets.CountModel(cut,'hc','ac',now,markets.CORNERS).expect('England','A','B','E0')
    assert c1.total==pytest.approx(c2.total)


def test_date_only_cutoff_is_stable_for_scan_overrides():
    d=pd.DataFrame([_row('2026-11-03','A','B',1,0,1,2,'a'),_row('2026-11-04','A','B',2,0,1,2,'b')])
    assert scanner.prediction_history_as_of(d,datetime(2026,11,4,0)).eid.tolist()==['a']
    assert scanner.prediction_history_as_of(d,datetime(2026,11,4,23,59)).eid.tolist()==['a']
    assert scanner.prediction_history_as_of(d,datetime(2026,11,5)).eid.tolist()==['a','b']


def test_scan_override_reference_quotes_are_not_relabelled_historical():
    fx=pd.DataFrame([dict(odds_h=1.2,odds_over=1.9,b365_under=2.1,bfe_h=1.3,max_over=2.2,home='A')])
    masked=scanner.without_unverified_replay_prices(fx)
    assert masked.home.iloc[0]=='A'
    assert masked.drop(columns='home').isna().all().all()
    assert fx.odds_h.iloc[0]==1.2  # source remains intact


def test_same_day_scores_remain_usable_for_settlement():
    now=datetime(2026,11,4,12)
    raw=pd.DataFrame([_row('2026-11-04','A','B',2,0,5,4,'finished')])
    assert scanner.prediction_history_as_of(raw,now).empty
    ticket={c:'' for c in scanner.TRACKER_COLS}
    ticket.update(match_date='2026-11-04',country='England',home='A',away='B',market='O15',status='pending')
    settled=scanner.settle_tracker(pd.DataFrame([ticket]),raw,now)
    assert settled.iloc[0]['status']=='hit' and settled.iloc[0]['score']=='2-0'

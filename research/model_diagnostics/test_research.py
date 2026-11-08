"""Historical characterization and corrected prediction-input checks; no network."""
from datetime import datetime
import math
import pandas as pd
import numpy as np
import json
import scanner, trends, worldfeed, history_integrity


def test_score_matrix_probability_invariants():
    for home,away in [(.15,.15),(1.4,1.1),(4.5,4.5)]:
        mat=scanner.score_matrix(home,away,scanner.CONFIG['DC_RHO'])
        assert np.isfinite(mat).all() and np.min(mat)>=0
        assert abs(mat.sum()-1)<1e-12
        p=scanner.probs_from_matrix(mat)
        assert p['O15']>=p['O25']>=p['O35']>=p['O45']>=p['O55']


def test_unfiltered_head_to_head_requires_shared_prediction_cutoff():
    rows=pd.DataFrame([{'date':pd.Timestamp('2027-03-06'),'country':'France','home':'A','away':'B','home_id':'1','away_id':'2','hg':2,'ag':2,'league':'test'},
                       {'date':pd.Timestamp('2026-10-01'),'country':'France','home':'A','away':'B','home_id':'1','away_id':'2','hg':1,'ag':0,'league':'test'}])
    scanner.H2H_CACHE.clear();scanner.build_h2h_index(rows)
    out=scanner.head_to_head(rows,'France','A','B',home_id='1',away_id='2')
    assert out[0]['date']>pd.Timestamp('2026-11-04')  # direct raw lookup is unsafe
    safe=scanner.prediction_history_as_of(rows,datetime(2026,11,4))
    scanner.H2H_CACHE.clear();scanner.build_h2h_index(safe)
    assert scanner.head_to_head(safe,'France','A','B',home_id='1',away_id='2')[0]['date']<pd.Timestamp('2026-11-04')


def test_unfiltered_trends_require_shared_prediction_cutoff():
    rows=pd.DataFrame([{'date':pd.Timestamp('2027-03-06'),'country':'France','home':'A','away':'B','home_id':'1','away_id':'2','hg':2,'ag':2,'league':'test'},
                       {'date':pd.Timestamp('2026-10-01'),'country':'France','home':'A','away':'B','home_id':'1','away_id':'2','hg':1,'ag':0,'league':'test'}])
    trends.clear_caches(); long=trends._long(rows)
    assert trends.team_rows(long,'France','A','1').iloc[0]['date']>pd.Timestamp('2026-11-04')
    safe=scanner.prediction_history_as_of(rows,datetime(2026,11,4))
    trends.clear_caches(); long=trends._long(safe)
    assert trends.team_rows(long,'France','A','1').iloc[0]['date']<pd.Timestamp('2026-11-04')


def test_same_event_in_two_stages_preserved_raw_but_deduplicated_for_predictions(tmp_path):
    archive=worldfeed.Archive(tmp_path)
    event=['202610011200','1','A','2','B',2,1,1,0]
    for name,key in [('a','country/season-a'),('b','country/season-b')]:
        (archive.stages_dir/f'{name}.json').write_text(json.dumps({'key':key,'country':'C','league':'L','events':{'42':event}}))
    df=archive.results_frame(datetime(2026,1,1))
    assert len(df)==2 and df['eid'].tolist()==['42','42']
    scanner.TEAM_HIST_CACHE.clear(); scanner.build_long_index(scanner.make_long(df,scanner.compute_div_avgs(df,datetime(2026,11,4))))
    assert df['hg'].sum()==4  # raw archive unchanged
    clean, info=history_integrity.reconcile_livescore_ids(df)
    assert len(clean)==1 and info['rows_removed']==1 and clean['hg'].sum()==2

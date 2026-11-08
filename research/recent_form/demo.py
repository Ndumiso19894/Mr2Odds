"""A reproducible invented-data demonstration; no provider or production files."""
import json
from datetime import datetime, timedelta
import pandas as pd
from .model import prepare, predict


def main():
    cutoff=datetime(2026,10,10,12)
    fixture={'country':'Demo','div':'LS:demo/league','home':'Alpha','away':'Beta','home_id':'a','away_id':'b'}
    records=[]
    def add(days,home,away,hid,aid,hg,ag,eid):
        records.append({'date':pd.Timestamp(cutoff-timedelta(days=days)),'country':'Demo',
                        'league':'Example League','div':fixture['div'], 'home':home,'away':away,
                        'home_id':hid,'away_id':aid,'hg':hg,'ag':ag,'eid':eid})
    for i in range(10):
        if i % 2 == 0:
            add(2*i+1,'Alpha',f'Other A{i}','a',f'x{i}',2 if i<5 else 1,0,f'a{i}')
            add(2*i+2,f'Other B{i}','Beta',f'y{i}','b',1,1,f'b{i}')
        else:
            add(2*i+1,f'Other A{i}','Alpha',f'x{i}','a',1,1,f'a{i}')
            add(2*i+2,'Beta',f'Other B{i}','b',f'y{i}',0,1,f'b{i}')
    for i in range(3):add(60+i*50,'Alpha','Beta','a','b',2,1,f'head{i}')
    output=predict(prepare(pd.DataFrame(records),cutoff),fixture)
    print(json.dumps({'classification':output['classification'],'league':output['league'],
                      'baseline_probabilities':output['baseline']['probabilities'],
                      'variant_probabilities':output['recent_variant']['probabilities'],
                      'evidence':output['evidence']},indent=2,allow_nan=False))


if __name__=='__main__':main()

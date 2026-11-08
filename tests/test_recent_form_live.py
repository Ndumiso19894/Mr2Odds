from datetime import timedelta
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

import markets
import quality
import recent_form
import scanner
from research.recent_form import model
from test_recent_form_research import sample, record, FX, NOW


def fixture():
    return pd.Series(dict(FX, source='world', odds_over=np.nan, odds_under=np.nan,
                          odds_h=np.nan, odds_d=np.nan, odds_a=np.nan))


def analyse(ctx, monkeypatch):
    model._activate(ctx)
    scanner.RECENT_TEAM_CACHE.clear()
    scanner.build_h2h_index(ctx.history)
    monkeypatch.setattr(scanner, 'RECENT_FORM_ENABLED', True)
    monkeypatch.setattr(scanner, 'EXPERIMENTAL_MODEL_SIGNALS', False)
    monkeypatch.setattr(scanner, 'MODELS', {})
    return scanner.analyse(fixture(), ctx.long, ctx.results, ctx.averages, ctx.cutoff, ctx.history)


def test_production_research_parity_score_matrix_and_evidence(monkeypatch):
    ctx = model.prepare(sample(), NOW)
    research = model.predict(ctx, FX)
    row = analyse(ctx, monkeypatch)
    assert row.recent_form['status'] == 'applied'
    assert row.lam_h == pytest.approx(research['recent_variant']['lambda_home'])
    assert row.lam_a == pytest.approx(research['recent_variant']['lambda_away'])
    assert row.recent_form['home'] == research['evidence']['home']
    assert row.recent_form['away'] == research['evidence']['away']
    assert row.recent_form['h2h']['matches'] == research['evidence']['h2h']['matches']
    matrix = np.array(research['recent_variant']['matrix'])
    assert row.p_model == pytest.approx(scanner.probs_from_matrix(matrix))
    assert row.extra.x12 == pytest.approx(markets.one_x_two(matrix))
    assert row.extra.tg == pytest.approx(markets.team_goals(matrix))
    assert all(p == pytest.approx(matrix[h,a]) for h,a,p in row.scores)
    assert row.recent_form['squad_availability'] == 'not_used'


def test_fallback_ambiguous_history_and_rollback_are_baseline(monkeypatch):
    data = sample()
    data.loc[len(data)] = record(NOW-timedelta(days=1), 'Alpha','Other','a','other',2,2,'ambiguous')
    ctx = model.prepare(data, NOW)
    row = analyse(ctx, monkeypatch)
    assert row.recent_form['status'] == 'baseline_fallback'
    assert 'ambiguous same-day' in row.recent_form['reason']
    monkeypatch.setattr(scanner, 'RECENT_FORM_ENABLED', False)
    baseline = scanner.analyse(fixture(), ctx.long, ctx.results, ctx.averages, NOW, ctx.history)
    assert baseline.recent_form['status'] == 'disabled'
    assert (row.lam_h,row.lam_a)==pytest.approx((baseline.lam_h,baseline.lam_a))
    assert row.p_model == baseline.p_model


def test_h2h_only_identified_same_league_prior_day_and_no_name_fallback(monkeypatch):
    data = sample()
    data.loc[len(data)] = record(NOW,'Alpha','Beta','a','b',50,50,'today')
    data.loc[len(data)] = record(NOW-timedelta(days=60),'Alpha','Beta','a','b',9,9,'cup','LS:test/cup')
    ctx = model.prepare(data, NOW)
    row = analyse(ctx, monkeypatch)
    assert [x['event_id'] for x in row.recent_form['h2h']['matches']] == ['h1','h2','h3']
    ev = quality.h2h_evidence([], NOW, row.recent_form)
    assert ev['used_by_model'] and ev['model_n']==3 and 'displayed sample may differ' in ev['note']
    fx = fixture();fx['home_id'] = None
    other = scanner.analyse(fx, ctx.long, ctx.results, ctx.averages, NOW, ctx.history)
    assert other.recent_form['h2h']['n'] == 0
    assert not quality.h2h_evidence([], NOW, other.recent_form)['used_by_model']


def test_no_combining_unvalidated_experimental_signals(monkeypatch):
    monkeypatch.setattr(scanner, 'RECENT_FORM_ENABLED', True)
    monkeypatch.setattr(scanner, 'EXPERIMENTAL_MODEL_SIGNALS', True)
    with pytest.raises(ValueError, match='cannot be combined'):
        scanner.analyse(fixture(), pd.DataFrame(), pd.DataFrame(), {}, NOW)
    with pytest.raises(ValueError, match='cannot be combined'):
        scanner.main()


def test_environment_rollback_and_default():
    for value, expected in [(None, True), ('0', False), ('1', True)]:
        env = dict(os.environ); env.pop('RECENT_FORM_ENABLED', None)
        if value is not None: env['RECENT_FORM_ENABLED'] = value
        result = subprocess.check_output([sys.executable,'-c','import scanner; print(scanner.RECENT_FORM_ENABLED)'], env=env, text=True)
        assert result.strip() == str(expected)


def test_recent_team_cache_and_new_scan_reset(monkeypatch):
    ctx = model.prepare(sample(), NOW)
    calls = []
    orig = recent_form.prepare_team
    def counted(*args):
        calls.append(1)
        return orig(*args)
    monkeypatch.setattr(recent_form, 'prepare_team', counted)
    row = analyse(ctx, monkeypatch)
    again = scanner.analyse(fixture(), ctx.long, ctx.results, ctx.averages, NOW, ctx.history)
    assert len(calls) == 2 and row.lam_h == again.lam_h
    scanner.RECENT_TEAM_CACHE.clear()
    scanner.analyse(fixture(), ctx.long, ctx.results, ctx.averages, NOW, ctx.history)
    assert len(calls) == 4


def test_bad_recent_values_and_future_inputs_fail_closed():
    p = scanner.TeamProfile('Alpha'); p.n_eff=10; p.n=10
    df=pd.DataFrame({'date':pd.to_datetime(['2026-10-09']), 'venue':['H'], 'gf':[1], 'ga':[0], 'gf_norm':[1.], 'ga_norm':[0.]})
    recent_form.prepare_team(p, df, 'H', NOW)
    with pytest.raises(ValueError):
        recent_form.prepare_team(p, df.assign(date=pd.Timestamp(NOW)), 'H', NOW)
    with pytest.raises(ValueError):
        recent_form.prepare_team(p, df.assign(gf=-1), 'H', NOW)
    with pytest.raises(ValueError):
        recent_form.prepare_team(p, df.assign(gf_norm=np.nan), 'H', NOW)


def test_match_audit_and_markdown_report_actual_application(monkeypatch):
    ctx = model.prepare(sample(), NOW)
    row = analyse(ctx, monkeypatch)
    scanner.build_audits([row], NOW)
    assert row.audit, 'the audit must not silently fail'
    assert row.audit['h2h']['used_by_model'] is True
    assert row.audit['explain']['recent_form']['status'] == 'applied'
    d = {'home':'Alpha','away':'Beta','quality':row.audit['quality'],
         'h2h_meta':row.audit['h2h'], 'explain':row.audit['explain'],
         'evidence':row.audit['evidence'], 'xg':{'model_home':row.lam_h,'model_away':row.lam_a,
         'model_total':row.lam_h+row.lam_a},'p':row.p_model}
    report = quality.audit_markdown(d)
    assert 'model H2H adjustment: **yes, eligible subset**' in report
    assert 'Recent form status: **applied**' in report
    assert 'not prospectively validated' in report
    assert 'baseline terms' in report

"""Numerical consistency only; these tests do not establish predictive skill."""
import math
import numpy as np
import pytest
import scanner, markets


@pytest.mark.parametrize('home,away',[(.15,.15),(.15,4.5),(1.4,1.1),(4.5,4.5)])
def test_dc_market_consistency(home,away):
    m=scanner.score_matrix(home,away,scanner.CONFIG['DC_RHO'])
    assert np.isfinite(m).all() and (m>=0).all() and m.sum()==pytest.approx(1,abs=1e-12)
    x=markets.one_x_two(m); goals=scanner.probs_from_matrix(m); team=markets.team_goals(m)
    assert x['H']+x['D']+x['A']==pytest.approx(1)
    assert x['1X']==pytest.approx(1-x['A']) and x['12']==pytest.approx(1-x['D']) and x['X2']==pytest.approx(1-x['H'])
    assert goals['BTTS']==pytest.approx(m[1:,1:].sum())
    assert goals['O15']==pytest.approx(1-m[0,0]-m[0,1]-m[1,0])
    assert team['H_o05']==pytest.approx(m[1:,:].sum()) and team['A_o05']==pytest.approx(m[:,1:].sum())
    assert 1>=goals['O15']>=goals['O25']>=goals['O35']>=goals['O45']>=goals['O55']>=0
    # Report the omitted unadjusted Poisson tail at the model's cap; the matrix
    # is normalized over 0..10 and does not model these outcomes explicitly.
    tail=1-sum(math.exp(-home)*home**k/math.factorial(k) for k in range(scanner.MAXG+1))
    assert 0 <= tail < .01


def test_negative_binomial_tail_and_market_prices():
    for params in (markets.CORNERS,markets.CARDS):
        for side in ('total','team'):
            probs=[markets.over_line(10,params['r_'+side],x) for x in params['lines_'+side]]
            assert all(0<=p<=1 for p in probs) and probs==sorted(probs,reverse=True)
    assert sum(markets.power_demargin([2.3,3.3,3.2]))==pytest.approx(1)
    assert 0 < markets.fair_two_way(1.8,2.1) < 1
    assert math.isnan(markets.fair_two_way(None,2))

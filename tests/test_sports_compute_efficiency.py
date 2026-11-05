"""Offline invariance and freshness tests; synthetic data, no accuracy claims."""
import copy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'analysis'))
import nba_independent_predictions as nba
import football_jc_euro_asian as football


def history(days=60):
    rows=[]
    for n in range(days):
        for k in range(5):
            hp,ap=100+(n+k)%20,95+(n*3+k)%20
            rows.append(dict(date=(date(2025,1,1)+timedelta(days=n)).isoformat(),
                season='2024-25',home=f'H{k}',away=f'A{k}',home_points=hp,away_points=ap,
                margin_home=hp-ap,total=hp+ap,home_possessions_est=99.,away_possessions_est=99.,pace_est=99.))
    return rows


def fit():
    models={t:dict(means=np.zeros(12),stds=np.ones(12),beta=np.arange(12)*.001,
                   mean_y=3. if t=='margin' else 220.) for t in ('margin','total')}
    cal={t:dict(residual_bias=0.,sigma=12.,residual_quantiles={'80':[-15.,15.]})
         for t in ('margin','total')}
    cal.update(_calibrated_through='2025-02-01',_sample=240)
    return models,cal,{}


def board():
    return {'games':[dict(game_id=str(k),date='2025-04-01',home=f'H{k%5}',away=f'A{k%5}',
                         spread_line=-3.5,total_line=220.5) for k in range(10)]}


class ComputeTests(unittest.TestCase):
    def test_nba_batch_exactly_matches_uncached_predictions(self):
        games=history(); models,cal,_=fit(); cutoff=date(2025,3,1)
        fixtures=board()['games']
        fixtures.append(dict(fixtures[0],date='2025-04-02'))
        cache={}
        for f in fixtures:
            self.assertEqual(nba._prediction_for_fixture(f,games,models,cal,cutoff),
                nba._prediction_for_fixture(f,games,models,cal,cutoff,context_cache=cache))
        self.assertEqual(len(cache),2)

    def test_generate_rebuilds_after_new_source_history(self):
        games=history(); b=board()
        with patch.object(nba,'extract_history',side_effect=lambda _: (copy.deepcopy(games),[],[])), \
             patch.object(nba,'_fit_production_model',side_effect=lambda *_:fit()), \
             patch.object(nba,'_history_before',wraps=nba._history_before) as hist, \
             patch.object(nba,'_elo_before',wraps=nba._elo_before) as elo:
            first=nba.generate(b)
            self.assertEqual((hist.call_count,elo.call_count),(1,1))
            games[-5]['home_points']+=20
            games[-5]['margin_home']+=20
            games[-5]['total']+=20
            second=nba.generate(b)
            self.assertEqual((hist.call_count,elo.call_count),(2,2))
            self.assertNotEqual(first['predictions'][0]['margin_mean_home_minus_away'],
                                second['predictions'][0]['margin_mean_home_minus_away'])

    def test_future_games_excluded_in_cached_context(self):
        games=history(); models,cal,_=fit(); f=board()['games'][0]
        future=dict(games[-5],date=f['date'],home_points=999,margin_home=900,total=1100)
        self.assertEqual(nba._prediction_for_fixture(f,games,models,cal,date(2025,3,1),context_cache={}),
            nba._prediction_for_fixture(f,games+[future],models,cal,date(2025,3,1),context_cache={}))

    def test_football_kernel_exact_and_immutable(self):
        football._fit_outcomes.cache_clear()
        for h,a in ((.15,4.5),(4.5,.15),(1.4,1.1),(2.,2.)):
            self.assertEqual(football._fit_outcomes(h,a),tuple(football.outcome_three(football.grid(h,a))))
        first=football.fit_1x2([.45,.3,.25])
        first[2][0]=999
        self.assertLess(football.fit_1x2([.45,.3,.25])[2][0],1)
        self.assertGreater(football._fit_outcomes.cache_info().hits,0)
        self.assertEqual(football._fit_outcomes.cache_info().maxsize,4096)

    def test_football_rejects_nonfinite_or_negative_probabilities(self):
        for p in ([float('nan'),.3,.7],[float('inf'),.3,.7],[-.1,.5,.6],[True,0,0]):
            with self.assertRaises(ValueError):football.fit_1x2(p)

    def test_all_asian_lines_match_direct_stake_settlement(self):
        grid=football.grid(1.7,1.1)
        for line in football.LINES:
            sums=[0.,0.,0.];event=0.
            for h,row in enumerate(grid):
                for a,p in enumerate(row):
                    units=football.outcome_units(h,a,line)
                    for k in range(3):sums[k]+=p*units[k]
                    if units[0]>0:event+=p
            actual=football.asian_fair(grid,line)
            for k,name in enumerate(('win','loss','refund')):
                self.assertEqual(actual['home_stake_fraction_'+name],round(sums[k],7))
            self.assertEqual(actual['home_full_or_half_win_event_probability'],round(event,7))

if __name__=='__main__':unittest.main()

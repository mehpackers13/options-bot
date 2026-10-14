import contextlib
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

import pandas as pd
import bot
import config
import self_improve
import ai_brain
import data_sources
import earnings_calendar
import signal_filter
import storage
import schedule_guard

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for module, names in [(bot,['ALERTS_LOG','HISTORY_FILE','THRESHOLDS_FILE','BOT_LOG']),
                              (self_improve,['ALERTS_LOG','THRESHOLDS_FILE','CHANGES_LOG']),
                              (ai_brain,['ALERTS_LOG','AI_LOG']), (signal_filter,['ALERTS_LOG'])]:
            for name in names:
                target = self.base / {'ALERTS_LOG':'alerts.csv','THRESHOLDS_FILE':'thresholds.json'}.get(name,name)
                patcher = patch.object(module,name,target)
                patcher.start(); self.addCleanup(patcher.stop)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        # Any accidental network request is a test failure.
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected network call')))

    def write_alerts(self,rows):
        with bot.ALERTS_LOG.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=bot._CSV_HEADERS)
            writer.writeheader();writer.writerows(rows)

    def test_baseline_excludes_today_and_sorts_dates(self):
        today=dt.datetime.now(bot.ET).date()
        vols={(today-dt.timedelta(days=i)).isoformat():100 for i in reversed(range(1,7))}
        vols[today.isoformat()]=99999
        bot.save_history({'SPY':{'volume':vols,'iv':{}}})
        self.assertEqual(bot.get_20day_stats('SPY'),(100,None,6))

    def test_no_signal_without_five_prior_days(self):
        data={'ticker':'SPY','total_volume':100000,'avg_iv':70,'put_call_ratio':4}
        self.assertEqual(bot.detect_raw_signals(data,config.DEFAULT_THRESHOLDS),[])
        self.assertTrue(bot.HISTORY_FILE.exists())

    def test_duplicate_check_does_not_reserve_undelivered_signal(self):
        self.assertFalse(bot._is_duplicate('SPY','volume_spike'))
        self.assertFalse(bot._is_duplicate('SPY','volume_spike'))

    def test_duplicate_persists_across_process_memory_reset(self):
        self.write_alerts([{'ticker':'SPY','signal_type':'volume_spike','timestamp':dt.datetime.now(bot.ET).isoformat()}])
        bot._recent_alerts.clear()
        self.assertTrue(bot._is_duplicate('SPY','volume_spike'))
        self.assertFalse(bot._is_duplicate('QQQ','volume_spike'))

    def test_expired_duplicate_is_eligible(self):
        self.write_alerts([{'ticker':'SPY','signal_type':'volume_spike','timestamp':(dt.datetime.now(bot.ET)-dt.timedelta(minutes=61)).isoformat()}])
        self.assertFalse(bot._is_duplicate('SPY','volume_spike'))

    def test_failed_delivery_not_logged(self):
        sig={'type':'volume_spike','label':'Volume'}
        with patch.object(bot,'check_vix_and_alert',return_value=None), patch.object(config,'TICKERS',['SPY']), patch.object(bot,'fetch_options_data',return_value={'ticker':'SPY'}), patch.object(bot,'is_earnings_play',return_value=(False,None)), patch.object(bot,'earnings_in_next_week',return_value=(False,None)), patch.object(bot,'detect_raw_signals',return_value=[sig]), patch.object(bot,'check_all_gates',return_value=(True,80,'')), patch.object(bot,'build_context_summary',return_value=''), patch.object(bot,'send_discord_alert',return_value=False), patch.object(bot,'log_alert') as record, patch.object(bot,'send_health_update') as health, patch.object(bot.time,'sleep'):
            bot.run_scan()
            record.assert_not_called()
            self.assertEqual(health.call_args.args[1],0)

    def test_missing_chain_columns_and_no_calls(self):
        chain={'source':'fixture','expirations':[{'expiry':'2026-10-01','calls':pd.DataFrame(),'puts':pd.DataFrame([{'strike':100,'volume':100,'impliedVolatility':.25}])}]}
        with patch.object(data_sources,'get_current_price',return_value=100),patch.object(data_sources,'get_options_chain',return_value=chain):
            result=bot.fetch_options_data('SPY')
        self.assertIsNotNone(result)
        self.assertIsNone(result['put_call_ratio'])
        self.assertEqual(result['total_volume'],100)

    def test_thresholds_merge_defaults_and_clamp(self):
        bot.THRESHOLDS_FILE.write_text('{"iv_jump_percent": 999, "_ratings_fingerprint":"abc"}')
        result=bot.load_thresholds()
        self.assertEqual(result['iv_jump_percent'],60)
        self.assertEqual(result['volume_spike_multiplier'],3)
        self.assertNotIn('_ratings_fingerprint',result)

    def test_invalid_threshold_fails_explicitly(self):
        bot.THRESHOLDS_FILE.write_text('{"iv_jump_percent": "broken"}')
        with self.assertRaises(ValueError):bot.load_thresholds()

    def test_atomic_failed_write_preserves_existing_state(self):
        path=self.base/'state.json';storage.atomic_json(path,{'ok':1})
        with self.assertRaises(ValueError):storage.atomic_json(path,{'bad':float('nan')})
        self.assertEqual(json.loads(path.read_text()),{'ok':1})
        self.assertEqual(list(self.base.glob('.state-*')),[])

    def test_unchanged_ratings_do_not_tune_twice(self):
        self.write_alerts([{'timestamp':str(i),'signal_type':'volume_spike','signal_value':'4','outcome':'0'} for i in range(20)])
        self.assertEqual(self_improve.run_morning_analysis(),1)
        first=bot.load_thresholds()
        self.assertEqual(self_improve.run_morning_analysis(),0)
        self.assertEqual(bot.load_thresholds(),first)

    def test_nan_volume_rejected(self):
        self.assertFalse(signal_filter.check_all_gates('SPY','volume_spike',float('nan'))[0])

    def test_plain_date_earnings_parsed(self):
        date=dt.date(2026,10,1)
        with patch.object(earnings_calendar.yf,'Ticker',return_value=Mock(calendar={'Earnings Date':[date]})):
            self.assertEqual(earnings_calendar.get_next_earnings('SPY'),date)

    def test_past_earnings_not_upcoming(self):
        yesterday=dt.datetime.now(bot.ET).date()-dt.timedelta(days=1)
        with patch.object(earnings_calendar,'get_next_earnings',return_value=yesterday):
            self.assertFalse(earnings_calendar.earnings_within_hours('SPY')[0])

    def test_ai_rejects_wrong_json_shapes(self):
        for raw in ['[]','true','{"summary":null}','{"premarket_watchlist":[123]}']:
            self.assertIsNone(ai_brain._parse_json_response(raw))
        self.assertEqual(ai_brain._parse_json_response('```json\n{"summary":"ok"}\n```'),{'summary':'ok'})

    def test_ai_period_uses_eastern_and_ignores_bad_dates(self):
        stamp=dt.datetime.now(bot.ET).isoformat()
        self.write_alerts([{'timestamp':stamp},{'timestamp':'invalid'},{'timestamp':'2000-01-01 12:00:00'}])
        self.assertEqual(len(ai_brain._load_alerts()),1)

    def test_reinitializing_provider_clears_previous_token(self):
        with patch.object(data_sources,'_tradier_token','test-only'),patch.dict(os.environ,{'TRADIER_API_TOKEN':''}):
            data_sources.init()
            self.assertEqual(data_sources._tradier_token,'')

    def test_schedule_only_one_cron_selected(self):
        event=self.base/'event.json'
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule','GITHUB_EVENT_PATH':str(event)}):
            results=[]
            for cron in ['0 12 * * 1-5','0 13 * * 1-5']:
                event.write_text(json.dumps({'schedule':cron}));results.append(schedule_guard.should_run('morning'))
            self.assertEqual(sum(results),1)

    def test_legacy_csv_upgrade_preserves_outcomes(self):
        bot.ALERTS_LOG.write_text("timestamp,ticker,signal_type,outcome,notes\n2026-01-01,SPY,volume_spike,1,keep me\n")
        bot.ensure_log_file()
        with bot.ALERTS_LOG.open() as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(rows[0]['outcome'],'1')
        self.assertEqual(rows[0]['notes'],'keep me')
        self.assertIn('data_source',rows[0])

    def test_market_holiday_and_early_close(self):
        from market_clock import market_open
        et=ZoneInfo('America/New_York')
        self.assertFalse(market_open(dt.datetime(2026,12,25,12,tzinfo=et)))
        self.assertTrue(market_open(dt.datetime(2026,11,27,12,tzinfo=et)))
        self.assertFalse(market_open(dt.datetime(2026,11,27,14,tzinfo=et)))
        self.assertFalse(market_open(dt.datetime(2026,9,22,9,29,tzinfo=et)))
        self.assertTrue(market_open(dt.datetime(2026,9,22,9,30,tzinfo=et)))

if __name__=='__main__':unittest.main()

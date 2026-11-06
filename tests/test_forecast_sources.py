import unittest

from research.forecast_sources import embedded_json, parse_forecasts, parse_polls, sheets, validate
from research.polling_audit import aggregate, normalize, score, walk_forward


class SourceTests(unittest.TestCase):
    def test_html_is_not_csv(self):
        with self.assertRaises(ValueError):
            validate(b'<!DOCTYPE html><html>News</html>', 'csv', {'state'})
        with self.assertRaises(ValueError):
            validate(b'name,value\na,b\n', 'csv', {'state'})

    def test_embedded_json_no_eval(self):
        self.assertEqual(embedded_json('window.x = {"a":2}; dangerous();', 'x'), {'a':2})

    def test_returned_sheet_names_and_party_warning(self):
        payload = {'sheetNames':['Last Update','Win'], 'data':[
            [['Last Updated Sep 25']], [['','D','R','Ind'],['Test','','R: 60%','I: 40%'],['Special 2','Dem: 0%','Rep: 0%','']]]}
        result = parse_forecasts(payload)
        self.assertEqual(len(result['races']), 1)
        self.assertEqual(result['races'][0]['candidates'][1]['sourceColumn'], 'Ind')
        self.assertFalse(result['races'][0]['mappingApproved'])
        payload['data'][1][1][2] = 'R: 160%'
        with self.assertRaises(ValueError):
            parse_forecasts(payload)

    def test_sheet_length_failure(self):
        with self.assertRaises(ValueError):
            sheets({'sheetNames':['a','b'], 'data':[[]]})

    def test_forecast_empty_or_changed_schema(self):
        for rows in ([], [['','D','R','Ind'],['Test','D: 50%','R: 50%','', 'extra']]):
            with self.assertRaises(ValueError):
                parse_forecasts({'sheetNames':['Win'], 'data':[rows]})

    def test_tsv_validation(self):
        self.assertEqual(validate(b'year\tstate\n2024\tTEST\n', 'tsv', {'year','state'}),
                         [{'year':'2024','state':'TEST'}])

    def test_linked_poll_rows_dedup(self):
        row = ['9/25', {'href':'https://example.org/poll', 'value':'Sep 20: 600 LV'},'49','48']
        payload = {'sheetNames':['Example'], 'data':[[['Added','Poll (Includes Link)','D','R'],row,row,['','No Polls Yet','','']]]}
        self.assertEqual(len(parse_polls(payload)), 1)


class PollAuditTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(type_simple='Sen-G', cand1_party='REP', cand2_party='DEM',
                   polldate='10/25/2022', electiondate='11/8/2022', margin_poll='3', margin_actual='1',
                   year='2022', race_id='r', race='example', pollster='test', pollster_rating_id='1',
                   poll_id='1', question_id='1')
        row.update(changes)
        return row

    def test_party_orientation(self):
        value, reason = normalize(self.row())
        self.assertIsNone(reason)
        self.assertEqual((value['margin'], value['actual'], value['error']), (-3,-1,-2))

    def test_date_and_nonfinite_filters(self):
        for changes in ({'polldate':'11/9/2022'}, {'polldate':'9/1/2022'}, {'margin_poll':'nan'}, {'year':'2020'}):
            self.assertIsNone(normalize(self.row(**changes))[0])

    def test_latest_pollster_only(self):
        rows = [normalize(self.row())[0], normalize(self.row(polldate='10/20/2022',margin_poll='10',poll_id='2'))[0]]
        races, conflicts = aggregate(rows + rows)
        self.assertEqual(races[0]['margin'], -3)
        self.assertEqual(races[0]['pollsters'], 1)
        self.assertFalse(conflicts)

    def test_inconsistent_outcome_quarantined(self):
        rows = [normalize(self.row())[0], normalize(self.row(margin_actual='9'))[0]]
        races, conflicts = aggregate(rows)
        self.assertFalse(races)
        self.assertEqual(len(conflicts), 1)

    def test_future_cycles_not_used_to_fit(self):
        races = [dict(year=2016, office='Sen-G', error=i%3-1, margin=1, actual=1) for i in range(30)]
        races += [dict(year=2018, office='Sen-G', error=100, margin=1, actual=1),
                  dict(year=2022, office='Sen-G', error=1000, margin=1, actual=1)]
        predictions, fits = walk_forward(races, (2018,))
        self.assertEqual(fits[0]['trainingYears'], [2016])
        self.assertEqual(fits[0]['biasDemPoints'], 0)
        self.assertEqual(len(predictions), 1)

    def test_brier(self):
        self.assertEqual(score([{'pDem':.5,'actual':1}])['brier'], .25)


if __name__ == '__main__':
    unittest.main()

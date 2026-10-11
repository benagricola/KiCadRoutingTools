"""Read-only requested-width policy uses the routing engine's own precedence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_router'))
sys.path.insert(0, str(ROOT / 'tests' / 'oracle'))
from constraint_agreement import write_board
from nominal_width_policy import WidthPolicyRefusal, nominal_policy, options


class WidthPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / 'board.kicad_pcb'
        write_board(str(self.board), classes=[{'name': 'wide', 'track_width': 0.4,
                    'diff_pair_width': 0.11, 'clearance': 0.2}], patterns=[('B', 'wide')])

    def policy(self, **kwargs):
        req = {'name': 'signals', 'kind': 'nets', 'nets': ['A', 'B'], 'layers': ['F.Cu', 'B.Cu'], 'args': []}
        req.update(kwargs)
        return nominal_policy(str(self.board), [req])['policies'][0]['by_net']

    def test_default_and_nondefault_widths_and_global_override(self):
        self.assertEqual(self.policy()['A']['widths']['F.Cu'], 0.2)
        self.assertEqual(self.policy()['B']['widths']['F.Cu'], 0.4)
        got = self.policy(args=['--track-width', '0.5', '--track-width=0.3'])
        self.assertEqual([got[n]['widths']['F.Cu'] for n in ('A', 'B')], [0.3, 0.3])

    def test_power_base_floor_and_exact_task_layer_override(self):
        got = self.policy(args=['--track-width', '0.5'], power={'A': 0.3, 'B': 0.6})
        self.assertEqual([got[n]['widths']['F.Cu'] for n in ('A', 'B')], [0.5, 0.6])
        got = self.policy(args=['--track-width', '0.5'], tasks={'A': {'F.Cu': 0.3, 'B.Cu': 0.25}})
        self.assertEqual(got['A']['widths'], {'F.Cu': 0.3, 'B.Cu': 0.25})

    def test_dru_layer_draw_width_and_explicit_global_priority(self):
        self.board.with_suffix('.kicad_dru').write_text('(version 1)\n'
            '(rule "A outer" (condition "A.NetName == \'A\'") (layer "F.Cu") (constraint track_width (opt 0.32)))\n'
            '(rule "A inner" (condition "A.NetName == \'A\'") (layer "B.Cu") (constraint track_width (opt 0.27)))\n')
        self.assertEqual(self.policy()['A']['widths'], {'F.Cu': 0.32, 'B.Cu': 0.27})
        self.assertEqual(self.policy(args=['--track-width', '0.5'])['A']['widths'], {'F.Cu': 0.5, 'B.Cu': 0.5})

    def test_pair_class_and_separate_explicit_pair_width(self):
        got = self.policy(kind='pairs', pairs=[['B', 'A']])
        self.assertEqual(got['A']['widths']['F.Cu'], 0.127)
        self.assertEqual(self.policy(kind='pairs', pairs=[['B', 'A']], args=['--track-width', '0.3'])['A']['widths']['F.Cu'], 0.3)

    def test_rest_phase_width_override_uses_real_single_option_parser(self):
        base = {'name': 'rest', 'owner': 'pair', 'kind': 'pairs', 'nets': ['A', 'B'],
                'pairs': [['B', 'A']], 'layers': ['F.Cu'], 'args': [],
                'rest_phase_args': [], 'rest_single_args': ['--track-width', '0.6']}
        inherited = nominal_policy(str(self.board), [base])['policies'][0]
        self.assertEqual(inherited['by_net']['A']['widths']['F.Cu'], 0.127)
        self.assertEqual(inherited['owner'], 'pair')
        for args in (['--track-width', '0.3'], ['--track-w=0.3']):
            request = dict(base, rest_phase_args=args, rest_single_args=['--track-width', '0.6'] + args)
            result = nominal_policy(str(self.board), [request])['policies'][0]
            self.assertEqual(result['by_net']['A']['widths']['F.Cu'], 0.3)
            self.assertEqual((result['effective_kind'], result['owner']), ('nets', 'rest'))

    def test_impedance_unknown_but_fixed_task_remains_known(self):
        got = self.policy(args=['--impedance', '50'], tasks={'A': {'F.Cu': 0.3, 'B.Cu': 0.3}})
        self.assertEqual(got['A']['status'], 'known')
        self.assertEqual(got['B']['status'], 'unknown')
        self.assertIsNone(got['B']['widths'])

    def test_argparse_vocabulary_abbreviation_separator_and_owned_raw_widths(self):
        self.assertEqual(options(['--track-w', '0.4'], 'route.py')['--track-width'], 0.4)
        self.assertEqual(options(['--', '--track-width', '0.4'], 'route.py'), {})
        self.assertEqual(options(['--diff-pair-gap=0.15'], 'route_diff.py'), {'--diff-pair-gap': 0.15})
        with self.assertRaises(WidthPolicyRefusal) as refused:
            options(['--track', '0.4'], 'route.py')
        self.assertEqual(refused.exception.code, 'router_arguments_rejected')
        self.assertEqual(refused.exception.fields['exit_code'], 2)
        with self.assertRaises(WidthPolicyRefusal) as refused:
            options(['--power-nets-widths', '0.4'], 'route.py')
        self.assertEqual((refused.exception.code, refused.exception.fields),
                         ('structured_request_field_required', {'option': '--power-nets-widths'}))

    def test_unknown_widths_are_codes_with_fields(self):
        got = self.policy(args=['--impedance', '50'])
        self.assertEqual(got['A']['reason'], {'code': 'impedance_width'})
        self.assertIsNone(self.policy()['A']['reason'])
        self.board.with_suffix('.kicad_dru').write_text('(version 1)\n'
            '(rule "odd" (condition "A.NetName == \'A\'") (constraint track_width (opt "wide")))\n')
        reason = self.policy()['A']['reason']
        self.assertEqual(reason['code'], 'design_rules_unknown')
        self.assertEqual([(r['code'], r['rule']) for r in reason['rules']], [('rule_unsupported', 'odd')])

    def test_fab_override_is_consumed_and_hashed(self):
        override = Path(self.tmp.name) / 'floors.json'
        override.write_text('track_width = 0.3\n')
        result = nominal_policy(str(self.board), [{'name': 'x', 'kind': 'nets', 'nets': ['A'],
            'layers': ['F.Cu'], 'args': ['--fab-overrides', str(override)]}])
        self.assertEqual(result['policies'][0]['by_net']['A']['widths']['F.Cu'], 0.3)
        import hashlib
        self.assertEqual(result['external_inputs'][str(override)], hashlib.sha256(override.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()

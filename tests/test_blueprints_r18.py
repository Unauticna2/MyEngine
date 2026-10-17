"""Repeated Blueprint updates must not move an object used as a purchase indicator."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

from engine_blueprints import generated_source
from engine_runtime import Entity, NativeEntity, ScriptBinding


def gate_graph(key, *, legacy_offset=None):
    graph = {'format': 1, 'nodes': [
        {'id': 'start', 'type': 'Start'},
        {'id': 'update', 'type': 'Update'},
        {'id': 'status', 'type': 'TransactionIs', 'params': {'key': key, 'state': 'succeeded'}},
        {'id': 'branch', 'type': 'Branch'},
        {'id': 'show', 'type': 'SetVisible', 'params': {'visible': True}},
        {'id': 'hide', 'type': 'SetVisible', 'params': {'visible': False}}],
        'links': [['start', 'next', 'branch', 'in'], ['update', 'next', 'branch', 'in'],
                  ['status', 'value', 'branch', 'condition'],
                  ['branch', 'true', 'show', 'in'], ['branch', 'false', 'hide', 'in']]}
    if legacy_offset is not None:
        graph['links'].pop(0)  # The supplied failing graph only ran in Update.
        for node in graph['nodes'][-2:]:
            node['type'] = 'Move'
            node['params'] = {'y': legacy_offset if node['id'] == 'hide' else 0}
    return graph


class BlueprintObjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.states = {}; self.logs = []; self.bindings = []
        self.world = NS(root=self.root, ui=None, scripts_allowed=True, editor_mode=False,
                        assert_thread=lambda: None, log=self.logs.append,
                        transactions=NS(state=lambda key: self.states.get(key, 'idle')),
                        resources=NS(model=lambda model: [NS(id=7)]))
        self.entity = Entity(self.world, 1, NativeEntity(), 'Cube', None, 1, 'cube')
        self.entity.position = (4, 1, -2)
        self.entity.w = 3
        self.addCleanup(self.clean_bindings)

    def clean_bindings(self):
        for binding in self.bindings:
            sys.modules.pop(binding.module_name, None)

    def bind(self, graph):
        path = self.root / f'graph{len(self.bindings)}.py'
        path.write_text(generated_source(graph)[0], encoding='utf-8')
        binding = ScriptBinding(self.entity, path)
        self.bindings.append(binding)
        self.assertTrue(binding.reload())
        return binding

    def test_original_large_move_reproduces_both_failures(self):
        for offset in (100000, 1000000):
            with self.subTest(offset=offset):
                self.entity.position = (4, 1, -2)
                binding = self.bind(gate_graph('purchase', legacy_offset=offset))
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    for _ in range(11):
                        binding.call('update', 1/60)
                self.assertFalse(binding.enabled)
                self.assertIn('Invalid/out-of-range number', output.getvalue())

    def test_visibility_tracks_each_key_without_moving_or_disabling(self):
        collider = self.entity.collider = object()
        body = self.entity.rigidbody = object()
        for key in ('purchase', 'cube2'):
            with self.subTest(key=key):
                self.states.clear()
                self.states['unrelated'] = 'succeeded'
                binding = self.bind(gate_graph(key))
                self.assertFalse(self.entity.visible)  # Already hidden by Start.
                for state in ('idle', 'creating', 'pending', 'manual', 'unknown',
                              'succeeded', 'succeeded', 'failed', 'canceled', 'succeeded'):
                    self.states[key] = state
                    for _ in range(120):
                        binding.call('update', 1/60)
                        self.entity.sync()
                        self.assertEqual(self.entity.visible, state == 'succeeded')
                        self.assertEqual(self.entity.native.visible, int(state == 'succeeded'))
                        self.assertEqual(tuple(self.entity.position), (4, 1, -2))
                        self.assertEqual(self.entity.w, 3)
                        self.assertTrue(binding.enabled)
                self.assertTrue(self.entity.active)
                self.assertIs(self.entity.collider, collider)
                self.assertIs(self.entity.rigidbody, body)

    def test_connected_visibility_boolean_and_next_action(self):
        graph = {'format': 1, 'nodes': [
            {'id': '1', 'type': 'Update'}, {'id': '2', 'type': 'TransactionIs', 'params': {'key': 'purchase'}},
            {'id': '3', 'type': 'SetVisible'}, {'id': '4', 'type': 'Print', 'params': {'text': 'next'}}],
            'links': [['1', 'next', '3', 'in'], ['2', 'value', '3', 'visible'], ['3', 'next', '4', 'in']]}
        binding = self.bind(graph)
        binding.call('update', .01)
        self.assertFalse(self.entity.visible)
        self.states['purchase'] = 'succeeded'
        binding.call('update', .01)
        self.assertTrue(self.entity.visible)
        self.assertEqual(self.logs, ['next', 'next'])

    def test_set_position_is_absolute_and_keeps_w(self):
        graph = {'format': 1, 'nodes': [
            {'id': '1', 'type': 'Update'}, {'id': '2', 'type': 'Number', 'params': {'value': -12}},
            {'id': '3', 'type': 'SetPosition', 'params': {'x': 8, 'y': 25, 'z': 3}},
            {'id': '4', 'type': 'Print', 'params': {'text': 'position set'}}],
            'links': [['1', 'next', '3', 'in'], ['2', 'value', '3', 'x'], ['3', 'next', '4', 'in']]}
        binding = self.bind(graph)
        for _ in range(1000):
            binding.call('update', 1/60)
        self.assertEqual(tuple(self.entity.position), (-12, 25, 3))
        self.assertEqual(self.entity.w, 3)
        self.assertEqual(len(self.logs), 1000)
        self.assertTrue(binding.enabled)

    def test_existing_move_still_accumulates(self):
        graph = {'format': 1, 'nodes': [{'id': '1', 'type': 'Update'},
            {'id': '2', 'type': 'Move', 'params': {'y': 2}}], 'links': [['1', 'next', '2', 'in']]}
        binding = self.bind(graph)
        for _ in range(3):
            binding.call('update', .1)
        self.assertEqual(tuple(self.entity.position), (4, 7, -2))

    def test_regeneration_preserves_user_code_and_disconnected_node(self):
        graph = gate_graph('purchase')
        graph['nodes'].append({'id': 'unused', 'type': 'TransactionPaidOnce', 'params': {'key': 'deluxe'}})
        old = '# User header\n' + generated_source(graph)[0] + '\nCUSTOM = 42\n'
        new, unused = generated_source(graph, old)
        self.assertEqual(new, old)
        self.assertEqual(unused, ['unused'])

    def test_visibility_rejects_non_boolean_parameter(self):
        graph = gate_graph('purchase')
        graph['nodes'][-1]['params']['visible'] = 'false'
        with self.assertRaisesRegex(ValueError, 'Boolean'):
            generated_source(graph)


if __name__ == '__main__':
    unittest.main()

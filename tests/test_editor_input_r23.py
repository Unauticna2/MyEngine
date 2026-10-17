import ctypes
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
import engine_editor_input as input
from MyEngine2Editor import Editor
class FocusTests(unittest.TestCase):
    def widget(self,kind='TEntry'):
        w=Mock();w.winfo_class.return_value=kind;w.winfo_exists.return_value=True;w.winfo_id.return_value=0x123456789;w.focus_get.return_value=w;return w
    def user(self):
        return NS(SetFocus=Mock(),GetFocus=Mock(return_value=0),GetForegroundWindow=Mock(return_value=123),GetAncestor=Mock(return_value=123))
    def test_explicit_text_click_repairs_native_focus_without_truncation(self):
        user=self.user();window=Mock();focus=input.EditorTextFocus(window,user=user);w=self.widget();focus.restore(NS(widget=w))
        user.SetFocus.assert_called_once_with(0x123456789);self.assertEqual(user.SetFocus.argtypes,[ctypes.c_void_p]);w.focus_set.assert_not_called()
        self.assertEqual(window.bind_all.call_count,2)
    def test_background_window_and_non_text_controls_never_steal_focus(self):
        user=self.user();focus=input.EditorTextFocus(Mock(),user=user)
        focus.restore(NS(widget=self.widget('Canvas')));user.SetFocus.assert_not_called()
        user.GetForegroundWindow.return_value=999;focus.restore(NS(widget=self.widget()));user.SetFocus.assert_not_called()
    def test_missing_tk_focus_and_destroyed_widget(self):
        user=self.user();focus=input.EditorTextFocus(Mock(),user=user);w=self.widget();w.focus_get.return_value=None;focus.restore(NS(widget=w));w.focus_set.assert_called_once()
        user.SetFocus.reset_mock();w.winfo_exists.return_value=False;focus.restore(NS(widget=w));user.SetFocus.assert_not_called()
    def test_ctfmon_launches_once_with_absolute_system_executable(self):
        kernel=NS(GetSystemDirectoryW=Mock(side_effect=lambda buf,n:(setattr(buf,'value','C:/Windows/System32') or 19)))
        with patch.object(input.sys,'platform','win32'),patch.object(input.C,'WinDLL',return_value=kernel,create=True),patch.object(Path,'is_file',return_value=True),patch.object(input.subprocess,'Popen') as popen,patch.object(input,'_text_services_attempted',False):
            input.start_text_services();input.start_text_services();popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0],['C:/Windows/System32/ctfmon.exe']);self.assertNotIn('shell',popen.call_args.kwargs)
    def test_duplicate_hierarchy_event_does_not_rebuild_inspector(self):
        editor=NS(hierarchy=Mock(),selected=0,inspector_vars={'name':object()},show_inspector=Mock(),send=Mock(),document=NS(data={'names':['A','B']}))
        editor.hierarchy.selection.return_value=('0',);Editor.on_selection(editor);editor.show_inspector.assert_not_called()
        editor.hierarchy.selection.return_value=('1',);Editor.on_selection(editor);editor.show_inspector.assert_called_once()

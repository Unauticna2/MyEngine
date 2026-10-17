"""Win32 API double: validates pointer ABI, routing and restoration; not a real GUI test."""
import ctypes as C
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import engine_window_menu as wm

class Function:
 def __init__(self,fn):self.fn=fn
 def __call__(self,*args):return self.fn(*args)
class User:
 def __init__(self,owner=None,child=False):
  self.proc=123;self.style=0x16CF0000|(0x40000000 if child else 0);self.calls=[];self.menu=[];self.owner=os.getpid() if owner is None else owner
 def __getattr__(self,name):
  def call(*args):
   self.calls.append((name,args))
   if name=='GetWindowThreadProcessId':args[1]._obj.value=self.owner;return 100
   if name=='GetWindowLongPtrW':return self.proc if args[1]==-4 else self.style
   if name=='SetWindowLongPtrW':
    if args[1]==-4:old=self.proc;self.proc=args[2];return old
    old=self.style;self.style=args[2];return old
   if name=='GetSystemMenu':return 200
   if name=='AppendMenuW':self.menu.append(args);return 1
   if name=='GetWindowPlacement':args[1]._obj.showCmd=3;return 1
   if name=='GetMonitorInfoW':
    r=args[1]._obj.rcMonitor;r.left=-1920;r.top=0;r.right=0;r.bottom=1080;return 1
   if name=='CallWindowProcW':return 17
   return 1
  fn=Function(call);setattr(self,name,fn);return fn

class MenuTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.user=User()
  self.patches=[patch.object(wm.sys,'platform','win32'),patch.object(C,'WinDLL',return_value=self.user,create=True),
   patch.object(C,'WINFUNCTYPE',C.CFUNCTYPE,create=True),patch.object(C,'set_last_error',create=True),patch.object(C,'get_last_error',return_value=0,create=True)]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def test_native_struct_sizes(self):
  self.assertEqual(C.sizeof(wm.Placement),44);self.assertEqual(C.sizeof(wm.MonitorInfo),40);self.assertEqual(C.sizeof(wm.Rect),16)
 def test_menu_routes_commands_restores_style_and_original_proc(self):
  menu=wm.TitleMenu(1000,self.tmp.name);style=self.user.style
  self.assertEqual(len(self.user.menu),5)
  self.assertEqual(menu.callback(1000,0x112,wm.FULLSCREEN,0),0);self.assertFalse(menu.fullscreen)
  menu.poll();self.assertTrue(menu.fullscreen);self.assertNotEqual(self.user.style,style)
  pos=[args for name,args in self.user.calls if name=='SetWindowPos'][-1]
  self.assertEqual(pos[2:6],(-1920,0,1920,1080))
  menu.callback(1000,0x100,0x7A,1<<30);self.assertTrue(menu.commands.empty())
  menu.callback(1000,0x100,0x7A,0);menu.poll();self.assertFalse(menu.fullscreen);self.assertEqual(self.user.style,style)
  self.assertEqual(menu.callback(1000,0x10,0,0),17)
  menu.close();self.assertEqual(self.user.proc,123)
 def test_game_uses_native_mailbox_without_python_wndproc(self):
  commands=iter([wm.FULLSCREEN,0,wm.FULLSCREEN])
  menu=wm.TitleMenu(1000,self.tmp.name,native_poll=lambda:next(commands))
  self.assertEqual(self.user.proc,123);self.assertFalse(hasattr(menu,'callback'))
  menu.poll();self.assertTrue(menu.fullscreen);menu.poll();self.assertTrue(menu.fullscreen);menu.poll();self.assertFalse(menu.fullscreen)
  menu.close();self.assertEqual(self.user.proc,123)
 def test_unlock_menu_writes_json(self):
  menu=wm.TitleMenu(1000,self.tmp.name);menu.callback(1000,0x112,wm.UNLOCK,0);menu.poll()
  from engine_access import unlock_all
  self.assertTrue(unlock_all(self.tmp.name));menu.close()
 def test_foreign_or_child_window_rejected(self):
  self.user.owner=0
  with self.assertRaises(ValueError):wm.TitleMenu(1000,self.tmp.name)
  self.user.owner=os.getpid();self.user.style|=0x40000000
  with self.assertRaises(ValueError):wm.TitleMenu(1000,self.tmp.name)
if __name__=='__main__':unittest.main()

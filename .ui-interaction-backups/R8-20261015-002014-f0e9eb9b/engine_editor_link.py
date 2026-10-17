"""Local editor transport. JSON only; commands run on the owning render thread."""
import json
import socket

class Channel:
    LIMIT=4*1024*1024
    def __init__(self,sock):
        self.socket=sock;sock.setblocking(False)
        self.incoming=bytearray();self.outgoing=bytearray();self.closed=False
        self.last_error=None
    def send(self,message):
        if self.closed:return False
        b=json.dumps(message,ensure_ascii=True,allow_nan=False).encode()+b'\n'
        if len(self.outgoing)+len(b)>self.LIMIT:raise RuntimeError('Editor queue overflow')
        self.outgoing.extend(b);return True
    def poll(self):
        if self.closed:return []
        try:
            if self.outgoing:
                try:
                    n=self.socket.send(self.outgoing)
                    if n==0:
                        self.last_error='Socket send returned zero';self.close();return []
                    del self.outgoing[:n]
                except (BlockingIOError,InterruptedError):pass
            # Bound per-frame transport work; no waits in the rendering loop.
            for _ in range(16):
                try:b=self.socket.recv(65536)
                except BlockingIOError:break
                except InterruptedError:continue
                if not b:
                    self.last_error='Peer closed the editor connection';self.close();return []
                self.incoming.extend(b)
                if len(self.incoming)>self.LIMIT:raise ValueError('Editor message too large')
            messages=[]
            while b'\n' in self.incoming:
                raw,_,tail=self.incoming.partition(b'\n');self.incoming=bytearray(tail)
                message=json.loads(raw)
                if not isinstance(message,dict):raise ValueError('Editor message must be a JSON object')
                messages.append(message)
            return messages
        except OSError as ex:
            # A lost IPC link is not an exception in the simulation/render loop.
            self.last_error=str(ex);self.close();return []
        except ValueError as ex:
            self.last_error=str(ex);self.close();raise
    def close(self):
        if self.closed:return
        self.closed=True;self.incoming.clear();self.outgoing.clear()
        try:self.socket.close()
        except OSError:pass


class RuntimeEditor:
    def __init__(self,core,port,token):
        # Authenticate before World.load(), which can take longer than the
        # editor's five-second hello deadline. This is a one-time startup send;
        # every subsequent poll stays nonblocking.
        sock=socket.create_connection(('127.0.0.1',int(port)),timeout=5)
        try:
            hello={'type':'hello','token':token,'hwnd':int(core.hwnd)}
            sock.sendall(json.dumps(hello,ensure_ascii=True,allow_nan=False).encode()+b'\n')
            self.channel=Channel(sock)
            self.selected=None;self._disconnect_reported=False
            from engine_gizmo import Gizmo
            self.gizmo=Gizmo(self,core)
        except BaseException:
            sock.close();raise
    def process(self,world):
        from engine_runtime import switch_scene
        try:commands=self.channel.poll()
        except (OSError,ValueError) as ex:
            self.channel.last_error=str(ex);self.channel.close();commands=[]
        if self.channel.closed:
            if not self._disconnect_reported:
                self._disconnect_reported=True
                # Roll back an unfinished drag and stop unsynchronised edits.
                self.gizmo.cancel();self.gizmo.mode='none';self.selected=None
                world.log('Editor connection closed:',self.channel.last_error or 'Disconnected',
                          'Viewport keeps running. Use Restart viewport in the editor to reconnect.')
            return world
        for command in commands:
            try:
                op=command['op']
                if op=='reload':
                    self.gizmo.cancel()
                    old_mode=world.core.editor_mode
                    world.core.editor_mode=not bool(command.get('play',False))
                    old=world;candidate=switch_scene(world,command['path'])
                    if candidate is old:
                        world.core.editor_mode=old_mode
                        raise RuntimeError('Scene load failed; see engine.log. Previous scene preserved.')
                    world=candidate
                elif op=='object':
                    self.gizmo.cancel()
                    if not world.editor_mode:raise RuntimeError('Stop Play before editing objects')
                    self.replace_object(world,command['old_name'],command['object'])
                elif op=='select':
                    self.gizmo.cancel();self.selected=command.get('name')
                elif op=='tool':
                    mode=command['mode']
                    if mode not in ('move','rotate','scale','rotate4','none'):raise ValueError('Unknown gizmo mode')
                    self.gizmo.cancel();self.gizmo.mode=mode
                elif op=='focus':
                    e=world.find(command['name'])
                    if e and not e.is_player:
                        x,y,z=e.position;world.camera.position=(x,y+2,z+6);world.camera.pitch=12;world.camera.yaw=0
                elif op=='appearance':world.editor_outlines=bool(command.get('outlines',False))
                elif op=='light':world.light_rotation.set(*command['rotation'])
                else:raise ValueError('Unknown editor command: '+op)
                self.channel.send({'type':'ok','op':op,'mode':'Edit' if world.editor_mode else 'Play'})
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self.channel.send({'type':'error','op':command.get('op'),'message':str(ex)})
        return world
    @staticmethod
    def replace_object(world,old_name,d):
        from engine_runtime import vec
        old=world.find(old_name)
        if old is None or old.is_player:raise ValueError('Object no longer exists: '+old_name)
        name=str(d['names'])
        if not name or name=='player' or name!=old_name and world.find(name):raise ValueError('Duplicate/reserved name')
        # Build a replacement before touching the original. Failed validation is non-destructive.
        temporary=f'__editor_{world._next_uid+1}'
        while world.find(temporary):temporary+='x'
        p=d['positions']
        new=world.instantiate(d['model'],name=temporary,position=vec(p),rotation=vec(d['rotations']),
            scale=vec(d['scales'],(1,1,1)),color=vec(d['colors'],(1,1,1),('r','g','b')),
            texture=d['textures'],scripts=d['scripts'],collider=d['colliders'],rigidbody=d['rigidbodies'],
            w=p.get('w',0) if isinstance(p,dict) else 0,layer_spacing=d['layerSpacings'],voxels=d['voxels'],
            scale_w=d['scales'].get('w',1) if isinstance(d['scales'],dict) else 1,
            rotation4=vec(d.get('rotations4D'),keys=('xw','yw','zw')),trusted=d.get('scriptTrusted',True))
        new.cast_shadows=bool(d.get('castShadows',True));new.receive_shadows=bool(d.get('receiveShadows',True))
        new.active=bool(d['active']);new.visible=bool(d['visible'])
        world.destroy(old);world._flush_destroy()
        world.by_name.pop(temporary);new.name=name;world.by_name[name]=new;new.sync();world._submit()
    def close(self):self.channel.close()

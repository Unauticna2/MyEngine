bl_info={
    'name':'MyEngine 4D Hierarchy','author':'MyEngine','version':(1,1,0),
    'blender':(3,0,0),'location':'File > Import / Export > MyEngine 4D; N > MyEngine',
    'description':'Import and export .4d files as editable child-depth W layers',
    'category':'Import-Export',
}
import bpy
from bpy.props import BoolProperty,EnumProperty,FloatProperty,StringProperty
from bpy_extras.io_utils import ExportHelper,ImportHelper
# Blender may retain child modules when an installed addon is replaced/reloaded.
# Reload our own pure modules explicitly before binding the export functions.
import importlib
from . import hierarchy as _hierarchy
from . import format4d as _format4d
from . import exporter as _exporter
from . import importer as _importer
importlib.reload(_hierarchy)
importlib.reload(_format4d)
importlib.reload(_exporter)
importlib.reload(_importer)
export_hierarchy=_exporter.export_hierarchy
import_4d=_importer.import_4d
group_layers=_hierarchy.group_layers
ADDON_VERSION='1.1.0'

ROOT_MODES=[('AUTO','Auto','A root Empty is a container; other roots form layer 0'),
            ('ROOT','Root is layer 0','Count the root as W=0, including Empty'),
            ('CHILDREN','Children are layer 0','Use the root only as a container')]

class MYENGINE_OT_export_4d(bpy.types.Operator,ExportHelper):
    bl_idname='export_scene.myengine_4d'
    bl_label='Export MyEngine 4D 1.1.0'
    bl_options={'PRESET'}
    filename_ext='.4d'
    filter_glob:StringProperty(default='*.4d',options={'HIDDEN'})
    spacing:FloatProperty(name='W layer spacing',default=.1,min=1e-30,max=1e6,precision=6)
    root_mode:EnumProperty(name='Root',items=ROOT_MODES,default='AUTO')
    modifiers:BoolProperty(name='Apply modifiers',default=True)
    include_hidden:BoolProperty(name='Include hidden geometry',default=False)
    @classmethod
    def poll(cls,context):return context.active_object is not None and context.mode=='OBJECT'
    def invoke(self,context,event):
        self.spacing=context.scene.myengine4d_spacing;self.root_mode=context.scene.myengine4d_root_mode
        if context.active_object.get('myengine4d_imported',False):
            self.spacing=context.active_object.get('myengine4d_spacing',self.spacing)
            self.root_mode='CHILDREN'
        if not self.filepath:self.filepath=bpy.path.clean_name(context.active_object.name)+'.4d'
        return ExportHelper.invoke(self,context,event)
    def draw(self,context):
        layout=self.layout;layout.label(text='Root: '+context.active_object.name)
        layout.prop(self,'spacing');layout.prop(self,'root_mode');layout.prop(self,'modifiers');layout.prop(self,'include_hidden')
        layout.label(text='Deeper child = next W layer')
    def execute(self,context):
        try:
            layers,triangles=export_hierarchy(context,context.active_object,self.filepath,self.spacing,self.root_mode,self.modifiers,self.include_hidden)
            self.report({'INFO'},f'Exported {layers} W layers, {triangles} triangles')
            return {'FINISHED'}
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'},'MyEngine 4D '+ADDON_VERSION+': '+str(ex));return {'CANCELLED'}

class MYENGINE_OT_import_4d(bpy.types.Operator,ImportHelper):
    bl_idname='import_scene.myengine_4d'
    bl_label='Import MyEngine 4D 1.1.0'
    bl_description='Load a .4d file as editable meshes, one child level per W layer'
    bl_options={'REGISTER','UNDO'}
    filename_ext='.4d'
    filter_glob:StringProperty(default='*.4d',options={'HIDDEN'})
    @classmethod
    def poll(cls,context):return context.mode=='OBJECT'
    def draw(self,context):
        self.layout.label(text='W spacing is read from the file (default 0.1).')
        self.layout.label(text='One editable mesh per W layer.')
    def execute(self,context):
        try:
            root,layers,triangles=import_4d(context,self.filepath)
            self.report({'INFO'},f'Imported {layers} W layers, {triangles} triangles')
            return {'FINISHED'}
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'},'MyEngine 4D '+ADDON_VERSION+': '+str(ex));return {'CANCELLED'}

class MYENGINE_OT_child_layer(bpy.types.Operator):
    bl_idname='object.myengine_child_layer'
    bl_label='Duplicate as child layer'
    bl_description='Copy the active mesh as its child; its depth becomes the next W layer'
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):return context.mode=='OBJECT' and context.active_object is not None and context.active_object.type=='MESH'
    def execute(self,context):
        parent=context.active_object;matrix=parent.matrix_world.copy()
        child=parent.copy();child.data=parent.data.copy();child.animation_data_clear()
        child.name=parent.name+'_W';context.collection.objects.link(child)
        child.parent=parent;child.matrix_world=matrix
        for obj in context.selected_objects:obj.select_set(False)
        child.select_set(True);context.view_layer.objects.active=child
        return {'FINISHED'}

class MYENGINE_PT_4d(bpy.types.Panel):
    bl_label='MyEngine 4D 1.1.0';bl_idname='MYENGINE_PT_4d'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='MyEngine'
    def draw(self,context):
        layout=self.layout
        layout.operator('import_scene.myengine_4d',text='Import .4d',icon='IMPORT')
        root=context.active_object
        mode=context.scene.myengine4d_root_mode
        if root and root.get('myengine4d_imported',False):
            layout.prop(root,'["myengine4d_spacing"]',text='W layer spacing')
            layout.label(text='Imported root is a container')
            mode='CHILDREN'
        else:
            layout.prop(context.scene,'myengine4d_spacing');layout.prop(context.scene,'myengine4d_root_mode')
        if root:
            layout.label(text='Export root: '+root.name)
            try:layout.label(text=f'W layers: {len(group_layers(root,mode))}')
            except ValueError as ex:layout.label(text=str(ex),icon='ERROR')
        layout.operator('object.myengine_child_layer',icon='DUPLICATE')
        layout.operator('export_scene.myengine_4d',text='Export active hierarchy',icon='EXPORT')
        layout.label(text='Select the root before exporting.')

def export_menu(self,context):self.layout.operator(MYENGINE_OT_export_4d.bl_idname,text='MyEngine 4D 1.1.0 (.4d)')
def import_menu(self,context):self.layout.operator(MYENGINE_OT_import_4d.bl_idname,text='MyEngine 4D 1.1.0 (.4d)')
CLASSES=(MYENGINE_OT_import_4d,MYENGINE_OT_export_4d,MYENGINE_OT_child_layer,MYENGINE_PT_4d)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.myengine4d_spacing=FloatProperty(name='W layer spacing',default=.1,min=1e-30,max=1e6,precision=6)
    bpy.types.Scene.myengine4d_root_mode=EnumProperty(name='Root',items=ROOT_MODES,default='AUTO')
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    bpy.types.TOPBAR_MT_file_import.append(import_menu)
def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(import_menu)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    del bpy.types.Scene.myengine4d_spacing;del bpy.types.Scene.myengine4d_root_mode
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
if __name__=='__main__':register()

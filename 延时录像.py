bl_info = {
    "name" : "延时录像",
    "author" : "尐贤之辈のTENO",
    "description" : "延时录像",
    "blender" : (3, 6, 0),
    "version" : (1, 0, 0),
    "location" : "渲染 > 延时录像",
    "category" : "录像",
    "doc_url": "",
    "tracker_url": "https://space.bilibili.com/1729654169"
}

import bpy,gpu,os
from bpy.props import (
        IntProperty,
        BoolProperty,
        StringProperty,
        PointerProperty,
        FloatVectorProperty,
        FloatProperty,
        IntVectorProperty,
        EnumProperty,
        CollectionProperty
    )

try:
    import cv2
except:
    import subprocess,sys
    bpy.ops.wm.console_toggle()
    python_exe=os.path.join(sys.prefix,'bin','python.exe')
    subprocess.call([python_exe,'-m','ensurepip'])
    subprocess.call([python_exe,'-m','pip','install','opencv-python','-i','https://pypi.mirrors.ustc.edu.cn/simple/'])
    bpy.ops.wm.console_toggle()
    import cv2

is_start = False
timer = None
instance = None

class TIMELAPSE_OP(bpy.types.Operator):
    bl_idname = "timelapse.operation"
    bl_label = "TIMELAPSE_OP"
    
    def execute(self,context):
        Timelapse = context.scene.Timelapse
        global is_start
        is_start = not is_start
        
        global timer, instance
        if is_start:
            Timelapse.camera.hide_viewport = True
            instance = TIMELAPSE(Timelapse.camera, Timelapse.width, Timelapse.height, Timelapse.path, Timelapse.fps, Timelapse.rate, Timelapse.type)
            timer = bpy.app.timers.register(timelapse_operator)
        else:
            Timelapse.camera.hide_viewport = False
            bpy.app.timers.unregister(timelapse_operator)
            instance.cancel()
            instance = None
            timer = None
            self.report({"INFO"}, "录像已保存至 "+get_output_path(Timelapse.path))
        return {"FINISHED"}
            
def get_output_path(path):
    Timelapse = bpy.context.scene.Timelapse
    return os.path.join(path, os.path.splitext(bpy.path.basename(bpy.data.filepath))[0]+(".mp4" if Timelapse.type == "mp4" else ".avi"))
            
import mathutils
class TIMELAPSE:
    def __init__(self, camera, width, height, path, fps, rate, type):
        self.Timelapse = bpy.context.scene.Timelapse
        Timelapse = self.Timelapse
        self.context = bpy.context
        self.cam = camera
        self.width, self.height = width, height
        self.offscreen=gpu.types.GPUOffScreen(self.width, self.height)
        
        self.path = get_output_path(path)
        self.fps = fps
        self.rate = rate
        self.type = type
        
        self.anim_fps = bpy.context.scene.render.fps
        self.now = 0
        self.animation_gap = 1/self.anim_fps
        self.real_gap = 1/self.fps
        self.anim_duration = self.animation_gap*((Timelapse.end - Timelapse.start) if Timelapse.end>Timelapse.start else 1)
        self.is_inv = False
        
        if not os.access(path,os.F_OK):
            os.makedirs(path)
            
        fourcc = cv2.VideoWriter_fourcc(*'AVC1') if Timelapse.type == "mp4" else cv2.VideoWriter_fourcc(*'FFV1')
        self.out = cv2.VideoWriter(self.path, fourcc, fps, (width, height))
    
    def get_space_data(self):
        end_space_data = None
        end_region = None
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        end_space_data = space
                        break
                for region in area.regions:
                    if region.type == "WINDOW":
                        end_region = region
                        break
                break
        if end_space_data and end_region:
            return (end_space_data, end_region)
        else:
            return None
    
    def get_Transform(self):
        Timelapse = self.Timelapse
        
        if not Timelapse.trans_animation:
            return self.cam.matrix_world
        
        location = self.cam.location.copy()
        rotation_euler = self.cam.rotation_euler.copy()
        scale = mathutils.Vector((1.0, 1.0, 1.0))
        
        frame = int(self.now/self.animation_gap) + Timelapse.start
        fcurves = Timelapse.trans_animation.fcurves
        for fcurve in fcurves:
            if fcurve.data_path == "location":
                location[fcurve.array_index] = fcurve.evaluate(frame)
            elif fcurve.data_path == "rotation_euler":
                rotation_euler[fcurve.array_index] = fcurve.evaluate(frame)
        
        return mathutils.Matrix.LocRotScale(location, rotation_euler.to_quaternion(), scale)
    
    def cauculate_proj(self):
        Timelapse = self.Timelapse
        
        lens = self.cam.data.lens
        if Timelapse.lens_animation:
            frame = int(self.now/self.animation_gap) + Timelapse.start
            fcurves = Timelapse.lens_animation.fcurves
            for fcurve in fcurves:
                if fcurve.data_path == "lens":
                    lens = fcurve.evaluate(frame)
        lens_origin = self.cam.data.lens
        self.cam.data.lens = lens
        result = self.cam.calc_matrix_camera(
            bpy.context.evaluated_depsgraph_get(),
            x=self.width,
            y=self.height
            )
        self.cam.data.lens = lens_origin
        
        return result
    
    def render(self):
        space_data, region = self.get_space_data()
        view_matrix = self.get_Transform().inverted()
        projection_matrix = self.cauculate_proj()
        self.offscreen.draw_view3d(
            bpy.context.scene,
            bpy.context.view_layer,
            space_data,
            region,
            view_matrix,
            projection_matrix,
            do_color_management=True,
            draw_background=True
        )
        return self.offscreen.texture_color.read()
    
    def process_image(self,image):
        Timelapse = self.Timelapse
        return cv2.cvtColor(np.flipud(np.array(image, dtype=np.uint8).T.reshape(Timelapse.height, Timelapse.width, 4)),cv2.COLOR_BGR2RGB)
    
    def output(self,image):
        self.out.write(image)
    
    def next(self):
        Timelapse = self.Timelapse
        
        if Timelapse.looptype == "loop":
            self.now += self.real_gap
            self.now %= self.anim_duration
        elif Timelapse.looptype == "once":
            self.now += self.real_gap
            if self.now>self.anim_duration:
                self.now = self.anim_duration
        elif Timelapse.looptype == "pingpong":
            if self.is_inv:
                self.now -= self.real_gap
                if self.now<=0:
                    self.now = 0
                    self.is_inv = False
            else:
                self.now += self.real_gap
                if self.now>=self.anim_duration:
                    self.now = self.anim_duration
                    self.is_inv = True
                    
    def cancel(self):
        self.out.release()
        self.offscreen.free()
   
   
   
import numpy as np
def timelapse_operator():
    Timelapse = bpy.context.scene.Timelapse
    
    image = instance.process_image(instance.render())
    instance.output(image)
    
    instance.next()
    
    return (1/Timelapse.fps)*Timelapse.rate
    
    
    
    
    
    
    
    
def cam_filter(self, context):
    Timelapse = context.scene.Timelapse
    if not (Timelapse.camera and Timelapse.camera.type == 'CAMERA'):
        Timelapse.camera = None

class Vars(bpy.types.PropertyGroup):
    path : StringProperty(name = '路径', subtype='DIR_PATH', description="保存视频路径")
    fps : IntProperty(name = '帧率', description="视频帧率", min = 1, default = 30)
    rate : FloatProperty(name = '倍率', description="加速视频几倍", min = 0.01, default = 1)
    type : EnumProperty(
        name="视频类型",
        items=(
            ("mp4","MP4",""),
            ("avi", "AVI", ""),
        ),
        default="mp4"
    )
    
    width : IntProperty(name="宽度",description="视频宽度",default = 1920,min = 8)
    height : IntProperty(name="高度",description="视频高度",default = 1080,min = 8)
    
    camera : PointerProperty(
        type = bpy.types.Object,
        name="相机",
        description="延时摄影的相机",
        update=cam_filter
    )
    
    trans_animation : PointerProperty(
        type = bpy.types.Action,
        name="变换动画",
        description="相机变换动画（绝对时间，不受“倍率”参数影响）"
    )
    lens_animation : PointerProperty(
        type = bpy.types.Action,
        name="焦距动画",
        description="相机焦距动画（绝对时间，不受“倍率”参数影响）"
    )
    start : IntProperty(name="起始",description="动画起始位置",default = 1,min = 0)
    end : IntProperty(name="结束",description="动画结束位置",default = 250,min = 0)
    looptype : EnumProperty(
        name="循环类型",
        items=(
            ("loop","循环","循环播放"),
            ("once", "一次", "只播放一次，播放结束后锁定为最后一帧的动作"),
            ("pingpong", "乒乓", "顺序播放完后倒序播放，以此循环"),
        ),
        default="loop"
    )

    
class TIMELAPSE_PT_panel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_category = "延时录像"
    bl_idname = "TIMELAPSE_PT_panel"
    bl_label = "延时录像"
    
    def draw(self,context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False 
        
        Timelapse = context.scene.Timelapse
        
        col = layout.box().column()
        col.operator(TIMELAPSE_OP.bl_idname, icon = 'DOT' if is_start else 'PLAY', text = "停止录像" if is_start else "开始录像")
        if Timelapse.path and Timelapse.camera:
            col.enabled = True
        else:
            col.enabled = False
        
        col = layout.column()
        if Timelapse.path and Timelapse.camera:
            col.label(text="")
        else:
            col.label(text="[警告] 未选择"+(" 路径" if not Timelapse.path else "")+(" 相机" if not Timelapse.camera else ""))
        
        
        col = layout.box().column()
        col.column().label(text="相机参数：")
        col.enabled = not is_start
        col.prop(Timelapse,"camera")
        
        col = col.box()
        col.column().label(text="")
        col = col.column(align=True)
        col.prop(Timelapse,"trans_animation")
        col.prop(Timelapse,"lens_animation")
        col.prop(Timelapse,"looptype")
        col.column().label(text="")
        col = col.column(align=True)
        col.prop(Timelapse,"start")
        col.prop(Timelapse,"end")
        col.column().label(text="")
        
        
        col = layout.box().column()
        col.column().label(text="输出参数：")
        col.enabled = not is_start
        col.prop(Timelapse,"path")
        col = col.box().column()
        col.column().label(text="")
        col.prop(Timelapse,"type")
        col.column().label(text="")
        col = col.column(align=True)
        col.prop(Timelapse,"fps")
        col.prop(Timelapse,"rate")
        
        col = col.column(align=True)
        col.column().label(text="")
        col.prop(Timelapse,"width")
        col.prop(Timelapse,"height")
        col.column().label(text="")
    
    
    
    
    
CLASS_LIST = (
    TIMELAPSE_OP,
    Vars,
    TIMELAPSE_PT_panel,
)
def register():
    for i in CLASS_LIST:
        bpy.utils.register_class(i)
        
    bpy.types.Scene.Timelapse = bpy.props.PointerProperty(type=Vars)
    
def unregister():
    for i in CLASS_LIST:
        bpy.utils.unregister_class(i)
    
    del bpy.types.Scene.Timelapse
    
if __name__ == "__main__":
    register()
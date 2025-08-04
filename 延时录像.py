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

old = None
class TIMELAPSE_OP(bpy.types.Operator):
    bl_idname = "timelapse.operation"
    bl_label = "开始录像"
    bl_description = "开始录像"
    
    def execute(self,context):
        Timelapse = context.scene.Timelapse
        global is_start
        is_start = not is_start
        
        global timer, instance, old
        if is_start:
            Timelapse.camera.hide_viewport = True
            old = [Timelapse.camera, Timelapse.trans_animation, Timelapse.lens_animation]
            instance = TIMELAPSE(Timelapse.is_showoverlay, Timelapse.camera, Timelapse.trans_animation, Timelapse.lens_animation, Timelapse.looptype, Timelapse.start, Timelapse.end, Timelapse.process, Timelapse.is_continueanim,     Timelapse.path, Timelapse.is_overridefile, Timelapse.type, Timelapse.fps, Timelapse.rate, Timelapse.width, Timelapse.height)
            if not instance.is_init:
                old = None
                instance = None
                self.report({'WARNING'}, "实例创建失败")
                is_start = not is_start
                return {"FINISHED"}
            
            if Timelapse.is_continueanim:
                Timelapse.old_process = Timelapse.process
            Timelapse.is_pause = False
            timer = bpy.app.timers.register(timelapse_operator)
        else:
            if Timelapse.camera:
                Timelapse.camera.hide_viewport = False
            bpy.app.timers.unregister(timelapse_operator)
            instance.cancel()
            Timelapse.is_pause = False
            instance = None
            timer = None
            old = None
            self.report({"INFO"}, "录像已保存至 "+get_output_path(Timelapse.path, Timelapse.type, Timelapse.is_overridefile))
        return {"FINISHED"}
    
class TIMELAPSE_RELOADPROCESS(bpy.types.Operator):
    bl_idname = "timelapse.reloadprocess"
    bl_label = "还原"
    bl_description = "将“进度”选项还原至开始录制时的参数（仅在开始录制时勾选上“承接进度”时才生效，否则其将定位至上一次开启“承接进度”且开始录像时的参数）"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self,context):
        Timelapse = bpy.context.scene.Timelapse
        Timelapse.process = Timelapse.old_process
        
        return {"FINISHED"}
            
def get_output_path(path, type, is_overridefile):
    name_bef = os.path.splitext(bpy.path.basename(bpy.data.filepath))[0]
    suffix = ".mp4" if type == "mp4" else ".avi"
    count = 1
    
    path_end = os.path.join(path, name_bef + suffix)
    if not os.path.exists(path_end) or is_overridefile:
        return path_end
        
    extra = ""
    while True:
        count_lens = len(str(count))
        if count_lens<3:
            extra = "_"+ "0"*(3-count_lens) +str(count)
        else:
            extra = "_"+ str(count)
        
        path_end = os.path.join(path, name_bef + extra + suffix)
        if not os.path.exists(path_end):
            return path_end
        
        count+=1
           
import mathutils
import numpy as np
image_old = None 
class TIMELAPSE:
    def __init__(self, is_showoverlay, camera, trans_animation, lens_animation, looptype, start, end, process, is_continueanim,     path, is_overridefile, type, fps, rate, width, height):
        
        self.is_init = True
        if not os.access(path,os.F_OK):
            try:
                os.makedirs(path)
            except:
                self.is_init = False
                error("无法创建文件夹，请确认文件夹路径是否可被创建")
                return None
            
        self.Timelapse = bpy.context.scene.Timelapse
        Timelapse = self.Timelapse
        
        self.context = bpy.context
        
        self.op_time_gap = (1/fps)*rate
        
        self.is_showoverlay = is_showoverlay
        self.camera = camera
        self.trans_animation = trans_animation
        self.lens_animation = lens_animation
        self.looptype = looptype
        self.start = start
        self.end = end
        self.process = process
        self.is_continueanim = is_continueanim
        
        self.path = get_output_path(path, type, is_overridefile)
        self.type = type
        self.fps = fps
        self.rate = rate
        self.width, self.height = width, height
        
        self.offscreen=gpu.types.GPUOffScreen(self.width, self.height)
        
        self.anim_fps = bpy.context.scene.render.fps
        self.animation_gap = 1/self.anim_fps
        self.real_gap = 1/self.fps
        self.anim_duration = self.animation_gap*((self.end - self.start) if self.end>self.start else 1)
        
        self.is_inv = False
        
        if looptype == "pingpong":
            if process>0.5:
                self.now = (1-process)*2*self.anim_duration
            else:
                self.now = process*2*self.anim_duration
        else:
            self.now = process*self.anim_duration
            
        fourcc = cv2.VideoWriter_fourcc(*'AVC1') if type == "mp4" else cv2.VideoWriter_fourcc(*'FFV1')
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
        if not self.trans_animation:
            return self.camera.matrix_world
        
        location = self.camera.location.copy()
        rotation_euler = self.camera.rotation_euler.copy()
        scale = mathutils.Vector((1.0, 1.0, 1.0))
        
        frame = int(self.now/self.animation_gap) + self.start
        fcurves = self.trans_animation.fcurves
        for fcurve in fcurves:
            if fcurve.data_path == "location":
                location[fcurve.array_index] = fcurve.evaluate(frame)
            elif fcurve.data_path == "rotation_euler":
                rotation_euler[fcurve.array_index] = fcurve.evaluate(frame)
        
        return mathutils.Matrix.LocRotScale(location, rotation_euler.to_quaternion(), scale)
    
    def cauculate_proj(self):
        lens = self.camera.data.lens
        if self.lens_animation:
            frame = int(self.now/self.animation_gap) + self.start
            fcurves = self.lens_animation.fcurves
            for fcurve in fcurves:
                if fcurve.data_path == "lens":
                    lens = fcurve.evaluate(frame)
        lens_origin = self.camera.data.lens
        self.camera.data.lens = lens
        result = self.camera.calc_matrix_camera(
            bpy.context.evaluated_depsgraph_get(),
            x=self.width,
            y=self.height
            )
        self.camera.data.lens = lens_origin
        
        return result
    
    def render(self):
        if not (sp_re:=self.get_space_data()):
            return None
        space_data, region = sp_re
        view_matrix = self.get_Transform().inverted()
        projection_matrix = self.cauculate_proj()
        
        is_showoverlay = space_data.overlay.show_overlays
        space_data.overlay.show_overlays=self.is_showoverlay
            
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
        space_data.overlay.show_overlays = is_showoverlay
        return self.offscreen.texture_color.read()
    
    def process_image(self,image):
        return cv2.cvtColor(np.flipud(np.array(image, dtype=np.uint8).T.reshape(self.height, self.width, 4)),cv2.COLOR_BGR2RGB)
    
    def output(self,image):
        self.out.write(image)
    
    def next(self):
        if self.looptype == "loop":
            self.now += self.real_gap
            self.now %= self.anim_duration
        elif self.looptype == "once":
            self.now += self.real_gap
            if self.now>self.anim_duration:
                self.now = self.anim_duration
        elif self.looptype == "pingpong":
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
        global image_old
        self.out.release()
        image_old = None
        self.offscreen.free()
        
        Timelapse=self.Timelapse
        if self.is_continueanim:
            if self.looptype == "pingpong":
                if self.is_inv:
                    Timelapse.process = 1-((self.now / self.anim_duration)/2)
                else:
                    Timelapse.process = (self.now / self.anim_duration)/2
            else:
                Timelapse.process = self.now / self.anim_duration
   
def timelapse_operator():
    Timelapse = bpy.context.scene.Timelapse
        
    time_gap = instance.op_time_gap
        
    if Timelapse.is_pause:
        return time_gap
        
    def kill_proc(reason):
        bpy.ops.timelapse.operation()
        error(reason)
        
    err = ""
    if Timelapse.camera != old[0]:
        err += " 相机"
    if Timelapse.trans_animation != old[1]:
        err += " 变换动画"
    if Timelapse.lens_animation != old[2]:
        err += " 焦距动画"
        
    if err != "":
        kill_proc(f"无法识别{err} ，已终止录像")
        return None
    
    image_pre = instance.render()
    if image_pre:
        global image_old
        image = instance.process_image(image_pre)
        image_old = image
        instance.output(image)
    elif image_old is None:
        kill_proc("无法识别到3D视图，请先创建3D视图窗口或移动至有3D窗口的界面 ，已终止录像")
        return None
    else:
        instance.output(image_old)
    
    instance.next()
    
    return time_gap
    
    
    
    
    
    
    
    
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
    process : FloatProperty(name="进度",description="动画进度（注：\"乒乓\"的阈值是其正反播放完成为基准）",default = 0,soft_min = 0,soft_max = 1, subtype = "FACTOR")
    looptype : EnumProperty(
        name="循环类型",
        items=(
            ("loop","循环","循环播放"),
            ("once", "一次", "只播放一次，播放结束后锁定为最后一帧的动作"),
            ("pingpong", "乒乓", "顺序播放完后倒序播放，以此循环"),
        ),
        default="loop"
    )
    is_overridefile : BoolProperty(
        name="覆盖文件",
        description="是否覆盖同名文件",
        default = True)
    is_showoverlay : BoolProperty(
        name="显示叠加层",
        description="是否显示叠加层",
        default = True)
    is_continueanim : BoolProperty(
        name="承接进度",
        description="若勾选，在录像结束后会让“进度”选项记录相机动画结束时的时间以在下一次录像时承接上一次的相机动画进度",
        default = False)

    old_process : FloatProperty(default = 0)
    
    is_pause : BoolProperty(
        name="暂停",
        description="暂时停止录制，再次点击即可恢复录制（即继续在视频文件后追加录制结果）",
        default = False)
    
class TIMELAPSE_PT_panel(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_category = "延时录像"
    bl_idname = "TIMELAPSE_PT_panel"
    bl_label = "延时录像"
    
    def draw(self,context):
        layout = self.layout
        
        Timelapse = context.scene.Timelapse
        
        col = layout.box().row(align = True)
        col.operator(TIMELAPSE_OP.bl_idname, icon = 'DOT' if is_start else 'PLAY', text = "停止录像" if is_start else "开始录像")
        col1 = col.row()
        col1.enabled = is_start
        col1.prop(Timelapse, "is_pause", text = "", icon="REC")
        if Timelapse.path and Timelapse.camera:
            col.enabled = True
        else:
            col.enabled = False
        
        col = layout.column()
        if Timelapse.path and Timelapse.camera:
            col.label(text="")
        else:
            col.label(text="[警告] 未选择"+(" 路径" if not Timelapse.path else "")+(" 相机" if not Timelapse.camera else ""))
        
        
        col = layout.column()
        col.use_property_split = False
        col.use_property_decorate = True
        col.enabled = not is_start
        col.prop(Timelapse,"is_showoverlay",icon='OVERLAY')
        
        col = layout.box().column()
        col.use_property_split = True
        col.use_property_decorate = False
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
        col1 = col.row(align = True)
        col1.prop(Timelapse,"process")
        col1.operator(TIMELAPSE_RELOADPROCESS.bl_idname, icon = "LOOP_BACK", text = "")
        col.prop(Timelapse,"is_continueanim")
        col.column().label(text="")
        
        col = layout.box().column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.column().label(text="输出参数：")
        col.enabled = not is_start
        col.prop(Timelapse,"path")
        col.prop(Timelapse,"is_overridefile")
        
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
    
    
def error(message, title="错误", icon='ERROR'):
    def draw(self, context):
        self.layout.label(text=message)
    
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    
    
    
    
    
CLASS_LIST = (
    TIMELAPSE_OP,
    TIMELAPSE_RELOADPROCESS,
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
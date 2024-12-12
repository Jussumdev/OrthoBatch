bl_info = {
    "name": "OrthoBatch",
    "author": "Day Lane",
    "version": (1, 1),
    "blender": (4, 00, 0),
    "location": "View3D > Sidebar > OrthoBatch",
    "description": "Orthographic image exports for batch meshes",
    "warning": "",
    "wiki_url": "",
    "category": "3D View"}

import os
import sys
import bpy
import json
import mathutils
import copy
import math

from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator
from bpy.app.handlers import persistent

#region declare constants

VALID_IMPORT_EXTENSIONS = {
    '.glb',
    '.gltf',
    '.obj',
    '.fbx'
}

VALID_EXPORT_EXTENSIONS = {
    '.png',
    '.bmp',
    '.tif',
    '.tiff',
    '.targa',
    '.jpg',
    '.jpeg'
}

#endregion


#region declare variables

bpy.types.WindowManager.orthobatch_logtext = bpy.props.StringProperty(
    name="Most recent log text",
    description = "The most recent text from the ShowMessageBox log",
    default = ""
)
bpy.types.WindowManager.orthobatch_editingpage = bpy.props.EnumProperty(
    name="Page",
#    description = "Which page of settings for orthobatch panel are we editing right now",
    items=[
        ("import", "Import", ""),
        ("shooting", "Shooting", ""),
        ("export", "Export", ""),
    ],
    default = "import"
)
bpy.types.WindowManager.orthobatch_imgSize = bpy.props.IntProperty(
    name="Pixels per unit",
    description = "The number of pixels alocated to a single unit of size in export",
    default = 256
)
bpy.types.WindowManager.orthobatch_imgPadding = bpy.props.FloatProperty(
    name="Image padding",
    description = "Add extra units of space to the edges of the exported image",
    min = 0,
    max = 10,
    default = 0
)
bpy.types.WindowManager.orthobatch_sourcePath = bpy.props.StringProperty(
    name="Model source directory",
    description = "The base directory containing all models",
    default = ""
)
bpy.types.WindowManager.orthobatch_exportPath = bpy.props.StringProperty(
    name="Model export directory",
    description = "The base directory in which to export all pictures",
    default = ""
)
bpy.types.WindowManager.orthobatch_importMode = bpy.props.EnumProperty(
    name="Import mode",
    description = "How should we get the models to render?",
    items=[
        ("currentfile", "Objects in this file", "Export all objects in this blend file"),
        ("currentfile_selected", "Selected objects", "Export all objects in this blend file that are currently selected"),
        ("folder", "Import folder", "Import model files from a directory")
    ],
    default = "folder"
)
bpy.types.WindowManager.orthobatch_limitSearch = bpy.props.BoolProperty(
    name="Limit maximum models",
    description = "If true, limit the total number of models that can be imported at once",
    default = False
)
bpy.types.WindowManager.orthobatch_maxFiles = bpy.props.IntProperty(
    name="Max files",
    description = "Maximum number of files to import at once",
    default = 10,
    min = 1,
    max = 100
)
bpy.types.WindowManager.orthobatch_exportPathMode = bpy.props.EnumProperty(
    name="Export path mode",
    description = "How should the filepaths (after the source directory) be treated on export?",
    items=[
        ("flatten", "Flatten", "Export files directly into export folder"),
        ("keeppath", "Keep relative paths", "Export files into a subdirectory of export folder that matches their path in the source folder"),
        ("flatten_foldername", "Flatten, name after folder", "Export files directly into export folder, but name them after the folder they were found in"),
        ("flatten_pathname", "Flatten, name after full path", "Export files directly into export folder, but name them after the full path they were found in (starting from the end of the base import folder)")
    ],
    default = "flatten"
)
bpy.types.WindowManager.orthobatch_exportNameMode = bpy.props.EnumProperty(
    name="Filename suffix",
    description = "Where should the direction suffix be placed in the filename of exported images",
    items=[
        ("prepend", "Before file", "Suffix appears before filename (Z_example.png)"),
        ("append", "After file", "Suffix appears after filename (example_Z.png)")
    ],
    default = "append"
)
bpy.types.WindowManager.orthobatch_shootDirections = bpy.props.EnumProperty(
    name="Shoot Directions",
    options={'ENUM_FLAG'},
    items=[
        ("X", "Right side", "pos X axis"),
        ("-X", "Left side", "neg X axis"),
        ("Y", "Back", "pos Y axis"),
        ("-Y", "Front", "neg Y axis"),
        ("Z", "Top down", "pos Z axis"),
        ("-Z", "Bottom up", "neg Z axis"),
    ]
)
bpy.types.WindowManager.orthobatch_backCulling = bpy.props.BoolProperty(
    name="Backface Culling",
    description = "If true, omit any backward facing / inside facing triangles",
    default = False
)
bpy.types.WindowManager.orthobatch_imgBrightness = bpy.props.FloatProperty(
    name="Image brightness",
    description = "Total brightness of the exported image (HDR)",
    min = 0,
    max = 2,
    default = 1
)

#endregion
    
    

    
# Deselect all objects and return to object mode
@persistent
def reset():
    # https://blender.stackexchange.com/questions/174525/how-to-merge-all-vertices-by-distance-and-remove-all-inner-faces
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for s in bpy.context.selected_objects:
        s.select_set(False)
  

# https://blender.stackexchange.com/questions/109711/how-to-popup-simple-message-box-from-python-console
@persistent  
def ShowMessageBox(message = "", title = "ORTHOBATCH Log", icon = 'INFO'):
    def draw(self, context):
        self.layout.label(text=message)
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)
    bpy.types.WindowManager.orthobatch_logtext = message
    print("ShowMessage: "+message)


class ModelPath():
    
    def __init__(self, filename, filepath, sourcepathused):
        self.filename = filename
        self.name = filename[:filename.rfind('.')]
        self.extension = filename[filename.rfind('.')+1:]
        self.filepath = filepath
        sourcepathused = sourcepathused.strip('\\')
        self.subpath = filepath[
            len(sourcepathused) : filepath.find(filename)
        ]
        self.subpath = self.subpath.strip('\\')
        self.sourcepathused = sourcepathused
        self.pathminusfilename = os.path.join(sourcepathused, self.subpath)
        
    def __str__(self):
        return self.filepath
#        return self.filepath + " " + self.name + " " + self.subpath
    
    def __eq__(self, other):
        return (self.filepath.lower() == other.filepath.lower())
    
    # Sort by path length, then alphabetically
    def __lt__(self, other):
        selffoldercount = len(self.pathminusfilename.split(os.sep))
        otherfoldercount = len(other.pathminusfilename.split(os.sep))
        if (selffoldercount == otherfoldercount):
            return (self.filename.lower() < other.filename.lower())
        return (selffoldercount < otherfoldercount)
    
    def imageExportPath(self, direction, exportpath, exportpathmode, exportNameMode):
        subpathtrimmed = self.subpath
        if subpathtrimmed.endswith(os.sep):
            subpathtrimmed = subpathtrimmed[:-1]

        match exportpathmode:
            case "keeppath":
                return os.path.join(exportpath, subpathtrimmed, self.suffixName(direction, self.name, exportNameMode))
            case "flatten":
                return os.path.join(exportpath, self.suffixName(direction, self.name, exportNameMode))
            case "flatten_pathname":
                return os.path.join(exportpath, self.suffixName(direction, subpathtrimmed.replace(os.sep,'_') + "_" + self.name, exportNameMode))
            case "flatten_foldername":
                return os.path.join(exportpath, self.suffixName(direction, subpathtrimmed.split(os.sep)[-1], exportNameMode))
            
    def suffixName(self, suffix, name, exportNameMode):
        match exportNameMode:
            case "prepend":
                return suffix + '_' + name
            case "append":
                return name + '_' + suffix
    
    def tryImport(self):
        try:
            before_import_objects = set(bpy.context.scene.objects)
            before_import_active = bpy.context.active_object
            match self.extension:
                case "obj":
                    bpy.ops.wm.obj_import(
                        filepath = self.filepath,
                        use_split_objects=False,
                        use_split_groups=False
                    )
                case "gltf":
                    bpy.ops.import_scene.gltf(
                        filepath = self.filepath
                    )
                case "glb":
                    bpy.ops.import_scene.gltf(
                        filepath = self.filepath
                    )
                case "fbx":
                    bpy.ops.import_scene.fbx(
                        filepath = self.filepath
                    )
                case _:
                    return (None, "FAILED: improper file extension")
            bpy.context.view_layer.objects.active = before_import_active
            imported = list(set(bpy.context.scene.objects) - before_import_objects)
            if len(imported) < 1:
                return (None, "FAILED: No meshes found in imported object")
            elif len(imported) == 1:
                return (imported[0], "succeeded")
            else:
                with bpy.context.temp_override(active_object=imported[0], selected_objects=imported[1:]):
                    bpy.ops.object.join()
                    return (before_import_active, "succeeded")
        
        except Exception as error:
            return (None, "FAILED: "+str(error))

# Recursively get all model paths in the given folder 
# Returns a (possibly empty) list of dictionaries which each contain:
#   filename : the name (with extension) of the model
#   name : everything before the extension in the filename
#   extension : the file extension of the model
#   filepath : the full path of the model
#   subpath : the path to the model starting from the base path
@persistent
def getAllModelPaths(basepath, extensions):
    modelpaths = []
    extensions_tuple = tuple(extensions)
    for subdir, dirs, files in os.walk(basepath):
        for file in files:
            if file.endswith(extensions_tuple):
                modelpaths += [
                    ModelPath(
                        file,
                        os.path.join(basepath, subdir, file),
                        basepath
                    )
                ]
    return modelpaths

@persistent
def prepareuniversalrendersettings():
    bpy.context.scene.render.film_transparent = True
    if bpy.app.version < (4, 1, 0):
        # Legacy BLENDER EEVEE before 4.1 (https://devtalk.blender.org/t/blender-4-2-eevee-next-feedback/31813)
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
    else:
        bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
    
    worldmat = bpy.data.materials.get("WorldMat")
    if worldmat is None:
        worldmat = bpy.data.materials.new(name="WorldMat")
        
    w = bpy.data.worlds['World']
    w.use_nodes = False
    br = bpy.context.window_manager.orthobatch_imgBrightness
    w.color = mathutils.Color((br,br,br))
        

@persistent
def prepareorthocam():
    cam_data = bpy.data.cameras.new("Camera")
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    cam_obj.name = "OrthoCam"
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    
    cam_data.type = 'ORTHO'

    return cam_obj
    
  
@persistent  
def disposeobject(object):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.data.objects[object.name].select_set(True)
    bpy.ops.object.delete() 


@persistent
def camlookat(camera, point):
    direction = point - camera.location
    # point the cameras '-Z' and use its 'Y' as up
    rot_quat = direction.to_track_quat('-Z', 'Y')
    # assume we're using euler rotation
    camera.rotation_euler = rot_quat.to_euler()


# Position camera object (camera) with respect to target object (target) and shoot a shot
# direction in [ "X" / "Y" / "Z" ]
# save the image to path
@persistent
def shoottarget(camera, target, direction, path):
    target.select_set(True)
    bpy.ops.object.transform_apply(rotation = True, scale = True, location = True)
    target.select_set(False)

    target_bb_center = target.matrix_world @ (0.125 * sum((mathutils.Vector(b) for b in target.bound_box), mathutils.Vector()))
    
    camera.location = target_bb_center

    match direction:
        case "X":
            camera.location.x += (target.dimensions.x)
            target_bb_viewsize = (target.dimensions.y, target.dimensions.z)
        case "Y":
            camera.location.y += (target.dimensions.y)
            target_bb_viewsize = (target.dimensions.x, target.dimensions.z)
        case "Z":
            camera.location.z += (target.dimensions.z)
            target_bb_viewsize = (target.dimensions.x, target.dimensions.y)
        case "-X":
            camera.location.x -= (target.dimensions.x)
            target_bb_viewsize = (target.dimensions.y, target.dimensions.z)
        case "-Y":
            camera.location.y -= (target.dimensions.y)
            target_bb_viewsize = (target.dimensions.x, target.dimensions.z)
        case "-Z":
            camera.location.z -= (target.dimensions.z)
            target_bb_viewsize = (target.dimensions.x, target.dimensions.y)
            
    target_bb_viewsize = (
        target_bb_viewsize[0] + bpy.context.window_manager.orthobatch_imgPadding,
        target_bb_viewsize[1] + bpy.context.window_manager.orthobatch_imgPadding
    )
    
    camlookat(camera, target_bb_center)
    
    r = bpy.context.scene.render
    r.resolution_x = math.ceil(bpy.context.window_manager.orthobatch_imgSize * target_bb_viewsize[0])
    r.resolution_y = math.ceil(bpy.context.window_manager.orthobatch_imgSize * target_bb_viewsize[1])
    # camera.data.sensor_fit = "HORIZONTAL"
    # camera.data.ortho_scale = target_bb_viewsize[0]
    camera.data.sensor_fit = "AUTO"
    camera.data.ortho_scale = max(target_bb_viewsize[0], target_bb_viewsize[1])
    
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still = True)


# Set up an object and shoot it from all required directions, save the images, then clean up
#   object : the model object to shoot
#   cam : the camera to use
#   modelpath : the ModelPath object to use to save out the file
@persistent
def prepare_shoot_clean_object(object, cam, modelpath):
    # back up rendered object's backface culling state
    old_culling = [False] * len(object.data.materials)
    for i in range(len(object.data.materials)):
        old_culling[i] = object.data.materials[i].use_backface_culling if object.data.materials[i] != None else False
        if object.data.materials[i] != None:
            object.data.materials[i].use_backface_culling = bpy.context.window_manager.orthobatch_backCulling

    object.hide_render = False
    
    for dir in bpy.context.window_manager.orthobatch_shootDirections:
        exportpath = modelpath.imageExportPath(
            direction = dir,
            exportpath = bpy.context.window_manager.orthobatch_exportPath,
            exportpathmode = bpy.context.window_manager.orthobatch_exportPathMode,
            exportNameMode = bpy.context.window_manager.orthobatch_exportNameMode
        )
        
        print(exportpath)
        
        shoottarget(
            camera = cam,
            target = object,
            direction = dir,
            path = exportpath
        )
    
    object.hide_render = True
        
    # restore rendered object's backface culling state
    for i in range(len(object.data.materials)):
        if object.data.materials[i] != None:
            object.data.materials[i].use_backface_culling = old_culling[i]

def main():
    
    print("\n")
    print("Running ORTHOBATCH main func")
    
    # assertions
    if (len(bpy.context.window_manager.orthobatch_shootDirections) < 1):
        ShowMessageBox("ABORTING: Should have at least one photo direction enabled")
        return
    
    # validatations
    if not bpy.context.window_manager.orthobatch_sourcePath.endswith(os.sep):
        bpy.context.window_manager.orthobatch_sourcePath += os.sep

    # back up old objects and their render hidden state, then set them all invisible to render
    old_objs = list(bpy.context.scene.objects)
    old_objs_werehidden = [False] * len(old_objs)
    for oi in range(len(old_objs)):
        old_objs_werehidden[oi] = old_objs[oi].hide_render
        old_objs[oi].hide_render = True

    # prepare the orthographic camera
    print("Preparing orthocam...")  
    camera = prepareorthocam()
    
    # prepare the rendering settings
    print("Preparing universal render settings...")  
    prepareuniversalrendersettings()

    try:

        match(bpy.context.window_manager.orthobatch_importMode):

            case "folder":

                # find all models in folder
                print("Finding models...")
                modelpaths = getAllModelPaths(
                    bpy.context.window_manager.orthobatch_sourcePath,
                    VALID_IMPORT_EXTENSIONS
                )
                print("Found "+str(len(modelpaths))+" models...")
                modelpaths = sorted(modelpaths)

                # assertions
                if (len(modelpaths) < 1):
                    ShowMessageBox("ABORTING: Source directory has no valid model files (valid extensions are)")
                    return
                
                # validations
                if (bpy.context.window_manager.orthobatch_limitSearch):
                    count = min(bpy.context.window_manager.orthobatch_maxFiles, len(modelpaths))
                    print("Limiting to "+str(count)+" models...")
                    modelpaths = modelpaths[:count]
                
                
                importresults_fails = []
                importresults_successes = []
                importsuccesses = 0
                for path in modelpaths:
                    print("Attempting import of "+str(path))
                    
                    out = path.tryImport()
                    
                    if (out[0] == None):
                        importresults_fails += [(
                            path.filepath,
                            out[1]
                        )]
                        continue
                        
                    else:
                        importresults_successes += [(
                            path.filepath,
                            out[1]
                        )]
                        
                        prepare_shoot_clean_object(out[0], camera, path)
                        disposeobject(out[0])

                prnt = "Successfully imported " + str(importresults_successes) + " files:"
                for success in importresults_successes:
                    prnt += "\n" + success[0] + " " + success[1]

                if (len(importresults_fails) > 0):
                    prnt += "Failed to import " + str(importresults_fails) + " files:"
                    for failure in importresults_fails:
                        prnt += "\n" + failure[0] + " " + failure[1]
        
                ShowMessageBox(prnt)

            case "currentfile":
                local_objects_to_shoot = filter_meshes_from_objlist(list(bpy.context.selectable_objects))

            case "currentfile_selected":
                local_objects_to_shoot = filter_meshes_from_objlist(list(bpy.context.selected_objects))

        if (bpy.context.window_manager.orthobatch_importMode != "folder"):
            for obj in local_objects_to_shoot:
                if obj == None or obj.type != 'MESH':
                    continue
                name_with_temp_suffix = obj.name + '.standin'
                print(name_with_temp_suffix)
                no_import_modelpath = ModelPath(name_with_temp_suffix, name_with_temp_suffix, bpy.context.window_manager.orthobatch_sourcePath)
                prepare_shoot_clean_object(obj, camera, no_import_modelpath)

    except Exception as e:
        ShowMessageBox(f"An error occurred: {e}")

    # restore old objects' hidden state
    for oi in range(len(old_objs)):
        old_objs[oi].hide_render = old_objs_werehidden[oi]

    # clean up the orthographic camera
    disposeobject(camera)

@persistent
def filter_meshes_from_objlist(objlist):
    listlen = len(objlist)
    for i in range(listlen):
        j = listlen - i - 1
        obj = objlist[j]
        if obj == None or obj.type != 'MESH':
            objlist.pop(j)
    return objlist
    
# region UI functions  
class ORTHOBATCH_func_execute(bpy.types.Operator):
    bl_idname = "orthobatch.func_execute"
    bl_label = "Execute"

    def execute(self, context):
        main()
        return {'FINISHED'}

class ORTHOBATCH_func_resetimportpath(bpy.types.Operator):
    bl_idname = "orthobatch.func_resetimportpath"
    bl_label = "Reset Import Path"
    def execute(self, context):
        bpy.context.window_manager.orthobatch_sourcePath = bpy.path.abspath("//")
        return {'FINISHED'}
    
class ORTHOBATCH_func_resetexportpath(bpy.types.Operator):
    bl_idname = "orthobatch.func_resetexportpath"
    bl_label = "Reset Export Path"

    def execute(self, context):
        bpy.context.window_manager.orthobatch_exportPath = bpy.path.abspath("//")
        return {'FINISHED'}

class ORTHOBATCH_func_browseForImportDirectory(Operator, ImportHelper):
    bl_idname = "orthobatch.func_browseforimportdirectory"
    bl_label = "Select source directory"
    bl_options = {'REGISTER'}

    # Define this to tell 'fileselect_add' that we want a directoy
    directory: StringProperty(
        name="Source directory",
        description="Source directory"
        # subtype='DIR_PATH' is not needed to specify the selection mode.
        # But this will be anyway a directory path.
    )
    
    # Filters folders
    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"}
    )

    filter_glob: StringProperty(
        default='*' + ';*'.join(VALID_IMPORT_EXTENSIONS),
        options={'HIDDEN'}
    )

    def execute(self, context):
        bpy.context.window_manager.orthobatch_sourcePath = os.path.split(self.filepath)[0] + os.sep
        return {'FINISHED'}
    
class ORTHOBATCH_func_browseForExportDirectory(Operator, ImportHelper):
    bl_idname = "orthobatch.func_browseforexportdirectory"
    bl_label = "Select destination directory"
    bl_options = {'REGISTER'}

    # Define this to tell 'fileselect_add' that we want a directoy
    directory: StringProperty(
        name="Destination directory",
        description="Destination directory"
        # subtype='DIR_PATH' is not needed to specify the selection mode.
        # But this will be anyway a directory path.
    )

    # Filters folders
    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"}
    )
    
    filter_glob: StringProperty(
        # default='*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.targa', for example
        default='*' + ';*'.join(VALID_EXPORT_EXTENSIONS),
        options={'HIDDEN'}
    )

    def execute(self, context):
        bpy.context.window_manager.orthobatch_exportPath = os.path.split(self.filepath)[0] + os.sep
        return {'FINISHED'}

class ORTHOBATCH_PT_panel(bpy.types.Panel):
    bl_label = "OrthoBatch"
    bl_category = "OrthoBatch"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        sectionspace = 1.5
        layout = self.layout
        
        layout.operator(ORTHOBATCH_func_execute.bl_idname)
        
        # layout.separator(factor=sectionspace)
        r = layout.row()
        r.prop(context.window_manager, "orthobatch_editingpage", expand=True)
        layout.separator(factor=sectionspace)
        layout.separator(factor=sectionspace)
        
        match(context.window_manager.orthobatch_editingpage):

            case "import":
                
                r = layout.row()
                r.prop(context.window_manager, "orthobatch_importMode", expand=True)

                match(context.window_manager.orthobatch_importMode):
                    
                    case "folder":
                        b = layout.box()
                        r = b.row()
                        r.label(text="Import models from folder:")
                        # r.operator(ORTHOBATCH_func_resetimportpath.bl_idname, text="reset")
                        b.prop(context.window_manager, "orthobatch_sourcePath", text="", expand=True, icon_only =True)
                        r.operator(ORTHOBATCH_func_browseForImportDirectory.bl_idname, text="browse")
                        r = b.row()
                        r.label(text="(valid filetypes: "+", ".join(VALID_IMPORT_EXTENSIONS)+")")

                        layout.prop(context.window_manager, "orthobatch_limitSearch")
                        if (bpy.context.window_manager.orthobatch_limitSearch):
                            r = layout.row()
                            r.label(text="Maximum imported models:")
                            r.prop(context.window_manager, "orthobatch_maxFiles", slider=True, text="")
                    
                    case "currentfile":
                        r = layout.row()
                        meshes_in_file = len(filter_meshes_from_objlist(list(bpy.context.selectable_objects)))
                        r.label(text=(str(meshes_in_file) + " meshes visible and selectable"))

                    case "currentfile_selected":
                        r = layout.row()
                        meshes_selected = len(filter_meshes_from_objlist(list(bpy.context.selected_objects)))
                        r.label(text=(str(meshes_selected) + " meshes selected"))
            
            
            case "shooting":
                
                r = layout.row()
                r.label(text="Shoot directions:")
                r.props_enum(context.window_manager, "orthobatch_shootDirections")
                
                layout.prop(context.window_manager, "orthobatch_backCulling")
                r = layout.row()
                r.label(text="Image brightness:")
                r.prop(context.window_manager, "orthobatch_imgBrightness", text="", slider=True)
                
            case "export":
                
                b = layout.box()
                r = b.row()
                r.label(text="Export path:")
                # r.operator(ORTHOBATCH_func_resetexportpath.bl_idname, text="reset")
                b.prop(context.window_manager, "orthobatch_exportPath", text="", expand=True)
                r.operator(ORTHOBATCH_func_browseForExportDirectory.bl_idname, text="browse")

                r = layout.row()
                r.label(text="Filename suffix (currently " + context.window_manager.orthobatch_exportNameMode + ")")
                r.prop_menu_enum(
                    context.window_manager,
                    "orthobatch_exportNameMode"
                )
                
                r = layout.row()
                r.label(text="Export path mode:")
                r.props_enum(
                    context.window_manager,
                    "orthobatch_exportPathMode"
                )
                
                r = layout.row()
                r.label(text="Pixels per unit:")
                r.prop(context.window_manager, "orthobatch_imgSize", text="")

                r = layout.row()
                r.label(text="Image padding (units):")
                r.prop(context.window_manager, "orthobatch_imgPadding", slider=True, text="")
                
                b = layout.box()
                b.label(text="File format:")
                b.props_enum(bpy.context.scene.render.image_settings, "file_format")
                r = b.row()
                r.label(text="Color mode:")
                r.props_enum(
                    bpy.context.scene.render.image_settings,
                    "color_mode"
#                    property_highlight="color_mode",
                )
                r = b.row()
                r.label(text="Compression:")
                r.prop(bpy.context.scene.render.image_settings, "compression", text="")
                r = b.row()
                r.label(text="color depth:")
                r.props_enum(
                    bpy.context.scene.render.image_settings,
                    "color_depth"
                )

        #showing as one truncated row right now
        # if (len(bpy.types.WindowManager.orthobatch_logtext) > 0):
        #     r = layout.separator(factor=sectionspace)
        #     r = layout.row()
        #     r.label(text="Log:")
        #     r = layout.row()
        #     r.label(text=bpy.types.WindowManager.orthobatch_logtext)
                
                
        

classes = [
    ORTHOBATCH_PT_panel,
    ORTHOBATCH_func_execute,
    ORTHOBATCH_func_resetexportpath,
    ORTHOBATCH_func_resetimportpath,
    ORTHOBATCH_func_browseForImportDirectory,
    ORTHOBATCH_func_browseForExportDirectory
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

#endregion


if __name__ == "__main__":
    register()
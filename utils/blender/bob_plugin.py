import os
import os.path
import bpy
import bmesh
import struct
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper, axis_conversion

from contextlib import contextmanager
from collections import defaultdict
import math

bl_info = {
	"name": "BOB format",
	"description": "Import-Export BombSquad .bob files.",
	"author": "Mrmaxmeier",
	"version": (0, 0),
	"blender": (2, 77, 0),
	"location": "File > Import-Export",
	"warning": "",
	"wiki_url": "",
	"category": "Import-Export"
}

BOB_FILE_ID = 45623
COB_FILE_ID = 13466

"""
.BOB File Structure:

MAGIC 45623 (I)
meshFormat  (I)
vertexCount (I)
faceCount   (I)
VertexObject x vertexCount (fff HH hhh xx)
index x faceCount*3 (b / H)

struct VertexObjectFull {
	float position[3];
	bs_uint16 uv[2]; // normalized to 16 bit unsigned ints 0 - 65535
	bs_sint16  normal[3]; // normalized to 16 bit signed ints -32768 - 32767
	bs_uint8 _padding[2];
};


.COB File Structure:

MAGIC 13466 (I)
vertexCount (I)
faceCount   (I)
vertexPos x vertexCount (fff)
index x faceCount*3 (I)
normal x faceCount (fff)
"""


@contextmanager
def to_bmesh(mesh, save=False):
	try:
		bm = bmesh.new()
		bm.from_mesh(mesh)
		bm.faces.ensure_lookup_table()
		yield bm
	finally:
		if save:
			bm.to_mesh(mesh)
		bm.free()
		del bm


def clamp(val, minimum=0, maximum=1):
	if max(min(val, maximum), minimum) != val:
		print("clamped", val, "to", max(min(val, maximum), minimum))
	return max(min(val, maximum), minimum)


class ImportBOB(bpy.types.Operator, ImportHelper):
	"""Load an Bombsquad Mesh file"""
	bl_idname = "import_mesh.bob"
	bl_label = "Import Bombsquad Mesh"
	filename_ext = ".bob"
	filter_glob = StringProperty(
		default="*.bob",
		options={'HIDDEN'},
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=('filter_glob',))
		mesh = load(self, context, **keywords)
		if not mesh:
			return {'CANCELLED'}

		scene = bpy.context.scene
		obj = bpy.data.objects.new(mesh.name, mesh)
		scene.objects.link(obj)
		scene.objects.active = obj
		obj.select = True
		obj.matrix_world = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
		scene.update()
		return {'FINISHED'}


class ExportBOB(bpy.types.Operator, ExportHelper):
	"""Save an Bombsquad Mesh file"""
	bl_idname = "export_mesh.bob"
	bl_label = "Export Bombsquad Mesh"
	filter_glob = StringProperty(
		default="*.bob",
		options={'HIDDEN'},
	)
	check_extension = True
	filename_ext = ".bob"

	triangulate = BoolProperty(
		name="Force Triangulation",
		description="force triangulation of .bob files",
		default=False,
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=('filter_glob',))
		return save(self, context, **keywords)


def import_bob_menu(self, context):
	self.layout.operator(ImportBOB.bl_idname, text="Bombsquad Mesh (.bob)")


def export_bob_menu(self, context):
	self.layout.operator(ExportBOB.bl_idname, text="Bombsquad Mesh (.bob)")


class ImportCOB(bpy.types.Operator, ImportHelper):
	"""Load an Bombsquad Collision Mesh"""
	bl_idname = "import_mesh.cob"
	bl_label = "Import Bombsquad Collision Mesh"
	filename_ext = ".cob"
	filter_glob = StringProperty(
		default="*.cob",
		options={'HIDDEN'},
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=('filter_glob',))
		mesh = loadcob(self, context, **keywords)
		if not mesh:
			return {'CANCELLED'}

		scene = bpy.context.scene
		obj = bpy.data.objects.new(mesh.name, mesh)
		scene.objects.link(obj)
		scene.objects.active = obj
		obj.select = True
		obj.draw_type = "SOLID"
		obj.matrix_world = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
		scene.update()
		return {'FINISHED'}


class ExportCOB(bpy.types.Operator, ExportHelper):
	"""Save an Bombsquad Collision Mesh file"""
	bl_idname = "export_mesh.cob"
	bl_label = "Export Bombsquad Collision Mesh"
	filter_glob = StringProperty(
		default="*.cob",
		options={'HIDDEN'},
	)
	check_extension = True
	filename_ext = ".cob"

	triangulate = BoolProperty(
		name="Force Triangulation",
		description="force triangulation of .cob files",
		default=False,
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=('filter_glob',))
		return savecob(self, context, **keywords)


def import_cob_menu(self, context):
	self.layout.operator(ImportCOB.bl_idname, text="Bombsquad Collision Mesh (.cob)")


def export_cob_menu(self, context):
	self.layout.operator(ExportCOB.bl_idname, text="Bombsquad Collision Mesh (.cob)")


def import_leveldefs(self, context):
	self.layout.operator(ImportLevelDefs.bl_idname, text="Bombsquad Level Definitions (.py)")


def register():
	bpy.utils.register_module(__name__)
	bpy.types.INFO_MT_file_import.append(import_bob_menu)
	bpy.types.INFO_MT_file_export.append(export_bob_menu)
	bpy.types.INFO_MT_file_import.append(import_cob_menu)
	bpy.types.INFO_MT_file_export.append(export_cob_menu)
	bpy.types.INFO_MT_file_import.append(import_leveldefs)


def unregister():
	bpy.utils.unregister_module(__name__)
	bpy.types.INFO_MT_file_import.remove(import_bob_menu)
	bpy.types.INFO_MT_file_export.remove(export_bob_menu)
	bpy.types.INFO_MT_file_import.remove(import_cob_menu)
	bpy.types.INFO_MT_file_export.remove(export_cob_menu)


def load(operator, context, filepath):
	filepath = os.fsencode(filepath)
	bs_dir = os.path.dirname(os.path.dirname(filepath))
	texname = os.path.basename(filepath).rstrip(b".bob") + b".dds"
	texpath = os.path.join(bs_dir, b"textures", texname)
	print(texpath)
	has_texture = os.path.isfile(texpath)
	print("texture file found:", has_texture)

	with open(filepath, 'rb') as file:
		def readstruct(s):
			tup = struct.unpack(s, file.read(struct.calcsize(s)))
			return tup[0] if len(tup) == 1 else tup

		assert readstruct("I") == BOB_FILE_ID
		meshFormat = readstruct("I")
		assert meshFormat in [0, 1]

		vertexCount = readstruct("I")
		faceCount = readstruct("I")

		verts = []
		faces = []
		edges = []
		indices = []
		uv_list = []
		normal_list = []

		for i in range(vertexCount):
			vertexObj = readstruct("fff HH hhh xx")
			position = (vertexObj[0], vertexObj[1], vertexObj[2])
			uv = (vertexObj[3] / 65535, vertexObj[4] / 65535)
			normal = (vertexObj[5] / 32767, vertexObj[6] / 32767, vertexObj[7] / 32767)
			verts.append(position)
			uv_list.append(uv)
			normal_list.append(normal)

		for i in range(faceCount * 3):
			if meshFormat == 0:
				# MESH_FORMAT_UV16_N8_INDEX8
				indices.append(readstruct("b"))
			elif meshFormat == 1:
				# MESH_FORMAT_UV16_N8_INDEX16
				indices.append(readstruct("H"))

		for i in range(faceCount):
			faces.append((indices[i * 3], indices[i * 3 + 1], indices[i * 3 + 2]))

		bob_name = bpy.path.display_name_from_filepath(filepath)
		mesh = bpy.data.meshes.new(name=bob_name)
		mesh.from_pydata(verts, edges, faces)

		with to_bmesh(mesh, save=True) as bm:
			for i, face in enumerate(bm.faces):
				for vi, vert in enumerate(face.verts):
					vert.normal = normal_list[vert.index]

		uv_texture = mesh.uv_textures.new("uv_map")
		texture = None
		if has_texture:
			texture = bpy.data.images.load(texpath)
			uv_texture.data[0].image = texture

		with to_bmesh(mesh, save=True) as bm:
			uv_layer = bm.loops.layers.uv.verify()
			tex_layer = bm.faces.layers.tex.verify()
			for i, face in enumerate(bm.faces):
				for vi, vert in enumerate(face.verts):
					uv = uv_list[vert.index]
					uv = (uv[0], 1 - uv[1])
					face.loops[vi][uv_layer].uv = uv
					if texture:
						face[tex_layer].image = texture

		mesh.validate()
		mesh.update()

		return mesh


class Verts:
	_verts = []
	_by_blender_index = defaultdict(list)

	def get(self, coords, normal, blender_index, uv=None):
		instance = Vert(coords=coords, normal=normal, uv=uv)
		for other in self._by_blender_index[blender_index]:
			if instance.simmilar(other):
				return other
		self._by_blender_index[blender_index].append(instance)
		instance.index = len(self._verts)
		self._verts.append(instance)
		return instance

	def calc(self):
		return

	def __len__(self):
		return len(self._verts)

	def __iter__(self):
		return iter(self._verts)

def vec_similar(v1, v2):
	return (v1-v2).length < 0.01

class Vert:
	def __init__(self, coords, normal, uv):
		self.coords = coords
		self.normal = normal
		self.uv = uv

	def simmilar(self, other):
		is_similar = vec_similar(self.coords, other.coords)
		is_similar = is_similar and vec_similar(self.normal, other.normal)
		if self.uv and other.uv:
			is_similar = is_similar and vec_similar(self.uv, other.uv)
		return is_similar

def save(operator, context, filepath, triangulate, check_existing):
	print("exporting", filepath)
	global_matrix = axis_conversion(to_forward='-Z', to_up='Y').to_4x4()
	scene = context.scene
	obj = scene.objects.active
	mesh = obj.to_mesh(scene, True, 'PREVIEW')
	mesh.transform(global_matrix * obj.matrix_world)  # inverse transformation

	if triangulate or any([len(face.vertices) != 3 for face in mesh.tessfaces]):
		print("triangulating...")
		with to_bmesh(mesh, save=True) as bm:
			bmesh.ops.triangulate(bm, faces=bm.faces)
		mesh.update(calc_edges=True, calc_tessface=True)

	filepath = os.fsencode(filepath)

	with open(filepath, 'wb') as file:

		def writestruct(s, *args):
			file.write(struct.pack(s, *args))

		writestruct('I', BOB_FILE_ID)
		writestruct('I', 1)  # MESH_FORMAT_UV16_N8_INDEX16

		verts = Verts()
		faces = []
		with to_bmesh(mesh) as bm:
			uv_layer = None
			if len(bm.loops.layers.uv) > 0:
				uv_layer = bm.loops.layers.uv[0]
			for i, face in enumerate(bm.faces):
				faceverts = []
				for vi, vert in enumerate(face.verts):
					uv = face.loops[vi][uv_layer].uv if uv_layer else None
					v = verts.get(coords=vert.co, normal=vert.normal, uv=uv, blender_index=vert.index)
					faceverts.append(v)
				faces.append(faceverts)

			print("verts:", len(verts))
			print("faces:", len(faces))
			writestruct('I', len(verts))
			writestruct('I', len(faces))

			for vert in verts:
				writestruct('fff', *vert.coords)
				if vert.uv:
					uv = vert.uv
					writestruct('HH', int(clamp(uv[0]) * 65535), int((1 - clamp(uv[1])) * 65535))
				else:
					writestruct('HH', 0, 0)
				normal = tuple(map(lambda n: int(clamp(n, -1, 1) * 32767), vert.normal))
				writestruct('hhh', *normal)
				writestruct('xx')

			for face in faces:
				assert len(face) == 3
				for vert in face:
					writestruct('H', vert.index)

	return {'FINISHED'}


def loadcob(operator, context, filepath):
	with open(os.fsencode(filepath), 'rb') as file:
		def readstruct(s):
			tup = struct.unpack(s, file.read(struct.calcsize(s)))
			return tup[0] if len(tup) == 1 else tup

		assert readstruct("I") == COB_FILE_ID

		vertexCount = readstruct("I")
		faceCount = readstruct("I")

		verts = []
		faces = []
		edges = []
		indices = []

		for i in range(vertexCount):
			vertexObj = readstruct("fff")
			position = (vertexObj[0], vertexObj[1], vertexObj[2])
			verts.append(position)

		for i in range(faceCount * 3):
			indices.append(readstruct("I"))

		for i in range(faceCount):
			faces.append((indices[i * 3], indices[i * 3 + 1], indices[i * 3 + 2]))

		bob_name = bpy.path.display_name_from_filepath(filepath)
		mesh = bpy.data.meshes.new(name=bob_name)
		mesh.from_pydata(verts, edges, faces)

		mesh.validate()
		mesh.update()

		return mesh


def savecob(operator, context, filepath, triangulate, check_existing):
	print("exporting", filepath)
	global_matrix = axis_conversion(to_forward='-Z', to_up='Y').to_4x4()
	scene = context.scene
	obj = scene.objects.active
	mesh = obj.to_mesh(scene, True, 'PREVIEW')
	mesh.transform(global_matrix * obj.matrix_world)  # inverse transformation

	if triangulate or any([len(face.vertices) != 3 for face in mesh.tessfaces]):
		print("triangulating...")
		with to_bmesh(mesh, save=True) as bm:
			bmesh.ops.triangulate(bm, faces=bm.faces)
		mesh.update(calc_edges=True, calc_tessface=True)

	with open(os.fsencode(filepath), 'wb') as file:

		def writestruct(s, *args):
			file.write(struct.pack(s, *args))

		writestruct('I', COB_FILE_ID)
		writestruct('I', len(mesh.vertices))
		writestruct('I', len(mesh.tessfaces))

		for i, vert in enumerate(mesh.vertices):
			writestruct('fff', *vert.co)

		for face in mesh.tessfaces:
			assert len(face.vertices) == 3
			for vertid in face.vertices:
				writestruct('I', vertid)

		for face in mesh.tessfaces:
			writestruct('fff', *face.normal)

	return {'FINISHED'}



class ImportLevelDefs(bpy.types.Operator, ImportHelper):
	"""Load an Bombsquad Level Defs"""
	bl_idname = "import_bombsquad.leveldefs"
	bl_label = "Import Bombsquad Level Definitions"
	filename_ext = ".py"
	filter_glob = StringProperty(
		default="*.py",
		options={'HIDDEN'},
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=('filter_glob',))
		print("executing", keywords["filepath"])
		data = {}
		with open(os.fsencode(keywords["filepath"]), "r") as file:
			exec(file.read(), data)
		del data["__builtins__"]
		from pprint import pprint
		pprint(data)
		if "points" not in data or "boxes" not in data:
			return {'CANCELLED'}

		scene = bpy.context.scene

		points_obj = bpy.data.objects.new("points", None)
		points_obj.matrix_world = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
		scene.objects.link(points_obj)
		scene.objects.active = points_obj
		scene.update()
		points_obj.layers = tuple([i == 1 for i in range(20)])


		for key, pos in data["points"].items():
			empty = bpy.data.objects.new(key, None)
			empty.location = pos[:3]
			empty.empty_draw_size = 0.45
			empty.parent = points_obj
			empty.show_name = True
			scene.objects.link(empty)

		scene.update()
		return {'FINISHED'}




if __name__ == "__main__":
	register()

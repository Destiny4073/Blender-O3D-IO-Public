# ==============================================================================
#  Copyright (c) 2022-2023 Thomas Mathieson.
# ==============================================================================

import struct
import math


def log(*args):
    print("[O3DConvert]", *args)


# ---------------------------------------------------------------------------
# O3D vertex scrambling ("encryption")
#
# Files of version 4+ carry a u32 key; unless it is 0xFFFFFFFF the vertex
# records are scrambled with a state machine, reproduced here from the original
# OMSI loader/writer (reference implementation: openOMSI `omsi-o3d`, which
# documents the algorithm against the exe's `mc_o3dfile` loader at 0x56c74c and
# its writer at 0x56af20).
# ---------------------------------------------------------------------------

# State modulus of the initial state; the per-vertex state is always < 8000.
_ENCRYPTION_STATE_MODULUS = 0xFDE8
_ENCRYPTION_STATE_MAX = 8000


def _frac(x):
    # The fractional part, negative for negative inputs (like Rust's
    # `x - x.trunc()`; Python's `x % 1` would clamp to [0, 1) instead).
    return x - math.trunc(x)


def frac_byte(pos):
    """
    Mixing byte derived from the raw (still scrambled) position of a vertex;
    feeds the state of the *next* vertex.
    :param pos: the raw position as an (x, y, z) tuple/list
    """
    prod = abs(_frac(pos[0]) * _frac(pos[1]) * _frac(pos[2])) * 600.0
    return int(prod) % 256


def _unscramble(state, pos, nrm, uv):
    """
    Undo the per-vertex scrambling of version 4+ files, in place.
    """
    if state < 1000:
        pos[0], pos[1] = pos[1], pos[0]
    elif state < 3000:
        pos[0], pos[2] = pos[2], pos[0]
    elif state > 7000:
        pos[1], pos[2] = pos[2], pos[1]

    if state & 3 == 0:
        nrm[0] = -nrm[0]
    if state % 6 == 0:
        nrm[1] = -nrm[1]
    if state % 7 == 0:
        nrm[2] = -nrm[2]

    # Note: the `state > 6500` x/z normal swap can never run (every such state
    # already took the `state > 4500` branch); OMSI's own loader and writer
    # carry the same dead test, so it is left out to decode exactly like OMSI.
    if state < 600:
        nrm[1], nrm[2] = nrm[2], nrm[1]
    elif state > 4500:
        nrm[0], nrm[1] = nrm[1], nrm[0]

    if state % 5 == 0:
        uv[0] -= (state % 100) ** 2 / 10000.0
    if state % 3 == 0:
        uv[1] -= (state % 50) ** 2 / 2500.0


def _scramble(state, pos, nrm, uv):
    """
    Scramble a vertex for export; the exact inverse of `_unscramble`, as the
    original OMSI writer does it (swaps before negation).
    """
    if state < 1000:
        pos[0], pos[1] = pos[1], pos[0]
    elif state < 3000:
        pos[0], pos[2] = pos[2], pos[0]
    elif state > 7000:
        pos[1], pos[2] = pos[2], pos[1]

    if state < 600:
        nrm[1], nrm[2] = nrm[2], nrm[1]
    elif state > 4500:
        nrm[0], nrm[1] = nrm[1], nrm[0]

    if state & 3 == 0:
        nrm[0] = -nrm[0]
    if state % 6 == 0:
        nrm[1] = -nrm[1]
    if state % 7 == 0:
        nrm[2] = -nrm[2]

    if state % 5 == 0:
        uv[0] += (state % 100) ** 2 / 10000.0
    if state % 3 == 0:
        uv[1] += (state % 50) ** 2 / 2500.0


def init_rand(encryption_header, alt_encryption_seed, version):
    """
    Computes the initial scrambling state of a file from its key, version and
    the "alternative encryption seed" header flag.
    """
    k = encryption_header + (version - 4) + (0x17D if alt_encryption_seed else 0)
    return k % _ENCRYPTION_STATE_MODULUS


def _advance_state(state, encryption_header, alt_encryption_seed, prev_vpos_seed, n_verts):
    """
    Runs the per-vertex state machine: the state of each vertex mixes in the
    stored position of the one before it. A key of 0 restarts the state at
    every vertex.
    """
    if encryption_header == 0:
        state = 0x130 if alt_encryption_seed else 0
    n16 = n_verts % _ENCRYPTION_STATE_MODULUS
    return (state * n16 + n16 * prev_vpos_seed) % _ENCRYPTION_STATE_MAX


def decrypt_vert(vert, encryption_header, alt_encryption_seed, prev_seed, prev_vpos_seed, n_verts):
    """
    Decrypts (unscrambles) an o3d vertex.
    :param vert: a vertex in the form [(x, y, z), (nx, ny, nz), (u, v)]
    :param encryption_header: the encryption key from the file header
    :param alt_encryption_seed: whether the alternative encryption seed is used
    :param prev_seed: the state of the previous vertex
    :param prev_vpos_seed: the position mixing byte of the previous vertex
    :param n_verts: the total number of vertices in the file
    :return: (the decrypted vertex, the new state, the new position mixing byte)
    """
    state = _advance_state(prev_seed, encryption_header, alt_encryption_seed, prev_vpos_seed, n_verts)
    pos = list(vert[0])
    nrm = list(vert[1])
    uv = list(vert[2])
    vpos_seed = frac_byte(pos)
    _unscramble(state, pos, nrm, uv)
    return [[pos, nrm, uv], state, vpos_seed]


def encrypt_vert(vert, encryption_header, alt_encryption_seed, prev_seed, prev_vpos_seed, n_verts):
    """
    Encrypts (scrambles) an o3d vertex for export; see `decrypt_vert`.
    """
    state = _advance_state(prev_seed, encryption_header, alt_encryption_seed, prev_vpos_seed, n_verts)
    pos = list(vert[0])
    nrm = list(vert[1])
    uv = list(vert[2])
    _scramble(state, pos, nrm, uv)
    vpos_seed = frac_byte(pos)
    return [[pos, nrm, uv], state, vpos_seed]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

# Takes an o3d vertex and returns (((pos), (nrm), (uv)), bewOffset)
def import_vertex(buff, offset):
    v = struct.unpack_from("<ffffffff", buff, offset=offset)  # xp,yp,zp,xn,yn,zn,u,v
    return [[list(v[0:3]), list(v[3:6]), list(v[6:8])], offset + 8 * 4]


# Takes an o3d triangle struct and returns ((indices, matIndex), newOffset)
def import_triangle(buff, offset, long_triangle_indices, invert_normals=False):
    if long_triangle_indices:
        t = struct.unpack_from("<IIIH", buff, offset=offset)
        offset += 4 * 3 + 2
    else:
        t = struct.unpack_from("<HHHH", buff, offset=offset)
        offset += 2 * 4

    if invert_normals:
        return (t[0:3], t[3]), offset
    else:
        return (t[0:3][::-1], t[3]), offset


# Takes an o3d material struct and returns:
#      ((diffuse_r, diffuse_g, diffuse_b, diffuse_a),
#       (specular_r, specular_g, specular_b),
#       (emission_r, emission_g, emission_b),
#       specular_power, texture_name)
# is set to None if one isn't specified in the file
def import_material(buff, offset):
    m = struct.unpack_from("<fffffffffffB", buff, offset=offset)
    offset += 11 * 4
    # Extract texture path length
    path_len = m[-1] + 1  # Path length
    m_name = None
    if path_len + 1 > 0:
        try:
            m_name = struct.unpack_from("<{0}p".format(str(path_len)), buff, offset=offset)[0].decode("cp1252")
        except:
            m_name = ""
        offset += path_len
    return (m[0:4], m[4:7], m[7:10], m[10], m_name), offset


# Takes an o3d bone struct and returns ((name, weights), newOffset)
def import_bone(buff, offset, long_triangle_indices):
    h = struct.unpack_from("<B", buff, offset=offset)  # Name length
    b_name = struct.unpack_from("<{0}p".format(str(h[0] + 1)), buff, offset=offset)[0].decode("cp1252",
                                                                                              errors="backslashreplace")
    offset += h[0] + 1

    n_weights = struct.unpack_from("<H", buff, offset=offset)
    offset += 2
    weights = []
    for w in range(n_weights[0]):
        weights.append(struct.unpack_from("<If" if long_triangle_indices else "<Hf", buff, offset=offset))
        offset += 8 if long_triangle_indices else 6

    return (b_name, weights), offset


# Imports a list of o3d vertices and returns (vertices, newOffset)
def import_vertex_list(buff, offset, wide_counts, encrypted, alt_encryption_seed, encryption_header, version):
    if wide_counts:
        header = struct.unpack_from("<I", buff, offset=offset)[0]
        offset += 4
    else:
        header = struct.unpack_from("<H", buff, offset=offset)[0]
        offset += 2

    verts = []
    prev_vpos_seed = 0
    if encrypted:
        prev_seed = init_rand(encryption_header, alt_encryption_seed, version)
    else:
        prev_seed = 0
    for v in range(header):
        nv = import_vertex(buff, offset)
        if encrypted:
            nv[0], prev_seed, prev_vpos_seed = decrypt_vert(nv[0], encryption_header, alt_encryption_seed, prev_seed,
                                                            prev_vpos_seed, header)

        verts.append(nv[0])
        offset = nv[1]

    return verts, offset


# Imports a list of o3d triangles and returns (triangles, newOffset)
def import_triangle_list(buff, offset, wide_counts, long_triangle_indices):
    if wide_counts:
        header = struct.unpack_from("<I", buff, offset=offset)[0]
        offset += 4
    else:
        header = struct.unpack_from("<H", buff, offset=offset)[0]
        offset += 2

    tris = []
    for t in range(header):
        nt = import_triangle(buff, offset, long_triangle_indices, True)
        tris.append(nt[0])
        offset = nt[1]

    return tris, offset


# Imports a list of o3d materials and returns (materials, newOffset)
def import_material_list(buff, offset):
    # IDK why but materials don't get the wide count...
    header = struct.unpack_from("<H", buff, offset=offset)[0]
    offset += 2

    mats = []
    for m in range(header):
        nm = import_material(buff, offset)
        mats.append(nm[0])
        offset = nm[1]

    return mats, offset


# Imports a list of o3d bones and returns (bones, newOffset)
def import_bone_list(buff, offset, long_triangle_indices):
    # Bones always use a u16 count, even in files with wide (u32) counts
    header = struct.unpack_from("<H", buff, offset=offset)[0]
    offset += 2

    bones = []
    for b in range(header):
        nb = import_bone(buff, offset, long_triangle_indices)
        bones.append(nb[0])
        offset = nb[1]

    return bones, offset


# Imports an o3d transform struct and returns (transform, newOffset)
def import_transform(buff, offset):
    m = struct.unpack_from("<ffffffffffffffff", buff, offset=offset)
    offset += 16 * 4
    return (
               (m[0], m[1], m[2], m[3]),
               (m[4], m[5], m[6], m[7]),
               (m[8], m[9], m[10], m[11]),
               (m[12], m[13], m[14], m[15])
           ), offset


def import_o3d(packed_bytes):
    if len(packed_bytes) < 3 or packed_bytes[0] != 0x84 or packed_bytes[1] != 0x19:
        log("WARNING: O3D file has an unsupported header (found={0}; expected=(0x84,0x19,...). File might not import "
            "correctly...".format(list(map(hex, packed_bytes[:3]))))

    version = packed_bytes[2] if len(packed_bytes) > 2 else 1
    off = 3
    # From version 3 on, files carry a flags byte and use wide (u32) section counts
    wide_counts = version >= 3
    long_triangle_indices = False
    alt_encryption_seed = False
    encryption_header = 0
    encrypted = False
    if version >= 3:
        if off < len(packed_bytes):
            flags = packed_bytes[off]
            off += 1
            long_triangle_indices = flags & 1 == 1
            alt_encryption_seed = flags & 2 == 2
    if version >= 4:
        if off + 4 <= len(packed_bytes):
            encryption_header = struct.unpack_from("<I", packed_bytes, offset=off)[0]
            off += 4
        # Files of version 4+ carry a key; unless it is 0xFFFFFFFF the vertex records are
        # scrambled.
        encrypted = encryption_header != 0xFFFFFFFF
        if encrypted:
            log("Encrypted o3d file detected (key={0}, alt_seed={1}), decrypting...".format(
                encryption_header, alt_encryption_seed))

    vertex_list = []
    triangle_list = []
    material_list = []
    bone_list = []
    transform = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
    logged_unknown = False
    while off < len(packed_bytes):
        section = packed_bytes[off]
        off += 1
        if section == 0x17:
            vertex_list, off = import_vertex_list(packed_bytes, off, wide_counts, encrypted, alt_encryption_seed,
                                                  encryption_header, version)
        elif section == 0x49:
            triangle_list, off = import_triangle_list(packed_bytes, off, wide_counts, long_triangle_indices)
        elif section == 0x26:
            material_list, off = import_material_list(packed_bytes, off)
        elif section == 0x54:
            bone_list, off = import_bone_list(packed_bytes, off, long_triangle_indices)
        elif section == 0x79:
            transform, off = import_transform(packed_bytes, off)
        else:
            # Unknown bytes are passed over one at a time, exactly like the original loader
            # (its section `case` has no else branch). Some protected v7 files even carry a
            # few junk bytes inside their sections, so refusing unknown tags would lose the
            # rest of the file.
            if not logged_unknown:
                log("Unknown section tag {0} at {1}, skipping... (further tags won't be logged)".format(
                    hex(section), hex(off - 1)))
                logged_unknown = True

    return (0x84, 0x19, version), vertex_list, triangle_list, material_list, bone_list, transform, encrypted


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_vertex(write, vertex):
    """
    Exports an O3D vertex
    :param write: the file writer function
    :param vertex: the vertex to export as a tuple in the form: xp, yp, zp, xn, yn, zn, u, v
    """
    write("<ffffffff", *vertex)  # xp,yp,zp,xn,yn,zn,u,v


def export_triangle(write, triangle, long_triangle_indices, invert_normals=False):
    """
    Exports an O3D triangle
    :param write: the file writer function
    :param triangle: the triangle to export as a tuple in the form: a, b, c, mat_index
    :param long_triangle_indices: whether long triangle indices (32 bit) are used
    :param invert_normals: whether to invert the triangle winding
    """
    write("<IIIH" if long_triangle_indices else "<HHHH",
          *(triangle[0:3][::-1] if invert_normals else triangle[0:3]), triangle[3])


def export_material(write, material):
    """
    Exports an O3D material
    :param write: the file writer function
    :param material: the material to export as a tuple in the form:
    (diffuse_r, diffuse_g, diffuse_b, diffuse_a, specular_r, specular_g, specular_b, emission_r, emission_g, emission_b,
    specular_power, texture_name)
    """
    write("<fffffffffff", *material[:-1])
    write("<{0}p".format(len(material[-1])+1), material[-1].encode("cp1252"))


def export_bone(write, bone, long_triangle_indices):
    write("<{0}p".format(len(bone[0])+1), bone[0].encode("cp1252"))

    write("<H", len(bone[1]))
    for w in bone[1]:
        write("<If" if long_triangle_indices else "<Hf", *w)


def export_vertex_list(write, vertex_list, encrypted, encryption_key, wide_counts, alt_encryption_seed, version):
    """
    Exports a list of vertices to an O3D file
    :param write: the file writer function
    :param vertex_list: the vertex list to export
    :param encrypted: whether the vertex list should be encrypted
    :param encryption_key: the encryption key to encrypt with
    :param wide_counts: whether the file uses wide (u32) section counts (version >= 3)
    :param alt_encryption_seed: whether the alternative encryption seed is used
    :param version: the o3d file version
    """
    write("<B", 0x17)
    if wide_counts:
        write("<I", len(vertex_list))
    else:
        write("<H", len(vertex_list))

    prev_vpos_seed = 0
    if encrypted:
        prev_seed = init_rand(encryption_key, alt_encryption_seed, version)
    else:
        prev_seed = 0
    for v in vertex_list:
        if encrypted:
            # Vertices come in as flat (xp, yp, zp, xn, yn, zn, u, v) tuples,
            # but the scrambler works on the nested (pos, normal, uv) form the
            # importer produces.
            nv = [list(v[0:3]), list(v[3:6]), list(v[6:8])]
            nv, prev_seed, prev_vpos_seed = encrypt_vert(nv, encryption_key, alt_encryption_seed, prev_seed,
                                                         prev_vpos_seed, len(vertex_list))
            v = nv[0] + nv[1] + nv[2]
        export_vertex(write, v)


def export_triangle_list(write, triangle_list, long_triangle_indices, wide_counts, invert_triangle_winding=False):
    """
    Exports a list of triangles to an O3D file
    :param write: the file writer function
    :param triangle_list: the list of triangles to export
    :param long_triangle_indices: whether the triangle indices are 32 bit
    :param wide_counts: whether the file uses wide (u32) section counts (version >= 3)
    """
    write("<B", 0x49)
    if wide_counts:
        write("<I", len(triangle_list))
    else:
        write("<H", len(triangle_list))

    for t in triangle_list:
        export_triangle(write, t, long_triangle_indices, invert_triangle_winding)


def export_material_list(write, material_list):
    if len(material_list) == 0:
        return

    write("<B", 0x26)
    # Materials always use a u16 count
    write("<H", len(material_list))

    for m in material_list:
        export_material(write, m)


def export_bone_list(write, bone_list, long_triangle_indices):
    if len(bone_list) == 0:
        return

    write("<B", 0x54)
    # Bones always use a u16 count
    write("<H", len(bone_list))

    for bone in bone_list:
        export_bone(write, bone, long_triangle_indices)


def export_transform(write, transform):
    # For now this just exports an identity matrix
    # TODO: Export correct transform matrix
    if transform is None:
        transform = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)

    write("<B", 0x79)
    m = transform
    write("<ffffffffffffffff", *m)


def export_o3d(file, vertex_list, triangle_list, material_list, bone_list, transform, encrypted=False,
               encryption_key=0xffffffff, version=7, long_triangle_indices=True, alt_encryption_seed=True,
               invert_triangle_winding=False):
    # Convenience function to pack and write bytes
    def write(fmt, *args):
        file.write(struct.pack(fmt, *args))

    # Write header
    write("<BBB", 0x84, 0x19, version)
    # From version 3 on, files carry a flags byte and use wide (u32) section counts
    wide_counts = version >= 3
    if version >= 3:
        # Write the extended header: flags byte, and the encryption key for version 4+
        options_byte = (1 if long_triangle_indices else 0) | (2 if alt_encryption_seed else 0)
        if version >= 4:
            if not encrypted:
                # An open key (0xFFFFFFFF) means the vertex records are stored unscrambled
                encryption_key = 0xFFFFFFFF
            write("<BI", options_byte, encryption_key)
        else:
            if encrypted:
                log("WARNING: O3D files with a version < 4 don't support encryption, the file will be written "
                    "unencrypted")
            write("<B", options_byte)

    if version < 3:
        if long_triangle_indices:
            log("WARNING: O3D files with a version < 3 don't support long triangle "
                "indices, the file will be unreadable")
        if alt_encryption_seed:
            log("WARNING: O3D files with a version < 3 don't support the alt encryption "
                "seed")
        if encrypted:
            log("WARNING: O3D files with a version < 3 don't support encryption, the "
                "file will be unreadable")

    export_vertex_list(write, vertex_list, encrypted, encryption_key, wide_counts, alt_encryption_seed, version)
    export_triangle_list(write, triangle_list, long_triangle_indices, wide_counts, invert_triangle_winding)
    export_material_list(write, material_list)
    export_bone_list(write, bone_list, long_triangle_indices)
    export_transform(write, transform)

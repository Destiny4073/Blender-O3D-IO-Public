# ==============================================================================
#  Copyright (c) 2023-2026 Thomas Mathieson / openOMSI contributors.
# ==============================================================================
"""
DirectX .x mesh parser for OMSI helper meshes and scenery objects.

This is a Python port of openOMSI's `omsi-o3d/src/xfile.rs` parser (licensed
GPL-2.0-or-later), which itself reproduces the behaviour of OMSI's D3DX-based
`.x` loader. It supports:

* text files (`xof 0303txt` / `0302txt`) and uncompressed binary files
  (`bin ` with `0032` or `0064` floats); the compressed `tzip`/`bzip`
  variants are not supported,
* `Frame` hierarchies with `FrameTransformMatrix` (Direct3D row-major
  matrices for row vectors; the translation lives in the 4th row),
* `Mesh`, `MeshNormals`, `MeshTextureCoords`, `MeshMaterialList`
  (inline materials and named references, resolved after the whole file),
* `Material` with `TextureFilename`,
* `DeclData` (Direct3D 9 vertex declarations) supplying normals and texture
  coordinates, widening all packed element types (D3DCOLOR, DEC3N, SHORT2N,
  FLOAT16_2, ...) exactly like Direct3D 9 does.

The parser is deliberately free of any `bpy` dependency so it can be unit
tested outside Blender. Coordinates are returned in the file's own (Direct3D)
frame: X right, Y up, Z forward; the caller is responsible for converting to
the target coordinate system.

Each `Mesh` data object becomes one entry of the returned list:
    {
        "name": str,                                # enclosing frame's name
        "vertices": [((x, y, z), (nx, ny, nz), (u, v)), ...],
        "faces": [(i0, i1, ...), ...],              # n-gons, may be triangles
        "face_materials": [int, ...],               # parallel to "faces"
        "materials": [(diffuse(rgba), specular(rgb), emissive(rgb), power, texture), ...],
    }
"""

import struct


def log(*args):
    print("[XFile]", *args)


class XFileError(Exception):
    pass


# Single-character marks of the text format.
_MARKS = "{};,<>"
# The keywords binary templates use for member types (token values 40 to 52).
_TYPE_WORDS = [
    "WORD", "DWORD", "FLOAT", "DOUBLE", "CHAR", "UCHAR", "SWORD", "SDWORD", "void", "string", "unicode", "cstring",
    "array",
]
# D3DDECLUSAGE values the meshes take data from.
_DECLUSAGE_NORMAL = 3
_DECLUSAGE_TEXCOORD = 5
# Bytes each D3DDECLTYPE takes in the vertex, FLOAT1 (0) to UNUSED (17).
_DECLTYPE_BYTES = [4, 8, 12, 16, 4, 4, 4, 8, 4, 4, 8, 4, 8, 4, 4, 4, 8, 0]

_MAX_FRAME_DEPTH = 128


# ---------------------------------------------------------------------------
# Tiny matrix helpers (4x4, row-major storage, column-vector convention:
# out_i = sum_j m[i][j] * v[j] + m[i][3], like mathutils).
# ---------------------------------------------------------------------------

def mat_identity():
    return [[1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]]


def mat_from_file_rows(m16):
    """
    Direct3D writes transform matrices row by row for row vectors
    (v' = v * M, translation in elements 12-14). Read column by column, that
    is already the column-vector matrix used here (and by mathutils/glam), so
    the file rows become the columns of the result.
    """
    return [[m16[0], m16[4], m16[8], m16[12]],
             [m16[1], m16[5], m16[9], m16[13]],
             [m16[2], m16[6], m16[10], m16[14]],
             [m16[3], m16[7], m16[11], m16[15]]]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_transform_point(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _inv3(m):
    det = _det3(m)
    if det == 0:
        return None
    inv = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            # (A^-1)[i][j] = C[j][i] / det, C[j][i] = (-1)^(j+i) * minor(row j, col i)
            r = [k for k in range(3) if k != j]
            c = [k for k in range(3) if k != i]
            minor = m[r[0]][c[0]] * m[r[1]][c[1]] - m[r[0]][c[1]] * m[r[1]][c[0]]
            inv[i][j] = (1 if (i + j) % 2 == 0 else -1) * minor / det
    return inv


def _transpose3(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


def normal_matrix(xform):
    """
    Normals go by the inverse transpose of the frame matrix.
    """
    linear = [[xform[i][j] for j in range(3)] for i in range(3)]
    inv = _inv3(linear)
    if inv is not None:
        return _transpose3(inv)
    return linear


def _normalize(v):
    l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    if l == 0:
        return (0.0, 0.0, 0.0)
    return (v[0] / l, v[1] / l, v[2] / l)


def _mat3_mul_vec(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def _token_key(tok):
    """
    What the parser matches against: the mark or the word; numbers, strings
    and GUIDs match none.
    """
    if tok is None:
        return None
    kind, v = tok
    if kind == "mark":
        return v
    if kind == "word":
        return v
    return ""


class Tokenizer:
    """
    One token stream over either encoding; roughly `struct Tok` of the Rust
    original.
    """

    def __init__(self, data: bytes):
        if len(data) < 16:
            raise XFileError("missing xof header")
        try:
            data[:16].decode("ascii")
        except UnicodeDecodeError:
            raise XFileError("missing xof header")
        if not data.startswith(b"xof "):
            raise XFileError("missing xof header")

        fmt = data[8:12]
        self.mode = None
        self.doubles = False
        if fmt == b"txt ":
            self.mode = "text"
            self.text = data.decode("cp1252", errors="replace")
        elif fmt == b"bin ":
            self.mode = "binary"
            self.data = data
            self.doubles = data[12:16] == b"0064"
        elif fmt == b"tzip" or fmt == b"bzip":
            raise XFileError("compressed .x not supported")
        else:
            raise XFileError(".x of the kind {0!r} not supported".format(fmt.decode("cp1252", errors="replace")))

        self.pos = 16
        # numbers still to come from the binary integer or float list being read
        self.list_left = 0
        self.list_floats = False
        # the separator stored after a binary string, handed out as the next token
        self.after_string = None

    # -- state save/restore (for the lookahead helpers) ---------------------

    def _save(self):
        return (self.pos, self.list_left, self.list_floats, self.after_string)

    def _restore(self, state):
        self.pos, self.list_left, self.list_floats, self.after_string = state

    # -- primitive readers (binary) -----------------------------------------

    def _take(self, n):
        data = self.data
        if self.pos + n > len(data):
            raise XFileError("binary .x ends inside a token")
        b = data[self.pos:self.pos + n]
        self.pos += n
        return b

    def _take_u16(self):
        return struct.unpack("<H", self._take(2))[0]

    def _take_u32(self):
        return struct.unpack("<I", self._take(4))[0]

    def _counted(self):
        n = self._take_u32()
        data = self.data
        if self.pos + n > len(data):
            raise XFileError("binary .x ends inside a name")
        b = data[self.pos:self.pos + n]
        self.pos += n
        return b

    def _left(self):
        if self.mode == "text":
            return len(self.text) - self.pos
        return len(self.data) - self.pos

    # -- token readers -------------------------------------------------------

    def next(self):
        if self.mode == "text":
            return self._next_text()
        return self._next_binary()

    def _next_text(self):
        s = self.text
        n = len(s)
        p = self.pos
        while p < n:
            c = s[p]
            # NOTE: ASCII whitespace only — names in OMSI content are
            # Windows-1252 and may contain characters like the NBSP which
            # Python's str.isspace() would wrongly treat as separators.
            if c in " \t\n\r\x0b\x0c":
                p += 1
                continue
            if c == "#" or s.startswith("//", p):
                while p < n and s[p] != "\n":
                    p += 1
                continue
            break
        self.pos = p
        if p >= n:
            return None
        c = s[p]
        if c == '"':
            end = s.find('"', p + 1)
            if end == -1:
                end = n
            self.pos = min(end + 1, n)
            return ("quoted", s[p + 1:end])
        if c in _MARKS:
            self.pos = p + 1
            return ("mark", c)
        end = p
        while end < n:
            c = s[end]
            if c in " \t\n\r\x0b\x0c" or c == '"' or c in _MARKS:
                break
            end += 1
        self.pos = end
        return ("word", s[p:end])

    def _next_binary(self):
        if self.after_string is not None:
            mark = self.after_string
            self.after_string = None
            return ("mark", mark)
        while True:
            if self.list_left > 0:
                self.list_left -= 1
                if not self.list_floats:
                    return ("int", self._take_u32())
                elif not self.doubles:
                    return ("float", struct.unpack("<f", self._take(4))[0])
                else:
                    return ("float", struct.unpack("<d", self._take(8))[0])
            if self.pos >= len(self.data):
                return None
            tid = self._take_u16()
            if tid == 1:
                return ("word", self._counted().decode("cp1252"))
            elif tid == 2:
                text = self._counted().decode("cp1252")
                # The terminator is a DWORD by the documentation (19 ',' or 20
                # ';'), but some exporters write it as a token's WORD: PAD-Labs'
                # binary Köln houses have `14 00` and then the `}` closing the
                # TextureFilename. No token is 0, so a WORD of 0 after it is the
                # DWORD's upper half.
                end = self._take_u16()
                if self.data[self.pos:self.pos + 2] == b"\x00\x00":
                    self.pos += 2
                self.after_string = "," if end == 19 else ";"
                return ("quoted", text)
            elif tid == 3:
                return ("int", self._take_u32())
            elif tid == 5:
                self._take(16)
                return ("guid", None)
            elif tid == 6 or tid == 7:
                n = self._take_u32()
                width = 8 if (tid == 7 and self.doubles) else 4
                if n > self._left() // width:
                    raise XFileError("binary .x list of {0} numbers is longer than the file".format(n))
                self.list_left = n
                self.list_floats = tid == 7
                continue
            elif 10 <= tid <= 20:
                return ("mark", "{}()[]<>.,;"[tid - 10])
            elif tid == 31:
                return ("word", "template")
            elif 40 <= tid <= 52:
                return ("word", _TYPE_WORDS[tid - 40])
            else:
                raise XFileError("unknown binary .x token {0}".format(tid))

    # -- lookahead helpers ----------------------------------------------------

    def at(self, key):
        """Whether the next token is `key`, without reading it."""
        state = self._save()
        tok = self.next()
        hit = _token_key(tok) == key
        self._restore(state)
        return hit

    def expect(self, key):
        tok = self.next()
        if tok is None:
            raise XFileError("expected '{0}', got eof".format(key))
        if _token_key(tok) != key:
            raise XFileError("expected '{0}', got {1!r}".format(key, tok))

    def label(self):
        """
        The name (and optional GUID) a data object may have before its `{`;
        gives the name.
        """
        name = None
        for _ in range(2):
            state = self._save()
            tok = self.next()
            if tok is None:
                self._restore(state)
                break
            kind, v = tok
            if kind == "guid":
                continue
            if kind == "word" and name is None:
                name = v
                continue
            self._restore(state)
            break
        return name

    def enter(self):
        """Step into a data object: past its label and its `{`."""
        name = self.label()
        self.expect("{")
        return name

    def scalar(self):
        """The next number, past separators."""
        while True:
            tok = self.next()
            if tok is None:
                raise XFileError("eof in number")
            kind, v = tok
            if kind == "mark" and (v == "," or v == ";"):
                continue
            if kind == "guid":
                continue
            if kind == "int":
                return float(v)
            if kind == "float":
                return v
            if kind == "word":
                try:
                    return float(v)
                except ValueError:
                    pass
                # tolerate C-style float literals with a trailing 'f'
                if v and v[-1] in "fF":
                    try:
                        return float(v[:-1])
                    except ValueError:
                        pass
                raise XFileError("{0!r} is not a number".format(v))
            raise XFileError("expected a number, got {0!r}".format(tok))

    def number(self):
        # All mesh numbers go through float32, exactly like the original
        # (f32 everywhere) — this also makes text and binary files parse to
        # identical values.
        return struct.unpack("<f", struct.pack("<f", self.scalar()))[0]

    def int(self):
        return int(self.scalar())

    def bits32(self):
        """
        A DWORD as stored, all 32 bits of it (DeclData keeps floats as their
        bit patterns, which an f32 round trip would change).
        """
        while True:
            tok = self.next()
            if tok is None:
                raise XFileError("eof in DWORD")
            kind, v = tok
            if kind == "mark" and (v == "," or v == ";"):
                continue
            if kind == "int":
                return v & 0xFFFFFFFF
            if kind == "float":
                return int(v) & 0xFFFFFFFF
            if kind == "word":
                try:
                    return int(v, 10) & 0xFFFFFFFF
                except ValueError:
                    pass
                # some exporters write the signed value
                try:
                    return int(float(v)) & 0xFFFFFFFF
                except ValueError:
                    raise XFileError("bad DWORD {0}".format(v))
            raise XFileError("expected a DWORD, got {0!r}".format(tok))

    def skip_block(self):
        """Skip to the `}` that closes the object we are in."""
        depth = 1
        while depth > 0:
            tok = self.next()
            if tok is None:
                raise XFileError("eof in block")
            if tok == ("mark", "{"):
                depth += 1
            elif tok == ("mark", "}"):
                depth -= 1


# ---------------------------------------------------------------------------
# DeclData (Direct3D 9 vertex declarations)
# ---------------------------------------------------------------------------

def _read_vertex_declaration(t):
    declared = t.bits32()
    elements = []
    while len(elements) < declared:
        kind = t.bits32()
        t.bits32()  # method (unused)
        usage = t.bits32()
        usage_index = t.bits32()
        elements.append((kind, usage, usage_index))
    size = t.bits32()
    buffer = []
    while len(buffer) < size:
        buffer.append(t.bits32())
    return elements, buffer


def _to_i16(x):
    x &= 0xFFFF
    return x - 0x10000 if x >= 0x8000 else x


def _snorm(v, maximum):
    v = v / maximum
    return v if v > -1.0 else -1.0


def _half2(word):
    return struct.unpack("<2e", struct.pack("<I", word & 0xFFFFFFFF))


def _half4(w0, w1):
    return struct.unpack("<4e", struct.pack("<II", w0 & 0xFFFFFFFF, w1 & 0xFFFFFFFF))


def _unpack_element(kind, words):
    """
    A vertex element widened to four floats the way Direct3D 9 does it:
    missing components are 0, 0, 0, 1; the `N` types are normalised.
    """
    w = words

    def f(i):
        return struct.unpack("<f", struct.pack("<I", w[i] & 0xFFFFFFFF))[0]

    if kind == 0:  # FLOAT1
        return (f(0), 0.0, 0.0, 1.0)
    if kind == 1:  # FLOAT2
        return (f(0), f(1), 0.0, 1.0)
    if kind == 2:  # FLOAT3
        return (f(0), f(1), f(2), 1.0)
    if kind == 3:  # FLOAT4
        return (f(0), f(1), f(2), f(3))
    if kind == 4:  # D3DCOLOR: A8R8G8B8, read out as r, g, b, a
        word = w[0] & 0xFFFFFFFF
        b = word & 0xFF
        g = (word >> 8) & 0xFF
        r = (word >> 16) & 0xFF
        a = (word >> 24) & 0xFF
        return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    if kind == 5:  # UBYTE4
        word = w[0] & 0xFFFFFFFF
        return tuple(float(b) for b in struct.pack("<I", word))
    if kind == 8:  # UBYTE4N
        word = w[0] & 0xFFFFFFFF
        return tuple(b / 255.0 for b in struct.pack("<I", word))
    if kind == 6:  # SHORT2
        word = w[0] & 0xFFFFFFFF
        return (_to_i16(word), _to_i16(word >> 16), 0.0, 1.0)
    if kind == 7:  # SHORT4
        return (_to_i16(w[0]), _to_i16(w[0] >> 16), _to_i16(w[1]), _to_i16(w[1] >> 16))
    if kind == 9:  # SHORT2N
        word = w[0] & 0xFFFFFFFF
        return (_snorm(_to_i16(word), 32767.0), _snorm(_to_i16(word >> 16), 32767.0), 0.0, 1.0)
    if kind == 10:  # SHORT4N
        return (_snorm(_to_i16(w[0]), 32767.0), _snorm(_to_i16(w[0] >> 16), 32767.0),
                _snorm(_to_i16(w[1]), 32767.0), _snorm(_to_i16(w[1] >> 16), 32767.0))
    if kind == 11:  # USHORT2N
        word = w[0] & 0xFFFFFFFF
        return ((word & 0xFFFF) / 65535.0, ((word >> 16) & 0xFFFF) / 65535.0, 0.0, 1.0)
    if kind == 12:  # USHORT4N
        return ((w[0] & 0xFFFF) / 65535.0, ((w[0] >> 16) & 0xFFFF) / 65535.0,
                (w[1] & 0xFFFF) / 65535.0, ((w[1] >> 16) & 0xFFFF) / 65535.0)
    if kind == 13:  # UDEC3: three 10-bit fields from bit 0 up
        word = w[0] & 0xFFFFFFFF
        return (float(word & 0x3FF), float((word >> 10) & 0x3FF), float((word >> 20) & 0x3FF), 1.0)
    if kind == 14:  # DEC3N
        word = w[0] & 0xFFFFFFFF

        def field(shift):
            v = (word >> shift) & 0x3FF
            if v & 0x200:
                v -= 0x400
            return _snorm(float(v), 511.0)

        return (field(0), field(10), field(20), 1.0)
    if kind == 15:  # HALF2
        h = _half2(w[0])
        return (h[0], h[1], 0.0, 1.0)
    if kind == 16:  # HALF4
        h = _half4(w[0], w[1])
        return (h[0], h[1], h[2], h[3])
    return None


def _apply_declaration(decl, to_world, vertices, normals, uvs):
    """
    Take the first normal and the first texture coordinate set out of the
    buffer. A layout with a type Direct3D 9 does not have gives no stride, so
    nothing is taken from it. `normals`/`uvs` may be None when the mesh already
    carries its own MeshNormals/MeshTextureCoords, which win over the DeclData.
    """
    elements, buffer = decl
    if normals is None and uvs is None:
        return
    offsets = []
    stride = 0
    for (kind, usage, usage_index) in elements:
        if kind >= len(_DECLTYPE_BYTES):
            log(".x DeclData: unknown vertex element type {0}; left out".format(kind))
            return
        offsets.append(stride)
        stride += _DECLTYPE_BYTES[kind] // 4
    # a buffer that does not hold exactly one record per vertex is not this
    # mesh's (the vertex count and the stride would otherwise scramble every
    # coordinate)
    if stride == 0 or len(buffer) != stride * vertices:
        return
    for (kind, usage, usage_index), offset in zip(elements, offsets):
        if usage_index != 0:
            continue
        for v in range(vertices):
            value = _unpack_element(kind, buffer[v * stride + offset:])
            if value is None:
                break
            if usage == _DECLUSAGE_NORMAL:
                normals[v] = _normalize(_mat3_mul_vec(to_world, value[:3]))
            elif usage == _DECLUSAGE_TEXCOORD:
                uvs[v] = (value[0], value[1])


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DEFAULT_MATERIAL = ((1.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, "")


class _Ctx:
    def __init__(self):
        self.meshes = []
        # Named data objects in an .x file can be referenced from any frame or
        # mesh.
        self.named_materials = {}


def _parse_objects(t, ctx, xform):
    while True:
        tok = t.next()
        if tok is None:
            return
        k = _token_key(tok)
        if k == "}":
            return
        elif k == "template":
            # template Name { ... }
            t.next()
            t.expect("{")
            t.skip_block()
        elif k == "Frame":
            name = t.enter()
            _parse_frame(t, ctx, xform, 1, name)
        elif k == "Mesh":
            name = t.enter()
            _parse_mesh(t, ctx, xform, name)
        elif k == "Material":
            name, material = _parse_material(t)
            if name is not None:
                ctx.named_materials[name] = material
        else:
            _skip_object(t, tok)


def _skip_object(t, first):
    """
    An object the reader does not use (`Name [id] { ... }`), after its first
    token; separators left between objects (the `;;` after a face list) are
    passed over.
    """
    kind, v = first
    if kind == "mark":
        if v == "{":
            t.skip_block()
        return
    t.label()
    if t.at("{"):
        t.next()
        t.skip_block()


def _parse_frame(t, ctx, parent, depth, frame_name):
    if depth > _MAX_FRAME_DEPTH:
        raise XFileError("frames nested more than {0} deep".format(_MAX_FRAME_DEPTH))
    xform = parent
    while True:
        tok = t.next()
        if tok is None:
            raise XFileError("eof in frame")
        k = _token_key(tok)
        if k == "}":
            return
        elif k == "FrameTransformMatrix":
            # a data object may carry a name (`FrameTransformMatrix relative {`)
            t.enter()
            m16 = [t.number() for _ in range(16)]
            # the trailing ';;' and the '}'
            t.skip_block()
            local = mat_from_file_rows(m16)
            xform = mat_mul(parent, local)
        elif k == "Frame":
            name = t.enter()
            _parse_frame(t, ctx, xform, depth + 1, name)
        elif k == "Mesh":
            name = t.enter()
            _parse_mesh(t, ctx, xform, frame_name or name)
        elif k == "Material":
            name, material = _parse_material(t)
            if name is not None:
                ctx.named_materials[name] = material
        else:
            _skip_object(t, tok)


def _parse_mesh(t, ctx, xform, mesh_name):
    nv = t.int()
    positions = []
    for _ in range(nv):
        p = (t.number(), t.number(), t.number())
        positions.append(mat_transform_point(xform, p))
    nf = t.int()
    faces = []
    for _ in range(nf):
        n = t.int()
        f = []
        for _ in range(n):
            f.append(t.int())
        faces.append(f)

    normals = [(0.0, 0.0, 1.0)] * nv
    uvs = [(0.0, 0.0)] * nv
    face_mats = [0] * nf
    # (MeshNormals and MeshTextureCoords win over a DeclData that also lists them)
    has_normals = False
    has_uvs = False
    decl = None
    mats = []
    material_refs = []
    while True:
        tok = t.next()
        if tok is None:
            raise XFileError("eof in mesh")
        k = _token_key(tok)
        if k == "}":
            break
        elif k == "MeshNormals":
            has_normals = True
            t.enter()
            nn = t.int()
            nrm = []
            to_world = normal_matrix(xform)
            for _ in range(nn):
                n = (t.number(), t.number(), t.number())
                nrm.append(_normalize(_mat3_mul_vec(to_world, n)))
            nfn = t.int()
            for fi in range(nfn):
                n = t.int()
                for k2 in range(n):
                    ni = t.int()
                    if fi < len(faces) and k2 < len(faces[fi]):
                        vi = faces[fi][k2]
                        if vi < len(normals) and ni < len(nrm):
                            normals[vi] = nrm[ni]
            t.skip_block()
        elif k == "MeshTextureCoords":
            has_uvs = True
            t.enter()
            n = t.int()
            for i in range(n):
                uv = (t.number(), t.number())
                if i < len(uvs):
                    uvs[i] = uv
            t.skip_block()
        elif k == "DeclData":
            t.enter()
            decl = _read_vertex_declaration(t)
            t.skip_block()
        elif k == "MeshMaterialList":
            t.enter()
            t.int()  # material count (implied by the following definitions)
            nfi = t.int()
            for i in range(nfi):
                m = t.int()
                if i < len(face_mats):
                    face_mats[i] = m
            while True:
                tk = t.next()
                if tk is None:
                    raise XFileError("eof in matlist")
                kk = _token_key(tk)
                if kk == "}":
                    break
                elif kk == "Material":
                    name, material = _parse_material(t)
                    if name is not None:
                        ctx.named_materials[name] = material
                    mats.append(material)
                elif kk == "{":
                    # Keep this slot even if the named material is defined later
                    # or absent: dropping it changes every following face
                    # material index. A reference by GUID alone keeps the slot
                    # too; it names nothing this reader can look up.
                    name = None
                    by_guid = False
                    while True:
                        tk2 = t.next()
                        if tk2 is None:
                            raise XFileError("unclosed material reference")
                        kind, v = tk2
                        if kind == "mark" and v == "}":
                            break
                        if kind == "word" and name is None:
                            name = v
                        elif kind == "mark" and v == "{":
                            raise XFileError("unclosed material reference")
                        else:
                            by_guid = True
                    if name is not None:
                        material_refs.append((len(mats), name))
                    elif not by_guid:
                        raise XFileError("missing material reference name")
                    mats.append(_DEFAULT_MATERIAL)
                # else: ignore
        else:
            _skip_object(t, tok)

    if decl is not None:
        to_world = normal_matrix(xform)
        # MeshNormals and MeshTextureCoords win over a DeclData that also lists them
        _apply_declaration(decl, to_world, nv,
                           None if has_normals else normals,
                           None if has_uvs else uvs)

    if len(mats) == 0:
        mats.append(_DEFAULT_MATERIAL)

    vertices = []
    for i in range(nv):
        vertices.append((positions[i], normals[i], uvs[i]))

    # Drop faces naming a vertex the file does not have (a damaged or
    # hand-made file) and degenerate faces (repeated vertex indices).
    out_faces = []
    out_face_mats = []
    for fi, f in enumerate(faces):
        if len(f) < 3 or len(set(f)) < len(f):
            continue
        if any(i < 0 or i >= nv for i in f):
            log("Mesh {0}: face {1} names a vertex beyond the {2} there are; left out".format(mesh_name, fi, nv))
            continue
        out_faces.append(tuple(f))
        out_face_mats.append(min(face_mats[fi], len(mats) - 1))

    ctx.meshes.append({
        "name": mesh_name or "Mesh",
        "vertices": vertices,
        "faces": out_faces,
        "face_materials": out_face_mats,
        "materials": mats,
        "material_refs": material_refs,
    })


def _parse_material(t):
    """
    A material declaration after its `Material` token, either inline or a
    named object.
    """
    name = t.label()
    t.expect("{")
    diffuse = (t.number(), t.number(), t.number(), t.number())
    power = t.number()
    specular = (t.number(), t.number(), t.number())
    emissive = (t.number(), t.number(), t.number())
    texture = ""
    while True:
        tok = t.next()
        if tok is None:
            raise XFileError("eof in material")
        k = _token_key(tok)
        if k == "}":
            break
        elif k == "TextureFilename":
            t.enter()
            tex_tok = t.next()
            if tex_tok is None:
                texture = ""
            elif tex_tok[0] == "quoted":
                texture = tex_tok[1]
            else:
                texture = (_token_key(tex_tok) or "").strip('"')
            t.skip_block()
        elif k == "{":
            t.skip_block()
    return name, (diffuse, specular, emissive, power, texture)


def parse_x(data: bytes):
    """
    Parse a DirectX `.x` file from memory.

    :param data: the raw file bytes
    :return: a list of mesh dictionaries, one per `Mesh` data object
             (see the module docstring for the format)
    """
    t = Tokenizer(data)
    ctx = _Ctx()
    _parse_objects(t, ctx, mat_identity())

    for mesh in ctx.meshes:
        # Resolve material references after the whole file, because
        # definitions may follow their references.
        for slot, name in mesh["material_refs"]:
            if name in ctx.named_materials:
                mesh["materials"][slot] = ctx.named_materials[name]
        del mesh["material_refs"]
        if len(mesh["materials"]) == 0:
            mesh["materials"].append(_DEFAULT_MATERIAL)

    return ctx.meshes

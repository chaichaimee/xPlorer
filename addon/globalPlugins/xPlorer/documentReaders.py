# documentReaders.py

import os
import re
import struct
import sys
import zipfile
import importlib.util
import xml.etree.ElementTree as ET

DOCUMENT_EXTENSIONS = ('.doc', '.docx')

_libsDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
_loadedLibs = {}

_MAX_STREAM_BYTES = 64 * 1024 * 1024
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_SKIPPED_RUN_TAGS = frozenset((
	_W + "pPr", _W + "rPr", _W + "delText", _W + "instrText",
	_W + "sdtPr", _W + "sdtEndPr",
))
_TRANSPARENT_BLOCK_TAGS = frozenset((
	_W + "ins", _W + "moveTo", _W + "customXml",
))
_DOC_CONTROL_MAP = {
	0x0d: "\n", 0x0b: "\n", 0x0c: "\n", 0x0e: "\n", 0x1e: "-",
}
_DOC_STRAY_CONTROLS = re.compile("[\x00-\x08\x0f-\x1f\x7f]")


class DocumentReadError(Exception):
	pass


def isDocumentFile(filePath):
	return os.path.splitext(filePath)[1].lower() in DOCUMENT_EXTENSIONS


def _loadBundledModule(moduleName, relativeParts):
	cached = _loadedLibs.get(moduleName)
	if cached is not None:
		return cached
	modulePath = os.path.join(_libsDir, *relativeParts)
	privateName = "_xPlorerLib_" + moduleName
	spec = importlib.util.spec_from_file_location(privateName, modulePath)
	if spec is None or spec.loader is None:
		raise DocumentReadError("Bundled library is missing: " + moduleName)
	module = importlib.util.module_from_spec(spec)
	sys.modules[privateName] = module
	try:
		spec.loader.exec_module(module)
	except (ImportError, OSError, SyntaxError) as e:
		sys.modules.pop(privateName, None)
		raise DocumentReadError("Bundled library failed to load: " + moduleName) from e
	_loadedLibs[moduleName] = module
	return module


def _tidyText(text):
	return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def rtfBytesToText(rawBytes):
	striprtf = _loadBundledModule("striprtf", ("striprtf", "striprtf.py"))
	try:
		converted = striprtf.rtf_to_text(rawBytes.decode("latin-1"), errors="replace")
	except (ValueError, TypeError, IndexError, LookupError, UnicodeError) as e:
		raise DocumentReadError("RTF conversion failed: " + str(e)[:80]) from e
	normalized = converted.replace("\r\n", "\n").replace("\r", "\n")
	return normalized[:-1] if normalized.endswith("\n") else normalized


def _paragraphText(paragraph, textBoxes):
	parts = []

	def walk(node):
		for child in node:
			tag = child.tag
			if tag in _SKIPPED_RUN_TAGS:
				continue
			if tag == _W + "t":
				parts.append(child.text or "")
			elif tag == _W + "tab" or tag == _W + "ptab":
				parts.append("\t")
			elif tag == _W + "br" or tag == _W + "cr":
				parts.append("\n")
			elif tag == _W + "noBreakHyphen":
				parts.append("-")
			elif tag == _W + "txbxContent":
				textBoxes.append(child)
			elif tag == _MC + "AlternateContent":
				chosen = child.find(_MC + "Choice")
				if chosen is None:
					chosen = child.find(_MC + "Fallback")
				if chosen is not None:
					walk(chosen)
			else:
				walk(child)

	walk(paragraph)
	return "".join(parts)


def _collectBlocks(container, lines):
	for child in container:
		tag = child.tag
		if tag == _W + "p":
			textBoxes = []
			lines.append(_paragraphText(child, textBoxes))
			for box in textBoxes:
				_collectBlocks(box, lines)
		elif tag == _W + "tbl":
			_collectTable(child, lines)
		elif tag == _W + "sdt":
			content = child.find(_W + "sdtContent")
			if content is not None:
				_collectBlocks(content, lines)
		elif tag in _TRANSPARENT_BLOCK_TAGS:
			_collectBlocks(child, lines)


def _collectTable(table, lines):
	for row in table.findall(_W + "tr"):
		cellTexts = []
		for cell in row.findall(_W + "tc"):
			cellLines = []
			_collectBlocks(cell, cellLines)
			cellTexts.append(" ".join(line for line in cellLines if line.strip()))
		lines.append("\t".join(cellTexts))


def docxXmlToText(xmlBytes):
	if b"<!DOCTYPE" in xmlBytes[:4096]:
		raise DocumentReadError("Unexpected DOCTYPE in document body")
	try:
		root = ET.fromstring(xmlBytes)
	except ET.ParseError as e:
		raise DocumentReadError("Document body is not valid XML") from e
	body = root.find(_W + "body")
	if body is None:
		raise DocumentReadError("Document body not found")
	lines = []
	_collectBlocks(body, lines)
	return _tidyText("\n".join(lines))


def readDocxText(filePath):
	try:
		with zipfile.ZipFile(filePath) as archive:
			info = archive.getinfo("word/document.xml")
			if info.file_size > _MAX_STREAM_BYTES:
				raise DocumentReadError("Document body is too large")
			xmlBytes = archive.read(info)
	except zipfile.BadZipFile as e:
		raise DocumentReadError("Not a valid docx archive (it may be password protected)") from e
	except KeyError as e:
		raise DocumentReadError("word/document.xml is missing") from e
	except OSError as e:
		raise DocumentReadError("Could not open document: " + str(e)[:80]) from e
	return docxXmlToText(xmlBytes)


def _cleanWordText(rawText):
	visible = []
	fieldStack = []
	for ch in rawText:
		if ch == "\x13":
			fieldStack.append(False)
			continue
		if ch == "\x14":
			if fieldStack:
				fieldStack[-1] = True
			continue
		if ch == "\x15":
			if fieldStack:
				fieldStack.pop()
			continue
		if fieldStack and not all(fieldStack):
			continue
		visible.append(ch)
	text = "".join(visible)
	text = text.replace("\x07\x07", "\n").replace("\x07", "\t")
	text = text.translate(_DOC_CONTROL_MAP)
	return _DOC_STRAY_CONTROLS.sub("", text)


def docStreamsToText(wordStream, tableStream):
	if len(wordStream) < 0x200:
		raise DocumentReadError("Word stream is too short")
	ident, nFib = struct.unpack_from("<HH", wordStream, 0)
	flags = struct.unpack_from("<H", wordStream, 0x0A)[0]
	if ident != 0xA5EC:
		raise DocumentReadError("Not a Word binary document")
	if flags & 0x0100:
		raise DocumentReadError("Document is encrypted")
	if nFib < 0xC1:
		raise DocumentReadError("Word 95 and older files are not supported")
	pos = 32
	swCount = struct.unpack_from("<H", wordStream, pos)[0]
	pos += 2 + swCount * 2
	lwCount = struct.unpack_from("<H", wordStream, pos)[0]
	lwStart = pos + 2
	pos = lwStart + lwCount * 4
	pairCount = struct.unpack_from("<H", wordStream, pos)[0]
	blobStart = pos + 2
	if lwCount < 4 or pairCount < 34:
		raise DocumentReadError("Unexpected Word header layout")
	textLength = struct.unpack_from("<I", wordStream, lwStart + 12)[0]
	clxOffset, clxLength = struct.unpack_from("<II", wordStream, blobStart + 33 * 8)
	clx = tableStream[clxOffset:clxOffset + clxLength]
	if not clx:
		raise DocumentReadError("Piece table is missing")

	idx = 0
	while idx + 3 <= len(clx) and clx[idx] == 0x01:
		idx += 3 + struct.unpack_from("<H", clx, idx + 1)[0]
	if idx + 5 > len(clx) or clx[idx] != 0x02:
		raise DocumentReadError("Piece table is malformed")
	plcLength = struct.unpack_from("<I", clx, idx + 1)[0]
	plc = clx[idx + 5:idx + 5 + plcLength]
	pieceCount = (len(plc) - 4) // 12
	if pieceCount < 1:
		raise DocumentReadError("Piece table is empty")
	charPositions = struct.unpack_from("<%dI" % (pieceCount + 1), plc, 0)
	descriptorBase = (pieceCount + 1) * 4

	chunks = []
	for n in range(pieceCount):
		startCp = charPositions[n]
		endCp = min(charPositions[n + 1], textLength)
		if startCp >= textLength:
			break
		if endCp <= startCp:
			continue
		charCount = endCp - startCp
		fcValue = struct.unpack_from("<I", plc, descriptorBase + n * 8 + 2)[0]
		if fcValue & 0x40000000:
			offset = (fcValue & 0x3FFFFFFF) // 2
			chunks.append(wordStream[offset:offset + charCount].decode("cp1252", errors="replace"))
		else:
			offset = fcValue & 0x3FFFFFFF
			chunks.append(wordStream[offset:offset + charCount * 2].decode("utf-16-le", errors="replace"))
	return _tidyText(_cleanWordText("".join(chunks)))


def readDocText(filePath):
	olefile = _loadBundledModule("olefile", ("olefile", "olefile.py"))
	try:
		ole = olefile.OleFileIO(filePath)
	except OSError as e:
		raise DocumentReadError("Not a valid Word binary file: " + str(e)[:80]) from e
	try:
		if not ole.exists("WordDocument"):
			raise DocumentReadError("WordDocument stream is missing")
		if ole.get_size("WordDocument") > _MAX_STREAM_BYTES:
			raise DocumentReadError("Document is too large")
		wordStream = ole.openstream("WordDocument").read()
		if len(wordStream) < 0x0C:
			raise DocumentReadError("Word stream is too short")
		tableName = "1Table" if struct.unpack_from("<H", wordStream, 0x0A)[0] & 0x0200 else "0Table"
		if not ole.exists(tableName):
			raise DocumentReadError("Table stream is missing")
		if ole.get_size(tableName) > _MAX_STREAM_BYTES:
			raise DocumentReadError("Document is too large")
		tableStream = ole.openstream(tableName).read()
	except OSError as e:
		raise DocumentReadError("Could not read Word streams: " + str(e)[:80]) from e
	finally:
		ole.close()
	try:
		return docStreamsToText(wordStream, tableStream)
	except struct.error as e:
		raise DocumentReadError("Word header is damaged") from e


def readDocumentText(filePath):
	try:
		with open(filePath, "rb") as f:
			header = f.read(8)
	except OSError as e:
		raise DocumentReadError("Could not open document: " + str(e)[:80]) from e
	if header.startswith(b"PK"):
		return readDocxText(filePath)
	if header.startswith(_OLE_MAGIC):
		return readDocText(filePath)
	if header.startswith(b"{\\rtf"):
		try:
			with open(filePath, "rb") as f:
				return rtfBytesToText(f.read())
		except OSError as e:
			raise DocumentReadError("Could not open document: " + str(e)[:80]) from e
	raise DocumentReadError("Unrecognized document format")

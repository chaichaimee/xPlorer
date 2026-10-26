# isoBuilder.py

import os
import stat
import struct
import time

SECTOR_SIZE = 2048
MAX_FILE_SIZE = 0xFFFFFFFF - (SECTOR_SIZE - 1)
JOLIET_MAX_UNITS = 64
_COPY_CHUNK = 1024 * 1024
_SKIPPED_REPARSE_TAGS = (0xA000000C, 0xA0000003)
_ISO_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_TREES = ("iso", "joliet")


class IsoError(Exception):
	pass


class IsoCancelled(Exception):
	pass


class _DirNode:
	def __init__(self, name, parent, mtime):
		self.name = name
		self.parent = parent
		self.mtime = mtime
		self.dirs = []
		self.files = []
		self.ident = {}
		self.lba = {"iso": 0, "joliet": 0}
		self.size = {"iso": 0, "joliet": 0}
		self.pathIndex = {"iso": 0, "joliet": 0}


class _FileNode:
	def __init__(self, path, size, mtime):
		self.path = path
		self.size = size
		self.mtime = mtime
		self.ident = {}
		self.lba = 0


def _both32(value):
	return struct.pack("<I", value) + struct.pack(">I", value)


def _both16(value):
	return struct.pack("<H", value) + struct.pack(">H", value)


def _sectors(byteCount):
	return (byteCount + SECTOR_SIZE - 1) // SECTOR_SIZE


def _recordDate(timestamp):
	parts = time.gmtime(max(timestamp, 0))
	return bytes([parts.tm_year - 1900, parts.tm_mon, parts.tm_mday, parts.tm_hour, parts.tm_min, parts.tm_sec, 0])


def _volumeDate(timestamp):
	return time.strftime("%Y%m%d%H%M%S", time.gmtime(timestamp)).encode("ascii") + b"00\x00"


def _isoChars(text):
	return "".join(c if c in _ISO_CHARS else "_" for c in text.upper())


def _uniqueIsoDirName(name, used):
	base = _isoChars(name)[:8] or "_"
	candidate = base
	attempt = 0
	while candidate in used:
		attempt += 1
		suffix = f"~{attempt}"
		candidate = base[:8 - len(suffix)] + suffix
	used.add(candidate)
	return candidate.encode("ascii")


def _uniqueIsoFileName(name, used):
	stem, extension = os.path.splitext(name)
	base = _isoChars(stem)[:8] or "_"
	suffixText = _isoChars(extension[1:])[:3]
	candidate = base
	attempt = 0
	while f"{candidate}.{suffixText};1" in used:
		attempt += 1
		marker = f"~{attempt}"
		candidate = base[:8 - len(marker)] + marker
	identifier = f"{candidate}.{suffixText};1"
	used.add(identifier)
	return identifier.encode("ascii")


def _utf16Units(text):
	return len(text.encode("utf-16-be")) // 2


def _uniqueJolietName(name, used):
	cleaned = "".join("_" if (c in '*/:;?\\' or ord(c) < 32) else c for c in name)
	stem, extension = os.path.splitext(cleaned)
	extension = extension[:16]
	while stem and _utf16Units(stem + extension) > JOLIET_MAX_UNITS:
		stem = stem[:-1]
	candidate = stem + extension
	attempt = 0
	while candidate.casefold() in used:
		attempt += 1
		marker = f"~{attempt}"
		trimmed = stem
		while trimmed and _utf16Units(trimmed + marker + extension) > JOLIET_MAX_UNITS:
			trimmed = trimmed[:-1]
		candidate = trimmed + marker + extension
	used.add(candidate.casefold())
	return candidate.encode("utf-16-be")


def _scanTree(rootPath, shouldStop, stats):
	root = _DirNode("", None, os.stat(rootPath).st_mtime)
	pending = [(root, rootPath)]
	while pending:
		node, path = pending.pop()
		if shouldStop():
			raise IsoCancelled()
		try:
			with os.scandir(path) as iterator:
				entries = list(iterator)
		except OSError:
			stats["skipped"] += 1
			continue
		for entry in entries:
			try:
				entryStat = entry.stat(follow_symlinks=False)
				if getattr(entryStat, "st_reparse_tag", 0) in _SKIPPED_REPARSE_TAGS or entry.is_symlink():
					stats["skipped"] += 1
					continue
				if entry.is_dir(follow_symlinks=False):
					child = _DirNode(entry.name, node, entryStat.st_mtime)
					node.dirs.append(child)
					pending.append((child, entry.path))
					stats["folders"] += 1
					continue
				if not stat.S_ISREG(entryStat.st_mode):
					stats["skipped"] += 1
					continue
				stats["largest"] = max(stats["largest"], entryStat.st_size)
				with open(entry.path, "rb"):
					pass
				node.files.append(_FileNode(entry.path, entryStat.st_size, entryStat.st_mtime))
				stats["files"] += 1
				stats["bytes"] += entryStat.st_size
			except OSError:
				stats["skipped"] += 1
	return root


def _iterDirs(root):
	pending = [root]
	while pending:
		node = pending.pop()
		yield node
		pending.extend(node.dirs)


def _assignNames(root):
	for node in _iterDirs(root):
		usedIso = set()
		usedJoliet = set()
		for child in sorted(node.dirs, key=lambda d: d.name):
			child.ident["iso"] = _uniqueIsoDirName(child.name, usedIso)
			child.ident["joliet"] = _uniqueJolietName(child.name, usedJoliet)
		for fileNode in sorted(node.files, key=lambda f: os.path.basename(f.path)):
			fileName = os.path.basename(fileNode.path)
			fileNode.ident["iso"] = _uniqueIsoFileName(fileName, usedIso)
			fileNode.ident["joliet"] = _uniqueJolietName(fileName, usedJoliet)


def _entries(node, tree):
	items = [(d.ident[tree], d, True) for d in node.dirs] + [(f.ident[tree], f, False) for f in node.files]
	items.sort(key=lambda item: item[0])
	return items


def _dirRecord(extent, length, timestamp, isDir, identifier):
	idLength = len(identifier)
	recordLength = 33 + idLength + (1 if idLength % 2 == 0 else 0)
	record = bytearray(recordLength)
	record[0] = recordLength
	record[2:10] = _both32(extent)
	record[10:18] = _both32(length)
	record[18:25] = _recordDate(timestamp)
	record[25] = 2 if isDir else 0
	record[28:32] = _both16(1)
	record[32] = idLength
	record[33:33 + idLength] = identifier
	return bytes(record)


def _packRecords(records):
	packed = bytearray()
	for record in records:
		room = SECTOR_SIZE - (len(packed) % SECTOR_SIZE)
		if len(record) > room:
			packed += b"\x00" * room
		packed += record
	if len(packed) % SECTOR_SIZE:
		packed += b"\x00" * (SECTOR_SIZE - len(packed) % SECTOR_SIZE)
	return bytes(packed)


def _buildDirExtent(node, tree):
	parent = node.parent or node
	records = [
		_dirRecord(node.lba[tree], node.size[tree], node.mtime, True, b"\x00"),
		_dirRecord(parent.lba[tree], parent.size[tree], parent.mtime, True, b"\x01"),
	]
	for identifier, item, isDir in _entries(node, tree):
		if isDir:
			records.append(_dirRecord(item.lba[tree], item.size[tree], item.mtime, True, identifier))
		else:
			records.append(_dirRecord(item.lba, item.size, item.mtime, False, identifier))
	return _packRecords(records)


def _pathTableOrder(root, tree):
	order = [root]
	root.pathIndex[tree] = 1
	current = [root]
	while current:
		nextLevel = []
		for parent in current:
			nextLevel.extend(item for _ident, item, isDir in _entries(parent, tree) if isDir)
		for node in nextLevel:
			order.append(node)
			node.pathIndex[tree] = len(order)
		current = nextLevel
	return order


def _buildPathTable(order, tree, bigEndian):
	longFormat = ">I" if bigEndian else "<I"
	shortFormat = ">H" if bigEndian else "<H"
	table = bytearray()
	for node in order:
		identifier = b"\x00" if node.parent is None else node.ident[tree]
		parentIndex = 1 if node.parent is None else node.parent.pathIndex[tree]
		record = bytes([len(identifier), 0]) + struct.pack(longFormat, node.lba[tree])
		record += struct.pack(shortFormat, parentIndex) + identifier
		if len(identifier) % 2:
			record += b"\x00"
		table += record
	return bytes(table)


def _textField(text, size, joliet):
	if joliet:
		encoded = text.encode("utf-16-be")[:size]
		return encoded + b"\x00\x20" * ((size - len(encoded)) // 2)
	encoded = text.encode("ascii", "replace")[:size]
	return encoded + b" " * (size - len(encoded))


def _volumeDescriptor(joliet, totalSectors, label, tableSize, tableLbas, root, now):
	tree = "joliet" if joliet else "iso"
	descriptor = bytearray(SECTOR_SIZE)
	descriptor[0] = 2 if joliet else 1
	descriptor[1:6] = b"CD001"
	descriptor[6] = 1
	descriptor[8:40] = _textField("", 32, joliet)
	descriptor[40:72] = _textField(label, 32, joliet)
	descriptor[80:88] = _both32(totalSectors)
	if joliet:
		descriptor[88:91] = b"%/E"
	descriptor[120:124] = _both16(1)
	descriptor[124:128] = _both16(1)
	descriptor[128:132] = _both16(SECTOR_SIZE)
	descriptor[132:140] = _both32(tableSize)
	descriptor[140:144] = struct.pack("<I", tableLbas[(tree, "L")])
	descriptor[148:152] = struct.pack(">I", tableLbas[(tree, "M")])
	descriptor[156:190] = _dirRecord(root.lba[tree], root.size[tree], root.mtime, True, b"\x00")
	for start in (190, 318, 446, 574):
		descriptor[start:start + 128] = _textField("", 128, joliet)
	for start in (702, 739, 776):
		descriptor[start:start + 37] = b"\x00" * 37 if joliet else b" " * 37
	descriptor[813:830] = _volumeDate(now)
	descriptor[830:847] = _volumeDate(now)
	descriptor[847:864] = b"0000000000000000\x00"
	descriptor[864:881] = b"0000000000000000\x00"
	descriptor[881] = 1
	return bytes(descriptor)


def _copyFile(out, fileNode, shouldStop, progress):
	remaining = fileNode.size
	with open(fileNode.path, "rb") as source:
		while remaining > 0:
			if shouldStop():
				raise IsoCancelled()
			chunk = source.read(min(_COPY_CHUNK, remaining))
			if not chunk:
				out.write(b"\x00" * remaining)
				progress(remaining)
				break
			out.write(chunk)
			remaining -= len(chunk)
			progress(len(chunk))
	padding = (-fileNode.size) % SECTOR_SIZE
	if padding:
		out.write(b"\x00" * padding)


def buildIso(sourceFolder, outputPath, volumeLabel, shouldStop, onPlan=None, mode="auto", onProgress=None):
	stats = {"skipped": 0, "files": 0, "folders": 0, "bytes": 0, "largest": 0}
	root = _scanTree(sourceFolder, shouldStop, stats)
	useUdf = mode == "udf" or (mode == "auto" and stats["largest"] > MAX_FILE_SIZE)
	if mode == "iso" and stats["largest"] > MAX_FILE_SIZE:
		raise IsoError("A file is larger than the 4 GB limit of a standard ISO")
	if useUdf:
		stats["format"] = "UDF"
		return _buildUdf(root, outputPath, volumeLabel, shouldStop, onPlan, stats, onProgress)
	stats["format"] = "ISO"
	_assignNames(root)
	allDirs = list(_iterDirs(root))
	orders = {tree: _pathTableOrder(root, tree) for tree in _TREES}
	for tree in _TREES:
		for node in allDirs:
			node.size[tree] = len(_buildDirExtent(node, tree))

	tableSizes = {tree: len(_buildPathTable(orders[tree], tree, False)) for tree in _TREES}
	nextLba = 19
	tableLbas = {}
	for tree in _TREES:
		for endian in ("L", "M"):
			tableLbas[(tree, endian)] = nextLba
			nextLba += _sectors(tableSizes[tree])
	for tree in _TREES:
		for node in orders[tree]:
			node.lba[tree] = nextLba
			nextLba += node.size[tree] // SECTOR_SIZE
	orderedFiles = []
	for node in orders["iso"]:
		orderedFiles.extend(item for _ident, item, isDir in _entries(node, "iso") if not isDir)
	for fileNode in orderedFiles:
		fileNode.lba = nextLba
		nextLba += _sectors(fileNode.size)
	totalSectors = nextLba
	if onPlan:
		onPlan(totalSectors * SECTOR_SIZE, stats)

	now = time.time()
	isoLabel = _isoChars(volumeLabel)[:32] or "CDROM"
	jolietLabel = "".join("_" if (c in '*/:;?\\' or ord(c) < 32) else c for c in volumeLabel)[:16] or "CDROM"
	terminator = bytearray(SECTOR_SIZE)
	terminator[0] = 255
	terminator[1:6] = b"CD001"
	terminator[6] = 1

	done = [0]
	lastReport = [0.0]

	def progress(count):
		done[0] += count
		if onProgress:
			tick = time.monotonic()
			if tick - lastReport[0] >= 0.25:
				lastReport[0] = tick
				onProgress(done[0], stats["bytes"])

	with open(outputPath, "wb") as out:
		out.write(b"\x00" * (SECTOR_SIZE * 16))
		out.write(_volumeDescriptor(False, totalSectors, isoLabel, tableSizes["iso"], tableLbas, root, now))
		out.write(_volumeDescriptor(True, totalSectors, jolietLabel, tableSizes["joliet"], tableLbas, root, now))
		out.write(bytes(terminator))
		for tree in _TREES:
			for bigEndian in (False, True):
				table = _buildPathTable(orders[tree], tree, bigEndian)
				out.write(table + b"\x00" * (_sectors(len(table)) * SECTOR_SIZE - len(table)))
		for tree in _TREES:
			for node in orders[tree]:
				out.write(_buildDirExtent(node, tree))
		for fileNode in orderedFiles:
			_copyFile(out, fileNode, shouldStop, progress)
		if out.tell() != totalSectors * SECTOR_SIZE:
			raise IsoError("Image size did not match the planned layout")
	stats["sectors"] = totalSectors
	return stats


_UDF_MAX_EXTENT = (1 << 30) - SECTOR_SIZE
_UDF_PARTITION_START = 257
_UDF_FILE_ENTRY_SIZE = 176
_UDF_MAX_EXTENTS = (SECTOR_SIZE - _UDF_FILE_ENTRY_SIZE) // 8


def _buildCrcTable():
	table = []
	for value in range(256):
		crc = value << 8
		for _bit in range(8):
			crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
		table.append(crc)
	return table


_CRC_TABLE = _buildCrcTable()


def _crc16(data):
	crc = 0
	for byte in data:
		crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ byte) & 0xFF]
	return crc


def _udfDescriptor(identifier, body, location):
	descriptor = bytearray(16) + bytearray(body)
	struct.pack_into("<HH", descriptor, 0, identifier, 2)
	struct.pack_into("<HH", descriptor, 8, _crc16(bytes(body)), len(body))
	struct.pack_into("<I", descriptor, 12, location)
	descriptor[4] = sum(descriptor[index] for index in range(16) if index != 4) & 0xFF
	return bytes(descriptor)


def _sectorPad(data):
	remainder = len(data) % SECTOR_SIZE
	return data if remainder == 0 else data + b"\x00" * (SECTOR_SIZE - remainder)


def _udfTimestamp(timestamp):
	parts = time.gmtime(max(timestamp, 0))
	return struct.pack("<HHBBBBBBBB", 0x1000, parts.tm_year, parts.tm_mon, parts.tm_mday,
		parts.tm_hour, parts.tm_min, parts.tm_sec, 0, 0, 0)


def _entityId(identifier, suffix=b""):
	return b"\x00" + identifier.encode("ascii")[:23].ljust(23, b"\x00") + suffix.ljust(8, b"\x00")


_UDF_DOMAIN_ID = _entityId("*OSTA UDF Compliant", struct.pack("<HB", 0x0102, 0))
_UDF_IMPL_ID = _entityId("*xPlorer ISO Writer", struct.pack("<HB", 0x0102, 0))
_UDF_CHARSPEC = b"\x00" + b"OSTA Compressed Unicode".ljust(63, b"\x00")


def _compressUnicode(text):
	if all(ord(c) < 256 for c in text):
		return b"\x08" + text.encode("latin-1")
	return b"\x10" + text.encode("utf-16-be")


def _fitUnicode(text, maxBytes):
	while text and len(_compressUnicode(text)) > maxBytes:
		text = text[:-1]
	return _compressUnicode(text) if text else b""


def _dstring(text, size):
	encoded = _fitUnicode(text, size - 1)
	return encoded.ljust(size - 1, b"\x00") + bytes([len(encoded)])


def _uniqueUdfName(name, used):
	cleaned = "".join("_" if ord(c) < 32 else c for c in name)
	stem, extension = os.path.splitext(cleaned)
	extension = extension[:16]
	while stem and len(_compressUnicode(stem + extension)) > 255:
		stem = stem[:-1]
	candidate = stem + extension
	attempt = 0
	while candidate.casefold() in used:
		attempt += 1
		marker = f"~{attempt}"
		trimmed = stem
		while trimmed and len(_compressUnicode(trimmed + marker + extension)) > 255:
			trimmed = trimmed[:-1]
		candidate = trimmed + marker + extension
	used.add(candidate.casefold())
	return _compressUnicode(candidate)


def _longAd(length, block, partition=0):
	return struct.pack("<IIH6s", length, block, partition, b"")


def _udfPrimaryDescriptor(sequence, label, setId, now, location):
	body = bytearray(496)
	struct.pack_into("<II", body, 0, sequence, 0)
	body[8:40] = _dstring(label, 32)
	struct.pack_into("<HHHH", body, 40, 1, 1, 2, 3)
	struct.pack_into("<II", body, 48, 1, 1)
	body[56:184] = _dstring(setId, 128)
	body[184:248] = _UDF_CHARSPEC
	body[248:312] = _UDF_CHARSPEC
	body[328:360] = _UDF_IMPL_ID
	body[360:372] = _udfTimestamp(now)
	body[372:404] = _UDF_IMPL_ID
	return _sectorPad(_udfDescriptor(1, body, location))


def _udfImplUseDescriptor(sequence, label, location):
	body = bytearray(496)
	struct.pack_into("<I", body, 0, sequence)
	body[4:36] = _entityId("*UDF LV Info", struct.pack("<HB", 0x0102, 0))
	body[36:100] = _UDF_CHARSPEC
	body[100:228] = _dstring(label, 128)
	body[336:368] = _UDF_IMPL_ID
	return _sectorPad(_udfDescriptor(4, body, location))


def _udfPartitionDescriptor(sequence, startSector, blockCount, location):
	body = bytearray(496)
	struct.pack_into("<IHH", body, 0, sequence, 1, 0)
	body[8:40] = _entityId("+NSR02")
	struct.pack_into("<III", body, 168, 1, startSector, blockCount)
	body[180:212] = _UDF_IMPL_ID
	return _sectorPad(_udfDescriptor(5, body, location))


def _udfLogicalVolumeDescriptor(sequence, label, integritySector, location):
	body = bytearray(430)
	struct.pack_into("<I", body, 0, sequence)
	body[4:68] = _UDF_CHARSPEC
	body[68:196] = _dstring(label, 128)
	struct.pack_into("<I", body, 196, SECTOR_SIZE)
	body[200:232] = _UDF_DOMAIN_ID
	body[232:248] = _longAd(SECTOR_SIZE, 0)
	struct.pack_into("<II", body, 248, 6, 1)
	body[256:288] = _UDF_IMPL_ID
	struct.pack_into("<II", body, 416, 2 * SECTOR_SIZE, integritySector)
	body[424:430] = bytes([1, 6]) + struct.pack("<HH", 1, 0)
	return _sectorPad(_udfDescriptor(6, body, location))


def _udfUnallocatedDescriptor(sequence, location):
	body = struct.pack("<II", sequence, 0)
	return _sectorPad(_udfDescriptor(7, body, location))


def _udfTerminator(location):
	return _sectorPad(_udfDescriptor(8, bytes(496), location))


def _udfIntegrityDescriptor(now, partitionBlocks, fileCount, dirCount, uniqueId, location):
	body = bytearray(118)
	body[0:12] = _udfTimestamp(now)
	struct.pack_into("<I", body, 12, 1)
	struct.pack_into("<Q", body, 24, uniqueId)
	struct.pack_into("<III", body, 56, 1, 46, 0)
	struct.pack_into("<I", body, 68, partitionBlocks)
	body[72:104] = _UDF_IMPL_ID
	struct.pack_into("<IIHHH", body, 104, fileCount, dirCount, 0x0102, 0x0102, 0x0102)
	return _sectorPad(_udfDescriptor(9, body, location))


def _udfAnchor(location):
	body = bytearray(496)
	struct.pack_into("<IIII", body, 0, 16 * SECTOR_SIZE, 32, 16 * SECTOR_SIZE, 48)
	return _sectorPad(_udfDescriptor(2, body, location))


def _udfFileSetDescriptor(label, rootBlock, now):
	body = bytearray(496)
	body[0:12] = _udfTimestamp(now)
	struct.pack_into("<HHIIII", body, 12, 3, 3, 1, 1, 0, 0)
	body[32:96] = _UDF_CHARSPEC
	body[96:224] = _dstring(label, 128)
	body[224:288] = _UDF_CHARSPEC
	body[288:320] = _dstring(label, 32)
	body[384:400] = _longAd(SECTOR_SIZE, rootBlock)
	body[400:432] = _UDF_DOMAIN_ID
	return _sectorPad(_udfDescriptor(256, body, 0))


def _udfFileEntry(block, isDir, infoLength, blocksRecorded, timestamp, uniqueId, linkCount, extents):
	allocation = b"".join(struct.pack("<II", length, position) for length, position in extents)
	body = bytearray(160)
	struct.pack_into("<IHHHBB", body, 0, 0, 4, 0, 1, 0, 4 if isDir else 5)
	struct.pack_into("<I", body, 20, 0xFFFFFFFF)
	struct.pack_into("<I", body, 24, 0xFFFFFFFF)
	struct.pack_into("<I", body, 28, 0x14A5)
	struct.pack_into("<H", body, 32, linkCount)
	struct.pack_into("<QQ", body, 40, infoLength, blocksRecorded)
	stamp = _udfTimestamp(timestamp)
	body[56:68] = stamp
	body[68:80] = stamp
	body[80:92] = stamp
	struct.pack_into("<I", body, 92, 1)
	body[112:144] = _UDF_IMPL_ID
	struct.pack_into("<Q", body, 144, uniqueId)
	struct.pack_into("<II", body, 152, 0, len(allocation))
	return _sectorPad(_udfDescriptor(261, bytes(body) + allocation, block))


def _udfFileIdentifier(characteristics, nameBytes, entryBlock, location):
	total = 38 + len(nameBytes)
	body = bytearray(total - 16 + (-total) % 4)
	struct.pack_into("<HBB", body, 0, 1, characteristics, len(nameBytes))
	body[4:20] = _longAd(SECTOR_SIZE, entryBlock)
	body[22:22 + len(nameBytes)] = nameBytes
	return _udfDescriptor(257, body, location)


def _fidLength(nameBytes):
	return (38 + len(nameBytes) + 3) // 4 * 4


def _splitExtents(size, firstBlock):
	extents = []
	position = firstBlock
	remaining = size
	while remaining > 0:
		length = min(remaining, _UDF_MAX_EXTENT)
		extents.append((length, position))
		position += _sectors(length)
		remaining -= length
	return extents


def _buildUdf(root, outputPath, volumeLabel, shouldStop, onPlan, stats, onProgress=None):
	dirs = list(_iterDirs(root))
	files = []
	for node in dirs:
		used = set()
		for child in sorted(node.dirs, key=lambda d: d.name.casefold()):
			child.ident["udf"] = _uniqueUdfName(child.name, used)
		for fileNode in sorted(node.files, key=lambda f: os.path.basename(f.path).casefold()):
			fileNode.ident["udf"] = _uniqueUdfName(os.path.basename(fileNode.path), used)
			files.append(fileNode)
	nodes = dirs + files
	block = 2
	for node in nodes:
		node.feBlock = block
		block += 1
	for node in dirs:
		node.dirSize = 40 + sum(_fidLength(item.ident["udf"]) for item in node.dirs + node.files)
		node.dataBlock = block
		block += _sectors(node.dirSize)
	for fileNode in files:
		extents = _splitExtents(fileNode.size, block)
		if len(extents) > _UDF_MAX_EXTENTS:
			raise IsoError("File is too large for the UDF writer: " + os.path.basename(fileNode.path))
		fileNode.extents = extents
		fileNode.dataBlock = block
		block += _sectors(fileNode.size)
	partitionBlocks = block
	totalSectors = _UDF_PARTITION_START + partitionBlocks + 1
	if onPlan:
		onPlan(totalSectors * SECTOR_SIZE, stats)

	now = time.time()
	label = volumeLabel or "CDROM"
	setId = os.urandom(8).hex().upper()
	uniqueIds = {}
	nextUnique = 16
	for node in nodes:
		if node is root:
			uniqueIds[id(node)] = 0
		else:
			uniqueIds[id(node)] = nextUnique
			nextUnique += 1

	def volumeStructure(identifier):
		sector = bytearray(SECTOR_SIZE)
		sector[1:6] = identifier
		sector[6] = 1
		return bytes(sector)

	def descriptorSequence(startSector):
		return (
			_udfPrimaryDescriptor(0, label, setId, now, startSector)
			+ _udfImplUseDescriptor(1, label, startSector + 1)
			+ _udfPartitionDescriptor(2, _UDF_PARTITION_START, partitionBlocks, startSector + 2)
			+ _udfLogicalVolumeDescriptor(3, label, 64, startSector + 3)
			+ _udfUnallocatedDescriptor(4, startSector + 4)
			+ _udfTerminator(startSector + 5)
		)

	done = [0]
	lastReport = [0.0]

	def progress(count):
		done[0] += count
		if onProgress:
			tick = time.monotonic()
			if tick - lastReport[0] >= 0.25:
				lastReport[0] = tick
				onProgress(done[0], stats["bytes"])

	with open(outputPath, "wb") as out:
		zeros = lambda count: out.write(b"\x00" * (SECTOR_SIZE * count))
		zeros(16)
		out.write(volumeStructure(b"BEA01"))
		out.write(volumeStructure(b"NSR02"))
		out.write(volumeStructure(b"TEA01"))
		zeros(13)
		out.write(descriptorSequence(32))
		zeros(10)
		out.write(descriptorSequence(48))
		zeros(10)
		out.write(_udfIntegrityDescriptor(now, partitionBlocks, len(files), len(dirs), nextUnique, 64))
		out.write(_udfTerminator(65))
		zeros(190)
		out.write(_udfAnchor(256))
		out.write(_udfFileSetDescriptor(label, root.feBlock, now))
		out.write(_udfTerminator(1))
		for node in dirs:
			out.write(_udfFileEntry(node.feBlock, True, node.dirSize, _sectors(node.dirSize), node.mtime,
				uniqueIds[id(node)], 1 + len(node.dirs), [(node.dirSize, node.dataBlock)]))
		for fileNode in files:
			out.write(_udfFileEntry(fileNode.feBlock, False, fileNode.size, _sectors(fileNode.size),
				fileNode.mtime, uniqueIds[id(fileNode)], 1, fileNode.extents))
		for node in dirs:
			parent = node.parent or node
			stream = bytearray(_udfFileIdentifier(0x0A, b"", parent.feBlock, node.dataBlock))
			children = sorted(
				[(d.ident["udf"], d, True) for d in node.dirs] + [(f.ident["udf"], f, False) for f in node.files],
				key=lambda item: item[0]
			)
			for nameBytes, child, isDir in children:
				location = node.dataBlock + len(stream) // SECTOR_SIZE
				stream += _udfFileIdentifier(0x02 if isDir else 0, nameBytes, child.feBlock, location)
			out.write(_sectorPad(bytes(stream)))
		for fileNode in files:
			_copyFile(out, fileNode, shouldStop, progress)
		out.write(_udfAnchor(totalSectors - 1))
		if out.tell() != totalSectors * SECTOR_SIZE:
			raise IsoError("Image size did not match the planned layout")
	stats["sectors"] = totalSectors
	return stats

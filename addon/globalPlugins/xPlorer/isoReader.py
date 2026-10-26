# isoReader.py

import os
import re
import struct

SECTOR_SIZE = 2048
_COPY_CHUNK = 1024 * 1024
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class IsoReadError(Exception):
	pass


class IsoReadCancelled(Exception):
	pass


def _safeName(name):
	cleaned = _INVALID_NAME_CHARS.sub("_", name).rstrip(" .")
	if cleaned in ("", ".", ".."):
		return "_"
	return cleaned


def _uniquePath(directory, name, taken):
	candidate = name
	counter = 1
	while candidate.casefold() in taken:
		counter += 1
		stem, extension = os.path.splitext(name)
		candidate = f"{stem} ({counter}){extension}"
	taken.add(candidate.casefold())
	return os.path.join(directory, candidate)


class _Extractor:
	def __init__(self, source, targetDir, shouldStop):
		self._source = source
		self._targetDir = targetDir
		self._shouldStop = shouldStop
		self.fileCount = 0
		self.folderCount = 0
		self.byteCount = 0

	def makeDir(self, directory):
		os.makedirs(directory, exist_ok=True)
		self.folderCount += 1

	def writeFile(self, path, extents):
		with open(path, "wb") as out:
			for offset, length in extents:
				if offset is None:
					self._writeZeros(out, length)
					continue
				self._source.seek(offset)
				remaining = length
				while remaining > 0:
					if self._shouldStop():
						raise IsoReadCancelled()
					chunk = self._source.read(min(_COPY_CHUNK, remaining))
					if not chunk:
						raise IsoReadError("The image ended before all file data was found")
					out.write(chunk)
					remaining -= len(chunk)
					self.byteCount += len(chunk)
		self.fileCount += 1

	def _writeZeros(self, out, length):
		while length > 0:
			count = min(length, _COPY_CHUNK)
			out.write(b"\x00" * count)
			length -= count
			self.byteCount += count


def _readSector(source, sector, count=1):
	source.seek(sector * SECTOR_SIZE)
	data = source.read(SECTOR_SIZE * count)
	if len(data) < SECTOR_SIZE * count:
		raise IsoReadError("The image is truncated")
	return data


def _tagIdentifier(data):
	if len(data) < 16:
		return None
	checksum = sum(data[index] for index in range(16) if index != 4) & 0xFF
	if checksum != data[4]:
		return None
	return struct.unpack_from("<H", data, 0)[0]


def _hasUdf(source):
	try:
		return _tagIdentifier(_readSector(source, 256)) == 2
	except IsoReadError:
		return False


def _findIsoDescriptor(source):
	primary = None
	joliet = None
	for sector in range(16, 48):
		try:
			descriptor = _readSector(source, sector)
		except IsoReadError:
			break
		if descriptor[1:6] != b"CD001":
			break
		kind = descriptor[0]
		if kind == 255:
			break
		if kind == 1 and primary is None:
			primary = descriptor
		elif kind == 2 and descriptor[88:91] in (b"%/@", b"%/C", b"%/E"):
			joliet = descriptor
	return primary, joliet


def _extractIso9660(source, descriptor, isJoliet, extractor, targetDir):
	rootExtent = struct.unpack_from("<I", descriptor, 156 + 2)[0]
	rootLength = struct.unpack_from("<I", descriptor, 156 + 10)[0]
	pending = [(rootExtent, rootLength, targetDir)]
	visited = set()
	while pending:
		extent, length, directory = pending.pop()
		if extent in visited:
			continue
		visited.add(extent)
		extractor.makeDir(directory)
		source.seek(extent * SECTOR_SIZE)
		data = source.read(length)
		taken = set()
		position = 0
		partial = None
		while position < len(data):
			recordLength = data[position]
			if recordLength == 0:
				position = (position // SECTOR_SIZE + 1) * SECTOR_SIZE
				continue
			record = data[position:position + recordLength]
			position += recordLength
			idLength = record[32]
			identifier = record[33:33 + idLength]
			if identifier in (b"\x00", b"\x01"):
				continue
			start = struct.unpack_from("<I", record, 2)[0]
			size = struct.unpack_from("<I", record, 10)[0]
			flags = record[25]
			name = identifier.decode("utf-16-be", "replace") if isJoliet else identifier.decode("latin-1")
			name = name.split(";")[0]
			if name.endswith(".") and not isJoliet:
				name = name[:-1]
			if flags & 2:
				pending.append((start, size, _uniquePath(directory, _safeName(name), taken)))
				continue
			segment = (start * SECTOR_SIZE, size)
			if partial is not None:
				partial[1].append(segment)
				if not flags & 0x80:
					extractor.writeFile(partial[0], partial[1])
					partial = None
				continue
			path = _uniquePath(directory, _safeName(name), taken)
			if flags & 0x80:
				partial = (path, [segment])
			else:
				extractor.writeFile(path, [segment])


class _UdfImage:
	def __init__(self, source):
		self._source = source
		self.partitionStart = None
		self.rootIcb = None

	def load(self):
		anchor = _readSector(self._source, 256)
		if _tagIdentifier(anchor) != 2:
			raise IsoReadError("No UDF anchor found")
		length, location = struct.unpack_from("<II", anchor, 16)
		fileSetLocation = None
		sector = location
		for _index in range(max(1, length // SECTOR_SIZE)):
			descriptor = _readSector(self._source, sector)
			identifier = _tagIdentifier(descriptor)
			sector += 1
			if identifier == 5:
				self.partitionStart = struct.unpack_from("<I", descriptor, 188)[0]
			elif identifier == 6:
				fileSetLocation = struct.unpack_from("<I", descriptor, 252)[0]
				mapCount = struct.unpack_from("<I", descriptor, 268)[0]
				if mapCount != 1 or descriptor[440] != 1:
					raise IsoReadError("Only simple UDF partitions are supported")
			elif identifier == 8:
				break
		if self.partitionStart is None or fileSetLocation is None:
			raise IsoReadError("The UDF volume structure is incomplete")
		fileSet = self.readBlock(fileSetLocation)
		if _tagIdentifier(fileSet) != 256:
			raise IsoReadError("The UDF file set descriptor is missing")
		self.rootIcb = struct.unpack_from("<I", fileSet, 404)[0]

	def readBlock(self, block, count=1):
		return _readSector(self._source, self.partitionStart + block, count)

	def entry(self, block):
		data = self.readBlock(block)
		identifier = _tagIdentifier(data)
		if identifier not in (261, 266):
			raise IsoReadError("A UDF file entry is damaged")
		fileType = data[27]
		allocationType = struct.unpack_from("<H", data, 34)[0] & 7
		if identifier == 261:
			infoLength = struct.unpack_from("<Q", data, 56)[0]
			eaLength, adLength = struct.unpack_from("<II", data, 168)
			adStart = 176 + eaLength
		else:
			infoLength = struct.unpack_from("<Q", data, 56)[0]
			eaLength, adLength = struct.unpack_from("<II", data, 208)
			adStart = 216 + eaLength
		descriptors = data[adStart:adStart + adLength]
		if allocationType == 3:
			return fileType, infoLength, [("embedded", descriptors[:infoLength])]
		return fileType, infoLength, self._extents(allocationType, descriptors, infoLength)

	def _extents(self, allocationType, descriptors, infoLength):
		if allocationType not in (0, 1):
			raise IsoReadError("Unsupported UDF allocation type")
		step = 8 if allocationType == 0 else 16
		extents = []
		remaining = infoLength
		queue = bytes(descriptors)
		while queue and remaining > 0:
			rawLength, position = struct.unpack_from("<II", queue, 0)
			queue = queue[step:]
			extentType = rawLength >> 30
			length = rawLength & 0x3FFFFFFF
			if length == 0:
				continue
			if extentType == 3:
				block = self.readBlock(position)
				if _tagIdentifier(block) != 258:
					raise IsoReadError("A UDF allocation extent is damaged")
				continuation = struct.unpack_from("<I", block, 20)[0]
				queue = block[24:24 + continuation] + queue
				continue
			take = min(length, remaining)
			if extentType == 0:
				extents.append(((self.partitionStart + position) * SECTOR_SIZE, take))
			else:
				extents.append((None, take))
			remaining -= take
		return extents

	def readStream(self, extents):
		chunks = []
		for item in extents:
			if item[0] == "embedded":
				chunks.append(item[1])
				continue
			offset, length = item
			if offset is None:
				chunks.append(b"\x00" * length)
			else:
				self._source.seek(offset)
				chunks.append(self._source.read(length))
		return b"".join(chunks)


def _decodeUdfName(raw):
	if not raw:
		return ""
	compression = raw[0]
	body = raw[1:]
	if compression == 8:
		return body.decode("latin-1")
	if compression == 16:
		return body.decode("utf-16-be", "replace")
	return body.decode("utf-8", "replace")


def _extractUdf(source, extractor, targetDir):
	image = _UdfImage(source)
	image.load()
	pending = [(image.rootIcb, targetDir)]
	visited = set()
	while pending:
		block, directory = pending.pop()
		if block in visited:
			continue
		visited.add(block)
		extractor.makeDir(directory)
		_fileType, _info, extents = image.entry(block)
		stream = image.readStream(extents)
		taken = set()
		position = 0
		while position + 38 <= len(stream):
			if struct.unpack_from("<H", stream, position)[0] != 257:
				break
			characteristics = stream[position + 18]
			nameLength = stream[position + 19]
			childBlock = struct.unpack_from("<I", stream, position + 24)[0]
			implLength = struct.unpack_from("<H", stream, position + 36)[0]
			nameStart = position + 38 + implLength
			rawName = stream[nameStart:nameStart + nameLength]
			position += (38 + implLength + nameLength + 3) // 4 * 4
			if characteristics & 0x0C:
				continue
			name = _safeName(_decodeUdfName(rawName))
			path = _uniquePath(directory, name, taken)
			fileType, infoLength, childExtents = image.entry(childBlock)
			if fileType == 4:
				pending.append((childBlock, path))
			elif fileType == 5:
				if childExtents and childExtents[0][0] == "embedded":
					with open(path, "wb") as out:
						out.write(childExtents[0][1])
					extractor.fileCount += 1
					extractor.byteCount += len(childExtents[0][1])
				else:
					extractor.writeFile(path, childExtents)


def extractIso(isoPath, targetDir, shouldStop):
	extractor = None
	with open(isoPath, "rb") as source:
		extractor = _Extractor(source, targetDir, shouldStop)
		if _hasUdf(source):
			_extractUdf(source, extractor, targetDir)
		else:
			primary, joliet = _findIsoDescriptor(source)
			descriptor = joliet or primary
			if descriptor is None:
				raise IsoReadError("This file is not a supported disc image")
			_extractIso9660(source, descriptor, joliet is not None, extractor, targetDir)
	return {"files": extractor.fileCount, "folders": extractor.folderCount, "bytes": extractor.byteCount}

import ctypes.wintypes
from logHandler import log
from brailleDisplayDrivers.hidBrailleStandard import HidBrailleDriver
import bdDetect
import math
import ctypes
from enum import Enum
import math
import braille
import inputCore
import itertools
from bdDetect import HID_USAGE_PAGE_BRAILLE
from hwIo import hid
import hidpi
import hwPortUtils

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
hidDll = ctypes.windll.hid

CM_Get_Parent = ctypes.windll.cfgmgr32.CM_Get_Parent
CM_Get_Parent.argtypes = [ctypes.POINTER(hwPortUtils.DWORD), hwPortUtils.DWORD, ctypes.c_ulong]
CM_Get_Parent.restype = hwPortUtils.DWORD

SetupDiOpenDeviceInfoW = ctypes.windll.setupapi.SetupDiOpenDeviceInfoW 
SetupDiOpenDeviceInfoW.argtypes = [hwPortUtils.HDEVINFO,
	ctypes.wintypes.LPCWSTR,
	hwPortUtils.HWND,
	hwPortUtils.DWORD,
	ctypes.POINTER(hwPortUtils.SP_DEVINFO_DATA)]
SetupDiOpenDeviceInfoW.restype = ctypes.c_bool

def getParent(child_dev_inst: hwPortUtils.SP_DEVINFO_DATA, g_hdi: hwPortUtils.HDEVINFO) -> hwPortUtils.SP_DEVINFO_DATA:
	buf = ctypes.create_unicode_buffer(1024)

	parent_dev_inst = hwPortUtils.DWORD()
	ret = CM_Get_Parent(ctypes.byref(parent_dev_inst), child_dev_inst.DevInst, ctypes.c_ulong(0))
	if ret != 0:
		raise ctypes.WinError(ctypes.get_last_error())

	ret = hwPortUtils.CM_Get_Device_ID(parent_dev_inst, buf, ctypes.sizeof(buf) - 1, 0)
	if ret != 0:
		raise ctypes.WinError(ctypes.get_last_error())
	
	parent_devinfo_data = hwPortUtils.SP_DEVINFO_DATA()
	parent_devinfo_data.cbSize = ctypes.sizeof(hwPortUtils.SP_DEVINFO_DATA)
	ret = SetupDiOpenDeviceInfoW(g_hdi, buf.value, None, 0, ctypes.byref(parent_devinfo_data))
	if not ret:
		raise ctypes.WinError(ctypes.get_last_error())
	
	return parent_devinfo_data

def getName(dev_inst: hwPortUtils.SP_DEVINFO_DATA, g_hdi: hwPortUtils.HDEVINFO) -> str:
	buf = ctypes.create_unicode_buffer(1024)
	DEVPKEY_NAME = hwPortUtils.DEVPROPKEY(hwPortUtils.GUID("{b725f130-47ef-101a-a5f1-02608c9eebac}"), 10)
	propRegDataType = hwPortUtils.DWORD()
	if not hwPortUtils.SetupDiGetDeviceProperty(
		g_hdi,
		ctypes.byref(dev_inst),
		ctypes.byref(DEVPKEY_NAME),
		ctypes.byref(propRegDataType),
		ctypes.byref(buf),
		ctypes.sizeof(buf) - 1,
		None,
		0,
	):
		raise ctypes.WinError(ctypes.get_last_error())
	else:
		return buf.value


# device buttons
class MiniKey(Enum):
	DPadUp = 25
	DPadDown = 26
	DPadRight = 28
	DPadLeft = 27
	DPadCenter = 24
	PanRight = 20
	PanLeft = 18
	Row1 = 32
	Row2 = 33
	Row3 = 34
	Row4 = 35
	Dot1 = 8
	Dot2 = 9
	Dot3 = 10
	Dot4 = 11
	Dot5 = 12
	Dot6 = 13
	Dot7 = 14
	Dot8 = 15
	Space = 16

# key IDs for right-side device when using two-device mode
rightKeys = {
	41: MiniKey.DPadUp,
	42: MiniKey.DPadDown,
	44: MiniKey.DPadRight,
	43: MiniKey.DPadLeft,
	40: MiniKey.DPadCenter,
	19: MiniKey.PanRight,
	21: MiniKey.PanLeft,
	48: MiniKey.Row1,
	49: MiniKey.Row2,
	50: MiniKey.Row3,
	51: MiniKey.Row4,
	17: MiniKey.Space,
}

# map keys for when device is upside-down
flippedKeys = {
	MiniKey.DPadUp: MiniKey.DPadDown,
	MiniKey.DPadDown: MiniKey.DPadUp,
	MiniKey.DPadLeft: MiniKey.DPadRight,
	MiniKey.DPadRight: MiniKey.DPadLeft,
	MiniKey.PanLeft: MiniKey.PanRight,
	MiniKey.PanRight: MiniKey.PanLeft,
	MiniKey.Row1: MiniKey.Row4,
	MiniKey.Row2: MiniKey.Row3,
	MiniKey.Row3: MiniKey.Row2,
	MiniKey.Row4: MiniKey.Row1,
	MiniKey.Dot1: MiniKey.Dot4,
	MiniKey.Dot2: MiniKey.Dot5,
	MiniKey.Dot3: MiniKey.Dot6,
	MiniKey.Dot4: MiniKey.Dot1,
	MiniKey.Dot5: MiniKey.Dot2,
	MiniKey.Dot6: MiniKey.Dot3,
	MiniKey.Dot7: MiniKey.Dot8,
	MiniKey.Dot8: MiniKey.Dot7,
}

# whether the device is a left type or right type
class DevSide(Enum):
	Left = 0
	Right = 1

# a position for where the device is
class DevPosition(Enum):
	BottomLeft = 0
	BottomRight = 1
	TopLeft = 2
	TopRight = 3

# is a bluetooth device a Cadence device?
def isDeviceCadence(m):
	log.info(f"possible cadence device {m} {'Dev_VID&02361f' in m.id}")
	return "Dev_VID&02361f_PID&52ae" in m.id

def getDevicePosition(side: DevSide, flipped: bool) -> DevPosition:
	if side == DevSide.Left:
		if flipped:
			return DevPosition.TopRight
		else:
			return DevPosition.BottomLeft
	else:
		if flipped:
			return DevPosition.TopLeft
		else:
			return DevPosition.BottomRight

# braille dot order
brailleOffsets = [[0,0], [0,1], [0,2], [1,0], [1,1], [1,2], [0,3], [1,3]]

# for debugging purposes
def debugImage(image: list[list[bool]]) -> str:
	return "\n".join(["".join(["#" if pix else " " for pix in row]) for row in image])

# boolean 2d array to list of braille codes
def imageToCells(image: list[list[bool]]) -> list[int]:
	height = len(image)
	width = len(image[0])
	numCols = int(width / 2)
	numRows = int(height / 4)
	out: list[int] = []
	for cellY in range(numRows):
		for cellX in range(numCols):
			cellOut = 0
			for (pixI, offset) in enumerate(brailleOffsets):
				sourceX = cellX * 2 + offset[0]
				sourceY = cellY * 4 + offset[1]
				valBool = image[sourceY][sourceX]
				if valBool:
					cellOut += 2**pixI
			out.append(cellOut)
	return out

# list of braille codes to boolean 2d array
def cellsToImage(cells: list[int], numRows: int) -> list[list[bool]]:
	numCols = int(len(cells) / numRows)
	height = numRows * 4
	width = numCols * 2
	image: list[list[bool]] = [[False for x in range(width)] for y in range(height)]
	for cellI, cell in enumerate(cells):
		cellX = cellI % numCols
		cellY = math.floor(cellI / numCols)
		for (pixI, offset) in enumerate(brailleOffsets):
			x = cellX * 2 + offset[0]
			y = cellY * 4 + offset[1]
			val = ((cell >> pixI) & 1) == 1
			image[y][x] = val
	return image

# join two boolean 2d arrays horizontally
def joinImagesHorizontally(imageLeft: list[list[bool]], imageRight: list[list[bool]]):
	return [rowLeft + rowRight for (rowLeft, rowRight) in zip(imageLeft, imageRight)]

# flip boolean 2d array 180 degrees
def flipImage(image: list[list[bool]]) -> list[list[bool]]:
	height = len(image)
	width = len(image[0])
	return [[image[height - y - 1][width - x - 1] for x in range(width)] for y in range(height)]

class HidFeatureReport(hid.HidOutputReport):
	_reportType = hidpi.HIDP_REPORT_TYPE.FEATURE

	def __init__(self, device, reportID=0):
		super().__init__(device, reportID)
		self._reportSize = device.caps.FeatureReportByteLength
		self._reportBuf = ctypes.c_buffer(self._reportSize)
		self._reportBuf[0] = 0

# Represents either a single device or a pair of two devices (where the second one is bluetooth connected to the first one)
# Isn't visible to NVDA, see CadenceDisplayDriver
class CadenceDeviceDriver(HidBrailleDriver):
	name = "CadenceDeviceDriver"
	description = _("Cadence HID Braille Display")

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(
			bdDetect.DeviceType.HID,
			{
				"VID_361F&PID_52AE",
			},
		)

		driverRegistrar.addBluetoothDevices(
			lambda m: isDeviceCadence(m)
		)

	def __init__(self, port, displayDriver, devIndex):
		log.info(f"########## CADENCE DEVICE {port}")
		super().__init__(port)
		# save properties
		self.displayDriver = displayDriver
		self.devIndex = devIndex

		self.valueCapsList = (hidpi.HIDP_VALUE_CAPS * self._dev.caps.NumberFeatureValueCaps)()
		numValueCaps = ctypes.c_long(self._dev.caps.NumberFeatureValueCaps)
		hid.check_HidP_status(
			hidDll.HidP_GetValueCaps,
			hidpi.HIDP_REPORT_TYPE.FEATURE,
			ctypes.byref(self.valueCapsList),
			ctypes.byref(numValueCaps),
			self._dev._pd)

		self.isOneHanded = not self.isTwoDevices()

		# detect left or right
		if "product" in port.deviceInfo and port.deviceInfo["product"].startswith("Cadence-"):
			self.isRight = port.deviceInfo["product"].startswith("Cadence-R")
			self.devName = port.deviceInfo["product"]
			log.info(f"USB {self.isRight} {self.devName}")
		else:
			self.isRight = None
			for g_hdi, idd, devinfo, buf in hwPortUtils._listDevices(hwPortUtils._hidGuid, True):
				if idd.DevicePath == port.deviceInfo["devicePath"]:
					log.info("Found device for isRight")

					parent = getParent(devinfo, g_hdi)
					parent2 = getParent(parent, g_hdi)

					name = getName(parent2, g_hdi)

					self.devName = name

					if name.startswith("Cadence-L"):
						self.isRight = False
					elif name.startswith("Cadence-R"):
						self.isRight = True
					else:
						raise Exception(f"improper device name {name}")

					log.info(f"BLUETOOTH {name} {self.isRight}")

			if self.isRight is None:
				raise Exception("unable to find device for checking if isRight")

		log.info(f"isRight {self.isRight}")

		# auto-select whether device is flipped based on whether another device is currently in non-flipped position
		self.isFlipped = False
		for side in self.getSides():
			unflippedPos = self.getPosition(side)
			for otherDevice in self.displayDriver.devices:
				for otherDeviceSide in otherDevice.getSides():
					if otherDevice.getPosition(otherDeviceSide) == unflippedPos and self.isFlipped == False:
						if self.devName < otherDevice.devName:
							otherDevice.isFlipped = True
						else:
							self.isFlipped = True

	# received button press (called by superclass)
	def _hidOnReceive(self, data: bytes):
		super()._hidOnReceive(data)
		self.displayDriver._hidOnReceive(data, self.devIndex)

	# handle button press
	def _handleKeyRelease(self):
		# TODO stop single-handed mode when there are multiple devices connected separately
		if not self.displayDriver.shouldStopKeys():
			# handle button press as a keyboard input
			super()._handleKeyRelease()

	# is this actually two devices where the second one is connected to the first one through bluetooth
	def isTwoDevices(self):
		return self.numCols > 12

	# get list of device sides (left or right, or both if the second one is connected to the first one through bluetooth)
	def getSides(self) -> list[DevSide]:
		if self.isTwoDevices():
			# TODO Is right, left possible?
			return [DevSide.Left, DevSide.Right]
		elif self.isRight:
			return [DevSide.Right]
		else:
			return [DevSide.Left]

	# get position of device
	def getPosition(self, side: DevSide) -> DevPosition:
		flipped = self.isFlipped
		return getDevicePosition(side, flipped)

	def setOneHanded(self, newOneHanded: bool):
		if newOneHanded == self.isOneHanded:
			return
		if self.isTwoDevices():
			return

		report = HidFeatureReport(self._dev)
		for valueCap in self.valueCapsList:
			if valueCap.LinkUsagePage == HID_USAGE_PAGE_BRAILLE and valueCap.u1.NotRange.Usage == 7:
				report.setUsageValueArray(
					HID_USAGE_PAGE_BRAILLE,
					valueCap.LinkCollection,
					valueCap.u1.NotRange.Usage,
					b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" if newOneHanded else b"\xf4\x50\x4c\x74\xd1\x6e\xca\xa3\x8c\x4f\x5f\x0a\xd1\xa7\x5a\x29",
				)

		self._dev.setFeature(report.data)
		self.isOneHanded = newOneHanded

	# cleanup on exit (called by NVDA)
	def terminate(self):
		log.info("## MainCadenceDisplayDriver Terminate")
		self.setOneHanded(True)
		try:
			super().terminate()
		except Exception as e:
			log.error(e)

	def saveSettings(self):
		pass

# A driver for multiple devices connected simultaneously
# This is the driver than NVDA sees, but actual communication with the device is delegated to CadenceDeviceDriver
class MainCadenceDisplayDriver(braille.BrailleDisplayDriver):
	name = "CadenceDisplayDriver"
	# Translators: The name of a series of braille displays.
	description = _("Cadence HID Braille Display")
	isThreadSafe = True
	supportsAutomaticDetection = True

	prevKeysDown: list[tuple[MiniKey, tuple[int, DevSide]]]
	liveKeys: list[tuple[MiniKey, tuple[int, DevSide]]]
	composedKeys: list[tuple[MiniKey, tuple[int, DevSide]]]

	devices: list[CadenceDeviceDriver]

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(
			bdDetect.DeviceType.HID,
			{
				"VID_361F&PID_52AE",
			},
		)

		driverRegistrar.addBluetoothDevices(
			lambda m: isDeviceCadence(m)
		)

	def __init__(self, port):
		super().__init__()
		# initialize properties
		self.prevKeysDown = []
		self.liveKeys = []
		self.composedKeys = []
		self.devices = []

		# check for USB devices
		for devMatch in self._getTryPorts("usb"):
			if devMatch.type != bdDetect.DeviceType.HID:
				continue
			device = CadenceDeviceDriver(devMatch, self, len(self.devices))
			self.devices.append(device)

		# if no USB devices, check for bluetooth devices
		# TODO figure out a way to determine which usb and bluetooth connections are the same device in case we want to connect to a mix of USB and bluetooth devices
		if len(self.devices) == 0:
			for devMatch in self._getTryPorts("bluetooth"):
				if devMatch.type != bdDetect.DeviceType.HID:
					continue
				device = CadenceDeviceDriver(devMatch, self, len(self.devices))
				self.devices.append(device)

		# if no devices, error
		if len(self.devices) == 0:
			raise RuntimeError("no cadence devices")

		log.info(f"########################## cadence driver initialized {port} {self.devices}")

		for devI, device in enumerate(self.devices):
			for side in device.getSides():
				log.info(f"device: {devI} {side} {device.getPosition(side)}")

		# initialize screen size
		self.updateScreenSize()

	def shouldStopKeys(self):
		return False

	# display on device (called by NVDA or manually in some cases)
	def display(self, cells: list[int]):
		# log.info(f"display {len(cells)} {self.numRows} {self.numCols}")
		if len(cells) < self.numRows * self.numCols:
			cells = [(cells[i] if i < len(cells) else 0) for i in self.numRows * self.numCols]
		cells = cells[:(self.numRows * self.numCols)]
		fullImage = cellsToImage(cells, self.numRows)
		for devI, device in enumerate(self.devices):
			sides = device.getSides()
			leftDevPos = device.getPosition(sides[0])
			# log.info(f"left {devI} {leftDevPos}")
			image = self.getImage(fullImage, leftDevPos)
			if len(sides) > 1:
				rightDevPos = device.getPosition(sides[1])
				# log.info(f"right {devI} {rightDevPos}")
				rightSideImage = self.getImage(fullImage, rightDevPos)
				image = joinImagesHorizontally(image, rightSideImage)
			devCells = imageToCells(image)
			device.display(devCells)

	# crop a screen to a device position
	def getImage(self, fullImage: list[list[bool]], pos: DevPosition) -> list[list[bool]]:
		xOffset = (24 if (pos == DevPosition.TopRight or pos == DevPosition.BottomRight) else 0) - self.offsetCols * 2
		yOffset = (16 if (pos == DevPosition.BottomLeft or pos == DevPosition.BottomRight) else 0) - self.offsetRows * 4
		image = [[fullImage[y + yOffset][x + xOffset] for x in range(24)] for y in range(16)]
		flipped = pos == DevPosition.TopLeft or pos == DevPosition.TopRight
		# log.info(f"display {pos} / {xOffset} / {yOffset} / {flipped}")
		if flipped:
			image = flipImage(image)
		return image
	
	# flip keys if necessary due to device position
	def rotateKey(self, key: MiniKey, pos: DevPosition) -> MiniKey:
		if pos == DevPosition.TopLeft or pos == DevPosition.TopRight:
			if key in flippedKeys:
				return flippedKeys[key]
		return key

	# receive button press from device (called by CadenceDeviceDriver)
	def _hidOnReceive(self, data: bytes, devIndex: int):
		# log.info("# data: " + " ".join([f"{b:0>8b}" for b in data]))
		if len(data) == 5 or len(data) == 7:
			keysDown = [key for key in self.prevKeysDown if key[1][0] != devIndex]
			for byteI, byte in enumerate(data):
				for bitI in range(8):
					if byte & (1 << bitI):
						index = byteI * 8 + bitI
						log.info(f"## key {index}")
						device = self.devices[devIndex]
						devSides = device.getSides()
						devSide = devSides[0]
						if len(data) == 7:
							if index in rightKeys:
								index = rightKeys[index]
								devSide = devSides[1]
						key = MiniKey(index)
						key = self.rotateKey(key, self.getDevPosition((devIndex, devSide)))
						if len(data) == 5:
							if key == MiniKey.Dot4:
								key = MiniKey.Dot1
							elif key == MiniKey.Dot5:
								key = MiniKey.Dot2
							elif key == MiniKey.Dot6:
								key = MiniKey.Dot3
							elif key == MiniKey.Dot8:
								key = MiniKey.Dot7
						if not key in keysDown:
							keysDown.append((key, (devIndex, devSide)))
			newKeys = [key for key in keysDown if key not in self.prevKeysDown]
			keysUp = [key for key in self.prevKeysDown if not key in keysDown]
			if len(newKeys) > 0:
				self.composedKeys = []
				for key in newKeys:
					if not key in self.liveKeys:
						self.liveKeys.append(key)
			if len(keysUp) > 0:
				self.liveKeys = [key for key in self.liveKeys if not key in keysUp]

			end = len(self.composedKeys) != 0 and len(self.liveKeys) == 0

			if len(keysUp) > 0:
				for key in keysUp:
					if not key in self.composedKeys:
						self.composedKeys.append(key)

			self.handleKeys(self.liveKeys, self.composedKeys)

			if end:
				self.composedKeys = []

			self.prevKeysDown = keysDown

	# update screen size based on the current positions of connected devices
	def updateScreenSize(self):
		devPositions: list[DevPosition] = []
		for device in self.devices:
			for side in device.getSides():
				devPositions.append(device.getPosition(side))

		self.offsetCols = 0
		self.offsetRows = 0

		if (DevPosition.BottomLeft in devPositions or DevPosition.TopLeft in devPositions) and (DevPosition.BottomRight in devPositions or DevPosition.TopRight in devPositions):
			self.numCols = 24
		else:
			if DevPosition.BottomRight in devPositions or DevPosition.TopRight in devPositions:
				self.offsetCols = 12
			self.numCols = 12

		if (DevPosition.BottomLeft in devPositions or DevPosition.BottomRight in devPositions) and (DevPosition.TopLeft in devPositions or DevPosition.TopRight in devPositions):
			self.numRows = 8
		else:
			if DevPosition.BottomLeft in devPositions or DevPosition.BottomRight in devPositions:
				self.offsetRows = 4
			self.numRows = 4

		log.info(f"## UPDATED SIZE {self.numRows} {self.numCols} {[device.isTwoDevices() for device in self.devices]}")

		self.updateOneHanded()

	def shouldBeOneHanded(self):
		return (self.numCols == 12)

	def updateOneHanded(self):
		newOneHanded = self.shouldBeOneHanded()

		log.info(f"setting one handed {newOneHanded}")

		for device in self.devices:
			device.setOneHanded(newOneHanded)

	# get current device position for a device
	def getDevPosition(self, device: tuple[int, DevSide]) -> DevPosition:
		return self.devices[device[0]].getPosition(device[1])

	# run after changing device positions to update screens
	def afterDevicePositionsChanged(self):
		self.updateScreenSize()

	# move current device position by flipping it
	def flipScreen(self, deviceID: tuple[int, DevSide], flipped: bool):
		log.info(f"flipScreen {deviceID} {flipped}")
		device = self.devices[deviceID[0]]
		device.isFlipped[deviceID[1]] = flipped
		newPosition = device.getPosition(deviceID[1])
		for otherDevice in self.devices:
			if otherDevice != device:
				for otherDeviceSide in otherDevice.getSides():
					otherDevicePos = otherDevice.getPosition(otherDeviceSide)
					if otherDevicePos == newPosition:
						otherDevice.isFlipped[otherDeviceSide] = not flipped
		self.afterDevicePositionsChanged()

	# cycle through possible device positions
	def cycleDevPositions(self):
		# get all individual devices
		deviceIds = [(devIndex, side) for devIndex, device in enumerate(self.devices) for side in device.getSides()]
		# get number of lefts and rights
		numLefts = len([(devIndex, side) for devIndex, side in deviceIds if side == DevSide.Left])
		numRights = len([(devIndex, side) for devIndex, side in deviceIds if side == DevSide.Right])
		# determine form factor(s)
		if numLefts >= 2 and numRights >= 2:
			forms = [set([DevPosition.BottomLeft, DevPosition.BottomRight, DevPosition.TopLeft, DevPosition.TopRight])]
		elif numLefts >= 1 and numRights >= 1:
			forms = [set([DevPosition.BottomLeft, DevPosition.BottomRight]), set([DevPosition.BottomLeft, DevPosition.TopLeft])]
		elif numLefts >= 1:
			forms = [set([DevPosition.BottomLeft])]
		else:
			forms = [set([DevPosition.BottomRight])]
		# find all possible options
		options: list[list[bool]] = []
		for positions in itertools.product([True, False], repeat=len(deviceIds)):
			if numLefts > 2 and numRights > 2:
				# don't combine two tall duets into a quartet
				devIndexFlipped = {}
				isTall = False
				for i in range(len(deviceIds)):
					devIndex = deviceIds[i][0]
					flipped = positions[i]
					if devIndex in devIndexFlipped and devIndexFlipped[devIndex] != flipped:
						isTall = True
						break
					devIndexFlipped[devIndex] = flipped
				if isTall:
					continue

			currentForm = set([getDevicePosition(deviceIds[i][1], positions[i]) for i in range(len(deviceIds))])
			if currentForm in forms:
				options.append(list(positions))
		# get current device positions
		currentPositions = [self.devices[devIndex].isFlipped[side] for devIndex, side in deviceIds]
		# find index of current device position in options
		currentPositionI = -1
		if currentPositions in options:
			currentPositionI = options.index(currentPositions)
		log.info(f"{deviceIds}, {numLefts}, {numRights}, {forms}, {options}, {currentPositions}, {currentPositionI}")
		# get new device positions
		newPositions = options[0] if currentPositionI + 1 >= len(options) else options[currentPositionI + 1]
		# set new device positions
		for i in range(len(deviceIds)):
			devIndex, side = deviceIds[i]
			flipped = newPositions[i]
			self.devices[devIndex].isFlipped[side] = flipped
		# update
		self.afterDevicePositionsChanged()

	# handle keys
	def handleKeys(self, liveKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]], composedKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]]):
		log.info(f"## {liveKeysWithPosition} {composedKeysWithPosition}")

		composedKeys = [key[0] for key in composedKeysWithPosition]

		if len(composedKeys) == 1:
			if MiniKey.Row1 in composedKeys or MiniKey.Row4 in composedKeys:
				position = self.getDevPosition(composedKeysWithPosition[0][1])
				isCurrentlyFlipped = position == DevPosition.TopLeft or position == DevPosition.TopRight
				self.flipScreen(composedKeysWithPosition[0][1], (MiniKey.Row4 in composedKeys and not isCurrentlyFlipped) or (MiniKey.Row1 in composedKeys and isCurrentlyFlipped))

	# map of device buttons to keyboard keys for non-image mode
	gestureMap = inputCore.GlobalGestureMap(
		{
			"globalCommands.GlobalCommands": {
				"braille_scrollBack": (
					"br(hidBrailleStandard):panLeft",
					"br(hidBrailleStandard):rockerUp",
				),
				"braille_scrollForward": (
					"br(hidBrailleStandard):panRight",
					"br(hidBrailleStandard):rockerDown",
				),
				"braille_routeTo": ("br(hidBrailleStandard):routerSet1_routerKey",),
				"braille_toggleTether": ("br(hidBrailleStandard):up+down",),
				"kb:upArrow": (
					"br(hidBrailleStandard):joystickUp",
					"br(hidBrailleStandard):dpadUp",
					"br(hidBrailleStandard):space+dot1",
				),
				"kb:downArrow": (
					"br(hidBrailleStandard):joystickDown",
					"br(hidBrailleStandard):dpadDown",
					"br(hidBrailleStandard):space+dot4",
				),
				"kb:leftArrow": (
					"br(hidBrailleStandard):space+dot3",
					"br(hidBrailleStandard):joystickLeft",
					"br(hidBrailleStandard):dpadLeft",
				),
				"kb:rightArrow": (
					"br(hidBrailleStandard):space+dot6",
					"br(hidBrailleStandard):joystickRight",
					"br(hidBrailleStandard):dpadRight",
				),
				"showGui": ("br(hidBrailleStandard):space+dot1+dot3+dot4+dot5",),
				"kb:shift+tab": ("br(hidBrailleStandard):space+dot1+dot3",),
				"kb:tab": ("br(hidBrailleStandard):space+dot4+dot6",),
				"kb:alt": ("br(hidBrailleStandard):space+dot1+dot3+dot4",),
				"kb:escape": ("br(hidBrailleStandard):space+dot1+dot5",),
				"kb:enter": (
					"br(hidBrailleStandard):joystickCenter",
					"br(hidBrailleStandard):dpadCenter",
				),
				"kb:windows+d": ("br(hidBrailleStandard):Space+dot1+dot4+dot5",),
				"kb:windows": ("br(hidBrailleStandard):space+dot3+dot4",),
				"kb:alt+tab": ("br(hidBrailleStandard):space+dot2+dot3+dot4+dot5",),
				"sayAll": ("br(hidBrailleStandard):Space+dot1+dot2+dot3+dot4+dot5+dot6",),
			},
		},
	)

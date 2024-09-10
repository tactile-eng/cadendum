from logHandler import log
from brailleDisplayDrivers.hidBrailleStandard import HidBrailleDriver, InputGesture
import bdDetect
from typing import List
import api
from NVDAObjects import NVDAObject
from screenBitmap import ScreenBitmap
import math
import threading
import ctypes
import winGDI
import hwIo.hid
from enum import Enum
import math
import braille
import inputCore

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

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

class DevSide(Enum):
	Left = 0
	Right = 1

class DevPosition(Enum):
	BottomLeft = 0
	BottomRight = 1
	TopLeft = 2
	TopRight = 3

# view & navigation
defaultZoom = 1
defaultPanRate = 2
panRateRate = 1.5
defaultZoomRate = 1.25
zoomRateRate = 1.5
bwThresholdOutOf = 100
defaultBwThresholdRate = 7

class Direction(Enum):
	Up = 0
	Down = 1
	Left = 2
	Right = 3

class ScreenBitmapResized(ScreenBitmap):
	def __init__(self, width, height):
		super().__init__(width, height)

	def captureImage(self, x, y, w, h, x2, y2, w2, h2):
		"""
		Captures the part of the screen starting at x,y and extends by w (width) and h (height), and stretches/shrinks it to fit in to the object's bitmap size.
		"""
		tempDC = gdi32.CreateCompatibleDC(self._screenDC)
		tempMemBitmap = gdi32.CreateCompatibleBitmap(self._screenDC, w, h)
		tempOldBitmap = gdi32.SelectObject(tempDC, tempMemBitmap)

		# Copy the requested content from the screen in to our memory device context, stretching/shrinking its size to fit.
		gdi32.StretchBlt(
			tempDC,
			0,
			0,
			w,
			h,
			self._screenDC,
			x,
			y,
			w,
			h,
			winGDI.SRCCOPY,
		)
		gdi32.StretchBlt(
			self._memDC,
			0,
			0,
			self.width,
			self.height,
			tempDC,
			x2,
			y2,
			w2,
			h2,
			winGDI.SRCCOPY,
		)
		# Fetch the pixels from our memory bitmap and store them in a buffer to be returned
		buffer = (winGDI.RGBQUAD * self.width * self.height)()
		gdi32.GetDIBits(
			self._memDC,
			self._memBitmap,
			0,
			self.height,
			buffer,
			ctypes.byref(self._bmInfo),
			winGDI.DIB_RGB_COLORS,
		)

		gdi32.SelectObject(tempDC, tempOldBitmap)
		gdi32.DeleteObject(tempMemBitmap)
		gdi32.DeleteDC(tempDC)

		return buffer

def isSupportEnabled() -> bool:
	return bdDetect.driverIsEnabledForAutoDetection(CadenceDisplayDriver.name)

def isDeviceCadence(m):
	log.info(f"possible cadence device {m} {'Dev_VID&02361f' in m.id}")
	return "Dev_VID&02361f_PID&52ae" in m.id

brailleOffsets = [[0,0], [0,1], [0,2], [1,0], [1,1], [1,2], [0,3], [1,3]]

def debugImage(image: list[list[bool]]) -> str:
	return "\n".join(["".join(["#" if pix else " " for pix in row]) for row in image])

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

def cellsToImage(cells: list[int], numRows: int) -> list[list[bool]]:
	numCols = int(len(cells) / numRows)
	height = numRows * 4
	width = numCols * 2
	log.info(f"############# cellsToImage {width}x{height}")
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

def bitmapToImage(bitmap, width: int, height: int, bwThreshold: float, bwReversed: bool, colorMode: int) -> list[list[bool]]:
	imageOut: list[list[bool]] = []
	log.info(f"############# bitmapToImage {width}x{height}")
	for y in range(height):
		row: list[bool] = []
		for x in range(width):
			rgb = bitmap[y][x]
			r = rgb.rgbRed
			g = rgb.rgbBlue
			b = rgb.rgbGreen
			if colorMode == 0:
				val = 0.299*r + 0.587*g + 0.114*b
			elif colorMode == 1:
				val = r
			elif colorMode == 2:
				val = g
			elif colorMode == 3:
				val = b
			threshold = bwThreshold / bwThresholdOutOf * 255
			if bwReversed:
				valBool = val < threshold
			else:
				valBool = val > threshold
			row.append(valBool)
		imageOut.append(row)
	return imageOut

def flipImage(image: list[list[bool]]) -> list[list[bool]]:
	height = len(image)
	width = len(image[0])
	return [[image[height - y - 1][width - x - 1] for x in range(width)] for y in range(height)]

def joinImagesHorizontally(imageLeft: list[list[bool]], imageRight: list[list[bool]]):
	return [rowLeft + rowRight for (rowLeft, rowRight) in zip(imageLeft, imageRight)]

# https://stackoverflow.com/questions/12435211/threading-timer-repeat-function-every-n-seconds
class RunInterval(threading.Thread):
	def __init__(self, callback, interval = 1):
		super().__init__()
		self.callback = callback
		self.interval = interval
		self.daemon = True
		self.stopFlag = threading.Event()
	
	def cancel(self):
		self.stopFlag.set()

	def run(self):
		while not self.stopFlag.wait(self.interval):
			try:
				self.callback()
			except Exception as e:
				log.error(f"{e}")
				pass

class SignalContainer():
	def __init__(self, value: float):
		self.value = value
		self.default = value
	
	def get(self) -> float:
		return self.value

	def set(self, val: float):
		self.value = val
	
	def reset(self):
		self.value = self.default

class Slider():
	# signal, rate, min, max, rateRate, strictMinMax, quantize, name, getRate, setRate, sliderExp, sliderSCurve, doToast, rateToast, valueText, hardMin, hardMax, displayPrecision, displayNumber, unit, notifySoundRelative, htmlId

	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool):
		self.signal = SignalContainer(default)
		self.rate = SignalContainer(rateDefault)
		self.min = SignalContainer(min)
		self.max = SignalContainer(max)
		self.rateRate = rateRate
		self.sliderExp = sliderExp
		self.sliderSCurve = sliderSCurve
		self.quantize = None
		self.strictMinMax = strictMinMax
	
	def get(self) -> float:
		return self.signal.get()
	
	def set(self, val: float):
		self.signal.set(val)

	def getRate(self) -> float:
		return self.rate.get()
	
	def setRate(self, val: float):
		self.rate.set(val)

	def expOrLog(self, value: float, expOrLog: bool):
		if (self.sliderExp):
			if (expOrLog):
				return math.pow(2, value) - 1
			else:
				return math.log(value + 1) / math.log(2)
		elif (self.sliderSCurve):
			if (value > 1 or value < 0): return value
			curvyness = 1.75
			if (expOrLog):
				return 1 / (1 + math.pow(value / (1 - value), -curvyness))
			else:
				if (value == 0.5): return 0.5
				return 1 / (math.pow(1 / value - 1, 1 / curvyness) + 1)
		else:
			return value

	def getNormalised(self):
		return (self.get() - self.min.get()) / (self.max.get() - self.min.get())

	
	def setNormalized(self, n: float):
		newValue = n * (self.max.get() - self.min.get()) + self.min.get()
		if (self.quantize != None):
			newValue = self.roundValue(newValue)
		if (self.strictMinMax):
			if (newValue < self.min.get()): newValue = self.min.get()
			if (newValue > self.max.get()): newValue = self.max.get()
		self.set(newValue)
	
	def roundValue(self, n: float) -> float:
		if (self.quantize == None): return n

		min = self.min.get()
		quantize = self.quantize.get()
		rounded = math.round((n - min) / quantize) * quantize + min

		max = self.max.get()
		if (self.strictMinMax):
			if (rounded < min): rounded = min
			elif (rounded > max): rounded = max
		return rounded

	def round(self):
		if (self.quantize != None):
			self.set(self.roundValue(self.get()))

	def getRateMinQuantize(self) -> float:
		rate = self.getRate()
		if (self.quantize != None and rate < self.quantize.get()):
			rate = self.quantize.get()
		return rate

	def rateSCurve(self, n: float, r: float, min: float, max: float) -> float:
		origNormalized = (n - min) / (max - min)
		rateNormalized = r / (max - min)
		origTransformed = self.expOrLog(origNormalized, False)
		newTransformed = origTransformed + rateNormalized
		newNormalized = self.expOrLog(newTransformed, True)
		return newNormalized * (max - min) + min

	def increase(self):
		n = self.get()
		
		if (self.sliderExp):
			n = n * self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, self.getRate(), self.min.get(), self.max.get())
		else:
			n = n + self.getRateMinQuantize()

		if (self.strictMinMax and n > self.max.get()):
			n = self.max.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def decrease(self):
		n = self.get()
					
		if (self.sliderExp):
			n = n / self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, -self.getRate(), self.min.get(), self.max.get())
		else:
			n = n - self.getRateMinQuantize()

		if (self.strictMinMax and n < self.min.get()):
			n = self.min.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def reset(self):
		self.signal.reset()
		self.rate.reset()

	def increaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) * rateRate + 1)
		else:
			self.rate.set(n * rateRate)

	def decreaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) / rateRate + 1)
		else:
			self.rate.set(n / rateRate)

class CombinedSlider():
	def __init__(self, sliders: list[Slider]):
		self.sliders = sliders

	def updateSliderRatios(self):
		firstValue = self.sliders[0].get()
		self.sliderRatios = []
		for slider in self.sliders:
			self.sliderRatios.push(slider.get() / firstValue)
	
	def updateSliders(self):
		firstValue = self.sliders[0].get()
		for i in range(len(self.sliders)):
			self.sliders[i].set(firstValue * self.sliderRatios[i - 1])

	def setNormalized(self, n: float):
		self.updateSliderRatios()
		super.setNormalized(n)
		self.updateSliders()

	def increase(self):
		for slider in self.sliders:
			slider.increase()
	
	def decrease(self):
		for slider in self.sliders:
			slider.decrease()
	
	def increaseRate(self):
		for slider in self.sliders:
			slider.increaseRate()
	
	def decreaseRate(self):
		for slider in self.sliders:
			slider.decreaseRate()

class PanSlider(Slider):
	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool, zoom):
		super().__init__(default, rateDefault, rateRate, sliderExp, sliderSCurve, min, max, strictMinMax)
		self.zoom = zoom
	def getRate(self) -> float:
		return self.rate.get() / self.zoom()

class CadenceDeviceDriver(HidBrailleDriver):
	name = "CadenceDisplayDriver"
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
		super().__init__(port)
		self.displayDriver = displayDriver
		self.devIndex = devIndex
		log.info(f"########## CADENCE DEVICE {port} {self._dev}")

		self.isTop = False
		self.isTall = False
		# for i in self._inputButtonCapsByDataIndex :
		# 	log.info(f"# {i} / {self._inputButtonCapsByDataIndex[i]}")

	def _hidOnReceive(self, data: bytes):
		super()._hidOnReceive(data)
		self.displayDriver._hidOnReceive(data, self.devIndex)
	def _handleKeyRelease(self):
		if not self.displayDriver.displayingImage:
			super()._handleKeyRelease()
	
	def isTwoDevices(self):
		return self.numCols > 12
	
	def getPostion(self, side: DevSide) -> DevPosition:
		if side == DevSide.Left:
			if self.isTop:
				return DevPosition.TopRight
			else:
				return DevPosition.BottomLeft
		else:
			if self.isTall:
				if self.isTop:
					return DevPosition.BottomRight
				else:
					return DevPosition.TopLeft
			else:
				if self.isTop:
					return DevPosition.TopLeft
				else:
					return DevPosition.BottomRight

class CadenceDisplayDriver(braille.BrailleDisplayDriver):
	name = "CadenceDisplayDriver"
	# Translators: The name of a series of braille displays.
	description = _("Cadence HID Braille Display")
	isThreadSafe = True
	supportsAutomaticDetection = True

	displayingImage = False
	lastDisplayedNonImage = None
	imageTimer = None

	lastFitWidth = -1
	lastFitHeight = -1
	prevKeysDown = []
	liveKeys = []
	composedKeys = []

	devices: list[CadenceDeviceDriver] = []

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

		self.devices = []
		for devMatch in self._getTryPorts("usb"):
			if devMatch.type != bdDetect.DeviceType.HID:
				continue
			device = CadenceDeviceDriver(devMatch, self, len(self.devices))
			self.devices.append(device)
		
		# TODO figure out a way to determine which usb and bluetooth connections are the same device in case we want to connect to a mix of USB and bluetooth devices
		if len(self.devices) == 0:
			for devMatch in self._getTryPorts("bluetooth"):
				if devMatch.type != bdDetect.DeviceType.HID:
					continue
				device = CadenceDeviceDriver(devMatch, self, len(self.devices))
				self.devices.append(device)
		
		if len(self.devices) == 0:
			raise RuntimeError("no cadence devices")

		log.info(f"########################## cadence driver initialized {port} {self.devices}")

		self.updateScreenSize()

		self.zoomX = Slider(defaultZoom,
			defaultZoomRate,
			zoomRateRate,
			True,
			False,
			0.00000000001,
			1000000000,
			True)
		self.zoomY = Slider(defaultZoom,
			defaultZoomRate,
			zoomRateRate,
			True,
			False,
			0.00000000001,
			1000000000,
			True)
		self.combinedZoom = CombinedSlider([self.zoomX, self.zoomY])
		self.centerX = PanSlider(0,
			defaultPanRate,
			panRateRate,
			False,
			False,
			0,
			1,
			True,
			lambda: self.zoomX.get() * 24 / 2)
		self.centerY = PanSlider(0,
			defaultPanRate,
			panRateRate,
			False,
			False,
			0,
			1,
			True,
			lambda: self.zoomX.get() * 16 / 2)
		self.combinedPan = CombinedSlider([self.centerX, self.centerY])
		self.bwThreshold = Slider(bwThresholdOutOf / 2,
			defaultBwThresholdRate,
			1.5,
			False,
			True,
			0,
			bwThresholdOutOf,
			True)
		self.bwReversed = False
		self.colorMode = 0
		
	def doToggleImage(self):
		self.displayingImage = not self.displayingImage
		if self.displayingImage:
			self.displayImage(True)
			if self.imageTimer is None:
				self.imageTimer = RunInterval(self.displayImage, 0.5)
				self.imageTimer.start()
		else:
			self.restoreFromImage()
			if self.imageTimer is not None:
				self.imageTimer.cancel()
				self.imageTimer = None
	
	def displayImage(self, resetView = False):
		obj = api.getNavigatorObject()
		if obj is None:
			obj = api.getFocusObject()
			if obj is None:
				log.error("no navigator object")
				return
		location = obj.location
		if not location:
			log.error("no location for object when displaying image")
			return
		(left, top, width, height) = location
#		log.info(f"######## screenshot {left} {top} {width} {height}")
		if width <= 0 or height <= 0:
			log.error("invalid object location")
			return
		if resetView or self.lastFitWidth != width or self.lastFitHeight != height:
			self.reset(width, height)
		screenWidth = self.getDisplayWidth()
		screenHeight = self.getDisplayHeight()

		topLeftX = self.screenXToVirtual(0, self.getDisplayWidth()) * width
		topLeftY = height - self.screenYToVirtual(0, self.getDisplayHeight()) * height
		bottomRightX = self.screenXToVirtual(self.getDisplayWidth(), self.getDisplayWidth()) * width
		bottomRightY = height - self.screenYToVirtual(self.getDisplayHeight(), self.getDisplayHeight()) * height

		# log.info(f"{topLeftX} {topLeftY} {bottomRightX} {bottomRightY}")

		bitmapHolder = ScreenBitmapResized(screenWidth, screenHeight)
		# TODO don't round here
		bitmapBuffer = bitmapHolder.captureImage(left, top, width, height, round(topLeftX), round(topLeftY), round(bottomRightX - topLeftX), round(bottomRightY - topLeftY))
		boolImage = bitmapToImage(bitmapBuffer, screenWidth, screenHeight, self.bwThreshold.get(), self.bwReversed, self.colorMode)
		cells = imageToCells(boolImage)
		self.display(cells, True)
	
	def restoreFromImage(self):
		if self.lastDisplayedNonImage is not None:
			self.display(self.lastDisplayedNonImage)

	def getImage(self, fullImage: list[list[bool]], pos: DevPosition) -> list[list[bool]]:
		xOffset = (24 if (pos == DevPosition.TopRight or pos == DevPosition.BottomRight) else 0) - self.offsetCols * 2
		yOffset = (16 if (pos == DevPosition.BottomLeft or pos == DevPosition.BottomRight) else 0) - self.offsetRows * 4
		image = [[fullImage[y + yOffset][x + xOffset] for x in range(24)] for y in range(16)]
		if pos == DevPosition.TopLeft or pos == DevPosition.TopRight:
			image = flipImage(image)
		return image

	def display(self, cells: List[int], isImage = False):
		# log.info(f"display {isImage} {self.displayingImage} {cells}")
		if not isImage:
			self.lastDisplayedNonImage = cells
		if isImage == self.displayingImage:
			fullImage = cellsToImage(cells, self.numRows)
			log.info(f"orig {len(fullImage[0])}x{len(fullImage)}")
			log.info(debugImage(fullImage))
			for device in self.devices:
				leftDevPos = device.getPostion(DevSide.Left)
				image = self.getImage(fullImage, leftDevPos)
				log.info(f"left {len(image[0])}x{len(image)}")
				log.info(debugImage(image))
				if device.isTwoDevices():
					rightDevPos = device.getPostion(DevSide.Right)
					rightSideImage = self.getImage(fullImage, rightDevPos)
					log.info(f"right {len(rightSideImage[0])}x{len(rightSideImage)}")
					image = joinImagesHorizontally(image, rightSideImage)
					log.info(f"combined {len(image[0])}x{len(image)}")
				log.info(debugImage(image))
				devCells = imageToCells(image)
				log.info(f"cells {devCells}")
				log.info(debugImage(cellsToImage(devCells, self.numRows)))
				device.display(devCells)

	def terminate(self):
		super().terminate()
		for device in self.devices:
			device.terminate()
		if self.imageTimer is not None:
			self.imageTimer.cancel()
			self.imageTimer = None
	
	def getDisplayWidth(self):
		return self.numCols * 2
	def getDisplayHeight(self):
		return self.numRows * 4
	def getFitZoom(self, toDrawWidth, toDrawHeight):
		# calculate zoom to fit image in screen while keeping aspect ratio
		if (toDrawWidth / toDrawHeight > self.getDisplayWidth() / self.getDisplayHeight()):
			# image wider than screen
			return [2, toDrawHeight / (toDrawWidth * (self.getDisplayHeight() / self.getDisplayWidth())) * 2]
		else:
			return [toDrawWidth / (toDrawHeight * (self.getDisplayWidth() / self.getDisplayHeight())) * 2, 2]
	def reset(self, toDrawWidth, toDrawHeight):
		self.centerX.set(0.5)
		self.centerY.set(0.5)
		fitZoom = self.getFitZoom(toDrawWidth, toDrawHeight)
		self.zoomX.set(fitZoom[0])
		self.zoomY.set(fitZoom[1])
		self.lastFitWidth = toDrawWidth
		self.lastFitHeight = toDrawHeight
		self.bwThreshold.reset()
		self.colorMode = 0
		self.bwReversed = False
		# log.info(f"################## reset {self.centerX.get()} {self.centerY.get()} / {self.zoomX.get()} {self.zoomY.get()} / {toDrawWidth} {toDrawHeight}")
	def virtualXToScreen(self, actualX, graphWidth):
		return (actualX - self.centerX.get()) * self.zoomX.get() * ((graphWidth) / 2) + (graphWidth) / 2
	def virtualYToScreen(self, actualY, graphHeight):
		return graphHeight - ((actualY - self.centerY.get()) * self.zoomY.get() * ((graphHeight) / 2) + (graphHeight) / 2)
	def screenXToVirtual(self, graphX, graphWidth):
		return ((graphX) - ((graphWidth) / 2)) / ((graphWidth) / 2) / self.zoomX.get() + self.centerX.get()
	def screenYToVirtual(self, graphY, graphHeight):
		return ((graphHeight - graphY) - ((graphHeight) / 2)) / ((graphHeight) / 2) / self.zoomY.get() + self.centerY.get()
	
	def _hidOnReceive(self, data: bytes, devIndex: int):
		# log.info("# data: " + " ".join([f"{b:0>8b}" for b in data]))
		if len(data) == 5 or len(data) == 7:
			keysDown = [key for key in self.prevKeysDown if key[1][0] != devIndex]
			for byteI, byte in enumerate(data):
				for bitI in range(8):
					if byte & (1 << bitI):
						index = byteI * 8 + bitI
						# log.info(f"## key {index}")
						devSide = DevSide.Left
						if len(data) == 7:
							if index > 16 and index <= 24:
								index -= 8
								devSide = DevSide.Right
							elif index > 36:
								index -= 16
								devSide = DevSide.Right
						key = MiniKey(index)
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
	
	def pan(self, direction: Direction):
		log.info("pan")
		if direction == Direction.Up:
			self.centerY.increase()
		elif direction == Direction.Down:
			self.centerY.decrease()
		elif direction == Direction.Left:
			self.centerX.decrease()
		elif direction == Direction.Right:
			self.centerX.increase()
		self.displayImage()
	
	def zoom(self, zoomIn: bool):
		log.info("zoom")
		if zoomIn:
			self.combinedZoom.increase()
		else:
			self.combinedZoom.decrease()
		self.displayImage()
	
	def changeThreshold(self, increase: bool):
		log.info("changeThreshold")
		if increase:
			self.bwThreshold.increase()
		else:
			self.bwThreshold.decrease()
		self.displayImage()
	
	def reverseThreshold(self):
		log.info("reverse threshold")
		self.bwReversed = not self.bwReversed
		self.displayImage()
	
	def cycleColorMode(self):
		log.info("cycle color mode")
		self.colorMode = (self.colorMode + 1) % 4
		self.displayImage()
	
	def resetAction(self):
		log.info("reset")
		self.reset()
		self.displayImage()

	def changePanRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} pan rate")
		if increase:
			self.combinedPan.increaseRate()
		else:
			self.combinedPan.decreaseRate()

	def changeZoomRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} zoom rate")
		if increase:
			self.combinedZoom.increaseRate()
		else:
			self.combinedZoom.decreaseRate()

	def changeThresholdRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} threshold rate")
		if increase:
			self.bwThreshold.increaseRate()
		else:
			self.bwThreshold.decreaseRate()

	def panEdgeUp(self):
		virtualHeight = self.screenYToVirtual(0, 1) - self.screenYToVirtual(1, 1)
		self.centerY.set(1 - virtualHeight / 2)
		self.displayImage()
	def panEdgeDown(self):
		virtualHeight = self.screenYToVirtual(0, 1) - self.screenYToVirtual(1, 1)
		self.centerY.set(virtualHeight / 2)
		self.displayImage()
	def panEdgeLeft(self):
		virtualWidth = self.screenXToVirtual(1, 1) - self.screenXToVirtual(0, 1)
		self.centerX.set(virtualWidth / 2)
		self.displayImage()
	def panEdgeRight(self):
		virtualWidth = self.screenXToVirtual(1, 1) - self.screenXToVirtual(0, 1)
		self.centerX.set(1 - virtualWidth / 2)
		self.displayImage()

	def updateScreenSize(self):
		devPositions: list[DevPosition] = []
		for device in self.devices:
			devPositions.append(device.getPostion(DevSide.Left))
			if device.isTwoDevices():
				devPositions.append(device.getPostion(DevSide.Right))
			
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

	def getDevPosition(self, device: tuple[int, DevSide]) -> DevPosition:
		return self.devices[device[0]].getPostion(device[1])

	def handleKeys(self, liveKeys, composedKeys):
		log.info(f"## {self.liveKeys} {self.composedKeys}")

		if self.displayingImage:
			if len(liveKeys) == 1:
				# pan - arrow keys
				if MiniKey.DPadUp in liveKeys:
					self.pan(Direction.Up)
				elif MiniKey.DPadDown in liveKeys:
					self.pan(Direction.Down)
				elif MiniKey.DPadLeft in liveKeys:
					self.pan(Direction.Left)
				elif MiniKey.DPadRight in liveKeys:
					self.pan(Direction.Right)
				# zoom in - pan right, zoom out - pan left
				elif MiniKey.PanRight in liveKeys:
					self.zoom(True)
				elif MiniKey.PanLeft in liveKeys:
					self.zoom(False)
				# increase threshold - dot7, decrease threshold - dot3
				elif MiniKey.Dot7 in liveKeys:
					self.changeThreshold(True)
				elif MiniKey.Dot3 in liveKeys:
					self.changeThreshold(False)
				# reverse threshold - dot2
				elif MiniKey.Dot2 in liveKeys:
					self.reverseThreshold()
				# cycle color mode - dot1
				elif MiniKey.Dot1 in liveKeys:
					self.cycleColorMode()
			elif len(liveKeys) == 2:
				if MiniKey.Row1 in liveKeys or MiniKey.Row2 in liveKeys:
					increase = (MiniKey.Row1 in liveKeys)
					# pan faster - row1 + arrow, pan slower - row2 + arrow
					if MiniKey.DPadUp in liveKeys or MiniKey.DPadDown in liveKeys or MiniKey.DPadLeft in liveKeys or MiniKey.DPadRight in liveKeys:
						self.changePanRate(increase)
					# zoom faster - row1 + pan, zoom slower - row2 + pan
					elif MiniKey.PanLeft in liveKeys or MiniKey.PanRight in liveKeys:
						self.changeZoomRate(increase)
					# threshold faster - row1 + dot2, threshold slower row2 + dot2
					elif MiniKey.Dot2 in liveKeys:
						self.changeThresholdRate(increase)
				# pan to edge - space + arrow or (up - space + dots123, down - space + dots 456, left - space + dots23, right - space + dots56)
				if MiniKey.Space in liveKeys:
					if MiniKey.DPadUp in liveKeys:
						self.panEdgeUp()
					elif MiniKey.DPadDown in liveKeys:
						self.panEdgeDown()
					elif MiniKey.DPadLeft in liveKeys:
						self.panEdgeLeft()
					elif MiniKey.DPadRight in liveKeys:
						self.panEdgeRight()
			elif len(liveKeys) == 4:
				# reset - dots1237
				if MiniKey.Dot1 in liveKeys and MiniKey.Dot2 in liveKeys and MiniKey.Dot3 in liveKeys and MiniKey.Dot4 in liveKeys:
					self.resetAction()
	
		if len(liveKeys) == 1:
			if MiniKey.Row4 in liveKeys:
				self.doToggleImage()
	
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

BrailleDisplayDriver = CadenceDisplayDriver
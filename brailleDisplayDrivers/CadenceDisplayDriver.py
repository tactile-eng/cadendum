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

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

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
	log.info(f"possible cadence device {m}")
	return "Dev_VID&02361f" in m.id

brailleOffsets = [[0,0], [0,1], [0,2], [1,0], [1,1], [1,2], [0,3], [1,3]]

def bitmapToCell(bitmap, cellNum, numCols, numRows):
	cellX = cellNum % numCols
	cellY = math.floor(cellNum / numCols)
	cellOut = 0
	for (pixI, offset) in enumerate(brailleOffsets):
		sourceX = cellX * 2 + offset[0]
		sourceY = cellY * 4 + offset[1]
		rgb = bitmap[sourceY][sourceX]
		r = rgb.rgbRed
		g = rgb.rgbBlue
		b = rgb.rgbGreen
		y =  0.299*r + 0.587*g + 0.114*b
		valBool = y > (255/2)
		if valBool:
			cellOut += 2**pixI
	return cellOut

# https://stackoverflow.com/questions/12435211/threading-timer-repeat-function-every-n-seconds
class RunInterval(threading.Thread):
	stopFlag = threading.Event()
	interval = 1
	callback = None

	def __init__(self, callback, interval = 1):
		super().__init__()
		self.callback = callback
		self.interval = interval
		self.daemon = True
	
	def cancel(self):
		self.stopFlag.set()

	def run(self):
		while not self.stopFlag.wait(self.interval):
			try:
				self.callback()
			except Exception as e:
				log.error(f"{e}")
				pass

class CadenceDisplayDriver(HidBrailleDriver):
	name = "CadenceDisplayDriver"
	# Translators: The name of a series of braille displays.
	description = _("Cadence HID Braille Display")

	displayingImage = False
	lastDisplayedNonImage = None
	imageTimer = None

	centerX = 0.5
	centerY = 0.5
	zoomX = 1
	zoomY = 1
	lastFitWidth = -1
	lastFitHeight = -1

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		# TODO USB
		# driverRegistrar.addUsbDevices(
		# 	lambda m: isDeviceCadence(m)
		# )

		driverRegistrar.addBluetoothDevices(
			lambda m: isDeviceCadence(m)
		)

	def __init__(self, port="auto"):
		log.info("cadence driver initialized")
		super().__init__(port)

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
		log.info(f"######## screenshot {left} {top} {width} {height}")
		if width <= 0 or height <= 0:
			log.error("invalid object location")
			return
		if resetView or self.lastFitWidth != width or self.lastFitHeight != height:
			self.reset(width, height)
		screenWidth = self.getDisplayWidth()
		screenHeight = self.getDisplayHeight()

		topLeftX = self.screenXToVirtual(0, self.getDisplayWidth()) * width
		bottomRightY = self.screenYToVirtual(0, self.getDisplayHeight()) * height
		bottomRightX = self.screenXToVirtual(self.getDisplayWidth(), self.getDisplayWidth()) * width
		topLeftY = self.screenYToVirtual(self.getDisplayHeight(), self.getDisplayHeight()) * height

		log.info(f"{topLeftX} {topLeftY} {bottomRightX} {bottomRightY}")

		bitmapHolder = ScreenBitmapResized(screenWidth, screenHeight)
		bitmapBuffer = bitmapHolder.captureImage(left, top, width, height, round(topLeftX), round(topLeftY), round(bottomRightX - topLeftX), round(bottomRightY - topLeftY))
		testImage = [bitmapToCell(bitmapBuffer, i, self.numCols, self.numRows) for i in range(self.numCells)]
		self.display(testImage, True)
	
	def restoreFromImage(self):
		if self.lastDisplayedNonImage is not None:
			self.display(self.lastDisplayedNonImage)

	def display(self, cells: List[int], isImage = False):
		if not isImage:
			self.lastDisplayedNonImage = cells
		if isImage == self.displayingImage:
			super().display(cells)

	def terminate(self):
		super.terminate()
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
		self.centerX = 0.5
		self.centerY = 0.5
		fitZoom = self.getFitZoom(toDrawWidth, toDrawHeight)
		self.zoomX = fitZoom[0]
		self.zoomY = fitZoom[1]
		self.lastFitWidth = toDrawWidth
		self.lastFitHeight = toDrawHeight
	def virtualXToScreen(self, actualX, graphWidth):
		return (actualX - self.centerX) * self.zoomX * ((graphWidth) / 2) + (graphWidth) / 2
	def virtualYToScreen(self, actualY, graphHeight):
		return graphHeight - ((actualY - self.centerY) * self.zoomY * ((graphHeight) / 2) + (graphHeight) / 2)
	def screenXToVirtual(self, graphX, graphWidth):
		return ((graphX) - ((graphWidth) / 2)) / ((graphWidth) / 2) / self.zoomX + self.centerX
	def screenYToVirtual(self, graphY, graphHeight):
		return ((graphHeight - graphY) - ((graphHeight) / 2)) / ((graphHeight) / 2) / self.zoomY + self.centerY


BrailleDisplayDriver = CadenceDisplayDriver
from logHandler import log
from brailleDisplayDrivers.hidBrailleStandard import HidBrailleDriver, InputGesture
import bdDetect
from typing import List
import api
from NVDAObjects import NVDAObject
from screenBitmap import ScreenBitmap
import math

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


class CadenceDisplayDriver(HidBrailleDriver):
	name = "CadenceDisplayDriver"
	# Translators: The name of a series of braille displays.
	description = _("Cadence HID Braille Display")

	displayingImage = False
	lastDisplayedNonImage = None

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
			self.displayImage()
		else:
			self.restoreFromImage()
	
	def displayImage(self):
		obj = api.getNavigatorObject()
		location = obj.location
		if not location:
			log.error("no location for object when displaying image")
			return
		(left, top, width, height) = location
		log.info(f"######## sscreenshot {location} {left} {top} {width} {height}")
		screenWidth = self.numCols * 2
		screenHeight = self.numRows * 4
		bitmapHolder = ScreenBitmap(screenWidth, screenHeight)
		bitmapBuffer = bitmapHolder.captureImage(left, top, width, height)
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

BrailleDisplayDriver = CadenceDisplayDriver
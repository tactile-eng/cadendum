import ctypes.wintypes
from logHandler import log
import api
from screenBitmap import ScreenBitmap
import threading
import ctypes
from enum import Enum
import queueHandler
from brailleDisplayDrivers.lib.MainCadenceDisplayDriver import MainCadenceDisplayDriver, MiniKey, imageToCells, DevSide
from brailleDisplayDrivers.lib.Sliders import Slider, CombinedSlider, PanSlider

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# a cardinal direction
class Direction(Enum):
	Up = 0
	Down = 1
	Left = 2
	Right = 3

# view & navigation constants
defaultPanRate = 2
panRateRate = 1.5
defaultZoomRate = 1.25
zoomRateRate = 1.5
bwThresholdOutOf = 100
defaultBwThresholdRate = 7
DOT_ASPECT_RATIO = 3.3 / 2.6

def getScreenResolution():
	screen = user32.GetDC(0)
	width = gdi32.GetDeviceCaps(screen, 8)  # HORZRES
	height = gdi32.GetDeviceCaps(screen, 10)  # VERTRES
	log.info(f"########## SCREEN RES {width}x{height}")
	user32.ReleaseDC(0, screen)
	return (width, height)

# winGDI bitmap to boolean 2d array
def bitmapToImage(bitmap, width: int, height: int, bwThreshold: float, bwReversed: bool, colorMode: int) -> list[list[bool]]:
	imageOut: list[list[bool]] = []
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

# a timer that repeatedly runs a function every n seconds
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

# Extends the driver to support image mode
class CadenceDisplayDriverWithImage(MainCadenceDisplayDriver):
	displayingImage: bool
	lastDisplayedNonImage: list[int] | None
	imageTimer: RunInterval | None

	lastLeft: int
	lastTop: int
	lastFitWidth: int
	lastFitHeight: int

	def __init__(self, port):
		# initialize properties
		self.displayingImage = False
		self.lastDisplayedNonImage = None
		self.imageTimer = None
		self.lastLeft = -1
		self.lastTop = -1
		self.lastFitWidth = -1
		self.lastFitHeight = -1

		screenWidth, screenHeight = getScreenResolution()

		# initialize more properties
		self.zoomX = Slider(-1,
			defaultZoomRate,
			zoomRateRate,
			True,
			False,
			0.00000000001,
			1000000000,
			True)
		self.zoomY = Slider(-1,
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
			screenWidth,
			True,
			lambda: self.zoomX.get() * 24 / 2)
		self.centerY = PanSlider(0,
			defaultPanRate,
			panRateRate,
			False,
			False,
			-screenHeight,
			0,
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
		self.bwReversed = True
		self.colorMode = 0
		self.correctAspectRatio = True
		
		super().__init__(port)

	def shouldStopKeys(self):
		return self.displayingImage
	
	def display(self, cells: list[int], isImage = False):
		if not isImage:
			self.lastDisplayedNonImage = cells
		if isImage == self.displayingImage:
			super().display(cells)

	# toggle between text and image mode
	def doToggleImage(self):
		self.displayingImage = not self.displayingImage
		if self.displayingImage:
			self.displayImage()
			if self.imageTimer is None:
				self.imageTimer = RunInterval(self.displayImage, 0.5)
				self.imageTimer.start()
		else:
			self.restoreNonImage()
			if self.imageTimer is not None:
				self.imageTimer.cancel()
				self.imageTimer = None
		self.updateOneHanded()

	# draw image mode (screencapture of current navigator object)
	def displayImage(self, resetView = False):
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyDisplayImage(resetView),
			_immediate=True,
		)
	def actuallyDisplayImage(self, resetView = False):
		obj = api.getNavigatorObject()
		if obj is None:
			log.info("no navigator object, switching to focus object")
			obj = api.getFocusObject()
			if obj is None:
				log.error("no focus object")
				self.doToggleImage()
				return
		self.prevObj = obj
		while obj is not None and obj.location is None:
			log.warn("object has no location, trying parent")
			obj = obj.parent
		if obj is None:
			log.error("no location for object when displaying image")
			self.doToggleImage()
			return
		location = obj.location
		(left, top, width, height) = location
		log.info(f"######## screenshot {left} {top} {width} {height}")
		if width <= 0 or height <= 0:
			log.error("invalid object location")
			self.doToggleImage()
			return
		if resetView or left != self.lastLeft or top != self.lastTop or self.lastFitWidth != width or self.lastFitHeight != height:
			self.reset(left, top, width, height)
		screenWidth = self.getDisplayWidth()
		screenHeight = self.getDisplayHeight()

		topLeftX = self.screenXToVirtual(0, self.getDisplayWidth())
		topLeftY = -self.screenYToVirtual(0, self.getDisplayHeight())
		bottomRightX = self.screenXToVirtual(self.getDisplayWidth(), self.getDisplayWidth())
		bottomRightY = -self.screenYToVirtual(self.getDisplayHeight(), self.getDisplayHeight())

		bitmapHolder = ScreenBitmap(screenWidth, screenHeight)
		# TODO don't round here
		bitmapBuffer = bitmapHolder.captureImage(round(topLeftX), round(topLeftY), round(bottomRightX - topLeftX), round(bottomRightY - topLeftY))
		boolImage = bitmapToImage(bitmapBuffer, screenWidth, screenHeight, self.bwThreshold.get(), self.bwReversed, self.colorMode)
		cells = imageToCells(boolImage)
		self.display(cells, True)

	# restore text mode by drawing text
	def restoreNonImage(self):
		if self.lastDisplayedNonImage is not None:
			self.display(self.lastDisplayedNonImage)

	# cleanup on exit (called by NVDA)
	def terminate(self):
		try:
			super().terminate()
		finally:
			if self.imageTimer is not None:
				self.imageTimer.cancel()
				self.imageTimer = None
			log.info("## Terminate CadenceDisplayDriverWithImage")
			for device in self.devices:
				device.terminate()

	# helper functions for screen size
	def getDisplayWidth(self):
		return self.numCols * 2
	def getDisplayHeight(self):
		return self.numRows * 4
	# reset image view
	def reset(self, left, top, toDrawWidth, toDrawHeight):
		self.centerX.set(left + toDrawWidth / 2)
		self.centerY.set(-(top + toDrawHeight / 2))
		fullZoom = min(2 / toDrawWidth, 2 / toDrawHeight / self.getTargetAspectRatio(self.correctAspectRatio))
		halfZoom = max(1 / toDrawWidth, 1 / toDrawHeight / self.getTargetAspectRatio(self.correctAspectRatio))
		zoom = max(halfZoom, fullZoom)
		self.zoomX.set(zoom)
		self.zoomY.set(zoom * self.getTargetAspectRatio(self.correctAspectRatio))
		self.lastLeft = left
		self.lastTop = top
		self.lastFitWidth = toDrawWidth
		self.lastFitHeight = toDrawHeight
	# helper functions for image mode - see NavigatibleCanvas in CadenceOS
	def virtualXToScreen(self, actualX, graphWidth):
		return (actualX - self.centerX.get()) * self.zoomX.get() * ((graphWidth) / 2) + (graphWidth) / 2
	def virtualYToScreen(self, actualY, graphHeight):
		return graphHeight - ((actualY - self.centerY.get()) * self.zoomY.get() * ((graphHeight) / 2) + (graphHeight) / 2)
	def screenXToVirtual(self, graphX, graphWidth):
		return ((graphX) - ((graphWidth) / 2)) / ((graphWidth) / 2) / self.zoomX.get() + self.centerX.get()
	def screenYToVirtual(self, graphY, graphHeight):
		return ((graphHeight - graphY) - ((graphHeight) / 2)) / ((graphHeight) / 2) / self.zoomY.get() + self.centerY.get()
	
	def getTargetAspectRatio(self, correct: bool):
		return (self.getDisplayWidth()) / (self.getDisplayHeight()) * (DOT_ASPECT_RATIO if correct else 1)

	# pan image
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
	# zoom image
	def zoom(self, zoomIn: bool):
		log.info("zoom")
		if zoomIn:
			self.combinedZoom.increase()
		else:
			self.combinedZoom.decrease()
		self.displayImage()
	# change image threshold
	def changeThreshold(self, increase: bool):
		log.info("changeThreshold")
		if increase:
			self.bwThreshold.increase()
		else:
			self.bwThreshold.decrease()
		self.displayImage()
	# reverse image threshold
	def reverseThreshold(self):
		log.info("reverse threshold")
		self.bwReversed = not self.bwReversed
		self.displayImage()
	# cycle image color mode
	def cycleColorMode(self):
		log.info("cycle color mode")
		self.colorMode = (self.colorMode + 1) % 4
		self.displayImage()
	# reset image view
	def resetAction(self):
		log.info("reset")
		self.bwThreshold.reset()
		self.colorMode = 0
		self.bwReversed = True
		self.zoomX.set(-1)
		self.zoomY.set(-1)
		self.displayImage(True)
	# change image pan rate
	def changePanRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} pan rate")
		if increase:
			self.combinedPan.increaseRate()
		else:
			self.combinedPan.decreaseRate()
	# change image zoom rate
	def changeZoomRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} zoom rate")
		if increase:
			self.combinedZoom.increaseRate()
		else:
			self.combinedZoom.decreaseRate()
	# change image threshold rate
	def changeThresholdRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} threshold rate")
		if increase:
			self.bwThreshold.increaseRate()
		else:
			self.bwThreshold.decreaseRate()
	# pan image to edge
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
	def toggleAspectRatio(self):
		self.correctAspectRatio = not self.correctAspectRatio
		zoomY = self.zoomY.get()
		zoomX = zoomY / self.getTargetAspectRatio(self.correctAspectRatio)
		self.zoomX.set(zoomX)
		self.displayImage()

	def shouldBeOneHanded(self):
		return False if self.displayingImage else super().shouldBeOneHanded()

	# run after changing device positions to update screens
	def afterDevicePositionsChanged(self):
		super().afterDevicePositionsChanged()
		if self.displayingImage:
			self.displayImage(True)
		else:
			self.restoreNonImage()

	# handle keys
	def handleKeys(self, liveKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]], composedKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]]):
		super().handleKeys(liveKeysWithPosition, composedKeysWithPosition)

		liveKeys = [key[0] for key in liveKeysWithPosition]

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
				# reset - dots37
				if MiniKey.Dot3 in liveKeys and MiniKey.Dot7 in liveKeys:
					self.resetAction()
				# toggle correct aspect ratio
				if MiniKey.Space in liveKeys and MiniKey.DPadCenter in liveKeys:
					self.toggleAspectRatio()

		if len(liveKeys) == 1:
			if MiniKey.Row3 in liveKeys:
				self.doToggleImage()

class TestCadenceDisplayDriver(MainCadenceDisplayDriver):
	def __init__(self, port):
		super().__init__(port)

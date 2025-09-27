from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage, RunInterval
from logHandler import log
import queueHandler

class CadenceDisplayDriverWithTable(CadenceDisplayDriverWithImage):
	displayingTable: bool
	tableTimer: RunInterval | None
	lastDisplayedNonTable: list[int] | None

	def __init__(self, port):
		self.displayingTable = False
		self.tableTimer = None
		self.lastDisplayedNonTable = None

		super().__init__(port)

	def doToggleTable(self):
		log.info(f"######## toggle table")
		if self.displayingImage:
			self.doToggleImage()
		
		self.displayingTable = not self.displayingTable

		if self.displayingTable:
			self.displayTable()
			if self.tableTimer is None:
				self.tableTimer = RunInterval(self.displayTable, 0.5)
				self.tableTimer.start()
		else:
			self.restoreNonTable()
			if self.tableTimer is not None:
				self.tableTimer.cancel()
				self.tableTimer = None

	
	def doToggleImage(self):
		if self.displayingTable:
			self.doToggleTable()
		
		super().doToggleImage()
	
	def display(self, cells: list[int], isImage = False, isTable = False):
		if not isTable:
			self.lastDisplayedNonTable = cells
		if isTable == self.displayingTable:
			super().display(cells, isImage)

	def displayTable(self, resetView = False):
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyDisplayTable(resetView),
			_immediate=True,
		)
	
	def actuallyDisplayTable(self, resetView = False):
		log.info(f"######## actuallyDisplayTable")
		self.display([255] * self.numCols * self.numRows, False, True)

	# restore text mode by drawing text
	def restoreNonTable(self):
		if self.lastDisplayedNonTable is not None:
			self.display(self.lastDisplayedNonTable)

	# cleanup on exit (called by NVDA)
	def terminate(self):
		try:
			super().terminate()
		finally:
			if self.tableTimer is not None:
				self.tableTimer.cancel()
				self.tableTimer = None
			log.info("## Terminate CadenceDisplayDriverWithTable")

from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage, RunInterval
from logHandler import log
import queueHandler
import api
import controlTypes
from braille import NVDAObjectRegion

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

	def getCell(self, table, row, col):
		row_obj = table.children[row]
		if row_obj is None:
			return None
		return row_obj.children[col]

	def getTableInfo(self):
		obj = api.getNavigatorObject()
		if obj is None:
			log.info("no navigator object, switching to focus object")
			obj = api.getFocusObject()
			if obj is None:
				log.error("no focus object")
				return None

		table_search_obj = obj
		index_stack = []
		while table_search_obj.parent != None and table_search_obj.role != controlTypes.ROLE_TABLE:
			log.info(f"search {table_search_obj.name} {table_search_obj.role} {table_search_obj.table}")
			index_stack.append(table_search_obj.indexInParent)
			table_search_obj = table_search_obj.parent

		if table_search_obj.role != controlTypes.ROLE_TABLE:
			log.error("unable to find table")
			return None

		table_obj = table_search_obj
		if len(index_stack) >= 2:
			row = index_stack[-1]
			col = index_stack[-2]
		else:
			row = 0
			col = 0
		cell_obj = self.getCell(table_obj, row, col)
		if cell_obj == None:
			log.error(f"unable to get cell {row} {col}")
			return None

		log.info(f"table: {table_obj} {table_obj.name}")
		log.info(f"cell: {cell_obj} {cell_obj.name}")
		log.info(f"pos: {row} {col}")

		return table_obj, cell_obj, row, col

	def actuallyDisplayTable(self, resetView = False):
		log.info(f"######## actuallyDisplayTable")

		table_info = self.getTableInfo()
		if table_info == None:
			self.doToggleTable()
			return

		table_obj, cell_obj, row, col = table_info

		cell_obj_region = NVDAObjectRegion(cell_obj)
		cell_obj_region.update()
		text = cell_obj_region.brailleCells

		availableSpace = self.numRows * self.numCols
		textReformatted = text[:availableSpace] + ([0] * max(availableSpace - len(text), 0))

		self.display(textReformatted, False, True)

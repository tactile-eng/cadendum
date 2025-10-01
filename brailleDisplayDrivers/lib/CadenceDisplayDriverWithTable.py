from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage, RunInterval, Direction
from logHandler import log
import queueHandler
import api
import controlTypes
from braille import NVDAObjectRegion, TextRegion
from collections import namedtuple
import math
from brailleDisplayDrivers.lib.MainCadenceDisplayDriver import MiniKey, DevSide, MiniKeyInputGesture, DOT_KEYS

rowCol = namedtuple("rowcol", ["row", "col"])
maxColHeaderChars = 4

BRAILLE_COMPUTER_CODE = [
	"\u2800", "⠮", "⠐", "⠼", "⠫", "⠩", "⠯", "⠄", "⠷", "⠾", "⠡", "⠬", "⠠", "⠤", "⠨", "⠌",            # \x20 - \x2f (' ' - '/')
	"⠴", "⠂", "⠆", "⠒", "⠲", "⠢", "⠖", "⠶", "⠦", "⠔", "⠱", "⠰", "⠣", "⠿", "⠜", "⠹",                 # \x30 - \x3f ('0' - '?')
	"⠈", "⠸⠁", "⠸⠃", "⠸⠉", "⠸⠙", "⠸⠑", "⠸⠋", "⠸⠛", "⠸⠓", "⠸⠊", "⠸⠚", "⠸⠅", "⠸⠇", "⠸⠍", "⠸⠝", "⠸⠕",  # \x40 - \x4f ('@' - 'O')
	"⠸⠏", "⠸⠟", "⠸⠗", "⠸⠎", "⠸⠞", "⠸⠥", "⠸⠧", "⠸⠺", "⠸⠭", "⠸⠽", "⠸⠵", "⠪", "⠳", "⠻", "⠘", "⠸⠸",     # \x50 - \x5f ('P' - '_')
	"⠸⠈", "⠁", "⠃", "⠉", "⠙", "⠑", "⠋", "⠛", "⠓", "⠊", "⠚", "⠅", "⠇", "⠍", "⠝", "⠕",                # \x60 - \x6f ('`' - 'o')
	"⠏", "⠟", "⠗", "⠎", "⠞", "⠥", "⠧", "⠺", "⠭", "⠽", "⠵", "⠸⠪", "⠸⠳", "⠸⠻", "⠸⠘",        # \x70 - \x7f ('p' - '\x7f')
]
BRAILLE_LOOKUP = {}
for i, char in enumerate(BRAILLE_COMPUTER_CODE):
	if len(char) == 1:
		key = ord(char) - 0x2800
		val = chr(i + 0x20)
		BRAILLE_LOOKUP[key] = val
def backTranslate(text: list[int]):
	out = ""
	for braille_char in text:
		out += BRAILLE_LOOKUP[braille_char] or "?"
	return out

class CadenceDisplayDriverWithTable(CadenceDisplayDriverWithImage):
	displayingTable: bool
	tableTimer: RunInterval | None
	lastDisplayedNonTable: list[int] | None
	showCellPositionsDevice: bool
	showFixedColumnHeader: bool
	showFixedRowHeader: bool
	panHorizontal: int

	def __init__(self, port):
		self.displayingTable = False
		self.tableTimer = None
		self.lastDisplayedNonTable = None
		self.showCellPositionsDevice = False
		self.showFixedColumnHeader = True
		self.showFixedRowHeader = True
		self.panHorizontal = 0

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
			try: 
				index_stack.append(table_search_obj.indexInParent)
				table_search_obj = table_search_obj.parent
			except NotImplementedError:
				log.warn("NotImplementedError")
				return None

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
	
	def getTableSize(self, table_obj):
		tableHeight = len(table_obj.children)
		tableWidth = max([len(row.children) for row in table_obj.children])

		return tableWidth, tableHeight

	def displayText(self, text):
		region = TextRegion(text)
		region.update()
		braille = region.brailleCells
		braille = braille[:(self.numRows * self.numCols)]
		while len(braille) < self.numRows * self.numCols:
			braille.append(0)
		self.display(braille, False, True)

	def actuallyDisplayTable(self, resetView = False):
		log.info(f"######## actuallyDisplayTable")

		table_info = self.getTableInfo()
		if table_info == None:
			self.displayText("not in table")
			return

		table_obj, cell_obj, row, col = table_info

		tableWidth, tableHeight = self.getTableSize(table_obj)

		log.info(f"{table_obj} {cell_obj} {row} {col} {tableWidth} {tableHeight}")

		self.draw(table_obj, tableWidth, tableHeight, max(row - 1, 0) if self.showFixedColumnHeader else row, col)

	"""
	 * Information on how large table is, how many headers, where data is scrolled
	 * @param isDevice true if is for device, false for GUI
	 * @returns table layout info
	"""
	def getTableLayoutInfo(self, deviceTableTop, deviceActiveColumn):
		showCellPositions = self.showCellPositionsDevice
		showColumnHeaders = self.showFixedColumnHeader and not showCellPositions
		showRowHeaders = self.showFixedRowHeader and not showCellPositions
		numRowsHeaders = (1 if showCellPositions else 0) + (1 if showColumnHeaders else 0)
		numColsHeaders = (1 if showCellPositions else 0) + (1 if showRowHeaders else 0)
		numRowsTotal = self.numRows
		numColsTotal = self.numCols
		numRowsWithoutHeaders = numRowsTotal - numRowsHeaders
		numColsWithoutHeaders = numColsTotal - numColsHeaders
		rowScrollOffset = 1 if showColumnHeaders else 0
		colScrollOffset = 0 if showRowHeaders else 0
		rowStartWithoutHeaders = (deviceTableTop) + rowScrollOffset
		colStartWithoutHeaders = (1 if deviceActiveColumn == 0 and showRowHeaders else deviceActiveColumn) + colScrollOffset
		tableInfo = {
			"showCellPositions": showCellPositions,
			"showColumnHeaders": showColumnHeaders,
			"showRowHeaders": showRowHeaders,
			"numRowsHeaders": numRowsHeaders,
			"numColsHeaders": numColsHeaders,
			"numRowsTotal": numRowsTotal,
			"numColsTotal": numColsTotal,
			"numRowsWithoutHeaders": numRowsWithoutHeaders,
			"numColsWithoutHeaders": numColsWithoutHeaders,
			"rowScrollOffset": rowScrollOffset,
			"colScrollOffset": colScrollOffset,
			"rowStartWithoutHeaders": rowStartWithoutHeaders,
			"colStartWithoutHeaders": colStartWithoutHeaders,
		}
		log.info(f"tableInfo: {tableInfo}")
		return namedtuple("TableLayout", tableInfo)(**tableInfo)

	"""
	 * get rows and columns for a certain position in the topleft, WITHOUT fixed rows/columns if active
	 * @param size number of rows and columns to get
	 * @param topLeft the top-left position of the data to get
	 * @returns the data
	 * @group Table - Internals
	"""
	def getRowsColsWithoutHeaders(self, tableWidth, tableHeight, numRows, numCols, rowStart, colStart):
		rows = []
		for rowI in range(numRows):
			row = rowI + rowStart
			if row < tableHeight:
				rowCols = []
				for colI in range(numCols):
					col = colI + colStart
					if col < tableWidth:
						rowCols.append(rowCol(row=row, col=col))
				rows.append(rowCols)
		log.info(f"getRowsColsWithoutHeaders: {rows}")
		return rows

	"""
	 * get rows and columns for a certain position in the topleft, with fixed rows/columns if active
	 * @param size number of rows and columns to get
	 * @param topLeft the top-left position of the data to get
	 * @returns the data
	 * @group Table - Internals
	"""
	def getRowsColsWithHeaders(self, tableWidth, tableHeight, deviceTableTop, deviceActiveColumn):
		layoutInfo = self.getTableLayoutInfo(deviceTableTop, deviceActiveColumn)
		rowsCols = self.getRowsColsWithoutHeaders(
			tableWidth,
			tableHeight,
			layoutInfo.numRowsWithoutHeaders,
			layoutInfo.numColsWithoutHeaders,
			layoutInfo.rowStartWithoutHeaders,
			layoutInfo.colStartWithoutHeaders,
		)
		if len(rowsCols) == 0 or len(rowsCols[0]) == 0:
			return rowsCols
		if layoutInfo.showColumnHeaders:
			rowsCols = [[rowCol(row=0, col=firstRowElement.col) for firstRowElement in rowsCols[0]]] + rowsCols
		if layoutInfo.showRowHeaders:
			rowsCols = [[rowCol(row=row[0].row, col=0)] + row for row in rowsCols]
		if layoutInfo.showCellPositions:
			rowsCols = [
				[rowCol(row=None, col=None)] + [rowCol(row=None, col=firstRowElement.col) for firstRowElement in rowsCols[0]]
			] + [[rowCol(row=row[0].row, col=None)] + row for row in rowsCols]
		log.info(f"getRowsColsWithHeaders: {rowsCols}")
		return rowsCols

	"""
	 * translate data to braille
	 * @param nifty NiftyTranslator braille translator
	 * @param rowsColsUntranslated the data to translate
	 * @returns the translated data
	 * @group Table - Internals
	"""
	def translateRows(self, rowsColsUntranslated):
		# translate to braille
		rowsColsTranslated = []
		for rowUntranslated in rowsColsUntranslated:
			rowTranslated = []
			for untranslated in rowUntranslated:
				if type(untranslated) == str:
					region = TextRegion(untranslated)
				else:
					region = NVDAObjectRegion(untranslated)
				region.update()
				rowTranslated.append(region.brailleCells)
			rowsColsTranslated.append(rowTranslated)
		log.info(f"rowsColsTranslated: {[[backTranslate(cell) for cell in row] for row in rowsColsTranslated]}")
		return rowsColsTranslated

	# fit an entry inside the column width, with text panning. Pad ⠐s to the right so it's easier to tell where the columns are.
	def fitTextEntry(self, text, width, panHorizontal, rowI, colI):
		# text panning
		if (panHorizontal > 0):
			text = text[max(min(width * panHorizontal, len(text) - width), 0):]
		# truncate to width
		text = text[0:width]
		# add a space between the text and the ⠐s
		if (len(text) < width and len(text) != 0):
			text.append(0)
		# end with ⠐s
		filler = 2**4 if ((math.floor(rowI / 3) + math.floor(colI / 3)) % 2 == 0) else 2**3 + 2**4 + 2**5
		while len(text) < width:
			text.append(filler)
		# log.info(f"fit: {text}")
		return text


	"""
	 * draw on device
	 * @group Table - Internals
	"""
	def draw(self, table_obj, tableWidth, tableHeight, deviceTableTop, deviceActiveColumn):
		rowsColsNumbers = self.getRowsColsWithHeaders(tableWidth, tableHeight, deviceTableTop, deviceActiveColumn)
		# populate data (ascii)
		rowsColsUntranslated = []
		for rowNums in rowsColsNumbers:
			rowUntranslated = []
			for cell in rowNums:
				row = cell.row
				col = cell.col
				if (row == None):
					if (col == None):
						data = ""
					else:
						data = self.columnNumberToLetters(col + 1)
				elif col == None:
					data = str(row + 1)
				else:
					data = self.getCell(table_obj, row, col)
				rowUntranslated.append(data)
			rowsColsUntranslated.append(rowUntranslated)
		# translate
		rowsColsTranslated = self.translateRows(rowsColsUntranslated)
		# return if no data
		if len(rowsColsTranslated) == 0:
			self.displayText("empty table")
			return
		# calculate width of each column using maximum text length
		numCols = len(rowsColsTranslated[0])
		colWidths = [0] * numCols
		for _rowI, rowArr in enumerate(rowsColsTranslated):
			for colI, text in enumerate(rowArr):
				colWidths[colI] = max(colWidths[colI], len(text))
		log.info(f"colWidths 1: {colWidths}")
		# where is active column
		cursorColIs = [i for i, col in enumerate(rowsColsNumbers[0]) if col.col == deviceActiveColumn]
		if len(cursorColIs) != 1:
			log.error("unknown error - unable to find cursor column")
			self.displayText("table error")
			return
		cursorColI = cursorColIs[0]
		log.info(f"cursorColI: {cursorColI}")
		# limit the size of the first column if row headers are active but not the selected column, if necessary, to have more space for the actual data
		for i in range(cursorColI):
			colWidths[i] = min(colWidths[i], maxColHeaderChars)
		# make all empty columns take up 1 space
		colWidths = [max(width, 1) for width in colWidths]
		log.info(f"colWidths 2: {colWidths}")
		# find x position of active column
		cursorColX = 0
		for i in range(cursorColI):
			cursorColX += colWidths[i] + 1
		log.info(f"cursorColX: {cursorColX}")
		# limit active column to device width (and even smaller if there's more data to the right so we can indicate that there's more data)
		if cursorColX + colWidths[cursorColI] > self.numCols - 2:
			if (cursorColI + 1 < len(colWidths) and colWidths[cursorColI + 1] > 0):
				colWidths[cursorColI] = max(self.numCols - cursorColX - 2, 1)
			elif (cursorColX + colWidths[cursorColI] > self.numCols):
				colWidths[cursorColI] = max(self.numCols - cursorColX, 1)
		log.info(f"colWidths 3: {colWidths}")
		# write data into lines
		lines = []
		for rowI, row in enumerate(rowsColsTranslated):
			line = []
			for colI, text in enumerate(row):
				if colI != 0:
					line.append(0)
				fitted = self.fitTextEntry(text, colWidths[colI], self.panHorizontal if colI == cursorColI else 0, -1 if rowsColsNumbers[rowI][colI].row == None else rowsColsNumbers[rowI][colI].row, -1 if rowsColsNumbers[rowI][colI].col == None else rowsColsNumbers[rowI][colI].col)
				line += fitted
			line = line[:self.numCols]
			while len(line) < self.numCols:
				line.append(0)
			lines += line
			log.info(f"line: {backTranslate(line)}")
		
		while len(lines) < self.numRows * self.numCols:
			lines.append(0)
		
		# display lines
		# self.display.moveCursor(cursorColX, 0)
		self.display(lines, False, True)

	def moveTable(self, direction):
		pass

	# run after changing device positions to update screens
	def afterDevicePositionsChanged(self):
		super().afterDevicePositionsChanged()
		if self.displayingTable:
			self.displayTable(True)
		else:
			self.restoreNonTable()

	# handle keys
	def handleKeys(self, liveKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]], composedKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]], gesture: MiniKeyInputGesture | None):
		liveKeys = [key[0] for key in liveKeysWithPosition]
		composedKeys = [key[0] for key in self.composedKeys]
		allKeys = liveKeys + composedKeys

		if not self.displayingTable or all([key in [MiniKey.Space] + DOT_KEYS for key in allKeys]):
			super().handleKeys(liveKeysWithPosition, composedKeysWithPosition, gesture)

		if self.displayingTable:
			if len(liveKeys) == 1 and len(composedKeys) == 0:
				# move - arrow keys
				if MiniKey.DPadUp in liveKeys:
					self.moveTable(Direction.Up)
				elif MiniKey.DPadDown in liveKeys:
					self.moveTable(Direction.Down)
				elif MiniKey.DPadLeft in liveKeys:
					self.moveTable(Direction.Left)
				elif MiniKey.DPadRight in liveKeys:
					self.moveTable(Direction.Right)

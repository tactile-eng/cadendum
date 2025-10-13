from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage, RunInterval, Direction
from logHandler import log
import queueHandler
import api
import controlTypes
from braille import NVDAObjectRegion, TextRegion
from collections import namedtuple
import math
from brailleDisplayDrivers.lib.MainCadenceDisplayDriver import MiniKey, DevSide, MiniKeyInputGesture, DOT_KEYS, DevPosition
from NVDAObjects import NVDAObject
from NVDAObjects.window.excel import ExcelWorksheet, ExcelCell

rowCol = namedtuple("rowcol", ["row", "col"])
savedTableInfo = namedtuple("savedTableInfo", ["table_obj", "width", "height", "row", "col"])
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
		out += BRAILLE_LOOKUP[braille_char] if braille_char in BRAILLE_LOOKUP else "?"
	return out

rowButtonNumbers = {
	MiniKey.Row1: 0,
	MiniKey.Row2: 1,
	MiniKey.Row3: 2,
	MiniKey.Row4: 3,
}

class CadenceDisplayDriverWithTable(CadenceDisplayDriverWithImage):
	displayingTable: bool
	tableTimer: RunInterval | None
	lastDisplayedNonTable: list[int] | None
	showCellPositionsDevice: bool
	showFixedColumnHeader: bool
	showFixedRowHeader: bool
	panHorizontal: int
	blink: bool
	maxPanHorizontal = 0
	lastTableTop: tuple[int, NVDAObject] | None

	columnHeaderTextToStrip: list[int]
	rowHeaderTextToStrip: list[int]

	def __init__(self, port):
		self.displayingTable = False
		self.tableTimer = None
		self.lastDisplayedNonTable = None
		self.showCellPositionsDevice = False
		self.showFixedColumnHeader = True
		self.showFixedRowHeader = True
		self.panHorizontal = 0
		self.blink = True
		self.lastTableTop = None

		columnHeaderTextToStripRegion = TextRegion(" column header")
		columnHeaderTextToStripRegion.update()
		self.columnHeaderTextToStrip = columnHeaderTextToStripRegion.brailleCells
		rowHeaderTextToStripRegion = TextRegion(" row header")
		rowHeaderTextToStripRegion.update()
		self.rowHeaderTextToStrip = rowHeaderTextToStripRegion.brailleCells

		super().__init__(port)

	def doToggleTable(self):
		log.info(f"######## toggle table")
		if self.displayingImage:
			self.doToggleImage()

		self.displayingTable = not self.displayingTable

		if self.displayingTable:
			self.blink = True
			self.panHorizontal = 0

			self.displayTable()
			if self.tableTimer is None:
				self.tableTimer = RunInterval(self.toggleBlinkAndDisplayTable, 0.5)
				self.tableTimer.start()
		else:
			self.restoreNonTable()
			if self.tableTimer is not None:
				self.tableTimer.cancel()
				self.tableTimer = None

	def toggleBlinkAndDisplayTable(self):
		self.blink = not self.blink
		self.displayTable()

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

	def getCellRowDirectly(self, cell):
		row_num = None
		try:
			row_num = cell._get_rowNumber()
		except NotImplementedError:
			pass
		if row_num != None:
			return row_num - 1
		return None

	def getCellColDirectly(self, cell):
		col_num = None
		try:
			col_num = cell._get_columnNumber()
		except NotImplementedError:
			pass
		if col_num != None:
			return col_num - 1
		return None
	
	def isCorrectCell(self, cell, row, col):
		if cell.role == controlTypes.ROLE_TABLECELL or cell.role == controlTypes.ROLE_TABLECOLUMNHEADER or cell.role == controlTypes.ROLE_TABLEROWHEADER:
			row_num = self.getCellRowDirectly(cell)
			col_num = self.getCellColDirectly(cell)
			if row_num == row and col_num == col:
				return True
		return False

	def getCell(self, table, row, col):
		if isinstance(table, ExcelWorksheet):
			cell=table.excelWorksheetObject.cells(row + 1,col + 1) 
			return ExcelCell(windowHandle=table.windowHandle,excelWindowObject=table.excelWindowObject,excelCellObject=cell)

		row_obj = table.firstChild
		row_i = 0

		while row_obj != None:
			if self.isCorrectCell(row_obj, row, col):
				return row_obj
			
			row_num = self.getCellRowDirectly(row_obj)
			if row_num == None:
				row_num = row_i

			if row_num == row:
				col_obj = row_obj.firstChild
				col_i = 0

				while col_obj != None:
					if self.isCorrectCell(col_obj, row, col):
						return col_obj

					col_num = self.getCellColDirectly(col_obj)
					if col_num == None:
						col_num = row_i
					
					if col_num == col:
						return col_obj
					elif col_num > col:
						return None
					
					col_i += 1
					col_obj = col_obj.next

				return None
			elif row_num > row:
				return None
			
			row_i += 1
			row_obj = row_obj.next

		return None

	def getIndexInParent(self, findChild):
		try:
			return findChild._get_indexInParent()
		except NotImplementedError:
			parent = findChild.parent
			child = parent.firstChild
			i = 0
			while child != None:
				if child == findChild:
					return i
				i += 1
				child = child.next
			return None

	def getTableInfo(self):
		obj = api.getNavigatorObject()
		if obj is None:
			log.info("no navigator object, switching to focus object")
			obj = api.getFocusObject()
			if obj is None:
				log.error("no focus object")
				return None
		
		log.info(f"looking for role (table={controlTypes.ROLE_TABLE} row={controlTypes.ROLE_TABLEROW} col={controlTypes.ROLE_TABLECOLUMN} cell={controlTypes.ROLE_TABLECELL} colheader={controlTypes.ROLE_TABLECOLUMNHEADER} rowheader={controlTypes.ROLE_TABLEROWHEADER})")

		table_search_obj = obj
		cell_obj = None
		obj_stack = []
		while table_search_obj.parent != None and table_search_obj.role != controlTypes.ROLE_TABLE:
			if table_search_obj.role == controlTypes.ROLE_TABLECELL:
				cell_obj = table_search_obj
			log.info(f"search {table_search_obj.name} {table_search_obj.role}")
			obj_stack.append(table_search_obj)
			table_search_obj = table_search_obj.parent
		
		if table_search_obj.role != controlTypes.ROLE_TABLE:
			log.error("unable to find table")
			return None

		table_obj = table_search_obj
		log.info(f"found {table_obj.name} {table_obj.role} {table_obj}")

		row = None
		col = None
		if cell_obj != None:
			row = self.getCellRowDirectly(cell_obj)
			col = self.getCellColDirectly(cell_obj)
		if row == None or col == None:
			log.info("table row/col not implemented")
			if len(obj_stack) >= 2:
				row = self.getIndexInParent(obj_stack[-1])
				col = self.getIndexInParent(obj_stack[-2])
			if row == None or col == None:
				row = 0
				col = 0
		log.info(f"{obj_stack} {row} {col}")
		
		log.info("finding table size")
		tableHeight = 0
		tableWidth = 0
		if isinstance(table_obj, ExcelWorksheet):
			tableWidth = None
			tableHeight = None
		else:
			try:
				tableWidth = table_obj._get_columnCount()
				tableHeight = table_obj._get_rowCount()
			except NotImplementedError:
				log.info("table width/height not implemented")
				row_obj = table_obj.firstChild
				while row_obj != None and tableHeight != None and tableWidth != None:
					tableHeight += 1
					if tableHeight > 50:
						tableHeight = None
						tableWidth = None
						break
					thisRowWidth = 0
					col_obj = row_obj.firstChild
					while col_obj != None and tableHeight != None and tableWidth != None:
						thisRowWidth += 1
						if thisRowWidth > 50:
							tableHeight = None
							tableWidth = None
							break
						col_obj = col_obj.next
					if tableWidth == None:
						break
					tableWidth = max(tableWidth, thisRowWidth)
					row_obj = row_obj.next
		
		if tableHeight == None or tableWidth == None:
			log.warn("large table")

		cell_obj = self.getCell(table_obj, row, col)
		if cell_obj == None:
			log.error(f"unable to get cell {row} {col}")
			return None

		log.info(f"table: {table_obj} {table_obj.name}")
		log.info(f"cell: {cell_obj} {cell_obj.name}")
		log.info(f"pos: {row} {col}")

		return table_obj, cell_obj, row, col, tableWidth, tableHeight
	
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

		table_obj, cell_obj, row, col, tableWidth, tableHeight = table_info

		log.info(f"{table_obj} {cell_obj} {row} {col} {tableWidth} {tableHeight}")

		self.draw(table_obj, tableWidth, tableHeight, row, col)

	"""
	 * Information on how large table is, how many headers, where data is scrolled
	 * @param isDevice true if is for device, false for GUI
	 * @returns table layout info
	"""
	def getTableLayoutInfo(self, deviceActiveRow, deviceActiveColumn, table_obj):
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
		if self.lastTableTop != None and table_obj == self.lastTableTop[1]:
			if deviceActiveRow < numRowsHeaders:
				deviceTableTop = self.lastTableTop[0]
				log.info(f"in headers {deviceTableTop}")
			else:
				distanceFromTop = deviceActiveRow - (self.lastTableTop[0] + rowScrollOffset)
				log.info(f"moving table top {distanceFromTop} {math.floor(distanceFromTop / numRowsWithoutHeaders)*numRowsWithoutHeaders}")
				if distanceFromTop < 0:
					deviceTableTop = max(self.lastTableTop[0] + math.floor(distanceFromTop / numRowsWithoutHeaders)*numRowsWithoutHeaders, 0)
				else:
					deviceTableTop = min(self.lastTableTop[0] + math.floor(distanceFromTop / numRowsWithoutHeaders)*numRowsWithoutHeaders, deviceActiveRow - rowScrollOffset)
		else:
			deviceTableTop = max(math.floor((deviceActiveRow - rowScrollOffset) / numRowsWithoutHeaders) * numRowsWithoutHeaders, 0)
			log.info(f"no lastTableTop {math.floor((deviceActiveRow - rowScrollOffset) / numRowsWithoutHeaders)}")
		
		self.lastTableTop = (deviceTableTop, table_obj)

		rowStartWithoutHeaders = (deviceTableTop) + rowScrollOffset
		colStartWithoutHeaders = (1 if deviceActiveColumn == 0 and showRowHeaders else deviceActiveColumn) + colScrollOffset
		tableInfo = {
			"deviceTableTop": deviceTableTop,
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
			if tableHeight == None or row < tableHeight:
				rowCols = []
				for colI in range(numCols):
					col = colI + colStart
					if tableWidth == None or col < tableWidth:
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
	def getRowsColsWithHeaders(self, tableWidth, tableHeight, deviceActiveRow, deviceActiveColumn, table_obj):
		layoutInfo = self.getTableLayoutInfo(deviceActiveRow, deviceActiveColumn, table_obj)
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
				if untranslated == None:
					rowTranslated.append([])
				else:
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

	def columnNumberToLetters(self, colNum, res = ""):
		# https://stackoverflow.com/questions/23861680/convert-spreadsheet-number-to-column-letter
		if colNum > 0:
			return self.columnNumberToLetters(math.floor((colNum - 1) / 26), "abcdefghijklmnopqrstuvwxyz"[(colNum - 1) % 26] + res)
		else:
			return res
	
	def endsWithBraille(self, brailleText: list[int], checkEndsWidth: list[int]):
		if len(brailleText) < len(checkEndsWidth):
			return False

		for i, letter in enumerate(checkEndsWidth):
			checkAgainst = brailleText[i + len(brailleText) - len(checkEndsWidth)]
			if letter != checkAgainst:
				return False
		return True

	def getExcelCellPositionBraille(self, cell, translated):
		address_region = TextRegion(cell._get_cellCoordsText())
		address_region.update()
		address_braille = address_region.brailleCells
		if len(translated) > len(address_braille):
			address_braille = [0] + address_braille
		return address_braille

	"""
	 * draw on device
	 * @group Table - Internals
	"""
	def draw(self, table_obj, tableWidth, tableHeight, deviceActiveRow, deviceActiveColumn):
		rowsColsNumbers = self.getRowsColsWithHeaders(tableWidth, tableHeight, deviceActiveRow, deviceActiveColumn, table_obj)
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
		log.info(f"names: {[[(None if cell == None else (cell if type(cell) == str else cell.name)) for cell in row] for row in rowsColsUntranslated]}")
		# translate
		rowsColsTranslated = self.translateRows(rowsColsUntranslated)
		# strip " column header" / " row header"
		hasColumnHeaderText = True
		hasRowHeaderText = True
		for rowI, rowTranslated in enumerate(rowsColsTranslated):
			for colI, translated in enumerate(rowTranslated):
				pos = rowsColsNumbers[rowI][colI]
				if pos.row == 0 and pos.col != 0 and not self.endsWithBraille(translated, self.columnHeaderTextToStrip):
					hasColumnHeaderText = False
				if pos.col == 0 and pos.row != 0 and not self.endsWithBraille(translated, self.rowHeaderTextToStrip):
					hasRowHeaderText = False
		for rowI, rowTranslated in enumerate(rowsColsTranslated):
			for colI, translated in enumerate(rowTranslated):
				pos = rowsColsNumbers[rowI][colI]
				if hasColumnHeaderText and pos.row == 0 and self.endsWithBraille(translated, self.columnHeaderTextToStrip):
					rowsColsTranslated[rowI][colI] = translated[:-len(self.columnHeaderTextToStrip)]
				if hasRowHeaderText and pos.col == 0 and self.endsWithBraille(translated, self.rowHeaderTextToStrip):
					rowsColsTranslated[rowI][colI] = translated[:-len(self.rowHeaderTextToStrip)]
		# strip position info
		hasPositionText = True
		for rowI, rowTranslated in enumerate(rowsColsTranslated):
			for colI, translated in enumerate(rowTranslated):
				untranslated = rowsColsUntranslated[rowI][colI]
				if isinstance(untranslated, ExcelCell):
					address_braille = self.getExcelCellPositionBraille(untranslated, translated)
					if not self.endsWithBraille(translated, address_braille):
						hasPositionText = False
		if hasPositionText:
			for rowI, rowTranslated in enumerate(rowsColsTranslated):
				for colI, translated in enumerate(rowTranslated):
					untranslated = rowsColsUntranslated[rowI][colI]
					if isinstance(untranslated, ExcelCell):
						address_braille = self.getExcelCellPositionBraille(untranslated, translated)
						rowsColsTranslated[rowI][colI] = translated[:-len(address_braille)]
		log.info(f"rowsColsTranslated stripped: {[[backTranslate(cell) for cell in row] for row in rowsColsTranslated]}")
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
		newMaxPanHorizontal = 0
		for rowI, row in enumerate(rowsColsTranslated):
			line = []
			for colI, text in enumerate(row):
				if colI != 0:
					line.append(0)
				newMaxPanHorizontal = max(newMaxPanHorizontal, math.ceil(len(text) / colWidths[colI]) - 1, 0)
				fitted = self.fitTextEntry(text, colWidths[colI], self.panHorizontal if colI == cursorColI else 0, -1 if rowsColsNumbers[rowI][colI].row == None else rowsColsNumbers[rowI][colI].row, -1 if rowsColsNumbers[rowI][colI].col == None else rowsColsNumbers[rowI][colI].col)
				if self.blink:
					cellPos = rowsColsNumbers[rowI][colI]
					if cellPos.col == deviceActiveColumn and cellPos.row == deviceActiveRow:
						fitted[0] += 2**6 + 2**7
				line += fitted
			line = line[:self.numCols]
			while len(line) < self.numCols:
				line.append(0)
			lines += line
			log.info(f"line: {backTranslate(line)}")
		self.maxPanHorizontal = newMaxPanHorizontal
		
		while len(lines) < self.numRows * self.numCols:
			lines.append(0)
		
		# display lines
		# self.display.moveCursor(cursorColX, 0)
		self.display(lines, False, True)

	def moveTable(self, direction, page=False):
		log.info(f"moveTable {direction} {page}")
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyMoveTable(direction, page),
			_immediate=True,
		)

	def actuallyMoveTable(self, direction, page=False):
		log.info(f"actuallyMoveTable {direction} {page}")
		table_info = self.getTableInfo()
		if table_info == None:
			log.warn("move table when not in table")
			return
		
		table_obj, cell_obj, row, col, tableWidth, tableHeight = table_info

		log.info(f"initial pos {row} {col}")

		if page:
			layout_info = self.getTableLayoutInfo(row, col, table_obj)
			amount = layout_info.numRowsWithoutHeaders
			num_headers = layout_info.numRowsHeaders
			if direction == Direction.Down and row < num_headers:
				amount += num_headers - row
		else:
			amount = 1

		if direction == Direction.Up:
			row = max(row - amount, 0)
		elif direction == Direction.Down:
			if tableHeight != None:
				row = min(row + amount, tableHeight - 1)
			else:
				row = row + amount
		elif direction == Direction.Left:
			col = max(col - amount, 0)
		elif direction == Direction.Right:
			if tableWidth != None:
				col = min(col + amount, tableWidth - 1)
			else:
				col = col + amount

		log.info(f"new pos {row} {col}")

		new_cell = self.getCell(table_obj, row, col)
		if new_cell == None:
			log.error("improperly sized table")
			return

		log.info(f"setting navigator object")

		api.setNavigatorObject(new_cell)

		log.info(f"set navigator object")

		self.actuallyDisplayTable()

	def moveTableToEdge(self, direction):
		log.info("moveTableToEdge")
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyMoveTableToEdge(direction),
			_immediate=True,
		)

	def actuallyMoveTableToEdge(self, direction):
		table_info = self.getTableInfo()
		if table_info == None:
			log.warn("move table to edge when not in table")
			return
		
		table_obj, cell_obj, row, col, tableWidth, tableHeight = table_info

		if direction == Direction.Up:
			row = 0
		elif direction == Direction.Down:
			if tableHeight != None:
				row = tableHeight - 1
		elif direction == Direction.Left:
			col = 0
		elif direction == Direction.Right:
			if tableWidth != None:
				col = tableWidth - 1
		
		new_cell = self.getCell(table_obj, row, col)
		if new_cell == None:
			log.error("improperly sized table")
			return

		api.setNavigatorObject(new_cell)

		self.actuallyDisplayTable()

	def goToRow(self, row):
		log.info(f"goToRow {row}")
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyGoToRow(row),
			_immediate=True,
		)

	def actuallyGoToRow(self, deviceRow):
		table_info = self.getTableInfo()
		if table_info == None:
			log.warn("move table when not in table")
			return
		
		table_obj, cell_obj, row, col, tableWidth, tableHeight = table_info

		rowsColsNumbers = self.getRowsColsWithHeaders(tableWidth, tableHeight, row, col, table_obj)

		row = rowsColsNumbers[deviceRow][0].row

		new_cell = self.getCell(table_obj, row, col)
		if new_cell == None:
			log.error("improperly sized table")
			return

		api.setNavigatorObject(new_cell)

		self.doToggleTable()

	def navigateToTableCell(self):
		log.info("navigateToTableCell")
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyNavigateToTableCell(),
			_immediate=True,
		)

	def actuallyNavigateToTableCell(self):
		log.info("actuallyNavigateToTableCell")
		table_info = self.tableState
		if table_info == None:
			log.warn("actuallyNavigateToTableCell when not in table")
			return

		cell = self.getCell(table_info.table_obj, table_info.row, table_info.col)
		if cell != None:
			api.setNavigatorObject(cell)

			self.doToggleTable()
		else:
			log.error("unable to get cell for actuallyNavigateToTableCell")

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
				elif liveKeys[0] in rowButtonNumbers:
					rowNum = rowButtonNumbers[liveKeys[0]]
					if self.numRows > 4:
						device = liveKeysWithPosition[0][1]
						position = self.getDevPosition(device)
						if position == DevPosition.BottomLeft or position == DevPosition.BottomRight:
							rowNum += 4
					self.goToRow(rowNum)
			elif len(liveKeys) == 2 and len(composedKeys) == 0:
				if MiniKey.Space in liveKeys:
					if MiniKey.DPadUp in liveKeys:
						self.moveTable(Direction.Up, True)
					elif MiniKey.DPadDown in liveKeys:
						self.moveTable(Direction.Down, True)
					elif MiniKey.Row1 in liveKeys:
						self.showFixedColumnHeader = not self.showFixedColumnHeader
						self.displayTable()
					elif MiniKey.Row2 in liveKeys:
						self.showFixedRowHeader = not self.showFixedRowHeader
						self.displayTable()
					elif MiniKey.Row3 in liveKeys:
						self.showCellPositionsDevice = not self.showCellPositionsDevice
						self.displayTable()
				elif MiniKey.PanLeft in liveKeys or MiniKey.PanRight in liveKeys:
					if MiniKey.DPadUp in liveKeys:
						self.moveTableToEdge(Direction.Up)
					elif MiniKey.DPadDown in liveKeys:
						self.moveTableToEdge(Direction.Down)
					elif MiniKey.DPadLeft in liveKeys:
						self.moveTableToEdge(Direction.Left)
					elif MiniKey.DPadRight in liveKeys:
						self.moveTableToEdge(Direction.Right)
			elif len(liveKeys) == 0 and len(composedKeys) == 1:
				# navigate to cell - center
				if MiniKey.DPadCenter in composedKeys:
					self.navigateToTableCell()
				elif MiniKey.PanLeft in composedKeys:
					self.panHorizontal = max(self.panHorizontal - 1, 0)
					self.displayTable()
				elif MiniKey.PanRight in composedKeys:
					self.panHorizontal = min(self.panHorizontal + 1, self.maxPanHorizontal)
					self.displayTable()

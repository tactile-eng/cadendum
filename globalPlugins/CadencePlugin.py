import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithTable import CadenceDisplayDriverWithTable

# taken keys: NVDA + nrq81[]m7spu5243adflbtc6k
# remaining keys: NVDA + eghijovwxyz

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def script_doToggleImage(self, gesture):
		"""Toggle image mode (Cadence)"""
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriverWithImage):
			display.doToggleImage()			
		else:
			log.error("doToggleImage without CadenceDisplayDriver")
	
	def script_doToggleTable(self, gesture):
		"""Toggle table mode (Cadence)"""
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriverWithTable):
			display.doToggleTable()
		else:
			log.error("doToggleTable without CadenceDisplayDriver")	
	
	# taken shortcuts: 1qrnm7s23pu54adflbtc6k
	__gestures={
		"kb:NVDA+I": "doToggleImage",
		"br(hidBrailleStandard):space+dot2+dot4": "doToggleImage",
		"kb:NVDA+G": "doToggleTable",
		"br(hidBrailleStandard):space+dot2+dot3+dot4+dot5": "doToggleTable",
	}
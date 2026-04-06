import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithTable import CadenceDisplayDriverWithTable

log.info("CadencePlugin Init")

# taken keys: NVDA + inrq81[]m7spu5243adflbtc6k
# remaining keys: NVDA + eghjovwxyz

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

	def script_cycleCadenceLayout(self, gesture):
		"""Cycle Cadence duet layout (wide / tall / other valid forms)"""
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriverWithImage):
			try:
				display.cycleDevPositions()
			except Exception as e:
				log.error(f"cycleCadenceLayout failed: {e}")
		else:
			log.error("cycleCadenceLayout without CadenceDisplayDriver")

	# taken shortcuts: 1qrnm7s23pu54adflbtc6kg
	__gestures={
		"kb:NVDA+I": "doToggleImage",
		"br(hidBrailleStandard):space+dot2+dot4": "doToggleImage",
		"kb:NVDA+shift+I": "cycleCadenceLayout",
		"kb:NVDA+Shift+T": "doToggleTable",
		"br(hidBrailleStandard):space+dot1+dot2+dot4+dot5": "doToggleTable",
	}

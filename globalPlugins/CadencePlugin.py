import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage
from brailleDisplayDrivers.lib.MainCadenceDisplayDriver import MainCadenceDisplayDriver

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
	
	def script_cycleDevPositions(self, gesture):
		display = braille.handler.display
		if isinstance(display, MainCadenceDisplayDriver):
			display.cycleDevPositions()			
		else:
			log.error("cycleDevPositions without CadenceDisplayDriver")

	__gestures={
		"kb:NVDA+I": "doToggleImage",
		"kb:NVDA+Y": "cycleDevPositions",
		"br(hidBrailleStandard):space+dot2+dot4": "doToggleImage",
	}
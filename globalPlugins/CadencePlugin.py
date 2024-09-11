import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.CadenceDisplayDriver import CadenceDisplayDriver

# taken keys: NVDA + nrq81[]m7spu5243adflbtc6k
# remaining keys: NVDA + eghijovwxyz

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def script_doToggleImage(self, gesture):
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriver):
			display.doToggleImage()			
		else:
			log.error("doToggleImage without CadenceDisplayDriver")
	
	def script_cycleDevPositions(self, gesture):
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriver):
			display.cycleDevPositions()			
		else:
			log.error("cycleDevPositions without CadenceDisplayDriver")

	__gestures={
		"kb:NVDA+I": "doToggleImage",
		"kb:NVDA+Y": "cycleDevPositions",
	}
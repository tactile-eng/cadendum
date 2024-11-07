import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage

# taken keys: NVDA + nrq81[]m7spu5243adflbtc6k
# remaining keys: NVDA + eghijovwxyz

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def script_doToggleImage(self, gesture):
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriverWithImage):
			display.doToggleImage()			
		else:
			log.error("doToggleImage without CadenceDisplayDriver")
	
	__gestures={
		"kb:NVDA+I": "doToggleImage",
	}
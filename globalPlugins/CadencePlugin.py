import globalPluginHandler
from logHandler import log
import braille
from brailleDisplayDrivers.CadenceDisplayDriver import CadenceDisplayDriver

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def script_doToggleImage(self, gesture):
		display = braille.handler.display
		if isinstance(display, CadenceDisplayDriver):
			display.doToggleImage()			
		else:
			log.error("doToggleImage without CadenceDisplayDriver")

	__gestures={
		"kb:NVDA+A": "doToggleImage"
	}
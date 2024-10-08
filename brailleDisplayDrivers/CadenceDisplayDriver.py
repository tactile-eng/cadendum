import bdDetect
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithImage import CadenceDisplayDriverWithImage, TestCadenceDisplayDriver
from brailleDisplayDrivers.lib.MainCadenceDisplayDriver import MainCadenceDisplayDriver

# is driver enabled?
def isSupportEnabled() -> bool:
	return bdDetect.driverIsEnabledForAutoDetection(CadenceDisplayDriverWithImage.name)

# export CadenceDisplayDriver
BrailleDisplayDriver = CadenceDisplayDriverWithImage
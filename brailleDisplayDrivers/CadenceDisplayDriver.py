import bdDetect
from brailleDisplayDrivers.lib.CadenceDisplayDriverWithTable import CadenceDisplayDriverWithTable

# is driver enabled?
def isSupportEnabled() -> bool:
	return bdDetect.driverIsEnabledForAutoDetection(CadenceDisplayDriverWithTable.name)

# export CadenceDisplayDriver
BrailleDisplayDriver = CadenceDisplayDriverWithTable
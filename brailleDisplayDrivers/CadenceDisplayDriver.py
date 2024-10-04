import ctypes.wintypes
from logHandler import log
from brailleDisplayDrivers.hidBrailleStandard import HidBrailleDriver, InputGesture
import bdDetect
from typing import List
import api
from NVDAObjects import NVDAObject
from screenBitmap import ScreenBitmap
import math
import threading
import ctypes
import winGDI
from enum import Enum
import math
import braille
import inputCore
import itertools
import queueHandler
from bdDetect import HID_USAGE_PAGE_BRAILLE
from hwIo import hid
import hidpi
import hwPortUtils
import typing

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
hidDll = ctypes.windll.hid

def _getHidInfo(hwId, path):
	info = {
		"hardwareID": hwId,
		"devicePath": path,
	}
	hwId = hwId.split("\\", 1)[1]
	if hwId.startswith("VID"):
		info["provider"] = "usb"
		info["usbID"] = hwId[:17]  # VID_xxxx&PID_xxxx
	elif hwId.startswith("{00001124-0000-1000-8000-00805f9b34fb}"):
		info["provider"] = "bluetooth"
	elif hwId.startswith("{00001812-0000-1000-8000-00805f9b34fb}"):
		# Low energy bluetooth: #15470
		info["provider"] = "bluetooth"
	else:
		# Unknown provider.
		info["provider"] = None
		return info
	# Fetch additional info about the HID device.
	from serial.win32 import FILE_FLAG_OVERLAPPED, INVALID_HANDLE_VALUE, CreateFile

	handle = CreateFile(
		path,
		0,
		hwPortUtils.winKernel.FILE_SHARE_READ | hwPortUtils.winKernel.FILE_SHARE_WRITE,
		None,
		hwPortUtils.winKernel.OPEN_EXISTING,
		FILE_FLAG_OVERLAPPED,
		None,
	)
	if handle == INVALID_HANDLE_VALUE:
		if True:
			log.debugWarning(f"Opening device {path} to get additional info failed: {ctypes.WinError()}")
		return info
	try:
		attribs = hwPortUtils.HIDD_ATTRIBUTES()
		if ctypes.windll.hid.HidD_GetAttributes(handle, ctypes.byref(attribs)):
			info["vendorID"] = attribs.VendorID
			info["productID"] = attribs.ProductID
			info["versionNumber"] = attribs.VersionNumber
		else:
			if True:
				log.debugWarning("HidD_GetAttributes failed")
		buf = ctypes.create_unicode_buffer(128)
		nrOfBytes = ctypes.sizeof(buf)
		if ctypes.windll.hid.HidD_GetManufacturerString(handle, buf, nrOfBytes):
			info["manufacturer"] = buf.value
		if ctypes.windll.hid.HidD_GetProductString(handle, buf, nrOfBytes):
			info["product"] = buf.value
		pd = ctypes.c_void_p()
		if ctypes.windll.hid.HidD_GetPreparsedData(handle, ctypes.byref(pd)):
			try:
				caps = hidpi.HIDP_CAPS()
				ctypes.windll.hid.HidP_GetCaps(pd, ctypes.byref(caps))
				info["HIDUsagePage"] = caps.UsagePage
			finally:
				ctypes.windll.hid.HidD_FreePreparsedData(pd)
	finally:
		hwPortUtils.winKernel.closeHandle(handle)
	return info

PKEYS = [\
["DEVPKEY_DeviceContainer_ModelNumber",              "{656A3BB3-ECC0-43FD-8477-4AE0404A96CD}", 8195],
["DEVPKEY_NAME",                          "{b725f130-47ef-101a-a5f1-02608c9eebac}", 10],
["DEVPKEY_Device_DeviceDesc",             "{a45c254e-df1c-4efd-8020-67d146a850e0}", 2],
["DEVPKEY_Device_HardwareIds",            "{a45c254e-df1c-4efd-8020-67d146a850e0}", 3],
["DEVPKEY_Device_CompatibleIds",          "{a45c254e-df1c-4efd-8020-67d146a850e0}", 4],
["DEVPKEY_Device_Service",                "{a45c254e-df1c-4efd-8020-67d146a850e0}", 6],
["DEVPKEY_Device_Class",                  "{a45c254e-df1c-4efd-8020-67d146a850e0}", 9],
["DEVPKEY_Device_ClassGuid",              "{a45c254e-df1c-4efd-8020-67d146a850e0}", 10],
["DEVPKEY_Device_Driver",                 "{a45c254e-df1c-4efd-8020-67d146a850e0}", 11],
["DEVPKEY_Device_ConfigFlags",            "{a45c254e-df1c-4efd-8020-67d146a850e0}", 12],
["DEVPKEY_Device_Manufacturer",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 13],
["DEVPKEY_Device_FriendlyName",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 14],
["DEVPKEY_Device_LocationInfo",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 15],
["DEVPKEY_Device_PDOName",                "{a45c254e-df1c-4efd-8020-67d146a850e0}", 16],
["DEVPKEY_Device_Capabilities",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 17],
["DEVPKEY_Device_UINumber",               "{a45c254e-df1c-4efd-8020-67d146a850e0}", 18],
["DEVPKEY_Device_UpperFilters",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 19],
["DEVPKEY_Device_LowerFilters",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 20],
["DEVPKEY_Device_BusTypeGuid",            "{a45c254e-df1c-4efd-8020-67d146a850e0}", 21],
["DEVPKEY_Device_LegacyBusType",          "{a45c254e-df1c-4efd-8020-67d146a850e0}", 22],
["DEVPKEY_Device_BusNumber",              "{a45c254e-df1c-4efd-8020-67d146a850e0}", 23],
["DEVPKEY_Device_EnumeratorName",         "{a45c254e-df1c-4efd-8020-67d146a850e0}", 24],
["DEVPKEY_Device_Security",               "{a45c254e-df1c-4efd-8020-67d146a850e0}", 25],
["DEVPKEY_Device_SecuritySDS",            "{a45c254e-df1c-4efd-8020-67d146a850e0}", 26],
["DEVPKEY_Device_DevType",                "{a45c254e-df1c-4efd-8020-67d146a850e0}", 27],
["DEVPKEY_Device_Exclusive",              "{a45c254e-df1c-4efd-8020-67d146a850e0}", 28],
["DEVPKEY_Device_Characteristics",        "{a45c254e-df1c-4efd-8020-67d146a850e0}", 29],
["DEVPKEY_Device_Address",                "{a45c254e-df1c-4efd-8020-67d146a850e0}", 30],
["DEVPKEY_Device_UINumberDescFormat",     "{a45c254e-df1c-4efd-8020-67d146a850e0}", 31],
["DEVPKEY_Device_PowerData",              "{a45c254e-df1c-4efd-8020-67d146a850e0}", 32],
["DEVPKEY_Device_RemovalPolicy",          "{a45c254e-df1c-4efd-8020-67d146a850e0}", 33],
["DEVPKEY_Device_RemovalPolicyDefault",   "{a45c254e-df1c-4efd-8020-67d146a850e0}", 34],
["DEVPKEY_Device_RemovalPolicyOverride",  "{a45c254e-df1c-4efd-8020-67d146a850e0}", 35],
["DEVPKEY_Device_InstallState",           "{a45c254e-df1c-4efd-8020-67d146a850e0}", 36],
["DEVPKEY_Device_LocationPaths",          "{a45c254e-df1c-4efd-8020-67d146a850e0}", 37],
["DEVPKEY_Device_BaseContainerId",        "{a45c254e-df1c-4efd-8020-67d146a850e0}", 38],
["DEVPKEY_Device_InstanceId",             "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 256],
["DEVPKEY_Device_DevNodeStatus",          "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 2],
["DEVPKEY_Device_ProblemCode",            "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 3],
["DEVPKEY_Device_EjectionRelations",      "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 4],
["DEVPKEY_Device_RemovalRelations",       "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 5],
["DEVPKEY_Device_PowerRelations",         "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 6],
["DEVPKEY_Device_BusRelations",           "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 7],
["DEVPKEY_Device_Parent",                 "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 8],
["DEVPKEY_Device_Children",               "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 9],
["DEVPKEY_Device_Siblings",               "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 10],
["DEVPKEY_Device_TransportRelations",     "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 11],
["DEVPKEY_Device_ProblemStatus",          "{4340a6c5-93fa-4706-972c-7b648008a5a7}", 12],
["DEVPKEY_Device_Reported",                   "{80497100-8c73-48b9-aad9-ce387e19c56e}", 2],
["DEVPKEY_Device_Legacy",                     "{80497100-8c73-48b9-aad9-ce387e19c56e}", 3],
["DEVPKEY_Device_ContainerId",             "{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c}", 2],
["DEVPKEY_Device_InLocalMachineContainer", "{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c}", 4],
["DEVPKEY_Device_Model",                  "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 39],
["DEVPKEY_Device_ModelId",                     "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 2],
["DEVPKEY_Device_FriendlyNameAttributes",      "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 3],
["DEVPKEY_Device_ManufacturerAttributes",      "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 4],
["DEVPKEY_Device_PresenceNotForDevice",        "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 5],
["DEVPKEY_Device_SignalStrength",              "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 6],
["DEVPKEY_Device_IsAssociateableByUserAction", "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 7],
["DEVPKEY_Device_ShowInUninstallUI",           "{80d81ea6-7473-4b0c-8216-efc11a2c4c8b}", 8],
["DEVPKEY_Device_Numa_Proximity_Domain",    "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 1],
["DEVPKEY_Device_DHP_Rebalance_Policy",     "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 2],
["DEVPKEY_Device_Numa_Node",                "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 3],
["DEVPKEY_Device_BusReportedDeviceDesc",    "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 4],
["DEVPKEY_Device_IsPresent",                "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 5],
["DEVPKEY_Device_HasProblem",               "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 6],
["DEVPKEY_Device_ConfigurationId",          "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 7],
["DEVPKEY_Device_ReportedDeviceIdsHash",    "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 8],
["DEVPKEY_Device_PhysicalDeviceLocation",   "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 9],
["DEVPKEY_Device_BiosDeviceName",           "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 10],
["DEVPKEY_Device_DriverProblemDesc",        "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 11],
["DEVPKEY_Device_DebuggerSafe",             "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 12],
["DEVPKEY_Device_PostInstallInProgress",    "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 13],
["DEVPKEY_Device_Stack",                    "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 14],
["DEVPKEY_Device_ExtendedConfigurationIds", "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 15],
["DEVPKEY_Device_IsRebootRequired",         "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 16],
["DEVPKEY_Device_FirmwareDate",             "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 17],
["DEVPKEY_Device_FirmwareVersion",          "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 18],
["DEVPKEY_Device_FirmwareRevision",         "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 19],
["DEVPKEY_Device_DependencyProviders",      "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 20],
["DEVPKEY_Device_DependencyDependents",     "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 21],
["DEVPKEY_Device_SoftRestartSupported",     "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 22],
["DEVPKEY_Device_ExtendedAddress",          "{540b947e-8b40-45bc-a8a2-6a0b894cbda2}", 23],
["DEVPKEY_Device_SessionId",               "{83da6326-97a6-4088-9453-a1923f573b29}", 6],
["DEVPKEY_Device_InstallDate",             "{83da6326-97a6-4088-9453-a1923f573b29}", 100],
["DEVPKEY_Device_FirstInstallDate",        "{83da6326-97a6-4088-9453-a1923f573b29}", 101],
["DEVPKEY_Device_LastArrivalDate",         "{83da6326-97a6-4088-9453-a1923f573b29}", 102],
["DEVPKEY_Device_LastRemovalDate",         "{83da6326-97a6-4088-9453-a1923f573b29}", 103],
["DEVPKEY_Device_DriverDate",               "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 2],
["DEVPKEY_Device_DriverVersion),",            "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 3],
["DEVPKEY_Device_DriverDesc),",               "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 4],
["DEVPKEY_Device_DriverInfPath),",            "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 5],
["DEVPKEY_Device_DriverInfSection),",         "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 6],
["DEVPKEY_Device_DriverInfSectionExt),",      "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 7],
["DEVPKEY_Device_MatchingDeviceId),",         "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 8],
["DEVPKEY_Device_DriverProvider),",           "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 9],
["DEVPKEY_Device_DriverPropPageProvider),",   "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 10],
["DEVPKEY_Device_DriverCoInstallers",       "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 11],
["DEVPKEY_Device_ResourcePickerTags",       "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 12],
["DEVPKEY_Device_ResourcePickerExceptions", "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 13],
["DEVPKEY_Device_DriverRank",               "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 14],
["DEVPKEY_Device_DriverLogoLevel",          "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 15],
["DEVPKEY_Device_NoConnectSound",              "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 17],
["DEVPKEY_Device_GenericDriverInstalled",      "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 18],
["DEVPKEY_Device_AdditionalSoftwareRequested", "{a8b865dd-2e3d-4094-ad97-e593a7c,5,6,}", 19],
["DEVPKEY_Device_SafeRemovalRequired",         "{afd97640-86a3-4210-b67c-289c41aabe55}", 2],
["DEVPKEY_Device_SafeRemovalRequiredOverride", "{afd97640-86a3-4210-b67c-289c41aabe55}", 3],
["DEVPKEY_DrvPkg_Model",                  "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 2],
["DEVPKEY_DrvPkg_VendorWebSite",          "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 3],
["DEVPKEY_DrvPkg_DetailedDescription",    "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 4],
["DEVPKEY_DrvPkg_DocumentationLink",      "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 5],
["DEVPKEY_DrvPkg_Icon",                   "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 6],
["DEVPKEY_DrvPkg_BrandingIcon",           "{cf73bb51-3abf-44a2-85e0-9a3dc7a12132}", 7],
["DEVPKEY_DeviceClass_UpperFilters",      "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 19],
["DEVPKEY_DeviceClass_LowerFilters",      "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 20],
["DEVPKEY_DeviceClass_Security",          "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 25],
["DEVPKEY_DeviceClass_SecuritySDS",       "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 26],
["DEVPKEY_DeviceClass_DevType",           "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 27],
["DEVPKEY_DeviceClass_Exclusive",         "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 28],
["DEVPKEY_DeviceClass_Characteristics",   "{4321918b-f69e-470d-a5de-4d88c75ad24b}", 29],
["DEVPKEY_DeviceClass_Name",              "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 2],
["DEVPKEY_DeviceClass_ClassName),",         "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 3],
["DEVPKEY_DeviceClass_Icon),",              "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 4],
["DEVPKEY_DeviceClass_ClassInstaller),",    "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 5],
["DEVPKEY_DeviceClass_PropPageProvider),",  "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 6],
["DEVPKEY_DeviceClass_NoInstallClass),",    "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 7],
["DEVPKEY_DeviceClass_NoDisplayClass),",    "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 8],
["DEVPKEY_DeviceClass_SilentInstall),",     "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 9],
["DEVPKEY_DeviceClass_NoUseClass),",        "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 10],
["DEVPKEY_DeviceClass_DefaultService",    "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 11],
["DEVPKEY_DeviceClass_IconPath",          "{259abffc-50a7-47ce-af8,-8,9,7,7,3,6,}", 12],
["DEVPKEY_DeviceClass_DHPRebalanceOptOut", "{d14d3ef3-66cf-4ba2-9d38-0ddb37ab4701}", 2],
["DEVPKEY_DeviceClass_ClassCoInstallers",  "{713d1703-a2e2-49f5-9214-56472ef3da5c}", 2],
["DEVPKEY_DeviceInterface_FriendlyName",       "{026e516e-b814-414b-83cd-856d6fef4822}", 2],
["DEVPKEY_DeviceInterface_Enabled",            "{026e516e-b814-414b-83cd-856d6fef4822}", 3],
["DEVPKEY_DeviceInterface_ClassGuid",          "{026e516e-b814-414b-83cd-856d6fef4822}", 4],
["DEVPKEY_DeviceInterface_ReferenceString",    "{026e516e-b814-414b-83cd-856d6fef4822}", 5],
["DEVPKEY_DeviceInterface_Restricted",         "{026e516e-b814-414b-83cd-856d6fef4822}", 6],
["DEVPKEY_DeviceInterface_UnrestrictedAppCapabilities", "{026e516e-b814-414b-83cd-856d6fef4822}", 8],
["DEVPKEY_DeviceInterface_SchematicName",      "{026e516e-b814-414b-83cd-856d6fef4822}", 9],
["DEVPKEY_DeviceInterfaceClass_DefaultInterface",    "{14c83a99-0b3f-44b7-be4c-a178d3990564}", 2],
["DEVPKEY_DeviceInterfaceClass_Name",                "{14c83a99-0b3f-44b7-be4c-a178d3990564}", 3],
["DEVPKEY_DeviceContainer_Address",                  "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 51],
["DEVPKEY_DeviceContainer_DiscoveryMethod",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 52],
["DEVPKEY_DeviceContainer_IsEncrypted",              "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 53],
["DEVPKEY_DeviceContainer_IsAuthenticated",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 54],
["DEVPKEY_DeviceContainer_IsConnected",              "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 55],
["DEVPKEY_DeviceContainer_IsPaired",                 "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 56],
["DEVPKEY_DeviceContainer_Icon",                     "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 57],
["DEVPKEY_DeviceContainer_Version",                  "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 65],
["DEVPKEY_DeviceContainer_Last_Seen",                "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 66],
["DEVPKEY_DeviceContainer_Last_Connected",           "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 67],
["DEVPKEY_DeviceContainer_IsShowInDisconnectedState", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 68],
["DEVPKEY_DeviceContainer_IsLocalMachine",           "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 70],
["DEVPKEY_DeviceContainer_MetadataPath",             "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 71],
["DEVPKEY_DeviceContainer_IsMetadataSearchInProgress", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 72],
["DEVPKEY_DeviceContainer_MetadataChecksum",         "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 73],
["DEVPKEY_DeviceContainer_IsNotInterestingForDisplay", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 74],
["DEVPKEY_DeviceContainer_LaunchDeviceStageOnDeviceConnect", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 76],
["DEVPKEY_DeviceContainer_LaunchDeviceStageFromExplorer", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 77],
["DEVPKEY_DeviceContainer_BaselineExperienceId",     "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 78],
["DEVPKEY_DeviceContainer_IsDeviceUniquelyIdentifiable", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 79],
["DEVPKEY_DeviceContainer_AssociationArray",         "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 80],
["DEVPKEY_DeviceContainer_DeviceDescription1",       "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 81],
["DEVPKEY_DeviceContainer_DeviceDescription2",       "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 82],
["DEVPKEY_DeviceContainer_HasProblem",               "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 83],
["DEVPKEY_DeviceContainer_IsSharedDevice",           "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 84],
["DEVPKEY_DeviceContainer_IsNetworkDevice",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 85],
["DEVPKEY_DeviceContainer_IsDefaultDevice",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 86],
["DEVPKEY_DeviceContainer_MetadataCabinet",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 87],
["DEVPKEY_DeviceContainer_RequiresPairingElevation", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 88],
["DEVPKEY_DeviceContainer_ExperienceId",             "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 89],
["DEVPKEY_DeviceContainer_Category",                 "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 90],
["DEVPKEY_DeviceContainer_Category_Desc_Singular",   "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 91],
["DEVPKEY_DeviceContainer_Category_Desc_Plural",     "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 92],
["DEVPKEY_DeviceContainer_Category_Icon",            "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 93],
["DEVPKEY_DeviceContainer_CategoryGroup_Desc",       "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 94],
["DEVPKEY_DeviceContainer_CategoryGroup_Icon",       "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 95],
["DEVPKEY_DeviceContainer_PrimaryCategory",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 97],
["DEVPKEY_DeviceContainer_UnpairUninstall",          "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 98],
["DEVPKEY_DeviceContainer_RequiresUninstallElevation", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 99],
["DEVPKEY_DeviceContainer_DeviceFunctionSubRank",    "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 100],
["DEVPKEY_DeviceContainer_AlwaysShowDeviceAsConnected", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 101],
["DEVPKEY_DeviceContainer_ConfigFlags",              "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 105],
["DEVPKEY_DeviceContainer_PrivilegedPackageFamilyNames", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 106],
["DEVPKEY_DeviceContainer_CustomPrivilegedPackageFamilyNames", "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 107],
["DEVPKEY_DeviceContainer_IsRebootRequired",         "{78c34fc8-104a-4aca-9ea4-524d52996e57}", 108],
["DEVPKEY_DeviceContainer_FriendlyName",             "{656A3BB3-ECC0-43FD-8477-4AE0404A96CD}", 12288],
["DEVPKEY_DeviceContainer_Manufacturer",             "{656A3BB3-ECC0-43FD-8477-4AE0404A96CD}", 8192],
["DEVPKEY_DeviceContainer_ModelName",                "{656A3BB3-ECC0-43FD-8477-4AE0404A96CD}", 8194],
["DEVPKEY_DeviceContainer_ModelNumber",              "{656A3BB3-ECC0-43FD-8477-4AE0404A96CD}", 8195],
["DEVPKEY_DeviceContainer_InstallInProgress",        "{83da6326-97a6-4088-9453-a1923f573b29}", 9],
["DEVPKEY_DevQuery_ObjectType",                  "{13673f42-a3d6-49f6-b4da-ae46e0c5237c}", 2],
]

CM_Get_Parent = ctypes.windll.cfgmgr32.CM_Get_Parent
CM_Get_Parent.argtypes = [ctypes.POINTER(hwPortUtils.DWORD), hwPortUtils.DWORD, ctypes.c_ulong]
CM_Get_Parent.restype = hwPortUtils.DWORD

SetupDiCreateDeviceInfoList = ctypes.windll.setupapi.SetupDiCreateDeviceInfoList
SetupDiCreateDeviceInfoList.argtypes = [
	ctypes.POINTER(hwPortUtils.GUID),
	hwPortUtils.HWND,
]
SetupDiCreateDeviceInfoList.restype = hwPortUtils.HDEVINFO

SetupDiOpenDeviceInfoW = ctypes.windll.setupapi.SetupDiOpenDeviceInfoW 
SetupDiOpenDeviceInfoW.argtypes = [hwPortUtils.HDEVINFO,
	ctypes.wintypes.LPCWSTR,
	hwPortUtils.HWND,
	hwPortUtils.DWORD,
	ctypes.POINTER(hwPortUtils.SP_DEVINFO_DATA)]
SetupDiOpenDeviceInfoW.restype = ctypes.c_bool
GetLastError = ctypes.windll.kernel32.GetLastError
GetLastError.restype = hwPortUtils.DWORD

def get_parent(child_dev_inst: hwPortUtils.SP_DEVINFO_DATA, g_hdi: hwPortUtils.HDEVINFO) -> hwPortUtils.SP_DEVINFO_DATA | None:
	buf = ctypes.create_unicode_buffer(1024)
	log.info(f"HIDTest buf {type(buf)} {ctypes.sizeof(buf)}")
	
	parent_dev_inst = hwPortUtils.DWORD()
	ret = CM_Get_Parent(ctypes.byref(parent_dev_inst), child_dev_inst.DevInst, ctypes.c_ulong(0))
	if ret != 0:
		raise ctypes.WinError(ctypes.get_last_error())

	log.info(f"HIDTest parent_dev_inst {parent_dev_inst}")
	ret = hwPortUtils.CM_Get_Device_ID(parent_dev_inst, buf, ctypes.sizeof(buf) - 1, 0)
	if ret != 0:
		raise ctypes.WinError(ctypes.get_last_error())
	
	log.info(f"HIDTest dev inst buf {buf.value}")
	# g_hdi = SetupDiCreateDeviceInfoList(None, None)
	
	# log.info(f"HIDTest g_hdi {g_hdi}")
	parent_devinfo_data = hwPortUtils.SP_DEVINFO_DATA()
	parent_devinfo_data.cbSize = ctypes.sizeof(hwPortUtils.SP_DEVINFO_DATA)
	ret = SetupDiOpenDeviceInfoW(g_hdi, buf.value, None, 0, ctypes.byref(parent_devinfo_data))
	if not ret:
		raise ctypes.WinError(ctypes.get_last_error())
	
	log.info(f"HIDTest SetupDiOpenDeviceInfoW {parent_devinfo_data}")
	return parent_devinfo_data

def listHidDevices(onlyAvailable: bool = True) -> typing.Iterator[dict]:
	"""List HID devices on the system.
	@param onlyAvailable: Only return devices that are currently available.
	@return: Generates dicts including keys such as hardwareID,
		usbID (in the form "VID_xxxx&PID_xxxx")
		and devicePath.
	"""
	_hidGuid = hwPortUtils._hidGuid
	if not _hidGuid:
		log.error("no hidGuid")
		# _hidGuid = hwPortUtils.GUID()
		# ctypes.windll.hid.HidD_GetHidGuid(ctypes.byref(_hidGuid))

	for g_hdi, idd, devinfo, buf in hwPortUtils._listDevices(_hidGuid, onlyAvailable):
		# hardware ID
		if not hwPortUtils.SetupDiGetDeviceRegistryProperty(
			g_hdi,
			ctypes.byref(devinfo),
			hwPortUtils.SPDRP_HARDWAREID,
			None,
			ctypes.byref(buf),
			ctypes.sizeof(buf) - 1,
			None,
		):
			# Ignore ERROR_INSUFFICIENT_BUFFER
			if ctypes.GetLastError() != hwPortUtils.ERROR_INSUFFICIENT_BUFFER:
				raise ctypes.WinError()
		else:
			hwId = buf.value
			info = _getHidInfo(hwId, idd.DevicePath)

			if "VID&02361f_PID&52ae" in info["hardwareID"]:
				log.info(f"HIDTest ALL {g_hdi} {idd} {devinfo} {buf}")
				log.info(f"HIDTest devinfo {devinfo}")
				try:
					parent = get_parent(devinfo, g_hdi)
					parent2 = get_parent(parent, g_hdi)

					propRegDataType = hwPortUtils.DWORD()
					log.info(f"HIDTest buf size {ctypes.sizeof(buf)}")
					for pkeyname, pkeyid, pkeynum in PKEYS:
						# log.info(f"HIDTest {pkeyname} {pkeyid} {pkeynum}")
						pkey = hwPortUtils.DEVPROPKEY(hwPortUtils.GUID(pkeyid), pkeynum)
						if not hwPortUtils.SetupDiGetDeviceProperty(
							g_hdi,
							ctypes.byref(parent2),
							ctypes.byref(pkey),
							ctypes.byref(propRegDataType),
							ctypes.byref(buf),
							ctypes.sizeof(buf) - 1,
							None,
							0,
						):
							# log.info(
							# 	f"HIDTest {pkeyname}",
							# )
							pass
						else:
							log.info(
								f"HIDTest {pkeyname}: {buf.value}",
							)
					# 	parent_device_id = ctypes.create_unicode_buffer(MAX_DEVICE_ID_LEN)
					# 	if hwPortUtils.CM_Get_Device_ID(parent_dev_inst.value, parent_device_id, MAX_DEVICE_ID_LEN, 0) == 0:
					# 		parent_dev_info_data = hwPortUtils.SP_DEVINFO_DATA()
					# 		parent_dev_info_data.cbSize = ctypes.sizeof(hwPortUtils.SP_DEVINFO_DATA)
					# 		if ctypes.windll.setupapi.SetupDiOpenDeviceInfo(devinfo, parent_device_id, None, 0, ctypes.byref(parent_dev_info_data)):
					# 			log.info(f"HIDTest PARENT STUFF {parent_dev_info_data}")
				except Exception as e:
					log.info(f"HIDTest error: {e}")




						# propRegDataType = hwPortUtils.DWORD()
						# DEVPKEY_Device_Parent = hwPortUtils.DEVPROPKEY(hwPortUtils.GUID("{4340a6c5-93fa-4706-972c-7b648008a5a7}"), 8)
						# if not hwPortUtils.SetupDiGetDeviceProperty(
						# 	g_hdi,
						# 	ctypes.byref(devinfo),
						# 	ctypes.byref(DEVPKEY_Device_Parent),
						# 	ctypes.byref(propRegDataType),
						# 	ctypes.byref(buf),
						# 	ctypes.sizeof(buf) - 1,
						# 	None,
						# 	0,
						# ):
						# 	log.info("HIDTest unable to find parent")
						# else:
						# 	log.info(
						# 		f"HIDTest parent {buf.value}",
						# 	)


			if True:
				log.debug(f"{info!r}")
			yield info

	if True:
		log.debug("Finished listing HID devices")

# device buttons
class MiniKey(Enum):
	DPadUp = 25
	DPadDown = 26
	DPadRight = 28
	DPadLeft = 27
	DPadCenter = 24
	PanRight = 20
	PanLeft = 18
	Row1 = 32
	Row2 = 33
	Row3 = 34
	Row4 = 35
	Dot1 = 8
	Dot2 = 9
	Dot3 = 10
	Dot4 = 11
	Dot5 = 12
	Dot6 = 13
	Dot7 = 14
	Dot8 = 15
	Space = 16

# key IDs for right-side device when using two-device mode
rightKeys = {
	41: MiniKey.DPadUp,
	42: MiniKey.DPadDown,
	44: MiniKey.DPadRight,
	43: MiniKey.DPadLeft,
	40: MiniKey.DPadCenter,
	19: MiniKey.PanRight,
	21: MiniKey.PanLeft,
	48: MiniKey.Row1,
	49: MiniKey.Row2,
	50: MiniKey.Row3,
	51: MiniKey.Row4,
	17: MiniKey.Space,
}

# map keys for when device is upside-down
flippedKeys = {
	MiniKey.DPadUp: MiniKey.DPadDown,
	MiniKey.DPadDown: MiniKey.DPadUp,
	MiniKey.DPadLeft: MiniKey.DPadRight,
	MiniKey.DPadRight: MiniKey.DPadLeft,
	MiniKey.PanLeft: MiniKey.PanRight,
	MiniKey.PanRight: MiniKey.PanLeft,
	MiniKey.Row1: MiniKey.Row4,
	MiniKey.Row2: MiniKey.Row3,
	MiniKey.Row3: MiniKey.Row2,
	MiniKey.Row4: MiniKey.Row1,
	MiniKey.Dot1: MiniKey.Dot4,
	MiniKey.Dot2: MiniKey.Dot5,
	MiniKey.Dot3: MiniKey.Dot6,
	MiniKey.Dot4: MiniKey.Dot1,
	MiniKey.Dot5: MiniKey.Dot2,
	MiniKey.Dot6: MiniKey.Dot3,
	MiniKey.Dot7: MiniKey.Dot8,
	MiniKey.Dot8: MiniKey.Dot7,
}

# whether the device is a left type or right type
class DevSide(Enum):
	Left = 0
	Right = 1

# a position for where the device is
class DevPosition(Enum):
	BottomLeft = 0
	BottomRight = 1
	TopLeft = 2
	TopRight = 3

# a cardinal direction
class Direction(Enum):
	Up = 0
	Down = 1
	Left = 2
	Right = 3

# view & navigation constants
defaultPanRate = 2
panRateRate = 1.5
defaultZoomRate = 1.25
zoomRateRate = 1.5
bwThresholdOutOf = 100
defaultBwThresholdRate = 7

def getScreenResolution():
	screen = user32.GetDC(0)
	width = gdi32.GetDeviceCaps(screen, 8)  # HORZRES
	height = gdi32.GetDeviceCaps(screen, 10)  # VERTRES
	log.info(f"########## SCREEN RES {width}x{height}")
	user32.ReleaseDC(0, screen)
	return (width, height)

# is driver enabled?
def isSupportEnabled() -> bool:
	return bdDetect.driverIsEnabledForAutoDetection(CadenceDisplayDriver.name)

# is a bluetooth device a Cadence device?
def isDeviceCadence(m):
	log.info(f"possible cadence device {m} {'Dev_VID&02361f' in m.id}")
	return "Dev_VID&02361f_PID&52ae" in m.id

# braille dot order
brailleOffsets = [[0,0], [0,1], [0,2], [1,0], [1,1], [1,2], [0,3], [1,3]]

# for debugging purposes
def debugImage(image: list[list[bool]]) -> str:
	return "\n".join(["".join(["#" if pix else " " for pix in row]) for row in image])

# boolean 2d array to list of braille codes
def imageToCells(image: list[list[bool]]) -> list[int]:
	height = len(image)
	width = len(image[0])
	numCols = int(width / 2)
	numRows = int(height / 4)
	out: list[int] = []
	for cellY in range(numRows):
		for cellX in range(numCols):
			cellOut = 0
			for (pixI, offset) in enumerate(brailleOffsets):
				sourceX = cellX * 2 + offset[0]
				sourceY = cellY * 4 + offset[1]
				valBool = image[sourceY][sourceX]
				if valBool:
					cellOut += 2**pixI
			out.append(cellOut)
	return out

# list of braille codes to boolean 2d array
def cellsToImage(cells: list[int], numRows: int) -> list[list[bool]]:
	numCols = int(len(cells) / numRows)
	height = numRows * 4
	width = numCols * 2
	image: list[list[bool]] = [[False for x in range(width)] for y in range(height)]
	for cellI, cell in enumerate(cells):
		cellX = cellI % numCols
		cellY = math.floor(cellI / numCols)
		for (pixI, offset) in enumerate(brailleOffsets):
			x = cellX * 2 + offset[0]
			y = cellY * 4 + offset[1]
			val = ((cell >> pixI) & 1) == 1
			image[y][x] = val
	return image

# winGDI bitmap to boolean 2d array
def bitmapToImage(bitmap, width: int, height: int, bwThreshold: float, bwReversed: bool, colorMode: int) -> list[list[bool]]:
	imageOut: list[list[bool]] = []
	for y in range(height):
		row: list[bool] = []
		for x in range(width):
			rgb = bitmap[y][x]
			r = rgb.rgbRed
			g = rgb.rgbBlue
			b = rgb.rgbGreen
			if colorMode == 0:
				val = 0.299*r + 0.587*g + 0.114*b
			elif colorMode == 1:
				val = r
			elif colorMode == 2:
				val = g
			elif colorMode == 3:
				val = b
			threshold = bwThreshold / bwThresholdOutOf * 255
			if bwReversed:
				valBool = val < threshold
			else:
				valBool = val > threshold
			row.append(valBool)
		imageOut.append(row)
	return imageOut

# flip boolean 2d array 180 degrees
def flipImage(image: list[list[bool]]) -> list[list[bool]]:
	height = len(image)
	width = len(image[0])
	return [[image[height - y - 1][width - x - 1] for x in range(width)] for y in range(height)]

# join two boolean 2d arrays horizontally
def joinImagesHorizontally(imageLeft: list[list[bool]], imageRight: list[list[bool]]):
	return [rowLeft + rowRight for (rowLeft, rowRight) in zip(imageLeft, imageRight)]

# a timer that repeatedly runs a function every n seconds
# https://stackoverflow.com/questions/12435211/threading-timer-repeat-function-every-n-seconds
class RunInterval(threading.Thread):
	def __init__(self, callback, interval = 1):
		super().__init__()
		self.callback = callback
		self.interval = interval
		self.daemon = True
		self.stopFlag = threading.Event()

	def cancel(self):
		self.stopFlag.set()

	def run(self):
		while not self.stopFlag.wait(self.interval):
			try:
				self.callback()
			except Exception as e:
				log.error(f"{e}")
				pass

# See SignalContainer in CadenceOS
class SignalContainer():
	def __init__(self, value: float):
		self.value = value
		self.default = value

	def get(self) -> float:
		return self.value

	def set(self, val: float):
		self.value = val

	def reset(self):
		self.value = self.default

# See Slider in CadenceOS
class Slider():
	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool):
		self.signal = SignalContainer(default)
		self.rate = SignalContainer(rateDefault)
		self.min = SignalContainer(min)
		self.max = SignalContainer(max)
		self.rateRate = rateRate
		self.sliderExp = sliderExp
		self.sliderSCurve = sliderSCurve
		self.quantize = None
		self.strictMinMax = strictMinMax

	def get(self) -> float:
		return self.signal.get()

	def set(self, val: float):
		self.signal.set(val)

	def getRate(self) -> float:
		return self.rate.get()

	def setRate(self, val: float):
		self.rate.set(val)

	def expOrLog(self, value: float, expOrLog: bool):
		if (self.sliderExp):
			if (expOrLog):
				return math.pow(2, value) - 1
			else:
				return math.log(value + 1) / math.log(2)
		elif (self.sliderSCurve):
			if (value > 1 or value < 0): return value
			curvyness = 1.75
			if (expOrLog):
				return 1 / (1 + math.pow(value / (1 - value), -curvyness))
			else:
				if (value == 0.5): return 0.5
				return 1 / (math.pow(1 / value - 1, 1 / curvyness) + 1)
		else:
			return value

	def getNormalised(self):
		return (self.get() - self.min.get()) / (self.max.get() - self.min.get())


	def setNormalized(self, n: float):
		newValue = n * (self.max.get() - self.min.get()) + self.min.get()
		if (self.quantize != None):
			newValue = self.roundValue(newValue)
		if (self.strictMinMax):
			if (newValue < self.min.get()): newValue = self.min.get()
			if (newValue > self.max.get()): newValue = self.max.get()
		self.set(newValue)

	def roundValue(self, n: float) -> float:
		if (self.quantize == None): return n

		min = self.min.get()
		quantize = self.quantize.get()
		rounded = math.round((n - min) / quantize) * quantize + min

		max = self.max.get()
		if (self.strictMinMax):
			if (rounded < min): rounded = min
			elif (rounded > max): rounded = max
		return rounded

	def round(self):
		if (self.quantize != None):
			self.set(self.roundValue(self.get()))

	def getRateMinQuantize(self) -> float:
		rate = self.getRate()
		if (self.quantize != None and rate < self.quantize.get()):
			rate = self.quantize.get()
		return rate

	def rateSCurve(self, n: float, r: float, min: float, max: float) -> float:
		origNormalized = (n - min) / (max - min)
		rateNormalized = r / (max - min)
		origTransformed = self.expOrLog(origNormalized, False)
		newTransformed = origTransformed + rateNormalized
		newNormalized = self.expOrLog(newTransformed, True)
		return newNormalized * (max - min) + min

	def increase(self):
		n = self.get()

		if (self.sliderExp):
			n = n * self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, self.getRate(), self.min.get(), self.max.get())
		else:
			n = n + self.getRateMinQuantize()

		if (self.strictMinMax and n > self.max.get()):
			n = self.max.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def decrease(self):
		n = self.get()

		if (self.sliderExp):
			n = n / self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, -self.getRate(), self.min.get(), self.max.get())
		else:
			n = n - self.getRateMinQuantize()

		if (self.strictMinMax and n < self.min.get()):
			n = self.min.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def reset(self):
		self.signal.reset()
		self.rate.reset()

	def increaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) * rateRate + 1)
		else:
			self.rate.set(n * rateRate)

	def decreaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) / rateRate + 1)
		else:
			self.rate.set(n / rateRate)

# See CombinedSlider in CadenceOS
class CombinedSlider():
	def __init__(self, sliders: list[Slider]):
		self.sliders = sliders

	def updateSliderRatios(self):
		firstValue = self.sliders[0].get()
		self.sliderRatios = []
		for slider in self.sliders:
			self.sliderRatios.push(slider.get() / firstValue)

	def updateSliders(self):
		firstValue = self.sliders[0].get()
		for i in range(len(self.sliders)):
			self.sliders[i].set(firstValue * self.sliderRatios[i - 1])

	def setNormalized(self, n: float):
		self.updateSliderRatios()
		super.setNormalized(n)
		self.updateSliders()

	def increase(self):
		for slider in self.sliders:
			slider.increase()

	def decrease(self):
		for slider in self.sliders:
			slider.decrease()

	def increaseRate(self):
		for slider in self.sliders:
			slider.increaseRate()

	def decreaseRate(self):
		for slider in self.sliders:
			slider.decreaseRate()

# See PanSlider in CadenceOS
class PanSlider(Slider):
	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool, zoom):
		super().__init__(default, rateDefault, rateRate, sliderExp, sliderSCurve, min, max, strictMinMax)
		self.zoom = zoom
	def getRate(self) -> float:
		return self.rate.get() / self.zoom()

def getDevicePosition(side: DevSide, flipped: bool) -> DevPosition:
	if side == DevSide.Left:
		if flipped:
			return DevPosition.TopRight
		else:
			return DevPosition.BottomLeft
	else:
		if flipped:
			return DevPosition.TopLeft
		else:
			return DevPosition.BottomRight

class HidFeatureReport(hid.HidOutputReport):
	_reportType = hidpi.HIDP_REPORT_TYPE.FEATURE

	def __init__(self, device, reportID=0):
		super().__init__(device, reportID)
		self._reportSize = device.caps.FeatureReportByteLength
		self._reportBuf = ctypes.c_buffer(self._reportSize)
		self._reportBuf[0] = 0

# Represents either a single device or a pair of two devices (where the second one is bluetooth connected to the first one)
# Isn't visible to NVDA, see CadenceDisplayDriver
class CadenceDeviceDriver(HidBrailleDriver):
	name = "CadenceDisplayDriver"
	description = _("Cadence HID Braille Display")

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(
			bdDetect.DeviceType.HID,
			{
				"VID_361F&PID_52AE",
			},
		)

		driverRegistrar.addBluetoothDevices(
			lambda m: isDeviceCadence(m)
		)

	def __init__(self, port, displayDriver, devIndex):
		log.info(f"HIDTest")
		log.info(f"HIDTest port {port}")
		log.info(f"HIDTest port.deviceInfo[devicePath] {port.deviceInfo['devicePath']}")

		log.info(f"HIDTest")

		for devMatch in bdDetect.getPossibleBluetoothDevicesForDriver(self.name):
			if devMatch.type != bdDetect.DeviceType.HID:
				continue
			log.info(f"HIDTest getPossibleBluetoothDevicesForDriver {devMatch}")

		log.info(f"HIDTest")

		for devMatch in bdDetect.deviceInfoFetcher.hidDevices:
			if devMatch["vendorID"] == 13855:
				log.info(f"HIDTest hidDevices {devMatch}")

		log.info(f"HIDTest")

		for devMatch in hwPortUtils.listHidDevices(onlyAvailable=True):
			if devMatch["vendorID"] == 13855:
				log.info(f"HIDTest listHidDevices {devMatch}")

		log.info(f"HIDTest")

		if not hwPortUtils._hidGuid:
			log.info(f"HIDTest NO HIDGUID")
		else:
			log.info(f"HIDTest YES HIDGUID")
		
		for g_hdi, idd, devinfo, buf in hwPortUtils._listDevices(hwPortUtils._hidGuid, True):
			log.info(f"HIDTest")
			# hardware ID
			if not hwPortUtils.SetupDiGetDeviceRegistryProperty(
				g_hdi,
				ctypes.byref(devinfo),
				hwPortUtils.SPDRP_HARDWAREID,
				None,
				ctypes.byref(buf),
				ctypes.sizeof(buf) - 1,
				None,
			):
				# Ignore ERROR_INSUFFICIENT_BUFFER
				if ctypes.GetLastError() != hwPortUtils.ERROR_INSUFFICIENT_BUFFER:
					raise ctypes.WinError()
				else:
					log.info("HIDTest insufficient buffer")
			else:
				hwId = buf.value
				info = hwPortUtils._getHidInfo(hwId, idd.DevicePath)
				log.info(f"HIDTest info {info}")
				log.info(f"HIDTest devinfo {devinfo}")
				log.info(f"HIDTest idd.DevicePath {idd.DevicePath}")
				match = bdDetect.DeviceMatch(bdDetect.DeviceType.HID, info["hardwareID"], info["devicePath"], info)
				log.info(f"HIDTest match {match}")
				if idd.DevicePath == port.deviceInfo.devicePath:
					log.info("HIDTest FOUND")
		
		super().__init__(port)
		# save properties
		self.displayDriver = displayDriver
		self.devIndex = devIndex
		log.info(f"########## CADENCE DEVICE {port} {self._dev}")

		self.valueCapsList = (hidpi.HIDP_VALUE_CAPS * self._dev.caps.NumberFeatureValueCaps)()
		numValueCaps = ctypes.c_long(self._dev.caps.NumberFeatureValueCaps)
		hid.check_HidP_status(
			hidDll.HidP_GetValueCaps,
			hidpi.HIDP_REPORT_TYPE.FEATURE,
			ctypes.byref(self.valueCapsList),
			ctypes.byref(numValueCaps),
			self._dev._pd)

		self.isOneHanded = not self.isTwoDevices()

		# detect left or right
		if "product" in port.deviceInfo:
			self.isRight = "product" in port.deviceInfo and port.deviceInfo["product"] == "Cadence-R"
		else:


			self.isRight = False

		# auto-select whether device is flipped based on whether another device is currently in non-flipped position
		currentPositionsOccupied = [device.getPosition(side) for device in self.displayDriver.devices for side in device.getSides()]
		self.isFlipped: dict[DevSide, bool] = {}
		for side in self.getSides():
			self.isFlipped[side] = False
			unflippedPos = self.getPosition(side)
			if unflippedPos in currentPositionsOccupied:
				self.isFlipped[side] = True

	# received button press (called by superclass)
	def _hidOnReceive(self, data: bytes):
		super()._hidOnReceive(data)
		self.displayDriver._hidOnReceive(data, self.devIndex)

	# handle button press
	def _handleKeyRelease(self):
		# TODO stop single-handed mode when there are multiple devices connected separately
		if not self.displayDriver.displayingImage:
			# handle button press as a keyboard input
			super()._handleKeyRelease()

	# is this actually two devices where the second one is connected to the first one through bluetooth
	def isTwoDevices(self):
		return self.numCols > 12

	# get list of device sides (left or right, or both if the second one is connected to the first one through bluetooth)
	def getSides(self) -> list[DevSide]:
		if self.isTwoDevices():
			# TODO Is right, left possible?
			return [DevSide.Left, DevSide.Right]
		elif self.isRight:
			return [DevSide.Right]
		else:
			return [DevSide.Left]

	# get position of device
	def getPosition(self, side: DevSide) -> DevPosition:
		flipped = self.isFlipped[side]
		return getDevicePosition(side, flipped)

	def setOneHanded(self, newOneHanded: bool):
		if newOneHanded == self.isOneHanded:
			return

		report = HidFeatureReport(self._dev)
		for valueCap in self.valueCapsList:
			if valueCap.LinkUsagePage == HID_USAGE_PAGE_BRAILLE and valueCap.u1.NotRange.Usage == 7:
				report.setUsageValueArray(
					HID_USAGE_PAGE_BRAILLE,
					valueCap.LinkCollection,
					valueCap.u1.NotRange.Usage,
					b"\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33\x33" if newOneHanded else b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
				)

		self._dev.setFeature(report.data)
		self.isOneHanded = newOneHanded


# A driver for multiple devices connected simultaneously
# This is the driver than NVDA sees, but actual communication with the device is delegated to CadenceDeviceDriver
class CadenceDisplayDriver(braille.BrailleDisplayDriver):
	name = "CadenceDisplayDriver"
	# Translators: The name of a series of braille displays.
	description = _("Cadence HID Braille Display")
	isThreadSafe = True
	supportsAutomaticDetection = True

	displayingImage: bool
	lastDisplayedNonImage: list[int] | None
	imageTimer: RunInterval | None

	lastLeft: int
	lastTop: int
	lastFitWidth: int
	lastFitHeight: int

	prevKeysDown: list[tuple[MiniKey, tuple[int, DevSide]]]
	liveKeys: list[tuple[MiniKey, tuple[int, DevSide]]]
	composedKeys: list[tuple[MiniKey, tuple[int, DevSide]]]

	devices: list[CadenceDeviceDriver]

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(
			bdDetect.DeviceType.HID,
			{
				"VID_361F&PID_52AE",
			},
		)

		driverRegistrar.addBluetoothDevices(
			lambda m: isDeviceCadence(m)
		)

	def __init__(self, port):
		super().__init__()
		# initialize properties
		self.displayingImage = False
		self.lastDisplayedNonImage = None
		self.imageTimer = None
		self.lastLeft = -1
		self.lastTop = -1
		self.lastFitWidth = -1
		self.lastFitHeight = -1
		self.prevKeysDown = []
		self.liveKeys = []
		self.composedKeys = []
		self.devices = []

		# for test in listHidDevices(True):
		# 	if "VID&02361f_PID&52ae" in test["hardwareID"]:
		# 		log.info(f"## HIDTest {test}")

		# check for USB devices
		for devMatch in self._getTryPorts("usb"):
			if devMatch.type != bdDetect.DeviceType.HID:
				continue
			device = CadenceDeviceDriver(devMatch, self, len(self.devices))
			self.devices.append(device)

		# if no USB devices, check for bluetooth devices
		# TODO figure out a way to determine which usb and bluetooth connections are the same device in case we want to connect to a mix of USB and bluetooth devices
		if len(self.devices) == 0:
			for devMatch in self._getTryPorts("bluetooth"):
				if devMatch.type != bdDetect.DeviceType.HID:
					continue
				device = CadenceDeviceDriver(devMatch, self, len(self.devices))
				self.devices.append(device)

		# if no devices, error
		if len(self.devices) == 0:
			raise RuntimeError("no cadence devices")

		log.info(f"########################## cadence driver initialized {port} {self.devices}")

		for devI, device in enumerate(self.devices):
			for side in device.getSides():
				log.info(f"device: {devI} {side} {device.getPosition(side)}")

		# initialize screen size
		self.updateScreenSize()

		screenWidth, screenHeight = getScreenResolution()

		# initialize more properties
		self.zoomX = Slider(-1,
			defaultZoomRate,
			zoomRateRate,
			True,
			False,
			0.00000000001,
			1000000000,
			True)
		self.zoomY = Slider(-1,
			defaultZoomRate,
			zoomRateRate,
			True,
			False,
			0.00000000001,
			1000000000,
			True)
		self.combinedZoom = CombinedSlider([self.zoomX, self.zoomY])
		self.centerX = PanSlider(0,
			defaultPanRate,
			panRateRate,
			False,
			False,
			0,
			screenWidth,
			True,
			lambda: self.zoomX.get() * 24 / 2)
		self.centerY = PanSlider(0,
			defaultPanRate,
			panRateRate,
			False,
			False,
			-screenHeight,
			0,
			True,
			lambda: self.zoomX.get() * 16 / 2)
		self.combinedPan = CombinedSlider([self.centerX, self.centerY])
		self.bwThreshold = Slider(bwThresholdOutOf / 2,
			defaultBwThresholdRate,
			1.5,
			False,
			True,
			0,
			bwThresholdOutOf,
			True)
		self.bwReversed = True
		self.colorMode = 0

	# toggle between text and image mode
	def doToggleImage(self):
		self.displayingImage = not self.displayingImage
		if self.displayingImage:
			self.displayImage()
			if self.imageTimer is None:
				self.imageTimer = RunInterval(self.displayImage, 0.5)
				self.imageTimer.start()
		else:
			self.restoreNonImage()
			if self.imageTimer is not None:
				self.imageTimer.cancel()
				self.imageTimer = None
		self.updateOneHanded()

	# draw image mode (screencapture of current navigator object)
	def displayImage(self, resetView = False):
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			lambda : self.actuallyDisplayImage(resetView),
			_immediate=True,
		)
	def actuallyDisplayImage(self, resetView = False):
		obj = api.getNavigatorObject()
		if obj is None:
			log.info("no navigator object, switching to focus object")
			obj = api.getFocusObject()
			if obj is None:
				log.error("no focus object")
				self.doToggleImage()
				return
		self.prevObj = obj
		while obj is not None and obj.location is None:
			log.warn("object has no location, trying parent")
			obj = obj.parent
		if obj is None:
			log.error("no location for object when displaying image")
			self.doToggleImage()
			return
		location = obj.location
		(left, top, width, height) = location
		log.info(f"######## screenshot {left} {top} {width} {height}")
		if width <= 0 or height <= 0:
			log.error("invalid object location")
			self.doToggleImage()
			return
		if resetView or left != self.lastLeft or top != self.lastTop or self.lastFitWidth != width or self.lastFitHeight != height:
			self.reset(left, top, width, height)
		screenWidth = self.getDisplayWidth()
		screenHeight = self.getDisplayHeight()

		topLeftX = self.screenXToVirtual(0, self.getDisplayWidth())
		topLeftY = -self.screenYToVirtual(0, self.getDisplayHeight())
		bottomRightX = self.screenXToVirtual(self.getDisplayWidth(), self.getDisplayWidth())
		bottomRightY = -self.screenYToVirtual(self.getDisplayHeight(), self.getDisplayHeight())

		bitmapHolder = ScreenBitmap(screenWidth, screenHeight)
		# TODO don't round here
		bitmapBuffer = bitmapHolder.captureImage(round(topLeftX), round(topLeftY), round(bottomRightX - topLeftX), round(bottomRightY - topLeftY))
		boolImage = bitmapToImage(bitmapBuffer, screenWidth, screenHeight, self.bwThreshold.get(), self.bwReversed, self.colorMode)
		cells = imageToCells(boolImage)
		self.display(cells, True)

	# restore text mode by drawing text
	def restoreNonImage(self):
		if self.lastDisplayedNonImage is not None:
			self.display(self.lastDisplayedNonImage)

	# crop a screen to a device position
	def getImage(self, fullImage: list[list[bool]], pos: DevPosition) -> list[list[bool]]:
		xOffset = (24 if (pos == DevPosition.TopRight or pos == DevPosition.BottomRight) else 0) - self.offsetCols * 2
		yOffset = (16 if (pos == DevPosition.BottomLeft or pos == DevPosition.BottomRight) else 0) - self.offsetRows * 4
		image = [[fullImage[y + yOffset][x + xOffset] for x in range(24)] for y in range(16)]
		flipped = pos == DevPosition.TopLeft or pos == DevPosition.TopRight
		# log.info(f"display {pos} / {xOffset} / {yOffset} / {flipped}")
		if flipped:
			image = flipImage(image)
		return image

	# display on device (called by NVDA or manually in some cases)
	def display(self, cells: list[int], isImage = False):
		if not isImage:
			self.lastDisplayedNonImage = cells
		if isImage == self.displayingImage:
			# log.info(f"display {len(cells)} {self.numRows} {self.numCols}")
			if len(cells) < self.numRows * self.numCols:
				cells = [(cells[i] if i < len(cells) else 0) for i in self.numRows * self.numCols]
			cells = cells[:(self.numRows * self.numCols)]
			fullImage = cellsToImage(cells, self.numRows)
			for devI, device in enumerate(self.devices):
				sides = device.getSides()
				leftDevPos = device.getPosition(sides[0])
				# log.info(f"left {devI} {leftDevPos}")
				image = self.getImage(fullImage, leftDevPos)
				if len(sides) > 1:
					rightDevPos = device.getPosition(sides[1])
					# log.info(f"right {devI} {rightDevPos}")
					rightSideImage = self.getImage(fullImage, rightDevPos)
					image = joinImagesHorizontally(image, rightSideImage)
				devCells = imageToCells(image)
				device.display(devCells)

	# cleanup on exit (called by NVDA)
	def terminate(self):
		super().terminate()
		for device in self.devices:
			device.terminate()
		if self.imageTimer is not None:
			self.imageTimer.cancel()
			self.imageTimer = None

	# helper functions for screen size
	def getDisplayWidth(self):
		return self.numCols * 2
	def getDisplayHeight(self):
		return self.numRows * 4
	# reset image view
	def reset(self, left, top, toDrawWidth, toDrawHeight):
		self.centerX.set(left + toDrawWidth / 2)
		self.centerY.set(-(top + toDrawHeight / 2))
		if (self.zoomX.get() < 0 or self.zoomY.get() < 0):
			fullZoom = min(2 / toDrawWidth, 2 / toDrawHeight * self.getDisplayHeight() / self.getDisplayWidth())
			halfZoom = max(1 / toDrawWidth, 1 / toDrawHeight * self.getDisplayHeight() / self.getDisplayWidth())
			zoom = max(halfZoom, fullZoom)
			self.zoomX.set(zoom)
			self.zoomY.set(zoom * self.getDisplayWidth() / self.getDisplayHeight())
		self.lastLeft = left
		self.lastTop = top
		self.lastFitWidth = toDrawWidth
		self.lastFitHeight = toDrawHeight
	# helper functions for image mode - see NavigatibleCanvas in CadenceOS
	def virtualXToScreen(self, actualX, graphWidth):
		return (actualX - self.centerX.get()) * self.zoomX.get() * ((graphWidth) / 2) + (graphWidth) / 2
	def virtualYToScreen(self, actualY, graphHeight):
		return graphHeight - ((actualY - self.centerY.get()) * self.zoomY.get() * ((graphHeight) / 2) + (graphHeight) / 2)
	def screenXToVirtual(self, graphX, graphWidth):
		return ((graphX) - ((graphWidth) / 2)) / ((graphWidth) / 2) / self.zoomX.get() + self.centerX.get()
	def screenYToVirtual(self, graphY, graphHeight):
		return ((graphHeight - graphY) - ((graphHeight) / 2)) / ((graphHeight) / 2) / self.zoomY.get() + self.centerY.get()

	# flip keys if necessary due to device position
	def rotateKey(self, key: MiniKey, pos: DevPosition) -> MiniKey:
		if pos == DevPosition.TopLeft or pos == DevPosition.TopRight:
			if key in flippedKeys:
				return flippedKeys[key]
		return key

	# receive button press from device (called by CadenceDeviceDriver)
	def _hidOnReceive(self, data: bytes, devIndex: int):
		# log.info("# data: " + " ".join([f"{b:0>8b}" for b in data]))
		if len(data) == 5 or len(data) == 7:
			keysDown = [key for key in self.prevKeysDown if key[1][0] != devIndex]
			for byteI, byte in enumerate(data):
				for bitI in range(8):
					if byte & (1 << bitI):
						index = byteI * 8 + bitI
						log.info(f"## key {index}")
						device = self.devices[devIndex]
						devSides = device.getSides()
						devSide = devSides[0]
						if len(data) == 7:
							if index in rightKeys:
								index = rightKeys[index]
								devSide = devSides[1]
						key = MiniKey(index)
						key = self.rotateKey(key, self.getDevPosition((devIndex, devSide)))
						if len(data) == 5:
							if key == MiniKey.Dot4:
								key = MiniKey.Dot1
							elif key == MiniKey.Dot5:
								key = MiniKey.Dot2
							elif key == MiniKey.Dot6:
								key = MiniKey.Dot3
							elif key == MiniKey.Dot8:
								key = MiniKey.Dot7
						if not key in keysDown:
							keysDown.append((key, (devIndex, devSide)))
			newKeys = [key for key in keysDown if key not in self.prevKeysDown]
			keysUp = [key for key in self.prevKeysDown if not key in keysDown]
			if len(newKeys) > 0:
				self.composedKeys = []
				for key in newKeys:
					if not key in self.liveKeys:
						self.liveKeys.append(key)
			if len(keysUp) > 0:
				self.liveKeys = [key for key in self.liveKeys if not key in keysUp]

			end = len(self.composedKeys) != 0 and len(self.liveKeys) == 0

			if len(keysUp) > 0:
				for key in keysUp:
					if not key in self.composedKeys:
						self.composedKeys.append(key)

			self.handleKeys(self.liveKeys, self.composedKeys)

			if end:
				self.composedKeys = []

			self.prevKeysDown = keysDown

	# pan image
	def pan(self, direction: Direction):
		log.info("pan")
		if direction == Direction.Up:
			self.centerY.increase()
		elif direction == Direction.Down:
			self.centerY.decrease()
		elif direction == Direction.Left:
			self.centerX.decrease()
		elif direction == Direction.Right:
			self.centerX.increase()
		self.displayImage()
	# zoom image
	def zoom(self, zoomIn: bool):
		log.info("zoom")
		if zoomIn:
			self.combinedZoom.increase()
		else:
			self.combinedZoom.decrease()
		self.displayImage()
	# change image threshold
	def changeThreshold(self, increase: bool):
		log.info("changeThreshold")
		if increase:
			self.bwThreshold.increase()
		else:
			self.bwThreshold.decrease()
		self.displayImage()
	# reverse image threshold
	def reverseThreshold(self):
		log.info("reverse threshold")
		self.bwReversed = not self.bwReversed
		self.displayImage()
	# cycle image color mode
	def cycleColorMode(self):
		log.info("cycle color mode")
		self.colorMode = (self.colorMode + 1) % 4
		self.displayImage()
	# reset image view
	def resetAction(self):
		log.info("reset")
		self.bwThreshold.reset()
		self.colorMode = 0
		self.bwReversed = True
		self.zoomX.set(-1)
		self.zoomY.set(-1)
		self.displayImage(True)
	# change image pan rate
	def changePanRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} pan rate")
		if increase:
			self.combinedPan.increaseRate()
		else:
			self.combinedPan.decreaseRate()
	# change image zoom rate
	def changeZoomRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} zoom rate")
		if increase:
			self.combinedZoom.increaseRate()
		else:
			self.combinedZoom.decreaseRate()
	# change image threshold rate
	def changeThresholdRate(self, increase):
		log.info(f"{'increase' if increase else 'decrease'} threshold rate")
		if increase:
			self.bwThreshold.increaseRate()
		else:
			self.bwThreshold.decreaseRate()
	# pan image to edge
	def panEdgeUp(self):
		virtualHeight = self.screenYToVirtual(0, 1) - self.screenYToVirtual(1, 1)
		self.centerY.set(1 - virtualHeight / 2)
		self.displayImage()
	def panEdgeDown(self):
		virtualHeight = self.screenYToVirtual(0, 1) - self.screenYToVirtual(1, 1)
		self.centerY.set(virtualHeight / 2)
		self.displayImage()
	def panEdgeLeft(self):
		virtualWidth = self.screenXToVirtual(1, 1) - self.screenXToVirtual(0, 1)
		self.centerX.set(virtualWidth / 2)
		self.displayImage()
	def panEdgeRight(self):
		virtualWidth = self.screenXToVirtual(1, 1) - self.screenXToVirtual(0, 1)
		self.centerX.set(1 - virtualWidth / 2)
		self.displayImage()

	# update screen size based on the current positions of connected devices
	def updateScreenSize(self):
		devPositions: list[DevPosition] = []
		for device in self.devices:
			for side in device.getSides():
				devPositions.append(device.getPosition(side))

		self.offsetCols = 0
		self.offsetRows = 0

		if (DevPosition.BottomLeft in devPositions or DevPosition.TopLeft in devPositions) and (DevPosition.BottomRight in devPositions or DevPosition.TopRight in devPositions):
			self.numCols = 24
		else:
			if DevPosition.BottomRight in devPositions or DevPosition.TopRight in devPositions:
				self.offsetCols = 12
			self.numCols = 12

		if (DevPosition.BottomLeft in devPositions or DevPosition.BottomRight in devPositions) and (DevPosition.TopLeft in devPositions or DevPosition.TopRight in devPositions):
			self.numRows = 8
		else:
			if DevPosition.BottomLeft in devPositions or DevPosition.BottomRight in devPositions:
				self.offsetRows = 4
			self.numRows = 4

		log.info(f"## UPDATED SIZE {self.numRows} {self.numCols} {[device.isTwoDevices() for device in self.devices]}")

		self.updateOneHanded()

	def updateOneHanded(self):
		newOneHanded = False if self.displayingImage else (self.numCols == 12)

		log.info(f"setting one handed {newOneHanded}")

		for device in self.devices:
			device.setOneHanded(newOneHanded)

	# get current device position for a device
	def getDevPosition(self, device: tuple[int, DevSide]) -> DevPosition:
		return self.devices[device[0]].getPosition(device[1])

	# run after changing device positions to update screens
	def afterDevicePositionsChanged(self):
		self.updateScreenSize()
		if self.displayingImage:
			self.displayImage(True)
		else:
			self.restoreNonImage()


	# move current device position by flipping it
	def flipScreen(self, deviceID: tuple[int, DevSide], flipped: bool):
		log.info(f"flipScreen {deviceID} {flipped}")
		device = self.devices[deviceID[0]]
		device.isFlipped[deviceID[1]] = flipped
		newPosition = device.getPosition(deviceID[1])
		for otherDevice in self.devices:
			if otherDevice != device:
				for otherDeviceSide in otherDevice.getSides():
					otherDevicePos = otherDevice.getPosition(otherDeviceSide)
					if otherDevicePos == newPosition:
						otherDevice.isFlipped[otherDeviceSide] = not flipped
		self.afterDevicePositionsChanged()

	# cycle through possible device positions
	def cycleDevPositions(self):
		# get all individual devices
		deviceIds = [(devIndex, side) for devIndex, device in enumerate(self.devices) for side in device.getSides()]
		# get number of lefts and rights
		numLefts = len([(devIndex, side) for devIndex, side in deviceIds if side == DevSide.Left])
		numRights = len([(devIndex, side) for devIndex, side in deviceIds if side == DevSide.Right])
		# determine form factor(s)
		if numLefts >= 2 and numRights >= 2:
			forms = [set([DevPosition.BottomLeft, DevPosition.BottomRight, DevPosition.TopLeft, DevPosition.TopRight])]
		elif numLefts >= 1 and numRights >= 1:
			forms = [set([DevPosition.BottomLeft, DevPosition.BottomRight]), set([DevPosition.BottomLeft, DevPosition.TopLeft])]
		elif numLefts >= 1:
			forms = [set([DevPosition.BottomLeft])]
		else:
			forms = [set([DevPosition.BottomRight])]
		# find all possible options
		options: list[list[bool]] = []
		for positions in itertools.product([True, False], repeat=len(deviceIds)):
			if numLefts > 2 and numRights > 2:
				# don't combine two tall duets into a quartet
				devIndexFlipped = {}
				isTall = False
				for i in range(len(deviceIds)):
					devIndex = deviceIds[i][0]
					flipped = positions[i]
					if devIndex in devIndexFlipped and devIndexFlipped[devIndex] != flipped:
						isTall = True
						break
					devIndexFlipped[devIndex] = flipped
				if isTall:
					continue

			currentForm = set([getDevicePosition(deviceIds[i][1], positions[i]) for i in range(len(deviceIds))])
			if currentForm in forms:
				options.append(list(positions))
		# get current device positions
		currentPositions = [self.devices[devIndex].isFlipped[side] for devIndex, side in deviceIds]
		# find index of current device position in options
		currentPositionI = -1
		if currentPositions in options:
			currentPositionI = options.index(currentPositions)
		log.info(f"{deviceIds}, {numLefts}, {numRights}, {forms}, {options}, {currentPositions}, {currentPositionI}")
		# get new device positions
		newPositions = options[0] if currentPositionI + 1 >= len(options) else options[currentPositionI + 1]
		# set new device positions
		for i in range(len(deviceIds)):
			devIndex, side = deviceIds[i]
			flipped = newPositions[i]
			self.devices[devIndex].isFlipped[side] = flipped
		# update
		self.afterDevicePositionsChanged()

	# handle keys
	def handleKeys(self, liveKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]], composedKeysWithPosition: list[tuple[MiniKey, tuple[int, DevSide]]]):
		log.info(f"## {liveKeysWithPosition} {composedKeysWithPosition}")

		liveKeys = [key[0] for key in liveKeysWithPosition]
		composedKeys = [key[0] for key in composedKeysWithPosition]

		if self.displayingImage:
			if len(liveKeys) == 1:
				# pan - arrow keys
				if MiniKey.DPadUp in liveKeys:
					self.pan(Direction.Up)
				elif MiniKey.DPadDown in liveKeys:
					self.pan(Direction.Down)
				elif MiniKey.DPadLeft in liveKeys:
					self.pan(Direction.Left)
				elif MiniKey.DPadRight in liveKeys:
					self.pan(Direction.Right)
				# zoom in - pan right, zoom out - pan left
				elif MiniKey.PanRight in liveKeys:
					self.zoom(True)
				elif MiniKey.PanLeft in liveKeys:
					self.zoom(False)
				# increase threshold - dot7, decrease threshold - dot3
				elif MiniKey.Dot7 in liveKeys:
					self.changeThreshold(True)
				elif MiniKey.Dot3 in liveKeys:
					self.changeThreshold(False)
				# reverse threshold - dot2
				elif MiniKey.Dot2 in liveKeys:
					self.reverseThreshold()
				# cycle color mode - dot1
				elif MiniKey.Dot1 in liveKeys:
					self.cycleColorMode()
			elif len(liveKeys) == 2:
				if MiniKey.Row1 in liveKeys or MiniKey.Row2 in liveKeys:
					increase = (MiniKey.Row1 in liveKeys)
					# pan faster - row1 + arrow, pan slower - row2 + arrow
					if MiniKey.DPadUp in liveKeys or MiniKey.DPadDown in liveKeys or MiniKey.DPadLeft in liveKeys or MiniKey.DPadRight in liveKeys:
						self.changePanRate(increase)
					# zoom faster - row1 + pan, zoom slower - row2 + pan
					elif MiniKey.PanLeft in liveKeys or MiniKey.PanRight in liveKeys:
						self.changeZoomRate(increase)
					# threshold faster - row1 + dot2, threshold slower row2 + dot2
					elif MiniKey.Dot2 in liveKeys:
						self.changeThresholdRate(increase)
				# pan to edge - space + arrow or (up - space + dots123, down - space + dots 456, left - space + dots23, right - space + dots56)
				if MiniKey.Space in liveKeys:
					if MiniKey.DPadUp in liveKeys:
						self.panEdgeUp()
					elif MiniKey.DPadDown in liveKeys:
						self.panEdgeDown()
					elif MiniKey.DPadLeft in liveKeys:
						self.panEdgeLeft()
					elif MiniKey.DPadRight in liveKeys:
						self.panEdgeRight()
			elif len(liveKeys) == 4:
				# reset - dots1237
				if MiniKey.Dot1 in liveKeys and MiniKey.Dot2 in liveKeys and MiniKey.Dot3 in liveKeys and MiniKey.Dot7 in liveKeys:
					self.resetAction()

		if len(liveKeys) == 1:
			if MiniKey.Row3 in liveKeys:
				self.doToggleImage()

		if len(composedKeys) == 1:
			if MiniKey.Row1 in composedKeys or MiniKey.Row4 in composedKeys:
				position = self.getDevPosition(composedKeysWithPosition[0][1])
				isCurrentlyFlipped = position == DevPosition.TopLeft or position == DevPosition.TopRight
				self.flipScreen(composedKeysWithPosition[0][1], (MiniKey.Row4 in composedKeys and not isCurrentlyFlipped) or (MiniKey.Row1 in composedKeys and isCurrentlyFlipped))

	# map of device buttons to keyboard keys for non-image mode
	gestureMap = inputCore.GlobalGestureMap(
		{
			"globalCommands.GlobalCommands": {
				"braille_scrollBack": (
					"br(hidBrailleStandard):panLeft",
					"br(hidBrailleStandard):rockerUp",
				),
				"braille_scrollForward": (
					"br(hidBrailleStandard):panRight",
					"br(hidBrailleStandard):rockerDown",
				),
				"braille_routeTo": ("br(hidBrailleStandard):routerSet1_routerKey",),
				"braille_toggleTether": ("br(hidBrailleStandard):up+down",),
				"kb:upArrow": (
					"br(hidBrailleStandard):joystickUp",
					"br(hidBrailleStandard):dpadUp",
					"br(hidBrailleStandard):space+dot1",
				),
				"kb:downArrow": (
					"br(hidBrailleStandard):joystickDown",
					"br(hidBrailleStandard):dpadDown",
					"br(hidBrailleStandard):space+dot4",
				),
				"kb:leftArrow": (
					"br(hidBrailleStandard):space+dot3",
					"br(hidBrailleStandard):joystickLeft",
					"br(hidBrailleStandard):dpadLeft",
				),
				"kb:rightArrow": (
					"br(hidBrailleStandard):space+dot6",
					"br(hidBrailleStandard):joystickRight",
					"br(hidBrailleStandard):dpadRight",
				),
				"showGui": ("br(hidBrailleStandard):space+dot1+dot3+dot4+dot5",),
				"kb:shift+tab": ("br(hidBrailleStandard):space+dot1+dot3",),
				"kb:tab": ("br(hidBrailleStandard):space+dot4+dot6",),
				"kb:alt": ("br(hidBrailleStandard):space+dot1+dot3+dot4",),
				"kb:escape": ("br(hidBrailleStandard):space+dot1+dot5",),
				"kb:enter": (
					"br(hidBrailleStandard):joystickCenter",
					"br(hidBrailleStandard):dpadCenter",
				),
				"kb:windows+d": ("br(hidBrailleStandard):Space+dot1+dot4+dot5",),
				"kb:windows": ("br(hidBrailleStandard):space+dot3+dot4",),
				"kb:alt+tab": ("br(hidBrailleStandard):space+dot2+dot3+dot4+dot5",),
				"sayAll": ("br(hidBrailleStandard):Space+dot1+dot2+dot3+dot4+dot5+dot6",),
			},
		},
	)

# export CadenceDisplayDriver
BrailleDisplayDriver = CadenceDisplayDriver
#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

"""
DSC Alarm Plugin
Developed by Travis Cook and modified by Monstergerm.
This plugin supports DSC alarm panels. It does not work with Vista 20p panels.
Envisalink 4 is the recommended interface.
Anything related to thermostats has not been field tested.
The plugin can be found on Github and in the Indigo Plugin Store.
The Github repository also shows examples for a control page, buttons for Arm and Disarm and icons for zones, bypass etc.
https://github.com/IndigoDomotics/DSC-Alarm
This plugin requires Python 3.10 and Indigo 2022.1.x and higher.

"""

import os
import platform
import sys
import re
import time
from datetime import datetime
import logging
import serial
try:
    import indigo
except ImportError:
    pass

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.


kSocketPort = 1514
kSocketBufferSize = 1024
kSocketTimeout = 1

kZoneStateOpen = 'open'
kZoneStateClosed = 'closed'
kZoneStateTripped = 'tripped'
kZoneBypassNo = 'nobypass'
kZoneBypassYes = 'bypassed'
kZoneGroupStateOpen = 'zoneOpen'
kZoneGroupStateClosed = 'allZonesClosed'
kZoneGroupStateTripped = 'zoneTripped'
kAlarmStateDisarmed = 'disarmed'
kAlarmStateExitDelay = 'exitDelay'
kAlarmStateFailedToArm = 'FailedToArm'
kAlarmStateArmedStay = 'armedStay'
kAlarmStateArmedAway = 'armedAway'
kAlarmStateEntryDelay = 'entryDelay'
kAlarmStateTripped = 'tripped'
kKeypadStateChimeEnabled = 'enabled'
kKeypadStateChimeDisabled = 'disabled'
kAlarmArmedStateDisarmed = 'disarmed'
kAlarmArmedStateStay = 'stay'
kAlarmArmedStateAway = 'away'
kReadyStateTrue = 'ready'
kReadyStateFalse = 'notready'
kPanicStateNone = 'none'
kPanicStateFire = 'fire'
kPanicStateSmoke = 'smoke'
kPanicStateAmbulance = 'ambulance'
kPanicStatePanic = 'panic'
kPanicStateDuress = 'duress'


kLedIndexList = ['None', 'Ready', 'Armed', 'Memory', 'Bypass', 'Trouble', 'Program', 'Fire', 'Backlight', 'AC']
kLedStateList = ['off', 'on', 'flashing']
kArmedModeList = ['Away', 'Stay', 'Away, No Delay', 'Stay, No Delay']
kPanicTypeList = ['None', 'Fire', 'Ambulance', 'Panic']
kMonthList = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
kLogLevelList = ['Detailed Debug', 'Debug', 'Info', 'Warning', 'Error', 'Critical']


kCmdNormal = 0
kCmdThermoSet = 1
kPingInterval = 301
kHoldRetryTimeMinutes = 3


##########################################################################################
class Plugin(indigo.PluginBase):

	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

		self.States = self.enum(STARTUP=1, HOLD=2, HOLD_RETRY=3, HOLD_RETRY_LOOP=4, BOTH_INIT=5, SO_CONNECT=6, ENABLE_TIME_BROADCAST=7, BOTH_PING=8, BOTH_POLL=9)
		self.state = self.States.STARTUP

		# ============================ Configure Logging =================================
		try:
			self.logLevel = int(self.pluginPrefs.get("logLevel",20))
			if self.logLevel < 5:  # convert old logging pref settings to level 20(INFO)
				self.logLevel = logging.INFO
				self.logger.info("We are converting old log settings.")
		except:
			self.logLevel = logging.INFO
			self.logger.info("We are forcing log settings to INFO.")
		# Set the format and level handlers for the logger
		log_format = '%(asctime)s.%(msecs)03d\t%(levelname)-10s\t%(name)s.%(funcName)-28s %(msg)s'
		self.plugin_file_handler.setFormatter(logging.Formatter(fmt=log_format, datefmt='%Y-%m-%d %H:%M:%S'))
		self.indigo_log_handler.setLevel(self.logLevel)
		# ================================================================================

		self.shutdown = False
		self.configRead = False
		self.interfaceState = 0
		self.zoneList = {}
		self.tempList = {}
		self.zoneGroupList = {}
		self.trippedZoneList = []
		self.triggerList = []
		self.keypadList = {}
		self.createVariables = False
		self.port = None
		self.repeatAlarmTripped = False
		self.isPortOpen = False
		self.useSerial = False
		self.txCmdList = []
		self.closeTheseZonesList = []
		self.currentHoldRetryTime = kHoldRetryTimeMinutes
		self.ourVariableFolder = None
		self.configEmailUrgent = ""
		self.configEmailNotice = ""
		self.configEmailDisarm = ""
		self.configEmailUrgentSubject = ""
		self.configEmailNoticeSubject = ""
		self.configEmailDisarmSubject = ""
		self.userCode = ""
		self.userLabel = ""
		self.userLabelDict = {}
		self.configSpeakVariable = None
		self.configKeepTimeSynced = True
		self.configUseCustomIcons = True
		self.timesyncflag = True
		self.troubleCode = 0
		self.troubleClearedTimer = 0
		
		try:
			self.pluginPrefs["TwoDS_Port"]
		except KeyError:
			self.pluginPrefs["TwoDS_Port"] = "4025"
				
		if "DSC" not in indigo.variables.folders:
			indigo.variables.folder.create("DSC")
		if "DSC_Alarm_Text" not in indigo.variables:
			indigo.variable.create("DSC_Alarm_Text", value="", folder="DSC")
		if "DSC_Alarm_Memory" not in indigo.variables:
			indigo.variable.create("DSC_Alarm_Memory", value="no tripped zones", folder="DSC")
		if "DSC_Command" not in indigo.variables:
			indigo.variable.create("DSC_Command", value="#", folder="DSC")
		if "DSC_Last_User_Disarm" not in indigo.variables:
			indigo.variable.create("DSC_Last_User_Disarm", value="", folder="DSC")
		if "DSC_Last_Zone_Active" not in indigo.variables:
			indigo.variable.create("DSC_Last_Zone_Active", value="", folder="DSC")
		if "DSC_Last_Motion_Active" not in indigo.variables:
			indigo.variable.create("DSC_Last_Motion_Active", value="", folder="DSC")



	def enum(self, **enums):
		return type('Enum', (), enums)

	def __del__(self):
		indigo.PluginBase.__del__(self)

	######################################################################################
	def startup(self):
		self.logger.debug(f"Startup called. Log Levels are set to \"{kLogLevelList[int(self.logLevel/10)]}\".")
		self.configRead = self.getConfiguration(self.pluginPrefs)

		spacer = " " * 35
		environment_state = f"\n"
		environment_state += spacer + f"{'='*20}{' Initializing New Plugin Session '}{'='*54}\n"
		environment_state += spacer + f"{'Plugin name:':<20} {self.pluginDisplayName}\n"
		environment_state += spacer + f"{'Plugin version:':<20} {self.pluginVersion}\n"
		environment_state += spacer + f"{'Plugin ID:':<20} {self.pluginId}\n"
		environment_state += spacer + f"{'Plugin Log Level:':<20} {kLogLevelList[int(self.logLevel/10)]}\n"
		environment_state += spacer + f"{'Indigo version:':<20} {indigo.server.version}\n"
		environment_state += spacer + "{0:<20} {1}\n".format("Python version:", sys.version.replace('\n', ''))
		environment_state += spacer + f"{'Mac OS Version:':<20} {platform.mac_ver()[0]}\n"
		environment_state += spacer + f"{'Process ID:':<20} {os.getpid()}\n"
		environment_state += spacer + f"{'':{'='}^107}\n"
		self.logger.info(environment_state)
		

	def shutdown(self):
		self.logger.debug("Shutdown called")


	######################################################################################
	# Indigo Device Start/Stop
	######################################################################################

	def deviceStartComm(self, dev):
		self.logger.threaddebug(f"<<-- entering deviceStartComm: {dev.name} ({dev.id} - {dev.deviceTypeId})")

		props = dev.pluginProps

		if dev.deviceTypeId == 'alarmZoneGroup':

			if dev.id not in self.zoneGroupList:
				self.zoneGroupList[dev.id] = props['devList']

			if dev.states['state'] == 0:
				dev.updateStateOnServer(key="state", value=kZoneGroupStateClosed)

			if 'AnyMemberLastChangedShort' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()

			if 'EntireGroupLastChangedShort' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()

		elif dev.deviceTypeId == 'alarmZone':
			if 'zoneNumber' not in props:
				return

			zone = int(props['zoneNumber'])
			if zone not in list(self.zoneList.keys()):
				self.zoneList[zone] = dev.id
			else:
				self.logger.error(f"Zone {zone} is already assigned to another device.")

			# Check for new version zone states.
			# If they're not present tell Indigo to reread the Devices.xml file
			if 'LastChangedShort' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()

			# If state is invalid or not there, set to closed
			if dev.states['state'] == 0:
				dev.updateStateOnServer(key='state', value=kZoneStateClosed)

			# If plugin is v2.x we won't have a bypass key so set it to default
			if 'bypass' not in dev.states or dev.states['bypass'] == 0:
				dev.stateListOrDisplayStateIdChanged()
				dev.updateStateOnServer(key='bypass', value=kZoneBypassNo)

			# If plugin is v2.x we won't have a zonePartition key so set it to 1 by default
			if 'zonePartition' not in props:
				props.update({'zonePartition': '1'})
				dev.replacePluginPropsOnServer(props)

			dev.updateStateOnServer(key="LastChangedShort", value=self.getShortTime(dev.states["LastChangedTimer"]))


			# Check for new version properties to see if we need to refresh the device
			if 'occupancyGroup' not in props:
				self.logger.debug(f"Adding occupancyGroup to device {dev.name} properties.")
				props.update({"occupancyGroup": 0})
				dev.replacePluginPropsOnServer(props)

			# If the variable we used no longer exists then remove the varID
			if "var" in props:
				if props["var"] not in indigo.variables:
					props["var"] = None
					dev.replacePluginPropsOnServer(props)
			else:
				props["var"] = None
				dev.replacePluginPropsOnServer(props)


		elif dev.deviceTypeId == 'alarmKeypad':
			partition = int(dev.pluginProps['partitionNumber'])
			if partition not in list(self.keypadList.keys()):
				self.keypadList[partition] = dev.id
				self.logger.debug(f"Adding keypad: {self.keypadList}")
			else:
				self.logger.error("Partition is already assigned to another device.")

			# If plugin is very old version v2.x we won't have a partitionName key so set it to "Default"
			if 'partitionName' not in dev.pluginProps:
				props['partitionName'] = 'Default'
				dev.replacePluginPropsOnServer(props)

			dev.updateStateOnServer(key='state', value=kAlarmStateDisarmed)
			dev.updateStateOnServer(key='ReadyState', value=kReadyStateTrue)
			dev.updateStateOnServer(key='PanicState', value=kPanicStateNone)
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)   # green circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Unlocked)  # red open padlock
			else:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

			# Check for new keypad states.
			# If they're not present tell Indigo to reread the Devices.xml file
			if 'ArmedState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
			elif 'ReadyState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
			elif 'PanicState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
			elif "armedAway" not in dev.states['state']:
				dev.stateListOrDisplayStateIdChanged()
			elif "armedStay" not in dev.states['state']:
				dev.stateListOrDisplayStateIdChanged()


		elif dev.deviceTypeId == 'alarmTemp':
			sensor = int(dev.pluginProps['sensorNumber'])
			if sensor not in list(self.tempList.keys()):
				self.tempList[sensor] = dev

		self.logger.threaddebug("exiting deviceStartComm -->>")


	def deviceStopComm(self, dev):
		self.logger.threaddebug(f"<<-- entering deviceStopComm: {dev.name} ({dev.id} - {dev.deviceTypeId})")

		if dev.deviceTypeId == 'alarmZoneGroup':
			if dev.id in self.zoneGroupList:
				del self.zoneGroupList[dev.id]

		elif dev.deviceTypeId == 'alarmZone':
			if 'zoneNumber' in dev.pluginProps:
				zone = int(dev.pluginProps['zoneNumber'])
				if zone in list(self.zoneList.keys()):
					del self.zoneList[zone]
				#self.logger.debug(f"ZoneList is now: {self.zoneList}")

		elif dev.deviceTypeId == 'alarmKeypad':
			if 'partitionNumber' in dev.pluginProps:
				keyp = int(dev.pluginProps['partitionNumber'])
				if keyp in self.keypadList:
					del self.keypadList[keyp]

		elif dev.deviceTypeId == 'alarmTemp':
			if 'sensorNumber' in dev.pluginProps:
				tmp = int(dev.pluginProps['sensorNumber'])
				if tmp in self.tempList:
					del self.tempList[int(dev.pluginProps['sensorNumber'])]

		self.logger.threaddebug("exiting deviceStopComm -->>")


	######################################################################################
	# Indigo Trigger Start/Stop
	######################################################################################

	def triggerStartProcessing(self, trigger):
		self.logger.threaddebug(f"<<-- entering triggerStartProcessing: {trigger.name} ({trigger.id})")
		self.triggerList.append(trigger.id)
		self.logger.threaddebug("exiting triggerStartProcessing -->>")

	def triggerStopProcessing(self, trigger):
		self.logger.threaddebug(f"<<-- entering triggerStopProcessing: {trigger.name} ({trigger.id})")
		if trigger.id in self.triggerList:
			self.logger.threaddebug("TRIGGER FOUND")
			self.triggerList.remove(trigger.id)
		self.logger.threaddebug("exiting triggerStopProcessing -->>")


	######################################################################################
	# Indigo Trigger Firing
	######################################################################################

	def triggerEvent(self, eventId):
		self.logger.threaddebug(f"<<-- entering triggerEvent: {eventId} ")
		for trigId in self.triggerList:
			trigger = indigo.triggers[trigId]
			if trigger.pluginTypeId == eventId:
				indigo.trigger.execute(trigger)
		return


	######################################################################################
	# Indigo Action Methods
	######################################################################################
	#These are partition specific commands, except global and panic alarms.

	def methodDisarmAlarm(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		self.logger.info(f"Disarming Alarm. (Partition {keyp} '{keypname}')")
		#tx = f"040{keyp}{self.pluginPrefs['code']:0<6}"
		tx = f"040{keyp}{self.pluginPrefs['code']}"
		self.txCmdList.append((kCmdNormal, tx))


	def methodArmStay(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		self.logger.info(f"Arming Alarm in Stay Mode. (Partition {keyp} '{keypname}')")
		self.txCmdList.append((kCmdNormal, '031' + keyp))


	def methodArmAway(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		self.logger.info(f"Arming Alarm in Away Mode. (Partition {keyp} '{keypname}')")
		self.txCmdList.append((kCmdNormal, '030' + keyp))


	def methodArmStayForce(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keypname = f" '{keypname}'"
		keyp = dev.pluginProps["partitionNumber"]
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if keypstate in (kAlarmStateArmedStay, kAlarmStateArmedAway):
			self.logger.warning("The Selected Partition is Already Armed.")
			return
		tx = f"071{keyp}*1" #starts bypass mode
		self.txCmdList.append((kCmdNormal, tx))
		self.sleep(1.25) #increase delay if keybus buffer overruns			
		if keyp != "1": #this sets all zones to nobypass if they are in partition 2-8, since those partitions do not report zone bypass status
			tx = f"071{keyp}00"  #cancels all zone bypass for this partition
			self.logger.debug("We have partition 2-8 and will cancel all bypass")
			self.txCmdList.append((kCmdNormal, tx))
			self.sleep(1.25) #increase delay if keybus buffer overruns
		for zoneNum in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneNum]]
			zonePartition = zone.pluginProps['zonePartition']
			if zone.states['state.open'] is True and zone.states['bypass'] == kZoneBypassNo and zonePartition == keyp:
				self.logger.info(f"Bypassing Zone '{zone.name}' in Partition {keyp}{keypname}.")
				zoneNum = str(zoneNum).zfill(2)
				tx = f"071{keyp}{zoneNum}"
				self.txCmdList.append((kCmdNormal, tx))
				self.sleep(1.25) #increase delay if keybus buffer overruns
		tx = f"071{keyp}1#" #ends bypass mode
		self.txCmdList.append((kCmdNormal, tx))
		self.sleep(1.5) #increase delay if keybus buffer overruns				
		self.logger.info(f"Arming Alarm in Forced Stay Mode. (Partition {keyp}{keypname})")
		self.txCmdList.append((kCmdNormal, '031' + keyp))


	def methodArmAwayForce(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '{keypname}'"
		keyp = dev.pluginProps["partitionNumber"]
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if keypstate in (kAlarmStateArmedStay, kAlarmStateArmedAway):
			self.logger.warning("The Selected Partition is Already Armed.")
			return
		tx = f"071{keyp}*1" #starts bypass mode
		self.txCmdList.append((kCmdNormal, tx))
		self.sleep(1.25) #increase delay if keybus buffer overruns			
		if keyp != "1": #this sets all zones to nobypass if they are in partition 2-8, since those partitions do not report zone bypass status
			tx = f"071{keyp}00"  #cancels all zone bypass for this partition
			self.logger.debug("We have partition 2-8 and will cancel all bypass")
			self.txCmdList.append((kCmdNormal, tx))
			self.sleep(1.25) #increase delay if keybus buffer overruns
		for zoneNum in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneNum]]
			zonePartition = zone.pluginProps['zonePartition']
			if zone.states['state.open'] is True and zone.states['bypass'] == kZoneBypassNo and zonePartition == keyp:
				self.logger.info(f"Bypassing Zone '{zone.name}' in Partition {keyp}{keypname}.")
				zoneNum = str(zoneNum).zfill(2)
				tx = f"071{keyp}{zoneNum}"
				self.txCmdList.append((kCmdNormal, tx))
				self.sleep(1.25) #increase delay if keybus buffer overruns
		tx = f"071{keyp}1#" #ends bypass mode
		self.txCmdList.append((kCmdNormal, tx))
		self.sleep(1.5) #increase delay if keybus buffer overruns				
		self.logger.info(f"Arming Alarm in Forced Away Mode. (Partition {keyp}{keypname})")
		self.txCmdList.append((kCmdNormal, '030' + keyp))


	def methodArmGlobal(self, action):
		#this action arms all defined partitions in away mode.
		self.logger.info("Arming Alarm in Global Mode (All Partitions).")
		for i in range(1, 9):
			if i in list(self.keypadList.keys()):
				key = str(i)
				self.txCmdList.append((kCmdNormal, '030' + key))
				self.sleep(1)


	def methodPanicAlarm(self, action):
		panicType = action.props['panicAlarmType']
		self.logger.info(f"Activating Panic Alarm! ({kPanicTypeList[int(panicType)]})")
		self.txCmdList.append((kCmdNormal, '060' + panicType))


	def methodSendKeypress070(self, action):
		self.logger.debug("Received Send Keypress 070 Action")
		keys = action.props['keys']
		firstChar = True
		sendBreak = False
		for char in keys:
			if char == 'L':
				self.sleep(2)
				sendBreak = False

			if firstChar is False:
				self.txCmdList.append((kCmdNormal, '070^'))

			if char != 'L':
				self.txCmdList.append((kCmdNormal, '070' + char))
				sendBreak = True

			firstChar = False
		if sendBreak is True:
			self.txCmdList.append((kCmdNormal, '070^'))


	def methodSendKeypress071(self, action, dev):
		keypname = f" '{str(dev.pluginProps['partitionName'])}' "
		keyp = dev.pluginProps["partitionNumber"]
		keys = action.props['keys']
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		self.logger.info(f"Received Send Keypress Action [{keys}]. (Partition {keyp}{keypname})")
		cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
		if len(keys) != len(cleanKeys) or "*8" in keys:
			self.logger.warning("There are Invalid Keys in your Command.")
			return
		if len(keys) > 6:
			self.logger.warning("The Key Command is too long.")
			return
		tx = f"071{keyp}{keys}"
		self.txCmdList.append((kCmdNormal, tx))


	def methodSendKeypressVariable(self, action):
		keys = indigo.variables["DSC_Command"]
		keys = keys.value
		self.logger.info(f"Received Send Keypress Action [{keys}].")
		cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if len(keys) != len(cleanKeys) or "*8" in keys:
			self.logger.warning("There are Invalid Keys in your DSCcommand Variable.")
			return
		if len(keys) > 7:
			self.logger.warning("The Key Command is too long.")
			return
		if keys[0] < "0" or keys[0] > "8":
			self.logger.warning("The First Character in your DSCcommand Needs to be a Valid Partition (1-8).")
		else:
			self.txCmdList.append((kCmdNormal, '071' + keys))


	def methodBypassZone(self, action, dev):
		key = dev.pluginProps["zoneNumber"]
		keyp = dev.pluginProps["zonePartition"]
		zone = indigo.devices[self.zoneList[int(key)]]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = f" '{str(dev.pluginProps['partitionName'])}'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if keypstate in (kAlarmStateArmedStay, kAlarmStateArmedAway):
			self.logger.warning(f"The Selected Zone '{zone.name}' is Armed and Cannot be Bypassed.")
			return
		self.logger.info(f"Received Zone Bypass Action for Zone '{zone.name}' in Partition {keyp}{keypname}.")
		key = str(key).zfill(2)
		tx = f"071{keyp}*1{key}#"
		self.txCmdList.append((kCmdNormal, tx))
		#This is a toggle action, i.e. already bypassed zones will turn to non-bypassed state.
		#Zones in partition 2-8 do not report bypass status, therefore there will be no zone state update.


	def methodBypassZoneCancel(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = f" '{str(dev.pluginProps['partitionName'])}'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if keypstate in (kAlarmStateArmedStay, kAlarmStateArmedAway):
			self.logger.warning(f"The Selected Partition {keyp}{keypname} is Armed and Cannot Accept Bypass Cancel.")
			return
		self.logger.info(f"Received All Zones Bypass Cancel for Partition {keyp}{keypname}.")
		tx = f"071{keyp}*100#"
		self.txCmdList.append((kCmdNormal, tx))


	def methodBypassZoneRecall(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = f" '{str(dev.pluginProps['partitionName'])}'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		if keypstate in (kAlarmStateArmedStay, kAlarmStateArmedAway):
			self.logger.warning(f"The Selected Partition {keyp}{keypname} is Armed and Cannot Accept Bypass Recall.")
			return
		self.logger.info(f"Received Zone(s) Bypass Recall for Partition {keyp}{keypname}.")
		tx = f"071{keyp}*199#"
		self.txCmdList.append((kCmdNormal, tx))


	def methodDoorChimeEnable(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = f" '{str(dev.pluginProps['partitionName'])}'"
		keypstate = str(dev.states['KeypadChime'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		self.logger.info(f"Received Keypad Chime Enable for Partition {keyp}{keypname}.")
		if keypstate != kKeypadStateChimeEnabled:
			tx = f"071{keyp}*4"
			self.txCmdList.append((kCmdNormal, tx))
			return


	def methodDoorChimeDisable(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = f" '{str(dev.pluginProps['partitionName'])}'"
		keypstate = str(dev.states['KeypadChime'])
		if self.useSerial is True:
			self.logger.error("This Action does not work with IT-100.")
			return
		self.logger.info(f"Received Keypad Chime Disable for Partition {keyp}{keypname}.")
		if keypstate == kKeypadStateChimeEnabled:
			tx = f"071{keyp}*4"
			self.txCmdList.append((kCmdNormal, tx))
			return


	def methodSyncTime(self, action):
		d = datetime.now()
		self.logger.info("Setting alarm panel time and date.")
		self.txCmdList.append((kCmdNormal, f"010{d.strftime('%H%M%m%d%y')}"))


    # Queue a command to set DSC Thermostat Setpoints
	#
	def methodAdjustThermostat(self, action):
		self.logger.debug(f"Device {action}:")
		self.txCmdList.append((kCmdThermoSet, action))


	# The command queued above calls this routine to create the packet
	#
	def setThermostat(self, action):
		#find this thermostat in our list to get the number
		for sensorNum in self.tempList.keys():
			if self.tempList[sensorNum].id == action.deviceId:
				break

		self.logger.debug(f"SensorNum = {sensorNum}")

		#send 095 for thermostat in question, wait for 563 response
		#self.logger.debug('095' + str(sensorNum))
		rx = self.sendPacket('095' + str(sensorNum), waitFor='563')
		if not rx:
			self.logger.error("Error getting current thermostat setpoints, aborting adjustment.")
			return

		if (action.props['thermoAdjustmentType'] == '+') or (action.props['thermoAdjustmentType'] == '-'):
			sp = 0
		else:
			sp = int(action.props['thermoSetPoint'])

		# then 096TC+000 to inc cool,
		#      096Th-000 to dec heat
		#      096Th=### to set setpoint
		# wait for 563 response
		#self.logger.debug('096%u%c%c%03u' % (sensorNum, action.props['thermoAdjustWhich'], action.props['thermoAdjustmentType'],sp) )
		rx = self.sendPacket('096%u%c%c%03u' % (sensorNum, action.props['thermoAdjustWhich'], action.props['thermoAdjustmentType'], sp), waitFor='563')
		if not rx:
			self.logger.error("Error changing thermostat setpoints, aborting adjustment.")
			return

		# send 097T
		#send 097 for thermostat in question to save setting, wait for 563 response
		rx = self.sendPacket('097' + str(sensorNum), waitFor='563')
		if not rx:
			self.logger.error("Error saving thermostat setpoints, aborting adjustment.")
			return


	# Reset an Alarm Zone Group's timer to 0
	#
	def methodResetZoneGroupTimer(self, action):
		if action.deviceId in indigo.devices:
			zoneGrp = indigo.devices[action.deviceId]
			self.logger.debug(f"Manual timer reset for alarm zone group \"{zoneGrp.name}\"")
			zoneGrp.updateStateOnServer(key="AnyMemberLastChangedTimer", value=0)
			zoneGrp.updateStateOnServer(key="EntireGroupLastChangedTimer", value=0)
			zoneGrp.updateStateOnServer(key="AnyMemberLastChangedShort", value="0m")
			zoneGrp.updateStateOnServer(key="EntireGroupLastChangedShort", value="0m")


	######################################################################################
	# Indigo Pref UI Methods
	######################################################################################

	# Validate the pluginConfig window after user hits OK
	# Returns False on failure, True on success
	#
	def validatePrefsConfigUi(self, valuesDict):
		self.logger.debug("validating Prefs called")
		errorMsgDict = indigo.Dict()
		wasError = False

		if valuesDict['configInterface'] == 'serial':
			if not (valuesDict['serialPort']):
				errorMsgDict['serialPort'] = "Select a valid serial port."
				wasError = True
		else:
			if not (valuesDict['TwoDS_Address']):
				errorMsgDict['TwoDS_Address'] = "Enter a valid IP address or host name."
				wasError = True
			if not (valuesDict['TwoDS_Port'].isdigit()):
				errorMsgDict['TwoDS_Port'] = "Enter a valid port number, default 4025."
				wasError = True
			elif not 0 < int(float(valuesDict['TwoDS_Port'])) < 65536:
				errorMsgDict['TwoDS_Port'] = "Enter a valid port number, default 4025."
				wasError = True
			if not (valuesDict['TwoDS_Password']):
				errorMsgDict['TwoDS_Password'] = "Enter the password for the Envisalink."
				wasError = True

		if not (valuesDict['code'].isdigit()):
			errorMsgDict['code'] = "The access code must numerical."
			wasError = True
			
		if not 3 < len(valuesDict['code']) < 7:
			errorMsgDict['code'] = "The access code must be 4-6 digits."
			wasError = True

		if int(float(valuesDict['code'])) == 0:
			errorMsgDict['code'] = "The access code cannot be 0000."
			wasError = True

		if not (valuesDict['code']):
			errorMsgDict['code'] = "You must enter the alarm's arm/disarm code."
			wasError = True

		if (valuesDict['emailUrgent']):
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict['emailUrgent']):
				errorMsgDict['emailUrgent'] = "Please enter a valid email address."
				wasError = True

		if (valuesDict['emailNotice']):
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict['emailNotice']):
				errorMsgDict['emailNotice'] = "Please enter a valid email address."
				wasError = True

		if (valuesDict['EmailDisarm']):
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict['EmailDisarm']):
				errorMsgDict['EmailDisarm'] = "Please enter a valid email address."
				wasError = True

		userCodeList = valuesDict['userCode'].split(",")
		userLabelList = valuesDict['userLabel'].split(",")
		newuserCodeList = [s for s in userCodeList if s.isdigit()]   #transfers only numbers to newUserCodeList
		length = len(userCodeList)

		if newuserCodeList and (any(len(lst) != length for lst in [newuserCodeList])):
			errorMsgDict['userCode'] = "Config Error: The user code contains invalid characters (2-digit numbers only)."
			wasError = True

		if any(len(lst) != length for lst in [userLabelList]):
			errorMsgDict['userCode'] = "Config Error: The user code and label lists are not of the same length."
			errorMsgDict['userLabel'] = "Config Error: The user code and label lists are not of the same length."
			wasError = True

		if len(userCodeList) != len(set(userCodeList)):
			errorMsgDict['userCode'] = "Config Error: The user code list contains duplicate codes."
			wasError = True

		for key in newuserCodeList:
			if int(key) < 1 or int(key) > 40:
				errorMsgDict['userCode'] = "Config Error: The user code is out of bound."
				wasError = True


		if wasError is True:
			return (False, valuesDict, errorMsgDict)

		# Tell DSC module to reread it's config
		self.configRead = False

		# User choices look good, so return True (client will then close the dialog window).
		return (True, valuesDict)

	def validateActionConfigUi(self, valuesDict, typeId, actionId):
		self.logger.debug("validating Action Config called")
		if typeId == 'actionSendKeypress':
			keys = valuesDict['keys']
			cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
			if len(keys) != len(cleanKeys) or "*8" in keys:
				errorMsgDict = indigo.Dict()
				errorMsgDict['keys'] = "There are invalid keys in your keystring."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)

	def validateEventConfigUi(self, valuesDict, typeId, eventId):
		self.logger.debug("validating Event Config called")
		#self.logger.debug(f"Type: {typeID}, Id: {eventID}, Dict: {valuesDict}")
		if typeId == 'userArmed' or typeId == 'userDisarmed':
			code = valuesDict['userCode']
			if len(code) != 2:
				errorMsgDict = indigo.Dict()
				errorMsgDict['userCode'] = "The user code must be 2 digits in length."
				return (False, valuesDict, errorMsgDict)

			cleanCode = re.sub(r'[^0-9]+', '', code)
			if len(code) != len(cleanCode):
				errorMsgDict = indigo.Dict()
				errorMsgDict['userCode'] = "The code can only contain digits 0-9."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)

	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		self.logger.debug("validating Device Config called")
		#self.logger.debug(f"Type: {typeID}, Id: {eventID}, Dict: {valuesDict}")
		if typeId == 'alarmZone':
			zoneNum = int(valuesDict['zoneNumber'])
			if zoneNum in list(self.zoneList.keys()) and devId != indigo.devices[self.zoneList[zoneNum]].id:
				#self.logger.debug("ZONEID: {self.DSC.zoneList[zone].id}")
				errorMsgDict = indigo.Dict()
				errorMsgDict['zoneNumber'] = "This zone has already been assigned to a different device."
				return (False, valuesDict, errorMsgDict)
		if typeId == 'alarmKeypad':
			partitionNum = int(valuesDict['partitionNumber'])
			if partitionNum in list(self.keypadList.keys()) and devId != indigo.devices[self.keypadList[partitionNum]].id:
				errorMsgDict = indigo.Dict()
				errorMsgDict['partitionNumber'] = "This partition has already been assigned to a different device."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)

	def getZoneList(self, filter="", valuesDict=None, typeId="", targetId=0):
		myArray = []
		for i in range(1, 65):
			zoneName = str(i)
			if i in list(self.zoneList.keys()):
				zoneDev = indigo.devices[self.zoneList[i]]
				zoneName = f"{str(i)} - {zoneDev.name}"
			myArray.append((str(i), zoneName))
		return myArray

	def getZoneDevices(self, filter="", valuesDict=None, typeId="", targetId=0):
		myArray = []

		for dev in indigo.devices:
			try:
				if dev.deviceTypeId == 'alarmZone':
					myArray.append((dev.id, dev.name))
			except:
				pass
		return myArray

	def getKeypadList(self, filter="", valuesDict=None, typeId="", targetId=0):
		myArray = []
		for i in range(1, 9):
			keypadName = str(i)
			if i in list(self.keypadList.keys()):
				keypDev = indigo.devices[self.keypadList[i]]
				keypadName = str(keypDev.pluginProps['partitionName'])
				keypadName = f"{str(i)} - {keypadName}"
			myArray.append((str(i), keypadName))
		return myArray


	######################################################################################
	# Configuration Routines
	######################################################################################

	# Reads the plugins config file into our own variables. 
	# Section is read automatically at every startup of plugin.
	#
	def getConfiguration(self, valuesDict):
		
		try:

			# Tell our logging class to reread the config for logging level changes
			self.logLevel = int(self.pluginPrefs.get("logLevel",20))  #new routine
			self.indigo_log_handler.setLevel(self.logLevel)  #new routine
			self.logger.debug(f"getConfiguration start. Log Levels are set to \"{kLogLevelList[int(self.logLevel/10)]}\".")
			#self.logger.debug(f"getConfiguration start. Log Levels are set to \"{valuesDict.get('logLevel',20)}\".")
		
			# Setting log level of private plugin log handler to only log threaddebug events if this is the setting in logging preferences.
			# Normally, the private log handler always logs threaddebug, which can fill up the log quite a lot.
			if self.logLevel == 5:
				self.plugin_file_handler.setLevel(logging.THREADDEBUG)
				self.logger.debug("Private Log Handler set to THREADDEBUG")
			else:
				self.plugin_file_handler.setLevel(logging.DEBUG)
				self.logger.debug("Private Log Handler set to DEBUG")

			# Get setting of Create Variables checkbox
			if valuesDict.get('createVariables', False) is True:
				self.createVariables = True
			else:
				self.createVariables = False

			# If the variable folder doesn't exist, disable variables, we're done!
			if valuesDict.get('variableFolder') not in indigo.variables.folders:
				self.createVariables = False

			self.useSerial = False
			if valuesDict.get('configInterface', 'twods') == 'serial':
				# using older serial port interface IT-100 or similar
				self.useSerial = True

			self.configKeepTimeSynced = valuesDict.get('syncTime', True)
			self.configUseCustomIcons = valuesDict.get('customStateIcons', True)

			self.configSpeakVariable = None
			if 'speakToVariableEnabled' in valuesDict:
				if valuesDict['speakToVariableEnabled'] is True:
					self.configSpeakVariable = int(valuesDict['speakToVariableId'])
					if self.configSpeakVariable not in indigo.variables:
						self.logger.error("Speak variable not found in variable list")
						self.configSpeakVariable = None

			self.configEmailUrgent = valuesDict.get('emailUrgent', '')
			self.configEmailNotice = valuesDict.get('emailNotice', '')
			self.configEmailDisarm = valuesDict.get('EmailDisarm', '')
			self.configEmailUrgentSubject = valuesDict.get('emailUrgentSubject', 'Alarm Tripped')
			self.configEmailNoticeSubject = valuesDict.get('emailNoticeSubject', 'Alarm Trouble')
			self.configEmailDisarmSubject = valuesDict.get('DisarmEmailSubject', 'Who Disarmed')

			self.userCodeList = valuesDict.get('userCode', '').split(",")
			self.userLabelList = valuesDict.get('userLabel', '').split(",")
			self.userLabelDict = dict(list(zip(self.userCodeList, self.userLabelList)))

			self.logger.debug("Configuration read successfully")

			return True

		except:
			self.logger.warning("Error reading plugin configuration. Happens on very first launch! Open plugin configuration, review settings and save.")

			return False


	######################################################################################
	# Communication Routines
	######################################################################################

	def calcChecksum(self, s):
		calcSum = 0
		for c in s:
			calcSum += ord(c)
		calcSum %= 256
		return calcSum

	def closePort(self):
		if self.port is None:
			return
		if self.port.isOpen() is True:
			self.port.close()
			self.port = None

	def openPort(self):
		self.closePort()
		if self.useSerial is False:
			#adr = self.pluginPrefs['TwoDS_Address'] + ':4025'
			adr = f"{self.pluginPrefs['TwoDS_Address']}:{int(float(self.pluginPrefs['TwoDS_Port']))}"
			self.logger.info(f"Initializing communication at address: {adr}")
			try:
				self.port = serial.serial_for_url('socket://' + adr, baudrate=115200)
			except Exception as err:
				self.logger.error(f"Error opening socket: {str(err)}")
				return False
		else:
			self.logger.info(f"Initializing communication on port {self.pluginPrefs['serialPort']}")
			try:
				self.port = serial.Serial(self.pluginPrefs['serialPort'], 9600, writeTimeout=1)
			except Exception as err:
				self.logger.error(f"Error opening serial port: {str(err)}")
				return False

		if self.port.isOpen() is True:
			self.port.flushInput()
			self.port.timeout = 1
			self.logger.info("Communication established")
			return True

		return False


	def readPort(self):
		if self.port.isOpen() is False:
			self.state = self.States.BOTH_INIT
			return ""

		data = ""
		try:
			data = self.port.readline()
		except Exception as err:
			self.logger.error(f"Connection RX Error: {str(err)}")
			data = '-'.encode('utf-8')   #encode in bytes to be compatible with how data are received from serial port
		except:
			self.logger.error("Connection RX Problem, DSC plugin is quitting")
			exit()
		return data


	def writePort(self, data):
		self.port.write(data)


	def sendPacketOnly(self, data):
		pkt = "{}{:02X}\r\n".format(data, self.calcChecksum(data))
		self.logger.threaddebug(f"TX: {pkt}")
		try:
			#All data is send as two-digit hex ASCII codes.
			self.writePort(pkt.encode("utf-8"))
		except Exception as err:
			self.logger.error(f"Connection TX Error: {str(err)}")
			exit()
		except:
			self.logger.error("Connection TX Problem, DSC plugin is quitting")
			exit()


	def sendPacket(self, tx, waitFor='500', rxTimeout=3, txRetries=3):
		retries = txRetries
		txCmd = tx[:3]

		while txRetries > 0:
			self.sendPacketOnly(tx)
			ourTimeout = time.time() + rxTimeout
			txRetries -= 1
			while time.time() < ourTimeout:
				if self.shutdown is True:
					return ''
				(rxCmd, rxData) = self.readPacket()

				# If rxCmd == - then the socket closed, return for re-init
				if rxCmd == '-':
					return '-'

				if rxCmd == '502':
					self.logger.error("Received system error/warning after sending command, aborting.")
					return ''

				# If rxCmd is not 0 length then we received a response
				if rxCmd:
					if waitFor == '500':
						if (rxCmd == '500') and (rxData == txCmd):
							return rxData
					elif rxCmd == waitFor:
						return rxData
			if txCmd != '000':
				self.logger.error(f"Timed out after waiting for response to command {tx} for {rxTimeout} seconds, retrying.")
		self.logger.error(f"Resent command {tx} {retries} times with no success, aborting.")
		return ''


	def readPacket(self):

		data = self.readPort()
		data = data.decode("utf-8")
		if not data:
			return ('', '')
		elif data == '-':
			self.logger.debug("Socket has closed")
			# socket has closed, return with signal to re-initialize
			return ('-', '')

		data = data.strip()

		m = re.search(r'^(...)(.*)(..)$', data)
		if not m:
			return ('', '')

		# This try block catches exceptions when non-ascii characters were received. 
		# Not sure why they are being received.
		try:
			self.logger.threaddebug(f"RX: {data}")
			(cmd, dat, sum) = (m.group(1), m.group(2), int(m.group(3), 16))
		except:
			self.logger.error("IT-100/Envisalink Error: Received a response with invalid characters")
			return ('', '')

		if sum != self.calcChecksum("".join([cmd, dat])):
			self.logger.error("Checksum did not match on a received packet.")
			return ('', '')

		##################################################################################
		# Parse responses based on cmd value received from panel
		##################################################################################

		if cmd == '500':
			self.logger.threaddebug(f"ACK for cmd {dat}.")
			self.cmdAck = dat

		elif cmd == '501':
			self.logger.error("IT-100/Envisalink Error: Received a command with a bad checksum")

		elif cmd == '502':
			errText = 'Unknown'

			if dat == '001':
				errText = 'Receive Buffer Overrun (a command is received while another is still being processed)'
			elif dat == '002':
				errText = 'Receive Buffer Overflow'
			elif dat == '003':
				errText = 'Transmit Buffer Overflow'

			elif dat == '010':
				errText = 'Keybus Transmit Buffer Overrun'
			elif dat == '011':
				errText = 'Keybus Transmit Time Timeout'
			elif dat == '012':
				errText = 'Keybus Transmit Mode Timeout'
			elif dat == '013':
				errText = 'Keybus Transmit Keystring Timeout'
				# this error is sometimes received after disarming a tripped partition with TPI disarm command 040
			elif dat == '014':
				errText = 'Keybus Interface Not Functioning (the TPI cannot communicate with the security system)'
			elif dat == '015':
				errText = 'Keybus Busy (Attempting to Disarm or Arm with user code)'
			elif dat == '016':
				errText = 'Keybus Busy – Lockout (The panel is currently in Keypad Lockout – too many disarm attempts)'
			elif dat == '017':
				errText = 'Keybus Busy – Installers Mode (Panel is in installers mode, most functions are unavailable)'
			elif dat == '018':
				errText = 'Keybus Busy – General Busy (The requested partition is busy)'

			elif dat == '020':
				errText = 'API Command Syntax Error'
			elif dat == '021':
				errText = 'API Command Partition Error (Requested Partition is out of bounds)'
			elif dat == '022':
				errText = 'API Command Not Supported'
			elif dat == '023':
				errText = 'API System Not Armed (sent in response to a disarm command)'
			elif dat == '024':
				errText = 'API System Not Ready to Arm (not secure, in delay, or already armed)'
				self.triggerEvent('eventFailToArm')
				self.speak('speakTextFailedToArm')
			elif dat == '025':
				errText = 'API Command Invalid Length'
			elif dat == '026':
				errText = 'API User Code not Required'
			elif dat == '027':
				errText = 'API Invalid Characters in Command'

			if dat in {'023', '024'}:
				self.logger.warning(f"IT-100/Envisalink Warning ({dat}): {errText}")
			else:
				self.logger.error(f"IT-100/Envisalink Error ({dat}): {errText}")

		elif cmd == '505':
			if dat == '3':
				self.logger.debug("Received login request")

		elif cmd == '510':
			# Keypad LED State Updates for Partition 1 only
			leds = int(dat, 16)

			if leds & 1 > 0:
				self.updateKeypad(1, 'LEDReady', 'on')
			else:
				self.updateKeypad(1, 'LEDReady', 'off')

			if leds & 2 > 0:
				self.updateKeypad(1, 'LEDArmed', 'on')
			else:
				self.updateKeypad(1, 'LEDArmed', 'off')

			if leds & 16 > 0:
				self.updateKeypad(1, 'LEDTrouble', 'on')
			else:
				self.updateKeypad(1, 'LEDTrouble', 'off')

			if leds & 4 > 0:
				self.updateKeypad(1, 'LEDMemory', 'on')
			else:
				self.updateKeypad(1, 'LEDMemory', 'off')

			if leds & 8 > 0:
				self.updateKeypad(1, 'LEDBypass', 'on')
			else:
				self.updateKeypad(1, 'LEDBypass', 'off')

		elif cmd == '511':
			# Keypad LED Flashing State Update
			# Same as 510 above but means an LED is flashing
			# We don't use this right now
			pass

		elif cmd == '550':
			# This command is send by DSC panel every 4 min
			m = re.search(r'^(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)$', dat)
			if m:
				tHour = m.group(1).zfill(2)   #padding str objects to two digits
				tMin = m.group(2).zfill(2)
				dMonth = m.group(3).zfill(2)
				dMonthDay = m.group(4).zfill(2)
				dYear = m.group(5)
				self.logger.debug(f"Received alarm panel time and date {tHour}:{tMin} {dMonth}-{dMonthDay}-{dYear}")

				if self.configKeepTimeSynced is True:
					# Is it around 3 am and the time has not recently been synced?
					d = datetime.now()
					if self.timesyncflag is True and (d.hour == 3) and (d.minute in range(0, 6)):
						self.logger.debug("Syncing alarm panel time and date.")
						self.txCmdList.append((kCmdNormal, f"010{d.strftime('%H%M%m%d%y')}"))
						self.timesyncflag = False
					else:
						self.timesyncflag = True
						self.logger.debug("No time sync necessary.")

				# If this is a 2DS/Envisalink interface then lets insert the time in the virtual keypad 
				# Time is updated only every 4 minutes, so not very useful to use
				if self.useSerial is False:
					tAmPm = 'a'
					tHour = int(tHour)
					if tHour >= 12:
						tAmPm = 'p'

					if tHour > 12:
						tHour -= 12
					elif tHour == 0:
						tHour = 12
					str(tHour).zfill(2)
					self.updateKeypad(0, 'LCDLine1', '  Date     Time ')
					self.updateKeypad(0, 'LCDLine2', f"{kMonthList[int(dMonth)-1]} {dMonthDay}/{dYear} {tHour}:{tMin}{tAmPm}")
					self.logger.debug(f"{kMonthList[int(dMonth)-1]} {dMonthDay}/{dYear} {tHour}:{tMin}{tAmPm}")

		elif cmd == '560':
			self.logger.info("Telephone Ring Tone Has Been Detected.")
			for trig in self.triggerList:
				trigger = indigo.triggers[trig]
				if trigger.pluginTypeId == 'eventNoticeTelephone_Ring':
					indigo.trigger.execute(trigger.id)

		elif cmd == '561' or cmd == '562':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(sensor, temp) = (int(m.group(1)), int(m.group(2)))
				if cmd == '562':
					self.updateSensorTemp(sensor, 'outside', temp)
				else:
					self.updateSensorTemp(sensor, 'inside', temp)

		elif cmd == '563':
			m = re.search(r'^(.)(...)(...)$', dat)
			if m:
				(sensor, cool, heat) = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
				self.updateSensorTemp(sensor, 'cool', cool)
				self.updateSensorTemp(sensor, 'heat', heat)

		elif cmd == '601':
			# a zone goes into alarm/is tripped
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.updateZoneState(zone, kZoneStateTripped)
				if zone in list(self.zoneList.keys()) and self.configUseCustomIcons is True:
					dev = indigo.devices[self.zoneList[zone]]
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)

				if not (self.trippedZoneList):
					if "DSC_Alarm_Memory" in indigo.variables:
						indigo.variable.updateValue("DSC_Alarm_Memory", value="")
				if zone not in self.trippedZoneList:
					self.trippedZoneList.append(zone)
					self.sendZoneTrippedEmail()
					indigoVar = ""
					for zoneNum in self.trippedZoneList:
						zone = indigo.devices[self.zoneList[zoneNum]]
						indigoVar += (zone.name + "; ")
					if "DSC_Alarm_Memory" in indigo.variables:
						indigo.variable.updateValue("DSC_Alarm_Memory", indigoVar)
					self.triggerEvent('eventZoneTripped')

		elif cmd == '602':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				dev = indigo.devices[self.keypadList[partition]]
				zonedev = indigo.devices[self.zoneList[zone]]
				keyp = str(dev.pluginProps['partitionName'])
				self.logger.info(f"Zone '{zonedev.name}' Restored. (Partition {partition} '{keyp}')")

		elif cmd == '603':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.logger.debug(f"Zone Number {zone} Has a Tamper Condition.")

		elif cmd == '604':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.logger.debug(f"Zone Number {zone} Tamper Condition has been Restored.")

		elif cmd == '605':
			zone = int(dat)
			self.logger.debug(f"Zone Number {zone} Has a Fault Condition.".format(zone))

		elif cmd == '606':
			zone = int(dat)
			self.logger.debug(f"Zone Number {zone} Fault Condition has been Restored.".format(zone))

		elif cmd == '609':
			zone = int(dat)
			self.logger.debug(f"Zone Number {zone} Open.".format(zone))
			self.updateZoneState(zone, kZoneStateOpen)
			if self.repeatAlarmTripped is True:
				if zone in self.closeTheseZonesList:
					self.closeTheseZonesList.remove(zone)

			# Custom state image icons are shown in Indigo Touch and Indigo Client UI if selected in Config Prefs.
			# Not all icons are working yet in Indigo. Feel free to change icons to your liking.
			if zone in list(self.zoneList.keys()) and self.configUseCustomIcons is True:
				self.logger.debug("We are using custom state icons.")
				dev = indigo.devices[self.zoneList[zone]]
				zoneType = dev.pluginProps['zoneType']
				if zoneType == "zoneTypeMotion":
					dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensorTripped)
				elif zoneType == "zoneTypeDoor":
					dev.updateStateImageOnServer(indigo.kStateImageSel.DoorSensorOpened)
				elif zoneType == "zoneTypeWindow":
					dev.updateStateImageOnServer(indigo.kStateImageSel.WindowSensorOpened)
				elif zoneType == "zoneTypeFire":
					dev.updateStateImageOnServer(indigo.kStateImageSel.HvacHeating)
				elif zoneType == "zoneTypeWater":
					dev.updateStateImageOnServer(indigo.kStateImageSel.SprinklerOn)
				elif zoneType == "zoneTypeGas":
					dev.updateStateImageOnServer(indigo.kStateImageSel.HvacFanOn)
				elif zoneType == "zoneTypeGlass":
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
				elif zoneType == "zoneTypeShock":
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
				elif zoneType == "zoneTypeCO":
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
				else:
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

			# This refreshes image icons after unchecking the custom settings in Config window
			if zone in list(self.zoneList.keys()) and self.configUseCustomIcons is False:
				dev = indigo.devices[self.zoneList[zone]]
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

		elif cmd == '610':
			zone = int(dat)
			self.logger.debug(f"Zone Number {zone} Closed.")
			# Update the zone to closed ONLY if the alarm is not tripped. We want the 
			# tripped states to be preserved so someone looking at their control page will 
			# see all the zones that have been opened since the break in.
			if self.repeatAlarmTripped is False:
				self.updateZoneState(zone, kZoneStateClosed)
				if zone in list(self.zoneList.keys()) and self.configUseCustomIcons is True:
					dev = indigo.devices[self.zoneList[zone]]
					zoneType = dev.pluginProps['zoneType']
					if zoneType == "zoneTypeMotion":
						dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
					else:
						dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

				# This refreshes image icons after unchecking the custom settings in Config window
				if zone in list(self.zoneList.keys()) and self.configUseCustomIcons is False:
					dev = indigo.devices[self.zoneList[zone]]
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

			else:
				self.closeTheseZonesList.append(zone)

		elif cmd == '616':
			# cmd is sent after a zone is bypassed or bypass is cancelled.
			# This dump can be forced with keypress command [1*1#] if partition is not armed. 
			# If partition is armed, it will switch armed state from stay to away and vice versa.
			# Routine that identifies bypassed zones and updates zone status kZoneBypassNo 
			# or kZoneBypassYes via newState (unfortunately for partition 1 only).
			BypassHexDump = str(dat)       #this is the 16-digit hex string for bypassed zones. Partition 1 only!
			self.logger.debug(f"Bypass Hex Dump ({BypassHexDump})")
			BBDump = format(int(BypassHexDump, 16), '0>64b')
			BypassBinaryDump = "".join(["".join([m[i:i+1] for i in range(8-1, -1, -1)]) for m in [BBDump[i:i+8] for i in range(0, len(BBDump), 8)]])
			# reordered in 8 bit words to get zones in 1-64 order
			self.logger.debug(f"Bypass Binary Dump ({BypassBinaryDump})")
			for i in range(64):
				if BypassBinaryDump[i-1] == '1':
					self.updateZoneBypass(i, kZoneBypassYes)
				elif BypassBinaryDump[i-1] == '0':
					self.updateZoneBypass(i, kZoneBypassNo)

		elif cmd == '620':
			self.logger.warning("Duress Alarm Detected")
			self.sendDuressEmail("Duress Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStateDuress)

		elif cmd == '621':
			self.logger.warning("Fire Key Alarm Detected")
			self.sendPanicEmail("Fire Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStateFire)

		elif cmd == '622':
			self.logger.info("Fire Key Alarm Restored")
			# This updates all keypads (partitions). Partitions that were Armed will stay Armed. 
			# Partitions that are "Ready for arming" will show up as Disarmed via cmd 650. 
			# Otherwise they will show up as Tripped until they become "Ready", e.g. all open windows are closed.
			self.updateKeypad(0, 'PanicState', kPanicStateNone)
			
			# After the fire alarm has been disarmed while it was tripped, update any zone states
			# that were closed during the fire alarm.  We don't update them during the event
			# so that Indigo's zone states will represent a zone as tripped during the entire event.
			if self.repeatAlarmTripped is True:
				self.repeatAlarmTripped = False
				for zone in self.closeTheseZonesList:
					self.updateZoneState(zone, kZoneStateClosed)
					if self.configUseCustomIcons is True:
						dev = indigo.devices[self.zoneList[zone]]
						zoneType = dev.pluginProps['zoneType']
						if zoneType == "zoneTypeMotion":
							dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
						else:
							dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

				self.closeTheseZonesList = []

		elif cmd == '623':
			self.logger.warning("Auxiliary/Medical Key Alarm Detected")
			self.sendPanicEmail("Ambulance/Medical Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStateAmbulance)

		elif cmd == '624':
			self.logger.info("Auxiliary/Medical Key Alarm Restored")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStateNone)

		elif cmd == '625':
			self.logger.warning("Panic/Police Key Alarm Detected")
			self.sendPanicEmail("Panic/Police Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStatePanic)

		elif cmd == '626':
			self.logger.info("Panic/Police Key Alarm Restored")
			# This updates all keypads (partitions). Partitions that were Armed will stay Armed. 
			# Partitions that are "Ready for arming" will show up as Disarmed via cmd 650. 
			# Otherwise they will show up as Tripped until they become "Ready", e.g. all open windows are closed.
			self.updateKeypad(0, 'PanicState', kPanicStateNone)

			# After the panic alarm has been disarmed while it was tripped, update any zone states
			# that were closed during the panic alarm.  We don't update them during the event
			# so that Indigo's zone states will represent a zone as tripped during the entire event.
			if self.repeatAlarmTripped is True:
				self.repeatAlarmTripped = False
				for zone in self.closeTheseZonesList:
					self.updateZoneState(zone, kZoneStateClosed)
					if self.configUseCustomIcons is True:
						dev = indigo.devices[self.zoneList[zone]]
						zoneType = dev.pluginProps['zoneType']
						if zoneType == "zoneTypeMotion":
							dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
						else:
							dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

				self.closeTheseZonesList = []
				
		elif cmd == '631':
			self.logger.warning("Auxiliary/Smoke Input Alarm Detected")
			self.updateKeypad(0, 'PanicState', kPanicStateSmoke)

		elif cmd == '632':
			self.logger.info("Auxiliary/Smoke Input Alarm Restored")
			# This updates all keypads (partitions)
			self.updateKeypad(0, 'PanicState', kPanicStateNone)

		elif cmd == '650':
			# This reports "Ready" state only for keypads i.e. partitions that are ready to arm.
			self.logger.debug(f"Partition {int(dat)} Ready")
			partition = int(dat)
			self.updateKeypad(partition, 'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, 'LEDReady', 'on')
			self.updateKeypad(partition, 'state', kAlarmStateDisarmed)

		elif cmd == '651':
			self.logger.debug(f"Partition {int(dat)} Not Ready")
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, 'LEDReady', 'off')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)   # green circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Unlocked)  # red open padlock
			else:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

		elif cmd == '652':
			if len(dat) == 1:
				partition = int(dat)
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				self.logger.debug(f"Alarm Panel Armed. (Partition {partition} '{keyp}')")
				self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
				self.updateKeypad(partition, 'LEDReady', 'off')
				self.updateKeypad(partition, 'LEDArmed', 'on')	  # updates LEDs for partitions 1-8
				self.speak('speakTextArmed')
				self.trippedZoneList = []
				if self.configUseCustomIcons is True:
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)  # red circle
					#dev.updateStateImageOnServer(indigo.kStateImageSel.Locked)  # green locked padlock
				else:
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
				

			elif len(dat) == 2:
				m = re.search(r'^(.)(.)$', dat)
				if m:
					(partition, mode) = (int(m.group(1)), int(m.group(2)))
					dev = indigo.devices[self.keypadList[partition]]
					keyp = str(dev.pluginProps['partitionName'])
					self.logger.info(f"Alarm Panel Armed in {kArmedModeList[mode]} Mode. (Partition {partition} '{keyp}')")
					if (mode == 0) or (mode == 2):
						armedEvent = 'armedAway'
						self.updateKeypad(partition, 'state', kAlarmStateArmedAway)
						self.updateKeypad(partition, 'ArmedState', kAlarmArmedStateAway)
					else:
						armedEvent = 'armedStay'
						self.updateKeypad(partition, 'state', kAlarmStateArmedStay)
						self.updateKeypad(partition, 'ArmedState', kAlarmArmedStateStay)
						self.updateKeypad(partition, 'LEDBypass', 'on')   # LED is on since motion sensors are bypassed in Stay mode

					self.triggerEvent(armedEvent)
					for trig in self.triggerList:
						trigger = indigo.triggers[trig]
						if trigger.pluginTypeId == 'eventPartitionArmed':
							if trigger.pluginProps['partitionNum'] == str(partition):
								indigo.trigger.execute(trigger.id)

					self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
					self.updateKeypad(partition, 'LEDReady', 'off')
					self.updateKeypad(partition, 'LEDArmed', 'on')	  # updates LEDs for partitions 1-8
					self.speak('speakTextArmed')
					self.trippedZoneList = []
					if self.configUseCustomIcons is True:
						dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)  # red circle
						#dev.updateStateImageOnServer(indigo.kStateImageSel.Locked)  # green locked padlock
					else:
						dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
	

		elif cmd == '653':
			# Partition Ready - Forced Arming Enabled
			# This reports ready state only for keypads i.e. partitions that are ready.
			self.logger.debug(f"Partition {int(dat)} Ready")
			partition = int(dat)
			self.updateKeypad(partition, 'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, 'LEDReady', 'on')
			self.updateKeypad(partition, 'state', kAlarmStateDisarmed)

		elif cmd == '654':
			# partition is in alarm due to zone violations or panic & fire alarm
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.warning(f"Alarm TRIPPED! (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'state', kAlarmStateTripped)
			self.updateKeypad(partition, 'LEDMemory', 'on')	  # updates LED for partitions 1-8
			self.triggerEvent('eventAlarmTripped')
			self.repeatAlarmTrippedNext = time.time()
			self.repeatAlarmTripped = True

		elif cmd == '655':
			# This command is send after user disarms an alarm that was not tripped (also see cmd 750, 751).
			# This is only disarm cmd sent if arming is cancelled during exit delay (which also cancels zone bypass)
			# If the alarm has been disarmed while it was tripped, update any zone states
			# that were closed during the break in.  We don't update them during the event
			# so that Indigo's zone states will represent a zone as tripped during the entire event.
			if self.repeatAlarmTripped is True:
				self.repeatAlarmTripped = False
				for zone in self.closeTheseZonesList:
					self.updateZoneState(zone, kZoneStateClosed)
					if self.configUseCustomIcons is True:
						dev = indigo.devices[self.zoneList[zone]]
						zoneType = dev.pluginProps['zoneType']
						if zoneType == "zoneTypeMotion":
							dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
						else:
							dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)


				self.closeTheseZonesList = []

			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			keypstate = str(dev.states['state'])
			if keypstate == kAlarmStateExitDelay:
				self.logger.info(f"Alarm Disarmed during Exit Delay. (Partition {partition} '{keyp}')")

			self.logger.debug("Bypass Cancelled for all Zones by DSC")
			for i in range(64):
				self.updateZoneBypass(i, kZoneBypassNo)

			self.trippedZoneList = []
			self.updateKeypad(partition, 'state', kAlarmStateDisarmed)
			self.updateKeypad(partition, 'ArmedState', kAlarmArmedStateDisarmed)
			self.updateKeypad(partition, 'LEDArmed', 'off')
			self.updateKeypad(0, 'PanicState', kPanicStateNone)
			self.updateKeypad(partition, 'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, 'LEDReady', 'on')
			self.updateKeypad(partition, 'LEDBypass', 'off')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)  # green circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Unlocked)  # red open padlock

			#self.triggerEvent('eventAlarmDisarmed') #use cmd 750 & 751 triggers
			#self.speak('speakTextDisarmed')  #use cmd 750 & 751 triggers


		elif cmd == '656':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Exit Delay. (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'state', kAlarmStateExitDelay)
			self.updateKeypad(partition, 'LEDArmed', 'on')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
			self.updateKeypad(partition, 'LEDMemory', 'off')
			if "DSC_Alarm_Memory" in indigo.variables:
				indigo.variable.updateValue("DSC_Alarm_Memory", value="no tripped zones")
			self.speak('speakTextArming')

		elif cmd == '657':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Entry Delay. (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'state', kAlarmStateEntryDelay)
			self.speak('speakTextEntryDelay')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)

		elif cmd == '663':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Keypad Chime Enabled. (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'KeypadChime', kKeypadStateChimeEnabled)

		elif cmd == '664':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Keypad Chime Disabled. (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'KeypadChime', kKeypadStateChimeDisabled)

		elif cmd == '672':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.warning(f"Alarm Panel Failed to Arm. (Partition {partition} '{keyp}')")
			self.triggerEvent('eventFailToArm')
			self.speak('speakTextFailedToArm')

		elif cmd == '673':
			#sends busy reply for partitions that are not defined by the plugin
			partition = int(dat)
			self.logger.debug(f"Partition {partition} Busy/Not defined by plugin.")

		elif cmd == '700':
			# A partition has been armed by a user – sent at the end of exit delay
			# No info on whether stay armed or away armed, but cmd 652 is also triggered and has this info
			m = re.search(r'^(.)..(..)$', dat)
			if m:
				(partition, user) = (int(m.group(1)), m.group(2))
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				keyu = self.userLabelDict.get(user, "")
				if keyu:
					keyu = f" '{keyu}'"
				self.logger.info(f"Alarm Panel Armed by User {user}{keyu}. (Partition {partition} '{keyp}')")
				self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
				self.updateKeypad(partition, 'LEDReady', 'off')
				self.updateKeypad(partition, 'LEDArmed', 'on')
				self.speak('speakTextArmed')
				if self.configUseCustomIcons is True:
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)  # red circle
					#dev.updateStateImageOnServer(indigo.kStateImageSel.Locked)  # green locked padlock
				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == 'userArmed':
						if trigger.pluginProps['userCode'] == user:
							indigo.trigger.execute(trigger.id)

		elif cmd == '701':
			# Special arming, e.g. IndigoTouch on iPhone, Keyswitch, etc
			# No info on whether stay armed or away armed, but cmd 652 is also triggered and has this info
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.debug(f"Alarm Panel Specially Armed. (Partition {partition} '{keyp}')")
			self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, 'LEDReady', 'off')
			self.updateKeypad(partition, 'LEDArmed', 'on')
			self.speak('speakTextArmed')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)  # red circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Locked)  # green locked padlock


		elif cmd == '702':
			# A partition has been armed but one or more zones have been bypassed
			# No info on whether stay armed or away armed, but cmd 652 is also triggered and has this info
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Alarm Panel Armed. (Partition {partition} '{keyp}' with zone(s) bypass)")
			self.updateKeypad(partition, 'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, 'LEDReady', 'off')
			self.updateKeypad(partition, 'LEDArmed', 'on')
			self.updateKeypad(partition, 'LEDBypass', 'on')
			self.speak('speakTextArmed')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)  # red circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Locked)  # green locked padlock


		elif cmd == '750':
			# this command is send after user disarms an alarm that was tripping or not tripping (vs cmd 655).
			# this command is not sent after cancelling a fire or panic/police alarm. In fact no commands are sent at all in this case.
			m = re.search(r'^(.)..(..)$', dat)
			if m:
				(partition, user) = (int(m.group(1)), m.group(2))
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				keyu = self.userLabelDict.get(user, "")
				if keyu:
					keyu = f" '{keyu}'"
				self.logger.info(f"Alarm Panel Disarmed by User {user}{keyu}. (Partition {partition} '{keyp}')")
				self.sendEmailDisarm(f"Alarm Panel Disarmed by User {user}{keyu}. (Partition {partition} '{keyp}')")
				if "DSC_Last_User_Disarm" in indigo.variables:
					indigo.variable.updateValue("DSC_Last_User_Disarm", value="User "+user+keyu)

				# self.trippedZoneList = []    # We do not want to delete list of tripped zones here
				self.updateKeypad(partition, 'state', kAlarmStateDisarmed)
				self.updateKeypad(partition, 'ArmedState', kAlarmArmedStateDisarmed)
				self.updateKeypad(partition, 'LEDArmed', 'off')
				self.updateKeypad(0, 'PanicState', kPanicStateNone)
				self.updateKeypad(partition, 'ReadyState', kReadyStateTrue)
				self.updateKeypad(partition, 'LEDReady', 'on')
				self.updateKeypad(partition, 'LEDBypass', 'off')
				self.triggerEvent('eventAlarmDisarmed')
				self.speak('speakTextDisarmed')
				if self.configUseCustomIcons is True:
					dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)   # green circle
					#dev.updateStateImageOnServer(indigo.kStateImageSel.Unlocked)  # red open padlock

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == 'userDisarmed':
						if trigger.pluginProps['userCode'] == user:
							indigo.trigger.execute(trigger.id)

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == 'userDisarmedPartition':
						if trigger.pluginProps['userCode'] == user and trigger.pluginProps['partitionNum'] == str(partition):
							indigo.trigger.execute(trigger.id)

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == 'eventPartitionDisarmed':
						if trigger.pluginProps['partitionNum'] == str(partition):
							indigo.trigger.execute(trigger.id)

			# If the alarm has been disarmed while it was tripped, update any zone states
			# that were closed during the break in.  We don't update them during the event
			# so that Indigo's zone states will represent a zone as tripped during the entire event.
			if self.repeatAlarmTripped is True:
				self.repeatAlarmTripped = False
				for zone in self.closeTheseZonesList:
					self.updateZoneState(zone, kZoneStateClosed)
					if self.configUseCustomIcons is True:
						dev = indigo.devices[self.zoneList[zone]]
						zoneType = dev.pluginProps['zoneType']
						if zoneType == "zoneTypeMotion":
							dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
						else:
							dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

				self.closeTheseZonesList = []

			#Disarming cancels all bypassed zones automatically by DSC. So just need to update plugin zone states.
			self.logger.debug("Bypass Cancelled for all Zones by DSC")
			for i in range(64):
				self.updateZoneBypass(i, kZoneBypassNo)


		elif cmd == '751':
			#special opening (triggered by keyswitch but not by Indigo Touch). A DSC/Envisalink bug seems to not send this cmd after key fob opening
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.logger.info(f"Alarm Disarmed by Special Opening (Partition {partition} '{keyp}')")
			# self.trippedZoneList = []    #We do not want to delete list of tripped zones here
			self.updateKeypad(partition, 'state', kAlarmStateDisarmed)
			self.updateKeypad(partition, 'ArmedState', kAlarmArmedStateDisarmed)
			self.updateKeypad(partition, 'LEDArmed', 'off')
			self.updateKeypad(0, 'PanicState', kPanicStateNone)
			self.updateKeypad(partition, 'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, 'LEDReady', 'on')
			self.updateKeypad(partition, 'LEDBypass', 'off')
			if self.configUseCustomIcons is True:
				dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)   # green circle
				#dev.updateStateImageOnServer(indigo.kStateImageSel.Unlocked)  # red open padlock

			self.triggerEvent('eventAlarmDisarmed')
			self.speak('speakTextDisarmed')

			for trig in self.triggerList:
				trigger = indigo.triggers[trig]
				if trigger.pluginTypeId == 'eventPartitionDisarmed':
					if trigger.pluginProps['partitionNum'] == str(partition):
						indigo.trigger.execute(trigger.id)

			#Disarming cancels all bypassed zones automatically by DSC. So just need to update plugin zone states.
			self.logger.debug("Bypass Cancelled for all Zones by DSC")
			for i in range(64):
				self.updateZoneBypass(i, kZoneBypassNo)


		elif cmd == '800':
			self.logger.warning("Alarm Panel Battery is low.")
			self.sendTroubleEmail("Alarm panel battery is low.")

		elif cmd == '801':
			self.logger.info("Alarm Panel Battery is now ok.")
			self.sendTroubleEmail("Alarm panel battery is now ok.")

		elif cmd == '802':
			self.logger.warning("AC Power Lost.")
			self.sendTroubleEmail("AC Power Lost.")
			self.triggerEvent('eventNoticeAC_Trouble')

		elif cmd == '803':
			self.logger.info("AC Power Restored.")
			self.sendTroubleEmail("AC Power Restored.")
			self.triggerEvent('eventNoticeAC_Restore')

		elif cmd == '806':
			self.logger.warning("An open circuit has been detected across the bell terminals.")
			self.sendTroubleEmail("An open circuit has been detected across the bell terminals.")

		elif cmd == '807':
			self.logger.info("The bell circuit has been restored.")
			self.sendTroubleEmail("The bell circuit has been restored.")

		elif cmd == '814':
			self.logger.warning("FTC Trouble.")
			self.sendTroubleEmail("The panel has failed to communicate successfully to the monitoring station.")

		elif cmd == '815':
			self.logger.info("FTC Trouble Restore.")
			self.sendTroubleEmail("The panel has resumed communications.")

		elif cmd == '840':
			partition = int(dat)
			if partition in self.keypadList:
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				self.logger.warning(f"Trouble Status (LED ON). (Partition {partition} '{keyp}')")
				self.updateKeypad(partition, 'LEDTrouble', 'on')   # this updates LED for partitions 1-8
				self.troubleClearedTimer = 0

		elif cmd == '841':
			#Sends Trouble off for all partitions, including undefined ones.
			partition = int(dat)
			self.logger.debug(f"Trouble Status Restore (LED OFF). (Partition {partition})")
			self.updateKeypad(partition, 'LEDTrouble', 'off')  # this updates LED for partitions 1-8
			if self.troubleCode > 0:
				# If the trouble light goes off, set a 10 second timer.
				# If the light is still off after 10 seconds we'll clear our status
				# This is required because the panel turns the light off/on quickly
				# when the light is actually on.
				self.troubleClearedTimer = 10

		elif cmd == '849':
			self.logger.debug(f"Received trouble code byte 0x{dat}")
			newCode = int(dat, 16)

			if newCode != self.troubleCode:
				self.troubleCode = newCode
				if self.troubleCode > 0:
					body = "Trouble Code Received:\n"
					if self.troubleCode & 1: body += "- Service is Required. Check Keypad for more Information.\n"
					if self.troubleCode & 2: body += "- AC Power Lost\n"
					if self.troubleCode & 4: body += "- Telephone Line Fault\n"
					if self.troubleCode & 8: body += "- Failure to Communicate\n"
					if self.troubleCode & 16: body += "- Sensor/Zone Fault\n"
					if self.troubleCode & 32: body += "- Sensor/Zone Tamper\n"
					if self.troubleCode & 64: body += "- Sensor/Zone Low Battery\n"
					if self.troubleCode & 128: body += "- Loss of Time\n"
					self.sendTroubleEmail(body)

		elif cmd == '851':
			self.logger.debug(f"Partition Busy Restore. (Partition {int(dat)})")
		elif cmd == '896':
			self.logger.debug("Keybus Fault")
		elif cmd == '897':
			self.logger.debug("Keybus Fault Restore")
		elif cmd == '900':
			self.logger.error("User Access Code Required")

		elif cmd == '901':
			#this updates the virtual keypad
			#for char in dat:
			#	self.logger.debug(f"LCD DEBUG: {ord(char)}")
			m = re.search(r'^...(..)(.*)$', dat)
			if m:
				lcdText = re.sub(r'[^ a-zA-Z0-9_/\:-]+', ' ', m.group(2))
				half = int(len(lcdText)/2)
				half1 = lcdText[:half]
				half2 = lcdText[half:]
				self.logger.debug(f"LCD Update, Line 1:'{half1}' Line 2:'{half2}'")
				self.updateKeypad(0, 'LCDLine1', half1)
				self.updateKeypad(0, 'LCDLine2', half2)

		elif cmd == '903':
			m = re.search(r'^(.)(.)$', dat)
			if m:
				(ledName, ledState) = (kLedIndexList[int(m.group(1))], kLedStateList[int(m.group(2))])
				self.logger.debug(f"LED '{ledName}' is '{ledState}'.")

				if ledState == 'flashing':
					ledState = 'on'

				if ledName == 'Ready':
					self.updateKeypad(1, 'LEDReady', ledState)
				elif ledName == 'Armed':
					self.updateKeypad(1, 'LEDArmed', ledState)
				elif ledName == 'Trouble':
					self.updateKeypad(1, 'LEDTrouble', ledState)
				elif ledName == 'Bypass':
					self.updateKeypad(1, 'LEDBypass', ledState)
				elif ledName == 'Memory':
					self.updateKeypad(1, 'LEDMemory', ledState)


		elif cmd == '904':
			self.logger.debug("Beep Status")

		elif cmd == '905':
			self.logger.debug("Tone Status")

		elif cmd == '906':
			self.logger.debug("Buzzer Status")

		elif cmd == '907':
			self.logger.debug("Door Chime Status")

		elif cmd == '908':
			m = re.search(r'^(..)(..)(..)$', dat)
			if m:
				self.logger.debug(f"DSC Software Version {m.group(1)}.{m.group(2)}")

		elif cmd == '912':
			self.logger.error("Command Output Pressed")

		elif cmd == '921':
			self.logger.error("Master Code Required")

		elif cmd == '922':
			self.logger.error("Installer Code Required")

		else:
			#self.logger.debug(f"RX: {data}")
			self.logger.debug(f"Unrecognized command received (Cmd:{cmd} Dat:{dat} Sum:{sum})")

		return (cmd, dat)



	######################################################################################
	# Indigo Device State Updating
	######################################################################################

	# Updates temperature of DSC temperature sensor
	#
	def updateSensorTemp(self, sensorNum, key, temp):
		if temp > 127:
			temp = 127 - temp
		self.logger.debug(f"Temp sensor {sensorNum} {key} temp now {temp} degrees.")
		if sensorNum in list(self.tempList.keys()):
			if key == 'inside':
				self.tempList[sensorNum].updateStateOnServer(key="temperatureInside", value=temp)
			elif key == 'outside':
				self.tempList[sensorNum].updateStateOnServer(key="temperatureOutside", value=temp)
			elif key == 'cool':
				self.tempList[sensorNum].updateStateOnServer(key="setPointCool", value=temp)
			elif key == 'heat':
				self.tempList[sensorNum].updateStateOnServer(key="setPointHeat", value=temp)

			if self.tempList[sensorNum].pluginProps['zoneLogChanges'] == 1:
				self.logger.info(f"Temp sensor {sensorNum} {key} temp now {temp} degrees.")


	# Updates zone group
	#
	def updateZoneGroup(self, zoneGroupDevId):

		zoneGrp = indigo.devices[zoneGroupDevId]

		zoneGrp.updateStateOnServer(key="AnyMemberLastChangedTimer", value=0)
		zoneGrp.updateStateOnServer(key="AnyMemberLastChangedShort", value="0m")

		newState = kZoneGroupStateClosed
		for zoneId in self.zoneGroupList[zoneGroupDevId]:
			zoneState = indigo.devices[int(zoneId)].states['state']
			if (zoneState != kZoneStateClosed) and (newState != kZoneGroupStateTripped):
				if zoneState == kZoneStateOpen:
					newState = kZoneGroupStateOpen
				elif zoneState == kZoneStateTripped:
					newState = kZoneGroupStateTripped

		if zoneGrp.states['state'] != newState:
			zoneGrp.updateStateOnServer(key="EntireGroupLastChangedTimer", value=0)
			zoneGrp.updateStateOnServer(key="EntireGroupLastChangedShort", value="0m")
			zoneGrp.updateStateOnServer(key="state", value=newState)


	# Updates indigo variable instance var with new value varValue
	#
	def updateZoneState(self, zoneKey, newState):

		if zoneKey in list(self.zoneList.keys()):
			try:
				zone = indigo.devices[self.zoneList[zoneKey]]
			except:
				self.logger.warning("possible Server Communication Error")   #catching servercommunicationerror
				pass
			zoneType = zone.pluginProps['zoneType']
			#zonePartition = zone.pluginProps['zonePartition']

			# If the new state is different from the old state
			# then lets update timers and set the new state
			if zone.states['state'] != newState:
				# This is a new state, update all states and timers
				zone.updateStateOnServer(key="LastChangedShort", value="0m")
				zone.updateStateOnServer(key="LastChangedTimer", value=0)
				zone.updateStateOnServer(key="state", value=newState)
				timeNowFormatted = datetime.now().strftime("%H:%M:%S, %Y-%m-%d")

				# Check if this zone is assigned to a zone group so we can update it
				for devId in self.zoneGroupList:
					#self.logger.debug(f"Zone Group ID: {zone.id} contains {zoneGroupList[devId]}")
					if str(zone.id) in self.zoneGroupList[devId]:
						self.updateZoneGroup(devId)

				if 'var' in list(zone.pluginProps.keys()):
					self.updateVariable(zone.pluginProps['var'], newState)

				if newState == kZoneStateTripped:
					self.logger.warning(f"Alarm Zone '{zone.name}' TRIPPED!")

				if zone.pluginProps['zoneLogChanges'] == 1:
					if newState == kZoneStateOpen:
						self.logger.info(f"Alarm Zone '{zone.name}' Opened.")
						if zoneType != "zoneTypeMotion":
							indigo.variable.updateValue("DSC_Last_Zone_Active", value=f"{zone.name} Opened at {timeNowFormatted}.")
					elif newState == kZoneStateClosed:
						self.logger.info(f"Alarm Zone '{zone.name}' Closed.")
						if zoneType != "zoneTypeMotion":
							indigo.variable.updateValue("DSC_Last_Zone_Active", value=f"{zone.name} Closed at {timeNowFormatted}.")
						
				if zoneType == "zoneTypeMotion":
					indigo.variable.updateValue("DSC_Last_Motion_Active", value=f"{zone.name} at {timeNowFormatted}.")


	def updateZoneBypass(self, zoneKey, newState):

		if zoneKey in list(self.zoneList.keys()):
			try:
				zone = indigo.devices[self.zoneList[zoneKey]]
			except:
				self.logger.warning("possible Server Communication Error")   #catching servercommunicationerror
				pass
			#zoneType = zone.pluginProps['zoneType']

			# If the new bypass state is different from the old state
			# then lets set the new state
			if zone.states['bypass'] != newState:
				# This is a new bypass state, update all states
				zone.updateStateOnServer(key="bypass", value=newState)

				if 'var' in list(zone.pluginProps.keys()):
					self.updateVariable(zone.pluginProps['var'], newState)

				if newState == kZoneBypassYes:
					self.logger.info(f"Alarm Zone '{zone.name}' Bypassed.")
				elif newState == kZoneBypassNo:
					self.logger.info(f"Alarm Zone '{zone.name}' Bypass Cancelled.")


	def updateKeypad(self, partition, stateName, newState):

		self.logger.threaddebug(f"Updating Custom State {stateName} for Keypad on Partition {partition} to {newState}.")

		# If we're updating the main keypad state, update the variable too
		if stateName == 'state':
			self.updateVariable(self.pluginPrefs['variableState'], newState)

		if partition == 0:
			for keyk in self.keypadList.keys():
				try:
					keyp = indigo.devices[self.keypadList[keyk]]
				except:
					self.logger.warning("possible Server Communication Error")   #catching servercommunicationerror
					pass
				keyp.updateStateOnServer(key=stateName, value=newState)
			return

		if partition in list(self.keypadList.keys()):
			try:
				keyp = indigo.devices[self.keypadList[partition]]
			except:
				self.logger.warning("possible Server Communication Error")   #catching servercommunicationerror
				pass
			keyp.updateStateOnServer(key=stateName, value=newState)


	######################################################################################
	# Sending email of tripped zones
	######################################################################################

	def sendZoneTrippedEmail(self):

		if not self.configEmailUrgent or not self.trippedZoneList:
			return

		theBody = "The following zone(s) have been tripped:\n\n"

		for zoneNum in self.trippedZoneList:

			if zoneNum in self.closeTheseZonesList:
				stateNow = "closed"
			else:
				stateNow = "open"

			zone = indigo.devices[self.zoneList[zoneNum]]

			theBody += f"{zone.name} (currently {stateNow})\n"

		theBody += "\n--\nDSC Alarm Plugin\n\n"

		self.logger.info(f"Sending zone tripped email to {self.configEmailUrgent}.")

		contentPrefix = self.pluginPrefs.get('emailUrgentContent', '')
		if contentPrefix:
			theBody = contentPrefix + "\n\n" + theBody

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=theBody)

##########################################################################################
############# Kidney514 ##########  Sending email of who is disarming
##########################################################################################

	def sendEmailDisarm(self, bodyText):

		if not (self.configEmailDisarm):
			return

		self.logger.info(f"Sending Disarmed by: email to {self.configEmailDisarm}.")

		contentPrefix = self.pluginPrefs.get('EmailDisarmContent', '')
		if contentPrefix:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailDisarm, subject=self.configEmailDisarmSubject, body=bodyText)

##########################################################################################
# sending emails
##########################################################################################


	def sendTroubleEmail(self, bodyText):

		if not self.configEmailNotice:
			return

		self.logger.info(f"Sending trouble email to {self.configEmailNotice}.")

		contentPrefix = self.pluginPrefs.get('emailNoticeContent', '')
		if contentPrefix:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailNotice, subject=self.configEmailNoticeSubject, body=bodyText)


	def sendPanicEmail(self, bodyText):

		if not self.configEmailUrgent:
			return

		self.logger.info(f"Sending panic alert email to {self.configEmailUrgent}.")

		contentPrefix = self.pluginPrefs.get('emailUrgentContent', '')
		if contentPrefix:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=bodyText)
		# if no email address is specified the speak part does not trigger
		say = f"{self.pluginPrefs['speakTextPanic']} Keypad: {bodyText}."
		self.sayThis(say)



	def sendDuressEmail(self, bodyText):

		if not self.configEmailUrgent:
			return

		self.logger.info(f"Sending duress alarm email to {self.configEmailUrgent}.")

		contentPrefix = self.pluginPrefs.get('emailUrgentContent', '')
		if contentPrefix:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=bodyText)
		# if no email address specified the speak part does not trigger
		say = f"{self.pluginPrefs['speakTextPanic']} Keypad: {bodyText}."
		self.sayThis(say)


	def sayThis(self, text):
		self.logger.debug(f"SAY: {text}")
		# The default variable is DSC_Alarm_Text
		if self.configSpeakVariable is not None:
			if self.configSpeakVariable in indigo.variables:
				indigo.variable.updateValue(self.configSpeakVariable, value=text)
		else:
			indigo.server.speak(text)


	def speak(self, textId):
		self.logger.debug(f"ID: {textId}")
		if self.pluginPrefs['speakingEnabled'] is False:
			return

		if not (self.pluginPrefs[textId]):
			return

		if textId == 'speakTextFailedToArm':
			zones = 0
			zoneText = ''
			for zoneNum in self.zoneList.keys():
				zone = indigo.devices[self.zoneList[zoneNum]]
				if zone.states['state.open'] is True:
					if zones > 0:
						zoneText += ', '
					zoneText += zone.name.replace("Alarm_", "")
					zones += 1

			if zones == 0:
				say = self.pluginPrefs[textId]
			if zones == 1:
				say = f"{self.pluginPrefs[textId]}  The {zoneText} is open."
			else:
				say = f"{self.pluginPrefs[textId]}  The following zones are open: {zoneText}."

			self.sayThis(say)

		elif textId == 'speakTextTripped':
			zones = 0
			zoneText = ''
			for zoneNum in self.trippedZoneList:
				zone = indigo.devices[self.zoneList[zoneNum]]
				if zones > 0:
					zoneText += ', '
				zoneText += zone.name.replace("Alarm_", "")
				zones += 1

			if zones == 0:
				return
				#if alarm is tripped due to panic, we want the panic alert to handle the talking
			if zones == 1:
				say = f"{self.pluginPrefs[textId]}  The {zoneText} has been tripped."
			else:
				say = f"{self.pluginPrefs[textId]}  The following zones have been tripped: {zoneText}."

			self.sayThis(say)


		else:
			self.sayThis(self.pluginPrefs[textId])


	# Updates indigo variable instance var with new value varValue
	#
	def updateVariable(self, varID, varValue):

		if self.createVariables is False:
			return

		#self.logger.debug(f"Variable: {varID}")

		if varID is None:
			return

		if varID in indigo.variables:
			indigo.variable.updateValue(varID, value=varValue)


	# Converts given time in minutes to a human format e.g. 3m, 5h, 2d, etc.
	#
	def getShortTime(self, minutes):

		# If time is less than 100 min then show XXm
		if minutes < 100:
			return str(minutes) + 'm'
		# If it's less than 49 hours then show XXh
		elif minutes < 2881:
			return str(int(minutes / 60)) + 'h'
		# If it's less than 100 days then show XXd
		elif minutes < 144000:
			return str(int(minutes / 1440)) + 'd'
		# If it's anything more than one hundred days then show nothing
		else:
			return ''

# 		############ Alternate Version #########################
# 		# If time is less than 100 min then show XXm
# 		if minutes < 100:
# 			return str(minutes) + 'm'
# 		# If it's less than 49 hours then show XXh
# 		elif minutes < 2881:
# 			return str(int(minutes / 60)) + 'h'
# 		# If it's less than 365 days then show XXd
# 		elif minutes < 525601:
# 			return str(int(minutes / 1440)) + 'd'
# 		# If it's anything more than 365 days then show XXmonths
# 		else:
# 			return str(int(minutes / 43800)) + 'months'
# 		########################################################



	######################################################################################
	# Concurrent Thread
	######################################################################################

	def runConcurrentThread(self):
		self.logger.threaddebug("runConcurrentThread called")
		self.minuteTracker = time.time() + 60
		self.nextUpdateCheckTime = 0

		# While Indigo hasn't told us to shutdown
		while self.shutdown is False:

			self.timeNow = time.time()

			if self.state == self.States.STARTUP:
				self.logger.debug("STATE: Startup")

				if self.configRead is False:
					if self.getConfiguration(self.pluginPrefs) is True:
						self.configRead = True

				if self.configRead is True:
					self.state = self.States.BOTH_INIT

				self.sleep(1)

			elif self.state == self.States.HOLD:
				if self.configRead is False:
					self.state = self.States.STARTUP
				self.sleep(1)

			elif self.state == self.States.HOLD_RETRY:
				self.logger.warning(f"Plugin will attempt to re-initialize again in {self.currentHoldRetryTime} minutes.")
				self.nextRetryTime = self.timeNow + (kHoldRetryTimeMinutes*60)
				self.state = self.States.HOLD_RETRY_LOOP

			elif self.state == self.States.HOLD_RETRY_LOOP:
				if self.configRead is False:
					self.state = self.States.STARTUP
				if self.timeNow >= self.nextRetryTime:
					self.state = self.States.BOTH_INIT
				self.sleep(1)

			elif self.state == self.States.BOTH_INIT:
				if self.openPort() is True:
					if self.useSerial is False:
						self.state = self.States.SO_CONNECT
						self.sleep(1)

						# Enable pinging every 5 minutes
						self.nextPingTime = self.timeNow + kPingInterval
					else:
						self.state = self.States.ENABLE_TIME_BROADCAST

				else:
					#self.logger.error(f"Error opening port, will retry in {self.currentHoldRetryTime} minutes.")
					self.state = self.States.HOLD_RETRY

			elif self.state == self.States.SO_CONNECT:
				err = True

				# Read packet to clear the port of the 5053 login request
				self.readPacket()

				attemptLogin = True
				while attemptLogin is True:
					attemptLogin = False
					rx = self.sendPacket('005' + self.pluginPrefs['TwoDS_Password'], waitFor='505')
					if not rx or rx == "-":
						self.logger.error("Timeout waiting for Envisalink to respond to login request.")
					else:
						rx = int(rx)
						if rx == 0:
							self.logger.error("Envisalink refused login request.")
						elif rx == 1:
							err = False
							self.logger.info("Connected to Envisalink.")
						elif rx == 3:
							# 2DS sent login request, retry (Happens when socket is first opened)
							self.logger.debug("Received login request, retrying login...")
							attemptLogin = True
						else:
							self.logger.error("Unknown response from Envisalink login request.")

				# This delay is required otherwise 2DS locks up
				self.sleep(1)

				if err is True:
					self.state = self.States.HOLD_RETRY
				else:
					self.state = self.States.ENABLE_TIME_BROADCAST


			elif self.state == self.States.ENABLE_TIME_BROADCAST:

				# Enable time broadcast
				self.logger.debug("Enabling Time Broadcast")
				rx = self.sendPacket('0561')
				if rx:
					self.logger.debug("Time Broadcast enabled.")
					self.state = self.States.BOTH_PING
				else:
					self.logger.error("Error enabling Time Broadcast.")
					self.state = self.States.HOLD_RETRY

			elif self.state == self.States.BOTH_PING:

				#Ping the panel to confirm we are in communication
				err = True
				self.logger.debug("Pinging the panel to test communication...")
				rx = self.sendPacket('000')
				if rx:
					self.logger.debug("Ping was successful.")
					err = False
				else:
					self.logger.error("Error pinging panel, aborting.")

				if err is True:
					self.state = self.States.HOLD_RETRY
				else:
					#Request a full state update
					self.logger.debug("Requesting a full state update.")
					rx = self.sendPacket('001')
					if not rx:
						self.logger.error("Error getting state update.")
						self.state = self.States.HOLD_RETRY
					else:
						self.logger.debug("State update request successful, initialization complete, starting normal operation.")
						self.state = self.States.BOTH_POLL

			elif self.state == self.States.BOTH_POLL:
				if self.configRead is False:
					self.state = self.States.STARTUP
				else:

					if (self.useSerial is False) and (self.timeNow > self.nextPingTime):
						#self.logger.debug("Pinging Envisalink")
						self.txCmdList.append((kCmdNormal, '000'))
						self.nextPingTime = self.timeNow + kPingInterval

					if self.txCmdList:
						(cmdType, data) = self.txCmdList[0]
						if cmdType == kCmdNormal:
							txRsp = self.sendPacket(data)
							if txRsp == '-':
								# If we receive - socket has closed, lets re-init
								self.logger.error("Tried to send data but socket seems to have closed.  Trying to re-initialize.")
								self.state = self.States.BOTH_INIT
							else:
								# send was a success, remove command from queue
								del self.txCmdList[0]

						elif cmdType == kCmdThermoSet:
							self.setThermostat(data)
							del self.txCmdList[0]
					else:
						(rxRsp, rxData) = self.readPacket()
						if rxRsp == '-':
							# If we receive - socket has closed, lets re-init
							self.logger.error("Tried to read data but socket seems to have closed.  Trying to re-initialize.")
							self.state = self.States.BOTH_INIT


			# Check if the trouble timer counter is timing
			# We need to know if the trouble light has remained off
			# for a few seconds before we assume the trouble is cleared
			if self.troubleClearedTimer > 0:
				self.troubleClearedTimer -= 1
				if self.troubleClearedTimer == 0:
					self.troubleCode = 0
					self.sendTroubleEmail("Trouble Code Cleared.")

			if self.repeatAlarmTripped is True:
				#timeNow = time.time()
				if self.timeNow >= self.repeatAlarmTrippedNext:
					self.repeatAlarmTrippedNext = self.timeNow + 12
					self.speak('speakTextTripped')


			# If a minute has elapsed
			if self.timeNow >= self.minuteTracker:

				# Increment all zone changed timers
				self.minuteTracker += 60
				for zoneKey in self.zoneList.keys():
					zone = indigo.devices[self.zoneList[zoneKey]]
					tmr = zone.states["LastChangedTimer"] + 1
					zone.updateStateOnServer(key="LastChangedTimer", value=tmr)
					zone.updateStateOnServer(key="LastChangedShort", value=self.getShortTime(tmr))

				for zoneGroupDeviceId in self.zoneGroupList:
					zoneGroupDevice = indigo.devices[zoneGroupDeviceId]
					tmr = zoneGroupDevice.states["AnyMemberLastChangedTimer"] + 1
					zoneGroupDevice.updateStateOnServer(key="AnyMemberLastChangedTimer", value=tmr)
					zoneGroupDevice.updateStateOnServer(key="AnyMemberLastChangedShort", value=self.getShortTime(tmr))
					tmr = zoneGroupDevice.states["EntireGroupLastChangedTimer"] + 1
					zoneGroupDevice.updateStateOnServer(key="EntireGroupLastChangedTimer", value=tmr)
					zoneGroupDevice.updateStateOnServer(key="EntireGroupLastChangedShort", value=self.getShortTime(tmr))


		self.closePort()
		self.logger.threaddebug("Exiting Concurrent Thread")


	def stopConcurrentThread(self):
		self.logger.threaddebug("stopConcurrentThread called")
		self.shutdown = True
		self.logger.threaddebug("Exiting stopConcurrentThread")

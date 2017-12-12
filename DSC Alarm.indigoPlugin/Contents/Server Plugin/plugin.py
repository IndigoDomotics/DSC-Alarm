#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# DSC Alarm Plugin
# Developed by Travis Cook and modified by Monstergerm
# www.frightideas.com

import re
import time
import indigo
from datetime import datetime
import serial
import indigoPluginUtils
import indigoPluginUpdateChecker

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
kAlarmStateDisarmed = u'disarmed'
kAlarmStateExitDelay = u'exitDelay'
kAlarmStateFailedToArm = u'FailedToArm'
kAlarmStateArmed = u'armed'
kAlarmStateEntryDelay = u'entryDelay'
kAlarmStateTripped = u'tripped'
kKeypadStateChimeEnabled = u'enabled'
kKeypadStateChimeDisabled = u'disabled'
kAlarmArmedStateDisarmed = u'disarmed'
kAlarmArmedStateStay = u'stay'
kAlarmArmedStateAway = u'away'
kReadyStateTrue = u'ready'
kReadyStateFalse = u'notready'
kPanicStateNone = u'none'
kPanicStateFire = u'fire'
kPanicStateAmbulance = u'ambulance'
kPanicStatePanic = u'panic'
kPanicStateDuress = u'duress'

kPluginUpdateUrl = u'http://www.frightideas.com/hobbies/dscAlarm/dscAlarmVersionInfo.html'

kLedIndexList = ['None', 'Ready', 'Armed', 'Memory', 'Bypass', 'Trouble', 'Program', 'Fire', 'Backlight', 'AC']
kLedStateList = ['off', 'on', 'flashing']
kArmedModeList = ['Away', 'Stay', 'Away, No Delay', 'Stay, No Delay']
kPanicTypeList = ['None', 'Fire', 'Ambulance', 'Panic', 'Duress']
kMonthList = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']


kCmdNormal = 0
kCmdThermoSet = 1
kPingInterval = 301
kHoldRetryTimeMinutes = 3





# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

################################################################################
class Plugin(indigo.PluginBase):

	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

		self.mylogger = indigoPluginUtils.logger(self)
		self.updater = indigoPluginUpdateChecker.updateChecker(self, kPluginUpdateUrl)

		self.States = self.enum(STARTUP=1, HOLD=2, HOLD_RETRY=3, HOLD_RETRY_LOOP=4, BOTH_INIT=5, SO_CONNECT=6, ENABLE_TIME_BROADCAST=7, BOTH_PING=8, BOTH_POLL=9)
		self.state = self.States.STARTUP
		self.logLevel = 1
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
		self.troubleCode = 0
		self.troubleClearedTimer = 0
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




	def enum(self, **enums):
		return type('Enum', (), enums)

	def __del__(self):
		indigo.PluginBase.__del__(self)

	########################################
	def startup(self):
		self.mylogger.log(4, u"startup called")
		self.configRead = self.getConfiguration(self.pluginPrefs)
		self.updater.checkVersionPoll()

	def shutdown(self):
		self.mylogger.log(4, u"shutdown called")


	######################################################################################
	# Indigo Device Start/Stop
	######################################################################################

	def deviceStartComm(self, dev):
		self.mylogger.log(4, u"<<-- entering deviceStartComm: %s (%d - %s)" % (dev.name, dev.id, dev.deviceTypeId))

		props = dev.pluginProps

		if dev.deviceTypeId == u'alarmZoneGroup':

			if dev.id not in self.zoneGroupList:
				self.zoneGroupList[dev.id] = props[u'devList']

			if dev.states[u'state'] == 0:
				dev.updateStateOnServer(key=u"state", value=kZoneGroupStateClosed)

		elif dev.deviceTypeId == u'alarmZone':
			if 'zoneNumber' not in props:
				return

			zone = int(props['zoneNumber'])
			if zone not in self.zoneList.keys():
				self.zoneList[zone] = dev.id
			else:
				self.mylogger.logError("Zone %s is already assigned to another device." % zone)

			# Check for new version zone states.
			# If they're not present tell Indigo to reread the Devices.xml file
			if 'LastChangedShort' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()

			# If state is invalid or not there, set to closed
			if dev.states['state'] == 0:
				dev.updateStateOnServer(key=u'state', value=kZoneStateClosed)

			# If plugin is v2 we won't have a bypass key so set it to default
			if 'bypass' not in dev.states or dev.states['bypass'] == 0:
				dev.stateListOrDisplayStateIdChanged()
				dev.updateStateOnServer(key=u'bypass', value=kZoneBypassNo)

			# If plugin is v2 we won't have a zonePartition key so set it to 1 by default
			if 'zonePartition' not in props:
				props.update({'zonePartition': '1'})
				dev.replacePluginPropsOnServer(props)

			dev.updateStateOnServer(key=u"LastChangedShort", value=self.getShortTime(dev.states[u"LastChangedTimer"]))


			# Check for new version properties to see if we need to refresh the device
			if 'occupancyGroup' not in props:
				self.mylogger.log(3, u"Adding occupancyGroup to device %s properties." % dev.name)
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


		elif dev.deviceTypeId == u'alarmKeypad':
			partition = int(dev.pluginProps['partitionNumber'])
			if partition not in self.keypadList.keys():
				self.keypadList[partition] = dev.id
				self.mylogger.log(3, u"Adding keypad: %s" % self.keypadList)
			else:
				self.mylogger.logError("Partition is already assigned to another device.")

			# If plugin is v2 we won't have a partitionName key so set it to default
			if 'partitionName' not in dev.pluginProps:
				props['partitionName'] = 'Default'
				dev.replacePluginPropsOnServer(props)

			dev.updateStateOnServer(key=u'state', value=kAlarmStateDisarmed)
			dev.updateStateOnServer(key=u'ReadyState', value=kReadyStateTrue)
			dev.updateStateOnServer(key=u'PanicState', value=kPanicStateNone)

			# Check for new keypad states.
			# If they're not present tell Indigo to reread the Devices.xml file
			if 'ArmedState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
			elif 'ReadyState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()
			elif 'PanicState' not in dev.states:
				dev.stateListOrDisplayStateIdChanged()


		elif dev.deviceTypeId == u'alarmTemp':
			sensor = int(dev.pluginProps['sensorNumber'])
			if sensor not in self.tempList.keys():
				self.tempList[sensor] = dev

		self.mylogger.log(4, u"exiting deviceStartComm -->>")


	def deviceStopComm(self, dev):
		self.mylogger.log(4, u"<<-- entering deviceStopComm: %s (%d - %s)" % (dev.name, dev.id, dev.deviceTypeId))

		if dev.deviceTypeId == u'alarmZoneGroup':
			if dev.id in self.zoneGroupList:
				del self.zoneGroupList[dev.id]

		elif dev.deviceTypeId == u'alarmZone':
			if 'zoneNumber' in dev.pluginProps:
				zone = int(dev.pluginProps['zoneNumber'])
				if zone in self.zoneList.keys():
					del self.zoneList[zone]
				#self.mylogger.log(3, u"ZoneList is now: %s" % self.zoneList)

		elif dev.deviceTypeId == u'alarmKeypad':
			if 'partitionNumber' in dev.pluginProps:
				keyp = int(dev.pluginProps['partitionNumber'])
				if keyp in self.keypadList:
					del self.keypadList[keyp]

		elif dev.deviceTypeId == u'alarmTemp':
			if 'sensorNumber' in dev.pluginProps:
				tmp = int(dev.pluginProps['sensorNumber'])
				if tmp in self.tempList:
					del self.tempList[int(dev.pluginProps['sensorNumber'])]

		self.mylogger.log(4, u"exiting deviceStopComm -->>")


	#def deviceUpdated(self, origDev, newDev):
	#	self.mylogger.log(4, u"<<-- entering deviceUpdated: %s" % origDev.name)
	#	origDev.name = newDev.name
	#	self.mylogger.log(4, u"OrigDev now: %s" % origDev.name)
	#	self.DigiTemp.deviceStop(origDev)
	#	self.DigiTemp.deviceStart(newDev)

	######################################################################################
	# Indigo Trigger Start/Stop
	######################################################################################

	def triggerStartProcessing(self, trigger):
		self.mylogger.log(4, u"<<-- entering triggerStartProcessing: %s (%d)" % (trigger.name, trigger.id))
		self.triggerList.append(trigger.id)
		self.mylogger.log(4, u"exiting triggerStartProcessing -->>")

	def triggerStopProcessing(self, trigger):
		self.mylogger.log(4, u"<<-- entering triggerStopProcessing: %s (%d)" % (trigger.name, trigger.id))
		if trigger.id in self.triggerList:
			self.mylogger.log(4, u"TRIGGER FOUND")
			self.triggerList.remove(trigger.id)
		self.mylogger.log(4, u"exiting triggerStopProcessing -->>")

	#def triggerUpdated(self, origDev, newDev):
	#	self.mylogger.log(4, u"<<-- entering triggerUpdated: %s" % origDev.name)
	#	self.triggerStopProcessing(origDev)
	#	self.triggerStartProcessing(newDev)


	######################################################################################
	# Indigo Trigger Firing
	######################################################################################

	def triggerEvent(self, eventId):
		self.mylogger.log(4, u"<<-- entering triggerEvent: %s " % eventId)
		for trigId in self.triggerList:
			trigger = indigo.triggers[trigId]
			if trigger.pluginTypeId == eventId:
				indigo.trigger.execute(trigger)
		return


	######################################################################################
	# Indigo Menu Action Methods
	######################################################################################

	def checkForUpdates(self):
		self.mylogger.log(1, u"Manually checking for updates")
		self.updater.checkVersionNow()


	######################################################################################
	# Indigo Action Methods
	######################################################################################
	#These are partition specific commands, except global and panic alarms.

	def methodDisarmAlarm(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		#keyp = keyp[0][0] might return first character as string
		self.mylogger.log(1, u"Disarming Alarm. (Partition %s '%s')" % (keyp, keypname))
		tx = "".join(["040", keyp, self.pluginPrefs[u'code'], "0"*(6-len(self.pluginPrefs[u'code']))])
		self.txCmdList.append((kCmdNormal, tx))


	def methodArmStay(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		self.mylogger.log(1, u"Arming Alarm in Stay Mode. (Partition %s '%s')" % (keyp, keypname))
		self.txCmdList.append((kCmdNormal, '031' + keyp))


	def methodArmAway(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keyp = dev.pluginProps["partitionNumber"]
		self.mylogger.log(1, u"Arming Alarm in Away Mode. (Partition %s '%s')" % (keyp, keypname))
		self.txCmdList.append((kCmdNormal, '030' + keyp))


	def methodArmStayForce(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keyp = dev.pluginProps["partitionNumber"]
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if keypstate == kAlarmStateArmed:
			self.mylogger.log(1, u"The Selected Partition is Already Armed.")
			return
		if keyp !="1": #this sets all zones to nobypass if they are in partition 2-8, since those partitions do not report zone bypass status
			tx = "".join(["071", keyp, "*100#"])
			self.mylogger.log(3, u"We have partition 2-8 and will cancel all bypass")
			self.txCmdList.append((kCmdNormal, tx))
			self.sleep(3) #add delay if keybus buffer overruns
		for zoneNum in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneNum]]
			zonePartition = zone.pluginProps['zonePartition']
			if zone.states[u'state.open'] is True and zone.states[u'bypass'] == kZoneBypassNo and zonePartition == keyp:
				self.mylogger.log(1, u"Received Zone Bypass Action for Zone '%s' in Partition %s%s." % (zone.name, keyp, keypname))
				zoneNum = str(zoneNum).zfill(2)
				tx = "".join(["071", keyp, "*1", zoneNum, "#"])
				self.txCmdList.append((kCmdNormal, tx))
				self.sleep(2) #add delay if keybus buffer overruns
		self.mylogger.log(1, u"Arming Alarm in Forced Stay Mode. (Partition %s%s)" % (keyp, keypname))
		self.txCmdList.append((kCmdNormal, '031' + keyp))


	def methodArmAwayForce(self, action, dev):
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keyp = dev.pluginProps["partitionNumber"]
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if keypstate == kAlarmStateArmed:
			self.mylogger.log(1, u"The Selected Partition is Already Armed.")
			return
		if keyp !="1": #this sets all zones to nobypass if they are in partition 2-8, since those partitions do not report zone bypass status
			tx = "".join(["071", keyp, "*100#"])
			self.mylogger.log(3, u"We have partition 2-8 and will cancel all bypass")
			self.txCmdList.append((kCmdNormal, tx))
			self.sleep(3) #add delay if keybus buffer overruns
		for zoneNum in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneNum]]
			zonePartition = zone.pluginProps['zonePartition']
			if zone.states[u'state.open'] is True and zone.states[u'bypass'] == kZoneBypassNo and zonePartition == keyp:
				self.mylogger.log(1, u"Received Zone Bypass Action for Zone '%s' in Partition %s%s." % (zone.name, keyp, keypname))
				zoneNum = str(zoneNum).zfill(2)
				tx = "".join(["071", keyp, "*1", zoneNum, "#"])
				self.txCmdList.append((kCmdNormal, tx))
				self.sleep(2) #add delay if keybus buffer overruns
		self.mylogger.log(1, u"Arming Alarm in Forced Away Mode. (Partition %s%s)" % (keyp, keypname))
		self.txCmdList.append((kCmdNormal, '030' + keyp))


	def methodArmGlobal(self, action):
		#this action arms all defined partitions in away mode.
		self.mylogger.log(1, u"Arming Alarm in Global Mode (All Partitions).")
		for i in range(1, 9):
			if i in self.keypadList.keys():
				key = str(i)
				self.txCmdList.append((kCmdNormal, '030' + key))
				time.sleep(1)


	def methodPanicAlarm(self, action):
		panicType = action.props[u'panicAlarmType']
		self.mylogger.log(1, u"Activating Panic Alarm! (%s)" % kPanicTypeList[int(panicType)])
		self.txCmdList.append((kCmdNormal, '060' + panicType))


	def methodSendKeypress070(self, action):
		self.mylogger.log(3, u"Received Send Keypress 070 Action")
		keys = action.props[u'keys']
		firstChar = True
		sendBreak = False
		for char in keys:
			if char == 'L':
				time.sleep(2)
				sendBreak = False

			if (firstChar is False):
				self.txCmdList.append((kCmdNormal, '070^'))

			if char != 'L':
				self.txCmdList.append((kCmdNormal, '070' + char))
				sendBreak = True

			firstChar = False
		if (sendBreak is True):
			self.txCmdList.append((kCmdNormal, '070^'))


	def methodSendKeypress071(self, action, dev):
	 	keypname = str(dev.pluginProps['partitionName'])
	 	keypname = " '" + keypname + "'"
	 	keyp = dev.pluginProps["partitionNumber"]
	 	keys = action.props[u'keys']
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
	 	self.mylogger.log(1, u"Received Send Keypress Action [%s]. (Partition %s%s)" % (keys, keyp, keypname))
	 	cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
		if len(keys) != len(cleanKeys) or "*8" in keys:
			self.mylogger.log(1, u"There are Invalid Keys in your Command.")
			return
		if len(keys) > 6:
			self.mylogger.log(1, u"The Key Command is too long.")
			return
	 	tx = "".join(["071", keyp, keys])
	 	self.txCmdList.append((kCmdNormal, tx))


	def methodSendKeypressVariable(self, action):
		keys = indigo.variables ["DSC_Command"]
		keys = keys.value
		self.mylogger.log(1, u"Received Send Keypress Action [%s]." % keys)
		cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if len(keys) != len(cleanKeys) or "*8" in keys:
			self.mylogger.log(1, u"There are Invalid Keys in your DSCcommand Variable.")
			return
		if len(keys) > 7:
			self.mylogger.log(1, u"The Key Command is too long.")
			return
		if keys[0] < "0" or keys[0] > "8":
			self.mylogger.log(1, u"The First Character in your DSCcommand Needs to be a Valid Partition (1-8).")
		else:
			self.txCmdList.append((kCmdNormal, '071' + keys))


	def methodBypassZone(self, action, dev):
		key = dev.pluginProps["zoneNumber"]
		keyp = dev.pluginProps["zonePartition"]
		zone = indigo.devices[self.zoneList[int(key)]]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if keypstate == kAlarmStateArmed:
			self.mylogger.log(1, u"The Selected Zone '%s' is Armed and Cannot be Bypassed." % zone.name)
			return
		self.mylogger.log(1, u"Received Zone Bypass Action for Zone '%s' in Partition %s%s." % (zone.name, keyp, keypname))
		key = str(key).zfill(2)
		tx = "".join(["071", keyp, "*1", key, "#"])
		self.txCmdList.append((kCmdNormal, tx))
		#This is a toggle action, i.e. already bypassed zones will turn to non-bypassed state.
		#Zones in partition 2-8 do not report bypass status, therefore there will be no zone state update.


	def methodBypassZoneCancel(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if keypstate == kAlarmStateArmed:
			self.mylogger.log(1, u"The Selected Partition %s%s is Armed and Cannot Accept Bypass Cancel." % (keyp, keypname))
			return
		self.mylogger.log(1, u"Received All Zones Bypass Cancel for Partition %s%s." % (keyp, keypname))
		tx = "".join(["071", keyp, "*100#"])
		self.txCmdList.append((kCmdNormal, tx))


	def methodBypassZoneRecall(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keypstate = str(dev.states['state'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		if keypstate == kAlarmStateArmed:
			self.mylogger.log(1, u"The Selected Partition %s%s is Armed and Cannot Accept Bypass Recall." % (keyp, keypname))
			return
		self.mylogger.log(1, u"Received Zone(s) Bypass Recall for Partition %s%s." % (keyp, keypname))
		tx = "".join(["071", keyp, "*199#"])
		self.txCmdList.append((kCmdNormal, tx))


	def methodDoorChimeEnable(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keypstate = str(dev.states['KeypadChime'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		self.mylogger.log(1, u"Received Keypad Chime Enable for Partition %s%s." % (keyp, keypname))
		if keypstate != kKeypadStateChimeEnabled:
			tx = "".join(["071", keyp, "*4"])
			self.txCmdList.append((kCmdNormal, tx))
			return


	def methodDoorChimeDisable(self, action, dev):
		keyp = dev.pluginProps["partitionNumber"]
		dev = indigo.devices[self.keypadList[int(keyp)]]
		keypname = str(dev.pluginProps['partitionName'])
		keypname = " '" + keypname + "'"
		keypstate = str(dev.states['KeypadChime'])
		if self.useSerial is True:
			self.mylogger.logError('This Action does not work with IT-100.')
			return
		self.mylogger.log(1, u"Received Keypad Chime Disable for Partition %s%s." % (keyp, keypname))
		if keypstate == kKeypadStateChimeEnabled:
			tx = "".join(["071", keyp, "*4"])
			self.txCmdList.append((kCmdNormal, tx))
			return


    # Queue a command to set DSC Thermostat Setpoints
	#
	def methodAdjustThermostat(self, action):
		self.mylogger.log(3, u"Device %s:" % action)
		self.txCmdList.append((kCmdThermoSet, action))


	# The command queued above calls this routine to create the packet
	#
	def setThermostat(self, action):
		#find this thermostat in our list to get the number
		for sensorNum in self.tempList.keys():
			if self.tempList[sensorNum].id == action.deviceId:
				break

		self.mylogger.log(3, u"SensorNum = %s" % sensorNum)

		#send 095 for thermostat in question, wait for 563 response
		#self.mylogger.log(3, u'095' + str(sensorNum))
		rx = self.sendPacket(u'095' + str(sensorNum), waitFor='563')
		if len(rx) == 0:
			self.mylogger.logError('Error getting current thermostat setpoints, aborting adjustment.')
			return

		if (action.props[u'thermoAdjustmentType'] == u'+') or (action.props[u'thermoAdjustmentType'] == u'-'):
			sp = 0
		else:
			sp = int(action.props[u'thermoSetPoint'])

		# then 096TC+000 to inc cool,
		#      096Th-000 to dec heat
		#      096Th=### to set setpoint
		# wait for 563 response
		#self.mylogger.log(3, u'096%u%c%c%03u' % (sensorNum, action.props[u'thermoAdjustWhich'], action.props[u'thermoAdjustmentType'],sp) )
		rx = self.sendPacket(u'096%u%c%c%03u' % (sensorNum, action.props[u'thermoAdjustWhich'], action.props[u'thermoAdjustmentType'], sp), waitFor='563')
		if len(rx) == 0:
			self.mylogger.logError('Error changing thermostat setpoints, aborting adjustment.')
			return

		# send 097T
		#send 097 for thermostat in question to save setting, wait for 563 response
		rx = self.sendPacket(u'097' + str(sensorNum), waitFor='563')
		if len(rx) == 0:
			self.mylogger.logError('Error saving thermostat setpoints, aborting adjustment.')
			return


	# Reset an Alarm Zone Group's timers to 0
	#
	def methodResetZoneGroupTimer(self, action):
		if action.deviceId in indigo.devices:
			zoneGrp = indigo.devices[action.deviceId]
			self.mylogger.log(3, u"Manual timer reset for alarm zone group \"%s\"" % zoneGrp.name)
			zoneGrp.updateStateOnServer(key=u"AnyMemberLastChangedTimer", value=0)
			zoneGrp.updateStateOnServer(key=u"EntireGroupLastChangedTimer", value=0)


	######################################################################################
	# Indigo Pref UI Methods
	######################################################################################

	# Validate the pluginConfig window after user hits OK
	# Returns False on failure, True on success
	#
	def validatePrefsConfigUi(self, valuesDict):
		self.mylogger.log(3, u"validating Prefs called")
		errorMsgDict = indigo.Dict()
		wasError = False

		if valuesDict[u'configInterface'] == u'serial':
			if len(valuesDict[u'serialPort']) == 0:
				errorMsgDict[u'serialPort'] = u"Select a valid serial port."
				wasError = True
		else:
			if len(valuesDict[u'TwoDS_Address']) == 0:
				errorMsgDict[u'TwoDS_Address'] = u"Enter a valid IP address or host name."
				wasError = True
			if len(valuesDict[u'TwoDS_Password']) == 0:
				errorMsgDict[u'TwoDS_Password'] = u"Enter the password for the 2DS."
				wasError = True

		if len(valuesDict[u'code']) > 6:
			errorMsgDict[u'code'] = u"The code must be 6 digits or less."
			wasError = True

		if len(valuesDict[u'code']) == 0:
			errorMsgDict[u'code'] = u"You must enter the alarm's arm/disarm code."
			wasError = True

		if len(valuesDict[u'emailUrgent']) > 0:
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict[u'emailUrgent']):
				errorMsgDict[u'emailUrgent'] = u"Please enter a valid email address."
				wasError = True

		if len(valuesDict[u'updaterEmail']) > 0:
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict[u'updaterEmail']):
				errorMsgDict[u'updaterEmail'] = u"Please enter a valid email address."
				wasError = True

		if len(valuesDict[u'EmailDisarm']) > 0:
			if not re.match(r"[^@]+@[^@]+\.[^@]+", valuesDict[u'EmailDisarm']):
				errorMsgDict[u'EmailDisarm'] = u"Please enter a valid email address."
				wasError = True

		userCodeList = valuesDict['userCode'].split(",")
		userLabelList = valuesDict['userLabel'].split(",")
		newuserCodeList = [s for s in userCodeList if s.isdigit()]   #transfers only numbers to newUserCodeList
		length = len(userCodeList)

		if newuserCodeList and (any(len(lst) != length for lst in [newuserCodeList])):
			errorMsgDict[u'userCode'] = u"Config Error: The user code contains invalid characters (2-digit numbers only)."
			wasError = True

		if any(len(lst) != length for lst in [userLabelList]):
			errorMsgDict[u'userCode'] = u"Config Error: The user code and label lists are not of the same length."
			errorMsgDict[u'userLabel'] = u"Config Error: The user code and label lists are not of the same length."
			wasError = True

		if len(userCodeList) != len(set(userCodeList)):
			errorMsgDict[u'userCode'] = u"Config Error: The user code list contains duplicate codes."
			wasError = True

		for key in newuserCodeList:
			if int(key) < 1 or int(key) > 40:
				errorMsgDict[u'userCode'] = u"Config Error: The user code is out of bound."
				wasError = True


		if wasError is True:
			return (False, valuesDict, errorMsgDict)

		# Tell DSC module to reread it's config
		self.configRead = False

		# User choices look good, so return True (client will then close the dialog window).
		return (True, valuesDict)

	def validateActionConfigUi(self, valuesDict, typeId, actionId):
		self.mylogger.log(3, u"validating Action Config called")
		if typeId == u'actionSendKeypress':
			keys = valuesDict[u'keys']
			cleanKeys = re.sub(r'[^a-e0-9LFAP<>=*#]+', '', keys)
			if len(keys) != len(cleanKeys) or "*8" in keys:
				errorMsgDict = indigo.Dict()
				errorMsgDict[u'keys'] = u"There are invalid keys in your keystring."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)


	def validateEventConfigUi(self, valuesDict, typeId, eventId):
		self.mylogger.log(3, u"validating Event Config called")
		#self.mylogger.log(3, u"Type: %s, Id: %s, Dict: %s" % (typeId, eventId, valuesDict))
		if typeId == u'userArmed' or typeId == u'userDisarmed':
			code = valuesDict[u'userCode']
			if len(code) != 2:
				errorMsgDict = indigo.Dict()
				errorMsgDict[u'userCode'] = u"The user code must be 2 digits in length."
				return (False, valuesDict, errorMsgDict)

			cleanCode = re.sub(r'[^0-9]+', '', code)
			if len(code) != len(cleanCode):
				errorMsgDict = indigo.Dict()
				errorMsgDict[u'userCode'] = u"The code can only contain digits 0-9."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)

	def validateDeviceConfigUi(self, valuesDict, typeId, devId):
		self.mylogger.log(3, u"validating Device Config called")
		#self.mylogger.log(3, u"Type: %s, Id: %s, Dict: %s" % (typeId, devId, valuesDict))
		if typeId == u'alarmZone':
			zoneNum = int(valuesDict[u'zoneNumber'])
			if zoneNum in self.zoneList.keys() and devId != indigo.devices[self.zoneList[zoneNum]].id:
				#self.mylogger.log(3, u"ZONEID: %s" % self.DSC.zoneList[zone].id)
				errorMsgDict = indigo.Dict()
				errorMsgDict[u'zoneNumber'] = u"This zone has already been assigned to a different device."
				return (False, valuesDict, errorMsgDict)
		if typeId == u'alarmKeypad':
			partitionNum = int(valuesDict[u'partitionNumber'])
			if partitionNum in self.keypadList.keys() and devId != indigo.devices[self.keypadList[partitionNum]].id:
				errorMsgDict = indigo.Dict()
				errorMsgDict[u'partitionNumber'] = u"This partition has already been assigned to a different device."
				return (False, valuesDict, errorMsgDict)
		return (True, valuesDict)


	def getZoneList(self, filter="", valuesDict=None, typeId="", targetId=0):
		myArray = []
		for i in range(1, 65):
			zoneName = str(i)
			if i in self.zoneList.keys():
				zoneDev = indigo.devices[self.zoneList[i]]
				zoneName = ''.join([str(i), ' - ', zoneDev.name])
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
			if i in self.keypadList.keys():
				keypDev = indigo.devices[self.keypadList[i]]
				keypadName = str(keypDev.pluginProps['partitionName'])
				keypadName = ''.join([str(i), ' - ', keypadName])
				#keypadName = ''.join([str(i), ' - ', keypDev.name])
			myArray.append((str(i), keypadName))
		return myArray




	######################################################################################
	# Configuration Routines
	######################################################################################

	# Reads the plugins config file into our own variables
	#
	def getConfiguration(self, valuesDict):

		# Tell our logging class to reread the config for level changes
		self.mylogger.readConfig()

		self.mylogger.log(3, u"getConfiguration start")

		try:

			# Get setting of Create Variables checkbox
			if valuesDict[u'createVariables'] is True:
				self.createVariables = True
			else:
				self.createVariables = False

			# If the variable folder doesn't exist, disable variables, we're done!
			if valuesDict[u'variableFolder'] not in indigo.variables.folders:
				self.createVariables = False

			self.useSerial = False
			if valuesDict[u'configInterface'] == 'serial':
				# using serial port interface IT-100 or similar
				self.useSerial = True

			self.configKeepTimeSynced = valuesDict.get(u'syncTime', True)

			self.configSpeakVariable = None
			if u'speakToVariableEnabled' in valuesDict:
				if valuesDict[u'speakToVariableEnabled'] is True:
					self.configSpeakVariable = int(valuesDict[u'speakToVariableId'])
					if self.configSpeakVariable not in indigo.variables:
						self.mylogger.logError('Speak variable not found in variable list')
						self.configSpeakVariable = None

			self.configEmailUrgent = valuesDict.get(u'emailUrgent', '')
			self.configEmailNotice = valuesDict.get(u'updaterEmail', '')
			self.configEmailDisarm = valuesDict.get(u'EmailDisarm', '')
			self.configEmailUrgentSubject = valuesDict.get(u'emailUrgentSubject', 'Alarm Tripped')
			self.configEmailNoticeSubject = valuesDict.get(u'updaterEmailSubject', 'Alarm Trouble')
			self.configEmailDisarmSubject = valuesDict.get(u'DisarmEmailSubject', 'Who Disarmed')

			self.userCodeList = valuesDict.get(u'userCode', '').split(",")
			self.userLabelList = valuesDict.get(u'userLabel', '').split(",")
			self.userLabelDict = dict(zip(self.userCodeList, self.userLabelList))

			self.mylogger.log(3, u"Configuration read successfully")

			return True

		except:
			self.mylogger.log(2, u"Error reading plugin configuration. (happens on very first launch)")

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
			adr = self.pluginPrefs[u'TwoDS_Address'] + ':4025'
			self.mylogger.log(1, u"Initializing communication at address: %s" % adr)
			try:
				self.port = serial.serial_for_url('socket://' + adr, baudrate=115200)
			except Exception, err:
				self.mylogger.logError('Error opening socket: %s' % (str(err)))
				return False
		else:
			self.mylogger.log(1, u"Initializing communication on port %s" % self.pluginPrefs[u'serialPort'])
			try:
				self.port = serial.Serial(self.pluginPrefs[u'serialPort'], 9600, writeTimeout=1)
			except Exception, err:
				self.mylogger.logError('Error opening serial port: %s' % (str(err)))
				return False

		if self.port.isOpen() is True:
			self.port.flushInput()
			self.port.timeout = 1
			self.mylogger.log(1, u"Communication established")
			return True

		return False


	def readPort(self):
		if self.port.isOpen() is False:
			self.state = self.States.BOTH_INIT
			return ""

		data = ""
		try:
			data = self.port.readline()
		except Exception, err:
			self.mylogger.logError('Connection RX Error: %s' % (str(err)))
			# Return with '-' signaling calling subs to abort so we can re-init.
			data = '-'
			#exit()
		except:
			self.mylogger.logError('Connection RX Problem, plugin quitting')
			exit()

		return data


	def writePort(self, data):
		self.port.write(data)


	def sendPacketOnly(self, data):
		pkt = "%s%02X\r\n" % (data, self.calcChecksum(data))
		self.mylogger.log(4, u"TX: %s" % pkt)
		try:
			self.writePort(pkt.encode())
		except Exception, err:
			self.mylogger.logError('Connection TX Error: %s' % (str(err)))
			exit()
		except:
			self.mylogger.logError('Connection TX Problem, plugin quitting')
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
					self.mylogger.logError('Received system error after sending command, aborting.')
					return ''

				# If rxCmd is not 0 length then we received a response
				if len(rxCmd) > 0:
					if waitFor == '500':
						if (rxCmd == '500') and (rxData == txCmd):
							return rxData
					elif (rxCmd == waitFor):
						return rxData
			if txCmd != '000':
				self.mylogger.logError('Timed out after waiting for response to command %s for %u seconds, retrying.' % (tx, rxTimeout))
		self.mylogger.logError('Resent command %s %u times with no success, aborting.' % (tx, retries))
		return ''


	def readPacket(self):

		data = self.readPort()
		if len(data) == 0:
			return ('', '')
		elif data == '-':
			# socket has closed, return with signal to re-initialize
			return ('-', '')

		data = data.strip()

		m = re.search(r'^(...)(.*)(..)$', data)
		if not m:
			return ('', '')

		# Put this try in to try to catch exceptions when non-ascii characters
		# were received, not sure why they are being received.
		try:
			self.mylogger.log(4, u"RX: %s" % data)
			(cmd, dat, sum) = (m.group(1), m.group(2), int(m.group(3), 16))
		except:
			self.mylogger.logError(u'IT-100/Envisalink Error: Received a response with invalid characters')
			return ('', '')

		if sum != self.calcChecksum("".join([cmd, dat])):
			self.mylogger.logError("Checksum did not match on a received packet.")
			return ('', '')

		# Parse responses based on cmd value
		#

		if cmd == '500':
			self.mylogger.log(3, u"ACK for cmd %s." % dat)
			self.cmdAck = dat

		elif cmd == '501':
			self.mylogger.logError(u'IT-100/Envisalink Error: Received a command with a bad checksum')

		elif cmd == '502':
			errText = u'Unknown'

			if dat == '001':
				errText = u'Receive Buffer Overrun (a command is received while another is still being processed)'
			elif dat == '002':
				errText = u'Receive Buffer Overflow'
			elif dat == '003':
				errText = u'Transmit Buffer Overflow'

			elif dat == '010':
				errText = u'Keybus Transmit Buffer Overrun'
			elif dat == '011':
				errText = u'Keybus Transmit Time Timeout'
			elif dat == '012':
				errText = u'Keybus Transmit Mode Timeout'
			elif dat == '013':
				errText = u'Keybus Transmit Keystring Timeout'
				# this error is sometimes received after disarming a tripped partition with TPI disarm command 040
			elif dat == '014':
				errText = u'Keybus Interface Not Functioning (the TPI cannot communicate with the security system)'
			elif dat == '015':
				errText = u'Keybus Busy (Attempting to Disarm or Arm with user code)'
			elif dat == '016':
				errText = u'Keybus Busy – Lockout (The panel is currently in Keypad Lockout – too many disarm attempts)'
			elif dat == '017':
				errText = u'Keybus Busy – Installers Mode (Panel is in installers mode, most functions are unavailable)'
			elif dat == '018':
				errText = u'Keybus Busy – General Busy (The requested partition is busy)'

			elif dat == '020':
				errText = u'API Command Syntax Error'
			elif dat == '021':
				errText = u'API Command Partition Error (Requested Partition is out of bounds)'
			elif dat == '022':
				errText = u'API Command Not Supported'
			elif dat == '023':
				errText = u'API System Not Armed (sent in response to a disarm command)'
			elif dat == '024':
				errText = u'API System Not Ready to Arm (not secure, in delay, or already armed)'
				self.triggerEvent(u'eventFailToArm')
				self.speak('speakTextFailedToArm')
			elif dat == '025':
				errText = u'API Command Invalid Length'
			elif dat == '026':
				errText = u'API User Code not Required'
			elif dat == '027':
				errText = u'API Invalid Characters in Command'

			self.mylogger.logError(u"IT-100/Envisalink Error (%s): %s" % (dat, errText))

		elif cmd == '505':
			if dat == '3':
				self.mylogger.log(3, u'Received login request')

		elif cmd == '510':
			# Keypad LED State Updates for Partition 1 only
			leds = int(dat, 16)

			if leds & 1 > 0:
				self.updateKeypad(1, u'LEDReady', 'on')
			else:
				self.updateKeypad(1, u'LEDReady', 'off')

			if leds & 2 > 0:
				self.updateKeypad(1, u'LEDArmed', 'on')
			else:
				self.updateKeypad(1, u'LEDArmed', 'off')

			if leds & 16 > 0:
				self.updateKeypad(1, u'LEDTrouble', 'on')
			else:
				self.updateKeypad(1, u'LEDTrouble', 'off')

			if leds & 4 > 0:
				self.updateKeypad(1, u'LEDMemory', 'on')
			else:
				self.updateKeypad(1, u'LEDMemory', 'off')

			if leds & 8 > 0:
				self.updateKeypad(1, u'LEDBypass', 'on')
			else:
				self.updateKeypad(1, u'LEDBypass', 'off')

		elif cmd == '511':
			# Keypad LED Flashing State Update
			# Same as 510 above but means an LED is flashing
			# We don't use this right now
			pass

		elif cmd == '550':

			m = re.search(r'^(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)$', dat)
			if m:
				tHour = int(m.group(1))
				tMin = int(m.group(2))
				dMonth = int(m.group(3)) - 1
				dMonthDay = int(m.group(4))
				dYear = int(m.group(5))

				# Check if we should sync time
				if self.configKeepTimeSynced is True:
					d = datetime.now()
					# Is the hour different or minute off by more than one minute?
					if (d.hour != tHour) or (abs(d.minute - tMin) > 1):
						self.mylogger.log(1, u"Setting alarm panel time and date.")
						self.txCmdList.append((kCmdNormal, u"010%s" % d.strftime("%H%M%m%d%y")))
					else:
						self.mylogger.log(3, u"Alarm panel time is within 1 minute of actual time, no update necessary.")

				# If this is a 2DS/Envisalink interface then lets insert the time (updated every 4 minutes)
				if self.useSerial is False:
					tAmPm = u'a'
					if tHour >= 12:
						tAmPm = u'p'

					if tHour > 12:
						tHour -= 12
					elif tHour == 0:
						tHour = 12
					self.updateKeypad(0, u'LCDLine1', u'  Date     Time ')
					self.updateKeypad(0, u'LCDLine2', u"%s %02u/%02u %2u:%02u%s" % (kMonthList[dMonth], dMonthDay, dYear, tHour, tMin, tAmPm))

		elif cmd == '560':
			self.mylogger.log(1, u"Telephone Ring Tone Has Been Detected.")
			for trig in self.triggerList:
				trigger = indigo.triggers[trig]
				if trigger.pluginTypeId == u'eventNoticeTelephone_Ring':
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
			# a zone goes into alarm
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.updateZoneState(zone, kZoneStateTripped)
				if (len(self.trippedZoneList) == 0):
					if "DSC_Alarm_Memory" in indigo.variables:
						indigo.variable.updateValue("DSC_Alarm_Memory", value ="")
				if zone not in self.trippedZoneList:
					self.trippedZoneList.append(zone)
					self.sendZoneTrippedEmail()
					indigoVar =""
					for zoneNum in self.trippedZoneList:
						zone = indigo.devices[self.zoneList[zoneNum]]
						indigoVar += (zone.name + "; ")
					if "DSC_Alarm_Memory" in indigo.variables:
						indigo.variable.updateValue("DSC_Alarm_Memory", indigoVar)
					self.triggerEvent(u'eventZoneTripped')

		elif cmd == '602':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				dev = indigo.devices[self.keypadList[partition]]
				zonedev = indigo.devices[self.zoneList[zone]]
				keyp = str(dev.pluginProps['partitionName'])
				self.mylogger.log(1, u"Zone '%s' Restored. (Partition %d '%s')" % (zonedev.name, partition, keyp))

		elif cmd == '603':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.mylogger.log(3, u"Zone Number %d Has a Tamper Condition." % zone)

		elif cmd == '604':
			m = re.search(r'^(.)(...)$', dat)
			if m:
				(partition, zone) = (int(m.group(1)), int(m.group(2)))
				self.mylogger.log(3, u"Zone Number %d Tamper Condition has been Restored." % zone)

		elif cmd == '605':
			zone = int(dat)
			self.mylogger.log(3, u"Zone Number %d Has a Fault Condition." % zone)

		elif cmd == '606':
			zone = int(dat)
			self.mylogger.log(3, u"Zone Number %d Fault Condition has been Restored." % zone)

		elif cmd == '609':
			zone = int(dat)
			self.mylogger.log(3, u"Zone Number %d Open." % zone)
			self.updateZoneState(zone, kZoneStateOpen)
			if self.repeatAlarmTripped is True:
				if zone in self.closeTheseZonesList:
					self.closeTheseZonesList.remove(zone)

		elif cmd == '610':
			zone = int(dat)
			self.mylogger.log(3, u"Zone Number %d Closed." % zone)
			# Update the zone to closed ONLY if the alarm is not tripped
			# We want the tripped states to be preserved so someone looking
			# at their control page will see all the zones that have been
			# opened since the break in.
			if self.repeatAlarmTripped is False:
				self.updateZoneState(zone, kZoneStateClosed)
			else:
				self.closeTheseZonesList.append(zone)

		elif cmd == '616':
			#cmd is sent after a zone is bypassed or bypass is cancelled.
			#This dump can be forced with keypress command [1*1#] if partition is not armed. If partition is armed it will switch armed state from stay to away and vice versa.
			#Routine that identifies bypassed zones and updates zone status kZoneBypassNo or kZoneBypassYes via newState (unfortunately for partition 1 only)
			BypassHexDump = str(dat)       #this is the 16-digit hex string for bypassed zones. Partition 1 only!
			self.mylogger.log(3, u"Bypass Hex Dump (%s)" % BypassHexDump)
			BBDump = format(int(BypassHexDump, 16), '0>64b')
			BypassBinaryDump = "".join(["".join([m[i:i+1] for i in range(8-1,-1,-1)]) for m in [BBDump[i:i+8] for i in range(0,len(BBDump),8)]])
			#reordered in 8 bit words to get zones in 1-64 order
			self.mylogger.log(2, u"Bypass Binary Dump (%s)" % BypassBinaryDump)
			for i in range(64):
				if BypassBinaryDump[i-1] == '1':
					self.updateZoneBypass(i, kZoneBypassYes)
				elif BypassBinaryDump[i-1] == '0':
					self.updateZoneBypass(i, kZoneBypassNo)

		elif cmd == '620':
			self.mylogger.log(1, u"Duress Alarm Detected")
			self.sendDuressEmail(u"Duress Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, u'PanicState', kPanicStateDuress)

		elif cmd == '621':
			self.mylogger.log(1, u"Fire Key Alarm Detected")
			self.sendPanicEmail(u"Fire Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, u'PanicState', kPanicStateFire)

		elif cmd == '623':
			self.mylogger.log(1, u"Auxiliary/Medical Key Alarm Detected")
			self.sendPanicEmail(u"Ambulance/Medical Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, u'PanicState', kPanicStateAmbulance)

		elif cmd == '625':
			self.mylogger.log(1, u"Panic Key Alarm Detected")
			self.sendPanicEmail(u"Police/Panic Key Alarm Detected")
			# This updates all keypads (partitions)
			self.updateKeypad(0, u'PanicState', kPanicStatePanic)

		elif cmd == '631':
			self.mylogger.log(1, u"Auxiliary/Smoke Input Alarm Detected")

		elif cmd == '632':
			self.mylogger.log(1, u"Auxiliary/Smoke Input Alarm Restored")

		elif cmd == '650':
			self.mylogger.log(3, u"Partition %d Ready" % int(dat))
			partition = int(dat)
			self.updateKeypad(partition, u'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, u'LEDReady', 'on')
			# This reports ready state only for keypads i.e. partitions that are ready.

		elif cmd == '651':
			self.mylogger.log(3, u"Partition %d Not Ready" % int(dat))
			partition = int(dat)
			self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, u'LEDReady', 'off')


		elif cmd == '652':
			if len(dat) == 1:
				partition = int(dat)
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				self.mylogger.log(3, u"Alarm Panel Armed. (Partition %d '%s')" % (partition, keyp))
				self.updateKeypad(partition, u'state', kAlarmStateArmed)
				self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
				self.updateKeypad(partition, u'LEDReady', 'off')
				self.updateKeypad(partition, u'LEDArmed', 'on')	  # these update LEDs for partitions 1-8
				self.speak('speakTextArmed')
				self.trippedZoneList = []

			elif len(dat) == 2:
				m = re.search(r'^(.)(.)$', dat)
				if m:
					(partition, mode) = (int(m.group(1)), int(m.group(2)))
					dev = indigo.devices[self.keypadList[partition]]
					keyp = str(dev.pluginProps['partitionName'])
					self.mylogger.log(1, u"Alarm Panel Armed in %s Mode. (Partition %d '%s')" % (kArmedModeList[mode], partition, keyp))
					if (mode == 0) or (mode == 2):
						armedEvent = u'armedAway'
						self.updateKeypad(partition, u'ArmedState', kAlarmArmedStateAway)
					else:
						armedEvent = u'armedStay'
						self.updateKeypad(partition, u'ArmedState', kAlarmArmedStateStay)
						self.updateKeypad(partition, u'LEDBypass', 'on')   #LED on since motion sensors are bypassed

					self.triggerEvent(armedEvent)
					for trig in self.triggerList:
						trigger = indigo.triggers[trig]
						if trigger.pluginTypeId == u'eventPartitionArmed':
							if trigger.pluginProps[u'partitionNum'] == str(partition):
								indigo.trigger.execute(trigger.id)

					self.updateKeypad(partition, u'state', kAlarmStateArmed)
					self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
					self.updateKeypad(partition, u'LEDReady', 'off')
					self.updateKeypad(partition, u'LEDArmed', 'on')	  # these update LEDs for partitions 1-8
					self.speak('speakTextArmed')
					self.trippedZoneList = []


		elif cmd == '653':
			# Partition Ready - Forced Arming Enabled
			# We don't do anything with this now.
			pass

		elif cmd == '654':
			# partition is in alarm due to zone violations or panic & fire alarm
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			keyp = " '" + keyp + "'"
			self.mylogger.log(1, u"Alarm TRIPPED! (Partition %d%s)" % (partition, keyp))
			self.updateKeypad(int(dat), u'state', kAlarmStateTripped)
			self.updateKeypad(int(dat), u'LEDMemory', 'on')	  # this updates LED for partitions 1-8
			self.triggerEvent(u'eventAlarmTripped')
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
				self.closeTheseZonesList = []

			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			keypstate = str(dev.states['state'])
			if partition == 1 and keypstate == kAlarmStateExitDelay:
				self.mylogger.log(1, u"Alarm Disarmed. (Partition %d '%s')" % (partition, keyp))

				#Only request bypassed zone list if we are not using IT-100
				if self.useSerial is False:
					self.sleep(1)    #add delay if keybus buffer overruns. Only send partition 1 cmd since other partitions don't work
					self.txCmdList.append((kCmdNormal, '071' + str(partition) + '*1#'))		#triggers cmd 616 only if partition was in exit delay and cmd 750 is not sent.
			self.trippedZoneList = []
			self.updateKeypad(partition, u'state', kAlarmStateDisarmed)
			self.updateKeypad(partition, u'ArmedState', kAlarmArmedStateDisarmed)
			self.updateKeypad(partition, u'LEDArmed', 'off')
			self.updateKeypad(0, u'PanicState', kPanicStateNone)
			self.updateKeypad(partition, u'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, u'LEDReady', 'on')
			self.updateKeypad(partition, u'LEDBypass', 'off')

			#self.triggerEvent(u'eventAlarmDisarmed') #use cmd 750 & 751 triggers
			#self.speak('speakTextDisarmed')  #use cmd 750 & 751 triggers


		elif cmd == '656':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Exit Delay. (Partition %d '%s')" % (partition, keyp))
			self.updateKeypad(partition, u'state', kAlarmStateExitDelay)
			self.updateKeypad(partition, u'LEDArmed', 'on')
			#keyp = indigo.devices[self.keypadList[partition]]
			#LEDMemoryState = keyp.states["LEDMemory"]
			self.updateKeypad(partition, u'LEDMemory', 'off')
			if "DSC_Alarm_Memory" in indigo.variables:
				indigo.variable.updateValue("DSC_Alarm_Memory", value = "no tripped zones")
			self.speak('speakTextArming')

		elif cmd == '657':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Entry Delay. (Partition %d '%s')" % (partition, keyp))
			self.updateKeypad(partition, u'state', kAlarmStateEntryDelay)
			self.speak('speakTextEntryDelay')

		elif cmd == '663':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Keypad Chime Enabled. (Partition %d '%s')" % (partition, keyp))
			self.updateKeypad(partition, u'KeypadChime', kKeypadStateChimeEnabled)

		elif cmd == '664':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Keypad Chime Disabled. (Partition %d '%s')" % (partition, keyp))
			self.updateKeypad(partition, u'KeypadChime', kKeypadStateChimeDisabled)

		elif cmd == '672':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Alarm Panel Failed to Arm. (Partition %d '%s')" % (partition, keyp))
			self.triggerEvent(u'eventFailToArm')
			self.speak('speakTextFailedToArm')

		elif cmd == '673':
			#sends busy reply for partitions that are not defined by the plugin
			partition = int(dat)
			self.mylogger.log(3, u"Partition %d Busy." % (partition))

		elif cmd == '700':
			m = re.search(r'^(.)..(..)$', dat)
			if m:
				(partition, user) = (int(m.group(1)), m.group(2))
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				#self.userCodeList = self.pluginPrefs[u'userCode'].split(",")
				#self.userLabelList = self.pluginPrefs[u'userLabel'].split(",")
				#self.userLabelDict = dict(zip(self.userCodeList, self.userLabelList))
				keyu = self.userLabelDict.get(user, "")
				if keyu:
					keyu = " '" + keyu +"'"
				self.mylogger.log(1, u"Alarm Panel Armed by User %s%s. (Partition %d '%s')" % (user, keyu, partition, keyp))
				#No info on whether stay or away armed, but cmd 652 is also triggered with that info
				self.updateKeypad(partition, u'state', kAlarmStateArmed)
				self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
				self.updateKeypad(partition, u'LEDReady', 'off')
				self.updateKeypad(partition, u'LEDArmed', 'on')
				self.speak('speakTextArmed')
				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == u'userArmed':
						if trigger.pluginProps[u'userCode'] == user:
							indigo.trigger.execute(trigger.id)

		elif cmd == '701':
			#special arming, e.g. IndigoTouch on iPhone
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(2, u"Alarm Panel Specially Armed. (Partition %d '%s')" % (partition, keyp))
			self.updateKeypad(partition, u'state', kAlarmStateArmed)
			self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, u'LEDReady', 'off')
			self.updateKeypad(partition, u'LEDArmed', 'on')
			self.speak('speakTextArmed')


		elif cmd == '702':
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Alarm Panel Armed. (Partition %d '%s' with zone(s) bypass)" % (partition, keyp))
			self.updateKeypad(partition, u'state', kAlarmStateArmed)
			self.updateKeypad(partition, u'ReadyState', kReadyStateFalse)
			self.updateKeypad(partition, u'LEDReady', 'off')
			self.updateKeypad(partition, u'LEDArmed', 'on')
			self.updateKeypad(partition, u'LEDBypass', 'on')
			self.speak('speakTextArmed')


		elif cmd == '750':
			# this command is send after user disarms an alarm that was tripping or not tripping (vs cmd 655).
			m = re.search(r'^(.)..(..)$', dat)
			if m:
				(partition, user) = (int(m.group(1)), m.group(2))
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				#self.userCodeList = self.pluginPrefs[u'userCode'].split(",")
				#self.userLabelList = self.pluginPrefs[u'userLabel'].split(",")
				#self.userLabelDict = dict(zip(self.userCodeList, self.userLabelList))
				keyu = self.userLabelDict.get(user, "")
				if keyu:
					keyu = " '" + keyu +"'"
				self.mylogger.log(1, u"Alarm Panel Disarmed by User %s%s. (Partition %d '%s')" % (user, keyu, partition, keyp))
				self.sendEmailDisarm(u"Alarm Panel Disarmed by User %s%s. (Partition %d '%s')" % (user, keyu, partition, keyp))
				if "DSC_Last_User_Disarm" in indigo.variables:
					indigo.variable.updateValue("DSC_Last_User_Disarm", value = "User " + user + keyu)

				# self.trippedZoneList = []    #We do not want to delete list of tripped zones here
				self.updateKeypad(partition, u'state', kAlarmStateDisarmed)
				self.updateKeypad(partition, u'ArmedState', kAlarmArmedStateDisarmed)
				self.updateKeypad(partition, u'LEDArmed', 'off')
				self.updateKeypad(0, u'PanicState', kPanicStateNone)
				self.updateKeypad(partition, u'ReadyState', kReadyStateTrue)
				self.updateKeypad(partition, u'LEDReady', 'on')
				self.updateKeypad(partition, u'LEDBypass', 'off')
				self.triggerEvent(u'eventAlarmDisarmed')
				self.speak('speakTextDisarmed')

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == u'userDisarmed':
						if trigger.pluginProps[u'userCode'] == user:
							indigo.trigger.execute(trigger.id)

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == u'userDisarmedPartition':
						if trigger.pluginProps[u'userCode'] == user and trigger.pluginProps[u'partitionNum'] == str(partition):
							indigo.trigger.execute(trigger.id)

				for trig in self.triggerList:
					trigger = indigo.triggers[trig]
					if trigger.pluginTypeId == u'eventPartitionDisarmed':
						if trigger.pluginProps[u'partitionNum'] == str(partition):
							indigo.trigger.execute(trigger.id)

			# If the alarm has been disarmed while it was tripped, update any zone states
			# that were closed during the break in.  We don't update them during the event
			# so that Indigo's zone states will represent a zone as tripped during the entire event.
			if self.repeatAlarmTripped is True:
				self.repeatAlarmTripped = False
				for zone in self.closeTheseZonesList:
					self.updateZoneState(zone, kZoneStateClosed)
				self.closeTheseZonesList = []

			#Only request bypassed zone list if we are on partition 1 and not using IT-100
			if (partition == 1) and (self.useSerial is False):
				self.sleep(1) #add delay if keybus buffer overruns. Only send partition 1 cmd since other partitions don't work
				#self.txCmdList.append((kCmdNormal, '071' + str(partition) + '*1#'))		#triggers cmd 616
				self.txCmdList.append((kCmdNormal, '0711*1#'))		#triggers cmd 616


		elif cmd == '751':
			#special opening (triggered by keyswitch but not by Indigo Touch)
			partition = int(dat)
			dev = indigo.devices[self.keypadList[partition]]
			keyp = str(dev.pluginProps['partitionName'])
			self.mylogger.log(1, u"Alarm Disarmed by Special Opening (Partition %d '%s')" % (partition, keyp))
			# self.trippedZoneList = []    #We do not want to delete list of tripped zones here
			self.updateKeypad(partition, u'state', kAlarmStateDisarmed)
			self.updateKeypad(partition, u'ArmedState', kAlarmArmedStateDisarmed)
			self.updateKeypad(partition, u'LEDArmed', 'off')
			self.updateKeypad(0, u'PanicState', kPanicStateNone)
			self.updateKeypad(partition, u'ReadyState', kReadyStateTrue)
			self.updateKeypad(partition, u'LEDReady', 'on')
			self.updateKeypad(partition, u'LEDBypass', 'off')

			self.triggerEvent(u'eventAlarmDisarmed')
			self.speak('speakTextDisarmed')

			for trig in self.triggerList:
				trigger = indigo.triggers[trig]
				if trigger.pluginTypeId == u'eventPartitionDisarmed':
					if trigger.pluginProps[u'partitionNum'] == str(partition):
						indigo.trigger.execute(trigger.id)

			#Only request bypassed zone list if we are not using IT-100
			if (partition == 1) and (self.useSerial is False):
				self.sleep(1) #add delay if keybus buffer overruns. Only send partition 1 cmd since other partitions don't work
				self.txCmdList.append((kCmdNormal, '0711*1#'))		#triggers cmd 616


		elif cmd == '800':
			self.mylogger.log(1, u"Alarm Panel Battery is low.")
			self.sendTroubleEmail(u"Alarm panel battery is low.")

		elif cmd == '801':
			self.mylogger.log(1, u"Alarm Panel Battery is now ok.")
			self.sendTroubleEmail(u"Alarm panel battery is now ok.")

		elif cmd == '802':
			self.mylogger.log(1, u"AC Power Lost.")
			self.sendTroubleEmail(u"AC Power Lost.")
			self.triggerEvent(u'eventNoticeAC_Trouble')

		elif cmd == '803':
			self.mylogger.log(1, u"AC Power Restored.")
			self.sendTroubleEmail(u"AC Power Restored.")
			self.triggerEvent(u'eventNoticeAC_Restore')

		elif cmd == '806':
			self.mylogger.log(1, u"An open circuit has been detected across the bell terminals.")
			self.sendTroubleEmail(u"An open circuit has been detected across the bell terminals.")

		elif cmd == '807':
			self.mylogger.log(1, u"The bell circuit has been restored.")
			self.sendTroubleEmail(u"The bell circuit has been restored.")

		elif cmd == '814':
			self.mylogger.log(1, u"FTC Trouble.")
			self.sendTroubleEmail(u"The panel has failed to communicate successfully to the monitoring station.")

		elif cmd == '840':
			partition = int(dat)
			if partition in self.keypadList:
				dev = indigo.devices[self.keypadList[partition]]
				keyp = str(dev.pluginProps['partitionName'])
				keyp = " '" + keyp + "'"
				self.mylogger.log(1, u"Trouble Status (LED ON). (Partition %d%s)" % (partition, keyp))
				self.updateKeypad(partition, u'LEDTrouble', 'on')   # this updates LED for partitions 1-8
				self.troubleClearedTimer = 0

		elif cmd == '841':
			#Sends Trouble off for all partitions, including undefined ones.
			partition = int(dat)
			self.mylogger.log(2, u"Trouble Status Restore (LED OFF). (Partition %d)" % (partition))
			self.updateKeypad(partition, u'LEDTrouble', 'off')  # this updates LED for partitions 1-8
			if self.troubleCode > 0:
				# If the trouble light goes off, set a 10 second timer.
				# If the light is still off after 10 seconds we'll clear our status
				# This is required because the panel turns the light off/on quickly
				# when the light is actually on.
				self.troubleClearedTimer = 10

		elif cmd == '849':
			self.mylogger.log(3, u"Received trouble code byte 0x%s" % dat)
			newCode = int(dat, 16)

			if newCode != self.troubleCode:
				self.troubleCode = newCode
				if self.troubleCode > 0:
					body = "Trouble Code Received:\n"
					if self.troubleCode & 1: body += "- Service is Required\n"
					if self.troubleCode & 2: body += "- AC Power Lost\n"
					if self.troubleCode & 4: body += "- Telephone Line Fault\n"
					if self.troubleCode & 8: body += "- Failure to Communicate\n"
					if self.troubleCode & 16: body += "- Sensor/Zone Fault\n"
					if self.troubleCode & 32: body += "- Sensor/Zone Tamper\n"
					if self.troubleCode & 64: body += "- Sensor/Zone Low Battery\n"
					if self.troubleCode & 128: body += "- Loss of Time\n"
					self.sendTroubleEmail(body)

		elif cmd == '851':
			self.mylogger.log(3, u"Partition Busy Restore. (Partition %d)" % int(dat))
		elif cmd == '896':
			self.mylogger.log(3, u"Keybus Fault")
		elif cmd == '897':
			self.mylogger.log(3, u"Keybus Fault Restore")
		elif cmd == '900':
			self.mylogger.logError(u"Code Required")

		elif cmd == '901':
			#this updates the virtual keypad
			#for char in dat:
			#	self.mylogger.log(3, u"LCD DEBUG: %d" % ord(char))
			m = re.search(r'^...(..)(.*)$', dat)
			if m:
				lcdText = re.sub(r'[^ a-zA-Z0-9_/\:-]+', ' ', m.group(2))
				half = len(lcdText)/2
				half1 = lcdText[:half]
				half2 = lcdText[half:]
				self.mylogger.log(3, u"LCD Update, Line 1:'%s' Line 2:'%s'" % (half1, half2))
				self.updateKeypad(0, u'LCDLine1', half1)
				self.updateKeypad(0, u'LCDLine2', half2)

		elif cmd == '903':
			m = re.search(r'^(.)(.)$', dat)
			if m:
				(ledName, ledState) = (kLedIndexList[int(m.group(1))], kLedStateList[int(m.group(2))])
				self.mylogger.log(3, u"LED '%s' is '%s'." % (ledName, ledState))

				if ledState == 'flashing':
					ledState = 'on'

				if ledName == 'Ready':
					self.updateKeypad(1, u'LEDReady', ledState)
				elif ledName == 'Armed':
					self.updateKeypad(1, u'LEDArmed', ledState)
				elif ledName == 'Trouble':
					self.updateKeypad(1, u'LEDTrouble', ledState)
				elif ledName == 'Bypass':
					self.updateKeypad(1, u'LEDBypass', ledState)
				elif ledName == 'Memory':
					self.updateKeypad(1, u'LEDMemory', ledState)


		elif cmd == '904':
			self.mylogger.log(3, u"Beep Status")

		elif cmd == '905':
			self.mylogger.log(3, u"Tone Status")

		elif cmd == '906':
			self.mylogger.log(3, u"Buzzer Status")

		elif cmd == '907':
			self.mylogger.log(3, u"Door Chime Status")

		elif cmd == '908':
			m = re.search(r'^(..)(..)(..)$', dat)
			if m:
				self.mylogger.log(3, u"DSC Software Version %s.%s" % (m.group(1), m.group(2)))
		else:
			#self.mylogger.log(3, u"RX: %s" % data)
			self.mylogger.log(3, u"Unrecognized command received (Cmd:%s Dat:%s Sum:%d)" % (cmd, dat, sum))

		return (cmd, dat)



	######################################################################################
	# Indigo Device State Updating
	######################################################################################

	# Updates temperature of DSC temperature sensor
	#
	def updateSensorTemp(self, sensorNum, key, temp):
		if temp > 127:
			temp = 127 - temp
		self.mylogger.log(3, u"Temp sensor %d %s temp now %d degrees." % (sensorNum, key, temp))
		if sensorNum in self.tempList.keys():
			if key == 'inside':
				self.tempList[sensorNum].updateStateOnServer(key=u"temperatureInside", value=temp)
			elif key == 'outside':
				self.tempList[sensorNum].updateStateOnServer(key=u"temperatureOutside", value=temp)
			elif key == 'cool':
				self.tempList[sensorNum].updateStateOnServer(key=u"setPointCool", value=temp)
			elif key == 'heat':
				self.tempList[sensorNum].updateStateOnServer(key=u"setPointHeat", value=temp)

			if self.tempList[sensorNum].pluginProps['zoneLogChanges'] == 1:
				self.mylogger.log(1, u"Temp sensor %d %s temp now %d degrees." % (sensorNum, key, temp))


	# Updates zone group
	#
	def updateZoneGroup(self, zoneGroupDevId):

		zoneGrp = indigo.devices[zoneGroupDevId]

		zoneGrp.updateStateOnServer(key=u"AnyMemberLastChangedTimer", value=0)
		zoneGrp.updateStateOnServer(key=u"AnyMemberLastChangedShort", value="0m")

		newState = kZoneGroupStateClosed
		for zoneId in self.zoneGroupList[zoneGroupDevId]:
			zoneState = indigo.devices[int(zoneId)].states[u'state']
			if (zoneState != kZoneStateClosed) and (newState != kZoneGroupStateTripped):
				if zoneState == kZoneStateOpen:
					newState = kZoneGroupStateOpen
				elif zoneState == kZoneStateTripped:
					newState = kZoneGroupStateTripped

		if zoneGrp.states[u'state'] != newState:
			zoneGrp.updateStateOnServer(key=u"EntireGroupLastChangedTimer", value=0)
			zoneGrp.updateStateOnServer(key=u"EntireGroupLastChangedShort", value="0m")
			zoneGrp.updateStateOnServer(key=u"state", value=newState)


	# Updates indigo variable instance var with new value varValue
	#
	def updateZoneState(self, zoneKey, newState):

		if zoneKey in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneKey]]
			#zoneType = zone.pluginProps['zoneType']
			#zonePartition = zone.pluginProps['zonePartition']

			# If the new state is different from the old state
			# then lets update timers and set the new state
			if zone.states[u'state'] != newState:
				# This is a new state, update all states and timers
				zone.updateStateOnServer(key=u"LastChangedShort", value="0m")
				zone.updateStateOnServer(key=u"LastChangedTimer", value=0)
				zone.updateStateOnServer(key=u"state", value=newState)

				# Check if this zone is assigned to a zone group so we can update it
				for devId in self.zoneGroupList:
					#self.mylogger.log(3, u"Zone Group id: %s contains %s" % (zone.id,self.zoneGroupList[devId]))
					if str(zone.id) in self.zoneGroupList[devId]:
						self.updateZoneGroup(devId)

				if 'var' in zone.pluginProps.keys():
					self.updateVariable(zone.pluginProps['var'], newState)

				if newState == kZoneStateTripped:
					self.mylogger.log(1, u"Alarm Zone '%s' TRIPPED!" % zone.name)

				if zone.pluginProps['zoneLogChanges'] == 1:
					if newState == kZoneStateOpen:
						self.mylogger.log(1, u"Alarm Zone '%s' Opened." % zone.name)
					elif newState == kZoneStateClosed:
						self.mylogger.log(1, u"Alarm Zone '%s' Closed." % zone.name)

	def updateZoneBypass(self, zoneKey, newState):

		if zoneKey in self.zoneList.keys():
			zone = indigo.devices[self.zoneList[zoneKey]]
			#zoneType = zone.pluginProps['zoneType']

			# If the new bypass state is different from the old state
			# then lets set the new state
			if zone.states[u'bypass'] != newState:
				# This is a new bypass state, update all states
				zone.updateStateOnServer(key=u"bypass", value=newState)

				if 'var' in zone.pluginProps.keys():
					self.updateVariable(zone.pluginProps['var'], newState)

				#if zone.pluginProps['zoneLogChanges'] == 1:
				if newState == kZoneBypassYes:
					self.mylogger.log(1, u"Alarm Zone '%s' Bypassed." % zone.name)
				elif newState == kZoneBypassNo:
					self.mylogger.log(1, u"Alarm Zone '%s' Bypass Cancelled." % zone.name)


	def updateKeypad(self, partition, stateName, newState):

		self.mylogger.log(4, u"Updating state %s for keypad on partition %u to %s." % (stateName, partition, newState))

		# If we're updating the main keypad state, update the variable too
		if stateName == u'state':
			self.updateVariable(self.pluginPrefs[u'variableState'], newState)

		if partition == 0:
			for keyk in self.keypadList.keys():
				keyp = indigo.devices[self.keypadList[keyk]]
				keyp.updateStateOnServer(key=stateName, value=newState)
			return

		if partition in self.keypadList.keys():
			keyp = indigo.devices[self.keypadList[partition]]
			keyp.updateStateOnServer(key=stateName, value=newState)


	######################################################################################
	# Misc
	######################################################################################

	def sendZoneTrippedEmail(self):

		if (len(self.configEmailUrgent) == 0) or (len(self.trippedZoneList) == 0):
			return

		theBody = "The following zone(s) have been tripped:\n\n"

		for zoneNum in self.trippedZoneList:

			if zoneNum in self.closeTheseZonesList:
				stateNow = "closed"
			else:
				stateNow = "open"

			zone = indigo.devices[self.zoneList[zoneNum]]

			theBody += "%s (currently %s)\n" % (zone.name, stateNow)

		theBody += "\n--\nDSC Alarm Plugin\n\n"

		self.mylogger.log(1, u"Sending zone tripped email to %s." % self.configEmailUrgent)

		contentPrefix = self.pluginPrefs.get(u'emailUrgentContent', '')
		if len(contentPrefix) > 0:
			theBody = contentPrefix + "\n\n" + theBody

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=theBody)

########################################################################################
############# Kidney514 ##########  Sending email of who is disarming
########################################################################################

	def sendEmailDisarm(self, bodyText):

		if len(self.configEmailDisarm) == 0:
			return

		self.mylogger.log(1, u"Sending Disarmed by: email to %s." % self.configEmailDisarm)

		contentPrefix = self.pluginPrefs.get(u'EmailDisarmContent', '')
		if len(contentPrefix) > 0:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailDisarm, subject=self.configEmailDisarmSubject, body=bodyText)

########################################################################################
########################################################################################


	def sendTroubleEmail(self, bodyText):

		if len(self.configEmailNotice) == 0:
			return

		self.mylogger.log(1, u"Sending trouble email to %s." % self.configEmailNotice)

		contentPrefix = self.pluginPrefs.get(u'updaterEmailContent', '')
		if len(contentPrefix) > 0:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailNotice, subject=self.configEmailNoticeSubject, body=bodyText)


	def sendPanicEmail(self, bodyText):

		if len(self.configEmailUrgent) == 0:
			return

		self.mylogger.log(1, u"Sending panic alert email to %s." % self.configEmailUrgent)

		contentPrefix = self.pluginPrefs.get(u'emailUrgentContent', '')
		if len(contentPrefix) > 0:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=bodyText)
		#if no email address is specified the speak part does not trigger
		say = self.pluginPrefs['speakTextPanic'] + ' Keypad: ' + bodyText + '.'
		self.sayThis(say)



	def sendDuressEmail(self, bodyText):

		if len(self.configEmailUrgent) == 0:
			return

		self.mylogger.log(1, u"Sending duress alarm email to %s." % self.configEmailUrgent)

		contentPrefix = self.pluginPrefs.get(u'emailUrgentContent', '')
		if len(contentPrefix) > 0:
			bodyText = contentPrefix + "\n\n" + bodyText

		indigo.server.sendEmailTo(self.configEmailUrgent, subject=self.configEmailUrgentSubject, body=bodyText)
		#if no email address specified the speak part does not trigger
		say = self.pluginPrefs['speakTextPanic'] + ' Keypad: ' + bodyText + '.'
		self.sayThis(say)



	def sayThis(self, text):
		self.mylogger.log(3, u"SAY: %s" % text)
		#The default variable is DSC_Alarm_Text
		if self.configSpeakVariable is not None:
			if self.configSpeakVariable in indigo.variables:
				indigo.variable.updateValue(self.configSpeakVariable, value=text)
		else:
			indigo.server.speak(text)


	def speak(self, textId):
		self.mylogger.log(3, u"ID: %s" % textId)
		if self.pluginPrefs['speakingEnabled'] is False:
			return

		if len(self.pluginPrefs[textId]) == 0:
			return

		if textId == 'speakTextFailedToArm':
			zones = 0
			zoneText = ''
			for zoneNum in self.zoneList.keys():
				zone = indigo.devices[self.zoneList[zoneNum]]
				if zone.states[u'state.open'] is True:
					if zones > 0:
						zoneText += ', '
					zoneText += zone.name.replace("Alarm_", "")
					zones += 1

			if zones == 0:
				say = self.pluginPrefs[textId]
			if zones == 1:
				say = self.pluginPrefs[textId] + '  The ' + zoneText + ' is open.'
			else:
				say = self.pluginPrefs[textId] + '  The following zones are open: ' + zoneText + '.'

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
				say = self.pluginPrefs[textId] + '  The ' + zoneText + ' has been tripped.'
			else:
				say = self.pluginPrefs[textId] + '  The following zones have been tripped: ' + zoneText + '.'

			self.sayThis(say)


		else:
			self.sayThis(self.pluginPrefs[textId])


	# Updates indigo variable instance var with new value varValue
	#
	def updateVariable(self, varID, varValue):

		if self.createVariables is False:
			return

		#self.mylogger.log(3, u"Variable: %s" % varID)

		if varID is None:
			return

		if varID in indigo.variables:
			indigo.variable.updateValue(varID, value=varValue)


	# Converts given time in minutes to a human format
	# 3m, 5h, 2d, etc.
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



	######################################################################################
	# Concurrent Thread
	######################################################################################

	def runConcurrentThread(self):
		self.mylogger.log(3, u"runConcurrentThread called")
		self.minuteTracker = time.time() + 60
		self.nextUpdateCheckTime = 0

		# While Indigo hasn't told us to shutdown
		while self.shutdown is False:

			self.timeNow = time.time()

			if self.state == self.States.STARTUP:
				self.mylogger.log(3, u"STATE: Startup")

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
				self.mylogger.log(1, "Plugin will attempt to re-initialize again in %u minutes." % self.currentHoldRetryTime)
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
					#self.mylogger.logError('Error opening port, will retry in %u minutes.' % self.currentHoldRetryTime)
					self.state = self.States.HOLD_RETRY

			elif self.state == self.States.SO_CONNECT:
				err = True

				# Read packet to clear the port of the 5053 login request
				self.readPacket()

				attemptLogin = True
				while attemptLogin is True:
					attemptLogin = False
					rx = self.sendPacket('005' + self.pluginPrefs[u'TwoDS_Password'], waitFor='505')
					if len(rx) == 0:
						self.mylogger.logError('Timeout waiting for Envisalink to respond to login request.')
					else:
						rx = int(rx)
						if rx == 0:
							self.mylogger.logError('Envisalink refused login request.')
						elif rx == 1:
							err = False
							self.mylogger.log(1, "Connected to Envisalink.")
						elif rx == 3:
							# 2DS sent login request, retry (Happens when socket is first opened)
							self.mylogger.log(3, u"Received login request, retrying login...")
							attemptLogin = True
						else:
							self.mylogger.logError('Unknown response from Envisalink login request.')

				# This delay is required otherwise 2DS locks up
				self.sleep(1)

				if err is True:
					self.state = self.States.HOLD_RETRY
				else:
					self.state = self.States.ENABLE_TIME_BROADCAST


			elif self.state == self.States.ENABLE_TIME_BROADCAST:

				# Enable time broadcast
				self.mylogger.log(2, "Enabling Time Broadcast")
				rx = self.sendPacket('0561')
				if len(rx) > 0:
					self.mylogger.log(2, u"Time Broadcast enabled.")
					self.state = self.States.BOTH_PING
				else:
					self.mylogger.logError(u'Error enabling Time Broadcast.')
					self.state = self.States.HOLD_RETRY

			elif self.state == self.States.BOTH_PING:

				#Ping the panel to confirm we are in communication
				err = True
				self.mylogger.log(2, u"Pinging the panel to test communication...")
				rx = self.sendPacket('000')
				if len(rx) > 0:
					self.mylogger.log(2, u"Ping was successful.")
					err = False
				else:
					self.mylogger.logError('Error pinging panel, aborting.')

				if err is True:
					self.state = self.States.HOLD_RETRY
				else:
					#Request a full state update
					self.mylogger.log(2, "Requesting a full state update.")
					rx = self.sendPacket('001')
					if len(rx) == 0:
						self.mylogger.logError('Error getting state update.')
						self.state = self.States.HOLD_RETRY
					else:
						self.mylogger.log(2, "State update request successful, initialization complete, starting normal operation.")
						self.state = self.States.BOTH_POLL

			elif self.state == self.States.BOTH_POLL:
				if self.configRead is False:
					self.state = self.States.STARTUP
				else:

					if (self.useSerial is False) and (self.timeNow > self.nextPingTime):
						#self.mylogger.log(1,"Pinging 2DS")
						self.txCmdList.append((kCmdNormal, '000'))
						self.nextPingTime = self.timeNow + kPingInterval

					if len(self.txCmdList) > 0:
						(cmdType, data) = self.txCmdList[0]
						if cmdType == kCmdNormal:
							txRsp = self.sendPacket(data)
							if txRsp == '-':
								# If we receive - socket has closed, lets re-init
								self.mylogger.logError('Tried to send data but socket seems to have closed.  Trying to re-initialize.')
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
							self.mylogger.logError('Tried to read data but socket seems to have closed.  Trying to re-initialize.')
							self.state = self.States.BOTH_INIT


			# Check if the trouble timer counter is timing
			# We need to know if the trouble light has remained off
			# for a few seconds before we assume the trouble is cleared
			if self.troubleClearedTimer > 0:
				self.troubleClearedTimer -= 1
				if self.troubleClearedTimer == 0:
					self.troubleCode = 0
					self.sendTroubleEmail(u"Trouble Code Cleared.")

			if self.repeatAlarmTripped is True:
				#timeNow = time.time()
				if self.timeNow >= self.repeatAlarmTrippedNext:
					self.repeatAlarmTrippedNext = self.timeNow + 12
					self.speak('speakTextTripped')


			# If a minute has elapsed
			if self.timeNow >= self.minuteTracker:

				# Do we need to check for a new version?
				self.updater.checkVersionPoll()

				# Increment all zone changed timers
				self.minuteTracker += 60
				for zoneKey in self.zoneList.keys():
					zone = indigo.devices[self.zoneList[zoneKey]]
					tmr = zone.states[u"LastChangedTimer"] + 1
					zone.updateStateOnServer(key=u"LastChangedTimer", value=tmr)
					zone.updateStateOnServer(key=u"LastChangedShort", value=self.getShortTime(tmr))

				for zoneGroupDeviceId in self.zoneGroupList:
					zoneGroupDevice = indigo.devices[zoneGroupDeviceId]
					tmr = zoneGroupDevice.states[u"AnyMemberLastChangedTimer"] + 1
					zoneGroupDevice.updateStateOnServer(key=u"AnyMemberLastChangedTimer", value=tmr)
					zoneGroupDevice.updateStateOnServer(key=u"AnyMemberLastChangedShort", value=self.getShortTime(tmr))
					tmr = zoneGroupDevice.states[u"EntireGroupLastChangedTimer"] + 1
					zoneGroupDevice.updateStateOnServer(key=u"EntireGroupLastChangedTimer", value=tmr)
					zoneGroupDevice.updateStateOnServer(key=u"EntireGroupLastChangedShort", value=self.getShortTime(tmr))


		self.closePort()
		self.mylogger.log(3, u"Exiting Concurrent Thread")


	def stopConcurrentThread(self):
		self.mylogger.log(3, u"stopConcurrentThread called")
		self.shutdown = True
		self.mylogger.log(3, u"Exiting stopConcurrentThread")

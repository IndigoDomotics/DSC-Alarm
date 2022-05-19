# DSC Alarm Plugin

This plugin interfaces Indigo to a DSC PowerSeries alarm system using one of the interfaces below. It lets Indigo see the status of the entire alarm system. Triggers can be created for any alarm or zone change, actions can be created to Arm, Disarm, or trip the alarm. 

The plugin also maintains timers to keep track of how long any doors and windows have been opened, as well as how long it's been since it's seen activity in certain areas. These timers can be used to turn off the HVAC system if the wife is airing out the house, or turn off lights in areas of the house that aren't occupied.

## Information and Support
Version 2022.0.1 with changes from Monstergerm has been released. This version is compatible with Python 2 (using Server API 2.0) or Python 3 (using Server API 3.0[default]). The plugin also adds a number of minor improvements over v2.2.2.
 Minor tweaks to code
 Removed outdated version check code
 Updated logging system to six levels
 Changed time sync routine and added Time Sync Action
 Added more zone attributes
 Implemented custom state GUI icons for Indigo desktop app and Indigo Touch

Version 2.0 with changes from Monstergerm has been released.  Read the DSC plugin v2 Release Notes.pdf file for more information.

For Installation and Information details please see this [forum post](http://forums.indigodomo.com/viewtopic.php?f=56&t=10287).

If you need help, please post a topic in this  [user forum](http://forums.indigodomo.com/viewforum.php?f=56).

## Downloading for use

If you are a user and just want to download and install the plugin, click on the "Clone or download" button and then "Download Zip" and it will download the plugin and readme file to a folder named "DSC-Alarm-master" in your Downloads directory. Once it's downloaded just open that folder and double-click on the "DSC Alarm.indigoPlugin" file to have the client install and enable it for you.

## Contributing

If you want to contribute, just clone the repository in your account, make your changes, and issue a pull request. Make sure that you describe the change you're making thoroughly - this will help the repository managers accept your request more quickly.

## Terms

Perceptive Automation is hosting this repository and will do minimal management. Unless a pull request has no description or upon cursory observation has some obvious issue, pull requests will be accepted without any testing by us. We may choose to delegate commit privledges to other users at some point in the future.

Perceptive Automation doesn't guarantee anything about this plugin - that this plugin works or does what the description above states, so use at your own risk. 

## Plugin ID

Here's the plugin ID in case you need to programmatically restart the plugin:

**Plugin ID**: com.frightideas.indigoplugin.dscAlarm

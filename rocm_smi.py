#!/usr/bin/env python
""" ROCm-SMI (System Management Interface) Tool

This tool provides a user-friendly interface for manipulating
the ROCK (Radeon Open Compute Kernel) via sysfs files.
Please view the README.md file for more information
"""

from __future__ import print_function, division
import os
import argparse
import re
import sys
import subprocess
from subprocess import check_output
import json
import collections
import logging
if hasattr(__builtins__, 'raw_input'):
    input = raw_input

# Version of the JSON output used to save clocks
JSON_VERSION = 1

# Set to 1 if an error occurs
RETCODE = 0

def relaunchAsSudo():
    """ Relaunch the SMI as sudo

    To write to sysfs, the SMI requires root access. Use execvp to relaunch the
    script with sudo privileges
    """
    if os.geteuid() != 0:
        os.execvp('sudo', ['sudo'] + sys.argv)

drmprefix = '/sys/class/drm'
hwmonprefix = '/sys/class/hwmon'
powerprefix = '/sys/kernel/debug/dri/'

headerSpacer = '='*24
logSpacer = headerSpacer * 4

valuePaths = {
    'id' : {'prefix' : drmprefix, 'filepath' : 'device', 'needsparse' : True},
    'vbios' : {'prefix' : drmprefix, 'filepath' : 'vbios_version', 'needsparse' : False},
    'perf' : {'prefix' : drmprefix, 'filepath' : 'power_dpm_force_performance_level', 'needsparse' : False},
    'sclk_od' : {'prefix' : drmprefix, 'filepath' : 'pp_sclk_od', 'needsparse' : False},
    'mclk_od' : {'prefix' : drmprefix, 'filepath' : 'pp_mclk_od', 'needsparse' : False},
    'sclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_sclk', 'needsparse' : False},
    'mclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_mclk', 'needsparse' : False},
    'pclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_pcie', 'needsparse' : False},
    'clk_voltage' : {'prefix' : drmprefix, 'filepath' : 'pp_od_clk_voltage', 'needsparse' : False},
    'profile' : {'prefix' : drmprefix, 'filepath' : 'pp_power_profile_mode', 'needsparse' : False},
    'use' : {'prefix' : drmprefix, 'filepath' : 'gpu_busy_percent', 'needsparse' : False},
    'pcie_bw' : {'prefix' : drmprefix, 'filepath' : 'pcie_bw', 'needsparse' : False},
    'vendor' : {'prefix' : drmprefix, 'filepath' : 'vendor', 'needsparse' : False},
    'fan' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1', 'needsparse' : False},
    'fanmax' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1_max', 'needsparse' : False},
    'fanmode' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1_enable', 'needsparse' : False},
    'temp' : {'prefix' : hwmonprefix, 'filepath' : 'temp1_input', 'needsparse' : True},
    'power' : {'prefix' : hwmonprefix, 'filepath' : 'power1_average', 'needsparse' : True},
    'power_cap' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap', 'needsparse' : False},
    'power_cap_max' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap_max', 'needsparse' : False},
    'power_cap_min' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap_min', 'needsparse' : False}
}


def getSysfsValue(device, key):
    """ Return the desired SysFS value for a specified device

    Parameters:
    device -- Device to return the desired value
    value -- SysFS value to return (defined in dict above)
    """
    pathDict = valuePaths[key]
    fileValue = ''
    filePath = os.path.join(pathDict['prefix'], device, 'device', pathDict['filepath'])

    if pathDict['prefix'] == hwmonprefix:
        # HW Monitor values have a different path structure
        if not getHwmonFromDevice(device):
            return None
        filePath = os.path.join(getHwmonFromDevice(device), pathDict['filepath'])

    if not os.path.isfile(filePath):
        return None

    # Use try since some sysfs files like power1_average will throw -EINVAL
    # instead of giving something useful.
    try:
        with open(filePath, 'r') as fileContents:
            fileValue = fileContents.read().rstrip('\n')
    except:
        printLog(device, 'WARNING: Unable to read ' + filePath)
        return None

    # Some sysfs files aren't a single line of text
    if pathDict['needsparse']:
        fileValue = parseSysfsValue(key, fileValue)

    if fileValue == '':
        printLog(device, 'WARNING: Empty SysFS value: ' + key)

    return fileValue


def parseSysfsValue(key, value):
    """ Parse the sysfs value string

    Parameters:
    value -- SysFS value to parse

    Some SysFS files aren't a single line/string, so we need to parse it
    to get the desired value
    """
    if key == 'id':
        # Strip the 0x prefix
        return value[2:]
    if key == 'temp':
        # Convert from millidegrees
        return int(value) / 1000
    if key == 'power':
        # power1_average returns the value in microwatts. However, if power is not
        # available, it will return "Invalid Argument"
        if value.isdigit():
            return float(value) / 1000 / 1000

    return ''


def parseDeviceNumber(deviceNum):
    """ Parse the device number, returning the format of card#

    Parameters:
    deviceNum -- Device number to parse
    """
    return 'card' + str(deviceNum)


def parseDeviceName(deviceName):
    """ Parse the device name, which is of the format card#.

    Parameters:
    deviceName -- Device name to parse
    """
    return deviceName[4:]


def printLog(device, log):
    """ Print out to the SMI log.

    Parameters:
    device -- Device that the log will reference
    log -- String to print to the log
    """
    for line in log.split('\n'):
        print('GPU[', parseDeviceName(device), '] \t\t: ', line, sep='')


def doesDeviceExist(device):
    """ Check whether the specified device exists in sysfs.

    Parameters:
    device -- Device to check for existence
    """
    if os.path.exists(os.path.join(drmprefix, device)) == 0:
        return False
    return True


def getPid(name):
    """ Get the process id of a specific application """
    return check_output(["pidof", name])


def confirmOutOfSpecWarning(autoRespond):
    """ Print the warning for running outside of specification and prompt user to accept the terms.

    Parameters:
    autoRespond -- Response to automatically provide for all prompts
    """

    print('''
          ******WARNING******\n
          Operating your AMD GPU outside of official AMD specifications or outside of
          factory settings, including but not limited to the conducting of overclocking,
          over-volting or under-volting (including use of this interface software,
          even if such software has been directly or indirectly provided by AMD or otherwise
          affiliated in any way with AMD), may cause damage to your AMD GPU, system components
          and/or result in system failure, as well as cause other problems.
          DAMAGES CAUSED BY USE OF YOUR AMD GPU OUTSIDE OF OFFICIAL AMD SPECIFICATIONS OR
          OUTSIDE OF FACTORY SETTINGS ARE NOT COVERED UNDER ANY AMD PRODUCT WARRANTY AND
          MAY NOT BE COVERED BY YOUR BOARD OR SYSTEM MANUFACTURER'S WARRANTY.
          Please use this utility with caution.
          ''')
    if not autoRespond:
        user_input = input('Do you accept these terms? [y/N] ')
    else:
        user_input = autoRespond
    if user_input in ['Yes', 'yes', 'y', 'Y', 'YES']:
        return
    else:
        sys.exit('Confirmation not given. Exiting without setting value')


def isDPMAvailable(device):
    """ Check if DPM is available for a specified device.

    Parameters:
    device -- Device to check for DPM availability
    """
    if not doesDeviceExist(device) or os.path.isfile(os.path.join(drmprefix, device, 'device', 'power_dpm_state')) == 0:
        return False
    return True


def getNumProfileArgs(device):
    """ Get the number of Power Profile fields for a specific device

    This varies per ASIC, so ensure that we get the right number of arguments

    Parameters:
    device -- Device to get the number of Power Profile fields
    """

    profile = getSysfsValue(device, 'profile')
    numHiddenFields = 0
    if not profile:
        return 0
    # Get the 1st line (column names)
    fields = profile.splitlines()[0]
    # SMU7 has 2 hidden fields for SclkProfileEnable and MclkProfileEnable
    if 'SCLK_UP_HYST' in fields:
        numHiddenFields = 2
    # Subtract 2 to remove NUM and MODE NAME, since they're not valid Profile fields
    return len(fields.split()) - 2 + numHiddenFields


def verifySetProfile(device, profile):
    """ Verify data from user to set as Power Profile.

    Ensure that we can set the profile, with Profiles being supported and
    the profile being passed in being valid

    Parameters:
    device -- Device to verify Profile variables
    """
    global RETCODE
    if not isDPMAvailable(device):
        printLog(device, 'DPM not available - cannot specify profile.')
        RETCODE = 1
        return False

    # If it's 1 number, we're setting the level, not the Custom Profile
    if profile.isdigit():
        maxProfileLevel = getMaxLevel(device, 'profile')
        if maxProfileLevel is None:
            printLog(device, 'Cannot set profile, unable to obtain max level')
            return False
        if int(profile) > maxProfileLevel:
            printLog(device, 'Cannot set profile to level ' + str(profile) + ', max level is ' + str(maxProfileLevel))
            return False
        return True
    # If we get a string, split it into elements to make it a list
    elif isinstance(profile, str):
        if profile == 'reset':
            printLog(device, 'Reset no longer accepted as a Power Profile')
            return False
        else:
            profileList = profile.strip().split(' ')
    elif isinstance(profile, collections.Iterable):
        profileList = profile
    else:
        printLog(device, 'Unsupported profile argument : ' + str(profile))
        return False
    numProfileArgs = getNumProfileArgs(device)
    if numProfileArgs == 0:
        printLog(device, 'Power Profiles not supported')
        return False
    if len(profileList) != numProfileArgs:
        printLog(device, 'Cannot set profile, must be 1 or ' + str(numProfileArgs) + ' values')
        RETCODE = 1
        return False

    return True


def getProfile(device):
    """ Get either the current profile level, or the custom profile

    The CUSTOM profile might be set, or a specific profile level may have been selected
    Return either a single digit for a non-CUSTOM profile, or return the CUSTOM profile

    Parameters:
    device -- Device to return the current profile
    """
    profiles = getSysfsValue(device, 'profile')
    profile = ''
    custom = ''
    asic = ''
    level = ''
    numArgs = getNumProfileArgs(device)
    for line in profiles.splitlines():
        if re.match(r'.*SCLK_UP_HYST./*', line):
            asic = 'SMU7'
            continue
        if re.match(r'.*\*.*', line):
            level = line.split()[0]
            if re.match(r'.*CUSTOM.*', line):
                # Ditch the NUM and NAME, which end with a : before the profile values
                # Then put it into single words via split
                custom = line.split(':')[1].split()
            break
    if not custom:
        return level
    # We need some special parsing for SMU7 if it's a CUSTOM profile
    if asic == 'SMU7' and custom:
        sclk = custom[0:3]
        mclk = custom[3:]
        if sclk[0] == '-':
            sclkStr = '0 0 0 0'
        else:
            sclkStr = '1 ' + ' '.join(sclk)
        if mclk[0] == '-':
            mclkStr = '0 0 0 0'
        else:
            mclkStr = '1 ' + ' '.join(mclk)
        customStr = sclkStr + ' ' + mclkStr
    else:
        customStr = ' '.join(custom[-numArgs:])
    return customStr


def writeProfileSysfs(device, value):
    """ Write to the Power Profile sysfs file

    This function is different from a regular sysfs file as it could involve
    parsing of the data first.

    Parameters:
    device -- Device to write the Power Profile info
    value -- Value to write to the sysfs file
    """
    if not verifySetProfile(device, value):
        return

    # Perf Level must be set to manual for a Power Profile to be specified
    # This is new compared to previous versions of the Power Profile
    setPerfLevel(device, 'manual')
    profilePath = os.path.join(drmprefix, device, 'device', 'pp_power_profile_mode')
    maxLevel = getMaxLevel(device, 'profile')
    if maxLevel is None:
        printLog(device, 'Cannot set profile, max level could not be obtained')
        return False
    # If it's a single number, then we're choosing the Power Profile, not setting CUSTOM
    if isinstance(value, str) and len(value) == 1:
        profileString = value
    # Otherwise, we're setting the CUSTOM profile
    elif value.isdigit():
        profileString = str(value)
    elif isinstance(value, str) and len(value) > 1:
        if maxLevel is not None:
            # Prepend the Max Level of Profiles since that will always be the CUSTOM profile
            profileString = str(maxLevel) + value
    else:
        printLog(device, 'Invalid input argument ' + value)
        return False
    if writeToSysfs(profilePath, profileString):
        return True
    return False


def writeToSysfs(fsFile, fsValue):
    """ Write to a sysfs file.

    Parameters:
    fsFile -- Path to the sysfs file to modify
    fsValue -- Value to write to the sysfs file
    """
    global RETCODE
    if not os.path.isfile(fsFile):
        print('Cannot write to sysfs file ' + fsFile + '. File does not exist', sep='')
        RETCODE = 1
        return False
    try:
        logging.debug('Writing value \'' + fsValue + '\' to file \'' + fsFile + '\'')
        with open(fsFile, 'w') as fs:
            fs.write(fsValue + '\n') # Certain sysfs files require \n at the end
    except (IOError, OSError):
        print('Unable to write to sysfs file ' + fsFile)
        RETCODE = 1
        return False
    return True


def listDevices(showall):
    """ Return a list of GPU devices.

    Parameters:
    showall -- Boolean whether we should show all devices, or just AMD devices
    """

    devicelist = [device for device in os.listdir(drmprefix) if re.match(r'^card\d+$', device) and (isAmdDevice(device) or showall)]
    devicelist.sort()
    return devicelist


def listAmdHwMons():
    """Return a list of AMD HW Monitors."""
    hwmons = []

    for mon in os.listdir(hwmonprefix):
        tempname = os.path.join(hwmonprefix, mon, 'name')
        if os.path.isfile(tempname):
            with open(tempname, 'r') as tempmon:
                drivername = tempmon.read().rstrip('\n')
                if drivername in ['radeon', 'amdgpu']:
                    hwmons.append(os.path.join(hwmonprefix, mon))
    return hwmons


def getHwmonFromDevice(device):
    """ Return the corresponding HW Monitor for a specified GPU device.

    Parameters:
    device -- Device to return the corresponding HW Monitor
    """
    drmdev = os.path.realpath(os.path.join(drmprefix, device, 'device'))
    for hwmon in listAmdHwMons():
        if os.path.realpath(os.path.join(hwmon, 'device')) == drmdev:
            return hwmon
    return None


def getFanSpeed(device):
    """ Return the fan speed (%) for a specified device.

    Parameters:
    device -- Device to return the current fan speed
    """

    fanLevel = getSysfsValue(device, 'fan')
    fanMax = getSysfsValue(device, 'fanmax')
    if not fanLevel or not fanMax:
        return 0
    return round((float(fanLevel) / float(fanMax)) * 100, 2)


def getCurrentClock(device, clock, clocktype):
    """ Return the current clock frequency for a specified device.

    Parameters:
    device -- Device to return the clock frequency
    clock -- [gpu|mem|pcie] Return the GPU (gpu), GPU Memory (mem) or PCIE (pcie) clock frequency
    clocktype -- [freq|level] Return either the clock frequency (freq) or clock level (level)
    """
    currClk = ''

    if clock == 'gpu':
        currClocks = getSysfsValue(device, 'sclk')
    elif clock == 'mem':
        currClocks = getSysfsValue(device, 'mclk')
    elif clock == 'pcie':
        currClocks = getSysfsValue(device, 'pclk')
    else:
        currClocks = None

    if not currClocks:
        return None
    # Since the current clock line is of the format 'X: #Mhz *', we either want the
    # first character for level, or the 3rd-to-2nd-last characters for speed
    for line in currClocks.splitlines():
        if re.match(r'.*\*$', line):
            if clocktype == 'freq':
                currClk = line[3:-2]
            else:
                currClk = line[0]
            break
    return currClk


def getMaxLevel(device, leveltype):
    """ Return the maximum level for a specified device.

    Parameters:
    device -- Device to return the maximum level
    leveltype -- [gpu|mem|pcie|profile] Return the maximum GPU (gpu), GPU Memory (mem) level,
                 PCIe level, or the highest numbered Power Profiles
    """
    global RETCODE
    levelmap = {'gpu' : 'sclk', 'mem' : 'mclk', 'pcie' : 'pclk', 'profile' : 'profile'}
    try:
        key = levelmap[leveltype]
    except KeyError:
        printLog(device, 'Invalid level type ' + leveltype)
        RETCODE = 1
        return None

    levels = getSysfsValue(device, key)
    if not levels:
        return None
    # lstrip since there are leading spaces for this sysfs file, but no others
    if leveltype == 'profile':
        levels = levels.splitlines()[-1].lstrip(' ')
    return int(levels.splitlines()[-1][0])


def isAmdDevice(device):
    """ Return whether the specified device is an AMD device or not

    Parameters:
    device -- Device to return whether or not it's an AMD device
    """
    vid = getSysfsValue(device, 'vendor')
    if vid == '0x1002':
        return True
    return False


def setPerfLevel(device, level):
    """ Set the Performance Level for a specified device.

    Parameters:
    device -- Device to modify the current Performance Level
    level -- Performance Level to set
    """
    global RETCODE
    validLevels = ['auto', 'low', 'high', 'manual']
    perfPath = os.path.join(drmprefix, device, 'device', 'power_dpm_force_performance_level')

    if level not in validLevels:
        print(device, 'Invalid Performance level:' + level)
        RETCODE = 1
        return False
    if not os.path.isfile(perfPath):
        return False
    writeToSysfs(perfPath, level)
    return True


def showId(deviceList):
    """ Display the device ID for a list of devices.

    Parameters:
    deviceList -- List of devices to return the device ID (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        printLog(device, 'GPU ID: 0x' + getSysfsValue(device, 'id'))
    print(logSpacer)


def showVbiosVersion(deviceList):
    """ Display the VBIOS version for a list of devices.

    Parameters:
    deviceList -- List of devices to return the VBIOS version (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        vbios = getSysfsValue(device, 'vbios')
        if vbios:
            printLog(device, 'VBIOS version: ' + vbios)
        else:
            printLog(device, 'Cannot get VBIOS version')
    print(logSpacer)


def showCurrentGpuClocks(deviceList):
    """ Display the current GPU clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current clock frequencies (can be a single-item list)
    """
    global RETCODE
    print(logSpacer)
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot display GPU clocks')
            continue
        gpuclk = getCurrentClock(device, 'gpu', 'freq')
        gpulevel = getCurrentClock(device, 'gpu', 'level')

        if gpuclk == '':
            printLog(device, 'Unable to determine current GPU clocks. Check dmesg or GPU temperature')
            RETCODE = 1
            return

        printLog(device, 'GPU Clock Level: ' + str(gpulevel) + ' (' + str(gpuclk) + ')')
    print(logSpacer)


def showCurrentClocks(deviceList):
    """ Display the current GPU and GPU Memory clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current clock frequencies (can be a single-item list)
    """
    global RETCODE
    print(logSpacer)
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot display clocks')
            continue
        gpuclk = getCurrentClock(device, 'gpu', 'freq')
        gpulevel = getCurrentClock(device, 'gpu', 'level')
        memclk = getCurrentClock(device, 'mem', 'freq')
        memlevel = getCurrentClock(device, 'mem', 'level')
        pcieclk = getCurrentClock(device, 'pcie', 'freq')
        pcielevel = getCurrentClock(device, 'pcie', 'level')

        if gpuclk == '':
            printLog(device, 'Unable to determine current clocks. Check dmesg or GPU temperature')
            RETCODE = 1
            return

        printLog(device, 'GPU Clock Level: ' + str(gpulevel) + ' (' + str(gpuclk) + ')')
        printLog(device, 'GPU Memory Clock Level: ' + str(memlevel) + ' (' + str(memclk) + ')')
        printLog(device, 'PCIE Clock Level: ' + str(pcielevel) + ' (' + str(pcieclk) + ')')
    print(logSpacer)


def showCurrentTemps(deviceList):
    """ Display the current temperature for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current temperature (can be a single-item list)
    """

    print(logSpacer)
    for device in deviceList:
        temp = getSysfsValue(device, 'temp')
        if not temp:
            printLog(device, 'Unable to display temperature')
            continue
        printLog(device, 'Temperature: ' + str(temp) + 'c')
    print(logSpacer)


def showCurrentFans(deviceList):
    """ Display the current fan speed for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current fan speed (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        fanlevel = getSysfsValue(device, 'fan')
        fanspeed = getFanSpeed(device)
        if not fanspeed or not fanlevel:
            printLog(device, 'Unable to determine current fan speed')
            continue
        printLog(device, 'Fan Level: ' + str(fanlevel) + ' (' + str(fanspeed) + ')%')
    print(logSpacer)


def showClocks(deviceList):
    """ Display current GPU and GPU Memory clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of devices to display current clock frequencies (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        devpath = os.path.join(drmprefix, device, 'device')
        sclkPath = os.path.join(devpath, 'pp_dpm_sclk')
        mclkPath = os.path.join(devpath, 'pp_dpm_mclk')
        pclkPath = os.path.join(devpath, 'pp_dpm_pcie')
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot display clocks')
            continue
        if not os.path.isfile(sclkPath) or not os.path.isfile(mclkPath):
            continue
        with open(sclkPath, 'r') as sclk:
            sclkLog = 'Supported GPU clock frequencies on GPU' + parseDeviceName(device) + '\n' + sclk.read()
        with open(mclkPath, 'r') as mclk:
            mclkLog = 'Supported GPU Memory clock frequencies on GPU' + parseDeviceName(device) + '\n' + mclk.read()
        with open(pclkPath, 'r') as pclk:
            pclkLog = 'Supported PCIE clock frequencies on GPU' + parseDeviceName(device) + '\n' + pclk.read()
        printLog(device, sclkLog)
        printLog(device, mclkLog)
        printLog(device, pclkLog)
    print(logSpacer)


def showPowerPlayTable(deviceList):
    """ Display current GPU and GPU Memory clock frequencies and voltages for a list of devices.

    Parameters:
    deviceList -- List of devices to display current clock frequencies and voltages (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot display voltages')
            continue
        table = getSysfsValue(device, 'clk_voltage')
        if not table:
            printLog(device, 'Cannot display voltage, clk_voltage is empty')
            continue
        printLog(device, table)
    print(logSpacer)


def showPerformanceLevel(deviceList):
    """ Display current Performance Level for a list of devices.

    Parameters:
    deviceList -- List of devices to display current Performance Level (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        level = getSysfsValue(device, 'perf')
        if not level:
            printLog(device, 'Cannot get Performance Level: Performance Level not supported')
        else:
            printLog(device, 'Current Performance Level: ' + level)
    print(logSpacer)


def showOverDrive(deviceList, odtype):
    """ Display current OverDrive level for a list of devices.

    Parameters:
    deviceList -- List of devices to display current OverDrive values (can be a single-item list)
    odtype -- Which OverDrive to display (gpu|mem)
    """

    print(logSpacer)
    for device in deviceList:
        if odtype == 'gpu':
            od = getSysfsValue(device, 'sclk_od')
            odStr = 'GPU'
        elif odtype == 'mem':
            od = getSysfsValue(device, 'mclk_od')
            odStr = 'GPU Memory'
        if not od or int(od) < 0:
            printLog(device, 'Cannot get ' + odStr + ' OverDrive value: OverDrive not supported')
        else:
            printLog(device, 'Current ' + odStr + ' OverDrive value: ' + str(od) + '%')
    print(logSpacer)


def showProfile(deviceList):
    """ Display available Power Profiles for a list of devices.

    Parameters:
    deviceList -- List of devices to display available Power Profile attributes (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Power Profiles not supported')
            continue
        profile = getSysfsValue(device, 'profile')
        if not profile:
            printLog(device, 'Unable to get Power Profiles')
            continue
        if len(profile) > 1:
            printLog(device, '\n' + profile)
        else:
            printLog(device, 'Invalid return value from Power Profile SysFS file')
    print(logSpacer)


def showPower(deviceList):
    """ Display current Average Graphics Package Power Consumption for a list of devices.

    Parameters:
    deviceList -- List of devices to display current Average Graphics Package Power Consumption (can be a single-item list)
    """
    print(logSpacer)
    try:
        getPid("atitool")
        print('WARNING: Please terminate ATItool to use this functionality')
    except subprocess.CalledProcessError:
        for device in deviceList:
            power = getSysfsValue(device, 'power')
            if not power:
                printLog(device, 'Cannot get Average Graphics Package Power Consumption: Average GPU Power not supported')
            else:
                printLog(device, 'Average Graphics Package Power: ' + str(power) + 'W')
    print(logSpacer)


def showMaxPower(deviceList):
    """ Display the maximum Graphics Package Power that this GPU will attempt to consume
    before it begins throttling performance.

    Parameters:
    deviceList -- List of devices to display maximum Graphics Package Power Consumption (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        hwmon = getHwmonFromDevice(device)
        if not hwmon:
            printLog(device, 'No corresponding HW Monitor found')
            continue
        power_cap = getSysfsValue(device, 'power_cap')
        if not power_cap:
            printLog(device, 'Cannot get maximum Graphics Package Power: Max GPU Power reading not supported')
        else:
            power_cap = str(int(getSysfsValue(device, 'power_cap')) / 1000000)
            printLog(device, 'Max Graphics Package Power: ' + power_cap + 'W')
    print(logSpacer)


def showGpuUse(deviceList):
    """ Display GPU use for a list of devices.

    Parameters:
    deviceList -- List of all devices
    """
    print(logSpacer)
    for device in deviceList:
        use = getSysfsValue(device, 'use')
        if use == None:
            printLog(device, 'Cannot get GPU use.')
        else:
            printLog(device, 'Current GPU use: ' + use + '%')
    print(logSpacer)


def showPcieBw(deviceList):
    """ Display estimated PCIe bandwidth usage for a list of devices.

    Parameters:
    deviceList -- List of all devices
    """
    print(logSpacer)
    for device in deviceList:
        fsvals = getSysfsValue(device, 'pcie_bw')
        if fsvals == None:
            printLog(device, 'Cannot get PCIe bandwidth')
        else:
            # The sysfs file returns 3 integers: bytes-received, bytes-sent, maxsize
            # Multiply the number of packets by the maxsize to estimate the PCIe usage
            received = int(fsvals.split()[0])
            sent = int(fsvals.split()[1])
            mps = int(fsvals.split()[2])

            # Use 1024.0 to ensure that the result is a float and not integer division
            bw = ((received + sent) * mps) / 1024.0 / 1024.0
            # Use the bwstr below to control precision on the string
            bwstr = '%.3f' % bw

            printLog(device, 'Estimated maximum PCIe bandwidth over the last second: ' + bwstr + ' MB/s')
    print(logSpacer)


def showAllConciseHw(deviceList):
    """ Display critical Hardware info for all devices in a concise format.

    Parameters:
    deviceList -- List of all devices
    """
    print(logSpacer)
    print(' GPU  DID    ECC        VBIOS')
    for device in deviceList:
        gpuid = getSysfsValue(device, 'id')

        # To support later
        ecc = 'N/A'

        vbios = getSysfsValue(device, 'vbios')

        print("  %-4s%-7s%-6s%-17s" % (device[4:], gpuid, ecc, vbios))


def showAllConcise(deviceList):
    """ Display critical info for all devices in a concise format.

    Parameters:
    deviceList -- List of all devices
    """
    print(logSpacer)
    print('GPU   Temp   AvgPwr   SCLK    MCLK    PCLK           Fan     Perf    PwrCap   SCLK OD   MCLK OD  GPU%')
    for device in deviceList:

        temp = getSysfsValue(device, 'temp')
        if not temp:
            temp = 'N/A'
        else:
            temp = str(temp) + 'c'

        power = getSysfsValue(device, 'power')
        if not power:
            power = 'N/A'
        else:
            power = str(power) + 'W'

        sclk = getCurrentClock(device, 'gpu', 'freq')
        if not sclk:
            sclk = 'N/A'

        mclk = getCurrentClock(device, 'mem', 'freq')
        if not mclk:
            mclk = 'N/A'

        pclk = getCurrentClock(device, 'pcie', 'freq')
        if not pclk:
            pclk = 'N/A'

        fan = str(getFanSpeed(device))
        if not fan:
            fan = 'N/A'
        else:
            fan = fan + '%'

        perf = getSysfsValue(device, 'perf')
        if not perf:
            perf = 'N/A'

        power_cap = getSysfsValue(device, 'power_cap')
        if not power_cap:
            power_cap = 'N/A'
        else:
            power_cap = str(int(power_cap)/1000000) + 'W'

        sclk_od = getSysfsValue(device, 'sclk_od')
        if not sclk_od or sclk_od == '-1':
            sclk_od = 'N/A'
        else:
            sclk_od = sclk_od + '%'

        mclk_od = getSysfsValue(device, 'mclk_od')
        if not mclk_od or mclk_od == '-1':
            mclk_od = 'N/A'
        else:
            mclk_od = mclk_od + '%'

        use = getSysfsValue(device, 'use')
        if use == None:
            use = 'N/A'
        else:
            use = use + '%'

        print("%-6s%-7s%-9s%-8s%-8s%-15s%-8s%-8s%-9s%-10s%-9s%-9s" % (device[4:], temp, power, sclk, mclk, pclk, fan, perf, power_cap, sclk_od, mclk_od, use))
    print(logSpacer)


def setPerformanceLevel(deviceList, level):
    """ Set the Performance Level for a list of devices.

    Parameters:
    deviceList -- List of devices to set the current Performance Level (can be a single-item list)
    level -- Specific Performance Level to set
    """
    print(logSpacer)
    for device in deviceList:
        if setPerfLevel(device, level):
            printLog(device, 'Successfully set current Performance Level to ' + level)
        else:
            printLog(device, 'Unable to set current Performance Level to ' + level)
    print(logSpacer)


def setClocks(deviceList, clktype, clk):
    """ Set clock frequency level for a list of devices.

    Parameters:
    deviceList -- List of devices to set the clock frequency (can be a single-item list)
    clktype -- [gpu|mem|pcie] Set the GPU (gpu), GPU Memory (mem), or PCIE clock frequency level
    clk -- Clock frequency level to set
    """
    global RETCODE
    if not clk:
        print('Invalid clock frequency')
        RETCODE = 1
        return
    check_value = ''.join(map(str, clk))
    value = ' '.join(map(str, clk))
    try:
        int(check_value)
    except ValueError:
        print('Cannot set Clock level to value', value, ', non-integer characters are present!')
        RETCODE = 1
        return
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot set clocks')
            RETCODE = 1
            continue
        devpath = os.path.join(drmprefix, device, 'device')
        if clktype == 'gpu':
            clkFile = os.path.join(devpath, 'pp_dpm_sclk')
        elif clktype == 'mem':
            clkFile = os.path.join(devpath, 'pp_dpm_mclk')
        elif clktype == 'pcie':
            clkFile = os.path.join(devpath, 'pp_dpm_pcie')
        else:
            printLog(device, 'Invalid clock type ' + clktype)
            RETCODE = 1
            return

        # If maxLevel is empty, it means that the sysfs file is empty, so quit
        # But 0 is a max level option, so use "is None" instead of "not maxLevel"
        maxLevel = getMaxLevel(device, clktype)
        if maxLevel is None:
            printLog(device, 'Unable to set clock for type ' + clktype + ', Sysfs file is empty')
            RETCODE = 1
            continue
        # GPU clocks can be set to multiple levels at the same time (of the format
        # 4 5 6 for levels 4, 5 and 6). Don't compare against the max level for gpu
        # clocks in this case
        if any(int(item) > getMaxLevel(device, clktype) for item in clk):
            printLog(device, 'Unable to set clock to unsupported Level - Max Level is ' + str(getMaxLevel(device, clktype)))
            RETCODE = 1
            continue
        setPerfLevel(device, 'manual')
        if writeToSysfs(clkFile, value):
            if clktype == 'gpu':
                printLog(device, 'Successfully set GPU Clock frequency mask to Level ' + value)
            else:
                printLog(device, 'Successfully set GPU Memory Clock frequency mask to Level ' + value)
        else:
            printLog(device, 'Unable to set ' + clktype + ' clock to Level ' + value)
            RETCODE = 1


def setPowerPlayTableLevel(deviceList, clktype, levelList, autoRespond):
    """ Set clock frequency and voltage for a level in the PowerPlay table for a list of devices.

    Parameters:
    deviceList -- List of devices to set the clock frequency (can be a single-item list)
    clktype -- [gpu|mem] Set the GPU (gpu) or GPU Memory (mem) clock frequency level
    levelList -- Clock frequency level to set
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    if not levelList:
        print('Invalid clock state')
        RETCODE = 1
        return
    value = ' '.join(map(str, levelList))
    try:
        all(int(item) for item in levelList)
    except ValueError:
        print('Cannot set PowerPlay table level to ', levelList, ', non-integer characters are present!')
        RETCODE = 1
        return
    if clktype == 'gpu':
        value = 's ' + value
    else:
        value = 'm ' + value
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not enabled - Cannot set voltages')
            RETCODE = 1
            continue
        devpath = os.path.join(drmprefix, device, 'device')
        clkFile = os.path.join(devpath, 'pp_od_clk_voltage')

        confirmOutOfSpecWarning(autoRespond)

        maxLevel = getMaxLevel(device, clktype)
        if maxLevel is None:
            printLog(device, 'Unable to set clock, cannot obtain maximum level')
            RETCODE = 1
            continue
        if int(levelList[0]) > maxLevel:
            printLog(device, 'Unable to set clock to unsupported Level - Max Level is ' + str(getMaxLevel(device, clktype)))
            RETCODE = 1
            continue
        setPerfLevel(device, 'manual')
        if writeToSysfs(clkFile, value) and writeToSysfs(clkFile, 'c'):
            if clktype == 'gpu':
                printLog(device, 'Successfully set GPU Clock frequency mask to Level ' + value)
            else:
                printLog(device, 'Successfully set GPU Memory Clock frequency mask to Level ' + value)
        else:
            printLog(device, 'Unable to set ' + clktype + ' clock to Level ' + value)
            RETCODE = 1


def setClockOverDrive(deviceList, clktype, value, autoRespond):
    """ Set clock speed to OverDrive for a list of devices

    Parameters:
    deviceList -- List of devices to set to OverDrive
    type -- Clock type to set to OverDrive (currently only GPU and GPU Memory supported)
    value -- Percentage amount to set for OverDrive (0-20)
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    try:
        int(value)
    except ValueError:
        print('Cannot set OverDrive to value', value, ', it is not an integer!')
        RETCODE = 1
        return
    confirmOutOfSpecWarning(autoRespond)

    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot set OverDrive')
            continue
        devpath = os.path.join(drmprefix, device, 'device')
        if clktype == 'gpu':
            odPath = os.path.join(devpath, 'pp_sclk_od')
            odStr = 'GPU'
        elif clktype == 'mem':
            odPath = os.path.join(devpath, 'pp_mclk_od')
            odStr = 'GPU Memory'
        else:
            printLog(device, 'Unsupported clock type ' + clktype + ' - Cannot set OverDrive')
            RETCODE = 1
            continue

        if int(value) < 0:
            printLog(device, 'Unable to set OverDrive less than 0%')
            RETCODE = 1
            return

        if int(value) > 20:
            printLog(device, 'Unable to set OverDrive greater than 20%. Changing to 20')
            value = '20'

        if writeToSysfs(odPath, value):
            printLog(device, 'Successfully set ' + odStr + ' OverDrive to ' + value + '%')
            setClocks([device], clktype, [getMaxLevel(device, clktype)])
        else:
            printLog(device, 'Unable to set OverDrive to ' + value + '%')

def setPowerOverDrive(deviceList, value, autoRespond):
    """ Use Power OverDrive to change the the maximum power available power
    available to the GPU in Watts. May be limited by the maximum power the
    VBIOS is configured to allow this card to use in OverDrive mode.

    Parameters:
    deviceList -- List of devices to set to OverDrive
    value -- New maximum power to assign to the target device, in Watts
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    try:
        int(value)
    except ValueError:
        print('Cannot set Power OverDrive to value ', value, ', it is not an integer!')
        RETCODE = 1
        return

    confirmOutOfSpecWarning(autoRespond)

    # Value in Watt - stored early this way to avoid pythons float -> int -> str conversion after dividing a number
    strValue = value
    # Our Watt value converted for sysfs as microWatt
    value = int(value) * 1000000

    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot set Power OverDrive')
            continue
        hwmon = getHwmonFromDevice(device)
        if not hwmon:
            printLog(device, 'No corresponding HW Monitor found')
            continue
        power_cap_path = os.path.join(hwmon, 'power1_cap')

        # Avoid early unnecessary conversions
        max_power_cap = int(getSysfsValue(device, 'power_cap_max'))
        min_power_cap = int(getSysfsValue(device, 'power_cap_min'))

        if value < min_power_cap:
            printLog(device, 'Unable to set Power OverDrive to less than ' + str(min_power_cap / 1000000) + 'W')
            RETCODE = 1
            return

        if value > max_power_cap:
            printLog(device, 'Unable to set Power OverDrive to more than ' + str(max_power_cap / 1000000) + 'W')
            RETCODE = 1
            return;

        if writeToSysfs(power_cap_path, str(value)):
            if value != 0:
                printLog(device, 'Successfully set Power OverDrive to ' + strValue + 'W')
            else:
                printLog(device, 'Successfully reset Power OverDrive')
        else:
            if value != 0:
                printLog(device, 'Unable to set Power OverDrive to ' + strValue + 'W')
            else:
                printLog(device, 'Unable to reset Power OverDrive to default')

def resetPowerOverDrive(deviceList, autoRespond):
    """ Reset Power OverDrive to the default power limit that comes with the GPU

    Parameters:
    deviceList -- List of devices on which to reset the power cap
    """
    setPowerOverDrive(deviceList, 0, autoRespond)

def resetFans(deviceList):
    """ Reset fans to driver control for a list of devices.

    Parameters:
    deviceList -- List of devices to set the fan speed (can be a single-item list)
    """
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot reset fan speed')
            continue
        hwmon = getHwmonFromDevice(device)
        if not hwmon:
            printLog(device, 'No corresponding HW Monitor found')
            continue
        fanpath = os.path.join(hwmon, 'pwm1_enable')
        if writeToSysfs(fanpath, '2'):
            printLog(device, 'Successfully reset fan speed to driver control')
        else:
            printLog(device, 'Unable to reset fan speed to driver control')


def setFanSpeed(deviceList, fan):
    """ Set fan speed for a list of devices.

    Parameters:
    deviceList -- List of devices to set the fan speed (can be a single-item list)
    level -- Fan speed level to set (0-255)
    """
    global RETCODE
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot set fan speed')
            RETCODE = 1
            continue
        hwmon = getHwmonFromDevice(device)
        if not hwmon:
            printLog(device, 'No corresponding HW Monitor found')
            RETCODE = 1
            continue
        fanpath = os.path.join(hwmon, 'pwm1')
        modepath = os.path.join(hwmon, 'pwm1_enable')
        maxfan = getSysfsValue(device, 'fanmax')
        if not maxfan:
            printLog(device, 'Cannot get max fan speed')
            RETCODE = 1
            continue
        if fan.endswith('%'):
            fanpct = int(fan[:-1])
            if fanpct > 100:
                printLog(device, 'Invalid fan value ' + fan)
                RETCODE = 1
                continue
            fan = str(int((fanpct * int(maxfan)) / 100))
        if int(fan) > int(maxfan):
            printLog(device, 'Unable to set fan speed to ' + fan + ' : Max Level = ' + maxfan)
            RETCODE = 1
            continue
        if getSysfsValue(device, 'fanmode') != '1':
            if writeToSysfs(modepath, '1'):
                printLog(device, 'Successfully set fan control to \'manual\'')
            else:
                printLog(device, 'Unable to set fan control to \'manual\'')
                continue
        if writeToSysfs(fanpath, str(fan)):
            printLog(device, 'Successfully set fan speed to Level ' + str(fan))
        else:
            printLog(device, 'Unable to set fan speed to Level ' + str(fan))


def setProfile(deviceList, profile):
    """ Set CUSTOM Power Profile values for a list of devices.

    Parameters:
    deviceList -- List of devices to specify the CUSTOM Power Profile for (can be a single-item list)
    profile -- The profile to set
    """
    for device in deviceList:
        if writeProfileSysfs(device, profile):
            printLog(device, 'Successfully set CUSTOM Power Profile values')
        else:
            printLog(device, 'Unable to set CUSTOM Power Profile values')


def resetProfile(deviceList):
    """ Reset profile for a list of a devices.

    Parameters:
    deviceList -- List of devices to reset the CUSTOM Power Profile for (can be a single-item list)
    """
    for device in deviceList:
        if not getSysfsValue(device, 'profile'):
            printLog(device, 'Unable to get current Power Profile')
            continue
        # Performance level must be set to manual for a reset of the profile to work
        setPerfLevel(device, 'manual')
        if not writeProfileSysfs(device, '0 ' * getNumProfileArgs(device)):
            printLog(device, 'Unable to reset CUSTOM Power Profile values')
        if writeProfileSysfs(device, '0'):
            printLog(device, 'Successfully reset Power Profile')
        else:
            printLog(device, 'Unable to reset Power Profile')
        setPerfLevel(device, 'auto')


def resetOverDrive(deviceList):
    """ Reset OverDrive to 0 if needed. We check first as setting OD requires sudo

    Parameters:
    deviceList -- List of devices to reset OverDrive (can be a single-item list)
    """
    for device in deviceList:
        devpath = os.path.join(drmprefix, device, 'device')
        odpath = os.path.join(devpath, 'pp_sclk_od')
        odclkpath = os.path.join(devpath, 'pp_od_clk_voltage')
        if not os.path.isfile(odpath):
            printLog(device, 'Unable to reset OverDrive; OverDrive not available')
            continue
        od = getSysfsValue(device, 'sclk_od')
        if not od or int(od) != 0:
            if not writeToSysfs(odpath, '0'):
                printLog(device, 'Unable to reset OverDrive')
                continue
        printLog(device, 'OverDrive set to 0')
        if os.path.isfile(odclkpath):
            if writeToSysfs(odclkpath, 'r') and writeToSysfs(odclkpath, 'c'):
                printLog(device, 'Reset OverDrive DPM table')


def resetClocks(deviceList):
    """ Reset clocks to default

    Reset sclk, mclk amd pclk to default values by setting performance level to auto, as well
    as setting OverDrive back to 0


    Parameters:
    deviceList -- List of devices to reset clocks (can be a single-item list)
    """
    for device in deviceList:
        resetOverDrive([device])
        setPerfLevel(device, 'auto')

        od = getSysfsValue(device, 'sclk_od')
        perf = getSysfsValue(device, 'perf')

        if not perf or not od or perf != 'auto' or od != '0':
            printLog(device, 'Unable to reset clocks')
        else:
            printLog(device, 'Successfully reset clocks')


def load(savefilepath, autoRespond):
    """ Load clock frequencies and fan speeds from a specified file.

    Parameters:
    savefilepath -- Path to a file with saved clock frequencies and fan speeds
    autoRespond -- Response to automatically provide for all prompts
    """

    if not os.path.isfile(savefilepath):
        print('No settings file found at ', savefilepath)
        sys.exit()
    with open(savefilepath, 'r') as savefile:
        jsonData = json.loads(savefile.read())
        for (device, values) in jsonData.items():
            if values['vJson'] != JSON_VERSION:
                print('Unable to load legacy clock file - file v' + str(values['vJson']) +
                      ' != current v' + str(JSON_VERSION))
                break
            setFanSpeed([device], values['fan'])
            setClockOverDrive([device], 'gpu', values['overdrivegpu'], autoRespond)
            setClockOverDrive([device], 'mem', values['overdrivegpumem'], autoRespond)
            setClocks([device], 'gpu', values['gpu'])
            setClocks([device], 'mem', values['mem'])
            setClocks([device], 'pcie', values['pcie'])
            setProfile([device], values['profile'])

            # Set Perf level last, since setting OverDrive sets the Performance level
            # it to manual, and Profiles only work when the Performance level is auto
            setPerfLevel(device, values['perflevel'])

            printLog(device, 'Successfully loaded values from ' + savefilepath)


def save(deviceList, savefilepath):
    """ Save clock frequencies and fan speeds for a list of devices to a specified file path.

    Parameters:
    deviceList -- List of devices to save the clock frequencies and fan speeds
    savefilepath -- Location to save the clock frequencies and fan speeds
    """
    perfLevels = {}
    gpuClocks = {}
    memClocks = {}
    pcieClocks = {}
    fanSpeeds = {}
    overDriveGpu = {}
    overDriveGpuMem = {}
    profiles = {}
    jsonData = {}

    if os.path.isfile(savefilepath):
        print(savefilepath, 'already exists. Settings not saved')
        sys.exit()
    for device in deviceList:
        if not isDPMAvailable(device):
            printLog(device, 'DPM not available - Cannot save clocks')
            continue
        perfLevels[device] = getSysfsValue(device, 'perf')
        gpuClocks[device] = getCurrentClock(device, 'gpu', 'level')
        memClocks[device] = getCurrentClock(device, 'mem', 'level')
        pcieClocks[device] = getCurrentClock(device, 'pcie', 'level')
        fanSpeeds[device] = getSysfsValue(device, 'fan')
        overDriveGpu[device] = getSysfsValue(device, 'sclk_od')
        overDriveGpuMem[device] = getSysfsValue(device, 'mclk_od')
        profiles[device] = getProfile(device)
        jsonData[device] = {'vJson': JSON_VERSION, 'gpu': gpuClocks[device], 'mem': memClocks[device], 'pcie': pcieClocks[device], 'fan': fanSpeeds[device], 'overdrivegpu': overDriveGpu[device], 'overdrivegpumem': overDriveGpuMem[device], 'profile': profiles[device], 'perflevel': perfLevels[device]}
        printLog(device, 'Current settings successfully saved to ' + savefilepath)
    with open(savefilepath, 'w') as savefile:
        json.dump(jsonData, savefile, ensure_ascii=True)

# Below is for when called as a script instead of when imported as a module
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AMD ROCm System Management Interface', formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=90, width=120))
    groupDev = parser.add_argument_group()
    groupDisplay = parser.add_argument_group()
    groupAction = parser.add_argument_group()
    groupFile = parser.add_mutually_exclusive_group()
    groupResponse = parser.add_argument_group()
    groupOutput = parser.add_argument_group()

    groupDev.add_argument('-d', '--device', help='Execute command on specified device', type=int)
    groupDisplay.add_argument('-i', '--showid', help='Show GPU ID', action='store_true')
    groupDisplay.add_argument('-v', '--showvbios', help='Show VBIOS version', action='store_true')
    groupDisplay.add_argument('--showhw', help='Show Hardware details', action='store_true')
    groupDisplay.add_argument('-t', '--showtemp', help='Show current temperature', action='store_true')
    groupDisplay.add_argument('-c', '--showclocks', help='Show current clock frequencies', action='store_true')
    groupDisplay.add_argument('-g', '--showgpuclocks', help='Show current GPU clock frequencies', action='store_true')
    groupDisplay.add_argument('-f', '--showfan', help='Show current fan speed', action='store_true')
    groupDisplay.add_argument('-p', '--showperflevel', help='Show current DPM Performance Level', action='store_true')
    groupDisplay.add_argument('-P', '--showpower', help='Show current Average Graphics Package Power Consumption', action='store_true')
    groupDisplay.add_argument('-o', '--showoverdrive', help='Show current GPU Clock OverDrive level', action='store_true')
    groupDisplay.add_argument('-m', '--showmemoverdrive', help='Show current GPU Memory Clock OverDrive level', action='store_true')
    groupDisplay.add_argument('-M', '--showmaxpower', help='Show maximum graphics package power this GPU will consume', action='store_true')
    groupDisplay.add_argument('-l', '--showprofile', help='Show Compute Profile attributes', action='store_true')
    groupDisplay.add_argument('-s', '--showclkfrq', help='Show supported GPU and Memory Clock', action='store_true')
    groupDisplay.add_argument('-u', '--showuse', help='Show current GPU use', action='store_true')
    groupDisplay.add_argument('-b', '--showbw', help='Show estimated PCIe use', action='store_true')
    groupDisplay.add_argument('-S', '--showclkvolt', help='Show supported GPU and Memory Clocks and Voltages', action='store_true')
    groupDisplay.add_argument('-a' ,'--showallinfo', help='Show Temperature, Fan and Clock values', action='store_true')
    groupDisplay.add_argument('--alldevices', help='Execute command on non-AMD devices as well as AMD devices', action='store_true')

    groupAction.add_argument('-r', '--resetclocks', help='Reset sclk, mclk and pclk to default', action='store_true')
    groupAction.add_argument('--setsclk', help='Set GPU Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setmclk', help='Set GPU Memory Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setpclk', help='Set PCIE Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setslevel', help='Change GPU Clock frequency (MHz) and Voltage (mV) for a specific Level', metavar=('SCLKLEVEL', 'SCLK', 'SVOLT'), nargs=3)
    groupAction.add_argument('--setmlevel', help='Change GPU Memory clock frequency (MHz) and Voltage for (mV) a specific Level', metavar=('MCLKLEVEL', 'MCLK', 'MVOLT'), nargs=3)
    groupAction.add_argument('--resetfans', help='Reset fans to automatic (driver) control', action='store_true')
    groupAction.add_argument('--setfan', help='Set GPU Fan Speed (Level or %%)', metavar='LEVEL')
    groupAction.add_argument('--setperflevel', help='Set Performance Level', metavar='LEVEL')
    groupAction.add_argument('--setoverdrive', help='Set GPU OverDrive level (requires manual|high Perf level)', metavar='%')
    groupAction.add_argument('--setmemoverdrive', help='Set GPU Memory Overclock OverDrive level (requires manual|high Perf level)', metavar='%')
    groupAction.add_argument('--setpoweroverdrive', help='Set the maximum GPU power using Power OverDrive in Watts', metavar='WATTS')
    groupAction.add_argument('--resetpoweroverdrive', help='Set the maximum GPU power back to the device deafult state', action='store_true')
    groupAction.add_argument('--setprofile', help='Specify Power Profile level (#) or a quoted string of CUSTOM Profile attributes "# # # #..." (requires manual Perf level)')
    groupAction.add_argument('--resetprofile', help='Reset Power Profile back to default', action='store_true')

    groupFile.add_argument('--load', help='Load Clock, Fan, Performance and Profile settings from FILE', metavar='FILE')
    groupFile.add_argument('--save', help='Save Clock, Fan, Performance and Profile settings to FILE', metavar='FILE')

    groupResponse.add_argument('--autorespond', help='Response to automatically provide for all prompts (NOT RECOMMENDED)', metavar='RESPONSE')

    groupOutput.add_argument('--loglevel', help='How much output will be printed for what program is doing, one of debug/info/warning/error/critical', metavar='ILEVEL')

    args = parser.parse_args()

    if args.loglevel is not None:
        numericLogLevel = getattr(logging, args.loglevel.upper(), logging.WARNING)
        logging.basicConfig(level=numericLogLevel)

    # If there is a single device specified, use that for all commands, otherwise use a
    # list of all available devices. Also use "is not None" as device 0 would
    # have args.device=0, and "if 0" returns false.
    if args.device is not None:
        device = parseDeviceNumber(args.device)
        if not doesDeviceExist(device):
            print('No such device ' + device)
            sys.exit()
        if isAmdDevice(device) or args.alldevices:
            deviceList = [device]
        else:
            print('No supported devices available to display')
    else:
        deviceList = listDevices(args.alldevices)

    if args.showallinfo:
        args.showid = True
        args.showtemp = True
        args.showclocks = True
        args.showfan = True
        args.list = True
        args.showclkfrq = True
        args.showuse = True
        args.showperflevel = True
        args.showoverdrive = True
        args.showmemoverdrive = True
        args.showmaxpower = True
        args.showprofile = True
        args.showpower = True
        args.showbw = True

    if args.setsclk or args.setmclk or args.setpclk or args.resetfans or args.setfan or args.setperflevel or \
       args.load or args.resetclocks or args.setprofile or args.resetprofile or args.setoverdrive or \
       args.setmemoverdrive or args.setpoweroverdrive or args.resetpoweroverdrive or \
       args.setslevel or args.setmlevel or len(sys.argv) == 1:
        relaunchAsSudo()

    # Header for the SMI
    print('\n\n', headerSpacer, '        ROCm System Management Interface        ', headerSpacer, sep='')

    # If all fields are requested, only print it for devices with DPM support. There is no point
    # in printing a bunch of "Feature unavailable" messages and cluttering the output
    # unnecessarily. We do it here to get it under the SMI Header, and to not print it multiple times
    # in case the SMI is relaunched as sudo
    # Note that this only affects the --all tab. While it won't output the supported fields like
    # temperature or fan speed, that would require a rework to implement. For now, devices without
    # DPM support can get the fields from the concise output, or by specifying the flag. But the
    # --all flag will not show any fields for a device that doesn't have DPM, even fan speed or temperature
    if args.showallinfo:
        for device in deviceList:
            if not isDPMAvailable(device):
                printLog(device, 'WARNING: DPM not available, skipping output for this device')
                deviceList.remove(device)

    if len(sys.argv) == 1 or len(sys.argv) == 2 and (args.loglevel or args.alldevices):
        showAllConcise(deviceList)
    if args.showhw:
        showAllConciseHw(deviceList)
    if args.showid:
        showId(deviceList)
    if args.showvbios:
        showVbiosVersion(deviceList)
    if args.resetclocks:
        resetClocks(deviceList)
    if args.showtemp:
        showCurrentTemps(deviceList)
    if args.showclocks:
        showCurrentClocks(deviceList)
    if args.showgpuclocks:
        showCurrentGpuClocks(deviceList)
    if args.showfan:
        showCurrentFans(deviceList)
    if args.showperflevel:
        showPerformanceLevel(deviceList)
    if args.showoverdrive:
        showOverDrive(deviceList, 'gpu')
    if args.showmemoverdrive:
        showOverDrive(deviceList, 'mem')
    if args.showmaxpower:
        showMaxPower(deviceList)
    if args.showprofile:
        showProfile(deviceList)
    if args.showpower:
        showPower(deviceList)
    if args.showclkfrq:
        showClocks(deviceList)
    if args.showuse:
        showGpuUse(deviceList)
    if args.showbw:
        showPcieBw(deviceList)
    if args.showclkvolt:
        showPowerPlayTable(deviceList)
    if args.setsclk:
        setClocks(deviceList, 'gpu', args.setsclk)
    if args.setmclk:
        setClocks(deviceList, 'mem', args.setmclk)
    if args.setpclk:
        setClocks(deviceList, 'pcie', args.setpclk)
    if args.setslevel:
        setPowerPlayTableLevel(deviceList, 'gpu', args.setslevel, args.autorespond)
    if args.setmlevel:
        setPowerPlayTableLevel(deviceList, 'mem', args.setmlevel, args.autorespond)
    if args.resetfans:
        resetFans(deviceList)
    if args.setfan:
        setFanSpeed(deviceList, args.setfan)
    if args.setperflevel:
        setPerformanceLevel(deviceList, args.setperflevel)
    if args.setoverdrive:
        setClockOverDrive(deviceList, 'gpu', args.setoverdrive, args.autorespond)
    if args.setmemoverdrive:
        setClockOverDrive(deviceList, 'mem', args.setmemoverdrive, args.autorespond)
    if args.setpoweroverdrive:
        setPowerOverDrive(deviceList, args.setpoweroverdrive, args.autorespond)
    if args.resetpoweroverdrive:
        resetPowerOverDrive(deviceList, args.autorespond)
    if args.setprofile:
        setProfile(deviceList, args.setprofile)
    if args.resetprofile:
        resetProfile(deviceList)
    if args.load:
        load(args.load, args.autorespond)
    if args.save:
        save(deviceList, args.save)

    # If RETCODE isn't 0, inform the user
    if RETCODE:
        print('WARNING: One or more commands failed')

    # Footer for the SMI
    print(headerSpacer, '               End of ROCm SMI Log              ', headerSpacer, '\n', sep='')
    sys.exit(RETCODE)

#!/usr/bin/python3

import os
import argparse
import re
import sys
import subprocess
import json
from subprocess import check_output
import glob

# Version of the JSON output used to save clocks
JSON_VERSION = 1

# Set to 1 if an error occurs
RETCODE = 0

# Currently we have 5 values for PowerPlay Profiles
NUM_PROFILE_ARGS = 5

# To write to sysfs, we need to run this script as root. If the script is not run as
# root, re-launch it via execvp to give the script sudo privileges.
def relaunchAsSudo():
    if os.geteuid() != 0:
        os.execvp('sudo', ['sudo'] + sys.argv)


drmprefix = '/sys/class/drm'
hwmonprefix = '/sys/class/hwmon'
powerprefix = '/sys/kernel/debug/dri/'

headerSpacer = '='*20
logSpacer = headerSpacer * 4


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
    print('GPU[', parseDeviceName(device), '] \t\t: ', log, sep='')


def doesDeviceExist(device):
    """ Check whether the specified device exists in sysfs.

    Parameters:
    device -- Device to check for existence
    """
    if os.path.exists(os.path.join(drmprefix, device)) == 0:
        return False
    return True

def getPid(name):
    return check_output(["pidof",name])


def confirmOverDrive(autoRespond):
    """ Print the warning for OverDrive functionality and prompt user to accept the terms.

    Parameters:
    autoRespond -- Response to automatically provide for all prompts
    """

    print('''
          ******WARNING******\n
          Operating your AMD GPU outside of official AMD specifications or outside of
          factory settings, including but not limited to the conducting of overclocking
          (including use of this overclocking software, even if such software has been
          directly or indirectly provided by AMD or otherwise affiliated in any way
          with AMD), may cause damage to your AMD GPU, system components and/or result
          in system failure, as well as cause other problems. DAMAGES CAUSED BY USE OF
          YOUR AMD GPU OUTSIDE OF OFFICIAL AMD SPECIFICATIONS OR OUTSIDE OF FACTORY
          SETTINGS ARE NOT COVERED UNDER ANY AMD PRODUCT WARRANTY AND MAY NOT BE COVERED
          BY YOUR BOARD OR SYSTEM MANUFACTURER'S WARRANTY. Please use this utility with caution.
          ''')
    if not autoRespond:
        user_input = input('Do you accept these terms? [y/N] ')
    else:
        user_input = autoRespond
    if user_input in ['Yes', 'yes', 'y', 'Y', 'YES']:
        return
    else:
        sys.exit('Confirmation not given. Exiting without setting OverDrive value')

def isPowerplayEnabled(device):
    """ Check if PowerPlay is enabled for a specified device.

    Parameters:
    device -- Device to check for PowerPlay enablement
    """
    if not doesDeviceExist(device) or os.path.isfile(os.path.join(drmprefix, device, 'device', 'power_dpm_force_performance_level')) == 0:
        return False
    return True


def verifyProfileData(device, profile):
    if not isPowerplayEnabled(device):
        printLog(device, 'PowerPlay not enabled, cannot specify profile.')
        return False

    if profile != 'reset' and len(profile) != NUM_PROFILE_ARGS:
        printLog(device, 'Unsupported profile argument : ' + str(profile))
        return False

    return True


def writeProfileSysfs(device, value):
    profilePath = os.path.join(drmprefix, device, 'device', 'pp_compute_power_profile')
    profileString = value

    if value != 'reset':
        profileString = ' '.join(value)
    if (writeToSysfs(profilePath, profileString)):
        return True

    return False

def pciNumFromDevice(device):
    drmPath = os.path.realpath(os.path.join(drmprefix, device, 'device'))
    return os.path.basename(drmPath)

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
    with open(fsFile, 'w') as fs:
        try:
            fs.write(fsValue + '\n') # Certain sysfs files require \n at the end
        except OSError:
            print('Unable to write to sysfs file' + fsFile)
            RETCODE = 1
            return False
    return True


def listDevices():
    """ Return a list of GPU devices."""
    devicelist = [device for device in os.listdir(drmprefix) if re.match(r'^card\d+$', device)]
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


def getId(device):
    """ Return the device ID for a specified device.

    Parameters:
    device -- Device to return the device ID
    """
    idPath=os.path.join(drmprefix, device, 'device', 'device')
    if not os.path.isfile(idPath):
        return ''
    with open(idPath, 'r') as devname:
        gpuId = devname.read().rstrip('\n')
    return gpuId[2:]


def getPerfLevel(device):
    """ Return the current PowerPlay Performance Level for a specified device.

    Parameters:
    device -- Device to return the current PowerPlay Performance Level
    """
    ret = ''
    perfPath = os.path.join(drmprefix, device, 'device', 'power_dpm_force_performance_level')
    if os.path.isfile(perfPath):
        with open(perfPath, 'r') as perflevel:
            ret = perflevel.read().rstrip('\n')
    return ret


def setPerfLevel(device, level):
    """ Set the PowerPlay Performance Level for a specified device.

    Parameters:
    device -- Device to modify the current PowerPlay Performance Level
    level -- PowerPlay Performance Level to set
    """
    validLevels = ['auto', 'low', 'high', 'manual']
    perfPath = os.path.join(drmprefix, device, 'device', 'power_dpm_force_performance_level')

    if level not in validLevels:
        print(device, 'Invalid Performance level:' + level)
        return False
    if not os.path.isfile(perfPath):
        return False
    writeToSysfs(perfPath, level)
    return True


def getTemp(device):
    """ Return the current temperature for a specified device.

    Parameters:
    device -- Device to return the current temperature
    """
    temp = ''

    hwmon = getHwmonFromDevice(device)
    if not hwmon:
        return None
    temppath = os.path.join(hwmon, 'temp1_input')
    if os.path.isfile(temppath):
        with open(temppath, 'r') as tempfile:
            # Temperature in sysfs is in millidegrees
            temp = int(tempfile.read().rstrip('\n'))/1000
    return temp


def getFanSpeed(device, type):
    """ Return the fan speed for a specified device.

    Parameters:
    device -- Device to return the current fan speed
    type -- [speed|level] Return either the fan % (speed) or the fan value (level, ranging from 0-255)
    """
    fan = ''

    hwmon = getHwmonFromDevice(device)
    if not hwmon:
        return None
    fanpath = os.path.join(hwmon, 'pwm1')
    fanmax = os.path.join(hwmon, 'pwm1_max')
    if not os.path.isfile(fanpath) or not os.path.isfile(fanmax):
        return ''
    with open(fanpath, 'r') as fanfile:
        currFan = int(fanfile.read().rstrip('\n'))
        if type == 'level':
            fan = currFan
        else:
            with open(fanmax, 'r') as fanmaxfile:
                fan = round(currFan / int(fanmaxfile.read().rstrip('\n')) * 100, 2)
    return str(fan)


def getClocks(device, type):
    """ Return all supported GPU or GPU Memory clock frequencies for a specified device.

    Parameters:
    device -- Device to return the supported clock frequencies
    type -- [gpu|mem] Return the list of either the GPU (gpu) or GPU Memory (mem) clock frequencies
    """
    global RETCODE
    clocks = []
    clockDict = {'gpu': 'pp_dpm_sclk', 'mem': 'pp_dpm_mclk'}

    try:
        clkFile = clockDict[type]
    except:
        print('Invalid clock type:', type)
        RETCODE = 1
        return None
    devpath = os.path.join(drmprefix, device, 'device')
    clkPath = os.path.join(devpath, clkFile)
    if not isPowerplayEnabled(device):
        printLog(device, 'PowerPlay not enabled - Cannot get supported clocks')
        return None
    if os.path.isfile(clkPath):
        with open(clkPath, 'r') as clk:
            for line in clk:
                clocks.append(line.strip('\n'))
    return clocks


def getCurrentClock(device, clock, type):
    """ Return the current clock frequency for a specified device.

    Parameters:
    device -- Device to return the clock frequency
    clock -- [gpu|mem] Return either the GPU (gpu) or GPU Memory (mem) clock frequency
    type -- [freq|level] Return either the clock frequency (freq) or clock level (level)
    """
    currClk = ''

    currClocks = getClocks(device, clock)
    if not currClocks:
        return None
    # Since the current clock line is of the format 'X: #Mhz *', we either want the
    # first character for level, or the 3rd-to-2nd-last characters for speed
    for line in currClocks:
        if re.match(r'.*\*$', line):
            if (type == 'freq'):
                currClk = line[3:-2]
            else:
                currClk = line[0]
            break
    return currClk


def getCurrentOverDrive(device, clock):
    """ Return the current OverDrive level for a specified device.

    Parameters:
    device -- Device to return the clock frequency
    clock -- [gpu|mem] Return either the GPU (gpu) or GPU Memory (mem) OverDrive value
    """

    od = '-1'
    if not clock == 'gpu':
        printLog(device, 'Unable to set OverDrive for non-GPU clocks')
        return od
    odpath = os.path.join(drmprefix, device, 'device', 'pp_sclk_od')
    if os.path.isfile(odpath):
        with open(odpath, 'r') as odFile:
            od = odFile.read().rstrip('\n')
    return od


def getMaxLevel(device, type):
    """ Return the maximum level for a specified device.

    Parameters:
    device -- Device to return the maximum level
    type -- [gpu|mem|fan] Return either the maximum GPU (gpu), GPU Memory (mem) level, or fan (fan)
    """
    if type == 'fan':
        return 255
    levels = getClocks(device, type)
    return int(levels[-1][0])


def getProfile(device):
    """ Return the current profile values for a specified device.

    Parameters:
    device -- Device to return the current Compute Profile attributes
    """
    profilePath = os.path.join(drmprefix, device, 'device', 'pp_compute_power_profile')
    profile = ''
    if os.path.isfile(profilePath):
        with open(profilePath, 'r') as profileFile:
            profile = profileFile.read().rstrip('\n')
    return profile

def isCorrectPowerDevice(root, device):
    """ Return the corresponding power reading for a specified GPU device.

    Parameters:
    device -- Device to return the corresponding HW Monitor
    """
    pciPath = os.path.join(root, 'name')
    if os.path.isfile(pciPath):
        with open(pciPath, 'r') as pciFile:
            if pciNumFromDevice(device) in pciFile.read().rstrip('\n'):
                return True
    return False

def findFile(prefix, file, device):
    """ Return the full file path given prefix

    Parameters:
    prefix -- directory that contains the file
    file -- name of the file
    """
    pcPaths = glob.glob(os.path.join(prefix, '*', file))
    for path in pcPaths:
        if isCorrectPowerDevice(os.path.dirname(path), device):
            return path
    return ''

def getPower(device):
    """ Return the current power consumption for a specified device.

    Parameters:
    device -- Device to return the current power consumption
    """
    pcPath = findFile(powerprefix, 'amdgpu_pm_info', device)
    pc = ''
    PowerString = 'average GPU'
    if os.path.isfile(pcPath):
        with open(pcPath, 'r') as pcFile:
            for line in pcFile:
                if PowerString in line:
                    pc = line.replace(' (average GPU)\n', '')
                    break
    return pc

def showId(deviceList):
    """ Display the device ID for a list of devices.

    Parameters:
    deviceList -- List of devices to return the device ID (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        printLog(device, 'GPU ID: 0x' + getId(device))
    print(logSpacer)


def showCurrentGpuClocks(deviceList):
    """ Display the current GPU clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current clock frequencies (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot display GPU clocks')
            continue
        gpuclk = getCurrentClock(device, 'gpu', 'freq')
        gpulevel = getCurrentClock(device, 'gpu', 'level')

        if gpuclk == '':
            printLog(device, 'Unable to determine current GPU clocks. Check dmesg or GPU temperature')
            return

        printLog(device, 'GPU Clock Level: ' + str(gpulevel) + ' (' + str(gpuclk) + ')')
    print(logSpacer)


def showCurrentClocks(deviceList):
    """ Display the current GPU and GPU Memory clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current clock frequencies (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot display clocks')
            continue
        gpuclk = getCurrentClock(device, 'gpu', 'freq')
        gpulevel = getCurrentClock(device, 'gpu', 'level')
        memclk = getCurrentClock(device, 'mem', 'freq')
        memlevel = getCurrentClock(device, 'mem', 'level')

        if gpuclk == '':
            printLog(device, 'Unable to determine current clocks. Check dmesg or GPU temperature')
            return

        printLog(device, 'GPU Clock Level: ' + str(gpulevel) + ' (' + str(gpuclk) + ')')
        printLog(device, 'GPU Memory Clock Level: ' + str(memlevel) + ' (' + str(memclk) + ')')
    print(logSpacer)


def showCurrentTemps(deviceList):
    """ Display the current temperature for a list of devices.

    Parameters:
    deviceList -- List of devices to return the current temperature (can be a single-item list)
    """
    tempfiles = []

    print(logSpacer)
    for device in deviceList:
        temp = getTemp(device)
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
        fanspeed = getFanSpeed(device, 'speed')
        fanlevel = getFanSpeed(device, 'level')
        if not fanspeed:
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
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot display clocks')
            continue
        if not os.path.isfile(sclkPath) or not os.path.isfile(mclkPath):
            continue
        with open(sclkPath, 'r') as sclk:
            sclkLog = 'Supported GPU clock frequencies on GPU' + parseDeviceName(device) + '\n' + sclk.read()
        with open(mclkPath, 'r') as mclk:
            mclkLog = 'Supported GPU Memory clock frequencies on GPU' + parseDeviceName(device) + '\n' + mclk.read()
        for line in sclkLog.split('\n'):
            printLog(device, line)
        for line in mclkLog.split('\n'):
            printLog(device, line)
    print(logSpacer)


def showPerformanceLevel(deviceList):
    """ Display current PowerPlay Performance Level for a list of devices.

    Parameters:
    deviceList -- List of devices to display current PowerPlay Performance Level (can be a single-item list)
    """
    print(logSpacer)
    for device in deviceList:
        level = getPerfLevel(device)
        if not level:
            printLog(device, 'Cannot get Performance Level: Performance Level not supported')
        else:
            printLog(device, 'Current PowerPlay Level: ' + level)
    print(logSpacer)


def showOverDrive(deviceList):
    """ Display current OverDrive level for a list of devices.

    Parameters:
    deviceList -- List of devices to display current OverDrive values (can be a single-item list)
    """

    print(logSpacer)
    for device in deviceList:
        od = int(getCurrentOverDrive(device, 'gpu'))
        if od < 0:
            printLog(device, 'Cannot get OverDrive value: OverDrive not supported')
        else:
            printLog(device, 'Current OverDrive value: ' + str(od) + '%')
    print(logSpacer)


def showProfile(deviceList):
    """ Display current Compute Power Profile for a list of devices.

    Parameters:
    deviceList -- List of devices to display current Compute Power Profile attributes (can be a single-item list)
    """

    print(logSpacer)
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Compute Power Profile not supported')
            continue
        profile = getProfile(device)
        vals = profile.split()
        if len(vals) == NUM_PROFILE_ARGS:
            printLog(device, 'Minimum SCLK: ' + vals[0] + 'MHz')
            printLog(device, 'Minimum MCLK: ' + vals[1] + 'MHz')
            printLog(device, 'Activity threshold: ' + vals[2] + '%')
            printLog(device, 'Hysteresis Up: ' + vals[3] + 'ms')
            printLog(device, 'Hysteresis Down: ' + vals[4] + 'ms')
        elif not profile:
            printLog(device, 'Compute Power Profile not supported')
        else:
            printLog(device, 'Invalid return value from pp_compute_power_profile')
    print(logSpacer)


def showPower(deviceList):
    """ Display current Power Consumption for a list of devices.

    Parameters:
    deviceList -- List of devices to display current Power Consumption (can be a single-item list)
    """
    print(logSpacer)
    try:
        getPid("atitool")
        print('WARNING: Please terminate ATItool to use this functionality')
    except subprocess.CalledProcessError:
        for device in deviceList:
            power = getPower(device)
            if not power:
                printLog(device, 'Cannot get GPU power Consumption: Average GPU Power not supported')
            else:
                printLog(device, 'Average GPU Power: ' + power)
    print(logSpacer)


def showAllConcise(deviceList):
    """ Display critical info for all devices in a concise format.

    Parameters:
    deviceList -- List of all devices
    """
    print(logSpacer)
    print(' GPU  DID    Temp     AvgPwr   SCLK     MCLK     Fan      Perf    OverDrive  ECC')
    for device in deviceList:
        gpuid = getId(device)

        temp = getTemp(device)
        if not temp:
            temp = 'N/A'
        else:
            temp = str(temp) + 'c'

        power = str.lstrip(getPower(device))
        if not power:
            power = 'N/A'
        else:
            power = power[:-2] + 'W'

        sclk = getCurrentClock(device, 'gpu', 'freq')
        if not sclk:
            sclk = 'N/A'

        mclk = getCurrentClock(device, 'mem', 'freq')
        if not mclk:
            mclk = 'N/A'

        fan = str(getFanSpeed(device, 'speed'))
        if not fan:
            fan = 'N/A'
        else:
            fan = fan + '%'

        perf = getPerfLevel(device)

        od = getCurrentOverDrive(device, 'gpu')
        if od == '-1':
            od = 'N/A'
        else:
            od = od + '%'
        """ To support later """
        ecc = 'N/A'

        print("  %-4s%-7s%-9s%-9s%-9s%-9s%-9s%-10s%-9s%-9s" % (device[4:], gpuid, temp,
            power, sclk, mclk, fan, perf, od, ecc))
    print(logSpacer)


def setPerformanceLevel(deviceList, level):
    """ Set the PowerPlay Performance Level for a list of devices.

    Parameters:
    deviceList -- List of devices to set the current PowerPlay Performance Level (can be a single-item list)
    level -- Specific PowerPlay Performance Level to set
    """
    print(logSpacer)
    for device in deviceList:
        if setPerfLevel(device, level):
            printLog(device, 'Successfully set current PowerPlay Level to ' + level)
        else:
            printLog(device, 'Unable to set current PowerPlay Level to ' + level)
    print(logSpacer)


def setClocks(deviceList, clktype, clk):
    """ Set clock frequency level for a list of devices.

    Parameters:
    deviceList -- List of devices to set the clock frequency (can be a single-item list)
    clktype -- [gpu|mem] Set the GPU (gpu) or GPU Memory (mem) clock frequency level
    clk -- Clock frequency level to set
    """
    global RETCODE
    value = ''.join(str(x) for x in clk)
    try:
        int(value)
    except ValueError:
        print('Cannot set OverDrive to value', value, ', it is not an integer!')
        return
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot set clocks')
            continue
        devpath = os.path.join(drmprefix, device, 'device')
        if clktype == 'gpu':
            clkFile = os.path.join(devpath, 'pp_dpm_sclk')
        else:
            clkFile = os.path.join(devpath, 'pp_dpm_mclk')

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


def setClockOverDrive(deviceList, clktype, value, autoRespond):
    """ Set clock speed to OverDrive for a list of devices

    Parameters:
    deviceList -- List of devices to set to OverDrive
    type -- Clock type to set to OverDrive (currently only GPU supported)
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
    confirmOverDrive(autoRespond)

    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot set OverDrive')
            continue
        devpath = os.path.join(drmprefix, device, 'device')
        if clktype == 'gpu':
            odPath = os.path.join(devpath, 'pp_sclk_od')
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

        if (writeToSysfs(odPath, value)):
            printLog(device, 'Successfully set OverDrive to ' + value + '%')
            setClocks([device], clktype, [getMaxLevel(device, 'gpu')])
        else:
            printLog(device, 'Unable to set OverDrive to ' + value + '%')


def resetFans(deviceList):
    """ Reset fans to driver control for a list of devices.

    Parameters:
    deviceList -- List of devices to set the fan speed (can be a single-item list)
    """
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot reset fan speed')
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
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot set fan speed')
            continue
        hwmon = getHwmonFromDevice(device)
        if not hwmon:
            printLog(device, 'No corresponding HW Monitor found')
            RETCODE = 1
            continue
        fanpath = os.path.join(hwmon, 'pwm1')
        maxfan = getMaxLevel(device, 'fan')
        if int(fan) > maxfan:
            printLog(device, 'Unable to set fan speed to ' + fan + ' : Max Level = ' + str(maxfan))
            RETCODE = 1
            continue
        if writeToSysfs(fanpath, str(fan)):
            printLog(device, 'Successfully set fan speed to Level ' + str(fan))
        else:
            printLog(device, 'Unable to set fan speed to Level ' + str(fan))


def setProfile(deviceList, profile):
    """ Set Compute Power Profile values for a list of devices.

    Parameters:
    deviceList -- List of devices to specify the Compute Power Profile for (can be a single-item list)
    profile -- The profile to set
    """
    for device in deviceList:
        if not verifyProfileData(device, profile):
            continue
        if (writeProfileSysfs(device, profile)):
            printLog(device, 'Successfully set Compute Power Profile values')
        else:
            printLog(device, 'Unable to set Compute Power Profile values')


def resetProfile(deviceList):
    """ Reset profile for a list of a devices.

    Parameters:
    deviceList -- List of devices to reset the Compute Power Profile for (can be a single-item list)
    """
    for device in deviceList:
        if not verifyProfileData(device, 'reset'):
            continue
        if writeProfileSysfs(device, 'reset'):
            printLog(device, 'Successfully reset Compute Power Profile values')
        else:
            printLog(device, 'Unable to reset Compute Power Profile values')


def resetClocks(deviceList):
    """ Reset performance level to default for a list of devices.

    Resetting the performance level to 'auto' will reset the GPU and GPU Memory clock
    frequencies to their default values.

    Parameters:
    deviceList -- List of devices to reset performance level (can be a single-item list)
    """
    for device in deviceList:
        devpath = os.path.join(drmprefix, device, 'device')
        odpath = os.path.join(devpath, 'pp_sclk_od')
        if not getPerfLevel(device):
            printLog(device, 'Cannot reset clocks: Performance Level not supported')
            continue
        # Setting perf level to auto will reset all manual values except for OverDrive
        if os.path.isfile(odpath):
            if not writeToSysfs(odpath, '0'):
                printLog(device, 'Unable to reset OverDrive')
                continue
        if getPerfLevel(device) == 'auto':
            printLog(device, 'Performance level already set to [auto]')
            continue
        if not setPerfLevel(device, 'auto'):
            printLog(device, 'Unable to reset GPU and Memory clocks')
            continue
        printLog(device, 'Successfully reset GPU and Memory clocks')


def load(savefilepath, autoRespond):
    """ Load clock frequencies and fan speeds from a specified file.

    Parameters:
    savefilepath -- Path to a file with saved clock frequencies and fan speeds
    autoRespond -- Response to automatically provide for all prompts
    """
    gpuClocks = {}
    memClocks = {}
    fanSpeeds = {}
    profiles = {}

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
            setClocks([device], 'gpu', values['gpu'])
            setClocks([device], 'mem', values['mem'])
            setProfile([device], values['profile'].split())

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
    fanSpeeds = {}
    overDriveGpu = {}
    profiles = {}
    jsonData = {}

    if os.path.isfile(savefilepath):
        print(savefilepath, 'already exists. Settings not saved')
        sys.exit()
    for device in deviceList:
        if not isPowerplayEnabled(device):
            printLog(device, 'PowerPlay not enabled - Cannot save clocks')
            continue
        perfLevels[device] = getPerfLevel(device)
        gpuClocks[device] = getCurrentClock(device, 'gpu', 'level')
        memClocks[device] = getCurrentClock(device, 'mem', 'level')
        fanSpeeds[device] = getFanSpeed(device, 'level')
        overDriveGpu[device] = getCurrentOverDrive(device, 'gpu')
        profiles[device] = getProfile(device)
        jsonData[device] = {'vJson': JSON_VERSION, 'gpu': gpuClocks[device], 'mem': memClocks[device], 'fan': fanSpeeds[device], 'overdrivegpu': overDriveGpu[device], 'profile': profiles[device], 'perflevel': perfLevels[device]}
        printLog(device, 'Current settings successfully saved to ' + savefilepath)
    with open(savefilepath, 'w') as savefile:
        json.dump(jsonData, savefile, ensure_ascii=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AMD ROCm System Management Interface',
             formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=90, width=110))
    groupDev = parser.add_argument_group()
    groupDisplay = parser.add_argument_group()
    groupAction = parser.add_argument_group()
    groupFile = parser.add_mutually_exclusive_group()
    groupResponse = parser.add_argument_group()

    groupDev.add_argument('-d', '--device', help='Execute command on specified device', type=int)
    groupDisplay.add_argument('-i', '--showid', help='Show GPU ID', action='store_true')
    groupDisplay.add_argument('-t', '--showtemp', help='Show current temperature', action='store_true')
    groupDisplay.add_argument('-c', '--showclocks', help='Show current clock frequencies', action='store_true')
    groupDisplay.add_argument('-g', '--showgpuclocks', help='Show current GPU clock frequencies', action='store_true')
    groupDisplay.add_argument('-f', '--showfan', help='Show current fan speed', action='store_true')
    groupDisplay.add_argument('-p', '--showperflevel', help='Show current PowerPlay Performance Level', action='store_true')
    groupDisplay.add_argument('-P', '--showpower', help='Show current power consumption', action='store_true')
    groupDisplay.add_argument('-o', '--showoverdrive', help='Show current OverDrive level', action='store_true')
    groupDisplay.add_argument('-l', '--showprofile', help='Show Compute Profile attributes', action='store_true')
    groupDisplay.add_argument('-s', '--showclkfrq', help='Show supported GPU and Memory Clock', action='store_true')
    groupDisplay.add_argument('-a' ,'--showallinfo', help='Show Temperature, Fan and Clock values', action='store_true')

    groupAction.add_argument('-r', '--resetclocks', help='Reset clocks to default values', action='store_true')
    groupAction.add_argument('--setsclk', help='Set GPU Clock Frequency Level(s)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setmclk', help='Set GPU Memory Clock Frequency Level(s)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--resetfans', help='Reset fans to automatic (driver) control', action='store_true')
    groupAction.add_argument('--setfan', help='Set GPU Fan Speed Level', metavar='LEVEL')
    groupAction.add_argument('--setperflevel', help='Set PowerPlay Performance Level', metavar='LEVEL')
    groupAction.add_argument('--setoverdrive', help='Set GPU OverDrive level', metavar='%')
    groupAction.add_argument('--setprofile', help='Specify Compute Profile attributes', metavar='#', nargs=NUM_PROFILE_ARGS)
    groupAction.add_argument('--resetprofile', help='Reset Compute Profile', action='store_true')

    groupFile.add_argument('--load', help='Load Clock, Fan, Performance and Profile settings from FILE', metavar='FILE')
    groupFile.add_argument('--save', help='Save Clock, Fan, Performance and Profile settings to FILE', metavar='FILE')

    groupResponse.add_argument('--autorespond', help='Response to automatically provide for all prompts (NOT RECOMMENDED)', metavar='RESPONSE')

    args = parser.parse_args()

    # If there is a single device specified, use that for all commands, otherwise use a
    # list of all available devices. Also use "is not None" as device 0 would
    # have args.device=0, and "if 0" returns false.
    if args.device is not None:
        device = parseDeviceNumber(args.device)
        if not doesDeviceExist(device):
            print('No such device ' + device)
            sys.exit()
        deviceList = [device]
    else:
        deviceList = listDevices()

    if args.showallinfo:
        args.showid = True
        args.showtemp = True
        args.showclocks = True
        args.showfan = True
        args.list = True
        args.showclkfrq = True
        args.showperflevel = True
        args.showoverdrive = True
        args.showprofile = True
        args.showpower = True

    if args.setsclk or args.setmclk or args.resetfans or args.setfan or args.setperflevel or args.resetclocks or args.load or \
       args.setoverdrive or args.setprofile or args.resetprofile or args.showpower or len(sys.argv) == 1:
           relaunchAsSudo()

    # Header for the SMI
    print('\n\n', headerSpacer, '    ROCm System Management Interface    ', headerSpacer, sep='')

    if len(sys.argv) == 1:
        showAllConcise(deviceList)
    if args.showid:
        showId(deviceList)
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
        showOverDrive(deviceList)
    if args.showprofile:
        showProfile(deviceList)
    if args.showpower:
        showPower(deviceList)
    if args.showclkfrq:
        showClocks(deviceList)
    if args.setsclk:
        setClocks(deviceList, 'gpu', args.setsclk)
    if args.setmclk:
        setClocks(deviceList, 'mem', args.setmclk)
    if args.resetfans:
        resetFans(deviceList)
    if args.setfan:
        setFanSpeed(deviceList, args.setfan)
    if args.setperflevel:
        setPerformanceLevel(deviceList, args.setperflevel)
    if args.setoverdrive:
        setClockOverDrive(deviceList, 'gpu', args.setoverdrive, args.autorespond)
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
    print(headerSpacer, '           End of ROCm SMI Log          ', headerSpacer, '\n', sep='')
    sys.exit(RETCODE)

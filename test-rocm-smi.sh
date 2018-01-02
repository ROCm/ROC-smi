#!/bin/bash

# This script will test that all functionality from the SMI is working properly.
# Each SMI function requires its own corresponding test function. Any failing tests
# will increment $NUM_FAILURES. Once all tests are complete, the test script will
# return 0 if $NUM_FAILURES = 0, or 1 otherwise. This test must be run before
# submitting any modifications to the SMI to ensure that all SMI functionality works.

SMI_DIR="$(pwd)"
SMI_SUBSET="all"
SMI_NAME="rocm-smi" # Name of the SMI application
DRM_PREFIX="/sys/class/drm"
HWMON_PREFIX="/sys/class/hwmon"
NUM_FAILURES=0

printUsage() {
    echo
    echo "Usage: $(basename $0) [options ...]"
    echo
    echo 'Options:'
    echo '  -p <path>    , --path <path>         Specify folder containing SMI'
    echo '  -s "flag(s)" , --subset "flag(s)"    Specify subset of SMI flags to test (must be in quotes)'
    echo '  -h           , --help                Prints this help'
    echo
    echo ' Example usage for subtest:'
    echo
    echo './test-rocm-smi.sh -s "--showclkfrq"'
    echo './test-rocm-smi.sh -s "-f -t -q"'

    return 0
}

# Get the corresponding HW Monitor for the specified GPU device $device
#  param device     Card number to obtain the corresponding HW Monitor
getHwmonFromDevice() {
    device="$1"; shift;
    local monitor=""
    local hwmons="$(ls $HWMON_PREFIX)"
    for hwmon in $hwmons; do
        if [ -e "$HWMON_PREFIX/$hwmon/name" ]; then
            local hwmonDevPath="$(readlink -f $HWMON_PREFIX/$hwmon/device)"
            local drmDevPath="$(readlink -f $DRM_PREFIX/card$device/device)"
            if [ "$hwmonDevPath" == "$drmDevPath" ]; then
                monitor="$hwmon"
                break
            fi
        fi
    done
    echo "$monitor"
}

# Set up the test environment by resetting all settings to default
setupTestEnv() {
    local smiPath="$1"; shift
    $($smiPath --resetclocks) &> /dev/null
    sleep 1
}

# Parse the line from the SMI output to remove the GPU prefix
# Each line is of the form "GPU[X] \t\t: $ATTRIBUTE: $VALUE", so we return $VALUE
#  param rocmLine       Line from the SMI log to parse
extractRocmValue() {
    local rocmLine="$1"; shift;
    local value="${rocmLine##*: }" # Remove the 'GPU[X] \t: [Attribute]:' prefix
    echo "$(echo $value | sed 's/ *$//')" # Remove any trailing whitespace
}

# Extract value from JSON file (modified from https://gist.github.com/cjus/1047794)
#  param device         Specific device for JSON value extraction
#  param jsonFile       Path to the JSON file to format
#  param field          Field to extract from the JSON file
extractJsonValue() {
    local device="$1"; shift;
    local jsonFile="$1"; shift;
    local field="$1"; shift;

    local value=""

    local json="$(cat $jsonFile)"
    # Remove everything before and after the desired device values (indicated with ||)
    # {card$device: |{values...}|, card$device+1: {values...}...})
    json="${json##*card$device}"
    json="${json%%card*}"

    value="$(echo "$json" | sed 's/\\\\\//\//g' | sed 's/[{}]//g' |\
        awk -v k="text" '{n=split($0,a,","); for (i=1; i<=n; i++) print a[i]}' |\
        sed 's/\"\:\"/\|/g' | sed 's/[\,]/ /g' | sed 's/\"//g' | grep -w $field |\
        awk -F ": " '{print $NF}')"
    echo "$value"
}

# Check the string to see if it starts with the SMI information prefix 'GPU[x]'
checkLogLine() {
    local rocmLine="$1"; shift;
    if [[ ! "$rocmLine" =~ ^"GPU[" ]]; then
        echo "false"
    else
        echo "true"
    fi
}

# Parse the line from the SMI output to determine the GPU number
#  param rocmLine       Line from the SMI log to parse
getGpuFromRocm() {
    local rocmLine="$1"; shift;
    local gpuPrefix="${rocmLine%%]*}" # Strip all information after 'GPU[X'
    echo "${gpuPrefix:4}" # Strip the 'GPU[' prefix
}

# Manually echo the value to the specified sysfs file
echoSysFs() {
    local sysfsPath="$1"; shift;
    local value="$1"; shift;
    echo "$value" | sudo tee $sysfsPath > /dev/null
}

# Return the number of clock levels in a specified clock file
#  param clockFile      Path to clock file
getNumLevels() {
    local clockFile="$1"; shift
    local numClockLevels="$(wc -l $clockFile)"
    numClockLevels="${numClockLevels%% *}" # Remove filename from wc output
    echo "$numClockLevels"
}

# Get current clock level for a specified clock file
#  param type           [freq|level] Type of clock to return
#  param clockFile      Path to clock file
getCurrentClock() {
    local type="$1"; shift;
    local clockFile="$1"; shift;
    local value=""
    clocks="$(cat $clockFile)"
    for line in $clocks; do
        if [ "${line: -1:1}" == "*" ]; then
            if [ "$type" == "level" ]; then
                value=${line%%:*}
            else
                value=${line##*: }
                value=${value:0:-2}
            fi
            break
        fi
    done
    echo "$value"
}

# Test that the GPU ID reported by the SMI matches the GPU ID for the
# corresponding device(s)
#  param smiPath        Path to the SMI
testGetId() {
    local smiPath="$1"; shift;
    local smiCmd="-i"
    echo -e "\nTesting $smiPath $smiCmd..."
    local ids="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $ids; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmId="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"

        local sysId="$(cat $HWMON_PREFIX/$hwmon/device/device)"
        if [ "$rocmId" != "$sysId" ]; then
            echo "FAILURE: ID from $SMI_NAME $rocmId does not match $sysId"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the temperature reported by the SMI matches the temperature for the
# corresponding device(s)
# by the HW Monitor
#  param smiPath        Path to the SMI
testGetTemp() {
    local smiPath="$1"; shift;
    local smiCmd="-t"
    echo -e "\nTesting $smiPath $smiCmd..."
    local temps="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $temps; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmTemp="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"

        local rocmTemp="${rocmTemp%%.*}" # Truncate the value, as bash rounds to the nearest int
        local sysTemp="$(cat $HWMON_PREFIX/$hwmon/temp1_input)" # Temp in millidegrees
        if [ "$sysTemp" != "" ]; then
            sysTemp=$(($sysTemp/1000)) # Convert to degrees
        fi
        if [ "$rocmTemp" != "$sysTemp" ]; then
            echo "FAILURE: Temperature from $SMI_NAME $rocmTemp does not match $sysTemp"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the current clock frequency reported by the SMI matches the current clock
# frequency speed of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetCurrentClocks() {
    local smiPath="$1"; shift;
    local smiCmd="-c"
    local clockType="GPU"
    echo -e "\nTesting $smiPath $smiCmd..."
    clocks="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        elif [[ "$line" == *"WARNING"* ]]; then
            continue
        fi
        local rocmClock="$(extractRocmValue $line)"
        rocmClock="${rocmClock##*(}"
        rocmClock="${rocmClock:0:-1}"
        local rocmGpu="$(getGpuFromRocm $line)"
        if [[ "$line" == *"GPU Memory"* ]]; then
            clockFile="$DRM_PREFIX/card$rocmGpu/device/pp_dpm_mclk"
            clockType="GPU Memory"
        else
            clockFile="$DRM_PREFIX/card$rocmGpu/device/pp_dpm_sclk"
        fi
        local sysClock="$(getCurrentClock freq $clockFile)"
        if [ "$rocmClock" == "None" ]; then
            echo "WARNING: Unable to test empty value for $clockType"
            continue
        fi
        if [ "$rocmClock" != "$sysClock" ]; then
            echo "FAILURE: $clockType clock frequency from $SMI_NAME $rocmClock does not match $sysClock"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the supported clocks reported by the SMI match the supported clocks of the
# corresponding device(s)
# Specifically, check that every entry in the SMI output matches an entry in the
# supported clock list, and that the number of supported clocks are equal.
#  param smiPath        Path to the SMI
testGetSupportedClocks() {
    local smiPath="$1"; shift;
    local smiCmd="-s"

    echo -e "\nTesting $smiPath $smiCmd..."
    devices="$(ls /sys/class/drm/card*/device/pp_dpm_sclk)"
    numDevices="$(echo $devices | wc -w)"
    for device in $devices; do
        local clockType="gpu"
        local numGpuMatches=0
        local numMemMatches=0
        local deviceNum="${devices##*/card}"
        deviceNum="${deviceNum%%/device*}"
        local gpuClockFile="$DRM_PREFIX/card$deviceNum/device/pp_dpm_sclk"
        local memClockFile="$DRM_PREFIX/card$deviceNum/device/pp_dpm_mclk"
        local clocks="$($smiPath $smiCmd -d $deviceNum)"
        IFS=$'\n'
        for rocmLine in $clocks; do
            if [ "$(checkLogLine $rocmLine)" != "true" ]; then
                continue
            fi
            if [[ "$rocmLine" == *"Supported GPU Memory clock"* ]]; then
                clockType="mem"
                continue
            fi
            if [[ ! "$rocmLine" == *"Mhz"* ]]; then # Ignore invalid lines
                continue
            fi
            rocmClock="$(extractRocmValue $rocmLine)"
            local rocmGpu="$(getGpuFromRocm $rocmLine)"
            local clockFile="$gpuClockFile"
            if [ "$clockType" == "mem" ]; then
                clockFile="$memClockFile"
            fi
            local sysClocks="$(cat $clockFile)"

            for clockLine in $sysClocks; do
                if [[ "$clockLine" == *"$rocmClock"* ]]; then
                    if [ "$clockType" == "gpu" ]; then
                        numGpuMatches=$((numGpuMatches+1))
                        break
                    else
                        numMemMatches=$((numMemMatches+1))
                        break
                    fi
                    break
                fi
            done
        done
        if [ "$numGpuMatches" != "$(getNumLevels $gpuClockFile)" ]; then
            echo "FAILURE: Supported GPU clock frequencies from $SMI_NAME do not match sysfs values"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
        if [ "$numMemMatches" != "$(getNumLevels $memClockFile)" ]; then
            echo "FAILURE: Supported GPU Memory clock frequencies from $SMI_NAME do not match sysfs values"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the current fan speed reported by the SMI matches the current fan speed of
# the corresponding device(s)
#  param smiPath        Path to the SMI
testGetFan() {
    local smiPath="$1"; shift;
    local smiCmd="-f"
    echo -e "\nTesting $smiPath $smiCmd..."
    local fans="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $fans; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"Unable to determine"* ]]; then
            continue
        fi
        local rocmFan="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local rocmFanLevel="${rocmFan%% \(*}"
        local rocmFanPct="${rocmFan##*(}"
        rocmFanPct="${rocmFanPct%%.*}" # Truncate fan percent decimals

        local sysFan="$(cat "$HWMON_PREFIX/$hwmon/pwm1")" # Fan speed level (not percentage)
        local sysFanMax="$(cat "$HWMON_PREFIX/$hwmon/pwm1_max")" # Maximum fan speed
        local sysFanPct=$((100*$sysFan/$sysFanMax))

        if [ "$sysFan" != "$rocmFanLevel" ]; then
            echo "FAILURE: GPU fan level from $SMI_NAME $rocmFanLevel does not match $sysFan"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$rocmFanPct" != "$sysFanPct" ]; then
            echo "FAILURE: GPU fan percentage from $SMI_NAME $rocmFanPct does not match $sysFanPct"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the current Performance Level reported by the SMI matches the current
# Performance Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetPerf() {
    local smiPath="$1"; shift;
    local smiCmd="-p"
    echo -e "\nTesting $smiPath $smiCmd..."
    local perfs="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmPerf="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"

        local sysPerf="$(cat $DRM_PREFIX/card$rocmGpu/device/power_dpm_force_performance_level)"
        if [ "$sysPerf" != "$rocmPerf" ]; then
            echo "FAILURE: Performance level from $SMI_NAME $rocmPerf does not match $sysPerf"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the current OverDrive Level reported by the SMI matches the current
# OverDrive Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiCmd="-o"
    echo -e "\nTesting $smiPath $smiCmd..."
    local perfs="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmOd="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"

        local sysOd="$(cat $DRM_PREFIX/card$rocmGpu/device/pp_sclk_od)%"
        if [ "$sysOd" != "$rocmOd" ]; then
            echo "FAILURE: OverDrive level from $SMI_NAME $rocmOd does not match $sysOd"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the fan speed through the SMI changes the current fan speed of the
# corresponding device(s)
#  param smiPath        Path to the SMI
testSetFan() {
    local smiPath="$1"; shift;
    local smiCmd="--setfan"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    # Get a list of current GPU clock frequencies. Since some GPUs can report but not
    # modify the fan speed, use ones that we can control.
    local clocks="$($smiPath -g)"
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"

        local currSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        local sysFanMin="$(cat $HWMON_PREFIX/$hwmon/pwm1_min)" # Minimum fan speed
        local sysFanMax="$(cat $HWMON_PREFIX/$hwmon/pwm1_max)" # Maximum fan speed
        local newFanValue="$sysFanMax"

        local fan="$($smiPath $smiCmd $sysFanMin)"
        local newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        if [ "$newSysFan" != "$sysFanMin" ]; then
            echo "FAILURE: Could not set fan to minimum value $sysFanMin"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        fan="$($smiPath $smiCmd $sysFanMax)"
        newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        if [ "$newSysFan" != "$sysFanMax" ]; then
            echo "FAILURE: Could not set fan to maximum value $sysFanMax"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        # Restore the original fan settings
        fan="$($smiPath $smiCmd $currSysFan)"
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the Performance Level through the SMI changes the current
# Performance Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testSetPerf() {
    local smiPath="$1"; shift;
    local smiCmd="--setperflevel"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local perfs=$($smiPath "-p") # Get a list of current Performance Levels
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local levelPath="$DRM_PREFIX/card$rocmGpu/device/power_dpm_force_performance_level"

        local currPerfLevel="$(cat $levelPath)" # Performance level
        local newPerfLevel="low"
        if [ "$currPerfLevel" == "low" ]; then
            local newPerfValue="high"
        fi

        local perf="$($smiPath $smiCmd $newPerfLevel)"
        local newSysPerf="$(cat $levelPath)"
        if [ "$newSysPerf" != "$newPerfLevel" ]; then
            echo "FAILURE: Could not set Performance Level to $newPerfLevel"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        # Restore the original Performance Level
        perf="$($smiPath $smiCmd $currPerfLevel)"
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the GPU and GPU Memory clock frequencies through the SMI changes
# the clock frequencies of the corresponding device(s)
#  param smiPath        Path to the SMI
testSetClock() {
    local clock="$1"; shift;
    local smiPath="$1"; shift;
    local smiCmd="--setsclk"
    local clockType="GPU"
    if [ "$clock" == "mem" ]; then
        local smiCmd="--setmclk"
    fi
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local clocks="$($smiPath -c)" # Get the SMI clock output
    for rocmLine in $clocks; do
        if [ "$(checkLogLine $rocmLine)" != "true" ]; then
            continue
        elif [[ "$rocmLine" == *"PowerPlay not enabled"* ]]; then
            continue
        fi

        local rocmGpu="$(getGpuFromRocm $rocmLine)"
        if [[ "$rocmLine" == *"GPU Memory"* ]]; then
            if [ "$clock" == "gpu" ]; then # If we are testing sclk, skip the mclk lines
                continue
            fi
            clockFile="$DRM_PREFIX/card$rocmGpu/device/pp_dpm_mclk"
            clockType="GPU Memory"
        else
            if [ "$clock" == "mem" ]; then # If we are testing mclk, skip the sclk lines
                continue
            fi
            clockFile="$DRM_PREFIX/card$rocmGpu/device/pp_dpm_sclk"
        fi

        local oldClockLevel="$(getCurrentClock freq $clockFile)"
        local newClockLevel="0"
        if [ "$oldClockLevel" == "0" ]; then
            if [ "$(getNumLevels $clockFile)" -gt "1" ]; then
                newClockLevel=1
            fi
        fi
        set="$($smiPath $smiCmd $newClockLevel)"
        local newSysClocks="$(cat $clockFile)"
        currClockLevel="$(getCurrentClock freq $clockFile)"
        if [ "$currClockLevel" == "$newClockLevel" ]; then
            echo "FAILURE: Could not set $clockType level to $newClockLevel"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the OverDrive Level through the SMI changes the current
# OverDrive Level of the corresponding device(s), and sets the current GPU Clock level
# to level 7 to use this new value
#  param smiPath        Path to the SMI
testSetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiCmd="--setoverdrive"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local clocks=$($smiPath "-g") # Get a list of current GPU clock frequencies
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local odPath="$DRM_PREFIX/card$rocmGpu/device/pp_sclk_od"

        local currOd="$(cat $odPath)" # OverDrive level
        local newOd="3"
        if [ "$currOd" == "3" ]; then
            local newOd="6"
        fi

        local od="$($smiPath $smiCmd $newOd --autorespond YES)"
        local newSysOd="$(cat $odPath)"
        if [ "$newSysOd" != "$newOd" ]; then
            echo "FAILURE: Could not set OverDrive Level"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that setting the Power Profile through the SMI applies the desired profile,
# but only when Performance Level is set to auto
testSetProfile() {
    local smiPath="$1"; shift;
    local smiCmd="--setprofile"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local clocks=$($smiPath "-g") # Get a list of current GPU clock frequencies
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local perf="$($smiPath --setperflevel auto)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local profilePath="$DRM_PREFIX/card$rocmGpu/device/pp_compute_power_profile"

        local currProfile="$(cat $profilePath)"
        local newProfile=(750 500 1 2 3)
        if [ "$currProfile" == "750 500 1 2 3" ]; then
            local newProfile=(800 500 2 3 4)
        fi

        local profile=$($smiPath $smiCmd ${newProfile[@]})
        local newSysProfile="$(cat $profilePath)"
        if [ "$newSysProfile" != "$(echo ${newProfile[@]})" ]; then
            echo "FAILURE: Could not set Profile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
            continue
        fi
        local currClock="$(getCurrentClock level $DRM_PREFIX/card$rocmGpu/device/pp_dpm_sclk)"
        sleep 1
        if [ "$currClock" == "3" ]; then
            local setClock="$($smiPath --setsclk 4)"
        else
            local setClock="$($smiPath --setsclk 3)"
        fi
        sleep 1
        local newClock="$(getCurrentClock level $DRM_PREFIX/card$rocmGpu/device/pp_dpm_sclk)"
        if [ "$currClock" == "$newClock" ]; then
            echo "FAILURE: Profile not overridden with Performance Level set to manual"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that resetting the profile actually resets the profile
testResetProfile() {
    local smiPath="$1"; shift;
    local smiCmd="--resetprofile"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local clocks=$($smiPath "-g") # Get a list of current GPU clock frequencies
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local perf="$($smiPath --setperflevel auto)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local profilePath="$DRM_PREFIX/card$rocmGpu/device/pp_compute_power_profile"

        local newProfile=(750 500 1 2 3)

        local resetProfile=$($smiPath $smiCmd)
        local resetSysProfile="$(cat $profilePath)"
        local setProfile=$($smiPath --setprofile ${newProfile[@]})
        local setSysProfile="$(cat $profilePath)"

        if [ "$resetSysProfile" == "$setSysProfile" ]; then
            echo "FAILURE: Could not set Profile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
            continue
        fi
        resetProfile="$($smiPath $smiCmd)"
        resetSysProfile="$(cat $profilePath)"
        if [ "$resetSysProfile" == "$setSysProfile" ]; then
            echo "FAILURE: Could not reset profile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}


# Test that the resetting the GPU and GPU Memory clock frequencies through the SMI
# resets the clock frequencies of the corresponding device(s)
#  param smiPath        Path to the SMI
testReset() {
    local smiPath="$1"; shift;
    local smiCmd="-r"
    echo -e "\nTesting $smiPath $smiCmd..."
    IFS=$'\n'
    local perfs="$($smiPath -p)" # Get a list of current Performance Levels
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local levelPath="$DRM_PREFIX/card$rocmGpu/device/power_dpm_force_performance_level"

        local currPerfLevel="$(cat $levelPath)" # Performance level
        if [ "$currPerfLevel" == "auto" ]; then
            echoSysFs "manual" "$levelPath"
        fi
        reset="$($smiPath $smiCmd)"
        local newPerfLevel=$(cat "$levelPath") # Performance level
        if [ "$newPerfLevel" != "auto" ]; then
            echo "FAILURE: Could not reset clocks"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that saving the current clock and fan settings creates a save file that
# reflects the system settings for the corresponding device(s)
#  param smiPath        Path to the SMI
testSave() {
    local smiPath="$1"; shift;
    local smiCmd="--save"
    setupTestEnv "$smiPath" # Make sure that we have a clean state before saving values
    IFS=$'\n'
    echo -e "\nTesting $smiPath $smiCmd..."

    local tempSaveDir="$(mktemp -d)"
    local tempSaveFile="$tempSaveDir/clocks.tmp"

    save="$($smiPath $smiCmd $tempSaveFile)"
    if [ ! -f $tempSaveFile ]; then
        echo "FAILURE: Save file not created"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ ! -s $tempSaveFile ]; then
        echo "FAILURE: Clock savefile is empty"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi

    local clocks="$($smiPath -g)" # Get a list of current GPU clock frequencies
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local device="$(getGpuFromRocm "$line")"
        local hwmon="$(getHwmonFromDevice $device)"
        local fan="$(extractJsonValue "$device" "$tempSaveFile" "fan")"
        local gpu="$(extractJsonValue "$device" "$tempSaveFile" "gpu")"
        local mem="$(extractJsonValue "$device" "$tempSaveFile" "mem")"
        local od="$(extractJsonValue "$device" "$tempSaveFile" "overdrivegpu")"
        local profile="$(extractJsonValue "$device" "$tempSaveFile" "profile")"
        local perf="$(extractJsonValue "$device" "$tempSaveFile" "perflevel")"
        local sysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)"
        local sysGpu="$(cat $DRM_PREFIX/card$device/device/pp_dpm_sclk)"
        local sysMem="$(cat $DRM_PREFIX/card$device/device/pp_dpm_mclk)"
        local sysOd="$(cat $DRM_PREFIX/card$device/device/pp_sclk_od)"
        local sysProfile="$(cat $DRM_PREFIX/card$device/device/pp_compute_power_profile)"
        local sysPerf="$(cat $DRM_PREFIX/card$device/device/power_dpm_force_performance_level)"
        if [ "$fan" != "$sysFan" ]; then
            echo "FAILURE: Saved fan $fan does not match current fan setting $sysFan"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$gpu" != "${sysGpu:0:1}" ]; then
            echo "FAILURE: Saved GPU frequency $gpu does not match current GPU clock ${sysGpu:0:1}"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$gpu" != "${sysMem:0:1}" ]; then
            echo "FAILURE: Saved GPU Memory frequency $mem does not match current GPU Memory clock ${sysMem:0:1}"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$od" != "$sysOd" ]; then
            echo "FAILURE: Saved OverDrive $od does not match current fan setting $sysOd"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$profile" != "$sysProfile" ]; then
            echo "FAILURE: Saved Profile $profile does not match current fan setting $sysProfile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$perf" != "$sysPerf" ]; then
            echo "FAILURE: Saved Performance Level $perf does not match current Performance Level $sysPerf"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    rm -f $tempSaveFile
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that loading clock and fan settings from a save file correctly changes the
# current clock and fan settings for the corresponding device(s)
#  param smiPath        Path to the SMI
testLoad() {
    local smiPath="$1"; shift;
    local smiCmd="--load"
    IFS=$'\n'
    echo -e "\nTesting $smiPath $smiCmd..."

    local tempSaveDir="$(mktemp -d)"
    local tempSaveFile="$tempSaveDir/clocks.tmp"

    local clocks="$($smiPath -g)" # Get a list of current GPU clock speeds
    local od="$($smiPath --setoverdrive 8 --autorespond YES)"
    local high="$($smiPath --setperflevel high)"
    local profile="$($smiPath --setprofile 1000 500 0 2 4)"
    sleep 1 # Give the system 1sec to ramp the clocks up to high
    local save="$($smiPath --save $tempSaveFile)"
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local reset="$($smiPath --setperflevel auto)"
        reset="$($smiPath --resetprofile)"
        local device="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $device)"
        local perfPath="$DRM_PREFIX/card$device/device/power_dpm_force_performance_level"
        local gpuPath="$DRM_PREFIX/card$device/device/pp_dpm_sclk"
        local memPath="$DRM_PREFIX/card$device/device/pp_dpm_mclk"
        local odPath="$DRM_PREFIX/card$device/device/pp_sclk_od"
        local profilePath="$DRM_PREFIX/card$device/device/pp_compute_power_profile"
        local oldOd="$(cat $odPath)"
        local oldGpuClock="$(getCurrentClock level $gpuPath)"
        local oldMemClock="$(getCurrentClock level $memPath)"
        local oldProfile="$(cat $profilePath)"
        local load="$($smiPath $smiCmd $tempSaveFile --autorespond YES)"
        sleep 1 # Give the system 1sec to ramp the clocks up to the desired values
        local newGpuClock="$(getCurrentClock level $gpuPath)"
        local newMemClock="$(getCurrentClock level $memPath)"
        local newOd="$(cat $odPath)"
        local newProfile="$(cat $profilePath)"
        local newPerf="$(cat $perfPath)"
        local jsonGpu="$(extractJsonValue $device $tempSaveFile gpu)"
        local jsonMem="$(extractJsonValue $device $tempSaveFile mem)"
        local jsonOd="$(extractJsonValue $device $tempSaveFile overdrivegpu)"
        local jsonProfile="$(extractJsonValue $device $tempSaveFile profile)"
        local jsonPerf="$(extractJsonValue $device $tempSaveFile perflevel)"
        if [ "$oldGpuClock" == "$newGpuClock" ]; then
            if [ "$(getNumLevels $gpuPath)" -gt "1" ]; then
                echo "FAILURE: Failed to change GPU clocks when loading values from save file $tempSaveFile"
                NUM_FAILURES=$(($NUM_FAILURES+1))
            fi
        elif [ "$oldMemClock" == "$newMemClock" ]; then
            if [ "$(getNumLevels $memPath)" -gt "1" ]; then
                echo "FAILURE: Failed to change GPU Memory clocks when loading values from save file $tempSaveFile"
                NUM_FAILURES=$(($NUM_FAILURES+1))
            fi
        elif [ "$oldOd" == "$newOd" ]; then
            echo "FAILURE: Failed to change GPU OverDrive when loading values from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
        if [ "$newGpuClock" != "$jsonGpu" ]; then
            echo "FAILURE: Failed to load GPU clock values from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$newMemClock" != "$jsonMem" ]; then
            echo "FAILURE: Failed to load GPU Memory clock values from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$newOd" != "$jsonOd" ]; then
            echo "FAILURE: Failed to load OverDrive values from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$newProfile" != "$jsonProfile" ]; then
            echo "FAILURE: Failed to load Profile values from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$newPerf" != "$jsonPerf" ]; then
            echo "FAILURE: Failed to load Performance Level value from save file $tempSaveFile"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    rm -f $tempSaveFile
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

runTestSuite() {
    local smiPath="$1"; shift;
    local subsetList="$1"; shift;
    setupTestEnv "$smiPath"

    for subset in $subsetList; do
        case $subset in
            -i | --id)
                testGetId "$smiPath" ;;
            -t | --temp)
                testGetTemp "$smiPath" ;;
            -c | --showclocks)
                testGetCurrentClocks "$smiPath" ;;
            -f | --showfan)
                testGetFan "$smiPath" ;;
            -p | --showperf)
                testGetPerf "$smiPath" ;;
            -o | --showoverdrive)
                testGetGpuOverDrive "$smiPath" ;;
            -s | --showclkfrq)
                testGetSupportedClocks "$smiPath" ;;
            -r | --resetclocks)
                testReset "$smiPath" ;;
            --setsclk)
                testSetClock "gpu" "$smiPath" ;;
            --setmclk)
                testSetClock "mem" "$smiPath" ;;
            --setfan)
                testSetFan "$smiPath" ;;
            --setperflevel)
                testSetPerf "$smiPath" ;;
            --setoverdrive)
                testSetGpuOverDrive "$smiPath" ;;
            --setprofile)
                testSetProfile "$smiPath" ;;
            --resetprofile)
                testResetProfile "$smiPath" ;;
            --save)
                testSave "$smiPath" ;;
            --load)
                testLoad "$smiPath" ;;
            all)
                testGetId "$smiPath" ;
                testGetTemp "$smiPath" ;
                testGetCurrentClocks "$smiPath" ;
                testGetFan "$smiPath" ;
                testGetPerf "$smiPath" ;
                testGetSupportedClocks "$smiPath" ;
                testGetGpuOverDrive "$smiPath" ;
                testSetFan "$smiPath" ;
                testSetClock "gpu" "$smiPath" ;
                testSetClock "mem" "$smiPath" ;
                testReset "$smiPath" ;
                testSetPerf "$smiPath" ;
                testSetGpuOverDrive "$smiPath" ;
                testSetProfile "$smiPath" ;
                testResetProfile "$smiPath" ;
                testSave "$smiPath" ;
                testLoad "$smiPath" ;
                break
                ;;
            *)
                echo "Unsupported option $subset . Exiting" ; exit 1 ;;
        esac
    done
}

while [ "$1" != "" ]; do
    case "$1" in
        -p  | --path )
            SMI_DIR="$2"; shift ;;
        -s  | --subtest )
            SMI_SUBSET="$2" ; shift ;;
        -h  | --help )
            printUsage; exit 0 ;;
        *)
            printUsage; exit 1 ;;
    esac
    shift 1
done

if [ ! -e "$SMI_DIR/$SMI_NAME" ]; then
    print "Unable to locate SMI at $SMI_DIR/$SMI_NAME."
    exit 1
fi

echo "===Start of ROCM-SMI test suite==="
runTestSuite "$SMI_DIR/$SMI_NAME" "$SMI_SUBSET"
echo "$NUM_FAILURES failure(s) occurred"
echo "===End of ROCM-SMI test suite==="

# Reset the system to get it back to a sane state
reset="$($SMI_DIR/$SMI_NAME -r && $SMI_DIR/$SMI_NAME --resetprofile)"

exit $NUM_FAILURES

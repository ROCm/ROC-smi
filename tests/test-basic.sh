#!/bin/bash

# Test that the GPU ID reported by the SMI matches the GPU ID for the
# corresponding device(s)
#  param smiPath        Path to the SMI
testGetId() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-i"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local ids="$($smiPath $smiDev $smiCmd)"
    IFS=$'\n'
    for line in $ids; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmId="$(extractRocmValue $line)"
        local hwmon="$(getHwmonFromDevice ${smiDev:3})"

        local sysId="$(cat $HWMON_PREFIX/$hwmon/device/device)"
        if [ "$rocmId" != "$sysId" ]; then
            echo "FAILURE: ID from $SMI_NAME $rocmId does not match $sysId"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the temperature reported by the SMI matches the temperature for the
# corresponding device(s)
# by the HW Monitor
#  param smiPath        Path to the SMI
testGetTemp() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-t"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local temps="$($smiPath $smiDev $smiCmd)"
    IFS=$'\n'
    for line in $temps; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmTemp="$(extractRocmValue $line)"
        local hwmon="$(getHwmonFromDevice ${smiDev:3})"

        rocmTemp="${rocmTemp%'c'}"
        rocmTemp="${rocmTemp%%.*}" # Truncate the value, as bash rounds to the nearest int
        local sysTemp="$(cat $HWMON_PREFIX/$hwmon/temp1_input)" # Temp in millidegrees
        if [ "$sysTemp" != "" ]; then
            sysTemp=$(($sysTemp/1000)) # Convert to degrees
        fi
        if [ "$rocmTemp" != "$sysTemp" ]; then
            echo "FAILURE: Temperature from $SMI_NAME $rocmTemp does not match $sysTemp"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that saving the current clock and fan settings creates a save file that
# reflects the system settings for the corresponding device(s)
#  param smiPath        Path to the SMI
testSave() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--save"
    setupTestEnv "$smiPath" # Make sure that we have a clean state before saving values
    IFS=$'\n'
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    local tempSaveDir="$(mktemp -d)"
    local tempSaveFile="$tempSaveDir/clocks.tmp"
    # Set the fan to something high to ensure that it doesn't end up ramping it up automatically
    local setFanHigh=$($smiPath $smiDev --setfan 90%)

    save="$($smiPath $smiDev $smiCmd $tempSaveFile)"
    if [ ! -f $tempSaveFile ]; then
        echo "FAILURE: Save file not created"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ ! -s $tempSaveFile ]; then
        echo "FAILURE: Clock savefile is empty"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi

    local device="${smiDev:3}"
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
    local sysProfile="$(grep -m 1 '\*' /sys/class/drm/card$device/device/pp_power_profile_mode)"
    sysProfile="${sysProfile:2:1}"
    local sysPerf="$(cat $DRM_PREFIX/card$device/device/power_dpm_force_performance_level)"
    if [ "$fan" != "$sysFan" ]; then
        if ! isApu; then
            echo "FAILURE: Saved fan $fan does not match current fan setting $sysFan"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    elif [ "$gpu" != "${sysGpu:0:1}" ]; then
        echo "FAILURE: Saved GPU frequency $gpu does not match current GPU clock ${sysGpu:0:1}"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ "$gpu" != "${sysMem:0:1}" ]; then
        echo "FAILURE: Saved GPU Memory frequency $mem does not match current GPU Memory clock ${sysMem:0:1}"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ "$od" != "$sysOd" ]; then
        echo "FAILURE: Saved OverDrive $od does not match current OverDrive setting $sysOd"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ "$profile" != "$sysProfile" ]; then
        echo "FAILURE: Saved Profile $profile does not match current Profile setting $sysProfile"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    elif [ "$perf" != "$sysPerf" ]; then
        echo "FAILURE: Saved Performance Level $perf does not match current Performance Level $sysPerf"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    rm -f $tempSaveFile
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that loading clock and fan settings from a save file correctly changes the
# current clock and fan settings for the corresponding device(s)
#  param smiPath        Path to the SMI
testLoad() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--load"
    IFS=$'\n'
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    local tempSaveDir="$(mktemp -d)"
    local tempSaveFile="$tempSaveDir/clocks.tmp"

    local od="$($smiPath $smiDev --setoverdrive 8 --autorespond YES)"
    local high="$($smiPath $smiDev --setperflevel high)"
    local profile="$($smiPath $smiDev --setprofile 4)"
    sleep 1 # Give the system 1sec to ramp the clocks up to high
    local save="$($smiPath $smiDev --save $tempSaveFile)"
    local reset="$($smiPath $smiDev --setperflevel auto)"
    reset="$($smiPath $smiDev --resetprofile)"
    local device="${smiDev:3}"
    local perfPath="$DRM_PREFIX/card$device/device/power_dpm_force_performance_level"
    local gpuPath="$DRM_PREFIX/card$device/device/pp_dpm_sclk"
    local memPath="$DRM_PREFIX/card$device/device/pp_dpm_mclk"
    local odPath="$DRM_PREFIX/card$device/device/pp_sclk_od"
    local profilePath="$DRM_PREFIX/card$device/device/pp_power_profile_mode"
    local oldOd="$(cat $odPath)"
    local oldGpuClock="$(getCurrentClock level $gpuPath)"
    local oldMemClock="$(getCurrentClock level $memPath)"
    local oldProfile="$(grep -m 1 '\*' /sys/class/drm/card$device/device/pp_power_profile_mode)"
    oldProfile="${sysProfile:2:1}"
    local load="$($smiPath $smiDev $smiCmd $tempSaveFile --autorespond YES)"
    sleep 1 # Give the system 1sec to ramp the clocks up to the desired values
    local newGpuClock="$(getCurrentClock level $gpuPath)"
    local newMemClock="$(getCurrentClock level $memPath)"
    local newOd="$(cat $odPath)"
    local newProfile="$(grep -m 1 '\*' /sys/class/drm/card$device/device/pp_power_profile_mode)"
    newProfile="${newProfile:2:1}"
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
    #TODO: Fix this since it currently fails
    #elif [ "$oldMemClock" == "$newMemClock" ]; then
    #    if [ "$(getNumLevels $memPath)" -gt "1" ]; then
    #        echo "FAILURE: Failed to change GPU Memory clocks when loading values from save file $tempSaveFile"
    #        NUM_FAILURES=$(($NUM_FAILURES+1))
    #    fi
    #elif [ "$oldOd" == "$newOd" ]; then
    #    echo "FAILURE: Failed to change GPU OverDrive when loading values from save file $tempSaveFile"
    #    NUM_FAILURES=$(($NUM_FAILURES+1))
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
    rm -f $tempSaveFile
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

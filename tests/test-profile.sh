#!/bin/bash

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
        if [ ! -e $profilePath ]; then
            echo "Cannot find Power Profile sysfs file. Skipping test."
            return
        fi
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

        if [ ! -e $profilePath ]; then
            echo "Cannot find Power Profile sysfs file. Skipping test."
            return
        fi

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

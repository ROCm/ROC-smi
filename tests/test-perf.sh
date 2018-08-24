#!/bin/bash

# Test that the current Performance Level reported by the SMI matches the current
# Performance Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetPerf() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-p"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local perfs="$($smiPath $smiDev $smiCmd)"
    IFS=$'\n'
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmPerf="$(extractRocmValue $line)"

        local sysPerf="$(cat $DRM_PREFIX/card${smiDev:3}/device/power_dpm_force_performance_level)"
        if [ "$sysPerf" != "$rocmPerf" ]; then
            echo "FAILURE: Performance level from $SMI_NAME $rocmPerf does not match $sysPerf"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the setting the Performance Level through the SMI changes the current
# Performance Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testSetPerf() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--setperflevel"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    IFS=$'\n'
    local perfs=$($smiPath "-p") # Get a list of current Performance Levels
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"DPM not available"* ]]; then
            continue
        fi
        local levelPath="$DRM_PREFIX/card${smiDev:3}/device/power_dpm_force_performance_level"

        local currPerfLevel="$(cat $levelPath)" # Performance level
        local newPerfLevel="low"
        if [ "$currPerfLevel" == "low" ]; then
            local newPerfValue="high"
        fi

        local perf="$($smiPath $smiDev $smiCmd $newPerfLevel)"
        local newSysPerf="$(cat $levelPath)"
        if [ "$newSysPerf" != "$newPerfLevel" ]; then
            echo "FAILURE: Could not set Performance Level to $newPerfLevel"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        # Restore the original Performance Level
        perf="$($smiPath $smiDev $smiCmd $currPerfLevel)"
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

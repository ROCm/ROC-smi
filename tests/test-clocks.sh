#!/bin/bash

# Test that the current clock frequency reported by the SMI matches the current clock
# frequency speed of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetCurrentClocks() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-c"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local clocks="$($smiPath $smiDev $smiCmd)"
    local sysClock=""
    while read -r line; do
        if [[ "$line" == *"GPU Clock Level"* ]]; then
            name="GPU clock"
            sysClock="$(getCurrentClock freq $DRM_PREFIX/card${smiDev:3}/device/pp_dpm_sclk)"
        elif [[ "$line" == *"GPU Memory"* ]]; then
            name="GPU Memory clock"
            sysClock="$(getCurrentClock freq $DRM_PREFIX/card${smiDev:3}/device/pp_dpm_mclk)"
        elif [[ "$line" == *"PCIE"* ]]; then
	    if [[ "$line" == *"None"* ]]; then
	        continue
	    fi
            name="PCIE"
            sysClock="$(getCurrentClock freq $DRM_PREFIX/card${smiDev:3}/device/pp_dpm_pcie)"
        else
            continue
        fi
        local rocmClock="$(extractRocmValue $line)"
        rocmClock="${line##*(}"
        rocmClock="${rocmClock:0:-1}"
        if [ "$sysClock" != "$rocmClock" ]; then
            echo "FAILURE: $name frequency from $SMI_NAME $rocmClock does not match $sysClock"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done <<< "$clocks"
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the supported clocks reported by the SMI match the supported clocks of the
# corresponding device(s)
# Specifically, check that every entry in the SMI output matches an entry in the
# supported clock list, and that the number of supported clocks are equal.
#  param smiPath        Path to the SMI
testGetSupportedClocks() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-s"

    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local clockType="gpu"
    local numGpuMatches=0
    local numMemMatches=0
    local numPciMatches=0
    local gpuClockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_sclk"
    local memClockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_mclk"
    local pciClockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_pcie"
    local clocks="$($smiPath $smiDev $smiCmd $smiDev)"
    IFS=$'\n'
    for rocmLine in $clocks; do
        if [ "$(checkLogLine $rocmLine)" != "true" ]; then
            continue
        fi
        if [[ "$rocmLine" == *"Supported GPU Memory clock"* ]]; then
            clockType="mem"
            continue
        elif [[ "$rocmLine" == *"PCIE"* ]]; then
            clockType="pcie"
            continue
        fi
        if [ "$clockType" == "mem" ] || [ "$clockType" == "gpu" ]; then
            if [[ ! "$rocmLine" == *"Mhz"* ]]; then # Ignore invalid lines
                continue
            fi
        elif [ "$clockType" == "pcie" ]; then
            if [[ ! "$rocmLine" == *"GT"* ]]; then # Ignore invalid lines
                continue
            fi
        fi
        local rocmClock="$(extractRocmValue $rocmLine)"
        local clockFile="$gpuClockFile"
        if [ "$clockType" == "mem" ]; then
            clockFile="$memClockFile"
        elif [ "$clockType" == "pcie" ]; then
            clockFile="$pciClockFile"
        fi
        local sysClocks="$(cat $clockFile)"

        for clockLine in $sysClocks; do
            if [[ "$clockLine" == *"$rocmClock"* ]]; then
                if [ "$clockType" == "gpu" ]; then
                    numGpuMatches=$((numGpuMatches+1))
                    break
                elif [ "$clockType" == "mem" ]; then
                    numMemMatches=$((numMemMatches+1))
                    break
                else
                    numPciMatches=$((numPciMatches+1))
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
    if [ "$numPciMatches" != "$(getNumLevels $pciClockFile)" ]; then
        echo "FAILURE: Supported PCIE clock frequencies from $SMI_NAME do not match sysfs values"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the setting the GPU and GPU Memory clock frequencies through the SMI changes
# the clock frequencies of the corresponding device(s)
#  param smiPath        Path to the SMI
testSetClock() {
    local clock="$1"; shift;
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--setsclk"
    local clockType="GPU"
    if [ "$clock" == "mem" ]; then
        local smiCmd="--setmclk"
    fi
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    IFS=$'\n'
    local clocks="$($smiPath -c)" # Get the SMI clock output
    for rocmLine in $clocks; do
        if [ "$(checkLogLine $rocmLine)" != "true" ]; then
            continue
        elif [[ "$rocmLine" == *"DPM not available"* ]]; then
            continue
        fi

        if [[ "$rocmLine" == *"GPU Memory"* ]]; then
            if [ ! "$clock" == "mem" ]; then
                continue
            fi
            clockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_mclk"
            clockType="GPU Memory"
        elif [[ "$rocmLine" == "PCIE" ]]; then
            if [ ! "$clock" == "pcie" ]; then
                continue
            fi
            clockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_pcie"
        else
            if [ ! "$clock" == "gpu" ]; then
                continue
            fi
            clockFile="$DRM_PREFIX/card${smiDev:3}/device/pp_dpm_sclk"
        fi

        local oldClockLevel="$(getCurrentClock freq $clockFile)"
        local newClockLevel="0"
        if [ "$oldClockLevel" == "0" ]; then
            if [ "$(getNumLevels $clockFile)" -gt "1" ]; then
                newClockLevel=1
            fi
        fi
        set="$($smiPath $smiDev $smiCmd $newClockLevel)"
        local newSysClocks="$(cat $clockFile)"
        currClockLevel="$(getCurrentClock freq $clockFile)"
        if [ "$currClockLevel" == "$newClockLevel" ]; then
            echo "FAILURE: Could not set $clockType level to $newClockLevel"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the resetting the GPU and GPU Memory clock frequencies through the SMI
# resets the clock frequencies of the corresponding device(s)
#  param smiPath        Path to the SMI
testReset() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-r"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    IFS=$'\n'
    local perfs="$($smiPath -p)" # Get a list of current Performance Levels
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"DPM not available"* ]]; then
            continue
        fi
        local levelPath="$DRM_PREFIX/card${smiDev:3}/device/power_dpm_force_performance_level"

        local currPerfLevel="$(cat $levelPath)" # Performance level
        if [ "$currPerfLevel" == "auto" ]; then
            echo "manual" | sudo tee "$levelPath" > /dev/null
        fi
        reset="$($smiPath $smiDev $smiCmd)"
        local newPerfLevel=$(cat "$levelPath") # Performance level
        if [ "$newPerfLevel" != "auto" ]; then
            echo "FAILURE: Could not reset clocks"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

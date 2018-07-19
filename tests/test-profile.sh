#!/bin/bash

# The new Power Profile needs some parsing
getCurrentProfile() {
    local cardNum="$1"
    if [ ! -e /sys/class/drm/card$cardNum/device/pp_power_profile_mode ]; then
        echo ""
    fi
    local currProfile="$(grep -m 1 '\*' /sys/class/drm/card$cardNum/device/pp_power_profile_mode)"
    # Strip away the name of the profile, replace - with 0, and remove extra spaces
    currProfile=$(echo ${currProfile#*:} | sed 's/ \+/ /g ; s/-/0/g')
    echo "${currProfile:1}"
}

getCustomProfile() {
    local cardNum="$1"
    local customProfile="$(grep -m 1 "CUSTOM" /sys/class/drm/card$cardNum/device/pp_power_profile_mode)"
    customProfile=$(echo ${customProfile#*:} | sed 's/ \+/ /g ; s/-/0/g')
    echo "${customProfile:1}"
}

getPowerProfileLevel() {
    local cardNum="$1"
    local currProfile="$(grep -m 1 '\*' /sys/class/drm/card$cardNum/device/pp_power_profile_mode)"
    # Will need to parse differently if we ever have more than 10 profiles
    echo "${currProfile:2:1}"
}

# Test that setting the Power Profile through the SMI applies the desired profile,
# but only when Performance Level is set to auto
testSetProfile() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--setprofile"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local perf="$($smiPath $smiDev --setperflevel manual)"
    local profilePath="$DRM_PREFIX/card${smiDev:3}/device/pp_power_profile_mode"
    if [ ! -e $profilePath ]; then
        echo "Cannot find Power Profile sysfs file $profilePath. Skipping test."
        return
    fi

    #TODO: Figure out how to test setting profiles for different ASICs
    echo "Testing Set Profile currently disabled"
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that resetting the profile actually resets the profile
testResetProfile() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--resetprofile"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    if [ -z "$(cat /sys/class/drm/card${smiDev:3}/device/pp_power_profile_mode)" ]; then
        echo "Power Profile not supported. Exiting"
        return
    fi

    #TODO: Change it to the CUSTOM profile and set some values there to ensure
    # that the CUSTOM profile gets reset as well as the Profile level
    local setLevel="2"
    local currLevel="$(getPowerProfileLevel ${smiDev:3})"
    if [ "$currLevel" == "$setLevel" ]; then
        setLevel="3"
    fi
    local setProfile="$($smiPath --setprofile $setLevel)"
    local oldLevel="$(getPowerProfileLevel ${smiDev:3})"
    if [ "$oldLevel" != "$setLevel" ]; then
        echo "FAILURE: Could not set Profile; $oldLevel $setLevel"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    local resetProfile=$($smiPath --setprofile 0)
    local newLevel="$(getPowerProfileLevel ${smiDev:3})"
    if [[ "$newLevel" != "0" ]]; then
        echo "FAILURE: Could not reset profile"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    local customProfile="$(getCustomProfile ${smiDev:3})"
    if [ -n "$(echo $customProfile | grep -v 0)" ]; then
        echo "FAILURE: Did not reset Custom Power Profile"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi

    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

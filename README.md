### ROCm System Management Interface

This repository includes the rocm-smi tool. This tool exposes functionality for
clock and temperature management of your ROCm enabled system.

#### Installation

You may find rocm-smi at the following location after installing the rocm package:
```shell
/opt/rocm/bin/rocm-smi
```

Alternatively, you may clone this repository and run the tool directly.

#### Usage

For detailed and up to date usage information, we recommend consulting the help:
```shell
/opt/rocm/bin/rocm-smi -h
```

For convenience purposes, following is a quick excerpt:
```shell

usage: rocm-smi [-h] [-d DEVICE] [-i] [-t] [-c] [-g] [-f] [-p] [-P] [-o] [-l] [-s] [-a] [-r]
                [--setsclk LEVEL [LEVEL ...]] [--setmclk LEVEL [LEVEL ...]] [--setfan LEVEL]
                [--setperflevel LEVEL] [--setoverdrive %] [--setprofile # # # # #] [--resetprofile]
                [--load FILE | --save FILE] [--autorespond RESPONSE]

AMD ROCm System Management Interface

optional arguments:
  -h, --help                  show this help message and exit
  --load FILE                 Load Clock, Fan, Performance and Profile settings from FILE
  --save FILE                 Save Clock, Fan, Performance and Profile settings to FILE

  -d DEVICE, --device DEVICE  Execute command on specified device

  -i, --showid                Show GPU ID
  -t, --showtemp              Show current temperature
  -c, --showclocks            Show current clock frequencies
  -g, --showgpuclocks         Show current GPU clock frequencies
  -f, --showfan               Show current fan speed
  -p, --showperflevel         Show current PowerPlay Performance Level
  -P, --showpower             Show current power consumption
  -o, --showoverdrive         Show current OverDrive level
  -l, --showprofile           Show Compute Profile attributes
  -s, --showclkfrq            Show supported GPU and Memory Clock
  -a, --showallinfo           Show all SMI-supported values values

  -r, --resetclocks           Reset clocks to default (auto)
  --setsclk LEVEL [LEVEL ...] Set GPU Clock Frequency Level Mask (manual)
  --setmclk LEVEL [LEVEL ...] Set GPU Memory Clock Frequency Mask (manual)
  --setfan LEVEL              Set GPU Fan Speed Level
  --setperflevel LEVEL        Set PowerPlay Performance Level
  --setoverdrive %            Set GPU OverDrive level (manual|high)
  --setprofile # # # # #      Specify Compute Profile attributes (auto)
  --resetprofile              Reset Compute Profile

  --autorespond RESPONSE      Response to automatically provide for all prompts (NOT RECOMMENDED)
```


#### Detailed Option Descriptions

--setsclk/--setmclk # [# # ...]:
    This allows you to set a mask for the levels. For example, if a GPU has 8 clock levels,
    you can set a mask to use levels 0, 5, 6 and 7 with --setsclk 0 5 6 7 . This will only
    use the base level, and the top 3 clock levels. This will allow you to keep the GPU at
    base level when there is no GPU load, and the top 3 levels when the GPU load increases.

    NOTES:
        The clock levels will change dynamically based on GPU load based on the default
        Compute and Graphics profiles. The thresholds and delays for a custom mask cannot
        be controlled through the SMI tool

        This flag automatically sets the Performance Level to "manual" as the mask is not
        applied when the Performance level is set to auto

--setfan LEVEL:
    This sets the fan speed to a value ranging from 0 to 255 (not from 0-100%).

    NOTE: While the hardware is usually capable of overriding this value when required, it is
          recommended to not set the fan level lower than the default value for extended periods
          of time

--setperflevel LEVEL:
    This lets you use the pre-defined Performance Level values, which can include:
        auto (Automatically change PowerPlay values based on GPU workload)
        low (Keep PowerPlay values low, regardless of workload)
        high (Keep PowerPlay values high, regardless of workload)
        manual (Only use values defined by --setsclk and --setmclk)

--setoverdrive #:
    This sets the percentage above maximum for the max Performance Level.
    For example, --setoverdrive 20 will increase the top sclk level by 20%. If the maximum
    sclk level is 1000MHz, then --setoverdrive 20 will increase the maximum sclk to 1200MHz

    NOTES:
        This option can be used in conjunction with the --setsclk mask

        Operating the GPU outside of specifications can cause irreparable damage to your hardware
        Please observe the warning displayed when using this option

        This flag automatically sets the sclk to the highest level, as only the highest level is
        increased by the OverDrive value

--setprofile # # # # #:
    The Compute Profile accepts 5 parameters, which are (in order):
        Minimum SCLK       - Minimum GPU clock speed in MHz
        Minimum MCLK       - Minimum GPU Memory clock speed in MHz
        Activity threshold - Workload required before clock levels change (%)
        Hysteresis Up      - Delay before clock level is increased in milliseconds
        Hysteresis Down    - Delay before clock level is decresed in milliseconds

    NOTES:
        When a compute queue is detected, these values will be automatically applied to the system

        Compute Power Profiles are only applied when the Performance Level is set to "auto"


#### Testing changes

After making changes to the SMI, run the test script to ensure that all functionality
remains intact before uploading the patch. This can be done using:
```shell
./test-rocm-smi.sh /opt/rocm/bin/rocm-smi
```

The test can run all flags for the SMI, or specific flags can be tested with the -s option.

Any new functionality added to the SMI should have a corresponding test added to the test script.

#### Disclaimer

The information contained herein is for informational purposes only, and is subject to change without notice. While every precaution has been taken in the preparation of this document, it may contain technical inaccuracies, omissions and typographical errors, and AMD is under no obligation to update or otherwise correct this information. Advanced Micro Devices, Inc. makes no representations or warranties with respect to the accuracy or completeness of the contents of this document, and assumes no liability of any kind, including the implied warranties of noninfringement, merchantability or fitness for particular purposes, with respect to the operation or use of AMD hardware, software or other products described herein. No license, including implied or arising by estoppel, to any intellectual property rights is granted by this document. Terms and limitations applicable to the purchase or use of AMD's products are as set forth in a signed agreement between the parties or in AMD's Standard Terms and Conditions of Sale.

AMD, the AMD Arrow logo, and combinations thereof are trademarks of Advanced Micro Devices, Inc. Other product names used in this publication are for identification purposes only and may be trademarks of their respective companies.

Copyright (c) 2014-2017 Advanced Micro Devices, Inc. All rights reserved.

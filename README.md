### ROC System Management Interface

This repository includes the roc-smi tool. This tool exposes functionality for
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

usage: rocm-smi [-h] [-d DEVICE] [-i] [-t] [-c] [-g] [-f] [-p] [-o] [-l] [-s] [-a] [-r] [--setsclk LEVEL]
                [--setmclk LEVEL] [--setfan LEVEL] [--setperflevel LEVEL] [--setoverdrive %]
                [--setprofile # # # # #] [--resetprofile] [--load FILE | --save FILE] [--autorespond RESPONSE]

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
  -o, --showoverdrive         Show current OverDrive level
  -l, --showprofile           Show Compute Profile attributes
  -s, --showclkfrq            Show supported GPU and Memory Clock
  -a, --showallinfo           Show Temperature, Fan and Clock values

  -r, --resetclocks           Reset clocks to default values
  --setsclk LEVEL             Set GPU Clock Frequency Level(s)
  --setmclk LEVEL             Set GPU Memory Clock Frequency Level(s)
  --setfan LEVEL              Set GPU Fan Speed Level
  --setperflevel LEVEL        Set PowerPlay Performance Level
  --setoverdrive %            Set GPU OverDrive level
  --setprofile # # # # #      Specify Compute Profile attributes
  --resetprofile              Reset Compute Profile

  --autorespond RESPONSE      Response to automatically provide for all prompts (NOT RECOMMENDED)
```

#### Testing changes

After making changes to the SMI, run the test script to ensure that all functionality
remains intact before uploading the patch. This can be done using:
```shell
./test-rocm-smi.sh/opt/rocm/bin/rocm-smi
```

The test can run all flags for the SMI, or specific flags can be tested with the -s option.

Any new functionality added to the SMI should have a corresponding test added to the test script.

#### Disclaimer

The information contained herein is for informational purposes only, and is subject to change without notice. While every precaution has been taken in the preparation of this document, it may contain technical inaccuracies, omissions and typographical errors, and AMD is under no obligation to update or otherwise correct this information. Advanced Micro Devices, Inc. makes no representations or warranties with respect to the accuracy or completeness of the contents of this document, and assumes no liability of any kind, including the implied warranties of noninfringement, merchantability or fitness for particular purposes, with respect to the operation or use of AMD hardware, software or other products described herein. No license, including implied or arising by estoppel, to any intellectual property rights is granted by this document. Terms and limitations applicable to the purchase or use of AMD's products are as set forth in a signed agreement between the parties or in AMD's Standard Terms and Conditions of Sale.

AMD, the AMD Arrow logo, and combinations thereof are trademarks of Advanced Micro Devices, Inc. Other product names used in this publication are for identification purposes only and may be trademarks of their respective companies.

Copyright (c) 2014-2016 Advanced Micro Devices, Inc. All rights reserved.

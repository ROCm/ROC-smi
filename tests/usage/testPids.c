/*
 * Copyright (C) 2019 Advanced Micro Devices, Inc. All Rights Reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
 * OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
 * ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 *
 */

#define DEFAULT_PIDS 8
#define DEFAULT_DELAY 1
#define DEFAULT_RUNTIME 30

#include <stdio.h>
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include "hsakmt.h"

void printUsage(char *name) {
	printf("USAGE: %s PIDS SEC_DELAY RUNTIME\n\n", name);
	printf("PIDS = Order of processes to spawn as 2^PIDS (DEFAULT=%d)\n", DEFAULT_PIDS);
	printf("SEC_DELAY = Seconds to delay before doubling the number of processes (DEFAULT=%d)\n", DEFAULT_DELAY);
	printf("RUNTIME = Seconds to wait after all processes have spawned before terminating (DEFAULT=%d)\n", DEFAULT_RUNTIME);
}

int main(int argc, char **argv) {
	int pids = DEFAULT_PIDS;
	int sdelay = DEFAULT_DELAY;
	int sruntime = DEFAULT_RUNTIME;
	int nChildren = 0;
	int x = 0;

	if (argc == 1) {
		pids = DEFAULT_PIDS;
		sdelay = DEFAULT_DELAY;
		sruntime = DEFAULT_RUNTIME;
	} else if (argc == 2) {
		if ((strcmp(argv[1], "-h") == 0) || (strcmp(argv[1], "--help") == 0)) {
			printUsage(argv[0]);
			return 0;
		} else {
			printUsage(argv[0]);
			return -1;
		}
	} else if (argc == 4) {
		if (!atoi(argv[1]) || !atoi(argv[2]) || !atoi(argv[3])) {
			printUsage(argv[0]);
			return -1;
		}
		pids = atoi(argv[1]);
		sdelay = atoi(argv[2]);
		sruntime = atoi(argv[3]);
	} else {
		printUsage(argv[0]);
		return -1;
	}
	hsaKmtOpenKFD();
	// Each fork will double the number of active processes
	for (x = 0; x < pids; x++) {
		pid_t childPid;

		sleep(sdelay);
		childPid = fork();
		if (childPid == 0) {
			// If it's a new child process, open a new KFD process
			nChildren = 0;
			hsaKmtOpenKFD();
		} else if (childPid > 0) {
			// If it's a parent, increment the children counter
			nChildren++;
		}
	}
	sleep(sruntime);
	for (x = 0; x < nChildren; x++)
		wait(NULL);
	return 0;
}

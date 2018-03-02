# Our directory
SMI_ROOT ?= $(abspath ./)

ifdef O
  BUILD_ROOT := $(O)
else
  BUILD_ROOT := $(SMI_ROOT)/build
endif
BUILD_ROOT := $(abspath $(BUILD_ROOT))
BUILDDIR = $(BUILD_ROOT)/$(MAKECMDGOALS)
PACKAGE_DIR = $(BUILD_ROOT)/rocm-smi
DEBIAN_DIR = $(SMI_ROOT)/DEBIAN
SMI_LOCATION = $(PACKAGE_DIR)/opt/rocm/bin
MODULE_VERSION = $(shell cd ${SMI_ROOT} && git describe --long --dirty --match [0-9]*)

export SMI_ROOT
export MODULE_VERSION

package-common:
	@mkdir -p $(BUILDDIR)

deb: package-common
	@mkdir -p $(PACKAGE_DIR)/DEBIAN
	@mkdir -p $(SMI_LOCATION)
	@sed 's/^Version: MODULE_VERSION/Version: $(MODULE_VERSION)/' $(DEBIAN_DIR)/control > $(PACKAGE_DIR)/DEBIAN/control
	@cp $(SMI_ROOT)/rocm_smi.py $(SMI_LOCATION)
	@ln -srf $(SMI_LOCATION)/rocm_smi.py $(SMI_LOCATION)/rocm-smi
	@fakeroot dpkg-deb --build $(PACKAGE_DIR) \
		$(BUILDDIR)/rocm-smi-$(MODULE_VERSION)-Linux.deb
	@rm -rf $(PACKAGE_DIR)

rpm: package-common
	@rpmbuild --define '_topdir $(BUILD_ROOT)/rpm' -ba $(SMI_ROOT)/RPM/rocm-smi.spec
	@mv $(BUILD_ROOT)/rpm/RPMS/*/*.rpm $(BUILD_ROOT)/rpm

clean:
	rm -rf $(BUILD_ROOT)

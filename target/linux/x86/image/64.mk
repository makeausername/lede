define Device/generic
  DEVICE_VENDOR := Generic
  DEVICE_MODEL := x86/64
  DEVICE_PACKAGES += kmod-amazon-ena kmod-amd-xgbe kmod-bnx2 \
	kmod-e1000e kmod-e1000 kmod-forcedeth kmod-fs-vfat \
	kmod-igb kmod-igc kmod-ixgbe kmod-r8168 kmod-tg3
  GRUB2_VARIANT := generic
endef
TARGET_DEVICES += generic

# Dedicated GPT/FAT image also embeds BIOS GRUB for the audited legacy boot.
define Device/paiq_j1900
  DEVICE_VENDOR := PAIQ
  DEVICE_MODEL := EC3-BT19D4L (J1900)
  DEVICE_PACKAGES := kmod-igb kmod-fs-vfat intel-microcode irqbalance
  SUPPORTED_DEVICES := paiq-ec3-bt19d4l
  GRUB2_VARIANT := generic
endef
TARGET_DEVICES += paiq_j1900

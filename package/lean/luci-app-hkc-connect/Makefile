include $(TOPDIR)/rules.mk

LUCI_TITLE:=HKC Connect simplified router client
LUCI_PKGARCH:=all
PKG_VERSION:=1.0.0
PKG_RELEASE:=1

LUCI_DEPENDS:=+luci-compat +luci-app-ssr-plus +curl +ca-bundle

define Package/luci-app-hkc-connect/conffiles
/etc/config/hkc_connect
/etc/hkc-connect/
endef

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature

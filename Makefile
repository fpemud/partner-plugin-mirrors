PACKAGE_VERSION=0.0.1
prefix=/usr

all:

install:
	install -d -m 0755 "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d"
	cp -r reflex/* "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d"

.PHONY: all install

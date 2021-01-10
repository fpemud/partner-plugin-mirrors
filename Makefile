PACKAGE_VERSION=0.0.1
prefix=/usr
reflex=mirrors

all:

clean:
	fixme

install:
	install -d -m 0755 "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d"
	cp -r $(reflex) "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d"
	find "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d/$(reflex)" -type f | xargs chmod 644
	find "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d/$(reflex)" -type d | xargs chmod 755

uninstall:
	rm -rf "$(DESTDIR)/$(prefix)/lib/partner/system-reflex.d/$(reflex)"

.PHONY: all clean install uninstall
